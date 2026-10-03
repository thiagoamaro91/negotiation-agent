"""Every team's cash and known cards, rebuilt from the public feed alone. Offline, no key.

Everyone starts with 400 P (kit/RULES.md). From there the public feed shows every move of cash:
- dealer settlements (packs and cards bought from or sold to a dealer, at the settled price);
- team-to-team settlements (the buyer pays the price; the fee is paid by whoever accepted, i.e. the team that did not
  post the matching listing; when that cannot be told, by the buyer). El Rastro keeps its fee; a fee charged on a
  team's own venue goes to that venue's owner;
- venue openings (a 250 P bond + 20 P; the free starter stalls of Saturday tick 201 cost nothing, "bond": 0 and
  "starter": true), bond refunds on venue.closed ("refund"), cash gifts and the organisers' grants. A grant's cash
  comes from the event, else from the schedule entry with the same note, else from the note itself ("150 primas":
  the Saturday allowance fired at tick 165 with no cash field and had left the schedule by then).

Holes in the recording: our recorder lost ticks 49-118 on Friday to DNS errors (logs/feed-vm/README.md).
Wherever two consecutive events are more than a tick apart, build() fills the hole from the complete copies in
GAP_SOURCES (logs/feed-vm/feed.jsonl), matched by event id.

Checked against our own account: Team 3's rebuilt cash equals the real one at every row of logs/score.jsonl from
tick 33 to tick 630 (Friday and Saturday). `--json` carries that comparison as "check_history".

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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import value_inference as vi  # noqa: E402

START_CASH = 400
VENUE_BOND = 250
VENUE_FEE = 20
HOUSE_VENUES = (None, "rastro")
GAP_SOURCES = (vi.ROOT / "logs" / "feed-vm" / "feed.jsonl",)  # complete copies of stretches our recorder missed
GAP_TICKS = 1  # two consecutive events further apart than this: a hole in the recording, filled from GAP_SOURCES
PRIMAS = re.compile(r"(\d+)\s*primas", re.IGNORECASE)
_source_cache: dict = {}


def _source_rows(path: Path) -> list:
    """A gap source's events, parsed once per file version (brain.py rebuilds the ledger every cycle)."""
    try:
        st = path.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    hit = _source_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _source_cache[str(path)] = (key, rows)
    return rows


def gaps(events: list) -> list:
    """Holes in a recording: (id before, tick before, id after, tick after) for consecutive events > GAP_TICKS apart."""
    out = []
    for a, b in zip(events, events[1:]):
        if "id" in a and "id" in b and b["tick"] - a["tick"] > GAP_TICKS:
            out.append((a["id"], a["tick"], b["id"], b["tick"]))
    return out


def fill_gaps(events: list, sources: tuple = GAP_SOURCES) -> list:
    """The events plus every event of `sources` that falls inside one of their holes (by id), in (tick, id) order.
    Without a hole, or without a source covering it, the events come back unchanged."""
    holes = gaps(events)
    if not holes:
        return events
    have = {e.get("id") for e in events}
    extra = []
    for path in sources:
        for e in _source_rows(Path(path)):
            if e.get("id") not in have and any(lo < e["id"] < hi for lo, _, hi, _ in holes):
                extra.append(e)
                have.add(e["id"])
    if not extra:
        return events
    return sorted(events + extra, key=lambda e: (e["tick"], e["id"]))


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
    """Cash per team of a fired grant: from the event itself, from the schedule entry with the same note, or from the
    note's own "<n> primas" (a fired entry leaves the schedule, so the live schedule no longer has it)."""
    if payload.get("cash"):
        return int(payload["cash"])
    for u in (schedule or {}).get("upcoming", []):
        if u.get("action") == "grant_all" and u.get("note") == payload.get("note"):
            cash = (u.get("params") or {}).get("cash")
            if cash:
                return int(cash)
    m = PRIMAS.search(payload.get("note") or "")
    return int(m.group(1)) if m else 0


def venue_cost(payload: dict) -> int:
    """What opening a venue took from its owner: the bond (250 P unless the event says otherwise) + 20 P; a starter
    stall is free."""
    if payload.get("starter"):
        return 0
    bond = payload.get("bond")
    return (VENUE_BOND if bond is None else int(bond)) + VENUE_FEE


