"""Acceptance checks spanning extraction, durable graph views and hierarchy APIs."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from graphifier.api import app
from graphifier.worker import work_once


class MultilevelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {
            'GRAPHIFIER_DB': str(self.root / 'graph.sqlite3'),
            'GRAPHIFIER_REPO_ROOT': str(self.root), 'GRAPHIFIER_API_TOKEN': '',
        })
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def scan(self, files, name='solution'):
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        for relative, content in files.items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        response = self.client.post('/api/repositories', json={'path': str(folder)})
        self.assertEqual(response.status_code, 200, response.text)
        rid = response.json()['id']
        self.analyse(rid)
        return rid

    def analyse(self, rid):
        response = self.client.post('/api/jobs', json={'repo_id': rid, 'environment': 'dev'})
        self.assertEqual(response.status_code, 200, response.text)
        jid = response.json()['id']
        self.assertTrue(work_once())
        job = self.client.get('/api/jobs/' + jid).json()
        self.assertEqual(job['status'], 'completed', job)

    def graph(self, rid, level='detail', **params):
        response = self.client.get('/api/graph', params={
            'repo_id': rid, 'environment': 'dev', 'granularity': level, **params,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_test_files_hidden_without_hiding_production_names(self):
        rid = self.scan({
            'src/latest.py': 'def latest_result():\n    return 1\n',
            'src/contest.py': 'def contest_score():\n    return 2\n',
            'tests/test_score.py': 'def test_score():\n    assert True\n',
        })
        hidden = self.graph(rid)
        visible = self.graph(rid, include_tests='true')
        hidden_paths = {ev['file'] for n in hidden['nodes'] for ev in n.get('evidence', [])}
        shown_paths = {ev['file'] for n in visible['nodes'] for ev in n.get('evidence', [])}
        self.assertIn('src/latest.py', hidden_paths)
        self.assertIn('src/contest.py', hidden_paths)
        self.assertNotIn('tests/test_score.py', hidden_paths)
        self.assertIn('tests/test_score.py', shown_paths)
        self.assertGreater(len(visible['nodes']), len(hidden['nodes']))
        overview = self.graph(rid, 'overview')
        self.assertFalse(any(n.get('attributes', {}).get('context') == 'test' for n in overview['nodes']))

    def test_legacy_snapshot_imports_use_captured_source(self):
        from graphifier.db import connect
        rid = self.scan({'app/main.ts': 'import { run } from "../lib/run.js";\n',
                         'lib/run.ts': 'export function run() {}\n'})
        with connect() as c:
            # Simulate pre-hierarchy findings without touching captured source.
            c.execute("DELETE FROM findings WHERE repo_id=? AND category='relationship' AND json_extract(data,'$.attributes.resolution')='local-source'", (rid,))
            c.execute("DELETE FROM graph_generations")
        (self.root / 'solution' / 'app' / 'main.ts').write_text('import "./nonexistent.js";\n')
        overview = self.graph(rid, 'overview')
        imported = [e for e in overview['edges'] if e['kind'] == 'IMPORTS']
        self.assertTrue(imported)
        response = self.client.get('/api/graph/edge-support', params={'generation': overview['generation'], 'edge_id': imported[0]['id']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(e['attributes'].get('module') == '../lib/run.js' for e in response.json()['edges']))

    def test_test_only_lineage_between_shared_resources_is_hidden(self):
        rid = self.scan({
            'src/input.sql': 'CREATE TABLE prod.first AS SELECT s.amount FROM raw.sales s;\n',
            'src/output.sql': 'CREATE TABLE prod.second AS SELECT o.amount FROM raw.other o;\n',
            'tests/test_pipeline.sql': 'CREATE TABLE prod.second AS SELECT s.amount FROM prod.first s;\n',
        })
        hidden = self.graph(rid)
        shown = self.graph(rid, include_tests='true')
        # Both physical outputs also occur in production. Filtering test nodes alone
        # must not leave a test-only canonical dependency behind.
        leaked = [e for e in hidden['edges'] if e.get('evidence') and
                  all(ev.get('file', '').startswith('tests/') for ev in e['evidence'])]
        self.assertEqual(leaked, [])
        self.assertTrue(any(any(ev.get('file', '').startswith('tests/') for ev in e.get('evidence', []))
                            for e in shown['edges']))
        outputs = [n for n in hidden['nodes'] if n.get('attributes', {}).get('canonical') and
                   n['kind'] == 'dataset' and n['name'] in {'prod.first', 'prod.second'}]
        self.assertEqual(len(outputs), 2)

    def test_repository_parent_named_tests_does_not_hide_production(self):
        rid = self.scan({'src/main.py': 'def main():\n    return 1\n'}, name='tests/solution')
        detail = self.graph(rid)
        functions = [n for n in detail['nodes'] if n['kind'] == 'function' and n['name'] == 'main']
        self.assertEqual(len(functions), 1)
        self.assertEqual(functions[0]['attributes']['path'], 'src/main.py')
        self.assertNotEqual(functions[0]['attributes']['context'], 'test')

    def test_architecture_drilldown_reaches_scoped_symbols(self):
        rid = self.scan({
            'service/handlers.py': 'class Handler:\n    def run(self):\n        return 1\n',
            'service/storage/client.py': 'def load():\n    return 2\n',
            'reports/publish.py': 'def publish():\n    return 3\n',
        })
        overview = self.graph(rid, 'overview')
        self.assertTrue(overview['nodes'])
        group = next(n for n in overview['nodes'] if n['kind'] == 'architecture' and 'Service' in n['name'])
        detail = self.graph(rid, scope_id=group['id'], generation=overview['generation'])
        self.assertEqual(detail['generation'], overview['generation'])
        self.assertEqual(detail['breadcrumbs'][-1]['id'], group['id'])
        self.assertTrue(any(n['kind'] == 'method' for n in detail['nodes']))
        paths = {ev['file'] for n in detail['nodes'] if n['kind'] not in {'architecture', 'component'}
                 for ev in n.get('evidence', [])}
        self.assertIn('service/handlers.py', paths)
        self.assertNotIn('reports/publish.py', paths)

    def test_warm_overview_does_not_reassemble_full_graph(self):
        rid = self.scan({'src/main.py': 'def main():\n    return 1\n'})
        first = self.graph(rid, 'overview')
        with patch('graphifier.graph._build', side_effect=AssertionError('full graph rebuild on warm read')):
            again = self.graph(rid, 'overview')
        self.assertEqual(first['generation'], again['generation'])
        self.assertEqual(first['nodes'], again['nodes'])

    def test_aggregate_neighbourhood_does_not_invent_detailed_lineage(self):
        rid = self.scan({
            'processing/first.sql': 'CREATE TABLE shared.left_result AS SELECT s.amount FROM raw.source s;\n',
            'processing/second.sql': 'CREATE TABLE shared.right_result AS SELECT s.amount FROM raw.unrelated s;\n',
            'reporting/output.sql': 'CREATE TABLE report.result AS SELECT r.amount FROM shared.right_result r;\n',
        })
        detail = self.graph(rid)
        source = next(n for n in detail['nodes'] if n['kind'] == 'dataset' and n['name'] == 'raw.source'
                      and n.get('attributes', {}).get('canonical'))
        for level in ('detail', 'overview'):
            with self.subTest(level=level):
                response = self.client.get('/api/trace', params={
                    'repo_id': rid, 'environment': 'dev', 'entity_id': source['id'],
                    'direction': 'out', 'granularity': level,
                })
                self.assertEqual(response.status_code, 200, response.text)
                reached = response.json()['nodes']
                self.assertFalse(any(n['name'] == 'report.result' for n in reached), reached)

    def test_rollup_support_is_paged_detailed_evidence_from_same_generation(self):
        rid = self.scan({
            'ingest/prepare.sql': 'CREATE TABLE shared.prepared AS SELECT s.amount FROM raw.source s;\n',
            'reporting/report.sql': 'CREATE TABLE report.result AS SELECT r.amount FROM shared.prepared r;\n',
        })
        overview = self.graph(rid, 'overview')
        detail = self.graph(rid, generation=overview['generation'])
        detailed_edges = {edge['id']: edge for edge in detail['edges']}
        self.assertTrue(overview['edges'])
        for edge in overview['edges']:
            response = self.client.get('/api/graph/edge-support', params={
                'generation': overview['generation'], 'edge_id': edge['id'], 'offset': 0, 'limit': 1,
            })
            self.assertEqual(response.status_code, 200, response.text)
            support = response.json()
            self.assertGreater(support['total'], 0)
            self.assertEqual(len(support['edges']), 1)
            self.assertIn(support['edges'][0]['id'], detailed_edges)
            self.assertEqual(support['edges'][0]['kind'], edge['kind'])
            self.assertEqual(support['has_more'], support['total'] > 1)
            end = self.client.get('/api/graph/edge-support', params={
                'generation': overview['generation'], 'edge_id': edge['id'],
                'offset': support['total'], 'limit': 1,
            }).json()
            self.assertEqual(end['edges'], [])
            self.assertFalse(end['has_more'])

    def test_generation_cannot_be_reused_with_different_context_filter(self):
        rid = self.scan({'src/main.py': 'def main():\n    return 1\n',
                         'tests/test_main.py': 'def test_main():\n    assert True\n'})
        production = self.graph(rid)
        response = self.client.get('/api/graph', params={
            'repo_id': rid, 'environment': 'dev', 'granularity': 'detail',
            'generation': production['generation'], 'include_tests': 'true',
        })
        self.assertIn(response.status_code, (404, 409))

    def test_hub_summary_payload_stays_bounded_without_losing_support(self):
        from graphifier.hierarchy import build_hierarchy
        count = 10000
        nodes = [{'id': 'hub', 'name': 'main', 'kind': 'function',
                  'attributes': {'path': 'app/main.py'}, 'evidence': [], 'repositories': ['repo']}]
        nodes.extend({'id': str(i), 'name': f'utility_{i}', 'kind': 'function',
                      'attributes': {'path': 'lib/helpers.py'}, 'evidence': [], 'repositories': ['repo']}
                     for i in range(count))
        edges = [{'id': f'e{i}', 'source': 'hub', 'target': str(i), 'kind': 'CALLS',
                  'attributes': {}, 'evidence': []} for i in range(count)]
        model = build_hierarchy({'nodes': nodes, 'edges': edges})
        overview = [g for g in model['groups'] if g['attributes']['level'] == 'overview']
        self.assertLess(len(json.dumps(overview)), 250000)
        rollups = [e for e in model['rollup_edges'] if e['attributes']['level'] == 'overview']
        self.assertEqual(sum(e['attributes']['support_count'] for e in rollups), count)
        self.assertEqual({sid for e in rollups for sid in e['attributes']['support_edge_ids']},
                         {e['id'] for e in edges})

    def test_new_snapshot_changes_generation_and_keeps_pinned_evidence(self):
        rid = self.scan({'src/main.py': 'def old_name():\n    return 1\n'})
        first = self.graph(rid)
        (self.root / 'solution/src/main.py').write_text('def new_name():\n    return 2\n')
        self.analyse(rid)
        second = self.graph(rid)
        self.assertNotEqual(first['generation'], second['generation'])
        pinned = self.graph(rid, generation=first['generation'])
        self.assertEqual(pinned['generation'], first['generation'])
        self.assertTrue(any(n['name'] == 'old_name' for n in pinned['nodes']))
        self.assertFalse(any(n['name'] == 'new_name' for n in pinned['nodes']))
        old_symbol = next(n for n in pinned['nodes'] if n['name'] == 'old_name')
        trace = self.client.get('/api/trace', params={
            'repo_id': rid, 'environment': 'dev', 'granularity': 'detail',
            'generation': first['generation'], 'entity_id': old_symbol['id'], 'direction': 'out',
        })
        self.assertEqual(trace.status_code, 200, trace.text)
        self.assertTrue(any(n['id'] == old_symbol['id'] for n in trace.json()['nodes']))


if __name__ == '__main__':
    unittest.main()
