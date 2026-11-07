import copy
import unittest
from graphifier.hierarchy import build_hierarchy, filter_graph_context


class AIProjectionTests(unittest.TestCase):
    def setUp(self):
        self.graph = {'nodes': [{'id': str(i), 'name': str(i), 'kind': 'function', 'repositories': ['repo'], 'attributes': {}, 'evidence': [{'file': f'{path}/a.py'}]} for i, path in enumerate(('ingest', 'process', 'publish'))], 'edges': [{'id': 'e', 'source': '0', 'target': '2', 'kind': 'CALLS', 'attributes': {}}]}
        self.base = build_hierarchy(self.graph)
        self.cids = [self.base['ancestors'][str(i)][1] for i in range(3)]
        self.proposal = {'model': 'mock', 'prompt_version': '1', 'groups': [{'id': 'ignored', 'name': 'Preparation', 'summary': 'Prepares data.', 'rationale': 'Observed roles.', 'confidence': .8, 'component_ids': self.cids[:2], 'evidence_node_ids': ['0','1']}], 'component_summaries': []}

    def test_preserves_detail_and_fallback_and_support(self):
        before = copy.deepcopy(self.graph)
        result = build_hierarchy(self.graph, self.proposal)
        self.assertEqual(before, self.graph)
        self.assertEqual(result['ancestors']['2'], self.base['ancestors']['2'])
        self.assertEqual(result['ancestors']['0'][0], result['ancestors']['1'][0])
        self.assertEqual(result['ancestors']['0'][1], self.cids[0])
        group = next(g for g in result['groups'] if g['id'] == result['ancestors']['0'][0])
        self.assertEqual(group['attributes']['member_count'], 2)
        self.assertEqual(group['attributes']['model'], 'mock')
        self.assertEqual(group['attributes']['summary'], 'Prepares data.')
        self.assertEqual(result['rollup_edges'][0]['attributes']['support_edge_ids'], ['e'])

    def test_stable_identity_not_model_label(self):
        first = build_hierarchy(self.graph, self.proposal)
        self.proposal['groups'][0]['name'] = 'Renamed'
        second = build_hierarchy(self.graph, self.proposal)
        self.assertEqual(first['ancestors'], second['ancestors'])

    def test_invalid_reference_duplicate_and_scope(self):
        for mutate in (lambda p: p['groups'][0]['component_ids'].append('bad'), lambda p: p['groups'].append(copy.deepcopy(p['groups'][0])), lambda p: p['groups'][0].update(evidence_node_ids=['2'])):
            p = copy.deepcopy(self.proposal)
            mutate(p)
            with self.assertRaises(ValueError):
                build_hierarchy(self.graph, p)

    def test_test_production_mixing_rejected(self):
        self.graph['nodes'][1]['attributes']['context'] = 'test'
        with self.assertRaises(ValueError):
            build_hierarchy(self.graph, self.proposal)

    def test_filtering_tests_preserves_visible_component_ids(self):
        g = copy.deepcopy(self.graph)
        g['nodes'] += [{'id': f't{i}', 'name': str(i), 'kind': 'function', 'repositories': ['repo'], 'attributes': {}, 'evidence': [{'file': f'tests/test_{i}.py'}]} for i in range(310)]
        full = build_hierarchy(g)
        filtered = build_hierarchy(filter_graph_context(g))
        for nid in ('0', '1', '2'):
            self.assertEqual(full['ancestors'][nid], filtered['ancestors'][nid])

    def test_unrelated_large_repo_does_not_change_small_repo_ids(self):
        g = copy.deepcopy(self.graph)
        g['nodes'] += [{'id': f'b{i}', 'name': str(i), 'kind': 'function', 'repositories': ['other'], 'attributes': {}, 'evidence': [{'file': f'lib/{i}.py'}]} for i in range(310)]
        aggregate = build_hierarchy(g)
        for nid in ('0', '1', '2'):
            self.assertEqual(self.base['ancestors'][nid], aggregate['ancestors'][nid])
