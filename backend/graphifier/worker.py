from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, init_db, json_data
from .paths import checked_path, safe_files


class ModelConfigurationChanged(Exception):
    pass


def stamp(): return datetime.now(timezone.utc).isoformat()


def claim_job():
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row: return None
        c.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'", (stamp(),row["id"]))
        return dict(row)


def is_cancelled(job_id):
    with connect() as c:
        row = c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
        return not row or bool(row[0])


def update_job(job_id, **fields):
    fields["updated_at"] = stamp()
    assignments = ",".join(f"{k}=?" for k in fields)
    with connect() as c: c.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*fields.values(),job_id))


def git_commit(root: Path):
    try:
        r = subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True,timeout=3)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception: return None


def scoped_id(repo_id, raw): return f"{repo_id}:{raw}"


def _extract(path, content):
    from .extraction import extract_file
    result = extract_file(str(path), content)
    if not isinstance(result,dict): raise ValueError("extract_file returned a non-object result")
    for key in ("entities","relationships","symbols","warnings"):
        if not isinstance(result.get(key,[]),list): raise ValueError(f"extract_file {key} must be a list")
    return result


class SnapshotSources(Mapping):
    """Disk-backed immutable scan input shared by extraction and agent tools."""
    def __init__(self, directory, cancelled):
        import sqlite3
        self.connection = sqlite3.connect(str(Path(directory) / "sources.sqlite3"))
        self.connection.execute("CREATE TABLE sources(path TEXT PRIMARY KEY,content TEXT,sha256 TEXT)")
        self.cancelled = cancelled

    def add(self, path, content):
        digest = hashlib.sha256(content.encode()).hexdigest()
        self.connection.execute("INSERT INTO sources VALUES(?,?,?)", (path, content, digest))

    def __getitem__(self, path):
        row = self.connection.execute("SELECT content FROM sources WHERE path=?", (path,)).fetchone()
        if row is None:
            raise KeyError(path)
        return row[0]

    def __iter__(self):
        return (row[0] for row in self.connection.execute("SELECT path FROM sources ORDER BY path"))

    def __len__(self):
        return self.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    def agent_config(self, purpose="harness"):
        from .agent_config import load_agent_config
        current = load_agent_config()
        frozen = self.frozen_config if purpose == "harness" else self.frozen_hierarchy_config
        if current["base_url"] != frozen["base_url"]:
            raise ModelConfigurationChanged("Restore the checkpoint's model endpoint before resuming, or start a new analysis")
        return {**current, **frozen}

    def load_conversation(self, file):
        from .checkpoints import load_conversation
        return load_conversation(self.job_id, file)

    def save_conversation(self, file, state):
        from .checkpoints import save_conversation
        save_conversation(self.job_id, file, state)

    def find_entities(self, query):
        query = query.lower()[:200]
        entities = [entity for entity in getattr(self, "entities", []) if query in entity.get("name", "").lower()][:50]
        ids = {entity["id"] for entity in entities}
        relationships = [rel for rel in getattr(self, "relationships", []) if rel.get("source") in ids or rel.get("target") in ids][:100]
        return {"entities": entities, "relationships": relationships}

    def find_schema(self, query, offset=0):
        if not hasattr(self, "schema_records"):
            self.schema_records = []
            for file, content, _ in self.rows():
                if self.cancelled():
                    from .agent import AnalysisCancelled
                    raise AnalysisCancelled("Analysis cancelled")
                parsed = _cached_extract(self.root / file, content)
                entities = {item["id"]: item for item in parsed.get("entities", [])}
                for column in entities.values():
                    attrs = column.get("attributes", {})
                    if column["kind"] != "column" or not attrs.get("declared"):
                        continue
                    owner = entities.get(attrs.get("parent_dataset_id"))
                    if owner:
                        evidence = {**column.get("evidence", {}), "file": file}
                        self.schema_records.append({"table": owner["name"], "column": column["name"], "evidence": evidence})
        matches = [item for item in self.schema_records if query.lower() in (item["table"] + " " + item["column"]).lower()]
        page_size = max(1, min(200, int(os.environ.get("GRAPHIFIER_SCHEMA_PAGE_SIZE", "50"))))
        return {"matches": matches[offset:offset + page_size], "total": len(matches), "next_offset": offset + page_size if offset + page_size < len(matches) else None}

    def rows(self):
        return self.connection.execute("SELECT path,content,sha256 FROM sources ORDER BY path")


