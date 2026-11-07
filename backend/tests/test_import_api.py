from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from graphifier.api import app


class ImportApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            'GRAPHIFIER_DB': str(root / 'test.sqlite3'),
            'GRAPHIFIER_REPO_ROOT': str(root / 'repos'),
            'GRAPHIFIER_API_TOKEN': '',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_queue_get_cancel_retry_and_no_early_registration(self):
        response = self.client.post('/api/repository-imports', json={'url': 'https://github.com/example/demo.git', 'branch': 'main', 'name': 'Demo'})
        self.assertEqual(response.status_code, 200, response.text)
        queued = response.json()
        self.assertEqual(queued['status'], 'queued')
        self.assertIsNone(queued['repo_id'])
        self.assertEqual(self.client.get('/api/repositories').json()['repositories'], [])
        self.assertEqual(self.client.get('/api/repository-imports/' + queued['id']).json()['id'], queued['id'])
        self.assertEqual(len(self.client.get('/api/repository-imports').json()['imports']), 1)
        cancelled = self.client.post('/api/repository-imports/' + queued['id'] + '/cancel')
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()['status'], 'cancelled')
        retry = self.client.post('/api/repository-imports/' + queued['id'] + '/retry')
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()['status'], 'queued')
        self.assertEqual(self.client.get('/api/repositories').json()['repositories'], [])

    def test_rejected_urls_never_echo_secret_or_create_jobs(self):
        for url in ('https://user:test-private-secret@github.com/example/demo.git',
                    'https://github.com/example/demo.git?token=test-private-secret',
                    'file:///tmp/repository',
                    'https://unapproved.invalid/example/demo.git'):
            response = self.client.post('/api/repository-imports', json={'url': url})
            self.assertIn(response.status_code, (400, 422), response.text)
            self.assertNotIn('test-private-secret', response.text)
        self.assertEqual(self.client.get('/api/repository-imports').json()['imports'], [])


if __name__ == '__main__':
    unittest.main()
