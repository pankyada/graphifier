import unittest
from graphifier.code_links import link_code_findings

class CodeLinkTests(unittest.TestCase):
    def run_links(self, sources):
        nodes = [{'id': p, 'kind': 'program', 'evidence': {'file': p}} for p in sources]
        return link_code_findings(nodes, [], sources)

    def test_local_imports_only(self):
        result = self.run_links({'src/a.ts': 'import { x } from "./b";\nimport external from "external";\nimport("./dynamic");', 'src/b.ts': '', 'src/dynamic.ts': ''})
        self.assertEqual([(e['source'],e['target']) for e in result['relationships']], [('src/a.ts','src/b.ts')])

    def test_typescript_js_specifier(self):
        result = self.run_links({'src/a.ts': 'import { x } from "./b.js";', 'src/b.ts': ''})
        self.assertEqual(result['relationships'][0]['target'], 'src/b.ts')

    def test_python_relative(self):
        result = self.run_links({'pkg/a.py': 'from . import b\nfrom external import thing', 'pkg/b.py': ''})
        self.assertEqual(result['relationships'][0]['target'], 'pkg/b.py')

    def test_ambiguous_extensions(self):
        result = self.run_links({'a.ts': 'import "./b";', 'b.ts': '', 'b.js': ''})
        self.assertEqual(result['relationships'], [])
        self.assertTrue(result['warnings'])