def build(events: list, schedule: dict | None = None, upto: int | None = None, fill: bool = True) -> dict:
    if fill:
        events = fill_gaps(events)
    teams = sorted({e["payload"]["team"] for e in events if e["type"] == "team.joined"})
    led = {t: {"cash": START_CASH, "dealer_spent": 0, "dealer_earned": 0, "team_bought": 0, "team_sold": 0,
               "fees": 0, "fees_earned": 0, "bonds": 0, "refunds": 0, "gifts": 0, "grants": 0, "trades": 0,
               "unlocked": [], "venue": None,
               "cards_in": collections.Counter(), "cards_out": collections.Counter(), "moves": [], "history": []}
           for t in teams}
    posted = listings(events)
    owners: dict = {}  # venue id -> owning team
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
                for i in items[:1]:  # one price per settlement, its direction from the first item
                    if i.get("to") in led:
                        move(i["to"], t, -price, f"bought {i.get('ref')} from {dealer}")
                        led[i["to"]]["dealer_spent"] += price
                    elif i.get("frm") in led:
                        move(i["frm"], t, price, f"sold {i.get('ref')} to {dealer}")
                        led[i["frm"]]["dealer_earned"] += price
                for i in items:  # every card of a lot moves
                    if i.get("to") in led:
                        led[i["to"]]["cards_in"][i.get("ref")] += 1
                    if i.get("frm") in led:
                        led[i["frm"]]["cards_out"][i.get("ref")] += 1
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
                owner = owners.get(p.get("venue")) if p.get("venue") not in HOUSE_VENUES else None
                if owner in led:
                    move(owner, t, fee, f"fee earned on {refs} at {p.get('venue')}")
                    led[owner]["fees_earned"] += fee
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
            owner = p["owner"]
            owners[p.get("venue")] = owner
            cost = venue_cost(p)
            if cost:
                move(owner, t, -cost, f"opened venue {p.get('name')}")
            led[owner]["bonds"] += cost
            led[owner]["venue"] = p.get("venue")
        elif kind == "venue.closed":
            owner = owners.get(p.get("venue"))
            refund = int(p.get("refund") or 0)
            if owner in led:
                if refund:
                    move(owner, t, refund, f"bond back on venue {p.get('venue')}")
                    led[owner]["refunds"] += refund
                if led[owner]["venue"] == p.get("venue"):
                    led[owner]["venue"] = None
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
        if kind in ("settlement", "venue.opened", "venue.closed", "gift.given", "schedule.fired"):
            record(t)
    for team in led:
        led[team]["known_cards"] = {r: n for r, n in (led[team]["cards_in"] - led[team]["cards_out"]).items() if n > 0}
    return led


def cash_at(hist: list, tick: int) -> int:
    """A team's rebuilt cash at the end of a tick, from its history."""
    return next((c for tk, c in reversed(hist) if tk <= tick), START_CASH)


def check_us(led: dict) -> dict | None:
    """Our rebuilt cash against our real cash (the freshest account copy), at that copy's tick."""
    if not (vi.ME.exists() or vi.ME_LIVE.exists()):
        return None
    me = vi.load_me()
    tick = me.get("tick")
    rebuilt = cash_at(led.get(vi.US, {}).get("history", []), tick)
    return {"tick": tick, "real": me["cash"], "rebuilt": rebuilt, "ok": rebuilt == me["cash"]}


def score_rows() -> list:
    """Our real cash over time (tools/snapshot.py): the feed directory's copy, else the committed logs/score.jsonl."""
    rows = vi.rows("score.jsonl")
    if rows:
        return rows
    path = vi.ROOT / "logs" / "score.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_history(led: dict, rows: list, upto: int | None = None) -> list:
    """Our rebuilt cash against every real snapshot (tick, cash) up to the feed's last tick."""
    hist = led.get(vi.US, {}).get("history", [])
    out = []
    for r in rows:
        tick, real = r.get("tick"), r.get("cash")
        if tick is None or real is None or (upto is not None and tick > upto):
            continue
        rebuilt = cash_at(hist, tick)
        out.append({"tick": tick, "real": real, "rebuilt": rebuilt, "ok": rebuilt == real})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Every team's cash and known cards from the public feed.")
    ap.add_argument("--team")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    raw = vi.rows("feed.jsonl")
    events = fill_gaps(raw)
    holes = {"found": gaps(raw), "left": gaps(events)}
    led = build(events, vi.public("schedule"), fill=False)
    chk = check_us(led)
    hist = check_history(led, score_rows(), events[-1]["tick"])
    if args.json:
        out = {t: {k: v for k, v in r.items() if k not in ("cards_in", "cards_out")} for t, r in led.items()}
        print(json.dumps({"tick": events[-1]["tick"], "check": chk, "check_history": hist, "gaps": holes,
                          "teams": out}, indent=1, default=str))
        return
    if args.team:
        r = led[args.team]
        for m in r["moves"]:
            print(f"  tick {m['tick']:>4} {m['delta']:+5} P  {m['what']}")
        print(f"\n{args.team}: cash {r['cash']} P; known cards {r['known_cards']}")
        return
    print(f"feed up to tick {events[-1]['tick']}; every team started with {START_CASH} P")
    for lo_id, lo, hi_id, hi in holes["found"]:
        state = "still open" if (lo_id, lo, hi_id, hi) in holes["left"] else "filled from " + ", ".join(
            str(Path(s).relative_to(vi.ROOT)) for s in GAP_SOURCES)
        print(f"recording hole between ticks {lo} and {hi}: {state}")
    if chk:
        print(f"check: Team 3 rebuilt {chk['rebuilt']} P vs real {chk['real']} P at tick {chk['tick']} -> {'OK' if chk['ok'] else 'MISMATCH'}")
    bad = [h for h in hist if not h["ok"]]
    if hist:
        print(f"history: {len(hist) - len(bad)}/{len(hist)} snapshots match"
              + "".join(f"; tick {h['tick']} real {h['real']} rebuilt {h['rebuilt']}" for h in bad))
    print(f"{'team':5} {'cash':>5} {'dealers':>8} {'teams+':>7} {'teams-':>7} {'fees':>5} {'bond':>5} {'trades':>6}  unlocked / venue")
    for t, r in sorted(led.items(), key=lambda x: -x[1]["cash"]):
        print(f"{t:5} {r['cash']:5} {r['dealer_earned'] - r['dealer_spent']:+8} {r['team_sold']:7} {r['team_bought']:7} "
              f"{r['fees']:5} {r['bonds']:5} {r['trades']:6}  {','.join(r['unlocked']) or '-'} {r['venue'] or ''}")


if __name__ == "__main__":
    main()
