"""Queued Git imports with a staged checkout and atomic repository registration."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .db import connect
from .paths import allowed_root, checked_path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def validate_remote(url: str, branch: str | None = None) -> tuple[str, str | None, str]:
    url = url.strip()
    if re.match(r"^git@[^/:]+:", url):
        host, path = url[4:].split(":", 1)
        url = f"ssh://git@{host}/{path}"
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTPS or SSH Git repository URL") from exc
    allowed = {"github.com", "bitbucket.org"}
    allowed.update(host.strip().lower() for host in os.environ.get("GRAPHIFIER_GIT_HOSTS", "").split(",") if host.strip())
    if parsed.scheme not in {"https", "ssh"} or (parsed.hostname or "").lower() not in allowed:
        raise ValueError("Use a GitHub or Bitbucket HTTPS/SSH URL, or add the enterprise hostname to GRAPHIFIER_GIT_HOSTS")
    if (parsed.password is not None or parsed.query or parsed.fragment or "%" in url or
            any(char.isspace() or ord(char) < 32 for char in url)):
        raise ValueError("Repository URLs cannot contain credentials, query parameters, fragments or escapes")
    if parsed.scheme == "https" and parsed.username is not None:
        raise ValueError("Use existing Git credentials instead of credentials in the URL")
    if parsed.scheme == "ssh" and parsed.username not in {None, "git"}:
        raise ValueError("SSH URLs must use the git user")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*", part) or part in {".", ".."} for part in parts):
        raise ValueError("Repository URL must include an owner/project and repository path")
    branch = branch.strip() if branch else None
    if branch and (len(branch) > 250 or branch.startswith("-") or branch.endswith((".", "/")) or
                   ".." in branch or "@{" in branch or "//" in branch or
                   not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", branch) or
                   any(part.startswith(".") or part.endswith(".lock") for part in branch.split("/"))):
        raise ValueError("Enter a valid branch name")
    host = parsed.hostname.lower()
    netloc = ("git@" if parsed.scheme == "ssh" else "") + host
    if port is not None:
        netloc += f":{port}"
    normalized = urlunsplit((parsed.scheme, netloc, "/" + "/".join(parts), "", ""))
    name = parts[-1].removesuffix(".git")
    return normalized, branch, name


def public_import(row) -> dict:
    result = {key: row[key] for key in ("id", "url", "branch", "name", "status", "progress", "error", "repo_id", "commit_hash", "created_at", "updated_at")}
    result["cancel_requested"] = bool(row["cancel_requested"])
    return result


def queue_import(url: str, branch: str | None = None, name: str | None = None) -> dict:
    url, branch, default_name = validate_remote(url, branch)
    name = (name or default_name).strip()
    if not name or len(name) > 200 or any(ord(char) < 32 for char in name):
        raise ValueError("Repository name must contain between 1 and 200 characters")
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute("SELECT * FROM repository_imports WHERE url=? AND branch IS ? AND status IN ('queued','cloning','completed') ORDER BY created_at DESC LIMIT 1", (url,branch)).fetchone()
        if existing and (existing["status"] != "completed" or Path(existing["destination"]).is_dir()):
            return public_import(existing)
        iid = str(uuid.uuid4())
        destination = checked_path(allowed_root() / "remote" / f"{default_name}-{iid[:12]}", must_exist=False)
        created = stamp()
        c.execute("INSERT INTO repository_imports(id,url,branch,name,destination,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)", (iid,url,branch,name,str(destination),created,created))
        return public_import(c.execute("SELECT * FROM repository_imports WHERE id=?", (iid,)).fetchone())


def claim_import():
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM repository_imports WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            return None
        c.execute("UPDATE repository_imports SET status='cloning',progress=0.05,updated_at=? WHERE id=?", (stamp(),row["id"]))
        return dict(row)


def cancelled(iid: str) -> bool:
    with connect() as c:
        row = c.execute("SELECT cancel_requested FROM repository_imports WHERE id=?", (iid,)).fetchone()
        return row is None or bool(row[0])


def cancel_import(iid: str) -> dict:
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM repository_imports WHERE id=?", (iid,)).fetchone()
        if row is None:
            raise LookupError("Repository import not found")
        if row["status"] in {"queued", "cloning"}:
            c.execute("UPDATE repository_imports SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated_at=? WHERE id=?", (stamp(),iid))
        return public_import(c.execute("SELECT * FROM repository_imports WHERE id=?", (iid,)).fetchone())


def retry_import(iid: str) -> dict:
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM repository_imports WHERE id=?", (iid,)).fetchone()
        if row is None:
            raise LookupError("Repository import not found")
        if row["status"] in {"failed", "cancelled"}:
            c.execute("UPDATE repository_imports SET status='queued',cancel_requested=0,error=NULL,progress=0,updated_at=? WHERE id=?", (stamp(),iid))
        return public_import(c.execute("SELECT * FROM repository_imports WHERE id=?", (iid,)).fetchone())


def recover_imports():
    with connect() as c:
        c.execute("UPDATE repository_imports SET status='failed',error='Worker restarted during import. Retry the import to continue.',updated_at=? WHERE status='cloning'", (stamp(),))


def git_command() -> list[str]:
    return ["git", "-c", "core.hooksPath=/dev/null", "-c", "init.templateDir=", "-c", "core.fsmonitor=false", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=", "-c", "filter.lfs.required=false", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "protocol.ssh.allow=always", "-c", "submodule.recurse=false"]


def git_environment() -> dict:
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/usr/bin/false", SSH_ASKPASS="/usr/bin/false",
               GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes", GIT_LFS_SKIP_SMUDGE="1")
    return env


def _terminate(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except ProcessLookupError:
        pass


def clone_checkout(url: str, branch: str | None, staging: Path, iid: str, timeout: float):
    args = git_command() + ["clone", "--template=", "--depth", "1", "--single-branch", "--no-tags", "--no-recurse-submodules"]
    if branch:
        args += ["--branch", branch]
    args += ["--", url, str(staging)]
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=git_environment(), start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if cancelled(iid):
                raise InterruptedError("Repository import cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("Repository clone exceeded GRAPHIFIER_CLONE_TIMEOUT")
            time.sleep(0.25)
        if process.returncode:
            raise RuntimeError(f"Git clone failed (exit {process.returncode}). Check the repository URL, branch, network and existing Git credentials or SSH access.")
    finally:
        _terminate(process)


def checkout_metadata(path: Path, expected_url: str) -> tuple[str, str | None]:
    def read(*args):
        result = subprocess.run(git_command() + ["-C", str(path), *args], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=10, env=git_environment())
        if result.returncode:
            raise RuntimeError("Imported directory is not a valid Git checkout")
        return result.stdout.strip()
    if read("config", "--get", "remote.origin.url") != expected_url:
        raise RuntimeError("Import destination already exists with a different repository")
    commit = read("rev-parse", "HEAD")
    if not re.fullmatch(r"[a-fA-F0-9]{40,64}", commit):
        raise RuntimeError("Git returned an invalid commit identifier")
    branch = read("rev-parse", "--abbrev-ref", "HEAD")
    return commit, None if branch == "HEAD" else branch


def run_import(job):
    iid = job["id"]
    staging_parent = None
    try:
        url, branch, _ = validate_remote(job["url"], job["branch"])
        raw_destination = Path(job["destination"])
        if raw_destination.is_symlink() or raw_destination.parent.is_symlink():
            raise ValueError("Import destination cannot use a symlink")
        destination = checked_path(raw_destination, must_exist=False)
        if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
            raise ValueError("Import destination is not an ordinary directory")
        if cancelled(iid):
            raise InterruptedError("Repository import cancelled")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = checked_path(destination, must_exist=False)
        if not destination.exists():
            timeout = float(os.environ.get("GRAPHIFIER_CLONE_TIMEOUT", "1800"))
            if not 1 <= timeout <= 86400:
                raise ValueError("GRAPHIFIER_CLONE_TIMEOUT must be between 1 and 86400 seconds")
            staging_root = checked_path(allowed_root() / ".graphifier-imports", must_exist=False)
            staging_root.mkdir(exist_ok=True)
            staging_parent = Path(tempfile.mkdtemp(prefix=f"{iid}-", dir=staging_root))
            staging = staging_parent / "checkout"
            clone_checkout(url, branch, staging, iid, timeout)
            commit, checked_branch = checkout_metadata(staging, url)
            if cancelled(iid):
                raise InterruptedError("Repository import cancelled")
            # A destination belongs exclusively to this import UUID. Never overwrite it.
            if destination.exists():
                raise RuntimeError("Import destination was created while cloning")
            staging.rename(destination)
        else:
            # Recover a complete rename after interruption before the registration transaction.
            commit, checked_branch = checkout_metadata(destination, url)
        if branch and checked_branch != branch:
            raise RuntimeError("Import destination does not match the requested branch")
        created = stamp()
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT cancel_requested FROM repository_imports WHERE id=?", (iid,)).fetchone()
            if current is None or current[0]:
                raise InterruptedError("Repository import cancelled")
            repo = c.execute("SELECT id FROM repositories WHERE path=?", (str(destination),)).fetchone()
            rid = repo["id"] if repo else str(uuid.uuid5(uuid.NAMESPACE_URL, f"graphifier-import:{iid}"))
            if repo is None:
                c.execute("INSERT INTO repositories(id,name,path,created_at,remote_url,remote_branch,remote_commit) VALUES(?,?,?,?,?,?,?)", (rid,job["name"],str(destination),created,url,checked_branch,commit))
            c.execute("UPDATE repository_imports SET status='completed',progress=1,repo_id=?,commit_hash=?,error=NULL,updated_at=? WHERE id=?", (rid,commit,created,iid))
    except Exception as exc:
        status = "cancelled" if isinstance(exc, InterruptedError) or cancelled(iid) else "failed"
        # Only our validation/operational errors are safe to show. Git stderr may contain credentials.
        error = str(exc) if isinstance(exc, (ValueError, RuntimeError, TimeoutError)) else "Repository import failed. Check Git installation, disk space and repository access."
        with connect() as c:
            c.execute("UPDATE repository_imports SET status=?,error=?,updated_at=? WHERE id=?", (status,None if status == "cancelled" else error,stamp(),iid))
    finally:
        if staging_parent is not None:
            shutil.rmtree(staging_parent, ignore_errors=True)
