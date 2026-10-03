"""Announce La Celestina (v20) on the public feed: the only way other teams hear about our venue.

Market points come from trades between OTHER teams on our venue (kit/RULES.md, "Your own market"): each one added
+1.3 to +2 to the free stalls that got one (t17, t07, t14 on Saturday). v20 had none by 19:00 on Saturday, although
t15 listed 16 asks on it at ticks 384-395: nobody heard of them, and t12 bought two of those very cards from t15 on
t14's and t17's free stalls half an hour later. Our messages at the time led with El Rastro's open bids, which sends
sellers to El Rastro.

So a message now sells what is on v20 and what v20 would cross, all inside the text (other teams' agents read the feed;
they do not open web pages):
  - the live offers on v20, with the team that posted them (public: the feed's offer.listed names every maker), the
    price and the offer id, and how to take one (accept it, or post the other side of a cash offer);
  - El Rastro pairs a broker would cross, ask at or just above the bid (NEAR_GAP), with both teams and offer ids:
    El Rastro has no broker and its taker pays 5 % + 1 P, so those pairs sit there; on v20 they meet at the midpoint;
  - a short pitch.
Three variants rotate the order so the feed does not see the same words twice in a row. Only public facts, no asks in
return. Cards we are missing ourselves never appear (--exclude): pointing their sellers at v20, where we cannot buy,
works against us. Offers addressed to one team (to: tXX) are left out: nobody else can take them.

    python3 tools/announce.py plan                       # prints the next message and the request; sends nothing
    python3 tools/announce.py run --yes                  # posts one message with the broker key
    python3 tools/announce.py run --yes --every-min 12 --count 40

Every offer named comes from the venues' current public books (GET /api/venues/<id>/offers), so nothing taken,
cancelled or expired is advertised; the feed only names who posted each one: the API's last 1,000 events plus the
recorded feed (logs/feed/feed.jsonl on the Mini), and each team's pseudonym per venue learnt from those names; in
`run`, our own open offers come from GET /api/me/offers with the team key when the machine has one (read only), so
they are never paired however old they are. Swaps are
advertised as taken by accepting them (POST /api/offers/<id>/accept): our broker crosses cash asks and bids only.
`plan` is keyless. `run` posts with the broker key (BROKER_KEY, or ~/.bazaar/broker.env as agent/broker.py reads it):
only the machine that runs the broker has it. The key is never printed or logged. POST /api/broker/announce.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))

URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
KEY_FILE = Path.home() / ".bazaar" / "broker.env"
VENUE = "v20"
LINK = None             # no web link by default: agents read the feed text, they do not open pages
MAX_CHARS = 1200        # the server keeps 1,200 characters of a message
NEAR_GAP = 3            # a bid within this many P of the ask counts as "almost crossing" (El Rastro's fee on a
                        # 20 P card is 2 P; at 0 % the two sides can meet halfway)
OURS = "t03"            # our own offers never appear: we cannot trade on our own venue anyway
SHOW_OFFERS = 4         # live v20 offers named in one message
POLL_S = 20             # run: seconds between reads of v20's book (keyless) while waiting
MEASURE_TICKS = 20      # run: a post's response is what reached v20 in this many ticks after it (and before, as base)
MIN_GAP_MIN = 10        # run --on-event: never two posts closer than this, whatever the trigger
GIVE_UP_TICKS = 40      # run: a response the feed could not give this many ticks after its window is logged unavailable
QUIET_BEFORE_S = 120    # run: Market Test silence (team rule: no API call from any lane), from this long before a
QUIET_AFTER_S = 600     # bench session starts until this long after it (19:53-20:05 for the 19:55 test)
TICKS_PER_HOUR = 120    # the game clock: t_hours moves 1/120 per tick (30 s ticks on Saturday, 15 s on Sunday)
# Cards Team 3 lacks (from /api/me at tick 556, after the silver pack): never advertised. Holdings are private, so
# this cannot be derived keylessly; update it when we buy one, or pass --exclude.
MISSING = ("LAV-09", "LAV-10", "LAT-03", "LAT-09", "SAL-02", "SAL-05", "SAL-09", "SAL-10",
           "MAL-03", "MAL-05", "MAL-09", "RET-01", "RET-03", "RET-04", "RET-05", "RET-07", "RET-08", "RET-09", "RET-10")
STATE = ROOT / "logs" / "state" / "announce.json"


def shape(o: dict):
    """The offer's complete shape, or None for anything we do not advertise:
      ("ask", ref, price)   gives exactly one card asset, wants cash only;
      ("bid", ref, price)   gives cash only, wants exactly one card type ("card:<ref>"), nothing else;
      ("swap", give, want)  gives exactly one card asset, wants exactly one card type, no cash either side.
    Any extra requirement (an asset id, a second type, a pack, cash on both sides) makes it None: a cash-only
    description or a crossing promise would be false for it. Asks and bids are what public_plan crosses."""
    if not isinstance(o, dict):
        return None
    g, w = o.get("give") or {}, o.get("want") or {}
    if not isinstance(g, dict) or not isinstance(w, dict):
        return None
    g_assets, g_types = g.get("assets") or [], g.get("types") or []
    w_assets, w_types = w.get("assets") or [], w.get("types") or []
    g_cash, w_cash = g.get("cash") or 0, w.get("cash") or 0

    def one_card(assets):
        if len(assets) == 1 and isinstance(assets[0], dict) and assets[0].get("kind") == "card" and assets[0].get("ref"):
            return assets[0]["ref"]
        return None

    def one_card_type(types):
        if len(types) == 1 and isinstance(types[0], str) and types[0].startswith("card:") and len(types[0]) > 5:
            return types[0][5:]
        return None

    def cash(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0

    if g_types or w_assets:
        return None
    gave, wanted = one_card(g_assets), one_card_type(w_types)
    if gave and not g_cash and cash(w_cash) and not w_types:
        return ("ask", gave, int(w_cash))
    if wanted and not g_assets and cash(g_cash) and not w_cash:
        return ("bid", wanted, int(g_cash))
    if gave and wanted and not g_cash and not w_cash:
        return ("swap", gave, wanted)
    return None


def refs(o: dict) -> set:
    """Every card an offer names, for the exclusion list (a shape we do not advertise names none)."""
    sh = shape(o)
    if sh is None:
        return set()
    return {sh[1]} | ({sh[2]} if sh[0] == "swap" else set())


def offer_makers(events: list) -> dict:
    """{offer id: team} from the public feed's offer.listed events (every listing names its maker). El Rastro's own
    book shows makers as pseudonyms; the feed is what ties an offer to a team."""
    out = {}
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "offer.listed":
            continue
        o = (e.get("payload") or {}).get("offer") or {}
        who = o.get("maker") or e.get("actor")
        if o.get("id") is not None and isinstance(who, str) and who.startswith("t"):
            out[o["id"]] = who
    return out


FEED_FILE = ROOT / "logs" / "feed" / "feed.jsonl"   # the feed recorder's file on the machine that runs us (the Mini)


def recorded_events(path: Path = FEED_FILE) -> list:
    """offer.listed events from the recorded feed (tools/feed_recorder.py), so makers older than the API's
    1,000-event window are known too. A missing file or a bad line costs nothing."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if '"offer.listed"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("type") == "offer.listed":
                    out.append(e)
    except OSError:
        pass
    return out


