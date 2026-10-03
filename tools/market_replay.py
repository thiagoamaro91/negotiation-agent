"""Replay the market desk over a recorded day: what would it have bought, sold and bid, and what would it have gained?

The boards are rebuilt tick by tick from the public feed: an offer is on its board from its `offer.listed` tick until
it is cancelled (`offer.cancelled`), expires (`expires_tick`) or settles (a `settlement` matched to it by asset and
price for a listing, by bidder, card and price for a bid). At each tick the desk's own decision function
(agent/market_desk.py `decide`) runs on that board, with the tape (prices, holders) built only from events before that
tick. Our holdings come from logs/state/me.json moved backwards and forwards by our public settlements (pack contents
are not public, so cards pulled from packs count as held all along). Cash is a parameter, not Friday's history.

What it simulates: the one accept per tick (taken by us, so the offer leaves the board), the caps, and our bids. A bid
"plausibly fills" when, while it was live, a team sold that card to another team at a price at or under what our bid
would have paid them after their fee, or listed it at an ask at or under that. That is evidence, not proof.

    python3 tools/market_replay.py --feed logs/feed-vm/feed.jsonl            # gain rule only, then Saturday caps
    python3 tools/market_replay.py --feed ... --cash 355 --min-cash 280 --top 15
Read-only: no network, no key.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import market_desk as md  # noqa: E402


def load(paths) -> list:
    rows, seen = [], set()
    for r in md.read_feed_files(paths):
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        rows.append(r)
    return sorted(rows, key=lambda e: (e.get("tick") or 0, e.get("id") or 0))


def rebuild(events: list) -> dict:
    """Every offer with the tick it left the board, and which settlement took it."""
    offers, gone, taken = {}, {}, {}
    for e in events:
        t, p = e.get("type"), e.get("payload") or {}
        if t == "offer.listed":
            o = p.get("offer") or {}
            if isinstance(o.get("id"), int):
                offers[o["id"]] = {"tick": e["tick"], "offer": {**o, "venue": o.get("venue") or p.get("venue")}}
        elif t == "offer.cancelled" and isinstance(p.get("offer"), int):
            gone.setdefault(p["offer"], e["tick"])
    for e in events:
        if e.get("type") != "settlement":
            continue
        p = e["payload"]
        if not p.get("venue") or not isinstance(p.get("price"), int):
            continue
        parties = p.get("parties") or []
        cards = [i for i in p.get("items") or [] if i.get("kind") == "card"]
        best = None
        for oid, rec in offers.items():
            o = rec["offer"]
            if rec["tick"] > e["tick"] or oid in taken or gone.get(oid, 10 ** 9) < e["tick"] - 1:
                continue
            if o.get("maker") != (parties[0] if parties else None):
                continue
            g, w = o.get("give") or {}, o.get("want") or {}
            ga = [a.get("id") for a in g.get("assets") or [] if isinstance(a, dict)]
            if ga and sorted(ga) == sorted(i["id"] for i in cards) and w.get("cash") == p["price"]:
                best = oid
            elif len(cards) == 1 and f"card:{cards[0]['ref']}" in (w.get("types") or []) and g.get("cash") == p["price"]:
                best = oid if best is None or oid > best else best
        if best is not None:
            taken[best] = {"tick": e["tick"], "by": parties[1] if len(parties) > 1 else None}
            gone[best] = min(gone.get(best, 10 ** 9), e["tick"])
    return {"offers": offers, "gone": gone, "taken": taken}


def board_at(rb: dict, t: int, removed: set) -> dict:
    out: dict = {}
    for oid, rec in rb["offers"].items():
        o = rec["offer"]
        if rec["tick"] > t or rb["gone"].get(oid, 10 ** 9) <= t or oid in removed:
            continue
        if isinstance(o.get("expires_tick"), int) and o["expires_tick"] <= t:
            continue
        out.setdefault(o.get("venue") or md.HOME, []).append(o)
    return out


def minted(events: list) -> tuple:
    """Asset ids are minted in order. (base, {tick: highest id seen by then}): ids up to `base` are the starting
    deal (minted before the first pack was sold); a higher id did not exist before some event showed an id >= it.
    This dates the cards we pulled from packs or got as gifts, which the feed does not name."""
    packs = [i["id"] for e in events if e.get("type") == "settlement"
             for i in (e.get("payload") or {}).get("items") or [] if i.get("kind") == "pack" and isinstance(i.get("id"), int)]
    base = (min(packs) - 1) if packs else 0
    mx, out = 0, {}
    for e in events:
        p = e.get("payload") or {}
        ids = []
        if e.get("type") == "offer.listed":
            ids = [a.get("id") for a in ((p.get("offer") or {}).get("give") or {}).get("assets") or [] if isinstance(a, dict)]
        elif e.get("type") == "settlement":
            ids = [i.get("id") for i in p.get("items") or []]
        mx = max([mx] + [i for i in ids if isinstance(i, int)])
        out[e.get("tick") or 0] = mx
    return base, out


def holdings_at(me: dict, ours: list, t: int, extra: dict, mint: tuple | None = None) -> dict:
    """Our assets at tick t: the snapshot moved through our public settlements, plus simulated trades."""
    t0, me_id = int(me.get("tick") or 0), me.get("id")
    assets = {a["id"]: dict(a) for a in me.get("assets") or []}
    if mint is not None:   # pack and gift cards that did not exist yet at tick t
        base, by_tick = mint
        seen = max([v for k, v in by_tick.items() if k <= t] or [0])
        received = {i.get("id") for s in ours for i in s.get("items") or [] if i.get("to") == me_id}
        for aid in [a for a in assets if a > max(base, seen) and a not in received]:
            assets.pop(aid)
    for s in ours:
        for i in s.get("items") or []:
            if i.get("kind") != "card":
                continue
            if t < s["tick"] <= t0:      # undo what happened after t
                if i.get("to") == me_id:
                    assets.pop(i["id"], None)
                elif i.get("frm") == me_id:
                    assets[i["id"]] = {k: i.get(k) for k in ("id", "kind", "ref", "serial", "rarity", "set")}
            elif t0 < s["tick"] <= t:    # replay what happened after the snapshot
                if i.get("frm") == me_id:
                    assets.pop(i["id"], None)
                elif i.get("to") == me_id:
                    assets[i["id"]] = {k: i.get(k) for k in ("id", "kind", "ref", "serial", "rarity", "set")}
    for aid in extra.get("sold", set()):
        assets.pop(aid, None)
    h = md.holdings_of(list(assets.values()))
    for n, ref in enumerate(extra.get("bought", [])):
        h.setdefault(ref, []).append({"id": -1 - n, "ref": ref, "serial": 10 ** 6})
    return h


def replay(events: list, me: dict, catalog: dict, cfg: md.Config, cash0: int, *, venues: dict | None = None,
           t_from: int | None = None, t_to: int | None = None) -> dict:
    me_id = me["id"]
    rb = rebuild(events)
    ticks = [e["tick"] for e in events if isinstance(e.get("tick"), int)]
    t_from = min(ticks) if t_from is None else t_from
    t_to = max(ticks) if t_to is None else t_to
    ours = [{"tick": e["tick"], **e["payload"]} for e in events
            if e.get("type") == "settlement" and me_id in (e["payload"].get("parties") or [])]
    released = {s["id"] for s in catalog["sets"] if s["id"] in {"LAV", "MAL", "LAT", "SAL"}}  # Friday's four sets
    venues = venues or {md.HOME: {"fee": md.DEFAULT_FEE, "owner": "world", "house": True}}
    tape = md.Tape()
    mint = minted(events)
    by_tick: dict = {}
    for e in events:
        by_tick.setdefault(e.get("tick") or 0, []).append(e)
    valuer = md.Valuer(catalog, me.get("affinity") or {}, {}, page_bonus=cfg.page_bonus)
    ledger, bidbook = md.Ledger(), {}
    extra = {"bought": [], "sold": set()}
    removed, trades, bids_posted, fills = set(), [], [], []
    cash = cash0
    order, idx = sorted(by_tick), 0
    for t in range(t_from, t_to + 1):
        batch = []   # the tape sees only what happened before this tick
        while idx < len(order) and order[idx] < t:
            batch += by_tick[order[idx]]
            idx += 1
        tape.ingest(batch)
        boards = board_at(rb, t, removed)
        mine = [o for offs in boards.values() for o in offs if o.get("maker") == me_id]
        h = holdings_at(me, ours, t, extra, mint)
        snap = {"tick": t, "t_hours": t / md.TICKS_PER_GAME_HOUR, "me_id": me_id, "cash": cash, "holdings": h,
                "venues": venues, "boards": boards, "mine": mine, "released": released, "tape_before": t}
        res = md.decide(snap, valuer, tape, ledger, cfg, bidbook)
        a = res["accept"]
        if a:
            contested = rb["taken"].get(a["offer"])
            trades.append({**a, "contested": contested})
            removed.add(a["offer"])
            if a["side"] == "buy":
                extra["bought"].append(a["card"])
                cash -= a["price"] + a["fee"]
                ledger.add(side="buy", t_hours=snap["t_hours"], tick=t, cost=a["price"] + a["fee"],
                           partner=a.get("partner"), card=a["card"])
            else:
                extra["sold"].add(a["asset"])
                cash += a["price"] - a["fee"]
                ledger.add(side="sell", t_hours=snap["t_hours"], tick=t, cash=a["price"] - a["fee"],
                           partner=a.get("partner"), card=a["card"])
        for b in res["bids"]:
            if b["action"] in ("post", "replace"):
                if b["action"] == "post":
                    bids_posted.append({"tick": t, "card": b["card"], "price": b["price"], "gain": b["record"]["gain"]})
                bidbook[b["card"]] = {"offer": f"sim-{b['card']}-{t}", "price": b["price"], "to": b["to"],
                                      "since": b["since"], "anchor": b["anchor"], "posted": t}
            elif b["action"] == "cancel":
                bidbook.pop(b["card"], None)
        # plausible fills of our live bids during this tick
        for ref, live in list(bidbook.items()):
            if live.get("offer") is None:
                continue
            if t - live.get("posted", t) >= cfg.bid_expires:
                bidbook[ref] = {**live, "offer": None}   # expired: the step clock carries over to the next post
                continue
            net_for_seller = live["price"] - md.fee_for(live["price"], md.DEFAULT_FEE)
            ev = None
            for e in by_tick.get(t, []):
                p = e.get("payload") or {}
                if e.get("type") == "settlement" and p.get("venue") and isinstance(p.get("price"), int):
                    cards = [i for i in p.get("items") or [] if i.get("kind") == "card"]
                    if len(cards) == 1 and cards[0].get("ref") == ref and cards[0].get("frm") != me_id \
                            and p["price"] <= net_for_seller:
                        ev = f"{cards[0]['frm']} sold {ref} at {p['price']} to {cards[0]['to']}"
                elif e.get("type") == "offer.listed":
                    o = p.get("offer") or {}
                    g, w = o.get("give") or {}, o.get("want") or {}
                    ga = [x for x in g.get("assets") or [] if isinstance(x, dict)]
                    if o.get("maker") != me_id and len(ga) == 1 and ga[0].get("ref") == ref \
                            and isinstance(w.get("cash"), int) and w["cash"] <= net_for_seller:
                        ev = f"{o.get('maker')} listed {ref} at {w['cash']}"
                if ev:
                    break
            if ev and valuer.info(ref) and not h.get(ref):
                v = valuer.first(ref)
                fills.append({"tick": t, "card": ref, "price": live["price"], "value": round(v, 2),
                              "gain": round(v - live["price"], 2), "evidence": ev})
                extra["bought"].append(ref)
                cash -= live["price"]
                ledger.add(side="buy", t_hours=t / md.TICKS_PER_GAME_HOUR, tick=t, cost=live["price"], card=ref,
                           partner=None)
                bidbook.pop(ref)
    return {"trades": trades, "bids_posted": bids_posted, "fills": fills, "cash_end": cash, "ticks": (t_from, t_to)}


def report(title: str, r: dict, top: int) -> None:
    buys = [x for x in r["trades"] if x["side"] == "buy"]
    sells = [x for x in r["trades"] if x["side"] == "sell"]
    print(f"\n== {title} (ticks {r['ticks'][0]}-{r['ticks'][1]}) ==")
    print(f"buys {len(buys)} (gain {sum(x['gain'] for x in buys):+.1f}), sells {len(sells)} "
          f"(gain {sum(x['gain'] for x in sells):+.1f}), bids posted {len(r['bids_posted'])}, plausible bid fills "
          f"{len(r['fills'])} (gain {sum(x['gain'] for x in r['fills']):+.1f}), cash at the end {r['cash_end']}")
    contested = sum(1 for x in r["trades"] if x.get("contested"))
    if contested:
        print(f"  {contested} of the trades were taken by another team on Friday (we would have raced them)")
    rows = sorted(r["trades"], key=lambda x: -x["gain"])[:top]
    for x in rows:
        c = x.get("contested")
        print(f"  tick {x['tick']:>3} {x['side'].upper():<4} {x['card']} @ {x['price']} fee {x['fee']} "
              f"value {x['value']:.1f} gain {x['gain']:+.1f} {x['side'] == 'buy' and 'from' or 'to'} "
              f"{x.get('partner')} on {x['venue']}" + (f"  [Friday: taken by {c['by']} at tick {c['tick']}]" if c else ""))
    for f in sorted(r["fills"], key=lambda x: -x["gain"])[:top]:
        print(f"  tick {f['tick']:>3} BID  {f['card']} @ {f['price']} value {f['value']:.1f} gain {f['gain']:+.1f} "
              f"(evidence: {f['evidence']})")
    seen = {}
    for b in r["bids_posted"]:
        seen.setdefault(b["card"], b)
    if seen:
        print("  first bids: " + ", ".join(f"{c} {b['price']}@t{b['tick']}" for c, b in sorted(seen.items())))


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay the market desk over a recorded feed")
    ap.add_argument("--feed", action="append", required=True, help="feed JSONL (repeatable; merged by event id)")
    ap.add_argument("--me", default=str(md.ME_SNAPSHOT))
    ap.add_argument("--catalog", default=None, help="catalog JSON (default: GET /api/catalog, keyless)")
    ap.add_argument("--cash", type=int, default=355, help="cash for the capped run (default 205 + the 150 grant)")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--from-tick", type=int, default=None)
    ap.add_argument("--to-tick", type=int, default=None)
    md.add_config_args(ap)
    args = ap.parse_args()
    events = load(args.feed)
    me = json.loads(Path(args.me).read_text())
    catalog = json.loads(Path(args.catalog).read_text()) if args.catalog else md.PublicClient().catalog()
    cfg = md.build_config(args)
    print(f"Replay over {len(events)} feed events; holdings from {args.me} (tick {me.get('tick')}) moved by our public "
          f"settlements; pack contents are not public. Board offers seen through the desk's structure checks only.")
    free = dataclasses.replace(cfg, min_cash=0, cap_hour=10 ** 6, cap_day=10 ** 6, partner_hour=10 ** 6)
    r1 = replay(events, me, catalog, free, 10 ** 6, t_from=args.from_tick, t_to=args.to_tick)
    report("gain rule only: no cash, spend or partner caps (price caps kept)", r1, args.top)
    r2 = replay(events, me, catalog, cfg, args.cash, t_from=args.from_tick, t_to=args.to_tick)
    report(f"with caps: cash {args.cash}, min cash {cfg.min_cash}, {cfg.cap_hour}/game hour, {cfg.cap_day}/day, "
           f"max {cfg.max_price} (LAV rares {cfg.max_price_rare}), {cfg.partner_hour}/partner/hour", r2, args.top)


if __name__ == "__main__":
    main()
