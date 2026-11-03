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


def _id(path: str, kind: str, name: str, expression: str = "", scope: str = "") -> str:
    raw = "\0".join((path, kind, name, expression, scope))
    return f"{kind}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def extract_file(path: str, content: str) -> dict:
    """Extract likely datasets, columns, transformations, models, and symbols.

    IDs are stable for a given path and source expression. Evidence line numbers
    are one-based and inclusive. Results are static hints, not an execution graph.
    """
    suffix = Path(path).suffix.lower()
    result: dict[str, list] = {"entities": [], "relationships": [], "symbols": [], "warnings": []}
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

    file_id = entity("file", path, 1, attributes={"language": suffix.lstrip(".") or "unknown"})
    program_id = entity("program", Path(path).name or path, 1, attributes={"path": path})

    def dataset(name: str, line: int, *, expression: str | None = None, role: str | None = None) -> str:
        clean = name.strip().strip("`\"'")
        if not clean:
            clean = expression or "<dynamic>"
        attrs = {"source_path": path}
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
            relation(ds, tid, "INPUT_TO", line, end=end)
        for ds in dict.fromkeys(outputs):
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
        # Projected columns and a bounded set of direct/calculated column lineage.
        select = re.search(r"\bSELECT\s+(.*?)\s+FROM\b", statement, re.I | re.S)
        if select and outs:
            for part in select.group(1).split(","):
                alias = re.search(r"\bAS\s+([\w$]+)\s*$", part, re.I)
                bare = re.fullmatch(r"\s*(?:[\w$]+\.)?([\w$]+)\s*", part)
                cname = alias.group(1) if alias else (bare.group(1) if bare else None)
                if cname:
                    cid = column(cname, line, outs[0], expression=part.strip())
                    relation(outs[0], cid, "HAS_COLUMN", line, end=end_line)
                    if not bare:
                        expression = re.sub(r"\bAS\s+[\w$]+\s*$", "", part, flags=re.I).strip()
                        identifiers = re.findall(r"(?<![\w$])([A-Za-z_][\w$]*)(?![\w$])", expression)
                        functions = {m.group(1).lower() for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", expression)}
                        reserved = {"as", "distinct", "case", "when", "then", "else", "end", "null", "true", "false"}
                        references = [x for x in dict.fromkeys(identifiers) if x.lower() not in functions | reserved]
                        if re.fullmatch(r"[\w.$+\-*/(),\s]+", expression) and len(ins) <= 1:
                            tid = entity("transformation", f"SQL column {cname}", line, expression=expression,
                                         attributes={"explanation": "SQL projected column calculation", "output_column_id": cid}, end=end_line)
                            if ins:
                                for ref in references:
                                    src_col = column(ref, line, ins[0])
                                    relation(ins[0], src_col, "HAS_COLUMN", line)
                                    relation(src_col, tid, "INPUT_TO", line, end=end_line)
                                    relation(src_col, cid, "DERIVES_FROM", line, attributes={"via": tid}, end=end_line)
                            relation(tid, cid, "PRODUCES", line, end=end_line)
                        else:
                            warn(f"line {line}: SQL column expression {cname} is outside the bounded lineage patterns")
                elif part.strip() != "*":
                    warn(f"line {line}: SQL projection is not a simple column or aliased expression: {part.strip()}")
        if re.search(r"\b(group\s+by|window|over\s*\()", statement, re.I) and outs:
            for match in re.finditer(r"\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\([^)]*\)\s*(?:AS\s+([\w$]+))?", statement, re.I):
                add_columns(outs[0], [match.group(1) or match.group(0)], line)

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
                lineno = base_line + block.group(1).count("\n", 0, stmt.start())
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
            for sm in re.finditer(r"(?im)^\s*(?:set|merge|modify)\s+([^;]+);", body):
                line = line_no + body.count("\n", 0, sm.start())
                for raw in re.split(r"\s+", sm.group(1).strip()):
                    raw = raw.rstrip(";")
                    if raw and not raw.startswith("("):
                        srcs.append(dataset(raw, line, expression=raw if "&" in raw else None))
            assignments = []
            for am in re.finditer(r"(?im)^\s*([A-Za-z_][\w.]*)\s*=\s*([^;]+);", body):
                colname = am.group(1).split(".")[-1]
                line = line_no + body.count("\n", 0, am.start())
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
                            src_col = column(ref, line, srcs[0])
                            relation(srcs[0], src_col, "HAS_COLUMN", line)
                            relation(src_col, calc, "INPUT_TO", line)
                            relation(src_col, cid, "DERIVES_FROM", line, attributes={"via": calc})
                    relation(calc, cid, "PRODUCES", line)
                else:
                    warn(f"line {line}: SAS column expression {colname} has ambiguous inputs or unsupported syntax")
            for cm in re.finditer(r"(?im)^\s*(?:keep|retain|drop)\s+([^;]+);", body):
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
            line = content.count("\n", 0, stmt.start()) + 1
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
                        if any(x in fn for x in ("read_csv", "read_parquet", "read_json", "read_table", "read_sql", "read_sql_query", "load", "read")):
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
                            src = dataset(src_name, line, expression=src_expr, role="read source")
                            for target in targets:
                                if isinstance(target, ast.Name):
                                    assigned[target.id] = target.id
                                    dst = dataset(target.id, line, expression=target.id, role="in-memory dataframe")
                                    t = transform(f"Python {fn}", expr_text(node), line, [src], [dst], attrs={"call": fn})
                                    relation(src, dst, "DERIVES_FROM", line, attributes={"via": t})
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
                    if re.search(r"(?:to_csv|to_parquet|to_json|write|save)$", fn, re.I):
                        line = line_of(node)
                        arg = node.args[0] if node.args else None
                        target_expr = expr_text(arg) if arg else fn
                        dst = dataset(target_expr, line, expression=target_expr if not isinstance(arg, ast.Constant) else None,
                                      role="write destination")
                        owner = node.func.value if isinstance(node.func, ast.Attribute) else None
                        src = dataset(expr_text(owner), line, expression=expr_text(owner), role="in-memory dataframe") if owner else None
                        transform(f"Python {fn}", expr_text(node), line, [src] if src else [], [dst], attrs={"call": fn})
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
        if re.search(r"\beval\s*\(|\bexec\s*\(|__import__\s*\(", content):
            warn("Python dynamic execution/import detected; runtime lineage is unresolved")
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
    else:
        warn(f"Unsupported file type {suffix or '<none>'}; only file/program entities were emitted")

    # Keep file/program entities even when no source pattern was recognized.
    _ = file_id
    result["entities"] = list(entities.values())
    result["relationships"] = list(relationships.values())
    result["symbols"] = list(symbols.values())
    result["warnings"] = sorted(warning_set)
    return result
