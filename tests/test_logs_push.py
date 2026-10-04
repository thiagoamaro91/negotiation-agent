"""tools/logs_push.py: the Mini's logs/ travel to the branch mini/logs of the origin, and nothing else moves.

Every test runs against a temporary bare repository as `origin` and a clone of it as the "Mini checkout"; git's global
and system configuration are switched off, so no hook or identity of the machine running the tests matters.

    python3 -m unittest tests.test_logs_push
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import logs_push as lp  # noqa: E402

ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
REAL_GIT = shutil.which("git")


class Stop(Exception):
    pass


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patch = mock.patch.dict(os.environ, ENV)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin, self.mini = self.tmp / "origin.git", self.tmp / "mini"
        self.run_git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.run_git(self.tmp, "clone", "-q", str(self.origin), str(self.mini))
        self.write("logs/score.jsonl", '{"tick": 1445, "cash": 253}\n')
        self.write("README.md", "code\n")
        self.run_git(self.mini, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        self.run_git(self.mini, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main")
        self.run_git(self.mini, "push", "-q", "origin", "HEAD:main")
        self.seen = {}

    # -- helpers
    def run_git(self, cwd, *args):
        r = subprocess.run([REAL_GIT, *args], cwd=cwd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, (args, r.stderr))
        return r.stdout.strip()

    def on_origin(self, *args):
        return self.run_git(self.tmp, "--git-dir", str(self.origin), *args)

    def write(self, rel, text):
        path = self.mini / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def cycle(self, **kw):
        return lp.cycle(self.mini, self.seen, **kw)

    def branch_sha(self):
        r = subprocess.run([REAL_GIT, "--git-dir", str(self.origin), "rev-parse", "--verify", "-q", "mini/logs"],
                           capture_output=True, text=True)
        return r.stdout.strip() or None

    def failing_push(self):
        """A `git` ahead of the real one on PATH whose push always fails, like a network or credential error."""
        shim = self.tmp / "shim"
        shim.mkdir(exist_ok=True)
        (shim / "git").write_text(f'#!/bin/sh\nif [ "$1" = push ]; then echo "fatal: could not read Username" >&2; exit 1; fi\n'
                                  f'exec {REAL_GIT} "$@"\n')
        (shim / "git").chmod(0o755)
        return mock.patch.dict(os.environ, {"PATH": f"{shim}:{os.environ['PATH']}"})


class Mirror(Sandbox):
    def test_a_commit_lands_on_mini_logs_with_the_copied_file(self):
        self.write("logs/duel/2026-10-04.jsonl", '{"event": "run_start"}\n')
        line = self.cycle()
        self.assertRegex(line, r"^pushed [0-9a-f]{7} \d+ files$")
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/2026-10-04.jsonl"), '{"event": "run_start"}')
        self.assertEqual(self.on_origin("show", "mini/logs:logs/score.jsonl"), '{"tick": 1445, "cash": 253}')
        self.assertEqual(self.on_origin("show", "mini/logs:README.md"), "code")      # it starts from main's tree

    def test_the_commit_names_the_madrid_time_and_the_tick(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle(now=datetime(2026, 10, 4, 6, 45, tzinfo=timezone.utc))              # 08:45 in Madrid (CEST)
        self.assertEqual(self.on_origin("log", "-1", "--format=%s", "mini/logs"), "logs: 08:45 Madrid (tick 1445)")

    def test_the_tick_is_left_out_when_no_log_gives_it(self):
        (self.mini / "logs" / "score.jsonl").unlink()
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        self.assertRegex(self.on_origin("log", "-1", "--format=%s", "mini/logs"), r"^logs: \d\d:\d\d Madrid$")

    def test_nothing_lands_on_main_and_the_checkout_is_untouched(self):
        main_before = self.on_origin("rev-parse", "main")
        head_before = self.run_git(self.mini, "rev-parse", "HEAD")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        self.assertEqual(self.on_origin("rev-parse", "main"), main_before)
        self.assertEqual(self.run_git(self.mini, "rev-parse", "HEAD"), head_before)
        self.assertEqual(self.run_git(self.mini, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(self.run_git(self.mini, "stash", "list"), "")
        self.assertEqual(self.run_git(self.mini, "diff", "--stat"), "")                 # no tracked file of main touched

    def test_main_moving_on_the_origin_never_moves_the_checkout(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        other = self.tmp / "other"
        self.run_git(self.tmp, "clone", "-q", str(self.origin), str(other))
        (other / "README.md").write_text("new code\n")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "someone merged")
        self.run_git(other, "push", "-q", "origin", "HEAD:main")
        head = self.run_git(self.mini, "rev-parse", "HEAD")
        self.write("logs/duel/a.jsonl", "{}\n{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        self.assertEqual(self.run_git(self.mini, "rev-parse", "HEAD"), head)             # the Mini pulls main by itself, not here
        self.assertEqual((self.mini / "README.md").read_text(), "code\n")

    def test_a_second_run_with_no_change_makes_no_commit(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        sha = self.branch_sha()
        self.assertEqual(self.cycle(), "nothing new")
        self.assertEqual(self.branch_sha(), sha)
        self.assertEqual(self.cycle(), "nothing new")
        self.assertEqual(self.on_origin("rev-list", "--count", "mini/logs"), "2")        # main's commit and one logs commit

    def test_a_new_line_makes_one_commit_with_only_that_file(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        self.write("logs/duel/a.jsonl", "{}\n{}\n")
        self.assertRegex(self.cycle(), r"^pushed [0-9a-f]{7} 1 files$")
        self.assertEqual(self.on_origin("show", "--name-only", "--format=", "mini/logs"), "logs/duel/a.jsonl")

    def test_a_file_that_left_logs_stays_in_the_target(self):
        path = self.write("logs/duel/gone.jsonl", "{}\n")
        self.cycle()
        path.unlink()
        self.write("logs/duel/other.jsonl", "{}\n")
        self.cycle()
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/gone.jsonl"), "{}")

    def test_a_half_written_jsonl_line_is_not_copied(self):
        self.write("logs/duel/a.jsonl", '{"n": 1}\n{"n": 2')
        self.cycle()
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), '{"n": 1}')
        self.write("logs/duel/a.jsonl", '{"n": 1}\n{"n": 2}\n')
        self.cycle()
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), '{"n": 1}\n{"n": 2}')

    def test_a_file_with_key_like_text_never_leaves_the_machine(self):
        self.write("logs/duel/leak.jsonl", '{"auth": "tk-abcd-efgh"}\n')
        self.write("logs/duel/ok.jsonl", "{}\n")
        line = self.cycle()
        self.assertIn("skipped, key-like text: duel/leak.jsonl", line)
        self.assertEqual(self.on_origin("ls-tree", "--name-only", "mini/logs", "logs/duel/"), "logs/duel/ok.jsonl")
        self.assertNotIn("tk-abcd", self.on_origin("log", "-p", "mini/logs"))

    def test_it_continues_the_branch_when_the_remote_already_has_one(self):
        other = self.tmp / "other"
        self.run_git(self.tmp, "clone", "-q", str(self.origin), str(other))
        self.run_git(other, "checkout", "-q", "-b", "mini/logs")
        (other / "logs").mkdir(exist_ok=True)
        (other / "logs" / "earlier.txt").write_text("kept\n")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "earlier logs")
        self.run_git(other, "push", "-q", "origin", "mini/logs")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        self.assertEqual(self.on_origin("show", "mini/logs:logs/earlier.txt"), "kept")
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), "{}")

    def test_the_worktree_is_ignored_by_the_repo(self):
        self.assertIn(".logs-push/", (ROOT / ".gitignore").read_text().split())


class Failures(Sandbox):
    def test_a_failed_push_is_reported_and_the_commit_goes_out_on_the_next_cycle(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        with self.failing_push():
            line = self.cycle()
        self.assertRegex(line, r"^push failed: .*could not read Username.* stays local")
        self.assertIsNone(self.branch_sha())
        self.assertRegex(self.cycle(), r"^pushed [0-9a-f]{7} 0 files$")                 # nothing new to commit, one to push
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), "{}")

    def test_the_loop_keeps_going_after_a_failed_push(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        sleeps = []

        def sleep(_s):
            sleeps.append(1)
            if len(sleeps) >= 3:
                raise Stop

        out = io.StringIO()
        with self.failing_push(), mock.patch.object(lp.time, "sleep", sleep), contextlib.redirect_stdout(out), \
                self.assertRaises(Stop):
            lp.main(["--root", str(self.mini), "--every", "1"])
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(all("push failed" in x for x in lines), lines)

    def test_once_exits_nonzero_only_when_it_could_not_push(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        with self.failing_push(), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lp.main(["--root", str(self.mini), "--once"]), 1)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(lp.main(["--root", str(self.mini), "--once"]), 0)
        self.assertIn("pushed", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(lp.main(["--root", str(self.mini), "--once"]), 0)
        self.assertIn("nothing new", out.getvalue())

    def test_a_stale_lease_heals_by_itself(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        other = self.tmp / "other"
        self.run_git(self.tmp, "clone", "-q", "-b", "mini/logs", str(self.origin), str(other))
        (other / "x.txt").write_text("someone else\n")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "intruder")
        self.run_git(other, "push", "-q", "origin", "mini/logs")
        self.write("logs/duel/a.jsonl", "{}\n{}\n")
        self.assertTrue(self.cycle().startswith("push failed"))                          # the lease is stale
        self.assertTrue(self.cycle().startswith("pushed"))                               # refreshed, then overwritten
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), "{}\n{}")

    def test_a_broken_origin_is_a_report_not_a_crash(self):
        self.run_git(self.mini, "remote", "set-url", "origin", str(self.tmp / "nowhere.git"))
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertRegex(self.cycle(), r"^push failed: git fetch")


if __name__ == "__main__":
    unittest.main()
