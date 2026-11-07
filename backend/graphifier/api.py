from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .db import connect, init_db, json_data
from .paths import allowed_root, checked_path
from .resolution import propose as propose_resolution, transition

app = FastAPI(title="Graphifier API", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(("/api/settings/agent", "/api/repository-imports")):
        # Validation responses must not echo write-only credentials from request input.
        errors = [{key: error[key] for key in ("loc", "msg", "type") if key in error} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})
    return await request_validation_exception_handler(request, exc)


def stamp(): return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def startup():
    allowed_root().mkdir(parents=True, exist_ok=True)
    init_db()


def _authorize(request: Request, require_token: bool = True):
    def local_host(value: str | None) -> bool:
        if not value: return False
        try: host=urlparse(f"//{value}").hostname or ""
        except ValueError: return False
        return host.lower() in {"localhost","127.0.0.1","::1"}
    if not local_host(request.headers.get("host")):
        raise HTTPException(403,"Only local hosts are allowed")
    origin = request.headers.get("origin")
    if origin:
        try: parsed_origin=urlparse(origin); host=parsed_origin.hostname or ""
        except ValueError: raise HTTPException(403,"Invalid Origin header")
        if parsed_origin.scheme not in {"http","https"} or parsed_origin.path not in {"","/"} or parsed_origin.username or parsed_origin.password:
            raise HTTPException(403,"Invalid Origin header")
        if host.lower() not in {"localhost","127.0.0.1","::1"}: raise HTTPException(403,"Non-local origins are not allowed")
    token = os.environ.get("GRAPHIFIER_API_TOKEN")
    if require_token and token and request.headers.get("authorization") != f"Bearer {token}": raise HTTPException(401,"Bearer token required")


@app.middleware("http")
async def protect_writes(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        try: _authorize(request,require_token=request.url.path!="/api/health")
        except HTTPException as exc:
            from starlette.responses import JSONResponse
            return JSONResponse({"detail":exc.detail},status_code=exc.status_code)
    return await call_next(request)


def _repo(row): return {key: row[key] for key in ("id", "name", "path", "created_at", "remote_url", "remote_branch", "remote_commit")}


def _job(row, connection=None):
    result={k:row[k] for k in ("id","repo_id","environment","status","progress","total_files","processed_files","error","commit_hash","snapshot_hash","created_at","updated_at")}
    result["use_agent"]=bool(row["use_agent"])
    result["use_embeddings"]=bool(row["use_embeddings"]) if "use_embeddings" in row.keys() else False
    result["use_ai_hierarchy"]=bool(row["use_ai_hierarchy"]) if "use_ai_hierarchy" in row.keys() else False
    from .checkpoints import checkpoint_info
    if connection is None:
        with connect() as c:
            checkpoint = checkpoint_info(c, row["id"])
    else:
        checkpoint = checkpoint_info(connection, row["id"])
    result["checkpoint"] = checkpoint
    result["resumable"] = bool(checkpoint and checkpoint["phase"] != "completed" and row["status"] in {"failed", "cancelled"})
    return result


class RepoIn(BaseModel):
    path: str
    name: str | None = None


class RepositoryImportIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    branch: str | None = Field(default=None, max_length=250)
    name: str | None = Field(default=None, max_length=200)


class JobIn(BaseModel):
    repo_id: str
    environment: str = "default"
    use_agent: bool = False
    use_embeddings: bool = False
    use_ai_hierarchy: bool = False
    force: bool = False


class EmbeddingSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    repo_id: str | None = None
    environment: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class ResolutionIn(BaseModel):
    repo_id: str
    environment: str
    symbol: str
    expression: str
    default_value: str | None = None
    actor: str | None = None


class TransitionIn(BaseModel):
    expected_version: int = Field(ge=1)
    actor: str | None = None


class AgentSettingsIn(BaseModel):
    base_url: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=500)
    api_mode: Literal["responses", "chat_completions"]
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    hierarchy_model: str | None = Field(default=None, min_length=1, max_length=500)
    hierarchy_reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    api_key: str | None = Field(default=None, max_length=8192, repr=False)
    clear_api_key: bool = False


