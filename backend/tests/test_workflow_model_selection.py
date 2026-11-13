"""Workflow-specific model settings, real payload mapping and checkpoint freezing."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from graphifier.api import app
from graphifier import agent_config
from graphifier.agent import ModelTransportError
from graphifier.db import connect
from graphifier.worker import work_once


EMPTY = {'entities': [], 'relationships': [], 'symbols': [], 'warnings': []}


class Response:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, *args): return json.dumps(self.body).encode()


def hierarchy_answer(user_content):
    request = json.loads(user_content)
    records = request['components']
    base = {'name': 'Account processing', 'summary': 'Processes account inputs.',
            'rationale': 'The cited functions provide the implementation.', 'confidence': 0.8}
    body = {'groups': [], 'component_summaries': [], 'warnings': []}
    if request['phase'] == 'components':
        body['component_summaries'] = [{**base, 'component_id': r['component_id'],
            'evidence_node_ids': [r['evidence_nodes'][0]['id']]} for r in records]
    else:
        body['groups'] = [{**base, 'id': 'account-processing',
            'component_ids': [r['component_id'] for r in records],
            'evidence_node_ids': [r['evidence_nodes'][0]['id'] for r in records]}]
    return body


class WorkflowModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'GRAPHIFIER_DB': str(self.root/'db.sqlite3'),
                                     'GRAPHIFIER_REPO_ROOT': str(self.root), 'GRAPHIFIER_API_TOKEN': ''})
        env.start()
        self.addCleanup(env.stop)
        for key in ('OPENAI_BASE_URL', 'GRAPHIFIER_AGENT_MODEL', 'GRAPHIFIER_AGENT_API',
                    'GRAPHIFIER_AGENT_REASONING_EFFORT', 'GRAPHIFIER_HIERARCHY_MODEL',
                    'GRAPHIFIER_HIERARCHY_REASONING_EFFORT'):
            os.environ.pop(key, None)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def settings(self, **overrides):
        body = {'base_url': 'http://localhost:8080/v1', 'model': 'harness-model',
                'api_mode': 'responses', 'reasoning_effort': 'low', **overrides}
        response = self.client.post('/api/settings/agent', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def queue(self, name):
        root = self.root/name
        root.mkdir()
        (root/'a.py').write_text('def load_accounts():\n    return 1\n')
        (root/'b.py').write_text('def process_accounts():\n    return 2\n')
        rid = self.client.post('/api/repositories', json={'path': str(root)}).json()['id']
        result = self.client.post('/api/jobs', json={'repo_id': rid, 'environment': 'dev',
                                                   'use_agent': True, 'use_ai_hierarchy': True})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['id']

    def test_openai_defaults_and_legacy_custom_endpoint_inheritance(self):
        config = agent_config.load_agent_config()
        harness = agent_config.profile_config(config, 'harness')
        hierarchy = agent_config.profile_config(config, 'hierarchy')
        self.assertEqual((harness['model'], harness['reasoning_effort']), ('gpt-6-luna', 'low'))
        self.assertEqual((hierarchy['model'], hierarchy['reasoning_effort']), ('gpt-6-luna', 'high'))
        self.settings(model='custom-local-model', reasoning_effort=None)
        config = agent_config.load_agent_config()
        hierarchy = agent_config.profile_config(config, 'hierarchy')
        self.assertEqual(hierarchy['model'], 'custom-local-model')
        self.assertIsNone(hierarchy['reasoning_effort'])

    def test_omitted_hierarchy_fields_preserve_saved_profile(self):
        self.settings(hierarchy_model='architecture-model', hierarchy_reasoning_effort='high')
        updated = self.settings(model='new-harness-model', reasoning_effort='medium')
        self.assertEqual(updated['hierarchy_model'], 'architecture-model')
        self.assertEqual(updated['hierarchy_reasoning_effort'], 'high')
        current = self.client.get('/api/settings').json()['agent']
        self.assertEqual(current['model'], 'new-harness-model')
        self.assertEqual(current['hierarchy_model'], 'architecture-model')
        self.settings(hierarchy_reasoning_effort=None)
        self.assertIsNone(agent_config.profile_config(agent_config.load_agent_config(), 'hierarchy')['reasoning_effort'])

    def test_both_protocols_send_distinct_workflow_models_and_efforts(self):
        for mode in ('responses', 'chat_completions'):
            with self.subTest(mode=mode):
                self.settings(api_mode=mode, hierarchy_model='architecture-model',
                              hierarchy_reasoning_effort='high', api_key='profile-secret')
                jid = self.queue(mode)
                captured = []
                def endpoint(request, **kwargs):
                    body = json.loads(request.data)
                    harness = bool(body.get('tools'))
                    effort = body.get('reasoning_effort') if mode == 'chat_completions' else body.get('reasoning', {}).get('effort')
                    captured.append((harness, body['model'], effort, request.full_url))
                    user = body['messages'][-1]['content'] if mode == 'chat_completions' else body['input'][0]['content']
                    result = EMPTY if harness else hierarchy_answer(user)
                    return Response({'choices': [{'message': {'content': json.dumps(result)}}]} if mode == 'chat_completions'
                                    else {'output_text': json.dumps(result)})
                with patch('graphifier.provider_http.urlopen', side_effect=endpoint):
                    work_once()
                job = self.client.get('/api/jobs/'+jid).json()
                self.assertEqual(job['status'], 'completed', job)
                self.assertTrue(any(c[0] for c in captured))
                self.assertTrue(any(not c[0] for c in captured))
                for harness, model, effort, url in captured:
                    self.assertEqual(model, 'harness-model' if harness else 'architecture-model')
                    self.assertEqual(effort, 'low' if harness else 'high')
                    self.assertTrue(url.endswith('/chat/completions' if mode == 'chat_completions' else '/responses'))

    def test_resume_freezes_both_profiles_but_never_serializes_key(self):
        self.settings(hierarchy_model='original-hierarchy', hierarchy_reasoning_effort='high', api_key='frozen-profile-secret')
        jid = self.queue('resume')
        initial = []
        def interrupted(payload, config=None):
            initial.append((payload['model'], config['reasoning_effort']))
            if len(initial) == 2:
                raise ModelTransportError('Temporary source analysis outage')
            return {'output_text': json.dumps(EMPTY)}
        with patch('graphifier.agent._response', side_effect=interrupted):
            work_once()
        failed = self.client.get('/api/jobs/'+jid).json()
        self.assertEqual(failed['status'], 'failed', failed)
        self.assertTrue(failed['resumable'])
        with connect() as c:
            state = c.execute('SELECT state FROM analysis_checkpoints WHERE job_id=?', (jid,)).fetchone()[0]
        self.assertNotIn('frozen-profile-secret', state)
        self.settings(model='changed-harness', reasoning_effort='medium', hierarchy_model='changed-hierarchy',
                      hierarchy_reasoning_effort='low', api_mode='chat_completions')
        resumed = self.client.post('/api/jobs/'+jid+'/resume')
        self.assertEqual(resumed.status_code, 200, resumed.text)
        captured = []
        def complete(payload, config=None):
            harness = bool(payload.get('tools'))
            captured.append((harness, payload['model'], config['reasoning_effort'], config['api_mode']))
            result = EMPTY if harness else hierarchy_answer(payload['input'][0]['content'])
            return {'output_text': json.dumps(result)}
        with patch('graphifier.agent._response', side_effect=complete):
            work_once()
        job = self.client.get('/api/jobs/'+jid).json()
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(sum(harness for harness, _, _, _ in captured), 1)
        self.assertTrue(any(not harness for harness, _, _, _ in captured))
        for harness, model, effort, mode in captured:
            self.assertEqual(model, 'harness-model' if harness else 'original-hierarchy')
            self.assertEqual(effort, 'low' if harness else 'high')
            self.assertEqual(mode, 'responses')
        with connect() as c:
            proposal = json.loads(c.execute('SELECT data FROM analysis_ai_hierarchy WHERE job_id=?', (jid,)).fetchone()[0])
        self.assertEqual(proposal['model'], 'original-hierarchy')
        self.assertNotIn('frozen-profile-secret', json.dumps(proposal))
        fresh = self.queue('fresh')
        captured.clear()
        with patch('graphifier.agent._response', side_effect=complete):
            work_once()
        self.assertEqual(self.client.get('/api/jobs/'+fresh).json()['status'], 'completed')
        for harness, model, effort, mode in captured:
            self.assertEqual(model, 'changed-harness' if harness else 'changed-hierarchy')
            self.assertEqual(effort, 'medium' if harness else 'low')
            self.assertEqual(mode, 'chat_completions')

    def test_connection_preview_reports_both_models_without_saving(self):
        self.settings(hierarchy_model='saved-hierarchy', hierarchy_reasoning_effort='high')
        body = {'base_url': 'http://localhost:8080/v1', 'model': 'candidate-harness',
                'hierarchy_model': 'candidate-hierarchy', 'api_mode': 'responses'}
        with patch('graphifier.provider_http.urlopen', return_value=Response({'data': [{'id': 'candidate-harness'}]})):
            response = self.client.post('/api/settings/agent/test', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['selected_model_available'])
        self.assertFalse(response.json()['hierarchy_model_available'])
        saved = agent_config.load_agent_config()
        self.assertEqual(saved['model'], 'harness-model')
        self.assertEqual(saved['hierarchy_model'], 'saved-hierarchy')


if __name__ == '__main__':
    unittest.main()