def our_offer_ids(me_offers: dict) -> set:
    """Ids of our own open offers from GET /api/me/offers. That list also holds offers other teams addressed to us:
    only maker == OURS counts."""
    return {o.get("id") for o in (me_offers or {}).get("offers") or []
            if isinstance(o, dict) and o.get("maker") == OURS and o.get("id") is not None}


def team_client():
    """A read-only use of the team key, when the machine has one (BAZAAR_KEY in the environment or the repo's .env,
    as the other bots load it): only GET /api/me/offers, to know our own offers for sure. None without a key. The key
    is never printed or logged."""
    key = os.environ.get("BAZAAR_KEY", "").strip()
    if not key:
        try:
            for line in (ROOT / ".env").read_text().splitlines():
                if line.strip().startswith("BAZAAR_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    if not key:
        return None
    from bazaar_sdk import Bazaar
    return Bazaar(URL, key, timeout=10, wait_on_tick=False, retries=1)


def learn_pseudonyms(books: dict, names: dict) -> dict:
    """Public books show makers as pseudonyms, one per team per venue (seen on Saturday: t06 has one on v07, another
    on El Rastro, another on v02). An offer the feed names ties its pseudonym to the team on that venue; every other
    offer with that pseudonym on that venue is then the same team's, however old. Returns names extended."""
    out = dict(names or {})
    for venue, book in (books or {}).items():
        alias = {}
        for o in book or []:
            team, m = out.get(o.get("id")), o.get("maker")
            if isinstance(team, str) and team[:1] == "t" and m and m != team:
                alias[m] = team
        for o in book or []:
            m = o.get("maker")
            if o.get("id") not in out and m in alias:
                out[o["id"]] = alias[m]
    return out


def market_books(get, venues: list) -> dict:
    """{venue: its open offers right now} from the public books (GET /api/venues/<id>/offers, keyless), El Rastro
    included. A venue whose book cannot be read is left out of this message. The books are the truth: an offer that
    was taken, cancelled or expired is simply not there (the feed only names who posted what)."""
    out = {}
    for v in dict.fromkeys(["rastro", *venues]):
        try:
            out[v] = [dict(o, venue=v) for o in get(f"{URL}/api/venues/{v}/offers").get("offers") or []
                      if isinstance(o, dict)]
        except Exception as e:  # one unreadable book costs that venue's lines, never the message
            print(f"book of {v} unavailable ({type(e).__name__})", flush=True)
    return out


def describe(o: dict, names: dict | None = None) -> str | None:
    """One offer in a few words: "t15 sells LAT-07 for 26 P (offer 9123)". None for shapes we do not advertise
    (anything but a plain ask, bid or one-for-one swap), offers to one team, and our own."""
    sh = shape(o)
    if sh is None or o.get("to"):
        return None
    who = (names or {}).get(o.get("id")) or o.get("maker") or ""
    if who == OURS:
        return None
    who = who if isinstance(who, str) and who[:1] == "t" and who[1:].isdigit() else "a team"
    oid = f" (offer {o['id']})" if o.get("id") is not None else ""
    kind, a, b = sh
    if kind == "ask":
        return f"{who} sells {a} for {b} P{oid}"
    if kind == "bid":
        return f"{who} buys {a} for {b} P{oid}"
    return f"{who} swaps {a} for any {b}{oid}, taken by accepting it"


def crossable(o: dict) -> bool:
    """A plain card ask or bid: what our broker crosses (public_plan). Swaps are only taken by accepting them."""
    sh = shape(o)
    return sh is not None and sh[0] in ("ask", "bid")


def take_order(o: dict, fee=(0, 0)) -> str | None:
    """The order that meets a plain v20 ask or bid on the other side, as RULES.md writes it, with our venue's fee
    counted (the buyer pays price + fee); None otherwise or when no whole price leaves room for the fee."""
    sh = shape(o)
    if sh is None or sh[0] == "swap":
        return None
    kind, ref, price = sh
    if kind == "ask":
        return f'{{"venue": "{VENUE}", "give": {{"cash": {price + fee_of(fee, price)}}}, "want": {{"cards": ["{ref}"]}}}}'
    ask = next((p for p in range(price, 0, -1) if p + fee_of(fee, p) <= price), None)
    if ask is None:
        return None
    return f'{{"venue": "{VENUE}", "give": {{"assets": [<your {ref}>]}}, "want": {{"cash": {ask}}}}}'


def venue_name(v) -> str:
    return "El Rastro" if v in (None, "rastro") else str(v)


def fee_of(fee, price: int) -> int:
    """Our venue's fee on one card at `price`, rounded up, as the broker computes it. fee = (bps, P per card)."""
    bps, per_card = fee or (0, 0)
    return math.ceil((bps or 0) * price / 10000) + (per_card or 0)


def fee_txt(fee) -> str:
    bps, per_card = fee or (0, 0)
    return f"{(bps or 0) / 100:g} % fee, {per_card or 0} P per card"


def market_sides(offers: list, names: dict | None = None) -> tuple[dict, dict]:
    """Best bid and ask per card across the offers given (El Rastro's book plus other venues' live offers), with the
    offer id and venue: ({ref: (bid, id, venue)}, {ref: (ask, id, venue)}). Only plain asks and bids (shape); offers
    on our venue, offers to one team and our own offers (by the feed's names or the maker) are left out: we cannot
    trade on v20, so a pair with one of ours would point a team at a trade that cannot happen there."""
    names = names or {}
    bids, asks = {}, {}
    for o in offers or []:
        if not isinstance(o, dict) or o.get("status", "open") != "open" or o.get("to") or o.get("venue") == VENUE:
            continue
        if OURS in (names.get(o.get("id")), o.get("maker")):
            continue
        sh = shape(o)
        v = o.get("venue") or "rastro"
        if sh and sh[0] == "bid" and sh[2] > bids.get(sh[1], (0,))[0]:
            bids[sh[1]] = (sh[2], o.get("id"), v)
        elif sh and sh[0] == "ask" and sh[2] < asks.get(sh[1], (10**9,))[0]:
            asks[sh[1]] = (sh[2], o.get("id"), v)
    return bids, asks


def near_market_pairs(offers: list, names: dict, skip=()) -> list:
    """Cards whose best bid and best ask (market_sides) are at most NEAR_GAP apart and come from two different teams
    (or makers we cannot name), closest first: [(ref, (bid, id, venue), (ask, id, venue))]."""
    bids, asks = market_sides(offers, names)
    out = []
    for r, b in bids.items():
        a = asks.get(r)
        if a is None or r in skip or a[0] - b[0] > NEAR_GAP:
            continue
        nb, na = names.get(b[1]), names.get(a[1])
        if (nb is not None and nb == na) or OURS in (nb, na):
            continue
        out.append((r, b, a))
    return sorted(out, key=lambda x: (x[2][0] - x[1][0], -x[1][0]))


def fillers(o: dict, offers: list, names: dict | None = None, n: int = 3) -> list:
    """Who could fill a v20 order, from the other venues' public books: for an ask, the best bids for that card; for
    a bid, the best asks; never the order's own maker, us, or a maker the feed cannot name (it could be us).
    [(team, price, venue)], best first."""
    sh = shape(o)
    if sh is None or sh[0] == "swap":
        return []
    names = names or {}
    kind, ref, _ = sh
    maker = names.get(o.get("id")) or o.get("maker")
    want = "bid" if kind == "ask" else "ask"
    out = []
    for x in offers or []:
        if not isinstance(x, dict) or x.get("to") or x.get("venue") == VENUE:
            continue
        sx = shape(x)
        who = names.get(x.get("id")) or x.get("maker")
        if not sx or sx[0] != want or sx[1] != ref or who in (maker, OURS):
            continue
        if not (isinstance(who, str) and who[:1] == "t" and who[1:].isdigit()):
            continue  # unnamed (a pseudonym older than the feed window): it could be us, so it is never named
        out.append((who, sx[2], x.get("venue") or "rastro"))
    return sorted(out, key=lambda t: -t[1] if want == "bid" else t[1])[:n]


def order_detail(o: dict, offers: list, names: dict | None = None) -> str:
    """For the order an event post leads with: until when it stands and who holds the other side elsewhere."""
    bits = []
    if isinstance(o.get("expires_tick"), int):
        bits.append(f"open until tick {o['expires_tick']}")
    f = fillers(o, offers, names)
    if f:
        side = "open bids" if (shape(o) or ("",))[0] == "ask" else "open asks"
        bits.append(f"{side} for it elsewhere: " + ", ".join(f"{w} {p} P on {venue_name(v)}" for w, p, v in f))
    return f" [{'; '.join(bits)}]" if bits else ""


def build_text(offers: list, variant: int, link: str | None = LINK, exclude=MISSING, venue_offers=(),
               names: dict | None = None, fee=(0, 0), lead=()) -> str:
    """One announcement, at most MAX_CHARS. `offers`: open offers off our venue (El Rastro's book, other venues' live
    offers); `venue_offers`: v20's live offers; `names`: {offer id: team} from the feed. variant 0: v20's book first;
    1: the near pairs first; 2: the "missing card" pitch in Spanish and English, then v20's book. Cards in
    `exclude` never appear. `fee`: v20's (bps, P per card), counted in every order and every "crosses" claim."""
    skip = set(exclude or ())
    names = names or {}
    live = [o for o in venue_offers or [] if not refs(o) & skip]
    lead = set(lead or ())
    shown = [(o, d + (order_detail(o, offers, names) if o.get("id") in lead else ""))
             for o in live for d in [describe(o, names)] if d][:SHOW_OFFERS]
    book = ""
    if shown:
        first = shown[0][0]
        order = next((take_order(o, fee) for o, _ in shown if crossable(o) and take_order(o, fee)), None)
        book = (f"Live on La Celestina ({VENUE}) now: " + "; ".join(d for _, d in shown) + ". "
                + f"Take one directly: POST /api/offers/{first.get('id', '<id>')}/accept (any offer id above). "
                + (f"Or post the other side of a cash offer on venue \"{VENUE}\", e.g. {order}, and our broker "
                   f"crosses it the same tick. " if order else "")
                + f"{fee_txt(fee)}. ")
    pairs = near_market_pairs(offers, names, skip)

    def who(oid, fallback):
        w = names.get(oid)
        return w if w and w != OURS else fallback

    def pair_txt(r, b, a):
        gap = a[0] + fee_of(fee, a[0]) - b[0]  # what the bid lacks to cover the ask plus v20's fee
        state = "they already cross on v20's terms" if gap <= 0 else f"{gap} P apart on v20's terms"
        return (f"{r}: {who(a[1], 'a seller')} asks {a[0]} P on {venue_name(a[2])} (offer {a[1]}), "
                f"{who(b[1], 'a buyer')} bids {b[0]} P on {venue_name(b[2])} (offer {b[1]}), {state}")

    pairs_txt = ""
    if pairs:
        pairs_txt = ("Buyer and seller close, nobody crossing them: "
                     + "; ".join(pair_txt(*p) for p in pairs[:3])
                     + f". On venue \"{VENUE}\" ({fee_txt(fee)}; El Rastro's taker pays 5 % + 1 P a card) our broker "
                       f"matches a bid and an ask the tick the bid covers the ask plus the fee, at the midpoint. ")
    pitch = (f"La Celestina ({VENUE}): {fee_txt(fee)}; our broker crosses a bid and an ask card by card, any copy, the "
             f"tick the bid covers the ask plus the fee.")
    tail = f" {link}" if link else ""
    v = variant % 3
    if v == 2:
        text = ("Missing one card for a page? Post a bid on venue \"v20\" (give cash, want {\"cards\": [\"<ref>\"]}) "
                "or your spare as an ask, and our broker crosses them card by card, any copy, each tick. 0 % fee, "
                "0 P per card. / ¿Te falta una carta? Publica tu puja o tu repetida en v20 y la cruzamos en el mismo "
                "tick, sin comisión. " + book)
    elif v == 1 and pairs_txt:
        text = pairs_txt + book
    elif book or pairs_txt:
        text = book + pairs_txt
    else:
        text = "Selling a spare or hunting a card? " + pitch + f" Post with venue \"{VENUE}\"."
    return (text.strip() + tail)[:MAX_CHARS]


class Announcer:
    """When to post, and what reached v20 after each post. Pure (the caller passes the clock, v20's book and the feed),
    so the tests drive it without a network.

    Posts: at most `count`. A scheduled slot every `every_s` seconds (the first one at once). With on_event, a new
    offer on v20 that we would advertise (eligible) posts at once instead of waiting for the slot, never closer than
    `min_gap_s` to the previous post; the next slot then counts from that post. Why: other teams' bots go where offers
    already are (no team's first offer on another venue followed an announcement naming it, 64 cases on Saturday),
    and a few explorers (t15, t04, t08, t13) post on empty venues: the moment one of them lists on v20 is the one
    moment a trade is possible, and the moment worth announcing.

    Response, logged per post: offers listed on v20 by other teams and trades settled on v20 in the MEASURE_TICKS
    after the post, with the same counts for the MEASURE_TICKS before it as the baseline (all from the public feed)."""

    def __init__(self, count: int, every_s: float, on_event: bool = False, min_gap_s: float = MIN_GAP_MIN * 60,
                 measure_ticks: int = MEASURE_TICKS, eligible=lambda o: True):
        self.count, self.every_s, self.on_event, self.min_gap_s = count, every_s, on_event, min_gap_s
        self.measure_ticks, self.eligible = measure_ticks, eligible
        self.posted, self.last_post, self.next_slot = 0, None, None
        self.queue = []         # eligible new v20 offers waiting for a post
        self.seen = None        # v20 offer ids already known (None until the first read: nothing is new at start)
        self.pending = []       # posts waiting for their response window

    def fresh(self, v20_book: list) -> list:
        """New offers on v20 that we would advertise, queued until a post is allowed (an offer that lands during the
        cooldown is posted when it ends, unless it has left the book by then). The first read only learns the book.
        Returns the queue as it stands, in arrival order."""
        ids = [o for o in v20_book or [] if isinstance(o, dict) and o.get("id") is not None]
        live = {o["id"] for o in ids}
        if self.seen is None:
            self.seen = set(live)
            return []
        new = [o for o in ids if o["id"] not in self.seen]
        self.seen.update(o["id"] for o in new)
        self.queue = [o for o in self.queue if o["id"] in live] + [o for o in new if self.eligible(o)]
        return list(self.queue)

    def due(self, now: float, fresh: list) -> str | None:
        """"event", "slot" or None. No two posts closer than min_gap_s, whatever the trigger."""
        if self.posted >= self.count:
            return None
        if self.last_post is not None and now - self.last_post < self.min_gap_s:
            return None
        if self.on_event and fresh:
            return "event"
        if self.next_slot is None or now >= self.next_slot:
            return "slot"
        return None

    def mark_posted(self, now: float, tick: int, why: str, fresh_ids=()) -> None:
        self.posted += 1
        self.last_post, self.next_slot = now, now + self.every_s
        self.queue = []         # every queued offer was on the book this post was built from
        self.pending.append({"post": self.posted, "tick": tick, "why": why, "fresh": list(fresh_ids)})

    def give_up(self, tick: int, after: int = GIVE_UP_TICKS) -> list:
        """Posts whose response window closed more than `after` ticks ago and could not be measured (the feed kept
        failing): they leave `pending`, so the run always ends."""
        late = [p for p in self.pending if tick >= p["tick"] + self.measure_ticks + after]
        self.pending = [p for p in self.pending if p not in late]
        return late

    def responses(self, tick: int, events: list, names: dict | None = None, v20_ids=None) -> list:
        """Response records for the posts whose window has closed at `tick`; they leave `pending`."""
        out, keep = [], []
        for p in self.pending:
            if tick < p["tick"] + self.measure_ticks:
                keep.append(p)
                continue
            r = dict(p, **window_counts(events, p["tick"], self.measure_ticks, names))
            if v20_ids is not None:  # the announced orders no longer on v20 (taken, cancelled or expired)
                r["fresh_left_book"] = [i for i in p.get("fresh", []) if i not in v20_ids]
            out.append(r)
        self.pending = keep
        return out


def window_counts(events: list, t0: int, k: int, names: dict | None = None) -> dict:
    """Offers listed on v20 by other teams and trades settled on v20, in (t0, t0 + k] ("after") and [t0 - k, t0)
    ("before"), from the public feed."""
    def count(lo, hi):
        listed, teams, trades = 0, set(), 0
        for e in events or []:
            t = e.get("tick") if isinstance(e, dict) else None
            if not isinstance(t, int) or not lo <= t <= hi:
                continue
            pl = e.get("payload") or {}
            if e.get("type") == "offer.listed" and (pl.get("offer") or {}).get("venue") == VENUE:
                who = (pl.get("offer") or {}).get("maker") or e.get("actor")
                if who != OURS:
                    listed += 1
                    teams.add(who)
            elif e.get("type") == "settlement" and pl.get("venue") == VENUE:
                trades += 1
        return listed, sorted(t for t in teams if t), trades
    la, ta, xa = count(t0 + 1, t0 + k)
    lb, tb, xb = count(t0 - k, t0 - 1)
    return {"window_ticks": k, "listed_after": la, "teams_after": ta, "trades_after": xa,
            "listed_before": lb, "teams_before": tb, "trades_before": xb}


def quiet_windows(schedule: dict, clock: dict, now: float, horizon_h: float = 3.0) -> list:
    """[(start, end)] wall-clock epochs when no lane may call the API: each upcoming Market Test (schedule action
    "bench") from QUIET_BEFORE_S before its start to QUIET_AFTER_S after. Game hours become seconds through the
    clock (TICKS_PER_HOUR ticks of tick_seconds each). Only sessions within `horizon_h` game hours and before the
    day closes are placed (the clock stops overnight); the schedule is read again outside the windows."""
    try:
        t_now, tick_s = float(clock["t_hours"]), float(clock["tick_seconds"])
    except (KeyError, TypeError, ValueError):
        return []
    if clock.get("paused"):
        return []
    out = []
    for ev in sorted((schedule or {}).get("upcoming") or [], key=lambda e: e.get("at_hours", 0)):
        at = ev.get("at_hours")
        if not isinstance(at, (int, float)) or at < t_now - 1 or at - t_now > horizon_h:
            continue
        if ev.get("action") == "day_closes":
            break
        if ev.get("action") == "bench":
            start = now + (at - t_now) * TICKS_PER_HOUR * tick_s
            out.append((math.floor(start - QUIET_BEFORE_S), math.ceil(start + QUIET_AFTER_S)))  # rounded outwards
    return out


def parse_quiet(text: str, today: time.struct_time | None = None) -> list:
    """--quiet "21:53-22:05,09:32-09:45": wall-clock windows for today (local time) as [(start, end)] epochs."""
    out = []
    base = today or time.localtime()
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        a, b = part.split("-")
        def at(hm):
            h, m = (int(x) for x in hm.strip().split(":"))
            return time.mktime((base.tm_year, base.tm_mon, base.tm_mday, h, m, 0, 0, 0, -1))
        out.append((at(a), at(b)))
    return out


def quiet_until(windows: list, now: float):
    """The end of the window `now` falls in, or None."""
    ends = [end for start, end in windows if start <= now < end]
    return max(ends) if ends else None


def next_variant(path: Path = STATE) -> int:
    try:
        return int(json.loads(path.read_text()).get("next", 0))
    except (OSError, ValueError, AttributeError):
        return 0


def save_variant(n: int, path: Path = STATE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"next": n}))
    except OSError:
        pass


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
        return json.load(r)


