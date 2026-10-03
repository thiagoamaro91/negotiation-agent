"""Duel field read: what the rivals of a live duel session actually do, from agent/duel.py's event log. Read-only.

For each duel since --since: the rival's offers (price and day per tick), a shape label in the arena's terms
(silent, oneshot, jump-hold, every-tick, stepped, reactive), how it uses the day (fixed 0/5/10, echoes ours, moves),
whether its text reads like an LLM, and the result. Then the field mix and the first days_meaning lines, to check
the arena's assumptions (tools/duel_arena.py DUELS1_WEIGHTS / FIELD_WEIGHTS, DAYS_STRESS) after the first wave.

Usage:
    python3 tools/duel_field_read.py --log /Volumes/bazaar/logs/duel/2026-10-03.jsonl --since 20:30
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def load(log: Path, since: str) -> dict:
    duels: dict = {}
    for line in log.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if since and str(e.get("ts", ""))[11:16] < since:
            continue
        did = e.get("duel")
        if did is None:
            continue
        d = duels.setdefault(did, {"new": None, "rival": [], "ours": [], "accepts": [], "result": None})
        ev = e.get("event")
        if ev == "duel_new":
            d["new"] = e
        elif ev == "rival" and e.get("offer"):
            o = e["offer"]
            key = (o.get("tick"), o.get("price"), o.get("days"))
            if not d["rival"] or d["rival"][-1][:3] != key:
                d["rival"].append((*key, e.get("text") or ""))
        elif ev == "say":
            d["ours"].append((e.get("tick"), e.get("price"), e.get("days")))
        elif ev == "accept":
            d["accepts"].append(e.get("tick"))
        elif ev == "result":
            d["result"] = e
    return duels


def shape(d: dict) -> str:
    """The rival's price path in the arena's vocabulary."""
    offers = d["rival"]
    if not offers:
        return "silent"
    prices = [p for _, p, _, _ in offers if p is not None]
    if len(set(prices)) <= 1:
        return "oneshot" if len(offers) == 1 else "holds"
    moves = [(offers[i][0], abs(prices[i] - prices[i - 1])) for i in range(1, len(prices)) if prices[i] != prices[i - 1]]
    total = sum(m for _, m in moves) or 1
    our_ticks = {t for t, _, _ in d["ours"]}
    reactive = sum(1 for t, _ in moves if t is not None and (t - 1 in our_ticks or t in our_ticks))
    if d["ours"] and reactive == len(moves) and len(moves) >= 2:
        return "reactive"
    first_two = sum(m for _, m in moves[:2]) / total
    if len(moves) >= 2 and first_two >= 0.7 and len(moves) <= 3:
        return "jump-hold"
    if len(moves) >= 0.7 * (len(offers) - 1):
        return "every-tick"
    return "stepped"


def day_use(d: dict) -> str:
    days = [x for _, _, x, _ in d["rival"] if x is not None]
    if not days:
        return "-"
    ours = {x for _, _, x in d["ours"] if x is not None}
    if len(set(days)) == 1:
        v = days[0]
        return f"fixed {v}" + (" (=ours)" if v in ours else "")
    if ours and days[-1] in ours:
        return f"moved to ours ({days[0]}->{days[-1]})"
    return f"moves {days[0]}->{days[-1]}"


def llm_like(d: dict) -> bool:
    texts = {t for *_, t in d["rival"] if t}
    return len(texts) >= 2 or any(len(t) > 80 for t in texts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", required=True)
    ap.add_argument("--since", default="", help="HH:MM, local time of the log's ts field")
    a = ap.parse_args()
    duels = load(Path(a.log).expanduser(), a.since)
    rows, mix, days_mix, meanings = [], collections.Counter(), collections.Counter(), collections.Counter()
    for did in sorted(duels):
        d = duels[did]
        n = d["new"] or {}
        s, du, llm = shape(d), day_use(d), llm_like(d)
        mix[s] += 1
        days_mix[du.split(" (")[0] if du.startswith("fixed") else du.split(" ")[0]] += 1
        if n.get("days_meaning"):
            meanings[(n.get("role"), n.get("days_meaning"), n.get("days_weight"))] += 1
        r = d["result"] or {}
        path = " ".join(f"{p}/{x}" if x is not None else f"{p}" for _, p, x, _ in d["rival"][:8])
        rows.append(f"{did:>6} {n.get('role', '?'):6} lim {n.get('limit', '?'):>4} | {s:10} | days {du:22} | "
                    f"{'LLM' if llm else '   '} | {r.get('status', 'live'):8} {r.get('our_surplus', '')!s:>6} | {path}")
    print(f"{len(duels)} duels" + (f" since {a.since}" if a.since else ""))
    print("\n".join(rows))
    print("\nrival shapes:", dict(mix.most_common()))
    print("rival day use:", dict(days_mix.most_common()))
    for (role, m, w), k in meanings.most_common(6):
        print(f"days_meaning ({role}, weight {w}) x{k}: {m}")


if __name__ == "__main__":
    main()
