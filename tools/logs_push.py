#!/usr/bin/env python3
"""Mirror the Mini checkout's logs/ onto the git branch `mini/logs` and push it, so the VM analyst reads fresh data.

Keyless: it never calls the game API and never reads a key. It only runs git on the repo it lives in.

    python3 tools/logs_push.py --every 600     # a loop, one cycle every 10 minutes (what the factory runs)
    python3 tools/logs_push.py --once          # one cycle; exit 1 if it could not push

Why a second worktree. The checkout the bots run in stays on `main`, untouched: this tool never commits to main, never
pulls main (it fetches origin/main once, to create the worktree), never stashes, never switches a branch. It keeps a
second worktree, `<repo>/.logs-push`, on branch `mini/logs`. Every cycle, under a lock file (`<repo>/.logs-push.lock`;
a cycle that finds it held reports so and does nothing, so two writers never interleave):

  0. it VERIFIES the worktree before touching anything: not a symlink, resolves to itself, is not the main checkout, is
     a linked worktree (git-dir differs from the common dir) and is on branch mini/logs; and every destination path
     lies inside <worktree>/logs with no symlink on the way. Otherwise it refuses and says why;
  1. it empties the worktree's index, then copies the files under logs/ into <worktree>/logs/ (overwrite; a file that
     disappeared from logs/ stays in the target, nothing is ever deleted). A .jsonl file is copied up to its last
     newline. Every file is SCREENED first with the repo's shared scrubber (tools/redaction.py: tk-, tk_, bk_, adm_,
     sk- key shapes), for credential assignments (`BAZAAR_KEY=...`, `"GH_TOKEN": "..."`) and by name (env, credentials,
     secrets, passwords, id_rsa, .pem, .key): a file that fails is not copied and is named in the report;
  2. it stages ONLY the files it copied this cycle (explicit paths), checks that nothing else is staged, and commits
     `logs: HH:MM Madrid (tick N)` if something is (tick: last line of logs/score.jsonl, else the feed, else left out).
     Anything else in the worktree, dirty or pre-staged, is never committed;
  3. it fetches origin/mini/logs, then `git push --force-with-lease`.

Data-loss policy: the Mini is the ONLY writer of mini/logs. A commit that exists only on the remote branch is discarded
by the next push (and reported); never push to mini/logs from anywhere else. A push that fails (network, credentials)
is logged and the loop goes on; the commit stays local and the next cycle pushes it. One line per cycle on stdout:
`pushed <sha> <n files>`, `nothing new`, or `push failed: <reason>`.
First run: `git worktree add -B mini/logs <repo>/.logs-push origin/main` (from origin/mini/logs if that exists).
Stdlib only; the commit time is Madrid time whatever TZ says.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import redaction  # noqa: E402  (the one scrubber for everything that leaves the key machine)

BRANCH = "mini/logs"
WORKTREE = ".logs-push"
LOCKFILE = ".logs-push.lock"
MADRID = ZoneInfo("Europe/Madrid")
GIT_TIMEOUT_S = 180
# a credential assignment: BAZAAR_KEY=..., export GH_TOKEN: ..., "BROKER_KEY": "..." (any value of 8+ characters)
ASSIGNMENT = re.compile(rb"""(?im)(?:^|[\s,{;])(?:export\s+)?["']?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?)"""
                        rb"""["']?\s*[=:]\s*["']?[A-Za-z0-9_\-./+=]{8,}""")
CREDENTIAL_NAME = re.compile(r"(?i)(?:^|[._-])(?:env|credentials?|secrets?|passwords?|passwd|id_rsa|id_ed25519)(?:[._-]|$)"
                             r"|\.(?:pem|key|p12|pfx)$")
FALLBACK_IDENTITY = ["-c", "user.name=Mini logs push", "-c", "user.email=mini-logs@localhost"]


class PushError(Exception):
    """A git step failed; the message is what the one-line report says."""


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    try:
        r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise PushError(f"git {args[0]} timed out after {GIT_TIMEOUT_S} s") from None
    except OSError as e:
        raise PushError(f"cannot run git: {e}") from None
    if check and r.returncode != 0:
        raise PushError(f"git {args[0]}: " + (r.stderr.strip().splitlines() or ["failed"])[-1][:200])
    return r


class Busy(Exception):
    """Another logs_push holds the lock."""


class Lock:
    """One whole cycle at a time: flock on <repo>/.logs-push.lock, never waited for."""

    def __init__(self, root: Path):
        self.path = root / LOCKFILE
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise Busy("another logs_push holds the lock") from None
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)