def post_announce(text: str, key: str) -> dict:
    """POST /api/broker/announce with the broker key. Returns the server's answer or {"http_error", "body"}."""
    req = urllib.request.Request(f"{URL}/api/broker/announce", method="POST", data=json.dumps({"text": text}).encode(),
                                 headers={"X-Broker-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode(errors="replace")[:300]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Announce La Celestina (v20) on the feed")
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--yes", action="store_true", help="run only: really post")
    ap.add_argument("--variant", type=int, default=None, help="0, 1 or 2 (default: rotate)")
    ap.add_argument("--no-link", action="store_true", help="leave out the web link (the default has none)")
    ap.add_argument("--link", default=LINK, help="append this link (off by default: agents do not open pages)")
    ap.add_argument("--exclude", default=",".join(MISSING),
                    help="comma list of cards never advertised (default: the cards we lack)")
    ap.add_argument("--every-min", type=float, default=0, help="run only: minutes between scheduled messages")
    ap.add_argument("--count", type=int, default=1, help="run only: how many messages at most")
    ap.add_argument("--on-event", action="store_true",
                    help="run only: also post at once when a new offer appears on v20 (never closer than --min-gap-min)")
    ap.add_argument("--min-gap-min", type=float, default=MIN_GAP_MIN, help="run: minutes between any two posts")
    ap.add_argument("--quiet", default="", help='run: extra silence windows today, e.g. "21:53-22:05" (Market Test '
                                                'silences from /api/schedule are always kept)')
    ap.add_argument("--key-file", default=str(KEY_FILE))
    args = ap.parse_args(argv)
    link = None if args.no_link else args.link
    exclude = tuple(x.strip() for x in args.exclude.split(",") if x.strip())
    if args.cmd == "run" and not args.yes:
        ap.error("run posts on the public feed: add --yes")
    key, team = None, None
    if args.cmd == "run":
        team = team_client()
        from broker import load_broker_key  # same key source as agent/broker.py
        key = load_broker_key(Path(args.key_file))
        from runlog import RunLog
        log = RunLog("announce")
        log.start(plan={"count": args.count, "every_min": args.every_min, "link": bool(link)})
    def compose(variant: int, first=()) -> str:
        """The message from the live books. A failed feed read costs only the team names; a failed venue index only
        the other venues and v20's fee (taken as 0 %, 0 P; El Rastro's and v20's books are still read): one bad read
        never cancels the run."""
        try:
            events = get_json(f"{URL}/api/feed?limit=1000").get("events", [])
        except Exception as e:
            print(f"feed unavailable ({type(e).__name__}); no team names in this message", flush=True)
            events = []
        try:
            index = [v for v in get_json(f"{URL}/api/venues").get("venues", []) if isinstance(v, dict)]
        except Exception as e:
            print(f"venue index unavailable ({type(e).__name__}); El Rastro and v20 only", flush=True)
            index = []
        venues = [v.get("venue") for v in index if v.get("status") == "open" and v.get("venue")]
        ours = next((v for v in index if v.get("venue") == VENUE), {})
        fee = (ours.get("fee_bps") or 0, ours.get("fee_per_card") or 0)
        books = market_books(get_json, venues + [VENUE])
        offers = [o for v, book in books.items() if v != VENUE for o in book]
        names = learn_pseudonyms(books, {**offer_makers(recorded_events()), **offer_makers(events)})
        if team is not None:  # our own open offers, for sure: never paired, never named as anyone else's
            try:
                names.update({i: OURS for i in our_offer_ids(team.my_offers())})
            except Exception as e:
                print(f"our offers unavailable ({type(e).__name__}); feed names and pseudonyms only", flush=True)
        firsts = {o.get("id") for o in first}
        v20 = sorted(books.get(VENUE, []), key=lambda o: o.get("id") not in firsts)  # the new offer leads
        return build_text(offers, variant, link, exclude, v20, names, fee, firsts)

    if args.cmd == "plan":
        variant = args.variant if args.variant is not None else next_variant()
        text = compose(variant)
        print(f"variant {variant % 3}, {len(text)} chars:\n{text}")
        print(f"\nwould POST {URL}/api/broker/announce {json.dumps({'text': text}, ensure_ascii=False)[:120]}...")
        return

    skip = set(exclude)
    ann = Announcer(max(1, args.count), max(60.0, args.every_min * 60), args.on_event, args.min_gap_min * 60,
                    eligible=lambda o: describe(o) is not None and not refs(o) & skip)
    manual = parse_quiet(args.quiet)
    windows, refreshed = list(manual), None
    while ann.posted < ann.count or ann.pending:
        end = quiet_until(windows, time.time())
        if end is not None:  # Market Test silence: no API call at all until it ends
            print(f"[{time.strftime('%H:%M:%S')}] silence until {time.strftime('%H:%M:%S', time.localtime(end))}",
                  flush=True)
            log.event("silence", until=round(end, 1))
            time.sleep(max(1.0, end - time.time()))
            continue
        if refreshed is None or time.time() - refreshed >= 300:  # place the coming Market Tests every 5 minutes
            try:
                windows = manual + quiet_windows(get_json(f"{URL}/api/schedule"), get_json(f"{URL}/api/clock"),
                                                 time.time())
                refreshed = time.time()
            except Exception as e:
                print(f"schedule unavailable ({type(e).__name__}); keeping the windows known", flush=True)
            if quiet_until(windows, time.time()) is not None:
                continue
        try:
            tick = get_json(f"{URL}/api/clock").get("tick")
            v20 = get_json(f"{URL}/api/venues/{VENUE}/offers").get("offers") or []
        except Exception as e:  # a failed read waits for the next poll
            print(f"read failed ({type(e).__name__}); retrying", flush=True)
            time.sleep(POLL_S)
            continue
        fresh = ann.fresh(v20)
        why = ann.due(time.time(), fresh)
        if why:
            # --variant wins for every post (f9 runs --on-event --variant 2: pitch + v20's book, no near-pair block);
            # without it an event leads with v20's book (variant 0) and slots rotate
            variant = args.variant if args.variant is not None else (0 if why == "event" else next_variant())
            text = compose(variant, fresh if why == "event" else ())
            res = post_announce(text, key)
            print(f"[{time.strftime('%H:%M:%S')}] {why} post {ann.posted + 1}/{ann.count} variant {variant % 3} "
                  f"-> {json.dumps(res, ensure_ascii=False)[:200]}\n{text}", flush=True)
            log.event("announce", why=why, variant=variant % 3, chars=len(text), text=text, result=res, tick=tick,
                      fresh=[o.get("id") for o in fresh])
            if "http_error" in res:
                break
            ann.mark_posted(time.time(), tick if isinstance(tick, int) else 0, why, [o.get("id") for o in fresh])
            if why != "event":
                save_variant(variant + 1)
        if ann.pending and isinstance(tick, int) and any(tick >= p["tick"] + ann.measure_ticks for p in ann.pending):
            try:
                events = get_json(f"{URL}/api/feed?limit=1000").get("events", [])
                for r in ann.responses(tick, events, v20_ids={o.get("id") for o in v20 if isinstance(o, dict)}):
                    print(f"[{time.strftime('%H:%M:%S')}] response {json.dumps(r)}", flush=True)
                    log.event("response", **r)
            except Exception as e:
                print(f"feed read failed ({type(e).__name__})", flush=True)
                for p in ann.give_up(tick):
                    log.event("response_unavailable", **p)
        time.sleep(POLL_S)
    log.end()


if __name__ == "__main__":
    main()
