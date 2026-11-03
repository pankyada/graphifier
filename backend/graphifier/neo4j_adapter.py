"""Rebuildable, namespaced Neo4j projection for Graphifier graphs."""
from __future__ import annotations

import hashlib
import json
import os

from .graph import build_graph


def _projection_id(system: str, environment: str | None, repo_id: str | None) -> str:
    scope = "\0".join((system, environment or "*", repo_id or "*"))
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def sync_repo(repo_id: str | None = None, environment: str | None = None):
    """Replace one Graphifier projection transactionally; preserve other scopes."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Neo4j integration is not installed") from exc
    uri=os.environ.get("NEO4J_URI"); user=os.environ.get("NEO4J_USER"); password=os.environ.get("NEO4J_PASSWORD")
    if not uri or not user or not password: raise RuntimeError("Neo4j is not configured")
    graph=build_graph(repo_id=repo_id,environment=environment)
    system=graph.get("system") or os.environ.get("GRAPHIFIER_SYSTEM","local-workspace")
    projection_id=_projection_id(system,environment,repo_id)
    nodes=[{"id":str(n.get("id")),"kind":str(n.get("kind","unknown")),"name":str(n.get("name","")),"expression":n.get("expression"),"attributes_json":json.dumps(n.get("attributes",{}),ensure_ascii=False),"evidence_json":json.dumps(n.get("evidence",[]),ensure_ascii=False),"repositories_json":json.dumps(n.get("repositories",[]),ensure_ascii=False),"snapshots_json":json.dumps(n.get("snapshots",[]),ensure_ascii=False)} for n in graph["nodes"]]
    edges=[{"id":str(e.get("id",f"edge:{i}")),"source":str(e.get("source")),"target":str(e.get("target")),"kind":str(e.get("kind","related")),"attributes_json":json.dumps(e.get("attributes",{}),ensure_ascii=False),"evidence_json":json.dumps(e.get("evidence",[]),ensure_ascii=False),"repositories_json":json.dumps(e.get("repositories",[]),ensure_ascii=False)} for i,e in enumerate(graph["edges"])]

    def replace(tx):
        tx.run("MATCH ()-[r:GRAPHIFIER_LINK {projection_id:$projection_id}]-() DELETE r",projection_id=projection_id).consume()
        tx.run("MATCH (n:GraphifierNode {projection_id:$projection_id}) DETACH DELETE n",projection_id=projection_id).consume()
        if nodes:
            tx.run("UNWIND $rows AS row MERGE (n:GraphifierNode {projection_id:$projection_id,id:row.id}) SET n.kind=row.kind,n.name=row.name,n.expression=row.expression,n.attributes_json=row.attributes_json,n.evidence_json=row.evidence_json,n.repositories_json=row.repositories_json,n.snapshots_json=row.snapshots_json",projection_id=projection_id,rows=nodes).consume()
        if edges:
            tx.run("UNWIND $rows AS row MATCH (a:GraphifierNode {projection_id:$projection_id,id:row.source}) MATCH (b:GraphifierNode {projection_id:$projection_id,id:row.target}) MERGE (a)-[r:GRAPHIFIER_LINK {projection_id:$projection_id,id:row.id}]->(b) SET r.kind=row.kind,r.attributes_json=row.attributes_json,r.evidence_json=row.evidence_json,r.repositories_json=row.repositories_json",projection_id=projection_id,rows=edges).consume()

    try:
        with GraphDatabase.driver(uri,auth=(user,password)) as driver:
            driver.verify_connectivity()
            with driver.session() as session:
                session.run("CREATE CONSTRAINT graphifier_projection_node IF NOT EXISTS FOR (n:GraphifierNode) REQUIRE (n.projection_id,n.id) IS UNIQUE").consume()
                session.execute_write(replace)
    except Exception as exc:
        # Driver exceptions can include their connection URI or auth details.
        # Return a generic failure while keeping a useful, nonsecret category.
        return {"status":"failed","repo_id":repo_id,"environment":environment,"system":system,"projection_id":projection_id,"nodes":0,"edges":0,"error":f"Neo4j operation failed ({type(exc).__name__})"}
    return {"status":"synced","repo_id":repo_id,"environment":environment,"system":system,"projection_id":projection_id,"nodes":len(nodes),"edges":len(edges)}
