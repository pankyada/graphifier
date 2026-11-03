from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .db import connect, json_data


def now() -> str: return datetime.now(timezone.utc).isoformat()


def propose(repo_id: str, environment: str, symbol: str, expression: str, default_value=None, actor=None):
    if not environment.strip() or not symbol.strip() or not expression.strip(): raise ValueError("environment, symbol, and expression are required")
    with connect() as c:
        live = c.execute("SELECT * FROM resolutions WHERE repo_id=? AND environment=? AND symbol=? AND status='applied'", (repo_id, environment, symbol)).fetchone()
        conflict = dict(live) if live else None
        rid, stamp = str(uuid.uuid4()), now()
        c.execute("INSERT INTO resolutions(id,repo_id,environment,symbol,expression,default_value,status,version,actor,created_at,updated_at) VALUES(?,?,?,?,?,?,'proposed',1,?,?,?)", (rid,repo_id,environment,symbol,expression,default_value,actor,stamp,stamp))
        c.execute("INSERT INTO events(repo_id,resolution_id,actor,action,data,created_at) VALUES(?,?,?,?,?,?)", (repo_id,rid,actor,"proposed",json_data({"symbol":symbol,"environment":environment,"conflict_id":conflict["id"] if conflict else None}),stamp))
        row = dict(c.execute("SELECT * FROM resolutions WHERE id=?", (rid,)).fetchone())
    row["conflict"] = conflict
    row["preview"] = {"repo_id":repo_id,"environment":environment,"symbol":symbol,"expression":expression,"default_value":default_value,"expected_version":1,"conflict":conflict}
    return row


def transition(rid: str, expected_version: int, action: str, actor=None):
    with connect() as c:
        # Lock before reading so concurrent transitions cannot both pass the
        # same optimistic version or scope-conflict check.
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM resolutions WHERE id=?", (rid,)).fetchone()
        if not row: raise LookupError("Resolution not found")
        r = dict(row)
        if r["version"] != expected_version: raise RuntimeError(f"Version conflict: current version is {r['version']}")
        if action == "apply":
            if r["status"] != "proposed": raise RuntimeError("Only proposed resolutions can be applied")
            conflict = c.execute("SELECT id FROM resolutions WHERE repo_id=? AND environment=? AND symbol=? AND status='applied'", (r["repo_id"],r["environment"],r["symbol"])).fetchone()
            if conflict: raise RuntimeError("A binding already exists for this repository, environment, and symbol")
            status = "applied"
        else:
            if r["status"] != "applied": raise RuntimeError("Only applied resolutions can be retracted")
            status = "retracted"
        stamp = now()
        c.execute("UPDATE resolutions SET status=?,version=version+1,actor=?,updated_at=? WHERE id=? AND version=?", (status,actor,stamp,rid,expected_version))
        c.execute("INSERT INTO events(repo_id,resolution_id,actor,action,data,created_at) VALUES(?,?,?,?,?,?)", (r["repo_id"],rid,actor,action,json_data({"from":r["status"],"to":status,"version":expected_version+1}),stamp))
        return dict(c.execute("SELECT * FROM resolutions WHERE id=?", (rid,)).fetchone())
