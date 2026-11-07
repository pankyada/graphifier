from __future__ import annotations

import os
from pathlib import Path

EXCLUDED_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "vendors", "dist", "build", "target", ".venv", "venv", "__pycache__", ".next", "coverage"}
from .languages import SOURCE_SUFFIXES, MANIFESTS


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


def safe_files(root: Path, max_files: int | None = None, max_bytes: int | None = None,
               max_file_bytes: int | None = None) -> list[Path]:
    """Return a deterministic inventory or fail explicitly when a configured cap is hit."""
    max_files = max_files if max_files is not None else int(os.environ.get("GRAPHIFIER_MAX_FILES", "100000"))
    max_bytes = max_bytes if max_bytes is not None else int(os.environ.get("GRAPHIFIER_MAX_SOURCE_BYTES", "1000000000"))
    max_file_bytes = max_file_bytes if max_file_bytes is not None else int(os.environ.get("GRAPHIFIER_MAX_FILE_BYTES", "5000000"))
    out, total = [], 0
    def walk_error(error):
        raise ValueError(f"Cannot enumerate repository: {error}") from error
    for current, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".") and not (base / d).is_symlink())
        for name in sorted(files):
            p = base / name
            low = name.lower()
            if p.is_symlink() or (p.suffix.lower() not in SOURCE_SUFFIXES and name not in MANIFESTS): continue
            if low in {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"} or any(x in low for x in ("secret", "credential", "private_key", "apikey", "password", "token")): continue
            size = p.stat().st_size
            if size > max_file_bytes:
                raise ValueError(f"Source file exceeds GRAPHIFIER_MAX_FILE_BYTES ({max_file_bytes}): {p.relative_to(root)}")
            total += size
            if len(out) >= max_files or total > max_bytes:
                raise ValueError("Repository exceeds scan budget; increase GRAPHIFIER_MAX_FILES or GRAPHIFIER_MAX_SOURCE_BYTES. No partial snapshot was published.")
            out.append(p)
    return out
