from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, init_db, json_data
from .paths import checked_path, safe_files


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


def run_job(job):
    jid, repo_id = job["id"], job["repo_id"]
    try:
        with connect() as c:
            repo = c.execute("SELECT path FROM repositories WHERE id=?", (repo_id,)).fetchone()
        if not repo: raise ValueError("Repository no longer exists")
        root = checked_path(repo["path"])
        files = safe_files(root)
        update_job(jid,total_files=len(files),processed_files=0,progress=0)
        entities, relationships, symbols, warnings = [], [], [], []
        agent_sources = {p.relative_to(root).as_posix():p.read_text(encoding="utf-8",errors="replace") for p in files} if job.get("use_agent") else {}
        indexed_sources=[]
        agent_files_used=0
        digest = hashlib.sha256()
        for i, path in enumerate(files):
            if is_cancelled(jid):
                update_job(jid,status="cancelled")
                return
            relative = path.relative_to(root).as_posix()
            content = path.read_text(encoding="utf-8",errors="replace")
            indexed_sources.append((relative,content,hashlib.sha256(content.encode()).hexdigest()))
            digest.update(relative.encode()); digest.update(b"\0"); digest.update(content.encode(errors="replace")); digest.update(b"\0")
            parsed = _extract(path, content)
            if job.get("use_agent") and agent_files_used < 20 and len(content) <= 80_000:
                from .agent import analyze_file
                agent_result=analyze_file(relative,content,agent_sources)
                agent_files_used+=1
                base_lookup={(e.get("kind"),e.get("name"),e.get("expression")):e.get("id") for e in parsed.get("entities",[])}
                remap={}
                for entity in agent_result.get("entities",[]):
                    key=(entity.get("kind"),entity.get("name"),entity.get("expression"))
                    agent_key=relative+chr(0)+str(entity.get("id"))
                    aid=base_lookup.get(key) or f"agent:{hashlib.sha256(agent_key.encode()).hexdigest()[:20]}"
                    remap[str(entity.get("id"))]=aid
                    if key not in base_lookup:
                        entity["id"]=aid
                        entity.setdefault("attributes",{})["method"]="model-inferred"
                        parsed.setdefault("entities",[]).append(entity)
                    else:
                        for static_entity in parsed.get("entities",[]):
                            if (static_entity.get("kind"),static_entity.get("name"),static_entity.get("expression"))==key:
                                static_entity.setdefault("attributes",{})["method"]="model-inferred"
                                static_entity["attributes"]["also_static"] = True
                                break
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
                reason="agent file limit reached" if agent_files_used>=20 else "agent source character limit reached"
                parsed.setdefault("warnings",[]).append(f"{reason}; static extraction used")
            file_warnings = parsed.get("warnings", [])
            warnings.extend(f"{relative}: {str(w)[:600]}" for w in file_warnings)
            for entity in parsed.get("entities",[]):
                entity.setdefault("attributes",{}).setdefault("method","static")
                e = dict(entity); e["id"] = scoped_id(repo_id,str(e.get("id",e.get("name","unknown"))))
                ev = e.get("evidence") or {}; ev["file"] = relative; e["evidence"] = ev
                entities.append(e)
            for rel in parsed.get("relationships",[]):
                r = dict(rel)
                r.setdefault("attributes",{}).setdefault("method","static")
                for field in ("source","target"):
                    if field in r: r[field] = scoped_id(repo_id,str(r[field]))
                ev = r.get("evidence") or {}; ev["file"] = relative; r["evidence"] = ev
                relationships.append(r)
            for sym in parsed.get("symbols",[]):
                s = dict(sym); s.setdefault("method","static"); ev = s.get("evidence") or {}; ev["file"] = relative; s["evidence"] = ev
                symbols.append(s)
            update_job(jid,processed_files=i+1,progress=(i+1)/max(1,len(files)))
        if is_cancelled(jid):
            update_job(jid,status="cancelled"); return
        commit, snap_hash, sid, created = git_commit(root), digest.hexdigest(), str(uuid.uuid4()), stamp()
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT INTO snapshots(id,repo_id,job_id,commit_hash,content_hash,created_at) VALUES(?,?,?,?,?,?)", (sid,repo_id,jid,commit,snap_hash,created))
            c.executemany("INSERT INTO source_files(repo_id,snapshot_id,file,content,sha256) VALUES(?,?,?,?,?)", ((repo_id,sid,file,content,filehash) for file,content,filehash in indexed_sources))
            for category, items in (("entity",entities),("relationship",relationships),("warning",warnings)):
                for index,item in enumerate(items):
                    key = str(item.get("id",f"{category}:{index}")) if isinstance(item,dict) else f"{category}:{index}"
                    c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES(?,?,?,?,?)", (repo_id,sid,category,key,json_data(item)))
            for sym in symbols:
                c.execute("INSERT OR IGNORE INTO symbols(repo_id,snapshot_id,name,expression,default_value,evidence,method) VALUES(?,?,?,?,?,?,?)", (repo_id,sid,str(sym.get("name","")),str(sym.get("expression","")),sym.get("default_value"),json_data(sym.get("evidence",{})),str(sym.get("method","static"))))
            c.execute("UPDATE jobs SET status='completed',progress=1,commit_hash=?,snapshot_hash=?,updated_at=? WHERE id=?", (commit,snap_hash,created,jid))
            c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,"job.completed",json_data({"snapshot_id":sid,"file_count":len(files),"warning_count":len(warnings)}),created))
    except Exception as exc:
        update_job(jid,status="failed",error=f"{type(exc).__name__}: {str(exc)[:1000]}")
        with connect() as c:
            c.execute("INSERT INTO events(repo_id,job_id,action,data,created_at) VALUES(?,?,?,?,?)", (repo_id,jid,"job.failed",json_data({"error":type(exc).__name__}),stamp()))


def work_once() -> bool:
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
        if args.once:
            work_once(); return
        while True:
            if not work_once(): time.sleep(0.6)


if __name__ == "__main__": main()
