"""Resolve explicit local imports against captured source paths only."""
import ast
import posixpath
import re


def link_code_findings(entities, relationships, sources):
    programs = {}
    for item in entities:
        if item.get('kind') == 'program' and not item.get('attributes', {}).get('external_script'):
            path = item.get('evidence', {}).get('file')
            if path in sources:
                programs[path] = item['id']
    edges, warnings, seen = [], [], set()
    existing = {(e['source'], e['target'], e['kind']) for e in relationships}

    def resolve(path, module, line, language, level=0):
        if language == 'script':
            if not module.startswith('.'):
                return
            base = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
            candidates = [base] if base in programs else [base + suffix for suffix in ('.ts', '.tsx', '.js', '.jsx', '.mts', '.mjs', '.cts', '.cjs')]
            if base not in programs and base.endswith(('.js', '.jsx', '.mjs', '.cjs')):
                stem = base.rsplit('.', 1)[0]
                candidates += [stem + suffix for suffix in ('.ts', '.tsx', '.mts', '.cts')]
            candidates += [base + '/index' + suffix for suffix in ('.ts', '.tsx', '.js', '.jsx')]
        else:
            if level:
                folder = posixpath.dirname(path)
                for _ in range(level - 1):
                    folder = posixpath.dirname(folder)
                base = posixpath.join(folder, module.replace('.', '/'))
            else:
                base = module.replace('.', '/')
            base = posixpath.normpath(base)
            candidates = [base + '.py', base + '/__init__.py']
        matches = sorted({candidate for candidate in candidates if candidate in programs})
        if len(matches) != 1:
            if len(matches) > 1:
                warnings.append(f'{path}:{line}: ambiguous local import {module}')
            return
        target = programs[matches[0]]
        key = (programs[path], target, 'IMPORTS')
        if key in seen or key in existing:
            return
        seen.add(key)
        edges.append({'source': key[0], 'target': target, 'kind': 'IMPORTS',
                      'attributes': {'method': 'static', 'resolution': 'local-source', 'module': module},
                      'evidence': {'file': path, 'start_line': line, 'end_line': line}})

    for path in sorted(programs):
        source = sources[path]
        if path.endswith('.py'):
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        resolve(path, alias.name, node.lineno, 'python')
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        resolve(path, node.module, node.lineno, 'python', node.level)
                    else:
                        for alias in node.names:
                            if alias.name != '*':
                                resolve(path, alias.name, node.lineno, 'python', node.level)
        elif re.search(r'\.[cm]?[jt]sx?$', path):
            # Mask comments but keep quoted import specifiers. Only statements
            # anchored at line starts are accepted, excluding dynamic import().
            clean = re.sub(r'`(?:\\.|[^`\\])*`|/\*[\s\S]*?\*/|(?m:^\s*//[^\n]*)', lambda m: '\n' * m.group().count('\n'), source)
            pattern = r'''(?m)^\s*(?:import\s+(?:[^;]*?\s+from\s+)?|export\s+[^;]*?\s+from\s+)["']([^"']+)["']'''
            for match in re.finditer(pattern, clean):
                line = clean.count('\n', 0, match.start()) + 1
                resolve(path, match.group(1), line, 'script')
    return {'relationships': edges, 'warnings': sorted(set(warnings))}
