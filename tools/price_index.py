"""Prices measured in the public feed: what each dealer really closes at, and what teams pay each other. Offline, no key.

Dealers. Every dealer settlement is matched to its conversation (same team and dealer, the settled price appears in it),
and the dealer's FIRST price in that conversation is its opening. Per dealer x side x rarity (packs by pack id) we keep:
- opening: the most common opening in the last OPENING_WINDOW conversations (welcome deals open lower and are left out);
- low / median / high: the negotiated closes, i.e. deals whose own opening is within OPENING_TOLERANCE of that opening
  and that did not close at it (a deal at the opening price is a welcome or a team that took the ask);
- n, and where the numbers come from: "measured" (n >= MIN_CLOSES), "fallback" (Friday's measured ranges, below) or
  "list" (a dealer with no closes yet: its list price from /api/dealers).
Side "sells" = the dealer sells (we buy); "buys" = the dealer buys (we sell).

The ladder scores the share of a dealer's price range a deal captures (kit/RULES.md, Scoring). The real range of each
conversation is secret, so ladder_share() ESTIMATES it from the measured range: (opening - price) / (opening - low) for a
buy from the dealer, (price - opening) / (high - opening) for a sale to it, clipped to 0..1.

Teams. team_index(): median / min / max of what teams paid each other for a single card, per rarity, set and
set x rarity, over the whole feed and the last RECENT_HOURS game hours.

    python3 tools/price_index.py            # dealer closes and the team price index from the recorded feed
    python3 tools/price_index.py --json
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import value_inference as vi  # noqa: E402

MIN_CLOSES = 3            # fewer negotiated closes than this: use the fallback range
OPENING_WINDOW = 20       # the dealer's usual opening = the most common one in its last 20 conversations of a kind
OPENING_TOLERANCE = 0.2   # a conversation opened more than 20 % away from the usual opening is another regime (welcome)
RECENT_HOURS = 2.0        # the team price index's recent window, in game hours (the feed's `t`)

# Friday's negotiated closes (logs/feed-vm, ticks 0-159; analysis-friday sections 2-3), used until the feed has its own.
FALLBACK = {
    ("chato", "sells", "rare"): {"opening": 97, "low": 82, "median": 91, "high": 93},
    ("chato", "sells", "uncommon"): {"opening": 33, "low": 28, "median": 29, "high": 32},
    ("abuela", "sells", "common"): {"opening": 12, "low": 8, "median": 10, "high": 10},
    ("abuela", "sells", "uncommon"): {"opening": 29, "low": 21, "median": 23, "high": 25},
    ("abuela", "sells", "pack:sobre_barrio"): {"opening": 30, "low": 19, "median": 22, "high": 24},
    ("abuela", "buys", "common"): {"opening": 5, "low": 6, "median": 6, "high": 6},
    ("abuela", "buys", "uncommon"): {"opening": 12, "low": 13, "median": 14, "high": 15},
}


def key_of(dealer: str, side: str, kind: str) -> str:
    return f"{dealer}/{side}/{kind}"


def dealer_threads(events: list) -> dict:
    """thread id -> {team, dealer, tick, offers: [(tick, sender, price)]}: every dealer conversation in the feed."""
    out = {}
    for e in events:
        p = e["payload"]
        if p.get("kind") != "persona":
            continue
        if e["type"] == "thread.opened":
            out[p["thread"]] = {"team": p.get("team"), "dealer": p.get("with"), "tick": e["tick"], "offers": []}
        elif e["type"] == "thread.message":
            t = out.setdefault(p["thread"], {"team": p.get("team"), "dealer": p.get("with"), "tick": e["tick"], "offers": []})
            o = p.get("offer") or {}
            price = (o.get("want") or {}).get("cash") or (o.get("give") or {}).get("cash") or 0
            if price > 0:
                t["offers"].append((e["tick"], p.get("sender"), price))
    return out


def dealer_deals(events: list, kind_of) -> list:
    """Every dealer settlement with its conversation's opening: [{tick, dealer, side, kind, ref, team, price, opening}].
    kind_of(item) -> 'common' | 'uncommon' | 'rare' | 'pack:<id>' | None."""
    threads = dealer_threads(events)
    by_pair = collections.defaultdict(list)
    for tid, t in threads.items():
        by_pair[(t["team"], t["dealer"])].append((t["tick"], tid))
    out = []
    for e in events:
        p = e["payload"]
        if e["type"] != "settlement" or not p.get("persona") or not p.get("items"):
            continue
        dealer, item, price = p["persona"], p["items"][0], p.get("price") or 0
        side = "sells" if item.get("frm") == dealer else "buys"
        team = item.get("to") if side == "sells" else item.get("frm")
        kind = kind_of(item)
        if not kind or price <= 0:
            continue
        opening = None
        for _, tid in sorted(by_pair.get((team, dealer), []), reverse=True):  # the latest conversation that shows this price
            offers = [o for o in threads[tid]["offers"] if o[0] <= e["tick"]]
            if threads[tid]["tick"] <= e["tick"] and any(o[2] == price for o in offers):
                theirs = [o[2] for o in offers if o[1] == dealer]
                opening = theirs[0] if theirs else None
                break
        out.append({"tick": e["tick"], "dealer": dealer, "side": side, "kind": kind, "ref": item.get("ref"),
                    "team": team, "price": price, "opening": opening})
    return out


def openings(events: list, kind_of_topic) -> dict:
    """(dealer, side, kind) -> the dealer's first price in each conversation, oldest first (settled or not).
    kind_of_topic(topic) -> (side, kind) or None."""
    out = collections.defaultdict(list)
    threads = dealer_threads(events)
    topics = {e["payload"]["thread"]: e["payload"].get("topic") or {} for e in events
              if e["type"] == "thread.opened" and e["payload"].get("kind") == "persona"}
    for tid in sorted(threads):
        t = threads[tid]
        sk = kind_of_topic(topics.get(tid) or {})
        first = next((o[2] for o in t["offers"] if o[1] == t["dealer"]), None)
        if sk and first:
            out[(t["dealer"], *sk)].append(first)
    return out


def usual_opening(values: list) -> int | None:
    recent = values[-OPENING_WINDOW:]
    if not recent:
        return None
    c = collections.Counter(recent)
    return max(c, key=lambda v: (c[v], v))


def stats_from(deals: list, opening: int | None) -> dict | None:
    """low / median / high of the negotiated closes around a usual opening."""
    if opening is None:
        return None
    closes = sorted(d["price"] for d in deals
                    if d["opening"] is not None and abs(d["opening"] - opening) <= OPENING_TOLERANCE * opening
                    and d["price"] != d["opening"])
    if not closes:
        return {"opening": opening, "n": 0}
    return {"opening": opening, "low": closes[0], "median": statistics.median(closes), "high": closes[-1], "n": len(closes)}


def dealer_prices(events: list, kind_of, kind_of_topic, dealers: dict | None = None) -> dict:
    """'dealer/side/kind' -> {dealer, side, kind, opening, low, median, high, n, source}. See the module docstring."""
    deals = dealer_deals(events, kind_of)
    opens = openings(events, kind_of_topic)
    groups = collections.defaultdict(list)
    for d in deals:
        groups[(d["dealer"], d["side"], d["kind"])].append(d)
    out = {}
    for k in set(groups) | set(opens) | set(FALLBACK):
        usual = usual_opening(opens.get(k) or [d["opening"] for d in groups.get(k, []) if d["opening"]])
        st = stats_from(groups.get(k, []), usual) or {"n": 0}
        row = {"dealer": k[0], "side": k[1], "kind": k[2], "n": st.get("n", 0)}
        if st.get("n", 0) >= MIN_CLOSES:
            row.update({x: st[x] for x in ("opening", "low", "median", "high")}, source="measured")
        elif k in FALLBACK:
            row.update(FALLBACK[k], source="fallback")
        elif st.get("n", 0) > 0:
            row.update({x: st[x] for x in ("opening", "low", "median", "high")}, source="measured (few)")
        else:
            continue
        out[key_of(*k)] = row
    for d in (dealers or {}).get("personas", []):  # a dealer with no closes yet: its list price, flagged
        for item in (d.get("menu") or {}).get("sells", []):
            kind = item.get("rarity") or (f"pack:{item['pack']}" if item.get("pack") else None)
            k = key_of(d.get("id"), "sells", kind)
            if kind and item.get("list_price") and k not in out:
                lp = item["list_price"]
                out[k] = {"dealer": d.get("id"), "side": "sells", "kind": kind, "n": 0, "opening": item.get("opening_ask") or lp,
                          "low": lp, "median": lp, "high": lp, "source": "list"}
    return out


def ladder_share(row: dict, price: float) -> float:
    """ESTIMATED share of the dealer's price range a deal at `price` captures (see the module docstring)."""
    if row["side"] == "sells":
        span = row["opening"] - row["low"]
        x = (row["opening"] - price) / span if span > 0 else 0.0
    else:
        span = row["high"] - row["opening"]
        x = (price - row["opening"]) / span if span > 0 else 0.0
    return round(max(0.0, min(1.0, x)), 2)


