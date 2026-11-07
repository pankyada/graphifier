"""Scope-aware Python definitions. Never executes indexed source."""
import ast
from pathlib import PurePosixPath


def extract_python_symbols(path, content, program_id, entity, relation, warn):
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return
    p = PurePosixPath(path)
    testing = any(part in {'tests', 'test', '__tests__'} for part in p.parts) or p.name.startswith('test_') or p.name.endswith('_test.py') or p.name == 'conftest.py'
    context = 'test' if testing else 'production'
    unittest_names, testcase_names, pytest_names = set(), set(), set()
    for imported in tree.body:
        if isinstance(imported, ast.Import):
            for alias in imported.names:
                if alias.name == 'unittest': unittest_names.add(alias.asname or alias.name)
                if alias.name == 'pytest': pytest_names.add(alias.asname or alias.name)
        elif isinstance(imported, ast.ImportFrom) and imported.module == 'unittest':
            testcase_names.update(a.asname or a.name for a in imported.names if a.name == 'TestCase')
    test_scopes = set()
    definitions = {}
    owners = {tree: program_id}
    parents = {tree: None}
    tables = {}
    scopes = {}

    def collect(node, scope, qualified):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            framework_test = scope in test_scopes
            if isinstance(node, ast.ClassDef):
                framework_test |= any(isinstance(base, ast.Name) and base.id in testcase_names or
                                      isinstance(base, ast.Attribute) and base.attr == 'TestCase' and isinstance(base.value, ast.Name) and base.value.id in unittest_names
                                      for base in node.bases)
            else:
                for decorator in node.decorator_list:
                    decorated = decorator.func if isinstance(decorator, ast.Call) else decorator
                    name = ast.unparse(decorated)
                    framework_test |= any(name == prefix + '.fixture' or name.startswith(prefix + '.mark.') for prefix in pytest_names)
            if framework_test:
                test_scopes.add(node)
            kind = 'class' if isinstance(node, ast.ClassDef) else ('method' if isinstance(scope, ast.ClassDef) else 'function')
            name = '.'.join(qualified + [node.name])
            ident = entity(kind, name, node.lineno, end=node.end_lineno,
                           scope=f'{name}:{node.lineno}', attributes={
                               'qualified_name': name, 'owner_id': owners[scope],
                               'context': 'test' if framework_test else context, 'context_basis': 'test-framework' if framework_test else ('test-path-convention' if testing else 'source-path'),
                               'async': isinstance(node, ast.AsyncFunctionDef),
                               'signature': ast.unparse(node.args) if hasattr(node, 'args') else None,
                               'method': 'static', 'path': path})
            owners[node] = ident
            parents[node] = scope
            definitions[node] = ident
            tables.setdefault(scope, {}).setdefault(node.name, []).append(node)
            relation(owners[scope], ident, 'DEFINES', node.lineno, end=node.end_lineno)
            # Definition expressions execute in the enclosing scope, while
            # parameters bind names in the new function scope.
            scopes[node] = scope
            for child in ast.iter_child_nodes(node):
                if child in node.body:
                    collect(child, node, qualified + [node.name])
                elif isinstance(child, ast.arguments):
                    scopes[child] = node
                    for argument in ast.iter_child_nodes(child):
                        if isinstance(argument, ast.arg):
                            scopes[argument] = node
                            for annotation in ast.iter_child_nodes(argument):
                                collect(annotation, scope, qualified)
                        else:
                            collect(argument, scope, qualified)
                else:
                    collect(child, scope, qualified)
            return
        scopes[node] = scope
        for child in ast.iter_child_nodes(node):
            collect(child, scope, qualified)
    collect(tree, tree, [])
    # Rebinding, arguments and imports defeat conservative local call resolution.
    shadowed = {}
    for node in ast.walk(tree):
        scope = scopes[node]
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadowed.setdefault(scope, set()).add(node.id)
        if isinstance(node, ast.arg):
            shadowed.setdefault(scope, set()).add(node.arg)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            shadowed.setdefault(scope, set()).update(alias.asname or alias.name.split('.')[0] for alias in node.names)
    unresolved = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        scope = scopes[node]
        target = None
        if isinstance(node.func, ast.Name):
            current = scope
            while current is not None:
                if node.func.id in shadowed.get(current, set()):
                    break
                candidates = tables.get(current, {}).get(node.func.id, [])
                if candidates:
                    if len(candidates) == 1:
                        target = candidates[0]
                    break
                current = parents.get(current)
                # Class namespaces are not lexical enclosing scopes for methods.
                while isinstance(current, ast.ClassDef):
                    current = parents.get(current)
        if target is not None:
            relation(owners[scope], definitions[target], 'CALLS', node.lineno,
                     attributes={'method': 'static', 'resolution': 'lexical', 'context': context})
        else:
            unresolved += 1
    if unresolved:
        warn(f'Python symbol analysis: {unresolved} call sites remain unresolved (imports, dynamic dispatch, builtins or shadowed names)')


