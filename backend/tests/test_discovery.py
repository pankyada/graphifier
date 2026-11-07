import tempfile
import unittest
from pathlib import Path

from graphifier.discovery import discover_repository, module_for, repository_structure
from graphifier.paths import safe_files
from graphifier.extraction import extract_file


class DiscoveryTests(unittest.TestCase):
    def test_large_inventory_and_explicit_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(1300):
                (root / f'job{index}.sas').write_text('data work.a; run;')
            self.assertEqual(len(safe_files(root)), 1300)
            with self.assertRaisesRegex(ValueError, 'scan budget'):
                safe_files(root, max_files=1200)

    def test_modules_and_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{"workspaces":["packages/*"]}')
            package = root / 'packages' / 'api'
            package.mkdir(parents=True)
            (package / 'package.json').write_text('{"name":"api"}')
            source = package / 'server.ts'
            source.write_text('import express from "express";\napp.get("/health", handler);\napp.listen(3000);')
            inventory = discover_repository(root)
            self.assertTrue(inventory['is_monorepo'])
            self.assertEqual(module_for('packages/api/server.ts', inventory['modules'])['name'], 'api')
            findings = extract_file(str(source), source.read_text())
            self.assertTrue(any(e['attributes'].get('entrypoint') for e in findings['entities']))
            self.assertTrue(any(e['kind'] == 'endpoint' for e in findings['entities']))
            structure = repository_structure(root, inventory)
            ids = {e['id'] for p in inventory['files'] for e in extract_file(str(p), p.read_text())['entities']}
            self.assertTrue(all(r['target'] in ids for r in structure['relationships']))

    def test_symlinks_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'small.py').write_text('x=1')
            (root / 'link.py').symlink_to(root / 'small.py')
            self.assertEqual(len(safe_files(root)), 1)
            with self.assertRaisesRegex(ValueError, 'MAX_FILE_BYTES'):
                safe_files(root, max_file_bytes=1)
