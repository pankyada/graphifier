import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from graphifier.api import app
from graphifier.worker import work_once
from graphifier.agent import ModelTransportError

SQL = 'CREATE TABLE mart.result AS\nWITH scoped AS (SELECT amount FROM raw.sales s JOIN raw.accounts a ON s.account_id=a.id)\nSELECT amount * 2 AS total FROM scoped;\n'
SCHEMA = 'CREATE TABLE raw.sales (amount DECIMAL, account_id INTEGER);\nCREATE TABLE raw.accounts (id INTEGER, status VARCHAR);\n'
EMPTY = {'entities': [], 'relationships': [], 'symbols': [], 'warnings': []}


def extraction():
    sql = {'file': 'query.sql', 'start_line': 3, 'end_line': 3}
    schema = {'file': 'schema.sql', 'start_line': 1, 'end_line': 1}
    def entity(id, kind, name, ev, attrs=None, expression=None):
        return {'id': id, 'kind': kind, 'name': name, 'attributes': attrs or {}, 'expression': expression, 'evidence': ev}
    entities = [entity('src', 'dataset', 'raw.sales', schema), entity('dst', 'dataset', 'mart.result', sql),
                entity('amount', 'column', 'amount', schema, {'parent_dataset_id': 'src'}),
                entity('total', 'column', 'total', sql, {'parent_dataset_id': 'dst'}),
                entity('calc', 'transformation', 'double amount', sql, expression='amount * 2')]
    relationships = [{'source': a, 'target': b, 'kind': kind, 'attributes': {}, 'evidence': sql}
                     for a,b,kind in [('src','amount','HAS_COLUMN'),('dst','total','HAS_COLUMN'),('amount','calc','INPUT_TO'),('calc','total','PRODUCES')]]
    return {**EMPTY, 'entities': entities, 'relationships': relationships}


class GapFallbackEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'GRAPHIFIER_DB': str(self.root/'db.sqlite3'), 'GRAPHIFIER_REPO_ROOT': str(self.root), 'GRAPHIFIER_API_TOKEN': '', 'GRAPHIFIER_AGENT_MAX_FILES': '0', 'GRAPHIFIER_AGENT_MAX_STEPS': '0'})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.repo = self.root/'repo'
        self.repo.mkdir()
        (self.repo/'query.sql').write_text(SQL)
        (self.repo/'schema.sql').write_text(SCHEMA)
        self.rid = self.client.post('/api/repositories', json={'path': str(self.repo)}).json()['id']

    def queue(self, ai):
        return self.client.post('/api/jobs', json={'repo_id': self.rid, 'use_agent': ai}).json()['id']

    def model(self, payload, config=None):
        if 'Current file: query.sql' not in payload['input'][0]['content']:
            return {'output_text': json.dumps(EMPTY)}
        outputs = [item for item in payload['input'] if item.get('type')=='function_call_output']
        if not outputs:
            self.first_prompt = json.loads(json.dumps(payload))
            return {'output': [{'type': 'function_call', 'call_id': 'schema', 'name': 'read_source', 'arguments': json.dumps({'path': 'schema.sql', 'start_line': 1})}]}
        self.assertIn('raw.sales', outputs[-1]['output'])
        return {'output_text': json.dumps(extraction())}

    def test_schema_investigation_recovers_cte_column_path_with_exact_citations(self):
        jid = self.queue(True)
        with patch('graphifier.agent._response', side_effect=self.model):
            work_once()
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        self.assertIn('Static investigation tasks:', self.first_prompt['input'][0]['content'])
        self.assertIn('nested', self.first_prompt['input'][0]['content'].lower())
        self.assertIn('find_schema', {tool['name'] for tool in self.first_prompt['tools']})
        graph = self.client.get('/api/graph', params={'repo_id': self.rid, 'granularity': 'detail'}).json()
        source = next(n for n in graph['nodes'] if n['kind']=='column' and n['name']=='amount')
        trace = self.client.get('/api/trace', params={'repo_id': self.rid, 'entity_id': source['id'], 'direction': 'out', 'granularity': 'detail'}).json()
        self.assertTrue(any(n['kind']=='column' and n['name']=='total' for n in trace['nodes']))
        self.assertTrue(any(n['kind']=='transformation' and n.get('expression')=='amount * 2' for n in trace['nodes']))
        evidence = self.client.get('/api/evidence', params={'repo_id': self.rid, 'file': 'schema.sql'}).json()
        self.assertEqual(evidence['content'], SCHEMA)
        self.assertTrue(any(item['item'].get('name')=='amount' for item in evidence['evidence']))

    def test_static_mode_and_unresolved_ai_keep_uncertainty(self):
        self.queue(False)
        with patch('graphifier.agent._response') as model:
            work_once()
            model.assert_not_called()
        self.queue(True)
        uncertain = {**EMPTY, 'warnings': ['Column ownership remains unresolved without authoritative schema context']}
        with patch('graphifier.agent._response', return_value={'output_text': json.dumps(uncertain)}):
            work_once()
        graph = self.client.get('/api/graph', params={'repo_id': self.rid, 'granularity': 'detail'}).json()
        self.assertTrue(any('unresolved' in str(w['warning']).lower() for w in graph['warnings']))
        self.assertFalse(any(n['kind']=='transformation' and n.get('expression')=='amount * 2' for n in graph['nodes']))

    def test_resume_replays_gap_context_and_captured_schema(self):
        jid = self.queue(True)
        first_payload = None
        def outage(payload, config=None):
            nonlocal first_payload
            if 'Current file: query.sql' not in payload['input'][0]['content']:
                return {'output_text': json.dumps(EMPTY)}
            if any(item.get('type')=='function_call_output' for item in payload['input']):
                first_payload = json.loads(json.dumps(payload))
                raise ModelTransportError('temporary outage')
            return self.model(payload, config)
        with patch('graphifier.agent._response', side_effect=outage):
            work_once()
        self.assertTrue(self.client.get('/api/jobs/'+jid).json()['resumable'])
        (self.repo/'schema.sql').write_text('CREATE TABLE raw.sales (changed INTEGER);\n')
        (self.repo/'query.sql').write_text('SELECT changed FROM raw.sales;\n')
        self.assertEqual(self.client.post('/api/jobs/'+jid+'/resume').status_code, 200)
        def resumed(payload, config=None):
            if 'Current file: query.sql' in payload['input'][0]['content']:
                self.assertEqual(payload, first_payload)
            return self.model(payload, config)
        with patch('graphifier.agent._response', side_effect=resumed):
            work_once()
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        self.assertEqual(self.client.get('/api/evidence', params={'repo_id': self.rid, 'file': 'schema.sql'}).json()['content'], SCHEMA)
