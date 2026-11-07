"""Lineage acceptance through indexing, graph assembly, tracing and snapshot evidence."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from graphifier.api import app
from graphifier.worker import work_once


class LineageEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'GRAPHIFIER_DB': str(self.root/'db.sqlite3'), 'GRAPHIFIER_REPO_ROOT': str(self.root), 'GRAPHIFIER_API_TOKEN': ''})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def scan(self, name, files):
        folder = self.root/name
        folder.mkdir()
        for path, text in files.items():
            (folder/path).write_text(text)
        rid = self.client.post('/api/repositories', json={'path': str(folder)}).json()['id']
        jid = self.client.post('/api/jobs', json={'repo_id': rid, 'environment': 'test'}).json()['id']
        self.assertTrue(work_once())
        job = self.client.get('/api/jobs/'+jid).json()
        self.assertEqual(job['status'], 'completed', job)
        return rid

    def graph(self):
        result = self.client.get('/api/graph', params={'environment': 'test', 'granularity': 'detail'})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_sql_column_path_stitches_across_repositories_and_keeps_evidence(self):
        first = 'CREATE TABLE finance.adjusted AS SELECT s.amount * 1.1 AS adjusted_amount FROM raw.sales s;\n'
        second = 'CREATE TABLE reporting.summary AS SELECT a.adjusted_amount * 2 AS doubled FROM finance.adjusted a;\n'
        rid_a = self.scan('producer', {'produce.sql': first})
        rid_b = self.scan('consumer', {'consume.sql': second})
        graph = self.graph()
        canonical = [n for n in graph['nodes'] if n['kind']=='dataset' and n['name']=='finance.adjusted' and n['attributes'].get('canonical')]
        self.assertEqual(len(canonical), 1)
        self.assertEqual(set(canonical[0]['repositories']), {rid_a, rid_b})
        source = next(n for n in graph['nodes'] if n['kind']=='column' and n['name']=='amount' and rid_a in n.get('repositories', []))
        trace = self.client.get('/api/trace', params={'entity_id': source['id'], 'direction': 'out', 'environment': 'test', 'granularity': 'detail'}).json()
        self.assertTrue(any(n['kind']=='column' and n['name']=='doubled' for n in trace['nodes']), trace)
        self.assertTrue(any(n['kind']=='transformation' for n in trace['nodes']))
        transformation = next(n for n in trace['nodes'] if n['kind']=='transformation' and '1.1' in (n.get('expression') or ''))
        evidence = transformation['evidence'][0]
        snapshot = next(s for s in graph['snapshots'] if s['repo_id']==rid_a)
        result = self.client.get('/api/evidence', params={'repo_id': rid_a, 'file': evidence['file'], 'snapshot_id': snapshot['snapshot_id'], 'environment': 'test'}).json()
        self.assertEqual(result['content'], first)
        self.assertGreaterEqual(evidence['start_line'], 1)
        self.assertLessEqual(evidence['end_line'], len(first.splitlines()))

    def test_ambiguous_join_column_has_warning_without_fabricated_input(self):
        self.scan('ambiguous', {'join.sql': 'CREATE TABLE mart.result AS SELECT amount AS total FROM raw.left_table a JOIN raw.right_table b ON a.id=b.id;\n'})
        graph = self.graph()
        self.assertTrue(any('ambiguous' in str(w['warning']).lower() for w in graph['warnings']))
        self.assertFalse(any(n['kind']=='column' and n['name']=='amount' for n in graph['nodes']))

    def test_sas_and_python_column_calculations_reach_written_outputs(self):
        cases = {
            'sas': ('score.sas', 'data mart.scored;\nset raw.accounts;\nweighted = amount * 2;\nrun;\n', 'amount', 'weighted'),
            'python': ('report.py', 'import pandas as pd\ndf = pd.read_csv("input.csv")\ndf["total"] = df["amount"] * df["rate"]\ndf.to_csv("output.csv")\n', 'amount', 'total'),
        }
        for name, (filename, content, input_name, output_name) in cases.items():
            with self.subTest(language=name):
                rid = self.scan(name, {filename: content})
                graph = self.client.get('/api/graph', params={'repo_id': rid, 'environment': 'test', 'granularity': 'detail'}).json()
                sources = [n for n in graph['nodes'] if n['kind']=='column' and n['name']==input_name]
                self.assertTrue(sources)
                reached = set()
                for source in sources:
                    trace = self.client.get('/api/trace', params={'repo_id': rid, 'entity_id': source['id'], 'direction': 'out', 'environment': 'test', 'granularity': 'detail'}).json()
                    reached.update(n['id'] for n in trace['nodes'])
                self.assertTrue(any(n['id'] in reached and n['kind']=='column' and n['name']==output_name for n in graph['nodes']))
                self.assertTrue(any(n['id'] in reached and n['kind']=='transformation' for n in graph['nodes']))
                self.assertTrue(any(e['kind']=='READS' for e in graph['edges']))
                self.assertTrue(any(e['kind']=='WRITES' for e in graph['edges']))
                evidence = self.client.get('/api/evidence', params={'repo_id': rid, 'file': filename, 'environment': 'test'}).json()
                self.assertEqual(evidence['content'], content)

    def test_ai_parent_ids_are_remapped_to_graph_entities(self):
        folder = self.root/'ai'
        folder.mkdir()
        (folder/'source.py').write_text('# catalog.external\n# amount\n')
        rid = self.client.post('/api/repositories', json={'path': str(folder)}).json()['id']
        citation = {'file': 'source.py', 'start_line': 1, 'end_line': 2}
        result = {
            'entities': [
                {'id': 'table', 'kind': 'dataset', 'name': 'catalog.external', 'attributes': {}, 'evidence': citation},
                {'id': 'field', 'kind': 'column', 'name': 'amount', 'attributes': {'parent_dataset_id': 'table'}, 'evidence': citation},
            ],
            'relationships': [{'source': 'table', 'target': 'field', 'kind': 'HAS_COLUMN', 'attributes': {}, 'evidence': citation}],
            'symbols': [], 'warnings': [],
        }
        jid = self.client.post('/api/jobs', json={'repo_id': rid, 'environment': 'test', 'use_agent': True}).json()['id']
        with patch('graphifier.agent.analyze_file', return_value=result):
            work_once()
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        graph = self.graph()
        ids = {node['id'] for node in graph['nodes']}
        columns = [node for node in graph['nodes'] if node['kind']=='column' and node['name']=='amount']
        self.assertTrue(columns)
        self.assertTrue(all(node['attributes']['parent_dataset_id'] in ids for node in columns))
        self.assertTrue(any(node['attributes'].get('canonical') for node in columns))
