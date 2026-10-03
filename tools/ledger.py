"""Every team's cash and known cards, rebuilt from the public feed alone. Offline, no key.

Everyone starts with 400 P (kit/RULES.md). From there the public feed shows every move of cash:
- dealer settlements (packs and cards bought from or sold to a dealer, at the settled price);
- team-to-team settlements (the buyer pays the price; the fee is paid by whoever accepted, i.e. the team that did not
  post the listing that was filled). The filled listing is the seller's standing ask or the buyer's standing bid at
  the settled price (standing: not cancelled, and expired at most one tick before, since an accept on the last tick
  settles on the next); with both at that price, the one that left the recorder's board without a cancel. A package
  (cards both ways, with or without cash) is read from the listing that was accepted: its maker paid the cash if the
  listing gave cash, was paid if it asked for cash, and the other side paid the fee. When nothing tells, the old rule
  charges the fee (the seller's ask wins, then the buyer's bid, then the buyer), and a consistency pass moves it to
  the other side if that leaves a team below zero. Each team's "cash_unsure" is the sum of the fees still unsure for
  it. El Rastro keeps its fee; a fee charged on a team's own venue goes to that venue's owner;
- venue openings (a 250 P bond + 20 P; the free starter stalls of Saturday tick 201 cost nothing, "bond": 0 and
  "starter": true), bond refunds on venue.closed ("refund"), cash gifts and the organisers' grants. A grant's cash
  comes from the event, else from the schedule entry with the same note, else from the note itself ("150 primas":
  the Saturday allowance fired at tick 165 with no cash field and had left the schedule by then).

Holes in the recording: our recorder lost ticks 49-118 on Friday to DNS errors (logs/feed-vm/README.md).
Wherever two consecutive events are more than a tick apart, build() fills the hole from the complete copies in
GAP_SOURCES (logs/feed-vm/feed.jsonl), matched by event id.

Checked against our own account: Team 3's rebuilt cash equals the real one at every row of logs/score.jsonl from
tick 33 to tick 630 (Friday and Saturday), and at every live /api/me reading of Saturday afternoon (ticks 767-1041,
the Mini's score.view.log). `--json` carries that comparison as "check_history".

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
EXPIRY_GRACE = 1  # an accept on an offer's last tick settles on the next one (ticks 40, 49, 103, 152, 946)
MAX_FLIPS = 20  # consistency pass: at most this many unsure fees moved to the other side
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
    """Who posted what, to tell the acceptor of a settlement: ('ask', asset id) and ('bid', card ref) ->
    [(maker, price, tick, offer id, expires tick, to)]; ('give', asset id) -> [(maker, give cash, want cash, tick, ids of
    every asset the listing gives)] for packages; ('cancel', offer id) -> [tick]."""
    out = collections.defaultdict(list)
    for e in events:
        p = e["payload"]
        if e["type"] == "offer.cancelled":
            out[("cancel", p.get("offer"))].append(e["tick"])
            continue
        o = p.get("offer")
        if e["type"] != "offer.listed" or not isinstance(o, dict):
            continue
        give, want = o.get("give") or {}, o.get("want") or {}
        assets = [a for a in give.get("assets") or [] if isinstance(a, dict)]
        ids = frozenset(a.get("id") for a in assets)
        row = (o.get("id"), o.get("expires_tick"), o.get("to"))
        for a in assets:
            out[("ask", a["id"])].append((o.get("maker"), want.get("cash"), e["tick"], *row))
            out[("give", a["id"])].append((o.get("maker"), give.get("cash") or 0, want.get("cash") or 0, e["tick"], ids))
        for ref in vi.card_types(want):
            out[("bid", ref)].append((o.get("maker"), give.get("cash"), e["tick"], *row))
    return out


class Boards:
    """Which offers left a venue's public board at a tick (the recorder's snapshots.jsonl: El Rastro's board and every
    venue's book), read once and then incrementally. A filled offer leaves without an offer.cancelled event."""

    def __init__(self, path: Path):
        self.path, self.offset, self.seen = path, 0, collections.defaultdict(dict)  # venue -> {tick: offer ids}

    def _update(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:
            self.offset, self.seen = 0, collections.defaultdict(dict)
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1
        for line in chunk[:end].splitlines():
            head = line[:300]
            if b'"rastro"' not in head and b'"book"' not in head:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            venue = "rastro" if r.get("what") == "rastro" else r.get("venue") if r.get("what") == "book" else None
            body = r.get("body")
            offers = body.get("offers", body) if isinstance(body, dict) else body
            if venue and isinstance(offers, list) and isinstance(r.get("tick"), int):
                self.seen[venue].setdefault(r["tick"], {o.get("id") for o in offers if isinstance(o, dict)})
        self.offset += end

    def gone(self, tick: int, venue: str | None) -> set | None:
        """Offer ids on the board before `tick` and no longer on it at `tick` (or the next snapshot); None if unknown."""
        self._update()
        ticks = self.seen.get(venue or "rastro") or {}
        before = max((t for t in ticks if t < tick), default=None)
        after = min((t for t in ticks if t >= tick), default=None)
        if before is None or after is None:
            return None
        return ticks[before] - ticks[after]


BOARDS = Boards(vi.FEED / "snapshots.jsonl")


def acceptor_of(posted: dict, first: dict, buyer: str, seller: str, price: int, tick: int, venue: str | None = None,
                boards: Boards | None = None) -> tuple:
    """Who accepted a one-way trade, and so paid the fee, and how we know: (team, "price" | "board" | "unsure").
    The listing taken is the seller's standing ask or the buyer's standing bid at the settled price (t16 sold LAT-09
    into our 88 P bid at tick 724 while its own ask stood at 135). Standing: posted, not cancelled, and expiring at most
    EXPIRY_GRACE ticks before (an accept on an offer's last tick settles on the next one). With both at that price,
    the one that left the board without a cancel was filled. Otherwise the old rule, marked unsure: the seller's ask
    wins, then the buyer's bid, then the buyer."""
    def standing(r) -> bool:
        maker, pr, tk, oid, exp, to = r
        cancel = posted.get(("cancel", oid))
        return tk <= tick and (exp is None or exp >= tick - EXPIRY_GRACE) and not (cancel and min(cancel) < tick)

    asks = [r for r in posted.get(("ask", first.get("id")), []) if r[0] == seller and standing(r)]
    bids = [r for r in posted.get(("bid", first.get("ref")), []) if r[0] == buyer and r[5] in (None, seller) and standing(r)]
    ask_hit = [r[3] for r in asks if r[1] == price]
    bid_hit = [r[3] for r in bids if r[1] == price]
    if ask_hit and not bid_hit:
        return buyer, "price"
    if bid_hit and not ask_hit:
        return seller, "price"
    if ask_hit and bid_hit:
        gone = (boards or BOARDS).gone(tick, venue)
        if gone is not None:
            if set(bid_hit) & gone and not set(ask_hit) & gone:
                return seller, "board"
            if set(ask_hit) & gone and not set(bid_hit) & gone:
                return buyer, "board"
        return buyer, "unsure"
    any_ask = [r[0] for r in posted.get(("ask", first.get("id")), []) if r[2] <= tick]
    any_bid = [r for r in posted.get(("bid", first.get("ref")), []) if r[2] <= tick and r[0] == buyer]
    if any_ask and any_ask[-1] == seller:
        return buyer, "unsure"
    return (seller if any_bid else buyer), "unsure"


def package_deal(posted: dict, items: list, tick: int) -> tuple | None:
    """A settlement with cards going both ways (a package: e.g. our 38 P + four cards for t07's LAV-10 at tick 844).
    The accepted listing is the latest one whose maker gave cards that all moved in this settlement; its maker is
    (maker, the other side, give cash, want cash), or None when no listing matches."""
    sent = collections.defaultdict(set)
    for i in items:
        sent[i.get("frm")].add(i.get("id"))
    best = None
    for i in items:
        for m, give_cash, want_cash, tk, ids in posted.get(("give", i.get("id")), []):
            if tk <= tick and m == i.get("frm") and ids <= sent[m] and (best is None or tk > best[3]):
                best = (m, give_cash, want_cash, tk)
    if best is None:
        return None
    other = next((i.get("to") for i in items if i.get("frm") == best[0]), None)
    return best[0], other, best[1], best[2]


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


def build(events: list, schedule: dict | None = None, upto: int | None = None, fill: bool = True,
          report: dict | None = None) -> dict:
    """Every team's cash and cards. A fee whose payer the record cannot tell (see acceptor_of) is first charged by the
    old rule; then a consistency pass moves it to the other side whenever that rule leaves a team paying more than it
    had (cash below zero), the latest unsure fee of that team first. Each team's "cash_unsure" is the sum of the fees
    still unsure for it: its rebuilt cash is exact up to that many P. `report` (a dict) gets how every fee was told."""
    if fill:
        events = fill_gaps(events)
    forced: dict = {}
    for _ in range(MAX_FLIPS + 1):
        rep: dict = {}
        led = _build(events, schedule, upto, forced, rep)
        flip = overdraft_flip(led, rep, forced)
        if flip is None:
            break
        forced[flip[0]] = flip[1]
    rep["flipped"] = [u for u in rep["unsure"] if u["event"] in forced]
    for team in led:
        led[team]["cash_unsure"] = sum(u["fee"] for u in rep["unsure"]
                                       if u["event"] not in forced and team in (u["buyer"], u["seller"]))
    if report is not None:
        report.update(rep)
    return led


def overdraft_flip(led: dict, rep: dict, forced: dict) -> tuple | None:
    """The first team whose cash goes below zero, and the latest unsure fee it paid before that: (event id, the other
    side), to be charged to the other side instead. None when no team overdraws or nothing is left to move."""
    worst = None
    for team, r in led.items():
        low = next(((tk, c) for tk, c in r["history"] if c < 0), None)
        if low and (worst is None or low[0] < worst[1]):
            worst = (team, low[0])
    if worst is None:
        return None
    team, tick = worst
    cands = [u for u in rep["unsure"] if u["payer"] == team and u["tick"] <= tick and u["event"] not in forced]
    if not cands:
        return None
    u = cands[-1]
    return u["event"], u["seller"] if u["payer"] == u["buyer"] else u["buyer"]


def _build(events: list, schedule: dict | None, upto: int | None, forced: dict, rep: dict) -> dict:
    rep.update(how={"price": 0, "board": 0, "unsure": 0, "package": 0, "no fee": 0}, unsure=[])
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

    def pay_fee(p: dict, acceptor: str, refs: str, tick: int) -> None:
        """The settlement's fee comes out of the acceptor's cash; on a team's own venue it goes to the owner."""
        fee = p.get("fee") or 0
        if not fee:
            return
        move(acceptor, tick, -fee, f"fee on {refs} (accepted)")
        if acceptor in led:
            led[acceptor]["fees"] += fee
        owner = owners.get(p.get("venue")) if p.get("venue") not in HOUSE_VENUES else None
        if owner in led:
            move(owner, tick, fee, f"fee earned on {refs} at {p.get('venue')}")
            led[owner]["fees_earned"] += fee

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
            if len(receivers) != 1:  # cards both ways: the accepted listing says who paid the cash and the fee
                for i in items:
                    if i.get("to") in led:
                        led[i["to"]]["cards_in"][i.get("ref")] += 1
                    if i.get("frm") in led:
                        led[i["frm"]]["cards_out"][i.get("ref")] += 1
                deal = package_deal(posted, items, t)
                fee = p.get("fee") or 0
                if deal is None:  # no matching listing: cash direction and fee payer unknown
                    if fee or price:
                        sides = sorted({i.get("frm") for i in items} | {i.get("to") for i in items})
                        rep["unsure"].append({"event": e.get("id"), "tick": t, "ref": items[0].get("ref"),
                                              "buyer": sides[0], "seller": sides[-1], "price": price, "fee": fee,
                                              "payer": None})
                        rep["how"]["unsure"] += 1
                    else:
                        rep["how"]["no fee"] += 1
                    record(t)
                    continue
                maker, other, give_cash, want_cash = deal

                def lot(team: str, way: str) -> str:
                    return ", ".join(i.get("ref") or "?" for i in items if i.get(way) == team)

                payer = (maker if give_cash else other if want_cash else None) if price else None
                if payer:
                    payee = other if payer == maker else maker
                    move(payer, t, -price, f"bought {lot(payer, 'to')} from {payee} for {price} P + {lot(payer, 'frm')}")
                    move(payee, t, price, f"sold {lot(payer, 'to')} to {payer} for {price} P + {lot(payer, 'frm')}")
                    for team, side in ((payer, "team_bought"), (payee, "team_sold")):
                        if team in led:
                            led[team][side] += price
                for team in (maker, other):  # a package or a card-for-card swap is one trade for each side
                    if team in led:
                        led[team]["trades"] += 1
                got, gave = lot(other, "to"), lot(other, "frm")
                pay_fee(p, other, f"{got} for {gave}", t)  # the side that took the listing pays the fee
                rep["how"]["package" if fee else "no fee"] += 1
                record(t)
                continue
            buyer = receivers[0]
            seller = next((i.get("frm") for i in items if i.get("frm") != buyer), None)
            acceptor, how = acceptor_of(posted, items[0], buyer, seller, price, t, p.get("venue"))
            if not p.get("fee"):
                how = "no fee"
            elif how == "unsure":
                rep["unsure"].append({"event": e.get("id"), "tick": t, "ref": items[0].get("ref"), "buyer": buyer,
                                      "seller": seller, "price": price, "fee": p.get("fee"), "payer": acceptor})
                acceptor = forced.get(e.get("id"), acceptor)
            rep["how"][how] += 1
            refs = ", ".join(i.get("ref") or "?" for i in items)
            move(buyer, t, -price, f"bought {refs} from {seller}")
            move(seller, t, price, f"sold {refs} to {buyer}")
            pay_fee(p, acceptor, refs, t)
            for team, side in ((buyer, "team_bought"), (seller, "team_sold")):
                if team in led:
                    led[team][side] += price
                    led[team]["trades"] += 1
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
    fees: dict = {}
    led = build(events, vi.public("schedule"), fill=False, report=fees)
    chk = check_us(led)
    hist = check_history(led, score_rows(), events[-1]["tick"])
    if args.json:
        out = {t: {k: v for k, v in r.items() if k not in ("cards_in", "cards_out")} for t, r in led.items()}
        print(json.dumps({"tick": events[-1]["tick"], "check": chk, "check_history": hist, "gaps": holes,
                          "fees": fees, "teams": out}, indent=1, default=str))
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
    print("fee payer told by: " + ", ".join(f"{k} {v}" for k, v in fees["how"].items())
          + "".join(f"; tick {u['tick']} {u['ref']} {u['seller']}->{u['buyer']} fee {u['fee']} "
                    + ("moved by the consistency pass" if u in fees["flipped"] else "still unsure")
                    for u in fees["unsure"]))
    bad = [h for h in hist if not h["ok"]]
    if hist:
        print(f"history: {len(hist) - len(bad)}/{len(hist)} snapshots match"
              + "".join(f"; tick {h['tick']} real {h['real']} rebuilt {h['rebuilt']}" for h in bad))
    print(f"{'team':5} {'cash':>5} {'+/-':>3} {'dealers':>8} {'teams+':>7} {'teams-':>7} {'fees':>5} {'bond':>5} {'trades':>6}  unlocked / venue")
    for t, r in sorted(led.items(), key=lambda x: -x[1]["cash"]):
        print(f"{t:5} {r['cash']:5} {r['cash_unsure'] or '':>3} {r['dealer_earned'] - r['dealer_spent']:+8} {r['team_sold']:7} {r['team_bought']:7} "
              f"{r['fees']:5} {r['bonds']:5} {r['trades']:6}  {','.join(r['unlocked']) or '-'} {r['venue'] or ''}")


if __name__ == "__main__":
    main()
