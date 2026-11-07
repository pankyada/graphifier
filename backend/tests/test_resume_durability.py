import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphifier.agent import ModelTransportError
from graphifier.agent_config import save_agent_config
from graphifier.db import connect, init_db
from graphifier.worker import run_job
from graphifier import checkpoints

EMPTY = {"entities": [], "relationships": [], "symbols": [], "warnings": []}


class Crash(BaseException):
    pass


class ResumeDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"GRAPHIFIER_DB": str(self.root / "db.sqlite3"), "GRAPHIFIER_REPO_ROOT": str(self.root), "GRAPHIFIER_AGENT_MAX_STEPS": "0"})
        env.start()
        self.addCleanup(env.stop)
        init_db()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "a.py").write_text("a=1\n")
        (self.repo / "b.py").write_text("b=2\n")
        with connect() as c:
            c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES('repo','repo',?,'now')", (str(self.repo),))
            c.execute("INSERT INTO jobs(id,repo_id,use_agent,status,created_at,updated_at) VALUES('job','repo',1,'running','now','now')")
        self.job = {"id": "job", "repo_id": "repo", "use_agent": 1}
        save_agent_config("http://localhost:8000/v1", "original-model", "responses", api_key="checkpoint-test-secret")

    def restart(self):
        with connect() as c:
            c.execute("UPDATE jobs SET status='running',cancel_requested=0 WHERE id='job'")

    def test_completed_files_reused_and_source_snapshot_immutable(self):
        calls = []
        def first(path, content, sources):
            calls.append(path)
            if path == "b.py":
                raise ModelTransportError("temporary outage")
            return EMPTY
        with patch("graphifier.agent.analyze_file", side_effect=first):
            run_job(self.job)
        with connect() as c:
            self.assertEqual(c.execute("SELECT status FROM jobs").fetchone()[0], "failed")
            self.assertEqual(checkpoints.checkpoint_info(c, "job")["completed_files"], 1)
        (self.repo / "a.py").write_text("changed=100\n")
        (self.repo / "b.py").unlink()
        self.restart()
        def resumed(path, content, sources):
            self.assertEqual(path, "b.py")
            self.assertEqual(content, "b=2\n")
            return EMPTY
        with patch("graphifier.agent.analyze_file", side_effect=resumed) as model:
            run_job(self.job)
            self.assertEqual(model.call_count, 1)
        with connect() as c:
            self.assertEqual(c.execute("SELECT status FROM jobs").fetchone()[0], "completed")
            self.assertEqual(c.execute("SELECT content FROM source_files WHERE file='a.py'").fetchone()[0], "a=1\n")

    def test_crash_after_response_checkpoint_replays_without_remote_request(self):
        original = checkpoints.save_conversation
        crashed = False
        def save(job_id, file, state):
            nonlocal crashed
            original(job_id, file, state)
            if state.get("response") and not crashed:
                crashed = True
                raise Crash()
        with patch("graphifier.agent._response", return_value={"output_text": json.dumps(EMPTY)}) as model, patch("graphifier.checkpoints.save_conversation", side_effect=save):
            with self.assertRaises(Crash):
                run_job(self.job)
            self.assertEqual(model.call_count, 1)
        self.restart()
        with patch("graphifier.agent._response", return_value={"output_text": json.dumps(EMPTY)}) as model:
            run_job(self.job)
            self.assertEqual(model.call_count, 1)  # Only b.py, a.py response was durable.
        with connect() as c:
            state = c.execute("SELECT state FROM analysis_checkpoints").fetchone()[0]
            self.assertNotIn("checkpoint-test-secret", state)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_consolidation_checkpoint_reused_after_crash(self):
        original = checkpoints.save_consolidated
        def save(job_id, data):
            original(job_id, data)
            raise Crash()
        with patch("graphifier.agent.analyze_file", return_value=EMPTY), patch("graphifier.checkpoints.save_consolidated", side_effect=save):
            with self.assertRaises(Crash):
                run_job(self.job)
        self.restart()
        with patch("graphifier.agent.analyze_file") as model, patch("graphifier.consolidation.consolidate_findings") as consolidate:
            run_job(self.job)
            model.assert_not_called()
            consolidate.assert_not_called()
        with connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_changed_provider_fails_without_using_new_key(self):
        with patch("graphifier.agent._response", side_effect=ModelTransportError("outage")):
            run_job(self.job)
        save_agent_config("http://localhost:9000/v1", "other", "responses", api_key="different-secret")
        self.restart()
        with patch("graphifier.agent._response") as model:
            run_job(self.job)
            model.assert_not_called()
        with connect() as c:
            job = c.execute("SELECT status,error FROM jobs").fetchone()
            self.assertEqual(job["status"], "failed")
            self.assertIn("Restore the checkpoint", job["error"])

    def test_published_snapshot_reused_when_embedding_phase_crashes(self):
        self.job["use_embeddings"] = 1
        with connect() as c:
            c.execute("UPDATE jobs SET use_embeddings=1")
        with patch("graphifier.agent.analyze_file", return_value=EMPTY), patch("graphifier.embeddings.index_snapshot", side_effect=Crash()):
            with self.assertRaises(Crash):
                run_job(self.job)
        with connect() as c:
            sid = c.execute("SELECT id FROM snapshots").fetchone()[0]
            self.assertEqual(checkpoints.checkpoint_info(c, "job")["phase"], "embeddings")
        self.restart()
        with patch("graphifier.agent.analyze_file") as model, patch("graphifier.embeddings.index_snapshot", return_value={"chunks": 2}) as embed:
            run_job(self.job)
            model.assert_not_called()
            self.assertEqual(embed.call_args[0][1], sid)
        with connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT status FROM jobs").fetchone()[0], "completed")

    def test_cancelled_tool_conversation_resumes_after_saved_tool_result(self):
        original = checkpoints.save_conversation
        cancelled = False
        response = {"output": [{"type": "function_call", "call_id": "read", "name": "read_source", "arguments": '{"path":"b.py","start_line":1}'}]}
        def save(job_id, file, state):
            nonlocal cancelled
            original(job_id, file, state)
            if state.get("tool_index") == 1 and not cancelled:
                cancelled = True
                with connect() as c:
                    c.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        with patch("graphifier.agent._response", return_value=response) as model, patch("graphifier.checkpoints.save_conversation", side_effect=save):
            run_job(self.job)
            self.assertEqual(model.call_count, 1)
        with connect() as c:
            self.assertEqual(c.execute("SELECT status FROM jobs").fetchone()[0], "cancelled")
        self.restart()
        payloads = []
        def resumed(payload, **kwargs):
            payloads.append(json.loads(json.dumps(payload)))
            return {"output_text": json.dumps(EMPTY)}
        with patch("graphifier.agent._response", side_effect=resumed):
            run_job(self.job)
        outputs = [item for item in payloads[0]["input"] if item.get("type") == "function_call_output"]
        self.assertEqual(len(outputs), 1)
        self.assertIn("b=2", outputs[0]["output"])
        self.assertEqual(len(payloads), 2)
