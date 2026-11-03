from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from graphifier.neo4j_adapter import sync_repo


class FakeTx:
    def __init__(self): self.calls=[]
    def run(self, query, **params):
        self.calls.append((query,params))
        return types.SimpleNamespace(consume=lambda: None)


class Neo4jProjectionTests(unittest.TestCase):
    def test_aggregate_sync_merges_stitched_nodes_and_scopes_replacement(self):
        tx=FakeTx()
        class Session:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def run(self,query,**params):
                tx.calls.append((query,params))
                return types.SimpleNamespace(consume=lambda: None)
            def execute_write(self,fn): return fn(tx)
        class Driver:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def verify_connectivity(self): pass
            def session(self): return Session()
        fake=types.SimpleNamespace(GraphDatabase=types.SimpleNamespace(driver=lambda *_a,**_k: Driver()))
        graph={"system":"local-workspace","nodes":[{"id":"physical:canonical","kind":"dataset","name":"db.table","repositories":["r1","r2"]}],"edges":[{"id":"resolve:1","source":"r1:source","target":"physical:canonical","kind":"RESOLVES_TO"}]}
        with patch.dict(os.environ,{"NEO4J_URI":"bolt://hidden.example","NEO4J_USER":"secret-user","NEO4J_PASSWORD":"secret-pass"}), patch.dict(sys.modules,{"neo4j":fake}), patch("graphifier.neo4j_adapter.build_graph",return_value=graph) as builder:
            result=sync_repo()
        self.assertEqual(result["status"],"synced")
        self.assertEqual(result["nodes"],1)
        builder.assert_called_once_with(repo_id=None,environment=None)
        queries=" ".join(call[0] for call in tx.calls)
        self.assertIn("(n.projection_id,n.id) IS UNIQUE", queries)
        self.assertIn("MERGE (n:GraphifierNode", queries)
        scoped=[(query,params) for query,params in tx.calls if "projection_id:$projection_id" in query]
        self.assertTrue(scoped)
        self.assertTrue(all(params.get("projection_id")==result["projection_id"] for _,params in scoped))

    def test_failed_sync_does_not_expose_credentials(self):
        class Driver:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def verify_connectivity(self): raise RuntimeError("bolt://secret.example secret-pass")
        fake=types.SimpleNamespace(GraphDatabase=types.SimpleNamespace(driver=lambda *_a,**_k: Driver()))
        with patch.dict(os.environ,{"NEO4J_URI":"bolt://secret.example","NEO4J_USER":"secret-user","NEO4J_PASSWORD":"secret-pass"}), patch.dict(sys.modules,{"neo4j":fake}), patch("graphifier.neo4j_adapter.build_graph",return_value={"system":"local-workspace","nodes":[],"edges":[]}):
            result=sync_repo()
        self.assertEqual(result["status"],"failed")
        self.assertNotIn("secret",result["error"])
        self.assertNotIn("bolt://",result["error"])


if __name__=="__main__": unittest.main()
