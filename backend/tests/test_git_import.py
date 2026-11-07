import os
import subprocess
import tempfile
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from graphifier.db import init_db, connect
from graphifier.git_import import (
    queue_import, claim_import, run_import, validate_remote, public_import,
    cancel_import, retry_import, git_command, recover_imports, clone_checkout,
)


class GitImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repos"
        self.root.mkdir()
        self.env = patch.dict(os.environ, {"GRAPHIFIER_DB": str(self.base / "db.sqlite3"), "GRAPHIFIER_REPO_ROOT": str(self.root), "GRAPHIFIER_GIT_HOSTS": "git.example.com"})
        self.env.start()
        self.addCleanup(self.env.stop)
        init_db()

    def row(self, iid):
        with connect() as c:
            return dict(c.execute("SELECT * FROM repository_imports WHERE id=?", (iid,)).fetchone())

    def local_remote(self):
        source = self.base / "source"
        source.mkdir()
        self.git("init", "--initial-branch=main", str(source))
        (source / "main.py").write_text("print('fixture')\n")
        self.git("-C", str(source), "add", ".")
        self.git("-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-m", "fixture")
        remote = self.base / "remote.git"
        self.git("clone", "--bare", str(source), str(remote))
        return remote.as_uri()

    def git(self, *args):
        subprocess.run(["git", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_url_validation_and_enterprise_host(self):
        url, branch, name = validate_remote("git@github.com:owner/project.git", "feature/example")
        self.assertEqual(url, "ssh://git@github.com/owner/project.git")
        self.assertEqual(name, "project")
        self.assertEqual(branch, "feature/example")
        self.assertEqual(validate_remote("https://git.example.com/scm/team/project.git")[2], "project")
        for bad in ("file:///tmp/repo", "../repo", "https://unknown.example/team/repo", "https://token@github.com/a/b", "https://github.com/a/b?token=secret", "ssh://git:secret@github.com/a/b", "https://github.com/a/%2e%2e", "-uhttps://github.com/a/b"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                validate_remote(bad)
        with self.assertRaises(ValueError):
            validate_remote("https://github.com/a/b", "--upload-pack=evil")

    def test_real_clone_registration_idempotence_and_no_hooks(self):
        remote = self.local_remote()
        hookdir = self.base / "hooks"
        hookdir.mkdir()
        marker = self.base / "hook-ran"
        hook = hookdir / "post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        hook.chmod(0o755)
        config = self.base / "gitconfig"
        config.write_text(f"[core]\n hooksPath = {hookdir}\n")
        command = git_command() + ["-c", "protocol.file.allow=always"]
        # File remotes are enabled exclusively in this fixture, never through production validation.
        with patch("graphifier.git_import.validate_remote", return_value=(remote, "main", "fixture")), patch("graphifier.git_import.git_command", return_value=command), patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            queued = queue_import(remote, "main")
            self.assertEqual(queue_import(remote, "main")["id"], queued["id"])
            with connect() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM repositories").fetchone()[0], 0)
            run_import(claim_import())
            completed = self.row(queued["id"])
            self.assertEqual(completed["status"], "completed", completed["error"])
            self.assertTrue((Path(completed["destination"]) / "main.py").is_file())
            self.assertFalse(marker.exists())
            with connect() as c:
                repo = c.execute("SELECT * FROM repositories WHERE id=?", (completed["repo_id"],)).fetchone()
                self.assertEqual(repo["remote_url"], remote)
                self.assertEqual(repo["remote_branch"], "main")
                self.assertEqual(repo["remote_commit"], completed["commit_hash"])
            self.assertEqual(queue_import(remote, "main")["id"], queued["id"])
            self.assertEqual(retry_import(queued["id"])["status"], "completed")
            self.assertEqual(list((self.root / ".graphifier-imports").iterdir()), [])

    def test_failure_and_cancellation_cleanup_staging_and_retry(self):
        queued = queue_import("https://github.com/team/repository.git")
        def failed_clone(url, branch, staging, iid, timeout):
            staging.mkdir()
            (staging / "partial").write_text("partial")
            raise RuntimeError("Git clone failed")
        with patch("graphifier.git_import.clone_checkout", side_effect=failed_clone):
            run_import(claim_import())
        self.assertEqual(self.row(queued["id"])["status"], "failed")
        self.assertEqual(list((self.root / ".graphifier-imports").iterdir()), [])
        self.assertEqual(retry_import(queued["id"])["status"], "queued")
        def cancelled_clone(url, branch, staging, iid, timeout):
            cancel_import(iid)
            raise InterruptedError("cancelled")
        with patch("graphifier.git_import.clone_checkout", side_effect=cancelled_clone):
            run_import(claim_import())
        self.assertEqual(self.row(queued["id"])["status"], "cancelled")
        with connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM repositories").fetchone()[0], 0)

    def test_timeout_and_cancellation_terminate_clone_process(self):
        queued = queue_import("https://github.com/team/repository.git")
        original_popen = subprocess.Popen
        processes = []
        def sleeping_git(*args, **kwargs):
            process = original_popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            processes.append(process)
            return process
        with patch("graphifier.git_import.subprocess.Popen", side_effect=sleeping_git):
            with self.assertRaises(TimeoutError):
                clone_checkout(queued["url"], None, self.root / "stage", queued["id"], 0.01)
            self.assertIsNotNone(processes[-1].poll())
            timer = threading.Timer(0.05, lambda: cancel_import(queued["id"]))
            timer.start()
            try:
                with self.assertRaises(InterruptedError):
                    clone_checkout(queued["url"], None, self.root / "stage", queued["id"], 10)
            finally:
                timer.join()
            self.assertIsNotNone(processes[-1].poll())

    def test_restart_and_symlink_destination(self):
        queued = queue_import("https://github.com/team/repository.git")
        claimed = claim_import()
        recover_imports()
        self.assertEqual(self.row(queued["id"])["status"], "failed")
        retry_import(queued["id"])
        destination = Path(claimed["destination"])
        destination.parent.mkdir()
        target = self.root / "unrelated"
        target.mkdir()
        (target / "keep").write_text("preserve")
        destination.symlink_to(target, target_is_directory=True)
        with patch("graphifier.git_import.clone_checkout") as clone:
            run_import(claim_import())
            clone.assert_not_called()
        self.assertEqual(self.row(queued["id"])["status"], "failed")
        self.assertEqual((target / "keep").read_text(), "preserve")
