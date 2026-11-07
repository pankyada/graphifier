import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from graphifier.api import app
from graphifier.db import connect


class ResumeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'GRAPHIFIER_DB': str(root/'db.sqlite3'), 'GRAPHIFIER_REPO_ROOT': str(root), 'GRAPHIFIER_API_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        repo = root/'repo'
        repo.mkdir()
        self.rid = self.client.post('/api/repositories', json={'path': str(repo)}).json()['id']
        self.jid = self.client.post('/api/jobs', json={'repo_id': self.rid, 'use_agent': True}).json()['id']
        with connect() as c:
            c.execute("UPDATE jobs SET status='failed',cancel_requested=1,error='interrupted' WHERE id=?", (self.jid,))

    def test_old_job_is_restart_only(self):
        job = self.client.get('/api/jobs/'+self.jid).json()
        self.assertFalse(job['resumable'])
        self.assertIsNone(job['checkpoint'])
        self.assertEqual(self.client.post('/api/jobs/'+self.jid+'/resume').status_code, 409)

    def test_resume_is_atomic_and_retains_job_mode(self):
        checkpoint = {'phase': 'extracting', 'completed_files': 4, 'total_files': 10, 'current_file': 'main.py'}
        with patch('graphifier.checkpoints.checkpoint_info', return_value=checkpoint):
            self.assertTrue(self.client.get('/api/jobs/'+self.jid).json()['resumable'])
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: self.client.post('/api/jobs/'+self.jid+'/resume'), range(2)))
            self.assertEqual(sorted(response.status_code for response in results), [200, 409])
            job = self.client.get('/api/jobs/'+self.jid).json()
            self.assertEqual(job['id'], self.jid)
            self.assertTrue(job['use_agent'])
            self.assertEqual(job['status'], 'queued')
            self.assertEqual(job['checkpoint']['completed_files'], 4)
        with connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE action='job.resumed'").fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT cancel_requested FROM jobs WHERE id=?', (self.jid,)).fetchone()[0], 0)

    def test_another_active_job_blocks_resume(self):
        self.client.post('/api/jobs', json={'repo_id': self.rid})
        with patch('graphifier.checkpoints.checkpoint_info', return_value={'phase': 'extracting'}):
            response = self.client.post('/api/jobs/'+self.jid+'/resume')
        self.assertEqual(response.status_code, 409)
        with connect() as c:
            self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?', (self.jid,)).fetchone()[0], 'failed')
