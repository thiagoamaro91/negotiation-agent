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
        self.assertIn("screened out: duel/leak.jsonl key-like text", line)
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

    def test_a_commit_only_the_remote_has_is_discarded_and_said_so(self):
        """The Mini is the only writer of mini/logs: someone else's push there is overwritten, with a line saying so."""
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        self.intruder_pushes()
        self.write("logs/duel/a.jsonl", "{}\n{}\n")
        line = self.cycle()
        self.assertRegex(line, r"^pushed [0-9a-f]{7} 1 files \(discarded 1 remote-only commit: the Mini is the only writer\)")
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), "{}\n{}")
        self.assertNotIn("x.txt", self.on_origin("ls-tree", "--name-only", "mini/logs"))

    def test_a_remote_ahead_with_nothing_new_locally_is_fetched_and_overwritten(self):
        """No local change and no local-only commit used to report `nothing new` without looking at the remote."""
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        self.intruder_pushes()
        line = self.cycle()
        self.assertRegex(line, r"^pushed [0-9a-f]{7} 0 files \(discarded 1 remote-only commit")
        self.assertEqual(self.on_origin("rev-parse", "mini/logs"), self.run_git(self.mini / ".logs-push", "rev-parse", "HEAD"))
        self.assertEqual(self.cycle(), "nothing new")

    def intruder_pushes(self):
        other = self.tmp / "other"
        self.run_git(self.tmp, "clone", "-q", "-b", "mini/logs", str(self.origin), str(other))
        (other / "x.txt").write_text("someone else\n")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        self.run_git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "intruder")
        self.run_git(other, "push", "-q", "origin", "mini/logs")

    def test_a_failed_commit_is_retried_not_remembered_as_done(self):
        """Sol, round 2: the source stamps were recorded before the commit, so a commit that failed once (a hook, a full
        disk) made every later cycle say `nothing new` and the files never left the machine."""
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()                                                                     # creates the worktree
        hook = self.mini / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.write("logs/duel/b.jsonl", '{"n": 1}\n')
        self.assertRegex(self.cycle(), r"^push failed: git commit")
        self.assertNotIn("b.jsonl", self.on_origin("ls-tree", "-r", "--name-only", "mini/logs"))
        hook.unlink()
        self.assertRegex(self.cycle(), r"^pushed [0-9a-f]{7} 1 files$")                   # not `nothing new`
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/b.jsonl"), '{"n": 1}')
        self.assertEqual(self.cycle(), "nothing new")

    def test_a_broken_origin_is_a_report_not_a_crash(self):
        self.run_git(self.mini, "remote", "set-url", "origin", str(self.tmp / "nowhere.git"))
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertRegex(self.cycle(), r"^push failed: git fetch")