def summarise(prices: list) -> dict:
    prices = sorted(prices)
    return {"n": len(prices), "median": statistics.median(prices), "low": prices[0], "high": prices[-1]} if prices else {"n": 0}


def team_trades(events: list, card_info: dict) -> list:
    """Single-card team-to-team settlements with a price: [{tick, t, ref, set, rarity, price, venue}]."""
    out = []
    for e in events:
        p = e["payload"]
        if e["type"] != "settlement" or p.get("persona"):
            continue
        items = p.get("items") or []
        if len(items) != 1 or items[0].get("kind") != "card" or not (p.get("price") or 0) > 0:
            continue
        ref = items[0].get("ref")
        if ref not in card_info:
            continue
        out.append({"tick": e["tick"], "t": e.get("t"), "ref": ref, "set": vi.set_of(ref), "rarity": card_info[ref],
                    "price": p["price"], "venue": p.get("venue")})
    return out


def team_index(events: list, card_info: dict, recent_hours: float = RECENT_HOURS) -> dict:
    """Median / min / max of team-to-team prices for one card, per rarity, set and set x rarity: all, and the last
    `recent_hours` game hours of the feed."""
    trades = team_trades(events, card_info)
    now = max((e.get("t") or 0 for e in events), default=0)

    def index(rows: list) -> dict:
        groups = {"rarity": collections.defaultdict(list), "set": collections.defaultdict(list),
                  "set_rarity": collections.defaultdict(list)}
        for r in rows:
            groups["rarity"][r["rarity"]].append(r["price"])
            groups["set"][r["set"]].append(r["price"])
            groups["set_rarity"][f"{r['set']} {r['rarity']}"].append(r["price"])
        return {g: {k: summarise(v) for k, v in sorted(d.items())} for g, d in groups.items()}

    recent = [r for r in trades if r["t"] is not None and r["t"] >= now - recent_hours]
    return {"now_hours": round(now, 2), "recent_hours": recent_hours, "trades": len(trades), "recent_trades": len(recent),
            "all": index(trades), "recent": index(recent)}


