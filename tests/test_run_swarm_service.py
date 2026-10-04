import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_swarm_service", ROOT / "tools" / "mini" / "run_swarm_service.py"
)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


class RunSwarmServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.deploy = self.base / "deploy"
        self.release = self.deploy / "releases" / ("a" * 40)
        (self.release / "tools").mkdir(parents=True)
        (self.release / "tools" / "swarm.py").write_text("# fixture\n", encoding="utf-8")
        (self.deploy / "current").symlink_to(self.release)
        self.env_file = self.base / "swarm.env"

    def tearDown(self):
        self.tmp.cleanup()

    def test_release_symlink_must_stay_in_sha_release_directory(self):
        release, swarm = runner.resolve_release(self.deploy)
        expected_release = self.release.resolve()
        self.assertEqual(release, expected_release)
        self.assertEqual(swarm, expected_release / "tools" / "swarm.py")

        outside = self.base / ("b" * 40)
        (outside / "tools").mkdir(parents=True)
        (outside / "tools" / "swarm.py").write_text("# outside\n", encoding="utf-8")
        (self.deploy / "current").unlink()
        (self.deploy / "current").symlink_to(outside)
        with self.assertRaisesRegex(runner.ConfigError, "under"):
            runner.resolve_release(self.deploy)

    def test_missing_and_short_tokens_fail_without_exposing_value(self):
        with self.assertRaisesRegex(runner.ConfigError, "cannot read") as missing:
            runner.read_swarm_token(self.env_file)
        self.assertNotIn("SWARM_TOKEN=", str(missing.exception))

        self.env_file.write_text("SWARM_TOKEN=too-short\n", encoding="utf-8")
        with self.assertRaisesRegex(runner.ConfigError, "at least 16") as short:
            runner.read_swarm_token(self.env_file)
        self.assertNotIn("too-short", str(short.exception))

    def test_exec_uses_exact_paths_and_keeps_token_out_of_argv(self):
        token = "0123456789abcdef"
        self.env_file.write_text(f"IGNORED_KEY=ignored\nSWARM_TOKEN={token}\n", encoding="utf-8")
        repo, live, out = self.base / "repo", self.base / "live", self.base / "out"
        argv = [
            "--deploy-root", str(self.deploy),
            "--env-file", str(self.env_file),
            "--python", sys.executable,
            "--repo", str(repo),
            "--live", str(live),
            "--out", str(out),
        ]

        with mock.patch.dict(os.environ, {"BASE": "kept"}, clear=True), \
             mock.patch.object(runner.os, "chdir") as chdir, \
             mock.patch.object(runner.os, "execve") as execve:
            self.assertEqual(runner.main(argv), 127)

        python = str(Path(sys.executable).resolve())
        expected_release = self.release.resolve()
        command = [
            python, "-u", str(expected_release / "tools" / "swarm.py"), "run",
            "--repo", str(repo), "--live", str(live), "--out", str(out),
            "--host", "127.0.0.1", "--port", "8777",
        ]
        chdir.assert_called_once_with(expected_release)
        execve.assert_called_once()
        executable, actual_command, env = execve.call_args.args
        self.assertEqual(executable, python)
        self.assertEqual(actual_command, command)
        self.assertNotIn(token, actual_command)
        self.assertEqual(env["SWARM_TOKEN"], token)
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["BASE"], "kept")
        self.assertNotIn("IGNORED_KEY", env)


if __name__ == "__main__":
    unittest.main()