class Isolation(Sandbox):
    """The tool must never act on the live checkout, and never write outside <worktree>/logs."""

    def main_head(self):
        return self.run_git(self.mini, "rev-parse", "HEAD")

    def test_a_worktree_that_is_a_symlink_to_the_main_checkout_is_refused(self):
        os.symlink(self.mini, self.mini / ".logs-push")
        head = self.main_head()
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertRegex(self.cycle(), r"^push failed: refusing: \.logs-push is a symlink")
        self.assertEqual(self.main_head(), head)
        self.assertIsNone(self.branch_sha())
        self.assertEqual(self.on_origin("rev-parse", "main"), head)

    def test_a_full_clone_in_the_worktree_place_is_refused(self):
        self.run_git(self.tmp, "clone", "-q", str(self.origin), str(self.mini / ".logs-push"))
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertRegex(self.cycle(), r"^push failed: refusing: \.logs-push is not a linked worktree")
        self.assertIsNone(self.branch_sha())

    def test_a_worktree_on_another_branch_is_refused(self):
        self.run_git(self.mini, "worktree", "add", "-q", "-b", "other", str(self.mini / ".logs-push"), "HEAD")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertRegex(self.cycle(), r"^push failed: refusing: \.logs-push is on branch other, not mini/logs")
        self.assertIsNone(self.branch_sha())

    def test_a_worktree_of_another_repository_is_refused(self):
        elsewhere = self.tmp / "elsewhere"
        self.run_git(self.tmp, "clone", "-q", str(self.origin), str(elsewhere))
        self.run_git(elsewhere, "worktree", "add", "-q", "-b", "mini/logs", str(self.mini / ".logs-push"), "HEAD")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertRegex(self.cycle(), r"^push failed: refusing: \.logs-push is a worktree of another repository")

    def test_a_symlinked_destination_never_overwrites_a_live_bot(self):
        self.write("agent/duel.py", "print('live bot')\n")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        wt = self.mini / ".logs-push"
        os.symlink("../../agent/duel.py", wt / "logs" / "dup.jsonl")                  # logs/dup.jsonl -> the live bot
        self.write("logs/dup.jsonl", "evil\n")
        line = self.cycle()
        self.assertRegex(line, r"^push failed: refusing: destination .*dup\.jsonl is a symlink")
        self.assertEqual((self.mini / "agent" / "duel.py").read_text(), "print('live bot')\n")

    def test_a_symlinked_destination_directory_is_refused_too(self):
        self.write("agent/duel.py", "print('live bot')\n")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        wt = self.mini / ".logs-push"
        os.symlink("../agent", wt / "logs" / "sub")
        self.write("logs/sub/duel.py", "evil\n")
        self.assertRegex(self.cycle(), r"^push failed: refusing: destination .*sub is a symlink")
        self.assertEqual((self.mini / "agent" / "duel.py").read_text(), "print('live bot')\n")

    def test_a_symlink_in_logs_is_never_followed(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("not for the VM\n")
        os.symlink(outside, self.mini / "logs" / "link")
        os.symlink(outside / "secret.txt", self.mini / "logs" / "file-link")
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        tree = self.on_origin("ls-tree", "-r", "--name-only", "mini/logs")
        self.assertNotIn("secret.txt", tree)
        self.assertNotIn("link", tree)


class SourceRoot(Sandbox):
    def test_a_mini_checkout_that_is_itself_a_linked_worktree_works(self):
        """Sol, round 2: a legitimate linked-worktree source root was refused (its .git is a file)."""
        linked = self.tmp / "linked"
        self.run_git(self.mini, "worktree", "add", "-q", "-b", "mini-live", str(linked), "HEAD")
        (linked / "logs" / "duel").mkdir(parents=True, exist_ok=True)
        (linked / "logs" / "duel" / "a.jsonl").write_text("{}\n")
        line = lp.cycle(linked, {})
        self.assertRegex(line, r"^pushed [0-9a-f]{7} \d+ files$")
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), "{}")


