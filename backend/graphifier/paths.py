from __future__ import annotations

import os
from pathlib import Path

EXCLUDED_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "vendors", "dist", "build", "target", ".venv", "venv", "__pycache__", ".next", "coverage"}
SOURCE_SUFFIXES = {".sas", ".sql", ".ddl", ".dml", ".py", ".sh", ".bash"}


def allowed_root() -> Path:
    raw = os.environ.get("GRAPHIFIER_REPO_ROOT")
    return Path(raw).expanduser().resolve() if raw else (Path(__file__).resolve().parents[2] / "examples").resolve()


def checked_path(raw: str | Path, must_exist: bool = True) -> Path:
    root = allowed_root()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("Path must stay inside the configured repository root")
    if must_exist and not resolved.is_dir():
        raise ValueError("Path must be an existing directory")
    return resolved


def safe_files(root: Path, max_files: int = 1200, max_bytes: int = 30_000_000, max_file_bytes: int = 2_000_000) -> list[Path]:
    out, total = [], 0
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".") and not (base / d).is_symlink()]
        for name in sorted(files):
            p = base / name
            low = name.lower()
            if p.is_symlink() or p.suffix.lower() not in SOURCE_SUFFIXES: continue
            if low in {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"} or p.suffix.lower() in {".pem", ".p12", ".pfx", ".key"} or any(x in low for x in ("secret", "credential", "private_key", "apikey", "password", "token")): continue
            if p.stat().st_size > max_file_bytes: continue
            total += p.stat().st_size
            if len(out) >= max_files or total > max_bytes: return out
            out.append(p)
    return out
