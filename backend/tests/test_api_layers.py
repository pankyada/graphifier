from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from graphifier.api import app
from graphifier.worker import work_once


class LayerApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            'GRAPHIFIER_DB': str(self.root / 'test.sqlite3'),
            'GRAPHIFIER_REPO_ROOT': str(self.root),
            'GRAPHIFIER_API_TOKEN': '',
            'GRAPHIFIER_EMBEDDING_MODEL': '',
        })
        self.env.start()
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / 'main.sql').write_text('create table reporting.result as select a from source.input;')
        self.repo_id = self.client.post('/api/repositories', json={'path': str(repo)}).json()['id']

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    def test_graph_views_validate_bound_and_search_outside_default_selection(self):
        self.client.post('/api/jobs', json={'repo_id': self.repo_id})
        self.assertTrue(work_once())
        for view in ('all', 'flow', 'constellation'):
            response = self.client.get('/api/graph', params={'repo_id': self.repo_id, 'view': view, 'max_nodes': 2})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertLessEqual(len(response.json()['nodes']), 2)
        result = self.client.get('/api/graph', params={'repo_id': self.repo_id, 'query': 'reporting.result', 'max_nodes': 2})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(any('reporting.result' in node['name'] for node in result.json()['nodes']))
        for level in ('overview', 'interfaces', 'detail'):
            response = self.client.get('/api/graph', params={'repo_id': self.repo_id, 'view': 'constellation', 'granularity': level})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['granularity'], level)
        self.assertEqual(self.client.get('/api/graph', params={'granularity': 'invalid'}).status_code, 422)
        self.assertEqual(self.client.get('/api/graph', params={'view': 'invalid'}).status_code, 422)
        self.assertEqual(self.client.get('/api/graph', params={'max_nodes': 5001}).status_code, 422)

    def test_embeddings_are_explicit_and_search_errors_are_bounded(self):
        job = self.client.post('/api/jobs', json={'repo_id': self.repo_id}).json()
        self.assertFalse(job['use_embeddings'])
        status = self.client.get('/api/embeddings/status', params={'repo_id': self.repo_id})
        self.assertEqual(status.status_code, 200, status.text)
        self.assertFalse(status.json()['enabled'])
        self.assertEqual(self.client.post('/api/embeddings/search', json={'query': '', 'limit': 10}).status_code, 422)
        with patch('graphifier.embeddings.search', side_effect=RuntimeError('Embedding request failed')):
            result = self.client.post('/api/embeddings/search', json={'query': 'risk score', 'repo_id': self.repo_id})
            self.assertEqual(result.status_code, 503)
        with patch('graphifier.embeddings.search', return_value={'matches': [], 'model': 'test'}) as search:
            result = self.client.post('/api/embeddings/search', json={'query': 'risk score', 'repo_id': self.repo_id, 'environment': 'dev', 'limit': 3})
            self.assertEqual(result.status_code, 200)
            search.assert_called_once_with(query='risk score', repo_id=self.repo_id, environment='dev', limit=3)


if __name__ == '__main__':
    unittest.main()