def card_kinds(cat: dict) -> tuple:
    """The rarity of every card, and the kind_of / kind_of_topic readers dealer_prices() needs."""
    rarity = {c["id"]: c["rarity"] for s in cat["sets"] for c in s["cards"]}
    packs = {p["id"] for p in cat.get("packs", [])} if isinstance(cat.get("packs"), list) else set()

    def kind_of(item: dict) -> str | None:
        if item.get("kind") == "pack" or item.get("ref") in packs:
            return f"pack:{item.get('ref')}"
        return rarity.get(item.get("ref"))

    def kind_of_topic(topic: dict):
        buy, sell = topic.get("buy") or {}, topic.get("sell") or {}
        if buy:
            if buy.get("pack"):
                return "sells", f"pack:{buy['pack']}"
            r = rarity.get(buy.get("card")) or buy.get("rarity")
            return ("sells", r) if r else None
        if sell:
            return None  # a sale names asset ids, not cards: the settlement tells the rarity
        return None

    return rarity, kind_of, kind_of_topic


def build(events: list, cat: dict, dealers: dict | None = None) -> dict:
    rarity, kind_of, kind_of_topic = card_kinds(cat)
    return {"dealers": dealer_prices(events, kind_of, kind_of_topic, dealers), "teams": team_index(events, rarity)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Dealer closes and team-to-team prices from the public feed.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    events = vi.rows("feed.jsonl")
    out = build(events, vi.catalog())
    if args.json:
        print(json.dumps(out, indent=1))
        return
    print(f"feed up to tick {events[-1]['tick']}: dealer closes (negotiated; a deal at the opening price is left out)")
    for k, r in sorted(out["dealers"].items()):
        print(f"  {k:28} opening {r['opening']:>4}  closes {r['low']:>4}-{r['high']:<4} median {r['median']:<5} "
              f"n={r['n']:<3} {r['source']}")
    t = out["teams"]
    print(f"\nteam-to-team, one card per trade: {t['trades']} trades, {t['recent_trades']} in the last {t['recent_hours']} game hours")
    for k, s in t["all"]["rarity"].items():
        rec = t["recent"]["rarity"].get(k, {"n": 0})
        print(f"  {k:10} median {s['median']:>5}  {s['low']}-{s['high']}  n={s['n']:<3} | recent "
              + (f"median {rec['median']} {rec['low']}-{rec['high']} n={rec['n']}" if rec["n"] else "none"))


if __name__ == "__main__":
    main()
