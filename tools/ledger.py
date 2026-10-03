"""Every team's cash and known cards, rebuilt from the public feed alone. Offline, no key.

Everyone starts with 400 P (kit/RULES.md). From there the public feed shows every move of cash:
- dealer settlements (packs and cards bought from or sold to a dealer, at the settled price);
- team-to-team settlements (the buyer pays the price; the fee is paid by whoever accepted, i.e. the team that did not
  post the listing that was filled). The filled listing is the seller's standing ask or the buyer's standing bid at
  the settled price (standing: not cancelled, and expired at most one tick before, since an accept on the last tick
  settles on the next, and on the settlement's venue); with both at that price, the one that left the recorder's board
  without a cancel or an expiry in between while the other stayed on it (else unsure). A package (cards both ways,
  with or without cash) is read from the listing that matches the whole settlement (standing, for that counterparty,
  exactly the cards each way, the settled cash on one side): its maker
  paid the cash if the listing gave cash, was paid if it asked for cash, and the other side paid the fee; with no
  such listing, or two that read it differently, it stays unsure. When nothing tells, the old rule charges the fee
  (the seller's ask wins, then the buyer's bid, then the buyer); a consistency pass weighs every way of charging the
  unsure fees against every team's cash history, applies one of the ways that leave the fewest teams below zero, and
  pins a fee only when all those ways agree on its payer. Each team's "cash_unsure" bounds what is
  still unknown for it (unsure fees, plus the cash of a settlement whose direction is unknown, or one without items).
  El Rastro keeps its fee; a fee charged on a team's own venue goes to that venue's owner;
- venue openings (a 250 P bond + 20 P; the free starter stalls of Saturday tick 201 cost nothing, "bond": 0 and
  "starter": true), bond refunds on venue.closed ("refund"), cash gifts and the organisers' grants. A grant's cash
  comes from the event, else from the schedule entry with the same note, else from the note itself ("150 primas":
  the Saturday allowance fired at tick 165 with no cash field and had left the schedule by then). A grant told only
  in an organisers' announcement counts too ("Payday in Madrid: every team gets 400 primas", tick 1201, with no
  schedule.fired), unless a structured grant fired within two ticks.

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
import itertools
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
MAX_FLIP_COMBOS = 4096  # consistency pass: largest group of linked unsure settlements it weighs exactly
GAP_TICKS = 1  # two consecutive events further apart than this: a hole in the recording, filled from GAP_SOURCES
PRIMAS = re.compile(r"(\d+)\s*primas", re.IGNORECASE)
PAYDAY = re.compile(r"every team gets (\d+) primas", re.IGNORECASE)  # an organisers' grant told only in words (tick 1201)
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
    """Who posted what, to tell the acceptor of a settlement. ('offer', id) -> [the offer as posted: maker, tick, cash on
    each side, ids it gives, refs and ids it wants, expiry, recipient, venue]; ('ask', asset id), ('give', asset id),
    ('bid', card ref) and ('bid_id', asset id) -> [offer ids]; ('cancel', offer id) -> [ticks]."""
    out = collections.defaultdict(list)
    for e in events:
        p = e["payload"]
        if e["type"] == "offer.cancelled":
            out[("cancel", p.get("offer"))].append(e["tick"])
            continue
        o = p.get("offer")
        if e["type"] != "offer.listed" or not isinstance(o, dict) or ("offer", o.get("id")) in out:
            continue
        give, want = o.get("give") or {}, o.get("want") or {}
        assets = [a for a in give.get("assets") or [] if isinstance(a, dict)]
        out[("offer", o.get("id"))].append({
            "id": o.get("id"), "maker": o.get("maker"), "tick": e["tick"], "give_cash": give.get("cash") or 0,
            "want_cash": want.get("cash") or 0, "give_ids": frozenset(a.get("id") for a in assets),
            "want_refs": collections.Counter(vi.card_types(want)),
            "want_ids": frozenset(a.get("id") for a in want.get("assets") or [] if isinstance(a, dict)),
            "expires": o.get("expires_tick"), "to": o.get("to"), "venue": o.get("venue")})
        for a in assets:
            out[("ask", a.get("id"))].append(o.get("id"))
            out[("give", a.get("id"))].append(o.get("id"))
        for ref in vi.card_types(want):
            out[("bid", ref)].append(o.get("id"))
        for a in want.get("assets") or []:
            if isinstance(a, dict):
                out[("bid_id", a.get("id"))].append(o.get("id"))
    return out


def offer(posted: dict, oid) -> dict:
    return posted[("offer", oid)][0]


def standing(posted: dict, o: dict, tick: int, venue: str | None = None) -> bool:
    """Could this offer be the one a settlement at `tick` on `venue` filled? Posted by then, not cancelled before,
    expired at most EXPIRY_GRACE ticks before (an accept on the last tick settles on the next), same venue if both say."""
    cancel = posted.get(("cancel", o["id"]))
    return (o["tick"] <= tick and (o["expires"] is None or o["expires"] >= tick - EXPIRY_GRACE)
            and not (cancel and min(cancel) < tick) and (venue is None or o["venue"] in (None, venue)))


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
                self.seen[venue][r["tick"]] = {o.get("id") for o in offers if isinstance(o, dict)}  # latest wins
        self.offset += end

    def window(self, tick: int, venue: str | None) -> tuple | None:
        """(tick of the last snapshot before `tick`, tick of the first at or after it, the offer ids on each), or None
        when the board was not recorded on both sides of `tick`."""
        self._update()
        ticks = self.seen.get(venue or "rastro") or {}
        before = max((t for t in ticks if t < tick), default=None)
        after = min((t for t in ticks if t >= tick), default=None)
        if before is None or after is None:
            return None
        return before, after, ticks[before], ticks[after]

    def gone(self, tick: int, venue: str | None) -> set | None:
        """Offer ids on the board before `tick` and no longer on it at `tick` (or the next snapshot); None if unknown."""
        w = self.window(tick, venue)
        return None if w is None else w[2] - w[3]


_BOARDS: dict = {}


def boards_for(path: Path) -> Boards:
    """One Boards reader per snapshots file, chosen when it is needed (the dashboard can point vi.FEED elsewhere)."""
    key = str(path)
    if key not in _BOARDS:
        _BOARDS[key] = Boards(Path(path))
    return _BOARDS[key]


def board_fill(posted: dict, boards: Boards, tick: int, venue: str | None, ask_hit: list, bid_hit: list) -> str | None:
    """"ask" or "bid": which of the two listings at the settled price the recorder's board shows being filled, or None.
    Filled: on the board before, gone after, with no cancel and no expiry inside that snapshot interval. The board
    tells only when one side has such an offer and every offer of the other side was on the board both before and
    after (still standing)."""
    w = boards.window(tick, venue)
    if w is None:
        return None
    before_tick, after_tick, before, after = w

    def filled(oid) -> bool:
        o = offer(posted, oid)
        cancelled = any(before_tick < c <= after_tick for c in posted.get(("cancel", oid), []))
        expired = o["expires"] is not None and o["expires"] < after_tick
        return oid in before and oid not in after and not cancelled and not expired

    def stayed(oid) -> bool:
        return oid in before and oid in after

    if any(map(filled, bid_hit)) and all(map(stayed, ask_hit)):
        return "bid"
    if any(map(filled, ask_hit)) and all(map(stayed, bid_hit)):
        return "ask"
    return None


def legs(items: list) -> tuple:
    """A settlement's two legs: ({team: ids of the cards it sent}, {team: the cards it got}), and its sides."""
    sent, got = collections.defaultdict(set), collections.defaultdict(list)
    for i in items:
        sent[i.get("frm")].add(i.get("id"))
        got[i.get("to")].append(i)
    return sent, got, set(sent) | set(got)


