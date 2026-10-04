import fcntl
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "mini"))
import autodeploy  # noqa: E402


class MiniAutodeploy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.remote = self.base / "remote.git"
        self.source = self.base / "source"
        self.deploy_root = self.base / "deploy"
        self.git("init", "--bare", str(self.remote), cwd=self.base)
        self.git("init", "-b", "main", str(self.source), cwd=self.base)
        self.git("config", "user.name", "Test User", cwd=self.source)
        self.git("config", "user.email", "test@example.invalid", cwd=self.source)
        (self.source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git("add", "app.py", cwd=self.source)
        self.git("commit", "-m", "first", cwd=self.source)
        self.first = self.rev()
        self.git("remote", "add", "origin", str(self.remote), cwd=self.source)
        self.git("push", "-u", "origin", "main", cwd=self.source)
        self.restarts = []
        self.health_failures = 0
        self.config = {
            "deploy_root": str(self.deploy_root),
            "remote_url": str(self.remote),
            "branch": "main",
            "git": "/usr/bin/git",
            "launchctl": "/bin/launchctl",
            "service_label": "com.example.swarm",
            "fetch_timeout_seconds": 10,
            "validation_timeout_seconds": 10,
            "validation_commands": [
                {"argv": [sys.executable, "-m", "compileall", "-q", "app.py"], "cwd": "."}
            ],
            "health": {
                "url": "http://127.0.0.1:8777/meta",
                "env_file": str(self.base / "swarm.env"),
                "token_key": "SWARM_TOKEN",
            },
        }

    def tearDown(self):
        for root, directories, files in os.walk(self.base, topdown=False):
            for name in files:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | 0o600)
            for name in directories:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | 0o700)
        self.tmp.cleanup()

    def git(self, *args, cwd):
        return subprocess.run(
            ["/usr/bin/git", *args], cwd=cwd, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def rev(self):
        return self.git("rev-parse", "HEAD", cwd=self.source)

    def commit(self, name="app.py", contents="VALUE = 2\n", message="update"):
        (self.source / name).write_text(contents, encoding="utf-8")
        self.git("add", name, cwd=self.source)
        self.git("commit", "-m", message, cwd=self.source)
        revision = self.rev()
        self.git("push", "origin", "main", cwd=self.source)
        return revision

    def health(self, settings):
        if self.health_failures:
            self.health_failures -= 1
            raise autodeploy.DeployError("mock health failure")

    def restart(self):
        self.restarts.append("restart")

    def deployer(self):
        return autodeploy.Deployer(
            self.config, health_checker=self.health, identity_checker=lambda release: None,
            restarter=self.restart,
        )

    def status(self):
        return json.loads((self.deploy_root / "status.json").read_text(encoding="utf-8"))

    def test_successful_revision_update_and_unchanged_noop(self):
        first = self.deployer().deploy()
        self.assertEqual((first["result"], first["deployed_revision"]), ("success", self.first))
        self.assertEqual((self.deploy_root / "current" / "app.py").read_text(), "VALUE = 1\n")
        self.assertFalse((self.deploy_root / "current" / ".git").exists())
        second_revision = self.commit()
        second = self.deployer().deploy()
        self.assertEqual((second["result"], second["deployed_revision"]), ("success", second_revision))
        self.assertEqual((self.deploy_root / "current").resolve().name, second_revision)
        restart_count = len(self.restarts)
        unchanged = self.deployer().deploy()
        self.assertEqual(unchanged["result"], "unchanged")
        self.assertEqual(len(self.restarts), restart_count)
        self.assertEqual(self.deployer().deploy()["result"], "unchanged")

    def test_failed_validation_retains_old_current(self):
        self.assertEqual(self.deployer().deploy()["result"], "success")
        failed_revision = self.commit()
        self.config["validation_commands"] = [[sys.executable, "-c", "raise SystemExit(9)"]]
        result = self.deployer().deploy()
        self.assertEqual(result["result"], "failed")
        self.assertEqual((self.deploy_root / "current").resolve().name, self.first)
        self.assertEqual(result["deployed_revision"], self.first)
        self.assertEqual(result["attempted_revision"], failed_revision)

    def test_failed_health_rolls_back_and_records_failed_revision(self):
        self.assertEqual(self.deployer().deploy()["result"], "success")
        failed_revision = self.commit()
        self.health_failures = 1
        result = self.deployer().deploy()
        self.assertEqual(result["result"], "failed")
        self.assertEqual(result["attempted_revision"], failed_revision)
        self.assertEqual(result["deployed_revision"], self.first)
        self.assertEqual((self.deploy_root / "current").resolve().name, self.first)
        self.assertIn("previous release restored, restarted, and verified", result["error"])
        self.assertEqual(len(self.restarts), 3)

    def test_failed_restart_rolls_back_and_records_failed_revision(self):
        self.assertEqual(self.deployer().deploy()["result"], "success")
        failed_revision = self.commit()
        calls = []

        def flaky_restart():
            calls.append("restart")
            if len(calls) == 1:
                raise autodeploy.DeployError("mock restart failure")

        deployer = autodeploy.Deployer(
            self.config, health_checker=self.health, identity_checker=lambda release: None,
            restarter=flaky_restart,
        )
        result = deployer.deploy()
        self.assertEqual(result["result"], "failed")
        self.assertEqual(result["attempted_revision"], failed_revision)
        self.assertEqual(result["deployed_revision"], self.first)
        self.assertEqual((self.deploy_root / "current").resolve().name, self.first)
        self.assertEqual(calls, ["restart", "restart"])

    def test_concurrent_lock_is_a_successful_skip(self):
        self.deploy_root.mkdir()
        with (self.deploy_root / "deploy.lock").open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.deployer().deploy()
        self.assertEqual(result, {"result": "locked", "exit_code": 0})
        self.assertFalse((self.deploy_root / "repo.git").exists())

    def test_dirty_user_checkout_is_untouched(self):
        checkout = self.base / "dirty-checkout"
        self.git("clone", str(self.remote), str(checkout), cwd=self.base)
        tracked = checkout / "app.py"
        tracked.write_text("LOCAL DIRTY VALUE\n", encoding="utf-8")
        untracked = checkout / "private.log"
        untracked.write_text("keep me\n", encoding="utf-8")
        before = self.git("status", "--porcelain=v1", cwd=checkout)
        self.assertEqual(self.deployer().deploy()["result"], "success")
        self.assertEqual(tracked.read_text(), "LOCAL DIRTY VALUE\n")
        self.assertEqual(untracked.read_text(), "keep me\n")
        self.assertEqual(self.git("status", "--porcelain=v1", cwd=checkout), before)

    def test_non_fast_forward_remote_is_refused(self):
        deployed = self.commit()
        self.assertEqual(self.deployer().deploy()["deployed_revision"], deployed)
        self.git("reset", "--hard", self.first, cwd=self.source)
        self.git("push", "--force", "origin", "main", cwd=self.source)
        result = self.deployer().deploy()
        self.assertEqual(result["result"], "failed")
        self.assertIn("non-fast-forward", result["error"])
        self.assertEqual(result["attempted_revision"], self.first)
        self.assertEqual(result["deployed_revision"], deployed)
        self.assertEqual((self.deploy_root / "current").resolve().name, deployed)

    def test_prepare_requires_later_restart_and_health(self):
        prepared = self.deployer().deploy(prepare=True)
        self.assertEqual(prepared["result"], "staged_pending_health")
        self.assertIsNone(prepared.get("deployed_revision"))
        self.assertEqual(prepared["staged_revision"], self.first)
        self.assertEqual(self.restarts, [])
        deployed = self.deployer().deploy()
        self.assertEqual(deployed["result"], "success")
        self.assertEqual(deployed["deployed_revision"], self.first)
        self.assertEqual(len(self.restarts), 1)

    def test_reused_release_refuses_source_integrity_mismatch(self):
        self.assertEqual(self.deployer().deploy()["result"], "success")
        source = self.deploy_root / "releases" / self.first / "app.py"
        source.chmod(0o644)
        source.write_text("TAMPERED = True\n", encoding="utf-8")
        restarts = len(self.restarts)
        result = self.deployer().deploy()
        self.assertEqual(result["result"], "failed")
        self.assertIn("source integrity mismatch", result["error"])
        self.assertEqual(len(self.restarts), restarts)

    def test_successful_release_is_frozen_after_validation(self):
        self.assertEqual(self.deployer().deploy()["result"], "success")
        release = self.deploy_root / "releases" / self.first
        self.assertEqual(release.stat().st_mode & 0o222, 0)
        self.assertEqual((release / "app.py").stat().st_mode & 0o222, 0)
        self.assertTrue((self.deploy_root / "manifests" / f"{self.first}.json").is_file())

    def test_orphan_manifest_from_interrupted_publish_is_recovered(self):
        manifests = self.deploy_root / "manifests"
        manifests.mkdir(parents=True)
        manifest = manifests / f"{self.first}.json"
        manifest.write_text('{"revision":"incomplete"}\n', encoding="utf-8")
        result = self.deployer().deploy()
        self.assertEqual(result["result"], "success")
        recovered = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(recovered["revision"], self.first)
        self.assertTrue(recovered["files"])

    def test_stale_listener_identity_failure_rolls_back(self):
        self.assertEqual(self.deployer().deploy()["result"], "success")
        attempted = self.commit()
        identities = []

        def identity(release):
            identities.append(release.name)
            if release.name == attempted:
                raise autodeploy.DeployError("stale listener owns port")

        deployer = autodeploy.Deployer(
            self.config, health_checker=self.health, identity_checker=identity,
            restarter=self.restart,
        )
        result = deployer.deploy()
        self.assertEqual(result["result"], "failed")
        self.assertEqual(result["attempted_revision"], attempted)
        self.assertEqual(result["deployed_revision"], self.first)
        self.assertEqual((self.deploy_root / "current").resolve().name, self.first)
        self.assertEqual(identities, [attempted, self.first])

    def test_real_loopback_health_requires_403_then_authenticated_200(self):
        token = "local-test-token-12345"
        env_file = self.base / "health.env"
        env_file.write_text(f"SWARM_TOKEN={token}\n", encoding="utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                code = 200 if query.get("t") == [token] else 403
                self.send_response(code)
                self.end_headers()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            autodeploy.check_health({
                "url": f"http://127.0.0.1:{server.server_port}/meta",
                "env_file": str(env_file),
                "token_key": "SWARM_TOKEN",
                "attempts": 1,
                "request_timeout_seconds": 1,
            })
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_health_client_refuses_redirects(self):
        captured = []

        class Capture(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                captured.append(self.path)
                self.send_response(200)
                self.end_headers()

        capture = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Capture)

        class Redirect(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{capture.server_port}/capture")
                self.end_headers()

        redirect = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threads = [
            threading.Thread(target=capture.serve_forever, daemon=True),
            threading.Thread(target=redirect.serve_forever, daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            status = autodeploy._http_status(
                f"http://127.0.0.1:{redirect.server_port}/meta?t=must-not-leak", 1,
            )
            self.assertEqual(status, 302)
            self.assertEqual(captured, [])
        finally:
            capture.shutdown()
            redirect.shutdown()
            capture.server_close()
            redirect.server_close()
            for thread in threads:
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
