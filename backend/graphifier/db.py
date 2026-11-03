from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


class ClosingConnection(sqlite3.Connection):
    """Keep sqlite's transaction context behavior and release it on exit."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def db_path() -> Path:
    path = Path(os.environ.get("GRAPHIFIER_DB", Path(__file__).resolve().parents[1] / "data" / "graphifier.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=15, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS repositories (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, repo_id TEXT NOT NULL REFERENCES repositories(id),
          environment TEXT NOT NULL DEFAULT 'default', use_agent INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
          total_files INTEGER NOT NULL DEFAULT 0, processed_files INTEGER NOT NULL DEFAULT 0,
          error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
          commit_hash TEXT, snapshot_hash TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS snapshots (
          id TEXT PRIMARY KEY, repo_id TEXT NOT NULL REFERENCES repositories(id),
          job_id TEXT NOT NULL REFERENCES jobs(id), commit_hash TEXT, content_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS findings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, repo_id TEXT NOT NULL REFERENCES repositories(id),
          snapshot_id TEXT NOT NULL REFERENCES snapshots(id), category TEXT NOT NULL,
          item_key TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS findings_repo_idx ON findings(repo_id, snapshot_id);
        CREATE TABLE IF NOT EXISTS symbols (
          repo_id TEXT NOT NULL REFERENCES repositories(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
          name TEXT NOT NULL, expression TEXT NOT NULL, default_value TEXT, evidence TEXT NOT NULL,
          method TEXT NOT NULL DEFAULT 'static',
          PRIMARY KEY(repo_id,snapshot_id,name,expression)
        );
        CREATE TABLE IF NOT EXISTS source_files (
          repo_id TEXT NOT NULL REFERENCES repositories(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
          file TEXT NOT NULL, content TEXT NOT NULL, sha256 TEXT NOT NULL,
          PRIMARY KEY(repo_id,snapshot_id,file)
        );
        CREATE TABLE IF NOT EXISTS resolutions (
          id TEXT PRIMARY KEY, repo_id TEXT NOT NULL REFERENCES repositories(id), environment TEXT NOT NULL,
          symbol TEXT NOT NULL, expression TEXT NOT NULL, default_value TEXT, status TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, actor TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS resolution_scope_idx ON resolutions(repo_id,environment,symbol,status);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, repo_id TEXT, job_id TEXT, resolution_id TEXT,
          actor TEXT, action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        symbol_columns={row["name"] for row in c.execute("PRAGMA table_info(symbols)")}
        if "method" not in symbol_columns:
            c.execute("ALTER TABLE symbols ADD COLUMN method TEXT NOT NULL DEFAULT 'static'")
        duplicate_scope=c.execute("SELECT 1 FROM resolutions WHERE status='applied' GROUP BY repo_id,environment,symbol HAVING COUNT(*)>1 LIMIT 1").fetchone()
        # Keep legacy conflicts readable and actionable. Once those are
        # resolved, the next startup installs the database-level invariant.
        if not duplicate_scope:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS resolutions_live_scope_idx ON resolutions(repo_id,environment,symbol) WHERE status='applied'")


def json_data(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