class Neo4jSyncIn(BaseModel):
    repo_id: str | None = None
    environment: str | None = None


@app.get("/api/health")
def health(): return {"status":"ok","version":app.version}


@app.get("/api/repositories")
def repositories():
    with connect() as c: rows=c.execute("SELECT * FROM repositories ORDER BY created_at").fetchall()
    return {"repositories":[_repo(x) for x in rows]}


@app.post("/api/repositories")
def register_repo(body: RepoIn):
    try: path=checked_path(body.path)
    except (ValueError,OSError) as e: raise HTTPException(400,str(e))
    rid, name, created = str(uuid.uuid4()), body.name or path.name, stamp()
    with connect() as c:
        existing=c.execute("SELECT * FROM repositories WHERE path=?",(str(path),)).fetchone()
        if existing: return _repo(existing)
        c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES(?,?,?,?)",(rid,name,str(path),created))
    return {"id":rid,"name":name,"path":str(path),"created_at":created}


@app.post("/api/repository-imports")
def import_repository(body: RepositoryImportIn):
    from .git_import import queue_import
    try:
        return queue_import(**body.model_dump())
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/repository-imports")
def repository_imports():
    from .git_import import public_import
    with connect() as c:
        rows = c.execute("SELECT * FROM repository_imports ORDER BY CASE WHEN status IN ('queued','cloning') THEN 0 ELSE 1 END,updated_at DESC LIMIT 100").fetchall()
    return {"imports": [public_import(row) for row in rows]}