def fits(o: dict, other: str, sent: dict, got: dict, price: int, pays: bool | None) -> bool:
    """Does listing `o` describe the whole settlement? For `other` (or anyone), giving exactly the cards its maker
    sent, wanting exactly the cards its maker got (by card type or by asset id), and the settled cash on the right
    side: `pays` True = its maker paid the price, False = was paid it, None = either (a package)."""
    maker = o["maker"]
    received = got.get(maker, [])
    refs = collections.Counter(i.get("ref") for i in received if i.get("id") not in o["want_ids"])
    net = o["give_cash"] - o["want_cash"]
    if pays is None:
        cash_ok = price in (o["give_cash"], o["want_cash"]) if price else not (o["give_cash"] or o["want_cash"])
    else:
        cash_ok = net == (price if pays else -price)
    return (o["give_ids"] == sent.get(maker, set()) and o["want_ids"] <= {i.get("id") for i in received}
            and refs == o["want_refs"] and o["to"] in (None, other) and cash_ok)


def candidates(posted: dict, items: list) -> list:
    """Every listing that names one of the settlement's cards: giving it, or wanting its type or its asset id."""
    ids = set()
    for i in items:
        ids |= set(posted.get(("give", i.get("id")), [])) | set(posted.get(("bid", i.get("ref")), []))
        ids |= set(posted.get(("bid_id", i.get("id")), []))
    return [offer(posted, oid) for oid in sorted(ids, key=str)]


