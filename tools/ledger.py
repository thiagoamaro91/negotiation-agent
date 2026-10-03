"""Every team's cash and known cards, rebuilt from the public feed alone. Offline, no key.

Everyone starts with 400 P (kit/RULES.md). From there the public feed shows every move of cash:
- dealer settlements (packs and cards bought from or sold to a dealer, at the settled price);
- team-to-team settlements (the buyer pays the price; the El Rastro fee is paid by whoever accepted, i.e. the team
  that did not post the matching listing; when that cannot be told, by the buyer);
- venue openings (a 250 P bond + 20 P), cash gifts and the organisers' grants.
Checked against our own account: Team 3's rebuilt cash equals /api/me exactly at ticks 72 and 93.

Cards are only partly visible: a team's starting hand (11 commons, 3 uncommons, 1 rare) and its pack pulls stay
hidden until it lists, sells or trades them, so "known cards" is a lower bound.

    python3 tools/ledger.py                 # every team: cash now, spent at dealers, traded with teams, bonds
    python3 tools/ledger.py --team t10      # one team, move by move
    python3 tools/ledger.py --json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import value_inference as vi  # noqa: E402

START_CASH = 400
VENUE_FEE = 20


def listings(events: list) -> dict:
    """Who posted what, to tell the acceptor of a settlement: ('ask', asset id) and ('bid', card ref) -> [(maker, price, tick)]."""
    out = collections.defaultdict(list)
    for e in events:
        o = e["payload"].get("offer")
        if e["type"] != "offer.listed" or not isinstance(o, dict):
            continue
        for a in (o.get("give") or {}).get("assets") or []:
            if isinstance(a, dict):
                out[("ask", a["id"])].append((o.get("maker"), (o.get("want") or {}).get("cash"), e["tick"]))
        for ref in vi.card_types(o.get("want") or {}):
            out[("bid", ref)].append((o.get("maker"), (o.get("give") or {}).get("cash"), e["tick"]))
    return out


def grant_cash(schedule: dict | None, payload: dict) -> int:
    """Cash per team of a fired grant: from the event itself, or from the schedule entry with the same note."""
    if payload.get("cash"):
        return int(payload["cash"])
    for u in (schedule or {}).get("upcoming", []):
        if u.get("action") == "grant_all" and u.get("note") == payload.get("note"):
            return int((u.get("params") or {}).get("cash") or 0)
    return 0


def build(events: list, schedule: dict | None = None, upto: int | None = None) -> dict:
    teams = sorted({e["payload"]["team"] for e in events if e["type"] == "team.joined"})
    led = {t: {"cash": START_CASH, "dealer_spent": 0, "dealer_earned": 0, "team_bought": 0, "team_sold": 0,
               "fees": 0, "bonds": 0, "gifts": 0, "grants": 0, "trades": 0, "unlocked": [], "venue": None,
               "cards_in": collections.Counter(), "cards_out": collections.Counter(), "moves": [], "history": []}
           for t in teams}
    posted = listings(events)
    gifted_at = set()

    def record(tick: int) -> None:
        for team in led:
            h = led[team]["history"]
            if not h or h[-1][1] != led[team]["cash"]:
                h.append((tick, led[team]["cash"]))

    def move(team: str, tick: int, delta: int, what: str) -> None:
        if team not in led:
            return
        led[team]["cash"] += delta
        led[team]["moves"].append({"tick": tick, "delta": delta, "what": what})

    for e in events:
        if upto is not None and e["tick"] > upto:
            break
        p, t = e["payload"], e["tick"]
        kind = e["type"]
        if kind == "settlement":
            items = p.get("items") or []
            price = p.get("price") or 0
            dealer = p.get("persona")
            if dealer:
                for i in items:
                    if i.get("to") in led:
                        move(i["to"], t, -price, f"bought {i.get('ref')} from {dealer}")
                        led[i["to"]]["dealer_spent"] += price
                        led[i["to"]]["cards_in"][i.get("ref")] += 1
                    elif i.get("frm") in led:
                        move(i["frm"], t, price, f"sold {i.get('ref')} to {dealer}")
                        led[i["frm"]]["dealer_earned"] += price
                        led[i["frm"]]["cards_out"][i.get("ref")] += 1
                    break  # one price per settlement
                record(t)
                continue
            ins = collections.defaultdict(list)
            for i in items:
                ins[i.get("to")].append(i)
            receivers = [x for x in ins if x in led]
            if len(receivers) != 1:  # a swap both ways: cards move, cash direction unknown
                for i in items:
                    if i.get("to") in led:
                        led[i["to"]]["cards_in"][i.get("ref")] += 1
                    if i.get("frm") in led:
                        led[i["frm"]]["cards_out"][i.get("ref")] += 1
                record(t)
                continue
            buyer = receivers[0]
            seller = next((i.get("frm") for i in items if i.get("frm") != buyer), None)
            first = items[0]
            ask_makers = [m for m, pr, tk in posted.get(("ask", first.get("id")), []) if tk <= t]
            bid_makers = [m for m, pr, tk in posted.get(("bid", first.get("ref")), []) if tk <= t and m == buyer]
            if ask_makers and ask_makers[-1] == seller:
                acceptor = buyer
            elif bid_makers:
                acceptor = seller
            else:
                acceptor = buyer
            refs = ", ".join(i.get("ref") or "?" for i in items)
            move(buyer, t, -price, f"bought {refs} from {seller}")
            move(seller, t, price, f"sold {refs} to {buyer}")
            fee = p.get("fee") or 0
            if fee:
                move(acceptor, t, -fee, f"fee on {refs} (accepted)")
            for team, side in ((buyer, "team_bought"), (seller, "team_sold")):
                if team in led:
                    led[team][side] += price
                    led[team]["trades"] += 1
            if acceptor in led:
                led[acceptor]["fees"] += fee
            for i in items:
                if buyer in led:
                    led[buyer]["cards_in"][i.get("ref")] += 1
                if seller in led:
                    led[seller]["cards_out"][i.get("ref")] += 1
        elif kind == "venue.opened" and p.get("owner") in led:
            cost = int(p.get("bond") or 250) + VENUE_FEE
            move(p["owner"], t, -cost, f"opened venue {p.get('name')}")
            led[p["owner"]]["bonds"] += cost
            led[p["owner"]]["venue"] = p.get("venue")
        elif kind == "gift.given" and p.get("team") in led:
            for ref in p.get("cards") or []:
                led[p["team"]]["cards_in"][ref] += 1
            if p.get("cash"):
                move(p["team"], t, int(p["cash"]), f"gift: {p.get('reason', '')}")
                led[p["team"]]["gifts"] += int(p["cash"])
                gifted_at.add((p["team"], t))
        elif kind == "schedule.fired" and p.get("action") == "grant_all":
            cash = grant_cash(schedule, p)
            for team in led:
                if cash and not any((team, tk) in gifted_at for tk in range(t - 2, t + 3)):
                    move(team, t, cash, f"grant: {p.get('note', '')}")
                    led[team]["grants"] += cash
        elif kind == "level.unlocked" and p.get("team") in led:
            led[p["team"]]["unlocked"].append(p.get("persona"))
        if kind in ("settlement", "venue.opened", "gift.given", "schedule.fired"):
            record(t)
    for team in led:
        led[team]["known_cards"] = {r: n for r, n in (led[team]["cards_in"] - led[team]["cards_out"]).items() if n > 0}
    return led


def check_us(led: dict) -> dict | None:
    """Our rebuilt cash against our real cash (the freshest account copy), at that copy's tick."""
    if not (vi.ME.exists() or vi.ME_LIVE.exists()):
        return None
    me = vi.load_me()
    tick = me.get("tick")
    hist = led.get(vi.US, {}).get("history", [])
    rebuilt = next((c for tk, c in reversed(hist) if tk <= tick), START_CASH)
    return {"tick": tick, "real": me["cash"], "rebuilt": rebuilt, "ok": rebuilt == me["cash"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Every team's cash and known cards from the public feed.")
    ap.add_argument("--team")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    events = vi.rows("feed.jsonl")
    led = build(events, vi.public("schedule"))
    chk = check_us(led)
    if args.json:
        out = {t: {k: v for k, v in r.items() if k not in ("cards_in", "cards_out")} for t, r in led.items()}
        print(json.dumps({"tick": events[-1]["tick"], "check": chk, "teams": out}, indent=1, default=str))
        return
    if args.team:
        r = led[args.team]
        for m in r["moves"]:
            print(f"  tick {m['tick']:>4} {m['delta']:+5} P  {m['what']}")
        print(f"\n{args.team}: cash {r['cash']} P; known cards {r['known_cards']}")
        return
    print(f"feed up to tick {events[-1]['tick']}; every team started with {START_CASH} P")
    if chk:
        print(f"check: Team 3 rebuilt {chk['rebuilt']} P vs real {chk['real']} P at tick {chk['tick']} -> {'OK' if chk['ok'] else 'MISMATCH'}")
    print(f"{'team':5} {'cash':>5} {'dealers':>8} {'teams+':>7} {'teams-':>7} {'fees':>5} {'bond':>5} {'trades':>6}  unlocked / venue")
    for t, r in sorted(led.items(), key=lambda x: -x[1]["cash"]):
        print(f"{t:5} {r['cash']:5} {r['dealer_earned'] - r['dealer_spent']:+8} {r['team_sold']:7} {r['team_bought']:7} "
              f"{r['fees']:5} {r['bonds']:5} {r['trades']:6}  {','.join(r['unlocked']) or '-'} {r['venue'] or ''}")


if __name__ == "__main__":
    main()