class Guards(Sandbox):
    """What is committed is only what this cycle copied and screened."""

    LEAKS = {
        "logs/a/bk-key.jsonl": '{"x": "bk_abcdef"}\n',
        "logs/a/tk-underscore.jsonl": '{"x": "tk_abcd_efgh"}\n',
        "logs/a/assign.txt": "BAZAAR_KEY=abcdef123456\n",
        "logs/a/export.txt": "export BROKER_KEY='abcdef123456'\n",
        "logs/a/json-env.jsonl": '{"GH_TOKEN": "ghp_abcdefgh1234"}\n',
        "logs/a/env-copy.txt": "nothing in here looks like a key\n",                 # the name alone says env
        "logs/a/.env": "A=B\n",
        "logs/a/server.pem": "-----\n",
        # Sol, round 2: bare names, other prefixes, Bearer values
        "logs/b/bare-token.json": '{"token":"ghp_fakeabcdefgh1234"}\n',
        "logs/b/bare-token2.json": '{"token": "abcdef1234567890"}\n',
        "logs/b/bare-key.txt": "KEY=abcdef123456\n",
        "logs/b/bare-key-json.json": '{"KEY": "abcdef1234567890"}\n',
        "logs/b/lower.txt": "api_key = abcdefghijkl\n",
        "logs/b/password.txt": "password: hunter2hunter2\n",
        "logs/b/auth.txt": "Authorization: Bearer abcdef1234567890\n",
        "logs/b/basic.txt": "authorization=Basic dXNlcjpwYXNzd29yZA==\n",
        "logs/b/sk.jsonl": '{"x": "sk-abcdefgh1234"}\n',
        "logs/b/gho.jsonl": '{"x": "gho_abcdefgh1234"}\n',
        "logs/b/pat.jsonl": '{"x": "github_pat_abcdefgh1234"}\n',
        "logs/b/secret-json.json": '{"Secret": "abcdefghijklmnop"}\n',
    }

    FINE = {
        "logs/c/key-field.jsonl": '{"key": "RET-07", "price": 22}\n',
        "logs/c/team-key.jsonl": '{"key": "t14:LAT-07:20248"}\n',
        "logs/c/tokens.jsonl": '{"tokens": 12, "monkey": "banana"}\n',
        "logs/c/prose.txt": "the key to the deal is the price; no token was spent\n",
    }

    def test_nothing_that_looks_like_a_credential_is_copied_or_committed(self):
        for rel, text in self.LEAKS.items():
            self.write(rel, text)
        for rel, text in self.FINE.items():
            self.write(rel, text)                                                       # ordinary fields and prose
        line = self.cycle()
        self.assertTrue(line.startswith("pushed"), line)
        shipped = set(self.on_origin("ls-tree", "-r", "--name-only", "mini/logs", "logs/a/", "logs/b/", "logs/c/").split())
        self.assertEqual(shipped, set(self.FINE))
        for rel in self.LEAKS:
            self.assertFalse((self.mini / ".logs-push" / rel).exists(), rel)

    def test_screen_only_runs_the_same_screener_for_a_hand_copy(self):
        for rel, text in {**self.LEAKS, **self.FINE}.items():
            self.write(rel, text)
        os.symlink(self.mini / "README.md", self.mini / "logs" / "link.txt")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = lp.main(["--screen-only", str(self.mini / "logs")])
        self.assertEqual(rc, 1)
        refused = {line.split(" ")[1].rstrip(":") for line in out.getvalue().splitlines() if line.startswith("REFUSED")}
        self.assertEqual(refused, {r[len("logs/"):] for r in self.LEAKS} | {"link.txt"})
        clean = self.tmp / "clean"
        clean.mkdir()
        (clean / "ok.jsonl").write_text('{"key": "RET-07"}\n')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(lp.main(["--screen-only", str(clean)]), 0)
        self.assertEqual(out.getvalue().strip(), "clean")

    def test_a_secret_already_sitting_dirty_in_the_worktree_is_never_committed(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        wt = self.mini / ".logs-push"
        (wt / "logs" / "planted.txt").write_text("tk-abcd-efgh\n")                      # untracked
        (wt / "logs" / "duel" / "a.jsonl").write_text("{}\n{\"x\": \"bk_abcdef\"}\n")       # tracked, dirty
        self.run_git(wt, "add", "logs/planted.txt")                                      # and pre-staged
        self.write("logs/duel/b.jsonl", "{}\n")                                          # an unrelated change to publish
        line = self.cycle()
        self.assertRegex(line, r"^pushed [0-9a-f]{7} 1 files$")
        self.assertEqual(self.on_origin("show", "--name-only", "--format=", "mini/logs"), "logs/duel/b.jsonl")
        self.assertNotIn("planted", self.on_origin("ls-tree", "-r", "--name-only", "mini/logs"))
        self.assertNotIn("bk_abcdef", self.on_origin("log", "-p", "mini/logs"))

    def test_a_secret_in_a_source_that_is_skipped_stays_unpublished(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        wt = self.mini / ".logs-push"
        (wt / "logs" / "duel" / "a.jsonl").write_text('{"x": "bk_abcdef"}\n')           # dirty copy of a source we now skip
        self.write("logs/duel/a.jsonl", '{"x": "bk_abcdef"}\n')
        self.assertEqual(self.cycle().split(" (")[0], "nothing new")
        self.assertEqual(self.on_origin("show", "mini/logs:logs/duel/a.jsonl"), "{}")

    def test_unrelated_files_staged_by_someone_else_are_not_in_the_commit(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        wt = self.mini / ".logs-push"
        (wt / "README.md").write_text("edited by hand\n")
        self.run_git(wt, "add", "README.md")
        self.write("logs/duel/b.jsonl", "{}\n")
        self.assertTrue(self.cycle().startswith("pushed"))
        self.assertEqual(self.on_origin("show", "--name-only", "--format=", "mini/logs"), "logs/duel/b.jsonl")
        self.assertEqual(self.on_origin("show", "mini/logs:README.md"), "code")


class Locking(Sandbox):
    def hold(self):
        import fcntl
        fd = os.open(self.mini / lp.LOCKFILE, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd

    def test_a_cycle_that_finds_the_lock_held_does_nothing_and_says_so(self):
        fd = self.hold()
        self.write("logs/duel/a.jsonl", "{}\n")
        self.assertEqual(self.cycle(), "push failed: another logs_push holds the lock")
        self.assertFalse((self.mini / ".logs-push").exists())                            # not even the worktree
        self.assertIsNone(self.branch_sha())
        os.close(fd)
        self.assertTrue(self.cycle().startswith("pushed"))

    def test_once_exits_nonzero_while_another_instance_holds_the_lock(self):
        fd = self.hold()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(lp.main(["--root", str(self.mini), "--once"]), 1)
        os.close(fd)
        self.assertIn("another logs_push holds the lock", out.getvalue())

    def test_the_lock_is_released_after_each_cycle(self):
        self.write("logs/duel/a.jsonl", "{}\n")
        self.cycle()
        os.close(self.hold())                                                            # would raise if it were still held


if __name__ == "__main__":
    unittest.main()