def acceptor_of(posted: dict, items, buyer: str, seller: str, price: int, tick: int, venue: str | None = None,
                boards: Boards | None = None) -> tuple:
    """Who accepted a one-way trade (the seller's cards for the buyer's cash), and so paid the fee, and how we know:
    (team, "price" | "board" | "unsure"). The listing taken is the seller's standing ask or the buyer's standing bid
    that fits the whole settlement (see fits() and standing(): t16 sold LAT-09 into our 88 P bid at tick 724 while its
    own ask stood at 135). With both fitting, the one that left the board cleanly was filled (board_fill). Otherwise
    the old rule, marked unsure: the seller's ask wins, then the buyer's bid, then the buyer. `items` is the list of
    cards that moved (one dict is read as a single card from seller to buyer); `boards` defaults to the snapshots next
    to the feed being read (vi.FEED)."""
    if isinstance(items, dict):
        items = [{"frm": seller, "to": buyer, **items}]
    sent, got, _ = legs(items)
    cands = candidates(posted, items)
    ask_hit = [o["id"] for o in cands if o["maker"] == seller and standing(posted, o, tick, venue)
               and fits(o, buyer, sent, got, price, False)]
    bid_hit = [o["id"] for o in cands if o["maker"] == buyer and standing(posted, o, tick, venue)
               and fits(o, seller, sent, got, price, True)]
    if ask_hit and not bid_hit:
        return buyer, "price"
    if bid_hit and not ask_hit:
        return seller, "price"
    if ask_hit and bid_hit:
        side = board_fill(posted, boards or boards_for(vi.FEED / "snapshots.jsonl"), tick, venue, ask_hit, bid_hit)
        if side:
            return (seller if side == "bid" else buyer), "board"
        return buyer, "unsure"
    asks = [offer(posted, i) for i in posted.get(("ask", items[0].get("id")), [])]
    any_ask = [o["maker"] for o in asks if o["tick"] <= tick]
    if any_ask and any_ask[-1] == seller:
        return buyer, "unsure"
    return (seller if any(o["maker"] == buyer and o["tick"] <= tick for o in cands) else buyer), "unsure"


def package_deal(posted: dict, items: list, tick: int, venue: str | None = None, price: int = 0) -> tuple | None:
    """A settlement with cards going both ways (a package: our 38 P + four cards for t07's LAV-10 at tick 844, or a
    card-for-card swap). The accepted listing must fit the whole settlement (see fits() and standing()); either side
    may have paid the cash. Returns (maker, the other side, give cash, want cash) of the latest such listing, or None
    when none fits or two fit with different readings."""
    sent, got, parties = legs(items)
    if len(parties) != 2:
        return None
    found = []
    for o in candidates(posted, items):
        maker = o["maker"]
        if maker not in parties or not standing(posted, o, tick, venue):
            continue
        other = next(x for x in parties if x != maker)
        if fits(o, other, sent, got, price, None):
            found.append((o["tick"], maker, other, o["give_cash"], o["want_cash"]))
    if len({(maker, give_cash == price) for _, maker, _, give_cash, _ in found}) != 1:
        return None  # nothing fits, or two listings that read the settlement differently: leave it unsure
    return max(found)[1:]


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
          report: dict | None = None, boards: Boards | None = None) -> dict:
    """Every team's cash and cards. A fee whose payer the record cannot tell (see acceptor_of) is first charged by the
    old rule; then the consistency pass (consistent_flips) looks at every way of charging the unsure fees and keeps
    the ways that leave the fewest teams below zero: the first of them is the cash shown, and a fee counts as known
    only when all of them agree on its payer. Each team's "cash_unsure" bounds what is still unknown for it (unsure
    fees, the cash of a settlement whose direction is unknown, or one without items): its real cash lies within
    rebuilt ± cash_unsure unless a move never reached the public feed. `report` (a dict) gets how every fee was told
    ("how"), the unsure settlements, the fees the pass moved ("flipped") or pinned ("settled"), any team still below
    zero ("overdrawn"). `boards` reads the recorder's snapshots (default: next to vi.FEED)."""
    if fill:
        events = fill_gaps(events)
    rep: dict = {}
    led = _build(events, schedule, upto, {}, rep, boards)
    forced, settled = consistent_flips(rep)
    if forced:
        rep = {}
        led = _build(events, schedule, upto, forced, rep, boards)
    rep["flipped"] = [u for u in rep["unsure"] if u["event"] in forced]
    rep["settled"] = [u for u in rep["unsure"] if u["event"] in settled]
    rep["overdrawn"] = overdrawn(led)
    for team in led:
        led[team]["cash_unsure"] = sum(u["amount"] for u in rep["unsure"]
                                       if u["event"] not in settled and team in (u["buyer"], u["seller"]))
    rep.pop("points", None)
    if report is not None:
        report.update(rep)
    return led


