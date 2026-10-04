"""Shared run logging for every Team 3 agent.

Every agent writes one JSONL file per agent per day under logs/<agent>/, and the files are committed to git so
the whole team can read every run. Team, broker and admin keys are redacted before anything touches disk.

    from runlog import RunLog, save_thread
    log = RunLog("abuela")
    log.start(plan=[...])
    log.event("say", thread=49, price=12)
    save_thread(b, 49)          # full transcript to logs/threads/thread-00049.json
    log.end(cash=383)

Set BAZAAR_OPERATOR=hector (or thiago) so the logs say who ran what.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
_SECRET = re.compile(r"\b(tk-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}|bk_[A-Za-z0-9_-]+|adm_[A-Za-z0-9_-]+)\b")
_SECRET_FIELDS = ("key", "token", "secret")


def redact(obj):
    """Strip anything that looks like a key, and any field named like one."""
    if isinstance(obj, str):
        return _SECRET.sub("[redacted]", obj)
    if isinstance(obj, dict):
        return {k: ("[redacted]" if any(s in str(k).lower() for s in _SECRET_FIELDS) and isinstance(v, str) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(obj), ensure_ascii=False, indent=1) + "\n")
    return path


class RunLog:
    def __init__(self, agent: str):
        self.agent = agent
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.operator = os.environ.get("BAZAAR_OPERATOR") or os.environ.get("USER", "unknown")
        self.path = LOGS / agent / (time.strftime("%Y-%m-%d") + ".jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, event: str, **data) -> None:
        row = redact({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": self.run_id, "agent": self.agent,
                      "event": event, **data})
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        shown = " ".join(f"{k}={v}" for k, v in row.items() if k not in ("ts", "run", "agent", "event"))
        print(f"[{row['ts'][11:]}] {event} {shown}", flush=True)

    def start(self, **data) -> None:
        self.event("run_start", operator=self.operator, argv=sys.argv[1:], **data)

    def end(self, **data) -> None:
        self.event("run_end", **data)


def save_thread(b, thread_id: int) -> Path:
    """Full transcript of one conversation (dealer or team), as the server holds it."""
    return write_json(LOGS / "threads" / f"thread-{int(thread_id):05d}.json", b.thread(thread_id))
