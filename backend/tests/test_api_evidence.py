from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from graphifier.api import app
from graphifier.db import connect
from graphifier.worker import work_once


class EvidenceApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.root=self.base/"repos"; self.root.mkdir()
        os.environ["GRAPHIFIER_DB"]=str(self.base/"db.sqlite3")
        os.environ["GRAPHIFIER_REPO_ROOT"]=str(self.root)
        self.client=TestClient(app,base_url="http://127.0.0.1")
        self.client.__enter__()
        path=self.root/"demo"; path.mkdir(); self.path=path
        response=self.client.post("/api/repositories",json={"path":str(path)})
        self.assertEqual(response.status_code,200,response.text); self.repo_id=response.json()["id"]

    def tearDown(self):
        self.client.__exit__(None,None,None)
        os.environ.pop("GRAPHIFIER_DB",None); os.environ.pop("GRAPHIFIER_REPO_ROOT",None)
        os.environ.pop("GRAPHIFIER_API_TOKEN",None)
        self.tmp.cleanup()

    def queue_snapshot(self, environment, content):
        (self.path/"query.sql").write_text(content)
        queued=self.client.post("/api/jobs",json={"repo_id":self.repo_id,"environment":environment})
        self.assertEqual(queued.status_code,200,queued.text); self.assertTrue(work_once())
        return queued.json()["id"]

    def test_evidence_uses_snapshot_content_and_skips_warning_strings(self):
        self.queue_snapshot("dev","select value;\n")
        with connect() as c: dev_sid=c.execute("SELECT id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()["id"]
        self.queue_snapshot("prod","select value from source_table;\n")
        dev=self.client.get("/api/evidence",params={"repo_id":self.repo_id,"file":"query.sql","environment":"dev"})
        self.assertEqual(dev.status_code,200,dev.text)
        self.assertEqual(dev.json()["snapshot_id"],dev_sid)
        self.assertEqual(dev.json()["content"],"select value;\n")
        self.assertIsInstance(dev.json()["evidence"],list)
        mismatch=self.client.get("/api/evidence",params={"repo_id":self.repo_id,"file":"query.sql","snapshot_id":dev_sid,"environment":"prod"})
        self.assertEqual(mismatch.status_code,404)
        symbols=self.client.get("/api/symbols",params={"repo_id":self.repo_id,"environment":"dev"})
        self.assertEqual(symbols.status_code,200,symbols.text)

    def test_host_allowlist_and_token_apply_to_reads_but_not_health(self):
        os.environ["GRAPHIFIER_API_TOKEN"]="test-token"
        denied=self.client.get("/api/repositories")
        self.assertEqual(denied.status_code,401)
        self.assertEqual(self.client.get("/api/health").status_code,200)
        wrong_host=TestClient(app,base_url="http://evil.example")
        self.assertEqual(wrong_host.get("/api/health").status_code,403)
        self.assertEqual(self.client.get("/api/repositories",headers={"Authorization":"Bearer test-token"}).status_code,200)


if __name__=="__main__": unittest.main()