@app.get("/api/repository-imports/{import_id}")
def repository_import(import_id: str):
    from .git_import import public_import
    with connect() as c:
        row = c.execute("SELECT * FROM repository_imports WHERE id=?", (import_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Repository import not found")
    return public_import(row)


@app.post("/api/repository-imports/{import_id}/cancel")
def cancel_repository_import(import_id: str):
    from .git_import import cancel_import
    try:
        return cancel_import(import_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/repository-imports/{import_id}/retry")
def retry_repository_import(import_id: str):
    from .git_import import retry_import
    try:
        return retry_import(import_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/browse")
def browse(path: str = ""):
    try: parent=checked_path(path or allowed_root())
    except (ValueError,OSError) as e: raise HTTPException(400,str(e))
    try: entries=[]
    except Exception: entries=[]
    for child in sorted(parent.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower())):
        if child.name.startswith(".") or child.is_symlink(): continue
        try: checked=checked_path(child)
        except (ValueError,OSError): continue
        if checked.is_dir(): entries.append({"name":child.name,"path":str(checked),"is_dir":True})
    return {"path":str(parent),"entries":entries}


@app.get("/api/jobs")
def jobs(repo_id: str | None = None):
    with connect() as c:
        rows=c.execute("SELECT * FROM jobs WHERE (? IS NULL OR repo_id=?) ORDER BY created_at DESC LIMIT 100",(repo_id,repo_id)).fetchall()
    return {"jobs":[_job(x) for x in rows]}


@app.post("/api/jobs")
def queue_job(body: JobIn):
    jid, created=str(uuid.uuid4()),stamp()
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM repositories WHERE id=?",(body.repo_id,)).fetchone(): raise HTTPException(404,"Repository not found")
        if not body.force:
            active=c.execute("SELECT * FROM jobs WHERE repo_id=? AND environment=? AND status IN ('queued','running') ORDER BY created_at LIMIT 1",(body.repo_id,body.environment)).fetchone()
            if active: return _job(active, c)
        c.execute("INSERT INTO jobs(id,repo_id,environment,use_agent,use_embeddings,use_ai_hierarchy,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(jid,body.repo_id,body.environment,1 if body.use_agent else 0,1 if body.use_embeddings else 0,1 if body.use_ai_hierarchy else 0,"queued",created,created))
        c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)",(body.repo_id,jid,"job.queued",json_data({"environment":body.environment,"use_agent":body.use_agent,"use_embeddings":body.use_embeddings}),created))
        row=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
    return _job(row)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with connect() as c: row=c.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not row: raise HTTPException(404,"Job not found")
    return _job(row)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    with connect() as c:
        row=c.execute("SELECT status FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not row: raise HTTPException(404,"Job not found")
        if row["status"] in ("queued","running"):
            c.execute("UPDATE jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated_at=? WHERE id=?",(stamp(),job_id))
        row=c.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    return _job(row)


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    from .checkpoints import checkpoint_info
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Job not found")
        if row["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, "Only failed or cancelled jobs can be resumed")
        checkpoint = checkpoint_info(c, job_id)
        if checkpoint is None or checkpoint["phase"] == "completed":
            raise HTTPException(409, "This job has no resumable checkpoint. Start a new analysis.")
        active = c.execute("SELECT id FROM jobs WHERE repo_id=? AND environment=? AND id<>? AND status IN ('queued','running') LIMIT 1", (row["repo_id"], row["environment"], job_id)).fetchone()
        if active:
            raise HTTPException(409, "Another analysis is queued or running for this repository and environment")
        updated = stamp()
        c.execute("UPDATE jobs SET status='queued',cancel_requested=0,error=NULL,updated_at=? WHERE id=?", (updated, job_id))
        c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (row["repo_id"], job_id, "job.resumed", json_data(checkpoint), updated))
        result = _job(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(), c)
    return result


def latest_snapshot(c, repo_id, environment=None):
    row=c.execute("SELECT s.id FROM snapshots s JOIN jobs j ON j.id=s.job_id WHERE s.repo_id=? AND j.status='completed' AND (? IS NULL OR j.environment=?) ORDER BY s.created_at DESC,s.rowid DESC LIMIT 1",(repo_id,environment,environment)).fetchone()
    return row["id"] if row else None


@app.get("/api/graph")
def graph(repo_id: str | None = None, environment: str | None = None, context: str | None = None, namespace: str | None = None, view: Literal["all", "flow", "constellation"] = "all", max_nodes: int | None = Query(default=None, ge=1, le=5000), focus_id: str | None = None, query: str | None = Query(default=None, max_length=500), granularity: Literal["overview", "interfaces", "detail"] | None = None, scope_id: str | None = None, generation: str | None = None, include_tests: bool = False, offset: int = Query(default=0, ge=0), hierarchy_mode: Literal["ai", "deterministic"] = "ai"):
    from .graph import build_graph
    environment=environment if environment is not None else context
    from .graph_store import GenerationError
    try:
        result=build_graph(repo_id=repo_id,environment=environment,namespace=namespace,view=view,max_nodes=max_nodes or 800,focus_id=focus_id,query=query,granularity=granularity,scope_id=scope_id,generation=generation,include_tests=include_tests,offset=offset,hierarchy_mode=hierarchy_mode)
    except GenerationError as exc:
        raise HTTPException(409,str(exc))
    result.setdefault("context",environment)
    return result


@app.get("/api/graph/edge-support")
def graph_edge_support(generation: str, edge_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)):
    from .graph_store import edge_support, GenerationError
    try:
        return edge_support(generation,edge_id,offset,limit)
    except GenerationError as exc:
        raise HTTPException(409,str(exc))


@app.get("/api/graph/location")
def graph_location(generation: str, node_id: str):
    from .graph_store import location, GenerationError
    try:
        return location(generation,node_id)
    except GenerationError as exc:
        raise HTTPException(409,str(exc))


@app.get("/api/symbols")
def symbols(repo_id: str, environment: str | None = None):
    with connect() as c:
        sid=latest_snapshot(c,repo_id,environment)
        if not sid: return {"repo_id":repo_id,"environment":environment,"symbols":[]}
        rows=c.execute("SELECT * FROM symbols WHERE repo_id=? AND snapshot_id=? ORDER BY name",(repo_id,sid)).fetchall()
        bound={r["symbol"]:dict(r) for r in c.execute("SELECT * FROM resolutions WHERE repo_id=? AND environment=? AND status='applied'",(repo_id,environment)).fetchall()} if environment else {}
    return {"repo_id":repo_id,"environment":environment,"namespace":repo_id,"system":os.environ.get("GRAPHIFIER_SYSTEM","local-workspace"),"symbols":[{"name":r["name"],"expression":r["expression"],"default_value":r["default_value"],"method":r["method"],"evidence":__import__("json").loads(r["evidence"]),"resolved":r["name"] in bound,"resolution":bound.get(r["name"])} for r in rows]}


@app.get("/api/evidence")
def evidence(repo_id: str, file: str, snapshot_id: str | None = None, environment: str | None = None):
    with connect() as c:
        if snapshot_id:
            owner=c.execute("SELECT s.id FROM snapshots s JOIN jobs j ON j.id=s.job_id WHERE s.id=? AND s.repo_id=? AND j.status='completed' AND (? IS NULL OR j.environment=?)",(snapshot_id,repo_id,environment,environment)).fetchone()
            if not owner: raise HTTPException(404,"Snapshot not found for repository and environment")
            sid=owner["id"]
        else: sid=latest_snapshot(c,repo_id,environment)
        if not sid: return {"repo_id":repo_id,"file":file,"content":None,"sha256":None,"evidence":[]}
        source=c.execute("SELECT content,sha256 FROM source_files WHERE repo_id=? AND snapshot_id=? AND file=?",(repo_id,sid,file)).fetchone()
        rows=c.execute("SELECT category,data FROM findings WHERE repo_id=? AND snapshot_id=?",(repo_id,sid)).fetchall()
        syms=c.execute("SELECT name,expression,evidence,method FROM symbols WHERE repo_id=? AND snapshot_id=?",(repo_id,sid)).fetchall()
    out=[]
    for r in rows:
        v=__import__("json").loads(r["data"])
        if not isinstance(v,dict): continue
        spans = v.get("evidence_spans") or [v.get("evidence", {})]
        for ev in spans:
            if isinstance(ev, dict) and ev.get("file") == file:
                out.append({"category": r["category"], "item": v, "evidence": ev})
    for s in syms:
        ev=__import__("json").loads(s["evidence"])
        if ev.get("file")==file: out.append({"category":"symbol","item":{"name":s["name"],"expression":s["expression"],"method":s["method"]},"evidence":ev})
    return {"repo_id":repo_id,"file":file,"snapshot_id":sid,"environment":environment,"content":source["content"] if source else None,"sha256":source["sha256"] if source else None,"evidence":out}


@app.get("/api/trace")
def trace(entity_id: str, direction: str = "both", repo_id: str | None = None, environment: str | None = None, namespace: str | None = None, view: Literal["all", "flow", "constellation"] = "all", max_nodes: int | None = Query(default=None, ge=1, le=5000), granularity: Literal["overview", "interfaces", "detail"] | None = None, include_tests: bool = False, generation: str | None = None, hierarchy_mode: Literal["ai", "deterministic"] = "ai"):
    if direction not in {"both","in","out"}: raise HTTPException(400,"direction must be both, in, or out")
    from .graph import trace_graph
    from .graph_store import GenerationError
    try:
        return trace_graph(entity_id=entity_id,direction=direction,repo_id=repo_id,environment=environment,namespace=namespace,view=view,max_nodes=max_nodes or 800,granularity=granularity,include_tests=include_tests,generation=generation,hierarchy_mode=hierarchy_mode)
    except GenerationError as exc:
        raise HTTPException(409,str(exc))


@app.get("/api/resolutions")
def resolutions(repo_id: str, environment: str | None = None):
    with connect() as c:
        rows=c.execute("SELECT * FROM resolutions WHERE repo_id=? AND (? IS NULL OR environment=?) ORDER BY created_at DESC",(repo_id,environment,environment)).fetchall()
    return {"resolutions":[dict(r) for r in rows]}


@app.post("/api/resolutions/propose")
def resolution_propose(body: ResolutionIn, request: Request):
    with connect() as c:
        if not c.execute("SELECT 1 FROM repositories WHERE id=?",(body.repo_id,)).fetchone(): raise HTTPException(404,"Repository not found")
    try:
        payload=body.model_dump()
        payload["actor"]=body.actor or request.headers.get("x-graphifier-actor")
        result=propose_resolution(**payload)
        from .graph import preview_binding
        result["preview"]=preview_binding(result)
        return result
    except ValueError as e: raise HTTPException(400,str(e))


@app.get("/api/resolutions/{resolution_id}/preview")
def resolution_preview(resolution_id: str):
    from .graph import preview_binding
    with connect() as c:
        row=c.execute("SELECT * FROM resolutions WHERE id=?",(resolution_id,)).fetchone()
        if not row: raise HTTPException(404,"Resolution not found")
        proposal=dict(row)
    return {"resolution":proposal,"expected_version":proposal["version"],"preview":preview_binding(proposal)}


def _transition(resolution_id, body, action, request):
    actor=body.actor or request.headers.get("x-graphifier-actor")
    try: return transition(resolution_id,body.expected_version,action,actor)
    except LookupError as e: raise HTTPException(404,str(e))
    except RuntimeError as e: raise HTTPException(409,str(e))


@app.post("/api/resolutions/{resolution_id}/apply")
def resolution_apply(resolution_id: str, body: TransitionIn, request: Request): return _transition(resolution_id,body,"apply",request)


@app.post("/api/resolutions/{resolution_id}/retract")
def resolution_retract(resolution_id: str, body: TransitionIn, request: Request): return _transition(resolution_id,body,"retract",request)


@app.get("/api/settings")
def settings():
    from .agent_config import public_agent_config
    return {
        "repo_root": str(allowed_root()),
        "system": os.environ.get("GRAPHIFIER_SYSTEM", "local-workspace"),
        "agent": public_agent_config(),
        "embeddings": {
            "enabled": bool(os.environ.get("GRAPHIFIER_EMBEDDING_MODEL")),
            "model": os.environ.get("GRAPHIFIER_EMBEDDING_MODEL", ""),
        },
        "neo4j": {"enabled": bool(os.environ.get("NEO4J_URI")), "uri_configured": bool(os.environ.get("NEO4J_URI"))},
        "api_token_required": bool(os.environ.get("GRAPHIFIER_API_TOKEN")),
    }


@app.post("/api/settings/agent")
def save_agent_settings(body: AgentSettingsIn):
    from .agent_config import save_agent_config
    try:
        return save_agent_config(**body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/settings/agent/test")
def test_agent_settings(body: AgentSettingsIn):
    from .agent_config import candidate_agent_config, test_agent_connection
    try:
        return test_agent_connection(candidate_agent_config(**body.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/neo4j/sync")
def neo4j_sync(body: Neo4jSyncIn):
    from .neo4j_adapter import sync_repo
    try: return sync_repo(repo_id=body.repo_id,environment=body.environment)
    except RuntimeError as e: raise HTTPException(503,str(e))


@app.get("/api/embeddings/status")
def embeddings_status(repo_id: str | None = None, environment: str | None = None):
    from .embeddings import status
    return status(repo_id=repo_id, environment=environment)


@app.post("/api/embeddings/search")
def embeddings_search(body: EmbeddingSearchIn):
    from .embeddings import search
    try:
        return search(query=body.query, repo_id=body.repo_id, environment=body.environment, limit=body.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
