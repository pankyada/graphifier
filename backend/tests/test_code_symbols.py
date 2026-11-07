import unittest
from graphifier.extraction import extract_file


class CodeSymbolsTests(unittest.TestCase):
    def test_nested_and_methods_have_distinct_owners(self):
        result = extract_file('src/service.py', '''class A:
    async def run(self):
        def nested():
            pass
        nested()
class B:
    def run(self):
        pass
''')
        nodes = {n['name']: n for n in result['entities']}
        self.assertNotEqual(nodes['A.run']['id'], nodes['B.run']['id'])
        self.assertEqual(nodes['A.run']['kind'], 'method')
        self.assertTrue(nodes['A.run']['attributes']['async'])
        self.assertEqual(nodes['A.run.nested']['attributes']['owner_id'], nodes['A.run']['id'])
        calls = [e for e in result['relationships'] if e['kind'] == 'CALLS']
        self.assertEqual([(e['source'], e['target']) for e in calls], [(nodes['A.run']['id'], nodes['A.run.nested']['id'])])
        ids = {n['id'] for n in nodes.values()}
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in result['relationships']))

    def test_shadowed_and_imported_calls_are_not_guessed(self):
        result = extract_file('src/a.py', '''def process():
    pass
def caller(process):
    process()
def other():
    from external import process
    process()
''')
        self.assertFalse([e for e in result['relationships'] if e['kind'] == 'CALLS'])
        self.assertTrue(any('unresolved' in w for w in result['warnings']))

    def test_class_namespace_does_not_capture_bare_calls(self):
        result = extract_file('a.py', '''class A:
    def other(self): pass
    def caller(self): other()
''')
        self.assertFalse([e for e in result['relationships'] if e['kind'] == 'CALLS'])

    def test_defaults_and_decorators_execute_in_enclosing_scope(self):
        result = extract_file('src/a.py', "def make(): pass\n@make()\ndef run(arg=make()):\n    def make(): pass\n    make()\n")
        nodes = {n['name']: n for n in result['entities']}
        calls = {(e['source'], e['target']) for e in result['relationships'] if e['kind'] == 'CALLS'}
        program = next(n for n in result['entities'] if n['kind'] == 'program')
        self.assertIn((program['id'], nodes['make']['id']), calls)
        self.assertIn((nodes['run']['id'], nodes['run.make']['id']), calls)
        self.assertNotIn((nodes['run']['id'], nodes['make']['id']), calls)

    def test_framework_context_in_mixed_file(self):
        source = "import unittest as ut\nimport pytest\nclass Checks(ut.TestCase):\n    def test_run(self): pass\n@pytest.fixture\ndef setup(): pass\ndef production(): pass\n"
        result = extract_file('src/mixed.py', source)
        nodes = {n['name']: n for n in result['entities']}
        self.assertEqual(nodes['Checks.test_run']['attributes']['context'], 'test')
        self.assertEqual(nodes['setup']['attributes']['context'], 'test')
        self.assertEqual(nodes['production']['attributes']['context'], 'production')

    def test_named_arrows(self):
        result = extract_file('src/a.ts', "export const run = async (x: string): Promise<void> => {\n const inner = () => x;\n};\nlet map = x => x + 1;\n")
        nodes = {n['name']: n for n in result['entities']}
        self.assertEqual(nodes['run.inner']['attributes']['owner_id'], nodes['run']['id'])
        self.assertEqual(nodes['map']['kind'], 'function')

    def test_typescript_scopes_and_test_context(self):
        source = "export class A {\n async run(x: string): Promise<void> { work(); }\n}\nclass B {\n run() {}\n}\nfunction outer() { function inner() {} }"
        result = extract_file('src/a.spec.ts', source)
        nodes = {n['name']: n for n in result['entities']}
        self.assertEqual(nodes['A.run']['kind'], 'method')
        self.assertEqual(nodes['A.run']['attributes']['owner_id'], nodes['A']['id'])
        self.assertEqual(nodes['outer.inner']['attributes']['owner_id'], nodes['outer']['id'])
        self.assertEqual(nodes['B.run']['attributes']['context'], 'test')
        self.assertFalse([e for e in result['relationships'] if e['kind'] == 'CALLS'])

    def test_context_and_lineage_survive(self):
        source = 'def load():\n    data = pd.read_csv("source.csv")\n    data.to_csv("out.csv")\n'
        for path, expected in [('tests/test_load.py', 'test'), ('src/contest.py', 'production')]:
            result = extract_file(path, source)
            function = next(n for n in result['entities'] if n['kind'] == 'function')
            self.assertEqual(function['attributes']['context'], expected)
            self.assertTrue(any(n['kind'] == 'dataset' for n in result['entities']))
            self.assertEqual(function['evidence']['end_line'], 3)

if __name__ == '__main__':
    unittest.main()