def overdrawn(led: dict) -> list:
    """[(team, first tick its cash went below zero)]: a fee charged to the wrong side, or a move we cannot see."""
    out = []
    for team, r in led.items():
        low = next((tk for tk, c in r["history"] if c < 0), None)
        if low is not None:
            out.append((team, low))
    return out


def consistent_flips(rep: dict) -> tuple:
    """How to read the unsure settlements so that the fewest teams go below zero, and which fees that pins.

    Unknowns: each unsure one-way fee (keep it on the old rule's payer, or move it to the other side) and each
    settlement whose direction is unknown (which side paid the cash, which side paid the fee; a dealer's settlement
    without items: paid or got the price). Unknowns that share a team, directly or through other unknowns, form a
    group; a team's cash only moves with its own group, so each group is weighed on its own, exhaustively, by shifting
    cash on the points the build recorded (no rebuild: nothing else in the ledger depends on cash). In each group the
    combinations that leave the fewest of its teams below zero are the feasible ones; the fee payers of the one with
    the fewest moved fees are applied (forced); a settlement of unknown direction stays unapplied (its whole amount is
    in cash_unsure, which covers every reading). A one-way fee is pinned only when every feasible combination of its
    group agrees on its payer. A group with more than MAX_FLIP_COMBOS combinations keeps the old rule and pins
    nothing, and nothing is pinned while a settlement without known sides exists. Returns ({event id: payer},
    {pinned event ids})."""
    points = rep.get("points") or {}
    base_low = {team for team, pts in points.items() if any(c < 0 for _, c in pts)}
    unsure = [u for u in rep["unsure"] if u.get("seq") is not None]
    blind = any(u["payer"] is None and not u.get("parties") for u in unsure)

    def other(u: dict) -> str:
        return u["seller"] if u["payer"] == u["buyer"] else u["buyer"]

    def unknown(u: dict) -> tuple:
        """(u, options, cash shifts of each option, teams it touches)."""
        s = u["seq"]
        if u["payer"] is not None:
            shift = [(u["payer"], s, u["fee"]), (other(u), s, -u["fee"])]
            return u, [None, other(u)], [[], shift], {u["buyer"], u["seller"]}
        a = u["parties"][0]
        b = u["parties"][1] if len(u["parties"]) > 1 else "dealer"
        opts, shifts = [], []
        for payer in ((a, b) if u["price"] else (None,)):
            for fee_by in (((a, b) if b != "dealer" else (a,)) if u["fee"] else (None,)):
                d = []
                if payer:
                    payee = b if payer == a else a
                    d += [(x, s, sign * u["price"]) for x, sign in ((payer, -1), (payee, 1)) if x != "dealer"]
                if fee_by:
                    d.append((fee_by, s, -u["fee"]))
                opts.append((payer, fee_by))
                shifts.append(d)
        return u, opts, shifts, set(u["parties"])

    def below(shifts: list, teams: set) -> int:
        """How many of `teams` go below zero with these cash shifts (each: team, event position, P)."""
        by_team = collections.defaultdict(list)
        for team, s, d in shifts:
            by_team[team].append((s, d))
        low = (base_low & teams) - set(by_team)
        for team, ds in by_team.items():
            pts = points.get(team) or []
            checks = list(pts) + [(s, next((c for q, c in reversed(pts) if q <= s), START_CASH)) for s, _ in ds]
            if any(c + sum(d for s, d in ds if s <= q) < 0 for q, c in checks):
                low.add(team)
        return len(low)

    unknowns = [unknown(u) for u in unsure if u["payer"] is not None or u.get("parties")]
    parent: dict = {}

    def root(team):
        while parent.setdefault(team, team) != team:
            team = parent[team]
        return team

    for v in unknowns:
        first, *rest = sorted(v[3], key=str)
        for team in rest:
            parent[root(team)] = root(first)
    groups = collections.defaultdict(list)
    for v in unknowns:
        groups[root(next(iter(v[3])))].append(v)
    forced, pinned = {}, set()
    for group in groups.values():
        size = 1
        for v in group:
            size *= len(v[1])
        if size > MAX_FLIP_COMBOS:  # too many to weigh exactly: the old rule stays, nothing of this group is pinned
            continue
        group.sort(key=lambda v: -v[0]["seq"])
        teams = set().union(*(v[3] for v in group))
        scored = []
        for choice in itertools.product(*(range(len(v[1])) for v in group)):
            shifts = [d for v, c in zip(group, choice) for d in v[2][c]]
            moved = sum(1 for v, c in zip(group, choice) if v[0]["payer"] is not None and c)
            scored.append((below(shifts, teams), moved, choice))
        fewest = min(n for n, _, _ in scored)
        feasible = [(moved, choice) for n, moved, choice in scored if n == fewest]
        chosen = min(feasible, key=lambda x: x[0])[1]
        forced.update({v[0]["event"]: v[1][c] for v, c in zip(group, chosen) if v[0]["payer"] is not None and c})
        if not blind:
            pinned |= {v[0]["event"] for i, v in enumerate(group)
                       if v[0]["payer"] is not None and len({c[i] for _, c in feasible}) == 1}
    return forced, pinned


