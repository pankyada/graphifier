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
        CREATE TABLE IF NOT EXISTS agent_configuration (
          id INTEGER PRIMARY KEY CHECK(id=1), base_url TEXT NOT NULL,
          model TEXT NOT NULL, api_mode TEXT NOT NULL, api_key TEXT
        );
        CREATE TABLE IF NOT EXISTS repositories (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS repository_imports (
          id TEXT PRIMARY KEY, url TEXT NOT NULL, branch TEXT, name TEXT NOT NULL,
          destination TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
          progress REAL NOT NULL DEFAULT 0, error TEXT, repo_id TEXT REFERENCES repositories(id),
          commit_hash TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS imports_status_idx ON repository_imports(status,created_at);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, repo_id TEXT NOT NULL REFERENCES repositories(id),
          environment TEXT NOT NULL DEFAULT 'default', use_agent INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
          total_files INTEGER NOT NULL DEFAULT 0, processed_files INTEGER NOT NULL DEFAULT 0,
          error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
          commit_hash TEXT, snapshot_hash TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS analysis_checkpoints (
          job_id TEXT PRIMARY KEY REFERENCES jobs(id), phase TEXT NOT NULL, state TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_sources (
          job_id TEXT NOT NULL REFERENCES jobs(id), file TEXT NOT NULL, content TEXT NOT NULL,
          sha256 TEXT NOT NULL, PRIMARY KEY(job_id,file)
        );
        CREATE TABLE IF NOT EXISTS analysis_units (
          job_id TEXT NOT NULL REFERENCES jobs(id), file TEXT NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY(job_id,file)
        );
        CREATE TABLE IF NOT EXISTS analysis_conversations (
          job_id TEXT NOT NULL REFERENCES jobs(id), file TEXT NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY(job_id,file)
        );
        CREATE TABLE IF NOT EXISTS analysis_ai_hierarchy (
          job_id TEXT PRIMARY KEY REFERENCES jobs(id), data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_ai_hierarchy_units (
          job_id TEXT NOT NULL REFERENCES jobs(id), unit_hash TEXT NOT NULL,
          phase TEXT NOT NULL, response_text TEXT NOT NULL,
          PRIMARY KEY(job_id,unit_hash)
        );
        CREATE TABLE IF NOT EXISTS analysis_consolidated (
          job_id TEXT PRIMARY KEY REFERENCES jobs(id), data TEXT NOT NULL
        );
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
        c.executescript("""
        CREATE TABLE IF NOT EXISTS embedding_indexes (
          snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id),
          repo_id TEXT NOT NULL REFERENCES repositories(id), model TEXT NOT NULL,
          provider TEXT NOT NULL, status TEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0,
          dimensions INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS code_chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          snapshot_id TEXT NOT NULL REFERENCES snapshots(id), repo_id TEXT NOT NULL REFERENCES repositories(id),
          file TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
          content TEXT NOT NULL, source_sha256 TEXT NOT NULL, vector TEXT NOT NULL, norm REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chunks_snapshot_idx ON code_chunks(snapshot_id);
        """)
        from .graph_store import init_store
        init_store(c)
        config_columns = {row["name"] for row in c.execute("PRAGMA table_info(agent_configuration)")}
        if "reasoning_effort" not in config_columns:
            c.execute("ALTER TABLE agent_configuration ADD COLUMN reasoning_effort TEXT")
        for column in ("hierarchy_model", "hierarchy_reasoning_effort"):
            if column not in config_columns:
                c.execute(f"ALTER TABLE agent_configuration ADD COLUMN {column} TEXT")
        if "hierarchy_effort_set" not in config_columns:
            c.execute("ALTER TABLE agent_configuration ADD COLUMN hierarchy_effort_set INTEGER NOT NULL DEFAULT 0")
        repository_columns = {row["name"] for row in c.execute("PRAGMA table_info(repositories)")}
        for column in ("remote_url", "remote_branch", "remote_commit"):
            if column not in repository_columns:
                c.execute(f"ALTER TABLE repositories ADD COLUMN {column} TEXT")
        job_columns = {row["name"] for row in c.execute("PRAGMA table_info(jobs)")}
        if "use_ai_hierarchy" not in job_columns:
            c.execute("ALTER TABLE jobs ADD COLUMN use_ai_hierarchy INTEGER NOT NULL DEFAULT 0")
        if "use_embeddings" not in job_columns:
            c.execute("ALTER TABLE jobs ADD COLUMN use_embeddings INTEGER NOT NULL DEFAULT 0")
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
