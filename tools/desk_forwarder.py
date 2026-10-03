"""Desk forwarder: shows every desk's heartbeat on the brain page. Keyless and local; it never talks to the game.

Each desk on the key machine writes its state to logs/state/desk-<name>.json (agent/market_desk.py, agent/broker.py,
and any desk added later). The brain only learns about desks through POST /ingest/desk (tools/brain.py), so this
loop reads those files and posts each one in the brain's shape: {name, mode, tick, last_decision, reason}.

    python3 tools/desk_forwarder.py                       # token from ~/bazaar/brain.env (--env), brain on 127.0.0.1:8790
    python3 tools/desk_forwarder.py --once --dry-run      # print what it would post

A heartbeat is posted only when its file changed since the last post, so a desk that stops shows its real age on the
page instead of looking alive. The brain drops any field named like a key and redacts key-shaped text; the file's
text is shown escaped, never run.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "logs" / "state"
EVERY_SECONDS = 10.0
LIVE_MODES = ("run", "live")        # anything else (watch, plan, shadow) is shown as shadow


def load_brain_env(path: Path) -> None:
    """BRAIN_URL and BRAIN_WRITE_TOKEN from the brain's own env file (never the repo's .env, which holds the team key
    on the key machine). Variables already set in the environment win."""
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = (s.strip() for s in line.split("=", 1))
                if k in ("BRAIN_URL", "BRAIN_WRITE_TOKEN"):
                    os.environ.setdefault(k, v)


def text(v) -> str:
    """A field as one line of text: strings as they are, anything else as compact JSON."""
    if v is None:
        return ""
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def to_desk(name: str, hb: dict) -> dict | None:
    """One heartbeat file in the brain's desk shape, or None if it is not a heartbeat."""
    if not isinstance(hb, dict):
        return None
    tick = hb.get("tick")
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        tick = None
    reason = hb.get("reason") or hb.get("what") or ""
    return {"name": name, "mode": "live" if str(hb.get("mode", "")).lower() in LIVE_MODES else "shadow",
            "tick": tick, "last_decision": text(hb.get("last_decision"))[:300], "reason": text(reason)[:500]}


def heartbeats(state: Path = STATE) -> list:
    """[(name, mtime, desk)] for every readable logs/state/desk-<name>.json."""
    out = []
    for path in sorted(state.glob("desk-*.json")):
        try:
            desk = to_desk(path.stem[len("desk-"):], json.loads(path.read_text()))
            if desk:
                out.append((desk["name"], path.stat().st_mtime, desk))
        except (OSError, ValueError):
            continue
    return out


def post(url: str, token: str, desk: dict) -> int:
    req = urllib.request.Request(url.rstrip("/") + "/ingest/desk", data=json.dumps(desk).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json", "X-Brain-Write": token})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def forward_once(state: Path, sent: dict, send) -> int:
    """Send every heartbeat whose file changed since its last send; `sent` remembers name -> mtime. Returns how many
    were sent. A failed send is retried on the next pass."""
    n = 0
    for name, mtime, desk in heartbeats(state):
        if sent.get(name) == mtime:
            continue
        try:
            send(desk)
            sent[name] = mtime
            n += 1
        except Exception as e:  # the brain restarting: try again next pass
            print(f"{time.strftime('%H:%M:%S')} {name}: post failed ({type(e).__name__})", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--dry-run", action="store_true", help="print what would be posted, post nothing")
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--env", default=str(Path.home() / "bazaar" / "brain.env"), help="the brain's env file")
    args = ap.parse_args()
    load_brain_env(Path(args.env))
    url, token = os.environ.get("BRAIN_URL", "http://127.0.0.1:8790"), os.environ.get("BRAIN_WRITE_TOKEN", "")
    if not token and not args.dry_run:
        raise SystemExit("BRAIN_WRITE_TOKEN is not set (it is in ~/bazaar/brain.env on the VM)")
    send = (lambda d: print(json.dumps(d, ensure_ascii=False))) if args.dry_run else (lambda d: post(url, token, d))
    sent: dict = {}
    while True:
        forward_once(Path(args.state), sent, send)
        if args.once:
            return
        time.sleep(EVERY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