def _build(events: list, schedule: dict | None, upto: int | None, forced: dict, rep: dict,
           boards: Boards | None = None) -> dict:
    rep.update(how={"price": 0, "board": 0, "unsure": 0, "package": 0, "no fee": 0}, unsure=[],
               points=collections.defaultdict(list))  # team -> [(event position, cash)] for the consistency pass
    pos = [0]
    teams = sorted({e["payload"]["team"] for e in events if e["type"] == "team.joined"})
    led = {t: {"cash": START_CASH, "dealer_spent": 0, "dealer_earned": 0, "team_bought": 0, "team_sold": 0,
               "fees": 0, "fees_earned": 0, "bonds": 0, "refunds": 0, "gifts": 0, "grants": 0, "trades": 0,
               "unlocked": [], "venue": None,
               "cards_in": collections.Counter(), "cards_out": collections.Counter(), "moves": [], "history": []}
           for t in teams}
    posted = listings(events)
    owners: dict = {}  # venue id -> owning team
    # read before the replay, so the order of same-tick events never matters: every cash gift (below), and the ticks
    # of every structured grant whose cash the ledger can read (one it cannot read accounts for nothing)
    gifted = collections.defaultdict(set)  # (team, tick) -> cash amounts of its gifts, up to `upto`
    for e in events:
        if e["type"] == "gift.given" and e["payload"].get("cash") and (upto is None or e["tick"] <= upto):
            gifted[(e["payload"].get("team"), e["tick"])].add(int(e["payload"]["cash"]))

    def gift_was_grant(team: str, tick: int, cash: int) -> bool:
        """A gift of exactly the grant's cash within two ticks is the team's share of that grant, not more money."""
        return any(cash in gifted.get((team, tk), ()) for tk in range(tick - 2, tick + 3))

    grant_ticks = {e["tick"] for e in events if e["type"] == "schedule.fired"
                   and e["payload"].get("action") == "grant_all" and grant_cash(schedule, e["payload"])}

    def record(tick: int) -> None:
        for team in led:
            h = led[team]["history"]
            if not h or h[-1][1] != led[team]["cash"]:
                h.append((tick, led[team]["cash"]))
                rep["points"][team].append((pos[0], led[team]["cash"]))

    def move(team: str, tick: int, delta: int, what: str) -> None:
        if team not in led:
            return
        led[team]["cash"] += delta
        led[team]["moves"].append({"tick": tick, "delta": delta, "what": what})

    def credit_owner(p: dict, refs: str, tick: int) -> None:
        """A fee charged on a team's own venue goes to its owner, whoever paid it (El Rastro keeps its own)."""
        fee = p.get("fee") or 0
        owner = owners.get(p.get("venue")) if p.get("venue") not in HOUSE_VENUES else None
        if fee and owner in led:
            move(owner, tick, fee, f"fee earned on {refs} at {p.get('venue')}")
            led[owner]["fees_earned"] += fee

    def pay_fee(p: dict, acceptor: str, refs: str, tick: int) -> None:
        """The settlement's fee comes out of the acceptor's cash and goes to the venue (credit_owner)."""
        fee = p.get("fee") or 0
        if not fee:
            return
        move(acceptor, tick, -fee, f"fee on {refs} (accepted)")
        if acceptor in led:
            led[acceptor]["fees"] += fee
        credit_owner(p, refs, tick)

    for n, e in enumerate(events):
        if upto is not None and e["tick"] > upto:
            break
        pos[0] = n
        p, t = e["payload"], e["tick"]
        kind = e["type"]
        if kind == "settlement":
            items = [i for i in p.get("items") or [] if isinstance(i, dict)]
            price = p.get("price") or 0
            dealer = p.get("persona")
            if not items:  # nothing to read who paid whom: keep the amount as unsure for the parties named
                fee = p.get("fee") or 0
                if price or fee:
                    named = [x for x in p.get("parties") or [] if x in led]
                    rep["unsure"].append({"event": e.get("id"), "tick": t, "ref": None,
                                          "buyer": named[0] if named else None, "seller": named[-1] if named else None,
                                          "price": price, "fee": fee, "amount": price + fee, "payer": None, "seq": n,
                                          "parties": named[:2] if 0 < len(named) <= 2 and (dealer or len(named) == 2)
                                          else [], "dealer": bool(dealer), "incomplete": True})
                    rep["how"]["unsure"] += 1
                    credit_owner(p, "a settlement without items", t)  # the venue's fee, whoever paid it
                record(t)
                continue
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
                deal = package_deal(posted, items, t, p.get("venue"), price)
                fee = p.get("fee") or 0
                if deal is None:  # no listing fits: cash direction and fee payer unknown, the whole amount is unsure
                    if fee or price:
                        sides = sorted({str(i.get("frm")) for i in items} | {str(i.get("to")) for i in items})
                        teams_in = [x for x in sides if x in led]
                        rep["unsure"].append({"event": e.get("id"), "tick": t, "ref": items[0].get("ref"),
                                              "buyer": sides[0], "seller": sides[-1], "price": price, "fee": fee,
                                              "amount": price + fee, "payer": None, "seq": n,
                                              "parties": teams_in if len(teams_in) == 2 else [], "dealer": False})
                        rep["how"]["unsure"] += 1
                        credit_owner(p, ", ".join(i.get("ref") or "?" for i in items), t)  # whoever paid it
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
            acceptor, how = acceptor_of(posted, items, buyer, seller, price, t, p.get("venue"), boards)
            if not p.get("fee"):
                how = "no fee"
            elif how == "unsure":
                rep["unsure"].append({"event": e.get("id"), "tick": t, "ref": items[0].get("ref"), "buyer": buyer,
                                      "seller": seller, "price": price, "fee": p.get("fee"), "amount": p.get("fee"),
                                      "payer": acceptor, "seq": n})
                acceptor = forced[e.get("id")] if isinstance(forced.get(e.get("id")), str) else acceptor
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
        elif kind == "schedule.fired" and p.get("action") == "grant_all":
            cash = grant_cash(schedule, p)
            for team in led:
                if cash and not gift_was_grant(team, t, cash):
                    move(team, t, cash, f"grant: {p.get('note', '')}")
                    led[team]["grants"] += cash
        elif kind == "announcement" and PAYDAY.search(p.get("text") or ""):
            # the organisers' own announcements only (teams post venue.announcement); skipped when a structured grant
            # fired within two ticks, so the same money is never counted twice
            cash = int(PAYDAY.search(p["text"]).group(1))
            if not any(tk in grant_ticks for tk in range(t - 2, t + 3)):
                for team in led:
                    if not gift_was_grant(team, t, cash):
                        move(team, t, cash, f"grant: {p['text'][:80]}")
                        led[team]["grants"] += cash
        elif kind == "level.unlocked" and p.get("team") in led:
            led[p["team"]]["unlocked"].append(p.get("persona"))
        if kind in ("settlement", "venue.opened", "venue.closed", "gift.given", "schedule.fired", "announcement"):
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
                    + ("pinned by the consistency pass" + (" (moved to the other side)" if u in fees["flipped"] else "")
                       if u in fees["settled"] else
                       ("moved by the consistency pass, " if u in fees["flipped"] else "") + f"still unsure (±{u['amount']} P)")
                    for u in fees["unsure"])
          + "".join(f"; {team} below zero from tick {tk}" for team, tk in fees["overdrawn"]))
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
