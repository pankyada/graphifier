"""Durable source, extraction and model-conversation checkpoints."""
from __future__ import annotations

import json
from .db import connect, json_data


def checkpoint_info(c, job_id):
    row = c.execute("SELECT phase,state FROM analysis_checkpoints WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None
    state = json.loads(row["state"])
    done = {r[0] for r in c.execute("SELECT file FROM analysis_units WHERE job_id=?", (job_id,))}
    files = state["files"]
    return {"phase": row["phase"], "completed_files": len(done), "total_files": len(files),
            "current_file": next((path for path in files if path not in done), None)}


def load(job_id):
    with connect() as c:
        row = c.execute("SELECT phase,state FROM analysis_checkpoints WHERE job_id=?", (job_id,)).fetchone()
    return {"phase": row["phase"], **json.loads(row["state"])} if row else None


def prepare(job_id, state, rows):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO analysis_checkpoints(job_id,phase,state) VALUES(?,'extracting',?)", (job_id,json_data(state)))
        c.executemany("INSERT INTO analysis_sources(job_id,file,content,sha256) VALUES(?,?,?,?)", ((job_id,*row) for row in rows))


def phase(job_id, phase_name):
    with connect() as c:
        c.execute("UPDATE analysis_checkpoints SET phase=? WHERE job_id=?", (phase_name,job_id))


def load_unit(job_id, file):
    with connect() as c:
        row = c.execute("SELECT data FROM analysis_units WHERE job_id=? AND file=?", (job_id,file)).fetchone()
    return json.loads(row[0]) if row else None


def save_unit(job_id, file, data, processed, progress):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO analysis_units(job_id,file,data) VALUES(?,?,?) ON CONFLICT(job_id,file) DO UPDATE SET data=excluded.data", (job_id,file,json_data(data)))
        c.execute("DELETE FROM analysis_conversations WHERE job_id=? AND file=?", (job_id,file))
        c.execute("UPDATE jobs SET processed_files=?,progress=? WHERE id=?", (processed,progress,job_id))


def load_conversation(job_id, file):
    with connect() as c:
        row = c.execute("SELECT data FROM analysis_conversations WHERE job_id=? AND file=?", (job_id,file)).fetchone()
    return json.loads(row[0]) if row else None


def save_conversation(job_id, file, data):
    with connect() as c:
        c.execute("INSERT INTO analysis_conversations(job_id,file,data) VALUES(?,?,?) ON CONFLICT(job_id,file) DO UPDATE SET data=excluded.data", (job_id,file,json_data(data)))


def save_consolidated(job_id, data):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO analysis_consolidated(job_id,data) VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET data=excluded.data", (job_id,json_data(data)))
        c.execute("UPDATE analysis_checkpoints SET phase='publishing' WHERE job_id=?", (job_id,))


def load_consolidated(job_id):
    with connect() as c:
        row = c.execute("SELECT data FROM analysis_consolidated WHERE job_id=?", (job_id,)).fetchone()
    return json.loads(row[0]) if row else None