def ensure_worktree(root: Path, remote: str = "origin", branch: str = BRANCH) -> Path:
    wt = root / WORKTREE
    if (wt / ".git").exists():
        return wt
    git(root, "fetch", "--quiet", remote, "main")
    exists = git(root, "ls-remote", "--exit-code", "--heads", remote, branch, check=False).returncode == 0
    if exists:
        git(root, "fetch", "--quiet", remote, branch)
    git(root, "worktree", "add", "-q", "-B", branch, str(wt), f"{remote}/{branch}" if exists else f"{remote}/main")
    return wt


def verify_worktree(root: Path, wt: Path, branch: str) -> None:
    """Refuse unless wt really is the separate linked worktree on `branch`: a symlink, the main checkout, a full clone
    or another branch would make every git command below act on the live checkout."""
    if wt.is_symlink():
        raise PushError(f"refusing: {WORKTREE} is a symlink")
    real = wt.resolve()
    if real == root.resolve():
        raise PushError(f"refusing: {WORKTREE} is the main checkout")
    top = git(wt, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(top).resolve() != real:
        raise PushError(f"refusing: {WORKTREE} belongs to the git checkout at {top}")
    git_dir = (wt / git(wt, "rev-parse", "--git-dir").stdout.strip()).resolve()
    common = (wt / git(wt, "rev-parse", "--git-common-dir").stdout.strip()).resolve()
    if git_dir == common:
        raise PushError(f"refusing: {WORKTREE} is not a linked worktree")
    if (root / ".git").exists() and common != (root / ".git").resolve():
        raise PushError(f"refusing: {WORKTREE} is a worktree of another repository")
    on = git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if on != branch:
        raise PushError(f"refusing: {WORKTREE} is on branch {on}, not {branch}")
    logs = wt / "logs"
    if logs.is_symlink() or (logs.exists() and logs.resolve() != real / "logs"):
        raise PushError("refusing: <worktree>/logs is a symlink")


def _tail_json_tick(path: Path):
    """The `tick` of the last complete JSON line of a file, reading only its tail."""
    import json
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            lines = fh.read().splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            tick = json.loads(raw).get("tick")
        except (ValueError, AttributeError):
            continue
        if isinstance(tick, int):
            return tick
    return None


def latest_tick(logs: Path):
    for name in ("score.jsonl", "feed/feed.jsonl"):
        tick = _tail_json_tick(logs / name)
        if tick is not None:
            return tick
    return None


def screen(rel: str, data: bytes):
    """Why this file must not leave the machine, or None. The shared scrubber's key shapes, credential assignments, and
    names that look like env or credential files."""
    if CREDENTIAL_NAME.search(Path(rel).name):
        return "credential-like name"
    if redaction.SECRET.search(data.decode("utf-8", "replace")):
        return "key-like text"
    if ASSIGNMENT.search(data):
        return "credential assignment"
    return None


def safe_target(dst_root: Path, rel: str) -> Path:
    """dst_root/rel, refusing a symlink anywhere on the way or a path that leaves dst_root."""
    target, probe = dst_root / rel, dst_root
    for part in Path(rel).parts:
        probe = probe / part
        if probe.is_symlink():
            raise PushError(f"refusing: destination {probe.relative_to(dst_root.parent)} is a symlink")
    real_root = dst_root.resolve()
    if real_root not in target.resolve().parents:
        raise PushError(f"refusing: destination {rel} leaves {WORKTREE}/logs")
    return target


def mirror(src: Path, dst: Path, seen: dict) -> tuple[list, list]:
    """Copy src/** into dst/** (overwrite, never delete, symlinks never followed). `seen` maps a source path to its
    (size, mtime_ns) at the last look, so an unchanged file costs one stat. Returns (relative paths written this cycle,
    [(relative path, reason)] screened out)."""
    copied, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            rel = str(path.relative_to(src))
            try:
                st = path.stat()
                stamp = (st.st_size, st.st_mtime_ns)
                if seen.get(path) == stamp:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            seen[path] = stamp
            if path.suffix == ".jsonl":
                data = data[:data.rfind(b"\n") + 1]
            why = screen(rel, data)
            if why:
                skipped.append((rel, why))
                continue
            target = safe_target(dst, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            safe_target(dst, rel)                                   # again, now that the directories exist
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
                copied.append(rel)
    return copied, skipped


def stage(wt: Path, copied: list) -> list:
    """Empty the index, add exactly `copied`, and return what is staged; anything else staged is an error."""
    git(wt, "reset", "--quiet")
    paths = [f"logs/{rel}" for rel in copied]
    if paths:
        r = subprocess.run(["git", "check-ignore", "--stdin"], cwd=wt, input="\n".join(paths), text=True,
                           capture_output=True, timeout=GIT_TIMEOUT_S)     # untracked paths a .gitignore rule covers
        ignored = set(r.stdout.split())
        paths = [x for x in paths if x not in ignored]
        for i in range(0, len(paths), 200):
            git(wt, "add", "--", *paths[i:i + 200])
    staged = [x for x in git(wt, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if x]
    extra = [x for x in staged if x not in set(paths)]
    if extra:
        git(wt, "reset", "--quiet")
        raise PushError(f"refusing: unexpected staged files in {WORKTREE} ({', '.join(extra[:3])})")
    return staged


def cycle(root: Path, seen: dict, remote: str = "origin", branch: str = BRANCH, now=None) -> str:
    """One mirror, commit and push. Returns the one-line report; never raises."""
    try:
        with Lock(root):
            return _cycle(root, seen, remote, branch, now)
    except Busy as e:
        return f"push failed: {e}"
    except PushError as e:
        return f"push failed: {e}"
    except Exception as e:  # nothing may stop the loop
        return f"push failed: {type(e).__name__}: {str(e)[:160]}"


def _cycle(root: Path, seen: dict, remote: str, branch: str, now) -> str:
    wt = ensure_worktree(root, remote, branch)
    verify_worktree(root, wt, branch)
    copied, skipped = mirror(root / "logs", wt / "logs", seen)
    note = f" (screened out: {', '.join(f'{r} {w}' for r, w in skipped[:3])})" if skipped else ""
    staged = stage(wt, copied)
    if staged:
        tick = latest_tick(root / "logs")
        stamp = (now or datetime.now(MADRID)).astimezone(MADRID).strftime("%H:%M")
        message = f"logs: {stamp} Madrid" + (f" (tick {tick})" if tick is not None else "")
        ident = [] if git(wt, "config", "user.email", check=False).stdout.strip() else FALLBACK_IDENTITY
        git(wt, *ident, "commit", "-q", "-m", message)
    # fetch every cycle: the push decision is made against what the remote has now, not against a stale view
    listed = git(wt, "ls-remote", "--exit-code", "--heads", remote, branch, check=False)
    if listed.returncode not in (0, 2):
        raise PushError("git ls-remote: " + (listed.stderr.strip().splitlines() or ["unreachable"])[-1][:200])
    on_remote = listed.returncode == 0
    if on_remote:
        git(wt, "fetch", "--quiet", remote, branch)
        local_only = int(git(wt, "rev-list", "--count", f"{remote}/{branch}..HEAD").stdout.strip() or 0)
        remote_only = int(git(wt, "rev-list", "--count", f"HEAD..{remote}/{branch}").stdout.strip() or 0)
    else:
        local_only, remote_only = 1, 0
    if not local_only and not remote_only:
        return "nothing new" + note
    sha = git(wt, "rev-parse", "--short", "HEAD").stdout.strip()
    pushed = git(wt, "push", "-q", "--force-with-lease", remote, f"HEAD:refs/heads/{branch}", check=False)
    if pushed.returncode != 0:
        reason = (pushed.stderr.strip().splitlines() or ["rejected"])[-1][:200]
        raise PushError(f"{reason} (commit {sha} stays local, next cycle pushes it)")
    lost = f" (discarded {remote_only} remote-only commit{'s' if remote_only != 1 else ''}: the Mini is the only writer)" if remote_only else ""
    return f"pushed {sha} {len(staged)} files" + lost + note


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mirror logs/ to the branch mini/logs and push it")
    ap.add_argument("--every", type=float, default=600, help="seconds between cycles (default 600)")
    ap.add_argument("--once", action="store_true", help="one cycle, exit 1 if it could not push")
    ap.add_argument("--root", default=str(ROOT), help="the repo to mirror (default: the one this tool lives in)")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default=BRANCH)
    a = ap.parse_args(argv)
    root, seen = Path(a.root).resolve(), {}
    while True:
        line = cycle(root, seen, a.remote, a.branch)
        print(f"{datetime.now(MADRID):%H:%M:%S} {line}", flush=True)
        if a.once:
            return 1 if line.startswith("push failed") else 0
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
