"""The pitch's numbers at 14:50: which version to read (A or B) and the five figures to refresh. Read-only, no key.

Three verdicts, never two:
- A: at least one settlement on our venue v20 between two OTHER teams (two distinct parties, both tNN, neither of them
  us) in the feed, AND the keyless leaderboard's v20 row counting at least one trade. Read version A.
- B-UNCONFIRMED: the feed and the leaderboard do not agree, or the leaderboard could not be read while the feed shows
  such a settlement. Read version B with its "not confirmed" sentence: never say that no trade settled.
- B: no such settlement in the feed, and no leaderboard count against it. Read version B as written.
A trade we were part of, a Market Test bench pair or a dealer is never such a settlement.

    python3 tools/pitch_numbers.py --live           # the 14:50 command: feed plus GET /api/leaderboard (keyless)
    python3 tools/pitch_numbers.py --live --stage   # the on-stage demo: no team id anywhere, done within 5 s
    python3 tools/pitch_numbers.py                  # offline: the numbers, but never VERSION A (nothing confirms it)
    (BAZAAR_FEED=<dir> or --feed DIR reads another clone's logs/feed/)
    python3 tools/pitch_numbers.py --json

The five numbers: (1) v20 trades between two other teams, the A/B fact; (2) other teams that posted on v20, and how
many offers; (3) public events recorded, our recorder's copy merged with the complete copies of the stretches it missed
(logs/feed-vm/, the same GAP_SOURCES tools/ledger.py fills from); (4) ledger readings that match our real cash; (5) pull requests merged.
(4) runs tools/ledger.py --json, (5) runs `gh` and --live reads the leaderboard, all three at once under one deadline
(--deadline SECONDS; 5 with --stage, else none): whatever has not answered by then prints "unavailable".
Without --stage the output names team ids (the parties of a v20 trade, the makers in --json), which the script on stage
never does; --stage prints only the verdict, cards, prices and counts.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENUE, US = "v20", "t03"
REPO = "thiagoamaro91/negotiation-agent"
URL = "https://bazaar.causaprima.ai"
TEAM = re.compile(r"^t\d\d$")
GAP_SOURCES = (ROOT / "logs" / "feed-vm" / "feed.jsonl",)  # as tools/ledger.py


def load(path: Path, extra: tuple = ()) -> list:
    """Every event once (a recorder can write one twice; two copies overlap), in id order. Missing extras are skipped."""
    seen = {}
    for p in (path, *extra):
        if p != path and not p.exists():
            continue
        for line in p.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("id") is not None:
                seen.setdefault(e["id"], e)
    return [seen[k] for k in sorted(seen)]


def others_trades(events: list, venue: str = VENUE, us: str = US) -> list:
    """Settlements on `venue` whose two parties are teams other than us: the fact that picks version A."""
    out = []
    for e in events:
        p = e.get("payload") or {}
        if e.get("type") != "settlement" or p.get("venue") != venue:
            continue
        parties = p.get("parties") or []
        if len(parties) == 2 and parties[0] != parties[1] and all(TEAM.match(str(t)) and t != us for t in parties):
            out.append({"tick": e.get("tick"), "parties": parties, "price": p.get("price"),
                        "cards": [i.get("ref") for i in p.get("items") or [] if i.get("kind") == "card"]})
    return out


def version(trades: list, board: dict | None) -> tuple:
    """(A, B-UNCONFIRMED or B, why). A needs the feed's trade AND the leaderboard's count; any doubt is B-UNCONFIRMED."""
    counted = (board or {}).get("trades") or 0
    if trades and counted:
        return "A", f"feed and leaderboard agree (feed {len(trades)}, leaderboard v20 trades {counted})"
    if trades and board is None:
        return "B-UNCONFIRMED", f"the feed shows {len(trades)}, the leaderboard was not read or did not answer"
    if trades:
        return "B-UNCONFIRMED", f"the feed shows {len(trades)}, the leaderboard's v20 row says 0: they disagree"
    if counted:
        return "B-UNCONFIRMED", f"the leaderboard counts {counted} trade(s) on v20, the feed shows none between two other teams"
    return "B", "no settlement on v20 between two other teams in the feed" + ("" if board else " (leaderboard not read)")


def venue_makers(events: list, venue: str = VENUE, us: str = US) -> collections.Counter:
    """Offers listed on `venue` per maker, other teams only (not us, not the Market Test bench)."""
    c = collections.Counter()
    for e in events:
        if e.get("type") != "offer.listed":
            continue
        p = e.get("payload") or {}
        o = p.get("offer") or {}
        maker = o.get("maker") or e.get("actor")
        if (p.get("venue") or o.get("venue")) == venue and TEAM.match(str(maker)) and maker != us:
            c[maker] += 1
    return c


def gather(calls: dict, deadline: float | None) -> dict:
    """Run every call at once; a call still running at the deadline (seconds from now) gives None ("unavailable")."""
    out = {k: None for k in calls}

    def run(k, f):
        try:
            out[k] = f(deadline)
        except Exception:  # noqa: BLE001  a failed figure prints "unavailable", never a traceback on a stage screen
            out[k] = None

    threads = [threading.Thread(target=run, args=(k, f), daemon=True) for k, f in calls.items()]
    end = None if deadline is None else time.monotonic() + deadline
    for t in threads:
        t.start()
    for t in threads:
        t.join(None if end is None else max(0.0, end - time.monotonic()))
    return dict(out)


def ledger_check(feed_dir: Path, timeout: float | None = None) -> tuple | None:
    """(matching readings, readings, last tick) from tools/ledger.py's check against our real cash."""
    env = dict(os.environ, BAZAAR_FEED=str(feed_dir))
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "ledger.py"), "--json"], capture_output=True,
                           text=True, timeout=timeout or 600, env=env, cwd=ROOT)
        hist = json.loads(r.stdout)["check_history"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None
    return sum(1 for h in hist if h.get("ok")), len(hist), hist[-1]["tick"] if hist else None


def merged_prs(timeout: float | None = None) -> int | None:
    try:
        r = subprocess.run(["gh", "pr", "list", "--repo", REPO, "--state", "merged", "--limit", "500", "--json",
                            "number"], capture_output=True, text=True, timeout=timeout or 60)
        return len(json.loads(r.stdout))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def leaderboard_v20(timeout: float | None = None) -> dict | None:
    try:
        with urllib.request.urlopen(URL + "/api/leaderboard", timeout=min(timeout or 10, 10)) as r:
            body = json.load(r)
    except (OSError, ValueError):
        return None
    for v in body.get("venues") or []:
        if v.get("venue") == VENUE:
            return {k: v.get(k) for k in ("trades", "volume", "traders", "pairs", "status")}
    return None


def report(out: dict, live: bool, stage: bool) -> list:
    """The printed lines. With stage=True nothing names a team: no parties, no makers."""
    trades, led = out["v20_other_team_trades"], out["ledger"]
    lines = [f"VERSION {out['version']}: {out['why']}"]
    for t in trades:
        who = "" if stage else f" ({' and '.join(t['parties'])})"
        lines.append(f"  tick {t['tick']}: {' / '.join(t['cards']) or 'no card'} for {t['price']} P{who}")
    if live:
        lines.append(f"  leaderboard {VENUE}: {out['leaderboard_v20'] or 'unavailable'}")
    lines += [f"1. {VENUE} trades between two other teams: {len(trades)}",
              f"2. other teams that posted on {VENUE}: {len(out['v20_other_makers'])}, {out['v20_other_offers']} offers",
              f"3. public events recorded (two recorder copies merged): {out['events']:,} (to tick {out['last_tick']})",
              "4. ledger vs our real cash: " + (f"{led['ok']} of {led['readings']} readings match (to tick {led['last_tick']})"
                                               if led else "unavailable"),
              f"5. pull requests merged: {out['merged_prs'] if out['merged_prs'] is not None else 'unavailable'}"]
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--feed", default=os.environ.get("BAZAAR_FEED", str(ROOT / "logs" / "feed")))
    ap.add_argument("--live", action="store_true", help="also read the keyless leaderboard")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stage", action="store_true", help="no team ids in the output (for a screen judges see)")
    ap.add_argument("--deadline", type=float, default=None, help="seconds for the slow figures (default 5 with --stage)")
    a = ap.parse_args()
    deadline = a.deadline if a.deadline is not None else (5.0 if a.stage else None)
    started = time.monotonic()
    feed = Path(a.feed).expanduser()
    events = load(feed / "feed.jsonl", GAP_SOURCES)
    trades = others_trades(events)
    makers = venue_makers(events)
    left = None if deadline is None else max(0.5, deadline - (time.monotonic() - started))
    calls = {"ledger": lambda t: ledger_check(feed, t), "prs": merged_prs}
    if a.live:
        calls["board"] = leaderboard_v20
    got = gather(calls, left)
    board, led = got.get("board"), got["ledger"]
    ver, why = version(trades, board)
    out = {"version": ver, "why": why, "v20_other_team_trades": trades,
           "v20_other_makers": dict(makers), "v20_other_offers": sum(makers.values()),
           "events": len(events), "last_tick": events[-1].get("tick") if events else None,
           "ledger": led and {"ok": led[0], "readings": led[1], "last_tick": led[2]},
           "merged_prs": got["prs"], "leaderboard_v20": board}
    if a.json:
        if a.stage:
            out["v20_other_makers"] = len(makers)
            out["v20_other_team_trades"] = [{k: v for k, v in t.items() if k != "parties"} for t in trades]
        print(json.dumps(out, indent=1))
        return
    print("\n".join(report(out, a.live, a.stage)))

if __name__ == "__main__":
    main()