def extract_script_symbols(path, content, program_id, entity, relation, warn):
    """Conservative JS/TS declaration inventory; calls remain unresolved."""
    import re
    # Mask strings/comments while preserving offsets, braces and line numbers.
    masked = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',
                    lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()), content)
    p = PurePosixPath(path)
    testing = any(part in {'tests', 'test', '__tests__'} for part in p.parts) or bool(re.search(r'\.(?:test|spec)\.[cm]?[jt]sx?$', p.name))
    context = 'test' if testing else 'production'
    pairs, stack = {}, []
    for index, char in enumerate(masked):
        if char == '{': stack.append(index)
        elif char == '}' and stack: pairs[stack.pop()] = index
    candidates = []
    pattern = r'\b(class)\s+([A-Za-z_$][\w$]*)[^;{}]*\{|\b(function)\s*\*?\s*([A-Za-z_$][\w$]*)\s*\([^{};]*\)[^{};]*\{'
    for match in re.finditer(pattern, masked):
        opening = match.end() - 1
        if opening in pairs:
            candidates.append((match.start(), opening, pairs[opening], 'class' if match.group(1) else 'function', match.group(2) or match.group(4)))
    # Named arrows: brace bodies and conservative single-line expressions.
    arrow = r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^{};]*?\)|[A-Za-z_$][\w$]*)\s*(?::[^{};=]+)?\s*=>\s*'
    for match in re.finditer(arrow, masked):
        opening = match.end()
        if opening >= len(masked):
            continue
        if masked[opening] == '{':
            closing = pairs.get(opening)
        else:
            end_match = re.search(r'[;\n]', masked[opening:])
            closing = opening + end_match.start() if end_match else len(masked) - 1
        if closing is not None:
            candidates.append((match.start(), opening, closing, 'function', match.group(1)))
    # Only recognise method signatures at the immediate body depth of a known class.
    for start, opening, closing, kind, name in list(candidates):
        if kind != 'class': continue
        body = masked[opening + 1:closing]
        for match in re.finditer(r'(?:^|[;}\n])\s*(?:(?:public|private|protected|static|async|override|abstract|readonly)\s+)*([A-Za-z_$][\w$]*)\s*\([^{};]*\)\s*(?::[^{};]+)?\s*\{', body):
            begin = opening + 1 + match.start()
            method_open = opening + match.end()
            depth = masked[opening + 1:begin].count('{') - masked[opening + 1:begin].count('}')
            if depth == 0 and method_open in pairs:
                candidates.append((begin, method_open, pairs[method_open], 'method', match.group(1)))
    records = []
    for start, opening, closing, kind, name in sorted(candidates):
        containing = [r for r in records if r[0] < start and closing < r[1]]
        owner = min(containing, key=lambda r: r[1] - r[0]) if containing else None
        qualified = (owner[3] + '.' if owner else '') + name
        line = content.count('\n', 0, start) + 1
        end = content.count('\n', 0, closing) + 1
        ident = entity(kind, qualified, line, end=end, scope=f'{qualified}:{start}', attributes={
            'qualified_name': qualified, 'owner_id': owner[2] if owner else program_id,
            'context': context, 'context_basis': 'test-path-convention' if testing else 'source-path',
            'method': 'static', 'resolution': 'structural', 'path': path})
        relation(owner[2] if owner else program_id, ident, 'DEFINES', line, end=end)
        records.append((opening, closing, ident, qualified))
    warn('JS/TS symbol inventory is structural: complex arrow expressions, computed members, decorators and call resolution may be incomplete')
