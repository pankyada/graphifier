import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from graphifier.api import app
from graphifier.agent import analyze_file
from graphifier.agent_config import load_agent_config, save_agent_config
from graphifier.db import connect
from graphifier.worker import work_once

EMPTY = {"entities": [], "relationships": [], "symbols": [], "warnings": []}
CONNECTION = {"base_url": "http://localhost:8080/v1", "model": "local-model", "api_mode": "chat_completions"}


class Response:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, *args): return json.dumps(self.body).encode()


class AgentConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"GRAPHIFIER_DB": str(self.root / "db.sqlite3"), "GRAPHIFIER_REPO_ROOT": str(self.root / "repos"), "GRAPHIFIER_API_TOKEN": "", "OPENAI_API_KEY": "inherited-secret", "OPENAI_BASE_URL": "https://api.openai.com/v1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_saved_key_is_write_only_blank_preserves_and_clear_overrides_env(self):
        saved = self.client.post("/api/settings/agent", json={**CONNECTION, "api_key": "new-secret"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertNotIn("new-secret", saved.text)
        self.assertTrue(saved.json()["key_configured"])
        self.client.post("/api/settings/agent", json={**CONNECTION, "api_key": ""})
        self.assertEqual(load_agent_config()["api_key"], "new-secret")
        self.client.post("/api/settings/agent", json={**CONNECTION, "clear_api_key": True})
        self.assertEqual(load_agent_config()["api_key"], "")
        public = self.client.get("/api/settings").json()["agent"]
        self.assertFalse(public["key_configured"])
        self.assertEqual(public["base_url"], CONNECTION["base_url"])
        self.assertNotIn("api_key", public)

    def test_reasoning_effort_persists_and_maps_to_provider_payload(self):
        for mode, field in (("responses", "reasoning"), ("chat_completions", "reasoning_effort")):
            response = self.client.post("/api/settings/agent", json={**CONNECTION, "api_mode": mode, "reasoning_effort": "low", "clear_api_key": True})
            self.assertEqual(response.json()["reasoning_effort"], "low")
            result = {"output_text": json.dumps(EMPTY)} if mode == "responses" else {"choices": [{"message": {"content": json.dumps(EMPTY)}}]}
            with patch("urllib.request.urlopen", return_value=Response(result)) as request:
                analyze_file("x.py", "x=1", {"x.py": "x=1"})
            payload = json.loads(request.call_args[0][0].data)
            self.assertEqual(payload[field], {"effort": "low"} if mode == "responses" else "low")
        self.client.post("/api/settings/agent", json={**CONNECTION, "reasoning_effort": None})
        self.assertIsNone(load_agent_config()["reasoning_effort"])

    def test_invalid_key_is_not_echoed_by_validation(self):
        response = self.client.post("/api/settings/agent", json={**CONNECTION, "api_key": ["secret-value"]})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("secret-value", response.text)
        response = self.client.post("/api/settings/agent", json={**CONNECTION, "base_url": "http://user:secret@localhost/v1"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("user:secret", response.text)

    def test_test_unsaved_connection_lists_models_without_saving(self):
        with patch("urllib.request.urlopen", return_value=Response({"data": [{"id": "local-model"}]})) as request:
            response = self.client.post("/api/settings/agent/test", json={**CONNECTION, "clear_api_key": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["selected_model_available"])
        self.assertEqual(response.json()["models"], ["local-model"])
        sent = request.call_args[0][0]
        self.assertEqual(sent.full_url, "http://localhost:8080/v1/models")
        self.assertIsNone(sent.get_header("Authorization"))
        self.assertFalse(load_agent_config()["saved"])

    def test_analysis_freezes_connection_across_tool_steps(self):
        save_agent_config(**CONNECTION, clear_api_key=True)
        captured = []
        def endpoint(request, **kwargs):
            captured.append((request.full_url, json.loads(request.data), request.get_header("Authorization")))
            if len(captured) == 1:
                save_agent_config(base_url="http://localhost:9000/v1", model="other-model", api_mode="responses", api_key="other-secret")
                return Response({"choices": [{"message": {"tool_calls": [{"id": "read", "type": "function", "function": {"name": "read_source", "arguments": '{"path":"x.py","start_line":1}'}}]}}]})
            return Response({"choices": [{"message": {"content": json.dumps(EMPTY)}}]})
        with patch("urllib.request.urlopen", side_effect=endpoint):
            analyze_file("x.py", "x=1\n", {"x.py": "x=1\n"})
        self.assertEqual(len(captured), 2)
        for url, body, auth in captured:
            self.assertEqual(url, "http://localhost:8080/v1/chat/completions")
            self.assertEqual(body["model"], "local-model")
            self.assertIsNone(auth)

    def test_worker_preserves_cross_file_evidence_and_continues_after_ai_failure(self):
        repo = self.root / "repos" / "cross"
        repo.mkdir()
        (repo / "main.py").write_text("import other\n")
        (repo / "other.py").write_text("# indexed source\nvalue = 1\n")
        rid = self.client.post("/api/repositories", json={"path": str(repo)}).json()["id"]
        jid = self.client.post("/api/jobs", json={"repo_id": rid, "use_agent": True}).json()["id"]
        entity = {"id": "shared", "kind": "dataset", "name": "cross-file-table", "attributes": {}, "evidence": {"file": "other.py", "start_line": 2, "end_line": 2}}
        def analyze(path, content, sources):
            if path == "main.py":
                return {**EMPTY, "entities": [entity]}
            raise RuntimeError("unrepairable extraction")
        with patch("graphifier.agent.analyze_file", side_effect=analyze):
            work_once()
        self.assertEqual(self.client.get(f"/api/jobs/{jid}").json()["status"], "completed")
        other = self.client.get("/api/evidence", params={"repo_id": rid, "file": "other.py"}).json()
        evidence = [entry for entry in other["evidence"] if entry["item"].get("name") == "cross-file-table"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["evidence"]["start_line"], 2)
        self.assertEqual(other["content"], "# indexed source\nvalue = 1\n")
        main = self.client.get("/api/evidence", params={"repo_id": rid, "file": "main.py"}).json()
        self.assertFalse(any(entry["item"].get("name") == "cross-file-table" for entry in main["evidence"]))
        graph = self.client.get("/api/graph", params={"repo_id": rid}).json()
        self.assertTrue(any("AI analysis incomplete" in str(warning) for warning in graph["warnings"]))

    def test_worker_uses_saved_config_and_cancellation_keeps_previous_snapshot(self):
        save_agent_config(**CONNECTION, clear_api_key=True)
        repo = self.root / "repos" / "example"
        repo.mkdir()
        (repo / "x.py").write_text("x=1\n")
        rid = self.client.post("/api/repositories", json={"path": str(repo)}).json()["id"]
        jid = self.client.post("/api/jobs", json={"repo_id": rid, "use_agent": True}).json()["id"]
        with patch("urllib.request.urlopen", return_value=Response({"choices": [{"message": {"content": json.dumps(EMPTY)}}]})) as request:
            self.assertTrue(work_once())
        self.assertEqual(request.call_args[0][0].full_url, "http://localhost:8080/v1/chat/completions")
        self.assertEqual(self.client.get(f"/api/jobs/{jid}").json()["status"], "completed")
        previous = self.client.get("/api/evidence", params={"repo_id": rid, "file": "x.py"}).json()["snapshot_id"]
        (repo / "x.py").write_text("x=2\n")
        next_job = self.client.post("/api/jobs", json={"repo_id": rid, "use_embeddings": True}).json()["id"]
        def cancelled_index(*args, **kwargs):
            self.client.post(f"/api/jobs/{next_job}/cancel")
            raise RuntimeError("cancelled")
        with patch("graphifier.embeddings.index_snapshot", side_effect=cancelled_index):
            self.assertTrue(work_once())
        self.assertEqual(self.client.get(f"/api/jobs/{next_job}").json()["status"], "cancelled")
        evidence = self.client.get("/api/evidence", params={"repo_id": rid, "file": "x.py"}).json()
        self.assertEqual(evidence["snapshot_id"], previous)
        self.assertEqual(evidence["content"], "x=1\n")
        with connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM events WHERE job_id=? AND action='job.completed'", (next_job,)).fetchone())
