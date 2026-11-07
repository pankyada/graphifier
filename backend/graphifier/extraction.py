"""Conservative, dependency-free static lineage extraction for small source files.

This module intentionally recognizes a bounded set of common syntax. It does not
execute code, expand macros, resolve imports, or claim complete lineage.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any
from .languages import language_for, SOURCE_SUFFIXES, MANIFESTS


def _id(path: str, kind: str, name: str, expression: str = "", scope: str = "") -> str:
    raw = "\0".join((path, kind, name, expression, scope))
    return f"{kind}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def extract_file(path: str, content: str) -> dict:
    """Extract likely datasets, columns, transformations, models, and symbols.

    IDs are stable for a given path and source expression. Evidence line numbers
    are one-based and inclusive. Results are static hints, not an execution graph.
    """
    suffix = Path(path).suffix.lower()
    result: dict[str, list] = {"entities": [], "relationships": [], "symbols": [], "warnings": [], "gaps": []}
    entities: dict[str, dict] = {}
    relationships: dict[tuple, dict] = {}
    symbols: dict[tuple, dict] = {}
    warning_set: set[str] = set()

    def evidence(start: int, end: int | None = None) -> dict:
        return {"file": path, "start_line": max(1, start), "end_line": max(1, end or start)}

    def entity(kind: str, name: str, line: int, *, expression: str | None = None,
               attributes: dict | None = None, end: int | None = None, scope: str = "") -> str:
        key_expr = expression or ""
        eid = _id(path, kind, name, key_expr, scope)
        if eid not in entities:
            item: dict[str, Any] = {"id": eid, "kind": kind, "name": name,
                                    "attributes": attributes or {}, "evidence": evidence(line, end)}
            if expression is not None:
                item["expression"] = expression
            entities[eid] = item
        elif attributes:
            entities[eid]["attributes"].update(attributes)
        return eid

    def relation(source: str, target: str, kind: str, line: int, *, attributes: dict | None = None,
                 end: int | None = None) -> None:
        key = (source, target, kind)
        if key not in relationships:
            item = {"source": source, "target": target, "kind": kind, "evidence": evidence(line, end)}
            if attributes:
                item["attributes"] = attributes
            relationships[key] = item

    def symbol(name: str, expression: str, line: int, default: str | None = None) -> None:
        key = (name, expression)
        if key not in symbols:
            item = {"name": name, "expression": expression, "evidence": evidence(line)}
            if default is not None:
                item["default_value"] = default
            symbols[key] = item

    def warn(message: str) -> None:
        warning_set.add(message)

    def gap(kind: str, message: str, expression: str, line: int, end: int | None = None,
            candidates: list[str] | None = None) -> None:
        warn(message)
        item = {"id": _id(path, "gap", kind, expression, f"{line}:{message}"), "kind": kind,
                "message": message, "expression": expression, "evidence": evidence(line, end),
                "candidates": [{"id": candidate, "kind": entities[candidate]["kind"],
                                "name": entities[candidate]["name"]}
                               for candidate in dict.fromkeys(candidates or []) if candidate in entities]}
        if not any(existing["id"] == item["id"] for existing in result["gaps"]):
            result["gaps"].append(item)

    file_id = entity("file", path, 1, attributes={"language": language_for(path)})
    program_id = entity("program", Path(path).name or path, 1, attributes={"path": path})

    relation(file_id, program_id, "CONTAINS", 1)
    entry_patterns = [r'if\s+__name__\s*==\s*[\"\']__main__', r'\b(?:public\s+static\s+void|func|fn)\s+main\s*\(', r'\b(?:app|server)\.listen\s*\(']
    for pattern in entry_patterns:
        match = re.search(pattern, content)
        if match:
            entities[program_id]["attributes"].update({"entrypoint": True, "entrypoint_line": content[:match.start()].count("\n") + 1, "interface": True})
            break

    def dataset(name: str, line: int, *, expression: str | None = None, role: str | None = None) -> str:
        clean = name.strip().strip("`\"'")
        if not clean:
            clean = expression or "<dynamic>"
        attrs = {"source_path": path}
        if role == "in-memory dataframe":
            attrs["transient"] = True
        if suffix == ".sas" and clean.lower().startswith("work."):
            attrs["transient"] = True
        if role:
            attrs["observed_role"] = role
        return entity("dataset", clean, line, expression=expression, attributes=attrs)

    def column(name: str, line: int, parent_dataset_id: str, *, expression: str | None = None) -> str:
        return entity("column", name, line, expression=expression,
                      attributes={"source_path": path, "parent_dataset_id": parent_dataset_id},
                      scope=parent_dataset_id)

    def transform(name: str, text: str, line: int, inputs: list[str], outputs: list[str], *,
                  attrs: dict | None = None, end: int | None = None) -> str:
        tid = entity("transformation", name, line, expression=text.strip(),
                     attributes={"explanation": name, **(attrs or {})}, end=end)
        for ds in dict.fromkeys(inputs):
            relation(program_id, ds, "READS", line, end=end)
            relation(ds, tid, "INPUT_TO", line, end=end)
        for ds in dict.fromkeys(outputs):
            relation(program_id, ds, "WRITES", line, end=end)
            relation(tid, ds, "PRODUCES", line, end=end)
            relation(tid, ds, "WRITES", line, end=end)
        return tid

    def add_columns(ds_id: str, names: list[str], line: int) -> None:
        for name in dict.fromkeys(n.strip().strip("'\"`") for n in names if n.strip()):
            cid = column(name, line, ds_id)
            relation(ds_id, cid, "HAS_COLUMN", line)

    def sql_tables(statement: str) -> tuple[list[str], list[str]]:
        reads = re.findall(r"\b(?:FROM|JOIN)\s+([\w.$&{}'-]+)", statement, re.I)
        writes = re.findall(r"\b(?:CREATE\s+(?:OR\s+REPLACE\s+)?TABLE|INSERT\s+INTO|MERGE\s+INTO)\s+([\w.$&{}'-]+)", statement, re.I)
        return reads, writes

    def extract_sql(statement: str, line: int, context: str = "SQL query", end_line: int | None = None) -> None:
        reads, writes = sql_tables(statement)
        for token in re.findall(r"\$\{([A-Za-z_]\w*)\}|&([A-Za-z_]\w*)", statement):
            name = next(x for x in token if x)
            symbol(name, "${" + name + "}" if "${" + name + "}" in statement else "&" + name, line)
        ins = [dataset(n, line, expression=n if any(c in n for c in "$&{}") else None) for n in reads]
        outs = [dataset(n, line, expression=n if any(c in n for c in "$&{}") else None) for n in writes]
        if reads or writes:
            t = transform(context, statement, line, ins, outs, attrs={"language": "sql"}, end=end_line)
            for inp in ins:
                for out in outs:
                    relation(inp, out, "DERIVES_FROM", line, attributes={"via": t}, end=end_line)
        elif re.search(r"\b(select|with)\b", statement, re.I):
            warn(f"line {line}: SQL query has no statically recognized table source or destination")
        # Conservative single SELECT scope. Nested scopes require a dialect parser.
        if len(re.findall(r"\bSELECT\b", statement, re.I)) > 1 or re.search(r"\b(?:WITH|UNION)\b", statement, re.I):
            gap("nested_query", f"line {line}: nested/compound SQL column scope is unresolved", statement, line, end_line, ins + outs)
            return
        if not reads and not writes:
            return
        aliases = {}
        keywords = {"where", "join", "left", "right", "inner", "outer", "full", "cross", "on", "group", "order", "having", "limit"}
        for match in re.finditer(r"\b(?:FROM|JOIN)\s+([\w.$&{}]+)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?", statement, re.I):
            name, alias = match.groups()
            parent = dataset(name, line, expression=name if any(c in name for c in "$&{}") else None)
            aliases[name.lower()] = parent
            aliases[name.split(".")[-1].lower()] = parent
            if alias and alias.lower() not in keywords:
                aliases[alias.lower()] = parent

        def references(expression, role, target):
            scrubbed = re.sub(r"'(?:''|[^'])*'", " ", expression)
            functions = {m.group(1).lower() for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", scrubbed)}
            reserved = keywords | functions | {"as", "distinct", "case", "when", "then", "else", "end", "null", "true", "false", "and", "or", "not", "is", "in", "like", "between", "asc", "desc", "cast", "decimal", "varchar", "date", "integer"}
            found = []
            for match in re.finditer(r"(?<![\w$])([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)", scrubbed):
                token = match.group(1)
                if token.lower() in reserved:
                    continue
                parts = token.rsplit(".", 1)
                parent = aliases.get(parts[0].lower()) if len(parts) == 2 else (ins[0] if len(set(ins)) == 1 else None)
                if parent is None:
                    gap("ambiguous_column", f"line {line}: ambiguous or unresolved SQL column {token}", statement, line, end_line, ins)
                    continue
                cid = column(parts[-1], line, parent)
                relation(parent, cid, "HAS_COLUMN", line)
                relation(program_id, cid, "READS", line, attributes={"role": role})
                relation(cid, target, "INPUT_TO", line, attributes={"role": role}, end=end_line)
                found.append(cid)
            return found

        def projections(text):
            parts, start, depth, quoted = [], 0, 0, False
            for index, char in enumerate(text):
                if char == "'": quoted = not quoted
                if quoted: continue
                if char == "(": depth += 1
                elif char == ")": depth -= 1
                elif char == "," and depth == 0:
                    parts.append(text[start:index]); start = index + 1
            return parts + [text[start:]]

        declaration = re.match(r"\s*CREATE\s+TABLE\s+[\w.]+\s*\((.*)\)\s*;?\s*$", statement, re.I | re.S)
        if declaration and outs:
            offset = declaration.start(1)
            for definition in projections(declaration.group(1)):
                definition_start = statement.find(definition, offset)
                offset = definition_start + len(definition)
                name_match = re.match(r"\s*([A-Za-z_][\w$]*)\s+([A-Za-z_][\w$]*)", definition)
                if not name_match or name_match.group(1).lower() in {"constraint", "primary", "foreign", "unique", "check"}:
                    continue
                column_line = line + statement[:definition_start + name_match.start(1)].count("\n")
                declared = column(name_match.group(1), column_line, outs[0])
                entities[declared]["attributes"].update({"declared": True, "data_type": name_match.group(2)})
                relation(outs[0], declared, "HAS_COLUMN", column_line)

        select = re.search(r"\bSELECT\s+(.*?)(?:\s+FROM\b|;?\s*$)", statement, re.I | re.S)
        destination_columns = re.search(r"\bINSERT\s+INTO\s+[\w.]+\s*\(([^)]+)\)", statement, re.I)
        names = [n.strip() for n in destination_columns.group(1).split(",")] if destination_columns else []
        if select:
            for index, part in enumerate(projections(select.group(1))):
                part = re.sub(r"^\s*DISTINCT\s+", "", part, flags=re.I).strip()
                if re.fullmatch(r"(?:\w+\.)?\*", part):
                    gap("wildcard", f"line {line}: wildcard column expansion needs a schema", statement, line, end_line, ins)
                    continue
                alias = re.search(r"\s+AS\s+([\w$]+)\s*$", part, re.I)
                bare = re.fullmatch(r"(?:[\w$]+\.)?([\w$]+)", part)
                cname = names[index] if index < len(names) else alias.group(1) if alias else bare.group(1) if bare else None
                expression = part[:alias.start()].strip() if alias else part
                if not outs:
                    references(expression, "value", t)
                    continue
                if not cname:
                    warn(f"line {line}: SQL output expression requires an explicit alias")
                    continue
                cid = column(cname, line, outs[0], expression=expression)
                relation(outs[0], cid, "HAS_COLUMN", line)
                relation(program_id, cid, "WRITES", line)
                calc = entity("transformation", f"SQL column {cname}", line, expression=expression,
                              attributes={"output_column_id": cid, "language": "sql"}, end=end_line)
                for source in references(expression, "value", calc):
                    relation(source, cid, "DERIVES_FROM", line, attributes={"via": calc, "role": "value"})
                relation(calc, cid, "PRODUCES", line, attributes={"role": "value"})
        for match in re.finditer(r"\b(WHERE|ON|HAVING|GROUP\s+BY)\s+(.*?)(?=\b(?:WHERE|JOIN|LEFT|RIGHT|INNER|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b|;|$)", statement, re.I | re.S):
            role = "join" if match.group(1).upper() == "ON" else "grouping" if match.group(1).upper().startswith("GROUP") else "filter"
            references(match.group(2), role, t)

    if suffix in {".sas", ".sas7bdat"}:
        macro_defaults: dict[str, str] = {}
        for m in re.finditer(r"(?im)^\s*%let\s+(\w+)\s*=\s*(.*?);", content):
            lineno = content.count("\n", 0, m.start()) + 1
            macro_defaults[m.group(1)] = m.group(2).strip()
            symbol(m.group(1), f"&{m.group(1)}", lineno, m.group(2).strip())
        if re.search(r"&\w+", content):
            warn("SAS macro values are recorded symbolically; macro expansion and libref path resolution are not evaluated")
        for m in re.finditer(r"(?im)^\s*libname\s+(\w+)\s+([^;]+);", content):
            lineno = content.count("\n", 0, m.start()) + 1
            symbol(m.group(1), f"libname {m.group(1)}", lineno, m.group(2).strip())
        for lineno, line_text in enumerate(content.splitlines(), 1):
            for macro in re.finditer(r"&(\w+)\.?", line_text):
                symbol(macro.group(1), macro.group(0), lineno, macro_defaults.get(macro.group(1)))

        # PROC SQL blocks, including multiple statements on one physical line.
        sql_blocks = re.finditer(r"(?is)\bproc\s+sql\b(.*?)(?:\bquit\s*;|\Z)", content)
        consumed: set[int] = set()
        for block in sql_blocks:
            base_line = content.count("\n", 0, block.start()) + 1
            for stmt in re.finditer(r"[^;]+;", block.group(1)):
                text = stmt.group(0).strip()
                lineno = content.count("\n", 0, block.start(1) + stmt.start() + len(stmt.group(0)) - len(stmt.group(0).lstrip())) + 1
                consumed.update(range(lineno, lineno + text.count("\n") + 1))
                end_line = lineno + text.count("\n")
                extract_sql(text, lineno, "SAS PROC SQL statement", end_line)

        # DATA step: capture its declared target, SET/MERGE sources and simple assignments.
        for block in re.finditer(r"(?is)\bdata\s+([^;]+);(.*?)(?:\brun\s*;|\Z)", content):
            line_no = content.count("\n", 0, block.start()) + 1
            target_text, body = block.group(1).strip(), block.group(2)
            target_name = target_text.split()[0]
            out = dataset(target_name, line_no, expression=target_name if "&" in target_name else None)
            srcs: list[str] = []
            for sm in re.finditer(r"(?im)(?:^|(?<=;))\s*(?:set|merge|modify)\s+([^;]+);", body):
                line = content.count("\n", 0, block.start(2) + sm.start()) + 1
                for raw in re.split(r"\s+", re.sub(r"\([^)]*\)", "", sm.group(1)).strip()):
                    raw = raw.rstrip(";")
                    if raw and not raw.startswith("("):
                        srcs.append(dataset(raw, line, expression=raw if "&" in raw else None))
            assignments = []
            for am in re.finditer(r"(?im)(?:^|(?<=;))\s*([A-Za-z_][\w.]*)\s*=\s*([^;]+);", body):
                colname = am.group(1).split(".")[-1]
                line = content.count("\n", 0, block.start(2) + am.start() + len(am.group(0)) - len(am.group(0).lstrip())) + 1
                cid = column(colname, line, out, expression=am.group(2).strip())
                relation(out, cid, "HAS_COLUMN", line)
                assignments.append(f"{colname} = {am.group(2).strip()}")
                expression = am.group(2).strip()
                refs = [x for x in re.findall(r"\b[A-Za-z_]\w*\b", expression)
                        if x.lower() not in {"and", "or", "not", "then", "else", "if", "missing", "true", "false"}]
                if re.fullmatch(r"[\w.$+\-*/ ()]+", expression) and len(srcs) <= 1:
                    calc = entity("transformation", f"SAS column {colname}", line, expression=expression,
                                  attributes={"explanation": "SAS DATA step column calculation", "output_column_id": cid})
                    if srcs:
                        for ref in dict.fromkeys(refs):
                            if re.search(r"\b" + re.escape(ref) + r"\s*\(", expression):
                                continue
                            src_col = column(ref, line, srcs[0])
                            relation(srcs[0], src_col, "HAS_COLUMN", line)
                            relation(src_col, calc, "INPUT_TO", line)
                            relation(src_col, cid, "DERIVES_FROM", line, attributes={"via": calc})
                    relation(calc, cid, "PRODUCES", line)
                else:
                    gap("sas_ambiguous_column", f"line {line}: SAS column expression {colname} has ambiguous inputs or unsupported syntax", am.group(0).strip(), line, line + am.group(0).strip().count("\n"), srcs + [out])
            for cm in re.finditer(r"(?im)^\s*(?:keep|retain)\s+([^;]+);", body):
                add_columns(out, re.findall(r"[A-Za-z_][\w.]*", cm.group(1)), line_no + body.count("\n", 0, cm.start()))
            if re.search(r"(?im)^\s*input\s+", body):
                im = re.search(r"(?im)^\s*input\s+([^;]+);", body)
                if im:
                    add_columns(out, re.findall(r"(?:\$)?([A-Za-z_][\w.]*)\s*(?:\$|\s+)", im.group(1)), line_no + body.count("\n", 0, im.start()))
            if srcs or assignments or re.search(r"(?im)^\s*(set|merge|input|if|where|format|length)\b", body):
                end_line = content.count("\n", 0, block.end()) + 1
                step = transform("SAS DATA step", "DATA " + target_text + ";" + body, line_no, srcs, [out],
                                 attrs={"assignments": assignments}, end=end_line)
                for src in srcs:
                    relation(src, out, "DERIVES_FROM", line_no, attributes={"via": step}, end=end_line)

        # Statistical PROC blocks: model statements, training input, and score/output destinations.
        for block in re.finditer(r"(?is)\bproc\s+(reg|logistic|glm|genmod|arima|mixed|phreg|tree|hp\w+)\b([^;]*);(.*?)(?:\brun\s*;|\Z)", content):
            proc, options, body = block.group(1).lower(), block.group(2), block.group(3)
            line = content.count("\n", 0, block.start()) + 1
            dm = re.search(r"\bdata\s*=\s*([\w.$&]+)", options, re.I)
            if not dm:
                continue
            train = dataset(dm.group(1), line, expression=dm.group(1) if "&" in dm.group(1) else None, role="training")
            mm = re.search(r"(?im)^\s*model\s+([^;]+);", body)
            model_name = mm.group(1).strip() if mm else f"{proc} model"
            end_line = content.count("\n", 0, block.end()) + 1
            model = entity("model", f"SAS {proc}: {model_name}", line,
                           expression=mm.group(0).strip() if mm else None,
                           attributes={"procedure": proc, "role": "statistical model"}, end=end_line)
            relation(train, model, "TRAINS", line, end=end_line)
            for relkind, raw in re.findall(r"(?im)^\s*(score|output)\s+([^;]+);", body):
                om = re.search(r"\bout\s*=\s*([\w.$&]+)", raw, re.I)
                if om:
                    out = dataset(om.group(1), line + body.count("\n", 0, body.lower().find(raw.lower())),
                                  expression=om.group(1) if "&" in om.group(1) else None, role="scored output")
                    relation(model, out, "SCORES" if relkind.lower() == "score" else "PRODUCES", line, end=end_line)
                    if relkind.lower() == "score":
                        relation(train, model, "INPUT_TO", line, attributes={"role": "score input (not statically distinguished from training data)"}, end=end_line)
            if not mm:
                warn(f"line {line}: PROC {proc} recognized, but no MODEL statement was found")
        if re.search(r"(?i)%include|call execute|dosubl|data\s+_null_", content):
            warn("SAS macro/include or generated code may add lineage that static patterns cannot resolve")
        if re.search(r"(?i)proc\s+(?:means|summary|sort|transpose|append|tabulate|freq)\b", content):
            warn("SAS procedure detected outside the supported DATA step, SQL, and statistical model patterns")

    elif suffix in {".sql", ".ddl", ".dml"}:
        # Split on semicolons while retaining approximate line offsets.
        for stmt in re.finditer(r"[^;]+;?", content):
            text = stmt.group(0).strip()
            if not text:
                continue
            line = content.count("\n", 0, stmt.start() + len(stmt.group(0)) - len(stmt.group(0).lstrip())) + 1
            extract_sql(text, line, "SQL transformation", line + text.count("\n"))
        if re.search(r"\b(?:EXECUTE\s+IMMEDIATE|PREPARE|\bEXEC\s*\()", content, re.I):
            warn("Dynamic SQL detected; runtime-built tables and lineage are unresolved")

    elif suffix == ".py":
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError as exc:
            warn(f"Python parse failed at line {exc.lineno}: {exc.msg}")
            tree = None
        if tree:
            assigned: dict[str, str] = {}
            static_strings: dict[str, tuple[str, bool]] = {}
            def expr_text(node: ast.AST) -> str:
                return ast.get_source_segment(content, node) or ast.unparse(node)
            def line_of(node: ast.AST) -> int:
                return getattr(node, "lineno", 1)
            def call_name(node: ast.AST) -> str:
                if isinstance(node, ast.Name): return node.id
                if isinstance(node, ast.Attribute): return call_name(node.value) + "." + node.attr
                return ""
            for candidate in ast.walk(tree):
                if isinstance(candidate, (ast.Assign, ast.AnnAssign)):
                    value = candidate.value
                    targets = candidate.targets if isinstance(candidate, ast.Assign) else [candidate.target]
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        text_value, dynamic = value.value, False
                    elif isinstance(value, ast.JoinedStr):
                        text_value = "".join(p.value if isinstance(p, ast.Constant) and isinstance(p.value, str)
                                              else "{" + ast.unparse(p.value) + "}" if isinstance(p, ast.FormattedValue)
                                              else "{dynamic}" for p in value.values)
                        dynamic = True
                    else:
                        continue
                    for target in targets:
                        if isinstance(target, ast.Name):
                            static_strings[target.id] = (text_value, dynamic)
            for _ in range(3):
                for key, (text_value, dynamic) in list(static_strings.items()):
                    for name, (replacement, _) in static_strings.items():
                        if name != key:
                            text_value = text_value.replace("{" + name + "}", replacement)
                    static_strings[key] = (text_value, dynamic or "{dynamic}" in text_value)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if isinstance(value, ast.Call):
                        fn = call_name(value.func)
                        if fn.endswith("getenv") and value.args and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str):
                            default = value.args[1].value if len(value.args) > 1 and isinstance(value.args[1], ast.Constant) else None
                            symbol(value.args[0].value, expr_text(value), line_of(node), str(default) if default is not None else None)
                        if any(x in fn for x in ("read_csv", "read_parquet", "read_json", "read_table", "read_sql", "read_sql_query", "read_sql_table")):
                            line = line_of(node)
                            arg = value.args[0] if value.args else None
                            source_expr = expr_text(arg) if arg else fn
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                src_name = arg.value
                                src_expr = None
                            else:
                                src_name, src_expr = source_expr, source_expr
                                for v in re.findall(r"\b([A-Z][A-Z0-9_]*)\b|\$\{?([A-Z][A-Z0-9_]*)", source_expr):
                                    var = next((x for x in v if x), None)
                                    if var: symbol(var, f"{var} in {source_expr}", line)
                            query_text = None
                            if "read_sql" in fn and not fn.endswith("read_sql_table"):
                                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                    query_text = arg.value
                                elif isinstance(arg, ast.Name) and arg.id in static_strings:
                                    query_text = static_strings[arg.id][0]
                                source_names = sql_tables(query_text)[0] if query_text else []
                                sources = [dataset(name, line, expression=name if any(c in name for c in "$&{}") else None, role="read source") for name in source_names]
                                if not sources:
                                    warn(f"line {line}: Python SQL read source is unresolved")
                            else:
                                sources = [dataset(src_name, line, expression=src_expr, role="read source")]
                            for target in targets:
                                if isinstance(target, ast.Name):
                                    if len(sources) == 1 and "read_sql" not in fn:
                                        assigned[target.id] = sources[0]
                                    dst = dataset(target.id, line, expression=target.id, role="in-memory dataframe")
                                    t = transform(f"Python {fn}", expr_text(node), line, sources, [dst], attrs={"call": fn})
                                    for source in sources:
                                        relation(source, dst, "DERIVES_FROM", line, attributes={"via": t})
                                    if "sql" in fn.lower() and arg and isinstance(arg, (ast.Constant, ast.JoinedStr)):
                                        extract_sql(source_expr.strip("'\""), line, "Python read_sql query")
                                    elif "sql" in fn.lower() and isinstance(arg, ast.Name) and arg.id in static_strings:
                                        query_text, dynamic = static_strings[arg.id]
                                        extract_sql(query_text, line, "Python read_sql query")
                                        if dynamic:
                                            warn(f"line {line}: interpolated SQL values are not resolved")
                                        query_reads, _ = sql_tables(query_text)
                                        for query_source in query_reads:
                                            table_id = dataset(query_source, line, expression=query_source if "{" in query_source else None)
                                            relation(table_id, dst, "DERIVES_FROM", line, attributes={"via": "Python read_sql"})
                    elif isinstance(value, (ast.JoinedStr, ast.BinOp, ast.Call)):
                        source_expr = expr_text(value)
                        if "{" in source_expr or "getenv" in source_expr or "environ" in source_expr:
                            target_name = next((t.id for t in targets if isinstance(t, ast.Name)), "<assigned expression>")
                            symbol(target_name, source_expr, line_of(node))
                            for v in re.findall(r"\{\s*([A-Za-z_]\w*)|getenv\(\s*['\"]([^'\"]+)", source_expr):
                                var = next((x for x in v if x), None)
                                if var: symbol(var, source_expr, line_of(node))
                            env_match = re.search(r"(?:getenv|environ(?:\.get)?)\s*\(\s*['\"]([^'\"]+)", source_expr)
                            if env_match:
                                default = value.args[1].value if isinstance(value, ast.Call) and len(value.args) > 1 and isinstance(value.args[1], ast.Constant) else None
                                symbol(env_match.group(1), source_expr, line_of(node), str(default) if default is not None else None)
                        if isinstance(value, ast.Call) and call_name(value.func).endswith("getenv") and value.args:
                            env = value.args[0]
                            if isinstance(env, ast.Constant) and isinstance(env.value, str):
                                default = value.args[1].value if len(value.args) > 1 and isinstance(value.args[1], ast.Constant) else None
                                symbol(env.value, source_expr, line_of(node), str(default) if default is not None else None)
                if isinstance(node, ast.Call):
                    fn = call_name(node.func)
                    if re.search(r"(?:to_csv|to_parquet|to_json|to_sql)$", fn, re.I):
                        line = line_of(node)
                        arg = node.args[0] if node.args else None
                        target_expr = expr_text(arg) if arg else fn
                        dst = dataset(target_expr, line, expression=target_expr if not isinstance(arg, ast.Constant) else None,
                                      role="write destination")
                        owner = node.func.value if isinstance(node.func, ast.Attribute) else None
                        src = dataset(expr_text(owner), line, expression=expr_text(owner), role="in-memory dataframe") if owner else None
                        transform(f"Python {fn}", expr_text(node), line, [src] if src else [], [dst], attrs={"call": fn})
            # Track literal dataframe column assignments and propagate known columns to exports.
            known_columns: dict[str, set[str]] = {}
            for node in sorted(ast.walk(tree), key=lambda n: getattr(n, "lineno", 0)):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if not (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                                and isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)):
                            continue
                        owner, name, line = target.value.id, target.slice.value, line_of(node)
                        parent = dataset(owner, line, expression=owner, role="in-memory dataframe")
                        output = column(name, line, parent, expression=expr_text(node.value))
                        relation(parent, output, "HAS_COLUMN", line)
                        relation(program_id, output, "WRITES", line)
                        known_columns.setdefault(owner, set()).add(name)
                        calc = entity("transformation", f"Python column {name}", line, expression=expr_text(node.value),
                                      attributes={"output_column_id": output, "language": "python"})
                        for ref in ast.walk(node.value):
                            if isinstance(ref, ast.Subscript) and isinstance(ref.value, ast.Name) and isinstance(ref.slice, ast.Constant) and isinstance(ref.slice.value, str):
                                source_parent = dataset(ref.value.id, line, expression=ref.value.id, role="in-memory dataframe")
                                source_col = column(ref.slice.value, line, source_parent)
                                relation(source_parent, source_col, "HAS_COLUMN", line)
                                original = assigned.get(ref.value.id)
                                if original and ref.slice.value not in known_columns.get(ref.value.id, set()):
                                    original_col = column(ref.slice.value, line, original)
                                    relation(original, original_col, "HAS_COLUMN", line)
                                    relation(original_col, source_col, "DERIVES_FROM", line, attributes={"role": "value"})
                                relation(program_id, source_col, "READS", line, attributes={"role": "value"})
                                relation(source_col, calc, "INPUT_TO", line, attributes={"role": "value"})
                                relation(source_col, output, "DERIVES_FROM", line, attributes={"via": calc, "role": "value"})
                                known_columns.setdefault(ref.value.id, set()).add(ref.slice.value)
                        relation(calc, output, "PRODUCES", line, attributes={"role": "value"})
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.attr in {"to_csv", "to_parquet", "to_json", "to_sql"} and node.args:
                    owner, line = node.func.value.id, line_of(node)
                    target_expr = expr_text(node.args[0])
                    destination = dataset(target_expr, line, expression=target_expr if not isinstance(node.args[0], ast.Constant) else None, role="write destination")
                    parent = dataset(owner, line, expression=owner, role="in-memory dataframe")
                    for name in sorted(known_columns.get(owner, set())):
                        source_col = column(name, line, parent)
                        target_col = column(name, line, destination)
                        relation(parent, source_col, "HAS_COLUMN", line)
                        relation(destination, target_col, "HAS_COLUMN", line)
                        relation(source_col, target_col, "DERIVES_FROM", line, attributes={"role": "value"})
                        relation(program_id, target_col, "WRITES", line)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and "read_sql" in call_name(node.func).lower():
                    query = node.args[0] if node.args else None
                    if isinstance(query, ast.Name) and query.id in static_strings:
                        query_text, dynamic = static_strings[query.id]
                        extract_sql(query_text, line_of(node), "Python read_sql query")
                        if dynamic:
                            warn(f"line {line_of(node)}: interpolated SQL values are not resolved")
                    if query and isinstance(query, (ast.Constant, ast.JoinedStr)):
                        q = expr_text(query)
                        # For an f-string use the literal skeleton; mark interpolation as dynamic.
                        if isinstance(query, ast.JoinedStr):
                            literal = "".join(p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else "{dynamic}" for p in query.values)
                            extract_sql(literal, line_of(node), "Python read_sql query")
                            warn(f"line {line_of(node)}: interpolated SQL values are not resolved")
        if tree:
            for dynamic_call in ast.walk(tree):
                if isinstance(dynamic_call, ast.Call) and isinstance(dynamic_call.func, ast.Name) and dynamic_call.func.id in {"eval", "exec", "__import__"}:
                    gap("python_dynamic", "Python dynamic execution/import detected; runtime lineage is unresolved",
                        expr_text(dynamic_call), dynamic_call.lineno, dynamic_call.end_lineno)

        if re.search(r"os\.getenv|os\.environ|environ\.get", content):
            warn("Python environment-derived values are recorded symbolically; runtime values are unresolved")

    elif suffix in {".sh", ".bash", ".zsh"}:
        for line_no, raw in enumerate(content.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for m in re.finditer(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(?:['\"]?)([^'\";]*)", line):
                symbol(m.group(1), f"${{{m.group(1)}}}", line_no, m.group(2).strip())
            for m in re.finditer(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", line):
                name = m.group(1) or m.group(2)
                symbol(name, m.group(0), line_no)
            # Recognize explicit file transfer/copy and common SQL import/export utilities.
            words = re.findall(r"(?:'([^']*)'|\"([^\"]*)\"|(\S+))", line)
            args = [next((x for x in tup if x), "") for tup in words]
            low = line.lower()
            inputs: list[str] = []
            outputs: list[str] = []
            if re.search(r"\b(cp|mv|rsync|scp)\b", low) and len(args) >= 3:
                inputs = [dataset(args[-2], line_no, expression=args[-2] if "$" in args[-2] else None)]
                outputs = [dataset(args[-1], line_no, expression=args[-1] if "$" in args[-1] else None)]
            elif re.search(r"\b(bcp|sqlldr|mysqlimport)\b", low):
                paths = [a for a in args if re.search(r"\.(csv|tsv|dat|txt|sql)(?:\b|$)", a, re.I) or "$" in a]
                if paths:
                    if re.search(r"\bin\b", low):
                        inputs = [dataset(paths[-1], line_no, expression=paths[-1] if "$" in paths[-1] else None)]
                    else:
                        outputs = [dataset(paths[-1], line_no, expression=paths[-1] if "$" in paths[-1] else None)]
            elif re.search(r"\b(sas|python\s+-|python3?\s+-|Rscript)\b", low):
                # Link a launched script as a program reference; no implicit dataflow guessed.
                script = next((a for a in args if a.endswith((".sas", ".py", ".R"))), None)
                if script:
                    target = entity("program", Path(script).name, line_no, expression=script,
                                    attributes={"external_script": True})
                    relation(program_id, target, "INPUT_TO", line_no, attributes={"role": "invokes"})
            if inputs or outputs:
                transform("Shell transfer command", line, line_no, inputs, outputs,
                          attrs={"command": args[0] if args else ""})
        if re.search(r"\beval\b|\$\([^)]*\)", content):
            warn("Shell command substitution or eval detected; generated command lineage is unresolved")
        if re.search(r"\$\{?[A-Za-z_]", content):
            warn("Shell variable references are recorded symbolically; runtime overrides are unresolved")
    elif Path(path).name in MANIFESTS:
        entities[program_id]["attributes"]["role"] = "manifest"
    elif suffix in SOURCE_SUFFIXES:
        entities[program_id]["attributes"]["language"] = language_for(path)
        # Imports and literal routes are intentionally shallow structural hints.
        for match in re.finditer(r"(?m)^\s*(?:import|from|use|using|require)\s+([^;\n]+)", content):
            line = content[:match.start()].count("\n") + 1
            dependency = entity("dependency", match.group(1).strip(), line,
                                attributes={"interface": True, "resolution": "unresolved"})
            relation(program_id, dependency, "IMPORTS", line)
        for match in re.finditer(r"\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]", content):
            line = content[:match.start()].count("\n") + 1
            endpoint = entity("endpoint", match.group(1).upper() + " " + match.group(2), line,
                              attributes={"interface": True, "protocol": "http"})
            relation(program_id, endpoint, "EXPOSES", line)
        warn(f"{language_for(path)} structural adapter extracts literal imports and HTTP routes only; dataflow and dynamic calls require further analysis")
    else:
        warn(f"Unsupported file type {suffix or '<none>'}; only file/program entities were emitted")

    if suffix == ".py":
        from .code_symbols import extract_python_symbols
        extract_python_symbols(path, content, program_id, entity, relation, warn)

    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}:
        from .code_symbols import extract_script_symbols
        extract_script_symbols(path, content, program_id, entity, relation, warn)

    # Keep file/program entities even when no source pattern was recognized.
    _ = file_id
    result["entities"] = list(entities.values())
    result["relationships"] = list(relationships.values())
    result["symbols"] = list(symbols.values())
    result["warnings"] = sorted(warning_set)
    return result
