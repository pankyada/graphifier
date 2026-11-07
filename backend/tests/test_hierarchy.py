import unittest
from graphifier.hierarchy import build_hierarchy, project_hierarchy, filter_graph_context


def node(i, path, repos=None):
    return {'id': i, 'name': i, 'kind': 'function', 'attributes': {}, 'evidence': [{'file': path}], 'repositories': repos or ['r']}


class HierarchyTests(unittest.TestCase):
    def graph(self):
        return {'nodes': [node('a', 'src/api/handlers/a.py'), node('b', 'src/api/db/b.py'), node('c', 'reports/c.py')], 'edges': [
            {'id': 'ab', 'source': 'a', 'target': 'b', 'kind': 'CALLS', 'attributes': {'condition': 'x'}},
            {'id': 'bc', 'source': 'b', 'target': 'c', 'kind': 'WRITES', 'attributes': {'role': 'value'}}]}

    def test_membership_and_levels(self):
        h = build_hierarchy(self.graph())
        self.assertEqual(len(h['ancestors']), 3)
        self.assertEqual(h['recommended_levels'], ['overview', 'interfaces', 'detail'])
        self.assertEqual(len(h['memberships']), 6)

    def test_support_and_no_composition(self):
        h = build_hierarchy(self.graph())
        overview = [e for e in h['rollup_edges'] if e['attributes']['level'] == 'overview']
        self.assertEqual(len(overview), 1)
        self.assertEqual(overview[0]['attributes']['support_edge_ids'], ['bc'])
        self.assertEqual(overview[0]['attributes']['role'], 'value')

    def test_stability_and_scoped_detail(self):
        g = self.graph()
        h = build_hierarchy(g)
        g['nodes'].reverse()
        self.assertEqual(h, build_hierarchy(g))
        cid = h['ancestors']['a'][1]
        view = project_hierarchy(g, h, 'detail', cid)
        self.assertIn('a', [n['id'] for n in view['nodes']])
        self.assertNotIn('b', [n['id'] for n in view['nodes']])
        self.assertEqual(len(view['edges']), 1)
        self.assertEqual(len(view['breadcrumbs']), 2)

    def test_shared_orphans_and_small(self):
        g = {'nodes': [node('shared', '', ['a', 'b'])], 'edges': []}
        h = build_hierarchy(g)
        self.assertEqual(h['recommended_levels'], ['overview', 'detail'])
        self.assertEqual(len(project_hierarchy(g, h, 'detail')['nodes']), 1)
        self.assertEqual(len(h['ancestors']['shared']), 2)

    def test_invalid_scope(self):
        g = self.graph()
        with self.assertRaises(ValueError):
            project_hierarchy(g, build_hierarchy(g), 'detail', 'missing')

    def test_context_filter_uses_boundaries(self):
        g = {'nodes': [node('t', 'src/__tests__/a.ts'), node('p', 'src/contest/latest.py'), node('s', 'src/a.spec.ts')], 'edges': []}
        filtered = filter_graph_context(g)
        self.assertEqual([n['id'] for n in filtered['nodes']], ['p'])
        self.assertEqual(filtered['hidden_test_nodes'], 2)
        self.assertEqual(len(filter_graph_context(g, True)['nodes']), 3)

    def test_relative_evidence_and_structured_behaviour(self):
        g = self.graph()
        g['nodes'][0]['attributes']['path'] = '/Users/example/source/a.py'
        h = build_hierarchy(g)
        group = next(x for x in h['groups'] if x['id'] == h['ancestors']['b'][0])
        self.assertEqual(group['name'], 'Src/Api')
        self.assertEqual(group['attributes']['outputs'][0]['name'], 'c')
        self.assertIn('Produces c', group['attributes']['summary'])

    def test_api_specs_visible_and_conftest_hidden(self):
        g = {'nodes': [node('api', 'spec/openapi.yaml'), node('fixtures', 'conftest.py')], 'edges': []}
        self.assertEqual([n['id'] for n in filter_graph_context(g)['nodes']], ['api'])

    def test_large_root_manifest_retains_file_components(self):
        g = {'nodes': [node(str(i), f'src/agents/file{i//10}.py') for i in range(310)], 'edges': []}
        g['nodes'].append({'id': 'module', 'name': 'app', 'kind': 'module', 'attributes': {'path': '.'}, 'repositories': ['r'], 'evidence': []})
        h = build_hierarchy(g)
        self.assertEqual(h['recommended_levels'], ['overview', 'interfaces', 'detail'])
        self.assertNotEqual(h['ancestors']['0'][1], h['ancestors']['20'][1])
        group = next(x for x in h['groups'] if x['id'] == h['ancestors']['0'][0])
        self.assertTrue(group['evidence'])
        self.assertLessEqual(len(group['evidence']), 3)

    def test_structure_is_not_architectural_dependency(self):
        g = self.graph()
        g['edges'] = [{'id': 'owns', 'source': 'a', 'target': 'c', 'kind': 'CONTAINS', 'attributes': {}}]
        h = build_hierarchy(g)
        self.assertEqual(h['rollup_edges'], [])
        self.assertTrue(all(not x['attributes']['dependencies'] for x in h['groups']))
        self.assertEqual(project_hierarchy(g, h, 'detail')['edges'], g['edges'])

    def test_import_spellings_consolidate_without_losing_support(self):
        g = {'nodes': [node('a', 'api/a.ts'), node('b', 'api/b.ts'), node('c', 'lib/c.ts')],
             'edges': [{'id': 'i1', 'source': 'a', 'target': 'c', 'kind': 'IMPORTS', 'attributes': {'module': '../lib/c.js', 'method': 'static'}},
                       {'id': 'i2', 'source': 'b', 'target': 'c', 'kind': 'IMPORTS', 'attributes': {'module': '../lib/c', 'method': 'static'}}]}
        rollups = [e for e in build_hierarchy(g)['rollup_edges'] if e['attributes']['level'] == 'overview']
        self.assertEqual(len(rollups), 1)
        self.assertEqual(rollups[0]['attributes']['support_count'], 2)
        self.assertEqual(set(rollups[0]['attributes']['support_edge_ids']), {'i1', 'i2'})

    def test_large_nested_manifest_keeps_file_components(self):
        g = {'nodes': [node(str(i), f'services/risk/file{i//10}.py') for i in range(310)], 'edges': []}
        g['nodes'].append({'id': 'module', 'name': 'risk', 'kind': 'module', 'attributes': {'path': 'services/risk'}, 'repositories': ['r'], 'evidence': []})
        h = build_hierarchy(g)
        self.assertEqual(h['ancestors']['0'][0], h['ancestors']['20'][0])
        self.assertNotEqual(h['ancestors']['0'][1], h['ancestors']['20'][1])
        self.assertEqual(h['recommended_levels'], ['overview', 'interfaces', 'detail'])
