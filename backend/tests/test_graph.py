from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from graphifier import graph
from graphifier.db import connect, init_db
from graphifier.resolution import propose, transition


class GraphBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRAPHIFIER_DB")
        os.environ["GRAPHIFIER_DB"] = str(Path(self.tmp.name) / "graph.sqlite3")
        init_db()

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("GRAPHIFIER_DB", None)
        else:
            os.environ["GRAPHIFIER_DB"] = self.old_db
        self.tmp.cleanup()

    def _snapshot(self, repo_id: str, job_id: str, snapshot_id: str, created: str):
        with connect() as c:
            c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES(?,?,?,?)",
                      (repo_id, repo_id, f"/tmp/{repo_id}", created))
            c.execute("INSERT INTO jobs(id,repo_id,environment,status,created_at,updated_at) VALUES(?,?,?,'completed',?,?)",
                      (job_id, repo_id, "dev", created, created))
            c.execute("INSERT INTO snapshots(id,repo_id,job_id,content_hash,created_at) VALUES(?,?,?,?,?)",
                      (snapshot_id, repo_id, job_id, f"hash-{snapshot_id}", created))

    def _entity(self, repo_id: str, snapshot_id: str, entity_id: str, kind: str,
                name: str, expression: str | None = None):
        item = {"id": entity_id, "kind": kind, "name": name, "attributes": {},
                "evidence": {"file": f"{repo_id}/source.sql", "start_line": 1, "end_line": 1}}
        if expression is not None:
            item["expression"] = expression
        with connect() as c:
            c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES(?,?,?,?,?)",
                      (repo_id, snapshot_id, "entity", entity_id, json.dumps(item)))

    def _relationship(self, repo_id: str, snapshot_id: str, source: str, target: str, kind: str):
        item = {"source": source, "target": target, "kind": kind,
                "evidence": {"file": f"{repo_id}/source.sql", "start_line": 1, "end_line": 1}}
        with connect() as c:
            c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES(?,?,?,?,?)",
                      (repo_id, snapshot_id, "relationship", f"{source}-{target}-{kind}", json.dumps(item)))

    def test_binding_replaces_sas_python_and_shell_reference_forms(self):
        binding = {"symbol": "RISK_SCORE_TABLE", "expression": "risk.risk_scored"}
        cases = (
            "&RISK_SCORE_TABLE.",
            "{RISK_SCORE_TABLE}",
            "${RISK_SCORE_TABLE}",
            "$RISK_SCORE_TABLE",
        )
        for reference in cases:
            with self.subTest(reference=reference):
                resolved, used = graph._resolved_name(
                    {"name": reference, "expression": reference}, [binding]
                )
                self.assertEqual(resolved, "risk.risk_scored")
                self.assertEqual([b["symbol"] for b in used], ["RISK_SCORE_TABLE"])
        self.assertIsNone(graph._resolved_name(
            {"name": "&RISK_SCORE_TABLE_EXTRA", "expression": "&RISK_SCORE_TABLE_EXTRA"}, [binding]
        )[0])

    def test_preview_cross_repo_merge_apply_retract_and_trace(self):
        self._snapshot("repo-a", "job-a", "snapshot-a", "2026-11-03T00:00:00Z")
        self._snapshot("repo-b", "job-b", "snapshot-b", "2026-11-03T00:00:01Z")
        self._entity("repo-a", "snapshot-a", "repo-a:reference", "dataset",
                     "${RISK_SCORE_TABLE}", "${RISK_SCORE_TABLE}")
        self._entity("repo-a", "snapshot-a", "repo-a:transform", "transformation", "score model")
        self._relationship("repo-a", "snapshot-a", "repo-a:reference", "repo-a:transform", "INPUT_TO")
        self._entity("repo-b", "snapshot-b", "repo-b:reference", "dataset",
                     "risk.risk_scored")

        base = graph.build_graph(environment="dev")
        self.assertFalse(any(edge["kind"] == "RESOLVES_TO" and edge["source"] == "repo-a:reference"
                             for edge in base["edges"]))
        proposal = propose("repo-a", "dev", "RISK_SCORE_TABLE", "risk.risk_scored")
        preview = graph.preview_binding(proposal)
        self.assertEqual(len(preview["affected_references"]), 1)
        self.assertEqual(preview["affected_references"][0]["reference_id"], "repo-a:reference")
        self.assertGreater(preview["counts"]["edges_added"], 0)
        with connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM resolutions WHERE status='applied'").fetchone()[0], 0)

        transition(proposal["id"], 1, "apply")
        stitched = graph.build_graph(environment="dev")
        canonical = next(node for node in stitched["nodes"]
                         if node["kind"] == "dataset" and node.get("attributes", {}).get("canonical"))
        self.assertEqual(set(canonical["repositories"]), {"repo-a", "repo-b"})
        trace = graph.trace_graph("repo-b:reference", direction="downstream", environment="dev")
        self.assertIn("repo-a:transform", {node["id"] for node in trace["nodes"]})
        self.assertFalse(trace["truncated"])

        transition(proposal["id"], 2, "retract")
        retracted = graph.build_graph(environment="dev")
        canonical_after_retract = next(node for node in retracted["nodes"]
                                       if node["id"] == canonical["id"])
        self.assertEqual(canonical_after_retract["repositories"], ["repo-b"])
        after_trace = graph.trace_graph("repo-b:reference", direction="downstream", environment="dev")
        self.assertNotIn("repo-a:transform", {node["id"] for node in after_trace["nodes"]})


if __name__ == "__main__":
    unittest.main()
