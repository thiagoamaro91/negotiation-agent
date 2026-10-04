#!/usr/bin/env python3
"""Mirror the Mini checkout's logs/ onto the git branch `mini/logs` and push it, so the VM analyst reads fresh data.

Keyless: it never calls the game API and never reads a key. It only runs git on the repo it lives in.

    python3 tools/logs_push.py --every 600     # a loop, one cycle every 10 minutes (what the factory runs)
    python3 tools/logs_push.py --once          # one cycle; exit 1 if it could not push

Why a second worktree. The checkout the bots run in stays on `main`, untouched: this tool never commits to main, never
pulls main (it fetches origin/main once, to create the worktree), never stashes, never switches a branch. It keeps a
second worktree, `<repo>/.logs-push`, on branch `mini/logs`, and each cycle:

  1. copies every file under logs/ into <worktree>/logs/ (overwrite; a file that disappeared from logs/ stays in the
     target, nothing is ever deleted). A .jsonl file is copied up to its last newline, so a line a bot is writing right
     now never arrives half-written. A file with key-like text (tk-, bk_, adm_ shapes) is skipped and named;
  2. `git add -A logs`, and a commit `logs: HH:MM Madrid (tick N)` only if something changed (tick comes from the last
     line of logs/score.jsonl, else the feed's last line, else it is left out);
  3. `git push --force-with-lease origin mini/logs`. The Mini is the only writer of that branch: if the lease goes stale
     (someone else pushed to it) the next cycle refreshes it from the remote and overwrites.

A push that fails (network, credentials) is logged and the loop goes on; the commit stays local and the next cycle
pushes it. One line per cycle on stdout: `pushed <sha> <n files>`, `nothing new`, or `push failed: <reason>`.
First run: `git worktree add -B mini/logs <repo>/.logs-push origin/main` (from origin/mini/logs if that exists).
Stdlib only; the commit time is Madrid time whatever TZ says.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "mini/logs"
WORKTREE = ".logs-push"
MADRID = ZoneInfo("Europe/Madrid")
GIT_TIMEOUT_S = 180
KEYLIKE = re.compile(rb"tk-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}|bk_[A-Za-z0-9_-]{8,}|adm_[A-Za-z0-9_-]{8,}")
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


def mirror(src: Path, dst: Path, seen: dict) -> tuple[int, list]:
    """Copy src/** into dst/** (overwrite, never delete). `seen` maps a source path to its (size, mtime_ns) at the last
    copy, so an unchanged file costs one stat. Returns (files copied, files skipped for key-like text)."""
    copied, skipped = 0, []
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            st = path.stat()
            stamp = (st.st_size, st.st_mtime_ns)
            if seen.get(path) == stamp:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        target = dst / path.relative_to(src)
        if KEYLIKE.search(data):
            skipped.append(str(path.relative_to(src)))
            seen[path] = stamp
            continue
        if path.suffix == ".jsonl":
            data = data[:data.rfind(b"\n") + 1]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
            copied += 1
        seen[path] = stamp
    return copied, skipped


def cycle(root: Path, seen: dict, remote: str = "origin", branch: str = BRANCH, now=None) -> str:
    """One mirror, commit and push. Returns the one-line report; never raises."""
    try:
        return _cycle(root, seen, remote, branch, now)
    except PushError as e:
        return f"push failed: {e}"
    except Exception as e:  # nothing may stop the loop
        return f"push failed: {type(e).__name__}: {str(e)[:160]}"


def _cycle(root: Path, seen: dict, remote: str, branch: str, now) -> str:
    wt = ensure_worktree(root, remote, branch)
    _, skipped = mirror(root / "logs", wt / "logs", seen)
    note = f" (skipped, key-like text: {', '.join(skipped[:3])})" if skipped else ""
    git(wt, "add", "-A", "--", "logs")
    changed = git(wt, "diff", "--cached", "--name-only").stdout.split()
    if changed:
        tick = latest_tick(root / "logs")
        stamp = (now or datetime.now(MADRID)).astimezone(MADRID).strftime("%H:%M")
        message = f"logs: {stamp} Madrid" + (f" (tick {tick})" if tick is not None else "")
        ident = [] if git(wt, "config", "user.email", check=False).stdout.strip() else FALLBACK_IDENTITY
        git(wt, *ident, "commit", "-q", "-m", message)
    remote_ref = git(wt, "rev-parse", "--verify", "-q", f"refs/remotes/{remote}/{branch}", check=False)
    ahead = remote_ref.returncode != 0 or int(git(wt, "rev-list", "--count", f"{remote}/{branch}..HEAD").stdout.strip() or 0) > 0
    if not changed and not ahead:
        return "nothing new" + note
    sha = git(wt, "rev-parse", "--short", "HEAD").stdout.strip()
    pushed = git(wt, "push", "-q", "--force-with-lease", remote, f"HEAD:refs/heads/{branch}", check=False)
    if pushed.returncode != 0:
        git(wt, "fetch", "--quiet", remote, branch, check=False)       # a stale lease heals on the next cycle
        reason = (pushed.stderr.strip().splitlines() or ["rejected"])[-1][:200]
        raise PushError(f"{reason} (commit {sha} stays local, next cycle pushes it)")
    return f"pushed {sha} {len(changed)} files" + note


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
