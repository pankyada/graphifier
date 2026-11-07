from __future__ import annotations

import os
import fcntl
import threading
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from graphifier.db import connect, db_path, init_db
from graphifier.paths import checked_path
from graphifier.resolution import propose, transition
from graphifier.worker import run_job


class BackendRiskCases(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.root=self.base/"repos"
        self.root.mkdir()
        self.db=self.base/"db.sqlite3"
        os.environ["GRAPHIFIER_DB"]=str(self.db)
        os.environ["GRAPHIFIER_REPO_ROOT"]=str(self.root)
        init_db()

    def tearDown(self):
        os.environ.pop("GRAPHIFIER_DB",None)
        os.environ.pop("GRAPHIFIER_REPO_ROOT",None)
        self.tmp.cleanup()

    def repo(self, name):
        rid=str(uuid.uuid4()); path=self.root/name; path.mkdir()
        with connect() as c: c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES(?,?,?,?)",(rid,name,str(path),"now"))
        return rid,path

    def test_resolution_scope_conflict_retract_and_version(self):
        repo_a,_=self.repo("a"); repo_b,_=self.repo("b")
        a=propose(repo_a,"dev","CUSTOMERS","warehouse.dev.customers")
        other_env=propose(repo_a,"prod","CUSTOMERS","warehouse.prod.customers")
        other_repo=propose(repo_b,"dev","CUSTOMERS","warehouse.dev.customers")
        applied=transition(a["id"],1,"apply")
        self.assertEqual(applied["status"],"applied")
        conflict=propose(repo_a,"dev","CUSTOMERS","other.customers")
        self.assertIsNotNone(conflict["conflict"])
        with self.assertRaisesRegex(RuntimeError,"already exists"):
            transition(conflict["id"],1,"apply")
        with self.assertRaisesRegex(RuntimeError,"Version conflict"):
            transition(a["id"],1,"retract")
        retracted=transition(a["id"],2,"retract")
        self.assertEqual(retracted["status"],"retracted")
        self.assertEqual(other_env["status"],"proposed")
        self.assertEqual(other_repo["status"],"proposed")

    def test_concurrent_apply_allows_only_one_live_scope_binding(self):
        repo,_=self.repo("concurrent")
        first=propose(repo,"dev","CUSTOMERS","warehouse.dev.customers")
        second=propose(repo,"dev","CUSTOMERS","warehouse.other_customers")
        barrier=threading.Barrier(2)
        def apply(proposal):
            barrier.wait(timeout=5)
            try:
                transition(proposal["id"],1,"apply")
                return "applied"
            except RuntimeError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(apply,(first,second)))
        self.assertEqual(results.count("applied"),1,results)
        with connect() as c:
            count=c.execute("SELECT COUNT(*) FROM resolutions WHERE repo_id=? AND environment='dev' AND symbol='CUSTOMERS' AND status='applied'",(repo,)).fetchone()[0]
            index=c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='resolutions_live_scope_idx'").fetchone()
        self.assertEqual(count,1)
        self.assertIsNotNone(index)

    def test_repository_path_traversal_and_symlink_escape_rejected(self):
        outside=self.base/"outside"; outside.mkdir()
        with self.assertRaises(ValueError): checked_path(self.root/".."/"outside")
        link=self.root/"escape"; link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): checked_path(link)

    def test_connection_context_closes_after_transaction(self):
        conn=connect()
        with conn: conn.execute("SELECT 1")
        with self.assertRaisesRegex(Exception,"closed"):
            conn.execute("SELECT 1")

    def test_worker_records_failure_without_partial_snapshot(self):
        rid,path=self.repo("broken")
        (path/"x.py").write_text("x=1\n")
        jid=str(uuid.uuid4())
        with connect() as c: c.execute("INSERT INTO jobs(id,repo_id,status,created_at,updated_at) VALUES(?,?,'running','now','now')",(jid,rid))
        with patch("graphifier.worker._extract",side_effect=RuntimeError("intentional parser failure")):
            run_job({"id":jid,"repo_id":rid,"use_agent":0})
        with connect() as c:
            job=c.execute("SELECT status,error FROM jobs WHERE id=?",(jid,)).fetchone()
            count=c.execute("SELECT COUNT(*) FROM snapshots WHERE job_id=?",(jid,)).fetchone()[0]
        self.assertEqual(job["status"],"failed")
        self.assertIn("intentional parser failure",job["error"])
        self.assertEqual(count,0)

    def test_agent_findings_keep_provenance_and_calls_are_bounded(self):
        rid,path=self.repo("agent")
        for i in range(21): (path/f"f{i}.py").write_text(f"value = {i}\n")
        jid=str(uuid.uuid4())
        with connect() as c: c.execute("INSERT INTO jobs(id,repo_id,use_agent,status,created_at,updated_at) VALUES(?,?,1,'running','now','now')",(jid,rid))
        agent_result={"entities":[{"id":"model-id","kind":"dataset","name":"table","expression":None,"attributes":{},"evidence":{"file":"f0.py","start_line":1,"end_line":1}}],"relationships":[],"symbols":[{"name":"P","expression":"&P","default_value":"table","evidence":{"file":"f0.py","start_line":1,"end_line":1}}],"warnings":[]}
        calls=[]
        def fake_agent(filename,content,sources):
            calls.append(filename)
            if filename=="f0.py": return agent_result
            return {"entities":[],"relationships":[],"symbols":[],"warnings":[]}
        def fake_extract(path_text,content):
            filename=Path(path_text).name
            return {"entities":[{"id":"static-id","kind":"dataset","name":"table","attributes":{},"evidence":{"file":filename,"start_line":1,"end_line":1}}] if filename=="f0.py" else [],"relationships":[],"symbols":[],"warnings":[]}
        with patch.dict(os.environ, {"GRAPHIFIER_AGENT_MAX_FILES": "20"}), patch("graphifier.worker._extract",side_effect=fake_extract), patch("graphifier.agent.analyze_file",side_effect=fake_agent):
            run_job({"id":jid,"repo_id":rid,"use_agent":1})
        self.assertEqual(len(calls),20)
        with connect() as c:
            entity=c.execute("SELECT data FROM findings WHERE repo_id=? AND category='entity' ORDER BY id LIMIT 1",(rid,)).fetchone()
            symbol=c.execute("SELECT method FROM symbols WHERE repo_id=? AND name='P'",(rid,)).fetchone()
            warnings=[r[0] for r in c.execute("SELECT data FROM findings WHERE repo_id=? AND category='warning'",(rid,)).fetchall()]
        import json
        entity_data=json.loads(entity["data"])
        self.assertEqual(entity_data["attributes"]["method"],"model-inferred")
        self.assertTrue(entity_data["attributes"]["also_static"])
        self.assertEqual(symbol["method"],"model-inferred")
        self.assertTrue(any("agent file limit reached" in warning for warning in warnings))

    def test_second_worker_does_not_recover_active_jobs(self):
        rid,_=self.repo("locked")
        jid=str(uuid.uuid4())
        with connect() as c: c.execute("INSERT INTO jobs(id,repo_id,status,created_at,updated_at) VALUES(?,?,'running','now','now')",(jid,rid))
        lock_path=db_path().with_suffix(".worker.lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch("sys.argv",["graphifier.worker","--once"]), self.assertRaises(SystemExit):
                from graphifier.worker import main
                main()
        with connect() as c: status=c.execute("SELECT status FROM jobs WHERE id=?",(jid,)).fetchone()[0]
        self.assertEqual(status,"running")


if __name__=="__main__": unittest.main()
