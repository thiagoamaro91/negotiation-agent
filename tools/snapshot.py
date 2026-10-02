"""Save everything the server knows about Team 3's play into logs/, whoever ran the agents and from whichever
machine: every conversation (dealers and teams) with full transcripts, every duel, our offers, our holdings, and
one score line per run. Safe to re-run at any time; then commit logs/.

    python3 tools/snapshot.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from bazaar_sdk import Bazaar  # noqa: E402
from runlog import LOGS, redact, write_json  # noqa: E402


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    load_env()
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"])
    me = b.me()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    threads = b.my_threads().get("threads", [])
    for t in threads:  # the listing carries messages; the single read adds standing offers and the item
        write_json(LOGS / "threads" / f"thread-{int(t['id']):05d}.json", b.thread(t["id"]))

    duels = b.duels(done=True).get("duels", []) + b.duels().get("duels", [])
    for d in duels:
        write_json(LOGS / "duels" / f"duel-{int(d.get('duel') or d.get('id')):05d}.json", d)

    write_json(LOGS / "state" / "offers.json", b.my_offers())
    write_json(LOGS / "state" / "me.json", me)

    s = me.get("score") or {}
    line = {"ts": ts, "tick": me.get("tick"), "cash": me.get("cash"), "level": me.get("level"),
            "unlocked": me.get("unlocked"), "collection_value": me.get("collection_value"),
            "album_filled": (me.get("album") or {}).get("filled"), "threads": len(threads), "duels": len(duels),
            "score": {k: s.get(k) for k in ("score", "negotiating", "market", "duel_points", "ladder_points",
                                            "neg_points", "mm_points", "bench_points", "deals", "rank")}}
    LOGS.mkdir(exist_ok=True)
    with (LOGS / "score.jsonl").open("a") as f:
        f.write(json.dumps(redact(line), ensure_ascii=False) + "\n")
    print(f"saved {len(threads)} threads, {len(duels)} duels, offers, holdings; score {line['score']['score']} "
          f"rank {line['score']['rank']} cash {line['cash']} tick {line['tick']}")


if __name__ == "__main__":
    main()
