"""Read what tools/feed_recorder.py saved: what every team did, and what the board gave them for it. Offline, no key.

    python3 tools/feed_report.py board            # each leaderboard refresh: every team's score next to its deals so far
    python3 tools/feed_report.py board --last 2
    python3 tools/feed_report.py haggles          # every dealer conversation as a price sequence
    python3 tools/feed_report.py haggles --team t05 --since 40
    python3 tools/feed_report.py trades           # team-to-team settlements and El Rastro listings
    python3 tools/feed_report.py prices           # what each item sold for at the dealers, by tick

Price sequences read "T16 A26 T18 A25 A24!": T = the team's bid, A = the dealer's ask, ! = a final offer.
Only structure is printed (prices, items, who): the dealers' words stay in the files.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

FEED = Path(__file__).resolve().parent.parent / "logs" / "feed"


def rows(name: str) -> list:
    path = FEED / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def cash(offer: dict) -> int | None:
    return ((offer.get("give") or {}).get("cash") or (offer.get("want") or {}).get("cash")) if offer else None


def threads(events: list) -> dict:
    out = collections.OrderedDict()
    for e in events:
        p = e["payload"]
        if e["type"] == "thread.opened":
            out[p["thread"]] = {"team": p.get("team"), "with": p.get("with"), "kind": p.get("kind"),
                                "topic": p.get("topic"), "tick": e["tick"], "msgs": []}
        elif e["type"] == "thread.message":
            t = out.setdefault(p["thread"], {"team": p.get("team"), "with": p.get("with"), "kind": p.get("kind"),
                                             "topic": None, "tick": e["tick"], "msgs": []})
            offer = p.get("offer") or {}
            who = "T" if p.get("sender") == t["team"] else "A"
            t["msgs"].append((e["tick"], who, cash(offer), bool(offer.get("final"))))
    return out


def deals(events: list) -> dict:
    """team -> [(tick, 'b'|'s'|'x', ref, price, venue, counterparty)] ; x = a trade with another team."""
    out = collections.defaultdict(list)
    for e in events:
        if e["type"] != "settlement":
            continue
        p = e["payload"]
        item = (p.get("items") or [{}])[0]
        dealer = p.get("persona")
        for team in p.get("parties", []):
            if team == dealer:
                continue
            other = next((x for x in p["parties"] if x != team), None)
            side = "x" if not dealer else ("b" if item.get("to") == team else "s")
            out[team].append((p["tick"], side, item.get("ref"), p.get("price"), p.get("venue"), other))
    return out


def cmd_board(args, events) -> None:
    by_team = deals(events)
    boards = [r for r in rows("snapshots.jsonl") if r.get("what") == "leaderboard"]
    for r in boards[-args.last:] if args.last else boards:
        lb = r["body"]
        st = lb.get("snapshot_tick")
        print(f"\n=== board at tick {st} (round phase {lb['rounds'][-1].get('phase')})")
        for t in sorted(lb["teams"], key=lambda t: -t["score"]):
            done = [d for d in by_team[t["team"]] if d[0] <= st]
            txt = " ".join(f"{side}:{ref}@{price}" + (f"<{other}>" if side == "x" else "") for _, side, ref, price, _, other in done)
            print(f"  {t['team']} score {t['score']:6.2f} neg {t['negotiating']:6.2f} mkt {t['market']:5.2f} "
                  f"L{t['level']} deals {t['deals']:2} | {txt}")


def cmd_haggles(args, events) -> None:
    for tid, t in threads(events).items():
        if args.team and t["team"] != args.team:
            continue
        if t["tick"] < args.since:
            continue
        seq = " ".join(f"{who}{'' if price is None else price}{'!' if final else ''}" for _, who, price, final in t["msgs"])
        topic = json.dumps(t["topic"], separators=(",", ":"))[:44]
        print(f"th{tid:>4} tick {t['tick']:>3} {t['team']} > {t['with'] or '?':7} {topic:44} | {seq}")


def cmd_trades(args, events) -> None:
    print("Team-to-team settlements:")
    for e in events:
        p = e["payload"]
        if e["type"] == "settlement" and not p.get("persona"):
            items = ", ".join(f"{i.get('ref')} {i.get('frm')}>{i.get('to')}" for i in p.get("items", []))
            print(f"  tick {p['tick']:>3} {'/'.join(p['parties'])} price {p.get('price')} fee {p.get('fee')} "
                  f"venue {p.get('venue')} | {items}")
    print("Listings posted on venues (latest 40):")
    listed = [e for e in events if e["type"] == "offer.listed"]
    for e in listed[-40:]:
        o = e["payload"]["offer"]
        give, want = o.get("give") or {}, o.get("want") or {}
        gives = [a.get("ref") for a in give.get("assets") or []] or give.get("cash")
        wants = want.get("cash") or want.get("types") or [a.get("ref") for a in want.get("assets") or []]
        print(f"  tick {e['tick']:>3} {o.get('maker')} on {o.get('venue')} gives {gives} wants {wants}"
              + (f" to {o['to']}" if o.get("to") else ""))


def cmd_prices(args, events) -> None:
    by_item = collections.defaultdict(list)
    for team, ds in deals(events).items():
        for tick, side, ref, price, _, _ in ds:
            if side != "x":
                by_item[(side, ref)].append((tick, price, team))
    for (side, ref), ds in sorted(by_item.items()):
        print(f"  {'bought' if side == 'b' else 'sold  '} {ref:13} " + " ".join(f"{p}@t{tick}({team})" for tick, p, team in sorted(ds)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Report on the recorded public feed.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("board")
    b.add_argument("--last", type=int, default=0, help="only the last N refreshes")
    h = sub.add_parser("haggles")
    h.add_argument("--team")
    h.add_argument("--since", type=int, default=0, help="only conversations opened at or after this tick")
    sub.add_parser("trades")
    sub.add_parser("prices")
    args = ap.parse_args()
    events = rows("feed.jsonl")
    if not events:
        raise SystemExit("logs/feed/feed.jsonl is empty: run tools/feed_recorder.py first.")
    {"board": cmd_board, "haggles": cmd_haggles, "trades": cmd_trades, "prices": cmd_prices}[args.cmd](args, events)


if __name__ == "__main__":
    main()
