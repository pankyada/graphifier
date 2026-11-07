"""Manifest-based module inventory and evidence-backed repository structure."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .languages import MANIFESTS, language_for
from .paths import safe_files


def discover_repository(root: Path, files: list[Path] | None = None) -> dict:
    files = safe_files(root) if files is None else files
    modules, warnings = [], []
    for path in files:
        if path.name not in MANIFESTS:
            continue
        relative = path.relative_to(root).as_posix()
        directory = path.parent.relative_to(root).as_posix()
        name = path.parent.name
        declared_workspaces = False
        if path.name == 'package.json':
            try:
                manifest = json.loads(path.read_text(encoding='utf-8'))
                name = manifest.get('name', name)
                declared_workspaces = bool(manifest.get('workspaces'))
            except (ValueError, OSError, AttributeError):
                warnings.append(f'{relative}: invalid package manifest; directory identity used')
        declared_workspaces |= path.name in {'pnpm-workspace.yaml', 'lerna.json', 'nx.json'}
        existing = next((m for m in modules if m['path'] == directory), None)
        if existing:
            existing['workspace'] |= declared_workspaces
            existing['manifests'].append(relative)
        else:
            modules.append({'name': str(name), 'path': directory, 'manifest': relative,
                            'manifests': [relative], 'workspace': declared_workspaces})
    return {'files': files, 'modules': modules, 'warnings': warnings,
            'languages': dict(Counter(language_for(str(p)) for p in files)),
            'is_monorepo': len(modules) > 1 or any(m['workspace'] for m in modules)}


def module_for(path: str, modules: list[dict]) -> dict | None:
    matches = [m for m in modules if m['path'] == '.' or path.startswith(m['path'] + '/')]
    return max(matches, key=lambda m: len(m['path'])) if matches else None


def repository_structure(root: Path, discovery: dict) -> dict:
    entities, relationships = [], []
    def stable(kind, name):
        return kind + ':' + hashlib.sha256(name.encode()).hexdigest()[:20]
    for module in discovery['modules']:
        ev = {'file': module['manifest'], 'start_line': 1, 'end_line': 1}
        entities.append({'id': stable('module', module['path']), 'kind': 'module', 'name': module['name'],
                         'attributes': {'path': module['path'], 'workspace': module['workspace'], 'method': 'static', 'interface': True}, 'evidence': ev})
    for path in discovery['files']:
        relative = path.relative_to(root).as_posix()
        module = module_for(relative, discovery['modules'])
        if not module:
            continue
        # Match the existing extractor's program identity exactly.
        from .extraction import _id
        program_id = _id(str(path), 'program', path.name)
        ev = {'file': relative, 'start_line': 1, 'end_line': 1}
        relationships.append({'source': stable('module', module['path']), 'target': program_id,
                              'kind': 'CONTAINS', 'attributes': {'method': 'static'}, 'evidence': ev})
    return {'entities': entities, 'relationships': relationships, 'symbols': [], 'warnings': discovery['warnings']}