def extraction_fingerprint():
    names = ("extraction.py", "code_symbols.py", "code_links.py", "languages.py", "agent.py", "consolidation.py", "worker.py", "discovery.py", "checkpoints.py", "hierarchy.py", "ai_hierarchy.py")
    return hashlib.sha256(b"".join((Path(__file__).parent / name).read_bytes() for name in names)).hexdigest()


def _cached_extract(path, content):
    # Adapter source hashes invalidate cached evidence when parser behavior changes.
    adapters = ("extraction.py", "code_symbols.py", "languages.py")
    version = hashlib.sha256(b"".join((Path(__file__).parent / name).read_bytes() for name in adapters)).hexdigest()
    key = hashlib.sha256((version + "\0" + str(path) + "\0" + content).encode()).hexdigest()
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS extraction_cache (cache_key TEXT PRIMARY KEY, data TEXT NOT NULL)")
        row = c.execute("SELECT data FROM extraction_cache WHERE cache_key=?", (key,)).fetchone()
    if row:
        return json.loads(row[0])
    parsed = _extract(path, content)
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO extraction_cache VALUES(?,?)", (key, json_data(parsed)))
    return parsed


def run_job(job):
    jid, repo_id = job["id"], job["repo_id"]
    staging = tempfile.TemporaryDirectory(prefix="graphifier-scan-")
    agent_sources = None
    try:
        with connect() as c:
            repo = c.execute("SELECT path FROM repositories WHERE id=?", (repo_id,)).fetchone()
        if not repo: raise ValueError("Repository no longer exists")
        from . import checkpoints
        from .agent_config import load_agent_config, profile_config
        checkpoint = checkpoints.load(jid)
        agent_sources = SnapshotSources(staging.name, lambda: is_cancelled(jid))
        agent_sources.job_id = jid
        if checkpoint is None:
            root = checked_path(repo["path"])
            from .discovery import discover_repository, repository_structure
            discovery = discover_repository(root)
            files = discovery["files"]
            for path in files:
                if is_cancelled(jid):
                    update_job(jid, status="cancelled")
                    return
                agent_sources.add(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8", errors="replace"))
            agent_sources.connection.commit()
            structure = repository_structure(root, discovery)
            if job.get("use_agent"):
                def priority(path):
                    relative = path.relative_to(root).as_posix()
                    sample = agent_sources[relative][:20000].lower()
                    static = _cached_extract(path, agent_sources[relative])
                    gap_score = len(static.get("gaps", [])) * 100
                    score = gap_score + sum(token in sample for token in ("__main__", "%include", "%macro", "getenv", "import ", "main(", "app.listen", "create table"))
                    return (-score, relative)
                files.sort(key=priority)
            config = load_agent_config()
            hierarchy_model_config = profile_config(config, "hierarchy")
            from .embeddings import configuration
            embedding_model, embedding_base, _ = configuration()
            checkpoint = {
                "root": str(root), "files": [path.relative_to(root).as_posix() for path in files],
                "modules": discovery["modules"], "warnings": discovery.get("warnings", []), "structure": structure,
                "agent_config": {key: config.get(key) for key in ("base_url", "model", "api_mode", "reasoning_effort")},
                "hierarchy_agent_config": {key: hierarchy_model_config.get(key) for key in ("base_url", "model", "api_mode", "reasoning_effort")},
                "embedding_config": {"model": embedding_model, "provider": hashlib.sha256(embedding_base.encode()).hexdigest()},
                "max_agent_files": int(os.environ.get("GRAPHIFIER_AGENT_MAX_FILES", "0")),
                "max_agent_steps": int(os.environ.get("GRAPHIFIER_AGENT_MAX_STEPS", "0")),
                "hierarchy_max_batches": int(os.environ.get("GRAPHIFIER_AI_HIERARCHY_MAX_BATCHES", "0")),
                "commit": git_commit(root), "snapshot_id": str(uuid.uuid4()), "fingerprint": extraction_fingerprint(),
            }
            if checkpoint["max_agent_files"] < 0 or checkpoint["max_agent_steps"] < 0 or checkpoint["hierarchy_max_batches"] < 0:
                raise ValueError("Agent budgets must be nonnegative")
            checkpoints.prepare(jid, checkpoint, agent_sources.rows())
        else:
            if checkpoint["fingerprint"] != extraction_fingerprint():
                raise RuntimeError("Analysis implementation changed since checkpoint. Start a new analysis to use the updated extractors.")
            root = Path(checkpoint["root"])
            with connect() as c:
                for row in c.execute("SELECT file,content FROM analysis_sources WHERE job_id=? ORDER BY file", (jid,)):
                    agent_sources.add(row["file"], row["content"])
            agent_sources.connection.commit()
        if job.get("use_embeddings"):
            from .embeddings import configuration
            embedding_model, embedding_base, _ = configuration()
            if checkpoint["embedding_config"] != {"model": embedding_model, "provider": hashlib.sha256(embedding_base.encode()).hexdigest()}:
                raise ModelConfigurationChanged("Restore the checkpoint's embedding model and endpoint before resuming, or start a new analysis")
        files = [root / relative for relative in checkpoint["files"]]
        discovery = {"modules": checkpoint["modules"]}
        agent_sources.root = root
        agent_sources.frozen_config = checkpoint["agent_config"]
        agent_sources.frozen_hierarchy_config = checkpoint.get("hierarchy_agent_config", checkpoint["agent_config"])
        agent_sources.max_steps = checkpoint["max_agent_steps"]
        max_agent_files = checkpoint["max_agent_files"]
        update_job(jid, total_files=len(files))
        entities, relationships, symbols = [], [], []
        warnings = list(checkpoint["warnings"])
        structure = checkpoint["structure"]
        for entity in structure["entities"]:
            entity["id"] = scoped_id(repo_id, entity["id"])
            entities.append(entity)
        for relation in structure["relationships"]:
            relation["source"] = scoped_id(repo_id, relation["source"])
            relation["target"] = scoped_id(repo_id, relation["target"])
            relationships.append(relation)
        agent_sources.entities = entities
        agent_sources.relationships = relationships
        agent_files_used = 0
        digest = hashlib.sha256()
        for relative, content, _ in agent_sources.rows():
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(content.encode())
            digest.update(b"\0")
        for i, path in enumerate(files):
            if is_cancelled(jid):
                update_job(jid,status="cancelled")
                return
            relative = path.relative_to(root).as_posix()
            saved_unit = checkpoints.load_unit(jid, relative)
            if saved_unit is not None:
                entities.extend(saved_unit["entities"])
                relationships.extend(saved_unit["relationships"])
                symbols.extend(saved_unit["symbols"])
                warnings.extend(saved_unit["warnings"])
                agent_files_used += int(saved_unit["used_agent"])
                continue
            starts = (len(entities), len(relationships), len(symbols), len(warnings))
            used_agent = False
            content = agent_sources[relative]
            parsed = _cached_extract(path, content)
            for category in ("entities", "relationships", "symbols", "gaps"):
                for finding in parsed.get(category, []):
                    finding.setdefault("evidence", {})["file"] = relative
                    if "path" in finding.get("attributes", {}):
                        finding["attributes"]["path"] = relative
                    attrs = finding.get("attributes", {})
                    if attrs.get("context_basis") in {"source-path", "test-path-convention"}:
                        from .hierarchy import classify_context
                        context, basis = classify_context({"evidence": [{"file": relative}]})
                        attrs.update(context=context, context_basis=basis)
            from .discovery import module_for
            module = module_for(relative, discovery["modules"])
            if module:
                for entity in parsed.get("entities", []):
                    entity.setdefault("attributes", {})["module"] = module["path"]
            if job.get("use_agent") and (max_agent_files == 0 or agent_files_used < max_agent_files):
                from .agent import analyze_file, AnalysisCancelled, ModelTransportError
                used_agent = True
                try:
                    agent_sources.current_analysis = parsed
                    agent_result = analyze_file(relative, content, agent_sources)
                except (AnalysisCancelled, ModelTransportError):
                    raise
                except (RuntimeError, ValueError, TypeError, KeyError) as exc:
                    agent_result = {"entities": [], "relationships": [], "symbols": [], "warnings": [f"AI analysis incomplete ({type(exc).__name__}): {exc}; static findings retained"]}
                agent_files_used+=1
                base_lookup={(e.get("kind"),e.get("name"),e.get("expression"),e.get("evidence", {}).get("file")):e.get("id") for e in parsed.get("entities",[])}
                remap={}
                for entity in agent_result.get("entities",[]):
                    key=(entity.get("kind"),entity.get("name"),entity.get("expression"),entity.get("evidence", {}).get("file"))
                    agent_key=json_data(key)
                    known_ids = {e["id"] for e in entities}
                    known_id = str(entity.get("id"))
                    reused_id = known_id[len(repo_id) + 1:] if known_id in known_ids and known_id.startswith(repo_id + ":") else None
                    aid=reused_id or base_lookup.get(key) or f"agent:{hashlib.sha256(agent_key.encode()).hexdigest()[:20]}"
                    remap[str(entity.get("id"))]=aid
                    if key not in base_lookup:
                        entity["id"]=aid
                        entity.setdefault("attributes",{})["method"]="model-inferred"
                        parsed.setdefault("entities",[]).append(entity)
                    else:
                        for static_entity in parsed.get("entities",[]):
                            if (static_entity.get("kind"),static_entity.get("name"),static_entity.get("expression"),static_entity.get("evidence", {}).get("file"))==key:
                                static_entity.setdefault("attributes",{})["method"]="model-inferred"
                                static_entity["attributes"]["also_static"] = True
                                break
                for entity in agent_result.get("entities", []):
                    for reference in ("parent_dataset_id", "output_column_id", "input_column_id", "owner_id"):
                        attrs = entity.setdefault("attributes", {})
                        if attrs.get(reference) in remap:
                            attrs[reference] = remap[attrs[reference]]
                for relation in agent_result.get("relationships",[]):
                    relation["source"]=remap[str(relation["source"])]
                    relation["target"]=remap[str(relation["target"])]
                    relation.setdefault("attributes",{})["method"]="model-inferred"
                    parsed.setdefault("relationships",[]).append(relation)
                existing_symbols={(s.get("name"),s.get("expression")) for s in parsed.get("symbols",[])}
                agent_symbols=[s for s in agent_result.get("symbols",[]) if (s.get("name"),s.get("expression")) not in existing_symbols]
                for symbol in agent_symbols: symbol["method"]="model-inferred"
                parsed.setdefault("symbols",[]).extend(agent_symbols)
                parsed.setdefault("warnings",[]).extend(agent_result.get("warnings",[]))
            elif job.get("use_agent"):
                reason="agent file limit reached"
                parsed.setdefault("warnings",[]).append(f"{reason}; static extraction used")
            file_warnings = parsed.get("warnings", [])
            warnings.extend(f"{relative}: {str(w)[:600]}" for w in file_warnings)
            for entity in parsed.get("entities",[]):
                entity.setdefault("attributes",{}).setdefault("method","static")
                e = dict(entity); e["id"] = scoped_id(repo_id,str(e.get("id",e.get("name","unknown"))))
                for reference in ("parent_dataset_id", "output_column_id", "input_column_id", "owner_id"):
                    value = e["attributes"].get(reference)
                    if isinstance(value, str) and not value.startswith(repo_id + ":"):
                        e["attributes"][reference] = scoped_id(repo_id, value)
                ev = dict(e.get("evidence") or {})
                if e["attributes"].get("method") != "model-inferred": ev["file"] = relative
                e["evidence"] = ev
                entities.append(e)
            for rel in parsed.get("relationships",[]):
                r = dict(rel)
                r.setdefault("attributes",{}).setdefault("method","static")
                for field in ("source","target"):
                    if field in r: r[field] = scoped_id(repo_id,str(r[field]))
                ev = dict(r.get("evidence") or {})
                if r["attributes"].get("method") != "model-inferred": ev["file"] = relative
                r["evidence"] = ev
                relationships.append(r)
            for sym in parsed.get("symbols",[]):
                s = dict(sym); s.setdefault("method", "static")
                ev = dict(s.get("evidence") or {})
                if s["method"] != "model-inferred": ev["file"] = relative
                s["evidence"] = ev
                symbols.append(s)
            unit = {"entities": entities[starts[0]:], "relationships": relationships[starts[1]:],
                    "symbols": symbols[starts[2]:], "warnings": warnings[starts[3]:], "used_agent": used_agent}
            checkpoints.save_unit(jid, relative, unit, i + 1, 0.9 * (i + 1) / max(1, len(files)))
        if is_cancelled(jid):
            update_job(jid,status="cancelled"); return
        consolidated = checkpoints.load_consolidated(jid)
        if consolidated is None:
            checkpoints.phase(jid, "consolidating")
            from .code_links import link_code_findings
            linked = link_code_findings(entities, relationships, agent_sources)
            relationships.extend(linked["relationships"])
            from .consolidation import consolidate_findings
            consolidated = consolidate_findings(entities, relationships)
            consolidated["warnings"].extend(linked["warnings"])
            checkpoints.save_consolidated(jid, consolidated)
        entities, relationships = consolidated["entities"], consolidated["relationships"]
        warnings.extend(consolidated["warnings"])
        commit, snap_hash, sid, created = checkpoint["commit"], digest.hexdigest(), checkpoint["snapshot_id"], stamp()
        pending_enrichment = bool(job.get("use_embeddings") or job.get("use_ai_hierarchy"))
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (jid,)).fetchone()[0]:
                c.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (jid,))
                return
            if not c.execute("SELECT 1 FROM snapshots WHERE id=?", (sid,)).fetchone():
                c.execute("INSERT INTO snapshots(id,repo_id,job_id,commit_hash,content_hash,created_at) VALUES(?,?,?,?,?,?)", (sid,repo_id,jid,commit,snap_hash,created))
                c.executemany("INSERT INTO source_files(repo_id,snapshot_id,file,content,sha256) VALUES(?,?,?,?,?)", ((repo_id,sid,file,content,filehash) for file,content,filehash in agent_sources.rows()))
                for category, items in (("entity",entities),("relationship",relationships),("warning",warnings)):
                    for index,item in enumerate(items):
                        key = str(item.get("id",f"{category}:{index}")) if isinstance(item,dict) else f"{category}:{index}"
                        c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES(?,?,?,?,?)", (repo_id,sid,category,key,json_data(item)))
                for sym in symbols:
                    c.execute("INSERT OR IGNORE INTO symbols(repo_id,snapshot_id,name,expression,default_value,evidence,method) VALUES(?,?,?,?,?,?,?)", (repo_id,sid,str(sym.get("name","")),str(sym.get("expression","")),sym.get("default_value"),json_data(sym.get("evidence",{})),str(sym.get("method","static"))))
                c.execute("UPDATE jobs SET status=?,progress=?,commit_hash=?,snapshot_hash=?,updated_at=? WHERE id=?", ("running" if pending_enrichment else "completed",0.95 if pending_enrichment else 1,commit,snap_hash,created,jid))
                c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,"snapshot.staged" if pending_enrichment else "job.completed",json_data({"snapshot_id":sid,"file_count":len(files),"warning_count":len(warnings)}),created))
            if not pending_enrichment:
                c.execute("UPDATE jobs SET status='completed',progress=1,error=NULL WHERE id=?", (jid,))
            c.execute("UPDATE analysis_checkpoints SET phase=? WHERE job_id=?", ("ai_hierarchy" if job.get("use_ai_hierarchy") else "embeddings" if job.get("use_embeddings") else "completed",jid))
        if job.get("use_ai_hierarchy"):
            from .ai_hierarchy import run_ai_hierarchy
            from .graph import _build
            with connect() as c:
                staged_graph = _build(c, repo_id, job.get("environment", "default"), snapshot_id=sid)
            hierarchy_config = {**agent_sources.agent_config("hierarchy"), "hierarchy_max_batches": checkpoint.get("hierarchy_max_batches", 0)}
            run_ai_hierarchy(jid, staged_graph, hierarchy_config, cancelled=lambda: is_cancelled(jid), sources=agent_sources)
        if job.get("use_embeddings"):
            checkpoints.phase(jid, "embeddings")
            from .embeddings import index_snapshot
            try:
                with connect() as c:
                    indexed = c.execute("SELECT 1 FROM embedding_indexes WHERE snapshot_id=? AND status='completed'", (sid,)).fetchone()
                stats = {"reused": True} if indexed else index_snapshot(repo_id, sid, cancelled=lambda: is_cancelled(jid))
                with connect() as c:
                    c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,"embeddings.completed",json_data(stats),stamp()))
            except Exception as exc:
                with connect() as c:
                    warning = f"Optional embeddings failed: {type(exc).__name__}"
                    c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES(?,?,'warning','embeddings',?)", (repo_id,sid,json_data(warning)))
                    c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,"embeddings.failed",json_data({"error":type(exc).__name__}),stamp()))
                raise
        if pending_enrichment:
            with connect() as c:
                c.execute("BEGIN IMMEDIATE")
                cancelled = bool(c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (jid,)).fetchone()[0])
                status = "cancelled" if cancelled else "completed"
                c.execute("UPDATE jobs SET status=?,progress=1,error=NULL,updated_at=? WHERE id=?", (status,stamp(),jid))
                if not cancelled:
                    c.execute("UPDATE analysis_checkpoints SET phase='completed' WHERE job_id=?", (jid,))
                c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,f"job.{status}",json_data({"snapshot_id":sid}),stamp()))
        # Read-model construction is recoverable independently of source analysis.
        # A projection failure must not turn a completed evidence snapshot into a
        # failed analysis; the next graph request resumes its durable build stages.
        with connect() as c:
            published = c.execute("SELECT status,environment FROM jobs WHERE id=?", (jid,)).fetchone()
        if published and published["status"] == "completed":
            try:
                from .graph_store import ensure_generation
                generation = ensure_generation(repo_id=repo_id, environment=published["environment"])
                with connect() as c:
                    c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)",
                              (repo_id,jid,"graph.prepared",json_data({"generation":generation}),stamp()))
            except Exception as exc:
                with connect() as c:
                    c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)",
                              (repo_id,jid,"graph.prepare_failed",json_data({"error":type(exc).__name__}),stamp()))
    except Exception as exc:
        if is_cancelled(jid):
            update_job(jid, status="cancelled")
            return
        update_job(jid,status="failed",error=f"{type(exc).__name__}: {str(exc)[:1000]}")
        with connect() as c:
            c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,"job.failed",json_data({"error":type(exc).__name__}),stamp()))

    finally:
        if agent_sources is not None:
            agent_sources.connection.close()
        staging.cleanup()

def work_once() -> bool:
    from .git_import import claim_import, run_import
    imported = claim_import()
    if imported:
        run_import(imported)
        return True
    job = claim_job()
    if not job: return False
    run_job(job)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    args = parser.parse_args()
    init_db()
    from .db import db_path
    lock_path=db_path().with_suffix(".worker.lock")
    with lock_path.open("a") as lock:
        try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit("Another Graphifier worker already holds the worker lock")
        # Only the lock owner may recover jobs abandoned by the prior worker.
        with connect() as c:
            c.execute("UPDATE jobs SET status='failed',error='Worker restarted while job was running',updated_at=? WHERE status='running'",(stamp(),))
        from .git_import import recover_imports
        recover_imports()
        if args.once:
            work_once(); return
        while True:
            if not work_once(): time.sleep(0.6)


if __name__ == "__main__": main()
