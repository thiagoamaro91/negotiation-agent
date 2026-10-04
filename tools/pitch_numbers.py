"""The pitch's numbers at 14:50: which version to read (A or B) and the five figures to refresh. Read-only, no key.

Version A ("the network worked") needs at least one settlement on our venue v20 between two OTHER teams: both parties
are teams (tNN) and neither is us. Anything else (no trade, a trade we were part of, a Market Test bench pair) is
version B. The feed is the source; `--live` also reads the keyless leaderboard, whose v20 row counts trades too.

    python3 tools/pitch_numbers.py                  # from logs/feed/ (BAZAAR_FEED=<dir> or --feed DIR for another clone)
    python3 tools/pitch_numbers.py --live           # plus GET /api/leaderboard (keyless) for v20's trades and pairs
    python3 tools/pitch_numbers.py --json

The five numbers: (1) v20 trades between two other teams, the A/B fact; (2) other teams that posted on v20, and how
many offers; (3) public events recorded; (4) ledger readings that match our real cash; (5) pull requests merged.
(4) runs tools/ledger.py --json and (5) runs `gh`; each prints "unknown" if it cannot run.
Output stays internal: it names team ids, which the script on stage never does.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENUE, US = "v20", "t03"
REPO = "thiagoamaro91/negotiation-agent"
URL = "https://bazaar.causaprima.ai"
TEAM = re.compile(r"^t\d\d$")


def load(path: Path) -> list:
    """Every event once (the recorder can write one twice), in id order."""
    seen = {}
    for line in path.read_text().splitlines():
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
        if len(parties) == 2 and all(TEAM.match(str(t)) and t != us for t in parties):
            out.append({"tick": e.get("tick"), "parties": parties, "price": p.get("price"),
                        "cards": [i.get("ref") for i in p.get("items") or [] if i.get("kind") == "card"]})
    return out


def version(trades: list) -> str:
    return "A" if trades else "B"


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


def ledger_check(feed_dir: Path) -> tuple | None:
    """(matching readings, readings, last tick) from tools/ledger.py's check against our real cash."""
    env = dict(os.environ, BAZAAR_FEED=str(feed_dir))
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "ledger.py"), "--json"], capture_output=True,
                           text=True, timeout=600, env=env, cwd=ROOT)
        hist = json.loads(r.stdout)["check_history"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None
    return sum(1 for h in hist if h.get("ok")), len(hist), hist[-1]["tick"] if hist else None


def merged_prs() -> int | None:
    try:
        r = subprocess.run(["gh", "pr", "list", "--repo", REPO, "--state", "merged", "--limit", "500", "--json",
                            "number"], capture_output=True, text=True, timeout=60)
        return len(json.loads(r.stdout))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def leaderboard_v20() -> dict | None:
    try:
        with urllib.request.urlopen(URL + "/api/leaderboard", timeout=10) as r:
            body = json.load(r)
    except (OSError, ValueError):
        return None
    for v in body.get("venues") or []:
        if v.get("venue") == VENUE:
            return {k: v.get(k) for k in ("trades", "volume", "traders", "pairs", "status")}
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--feed", default=os.environ.get("BAZAAR_FEED", str(ROOT / "logs" / "feed")))
    ap.add_argument("--live", action="store_true", help="also read the keyless leaderboard")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    feed = Path(a.feed).expanduser()
    events = load(feed / "feed.jsonl")
    trades = others_trades(events)
    makers = venue_makers(events)
    led = ledger_check(feed)
    out = {"version": version(trades), "v20_other_team_trades": trades,
           "v20_other_makers": dict(makers), "v20_other_offers": sum(makers.values()),
           "events": len(events), "last_tick": events[-1].get("tick") if events else None,
           "ledger": led and {"ok": led[0], "readings": led[1], "last_tick": led[2]},
           "merged_prs": merged_prs(), "leaderboard_v20": leaderboard_v20() if a.live else None}
    if a.json:
        print(json.dumps(out, indent=1))
        return
    print(f"VERSION {out['version']}  ({len(trades)} settlement(s) on {VENUE} between two other teams)")
    for t in trades:
        print(f"  tick {t['tick']}: {' / '.join(t['cards']) or 'no card'} for {t['price']} P ({' and '.join(t['parties'])})")
    if a.live:
        print(f"  leaderboard {VENUE}: {out['leaderboard_v20'] or 'unknown'}")
    print(f"1. {VENUE} trades between two other teams: {len(trades)}")
    print(f"2. other teams that posted on {VENUE}: {len(makers)}, {out['v20_other_offers']} offers")
    print(f"3. public events recorded: {len(events):,} (to tick {out['last_tick']})")
    print("4. ledger vs our real cash: " + (f"{led[0]} of {led[1]} readings match (to tick {led[2]})" if led
                                           else "unknown (tools/ledger.py --json failed)"))
    print(f"5. pull requests merged: {out['merged_prs'] if out['merged_prs'] is not None else 'unknown (gh failed)'}")


if __name__ == "__main__":
    main()
