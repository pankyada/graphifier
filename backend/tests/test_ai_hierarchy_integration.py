"""AI hierarchy acceptance: inferred grouping never rewrites detailed evidence."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from graphifier.api import app
from graphifier.hierarchy import build_hierarchy, filter_graph_context
from graphifier.db import connect
from graphifier.worker import work_once
from graphifier.agent import ModelTransportError
from graphifier.agent_config import save_agent_config


def fixture_graph():
    nodes = [{'id': key, 'name': name, 'kind': 'function',
              'attributes': {}, 'evidence': [{'file': path, 'start_line': 1, 'end_line': 2}],
              'repositories': [repo]}
             for key, name, path, repo in [
                 ('ingest', 'read_accounts', 'ingestion/source.py', 'repo'),
                 ('score', 'calculate_risk', 'scoring/model.py', 'repo'),
                 ('test', 'test_risk', 'tests/test_model.py', 'repo'),
                 ('other', 'calculate_risk', 'scoring/model.py', 'other-repo'),
             ]]
    return {'repo_id': None, 'nodes': nodes, 'edges': [
        {'id': 'call', 'source': 'ingest', 'target': 'score', 'kind': 'CALLS',
         'attributes': {'role': 'control'}, 'evidence': [{'file': 'ingestion/source.py', 'start_line': 2, 'end_line': 2}]}
    ], 'snapshots': [], 'warnings': [], 'version': 'fixture', 'system': 'test'}


def proposal_for(graph, member_ids, name='Risk scoring pipeline'):
    source = build_hierarchy(graph)
    component_ids = sorted({source['ancestors'][nid][-1] for nid in member_ids})
    return {'groups': [{'id': 'risk', 'name': name, 'summary': 'Reads accounts and calculates risk.',
                        'rationale': 'The cited functions supply and calculate risk inputs.', 'confidence': 0.9,
                        'component_ids': component_ids, 'evidence_node_ids': member_ids}],
            'component_summaries': [], 'model': 'test-model', 'prompt_version': 'test-prompt'}


class AIHierarchyProjectionTests(unittest.TestCase):
    def test_inferred_membership_preserves_detail_and_evidence(self):
        graph = fixture_graph()
        before = copy.deepcopy(graph)
        source = build_hierarchy(graph)
        model = build_hierarchy(graph, proposal_for(graph, ['ingest', 'score']))
        self.assertEqual(graph, before)
        group = next(g for g in model['groups'] if g['name'] == 'Risk scoring pipeline')
        self.assertEqual(group['attributes']['provenance'], 'model-inferred')
        self.assertEqual(group['attributes']['confidence'], 0.9)
        self.assertEqual(set(group['attributes']['cited_node_ids']), {'ingest', 'score'})
        self.assertIn('observed_summary', group['attributes'])
        self.assertEqual(model['ancestors']['ingest'][0], model['ancestors']['score'][0])
        self.assertNotEqual(model['ancestors']['ingest'][0], model['ancestors']['other'][0])
        self.assertEqual({m['node_id'] for m in source['memberships']},
                         {m['node_id'] for m in model['memberships']})
        renamed = build_hierarchy(graph, proposal_for(graph, ['ingest', 'score'], name='Account risk'))
        self.assertEqual(model['ancestors']['ingest'][0], renamed['ancestors']['ingest'][0])

    def test_cross_repository_and_test_production_merges_rejected(self):
        graph = fixture_graph()
        for members in (['score', 'other'], ['score', 'test']):
            with self.subTest(members=members), self.assertRaises(ValueError):
                build_hierarchy(graph, proposal_for(graph, members))

    def test_invented_or_unrelated_citations_and_duplicate_ownership_rejected(self):
        graph = fixture_graph()
        valid = proposal_for(graph, ['ingest', 'score'])
        for citation in ('imaginary-entity', 'other'):
            bad = copy.deepcopy(valid)
            bad['groups'][0]['evidence_node_ids'] = [citation]
            with self.subTest(citation=citation), self.assertRaises(ValueError):
                build_hierarchy(graph, bad)
        bad = copy.deepcopy(valid)
        bad['groups'].append(copy.deepcopy(bad['groups'][0]))
        with self.assertRaises(ValueError):
            build_hierarchy(graph, bad)

    def test_filtering_tests_keeps_validated_production_proposal(self):
        graph = fixture_graph()
        proposal = proposal_for(graph, ['ingest', 'score'])
        test_proposal = proposal_for(graph, ['test'], name='Risk verification')
        proposal['groups'].extend(test_proposal['groups'])
        source = build_hierarchy(graph)
        proposal['validated_component_ids'] = [g['id'] for g in source['groups'] if g['kind'] == 'component']
        proposal['validated_node_ids'] = [n['id'] for n in graph['nodes']]
        filtered = filter_graph_context(graph)
        model = build_hierarchy(filtered, proposal)
        self.assertNotIn('test', model['ancestors'])
        self.assertFalse(any(g['name'] == 'Risk verification' for g in model['groups']))
        self.assertTrue(any(g['name'] == 'Risk scoring pipeline' for g in model['groups']))


class AIHierarchyPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'GRAPHIFIER_DB': str(self.root/'db.sqlite3'),
                                     'GRAPHIFIER_REPO_ROOT': str(self.root), 'GRAPHIFIER_API_TOKEN': ''})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        save_agent_config('http://localhost:8000/v1', 'mock-hierarchy-model', 'responses', api_key='hierarchy-test-secret')

    def repository(self, name='repo', tests=False):
        root = self.root/name
        root.mkdir()
        files = {'ingestion/source.py': 'def read_accounts():\n    return 1\n',
                 'scoring/model.py': 'def calculate_risk():\n    return 2\n'}
        if tests:
            files['tests/test_model.py'] = 'def test_model():\n    assert True\n'
        for relative, content in files.items():
            path = root/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        response = self.client.post('/api/repositories', json={'path': str(root)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def queue(self, rid, use_ai=True):
        response = self.client.post('/api/jobs', json={'repo_id': rid, 'environment': 'dev',
                                                     'use_agent': False, 'use_ai_hierarchy': use_ai})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    @staticmethod
    def provider(payload, config=None):
        supplied = json.loads(payload['input'][0]['content'])
        records = supplied['components']
        body = {'groups': [], 'component_summaries': [], 'warnings': []}
        common = {'name': 'Risk scoring capability', 'summary': 'Reads accounts and calculates risk.',
                  'rationale': 'Cited source definitions describe this responsibility.', 'confidence': 0.9}
        if supplied['phase'] == 'components':
            body['component_summaries'] = [{**common, 'component_id': record['component_id'],
                                           'evidence_node_ids': [record['evidence_nodes'][0]['id']]}
                                          for record in records]
        else:
            body['groups'] = [{**common, 'id': 'risk', 'component_ids': [r['component_id'] for r in records],
                               'evidence_node_ids': [r['evidence_nodes'][0]['id'] for r in records]}]
        return {'output_text': json.dumps(body)}

    def graph(self, rid, **params):
        response = self.client.get('/api/graph', params={'repo_id': rid, 'environment': 'dev',
                                                       'granularity': 'overview', **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_static_job_never_calls_model(self):
        rid = self.repository()
        jid = self.queue(rid, use_ai=False)
        with patch('graphifier.agent._response', side_effect=AssertionError('Unexpected model call')) as model:
            work_once()
        self.assertEqual(model.call_count, 0)
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        with connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM analysis_ai_hierarchy').fetchone()[0], 0)

    def test_hierarchy_only_job_calls_model_and_keeps_source_detail(self):
        rid = self.repository(tests=True)
        jid = self.queue(rid)
        with patch('graphifier.agent._response', side_effect=self.provider) as model, \
             patch('graphifier.agent.analyze_file', side_effect=AssertionError('Source enrichment must be disabled')):
            work_once()
        job = self.client.get('/api/jobs/'+jid).json()
        self.assertEqual(job['status'], 'completed', job)
        self.assertGreater(model.call_count, 0)
        self.assertTrue(job['use_ai_hierarchy'])
        source = self.graph(rid, hierarchy_mode='deterministic', granularity='detail')
        inferred = self.graph(rid, hierarchy_mode='ai', granularity='detail')
        self.assertEqual(source['nodes'], inferred['nodes'])
        self.assertEqual(source['edges'], inferred['edges'])
        overview = self.graph(rid, hierarchy_mode='ai')
        self.assertTrue(any(n['attributes'].get('provenance') == 'model-inferred' for n in overview['nodes']))
        self.assertFalse(any(n['attributes'].get('context') == 'test' for n in overview['nodes']))
        with_tests = self.graph(rid, hierarchy_mode='ai', include_tests=True)
        self.assertTrue(any(n['attributes'].get('context') == 'test' for n in with_tests['nodes']))
        with connect() as c:
            for table, column in [('analysis_checkpoints', 'state'), ('analysis_ai_hierarchy', 'data'),
                                  ('analysis_ai_hierarchy_units', 'response_text')]:
                for row in c.execute(f'SELECT {column} FROM {table}'):
                    self.assertNotIn('hierarchy-test-secret', row[0])

    def test_transport_resume_reuses_completed_model_call(self):
        rid = self.repository()
        jid = self.queue(rid)
        calls = []
        def interrupted(payload, config=None):
            phase = json.loads(payload['input'][0]['content'])['phase']
            calls.append(phase)
            if phase == 'architecture':
                raise ModelTransportError('Temporary provider failure')
            return self.provider(payload, config)
        with patch('graphifier.agent._response', side_effect=interrupted):
            work_once()
        failed = self.client.get('/api/jobs/'+jid).json()
        self.assertEqual(failed['status'], 'failed', failed)
        self.assertTrue(failed['resumable'])
        self.assertEqual(calls, ['components', 'architecture'])
        response = self.client.post('/api/jobs/'+jid+'/resume')
        self.assertEqual(response.status_code, 200, response.text)
        with patch('graphifier.agent._response', side_effect=self.provider) as model:
            work_once()
        completed = self.client.get('/api/jobs/'+jid).json()
        self.assertEqual(completed['status'], 'completed', completed)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(json.loads(model.call_args.args[0]['input'][0]['content'])['phase'], 'architecture')

    def test_invalid_model_references_leave_visible_fallback_warning(self):
        rid = self.repository()
        jid = self.queue(rid)
        def invalid(payload, config=None):
            result = self.provider(payload, config)
            body = json.loads(result['output_text'])
            for item in body['groups'] + body['component_summaries']:
                item['evidence_node_ids'] = ['invented-source-node']
            return {'output_text': json.dumps(body)}
        with patch('graphifier.agent._response', side_effect=invalid):
            work_once()
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        with connect() as c:
            proposal = json.loads(c.execute('SELECT data FROM analysis_ai_hierarchy WHERE job_id=?', (jid,)).fetchone()[0])
        self.assertEqual(proposal['status'], 'partial')
        self.assertTrue(proposal['warnings'])
        graph = self.graph(rid, hierarchy_mode='ai')
        self.assertFalse(any(n['attributes'].get('provenance') == 'model-inferred' for n in graph['nodes']))
        self.assertEqual(graph['ai_hierarchy']['status'], 'partial')
        self.assertTrue(any('AI hierarchy' in str(w) for w in graph['ai_hierarchy']['warnings']))

    def test_mode_and_proposal_revisions_are_generation_scoped(self):
        rid = self.repository()
        jid = self.queue(rid)
        with patch('graphifier.agent._response', side_effect=self.provider):
            work_once()
        first = self.graph(rid, hierarchy_mode='ai')
        source = self.graph(rid, hierarchy_mode='deterministic')
        self.assertNotEqual(first['generation'], source['generation'])
        mismatch = self.client.get('/api/graph', params={'repo_id': rid, 'environment': 'dev',
            'generation': first['generation'], 'hierarchy_mode': 'deterministic', 'granularity': 'overview'})
        self.assertIn(mismatch.status_code, (404, 409))
        with connect() as c:
            proposal = json.loads(c.execute('SELECT data FROM analysis_ai_hierarchy WHERE job_id=?', (jid,)).fetchone()[0])
            proposal['groups'][0]['summary'] = 'Revised explanation with the same cited membership.'
            c.execute('UPDATE analysis_ai_hierarchy SET data=? WHERE job_id=?', (json.dumps(proposal), jid))
        changed = self.graph(rid, hierarchy_mode='ai')
        self.assertNotEqual(changed['generation'], first['generation'])
        pinned = self.graph(rid, hierarchy_mode='ai', generation=first['generation'])
        self.assertEqual(pinned['nodes'], first['nodes'])
        with connect() as c:
            proposal['warnings'].append('AI hierarchy: one responsibility remains uncertain.')
            proposal['status'] = 'partial'
            c.execute('UPDATE analysis_ai_hierarchy SET data=? WHERE job_id=?', (json.dumps(proposal), jid))
        revised_status = self.graph(rid, hierarchy_mode='ai')
        self.assertNotEqual(revised_status['generation'], changed['generation'])
        self.assertEqual(revised_status['ai_hierarchy']['status'], 'partial')

    def test_aggregate_view_keeps_same_named_inferences_repository_scoped(self):
        repositories = [self.repository('repo_a'), self.repository('repo_b')]
        for rid in repositories:
            jid = self.queue(rid)
            with patch('graphifier.agent._response', side_effect=self.provider):
                work_once()
            self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        response = self.client.get('/api/graph', params={'environment': 'dev', 'granularity': 'overview', 'hierarchy_mode': 'ai'})
        self.assertEqual(response.status_code, 200, response.text)
        inferred = [n for n in response.json()['nodes'] if n['attributes'].get('provenance') == 'model-inferred']
        self.assertEqual(len(inferred), 2)
        self.assertEqual(len({n['id'] for n in inferred}), 2)
        self.assertTrue(all(len(n['repositories']) == 1 for n in inferred))
        self.assertEqual({n['repositories'][0] for n in inferred}, set(repositories))

    def test_provider_cannot_supply_trusted_validation_allowlists(self):
        rid = self.repository()
        jid = self.queue(rid)
        def poisoned(payload, config=None):
            result = self.provider(payload, config)
            body = json.loads(result['output_text'])
            body['validated_node_ids'] = ['invented-source-node']
            body['validated_component_ids'] = ['invented-component']
            return {'output_text': json.dumps(body)}
        with patch('graphifier.agent._response', side_effect=poisoned):
            work_once()
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'], 'completed')
        with connect() as c:
            proposal = json.loads(c.execute('SELECT data FROM analysis_ai_hierarchy WHERE job_id=?', (jid,)).fetchone()[0])
        self.assertEqual(proposal['groups'], [])
        self.assertEqual(proposal['component_summaries'], [])
        self.assertNotIn('invented-source-node', proposal.get('validated_node_ids', []))
        self.assertEqual(proposal['status'], 'partial')


if __name__ == '__main__':
    unittest.main()
