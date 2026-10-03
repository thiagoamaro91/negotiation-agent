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

--variant missing (Sunday): ONE match per post from tools/matchmaker.py's output (--matches, default
logs/matchmaker/latest.json, written by `matchmaker.py json --live --out ... --every 120`), in its order (explicit live
wants first): the live offer (team, card, price, offer id, expiry) and the one action that completes it (POST
/api/offers/<id>/accept), or, for a need that is only inferred, "appears to be missing ... not confirmed" and the v20
bid and ask. A swap is accepted directly, never said to be crossed by our broker. Never an offer that has left its
book, one on another team's venue (unless --rival-venues), a card in --exclude, Team 3, or a match named in the last
MISSING_REPEAT posts. Nothing is recomputed here; a missing or stale file, or no match left, means no post. Each
post's response then says whether the named offer was taken (named_outcome) besides the trades on v20.

    python3 tools/announce.py plan                       # prints the next message and the request; sends nothing
    python3 tools/announce.py plan --variant missing     # the missing-card board from the matchmaker's last output
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
import re
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
QUIET_TAIL_S = 120      # run: silence kept this long after a session's last tick (its ticks x tick_seconds)
BENCH_TICKS = 16        # a Market Test session's length when the schedule or the feed does not say
STATUS_MAX_AGE_S = 300  # run: no post unless the Market Test schedule was read this recently (unknown = defer)
STATUS_RETRY_S = 60     # run: how often a failed schedule read is tried again (no other request meanwhile)
# Cards Team 3 lacks (from /api/me at tick 556, after the silver pack): never advertised. Holdings are private, so
# this cannot be derived keylessly; update it when we buy one, or pass --exclude.
MISSING = ("LAV-09", "LAV-10", "LAT-03", "LAT-09", "SAL-02", "SAL-05", "SAL-09", "SAL-10",
           "MAL-03", "MAL-05", "MAL-09", "RET-01", "RET-03", "RET-04", "RET-05", "RET-07", "RET-08", "RET-09", "RET-10")
STATE = ROOT / "logs" / "state" / "announce.json"
MATCHES = ROOT / "logs" / "matchmaker" / "latest.json"   # tools/matchmaker.py json --live --out ... --every 120
MATCHES_MAX_AGE_S = 900  # --variant missing: no post from a matchmaker file older than this
MISSING_STATE = ROOT / "logs" / "state" / "announce_missing.json"   # the matches announced lately
MISSING_REPEAT = 6       # --variant missing: a match is not announced again within this many posts


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


def recorded_events(path: Path = FEED_FILE, kinds=("offer.listed",)) -> list:
    """Events of the given kinds from the recorded feed (tools/feed_recorder.py), so what is older than the API's
    1,000-event window is known too. A missing file or a bad line costs nothing."""
    out = []
    marks = tuple(f'"{k}"' for k in kinds)
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not any(m in line for m in marks):
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("type") in kinds:
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
    return Bazaar(URL, key, timeout=10, wait_on_tick=False, retries=0)  # one attempt: no retry inside a silence


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


def load_matches(path: Path = MATCHES, now: float | None = None, max_age_s: float = MATCHES_MAX_AGE_S) -> dict:
    """The matchmaker's last output (tools/matchmaker.py json --out). LookupError when it is missing, unreadable or
    older than max_age_s: a stale match could name a card that has since been bought, so no post then."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LookupError(f"no matchmaker output at {path} ({type(e).__name__})")
    at = doc.get("generated_at") if isinstance(doc, dict) else None
    if not isinstance(at, (int, float)) or (now if now is not None else time.time()) - at > max_age_s:
        raise LookupError("the matchmaker output is stale")
    return doc


def _public(name, team) -> str | None:
    """A team's public name ("Team 13") or None for Team 3 and anything that is not a team."""
    if not (isinstance(team, str) and team[:1] == "t" and team[1:].isdigit()) or team == OURS:
        return None
    return name if isinstance(name, str) and name.strip() else team


def match_key(m: dict) -> str:
    a = m.get("action") or {}
    return f"{m.get('team')}:{m.get('card')}:{a.get('offer') or VENUE}"


def recent_matches(path: Path | None = None) -> list:
    try:
        return [k for k in json.loads((path or MISSING_STATE).read_text()).get("recent", []) if isinstance(k, str)]
    except (OSError, ValueError, AttributeError):
        return []


def remember_match(key: str, path: Path | None = None) -> None:
    path = path or MISSING_STATE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"recent": (recent_matches(path) + [key])[-MISSING_REPEAT:]}))
    except OSError:
        pass


def pick_match(doc: dict, books: dict, exclude=(), recent=(), rival_venues: bool = False):
    """The one match a post names, in the matchmaker's order (explicit live wants first): never Team 3, never a card
    in `exclude`, never one announced in the last MISSING_REPEAT posts, never a live offer that has left its venue's
    current book, and (unless rival_venues) never an offer on another team's venue, where a trade scores for that team.
    None when nothing is left."""
    skip, recent = set(exclude or ()), set(recent or ())
    live = {(v, o.get("id")) for v, book in (books or {}).items() for o in book or [] if isinstance(o, dict)}
    for m in (doc or {}).get("matches") or []:
        if not isinstance(m, dict) or _public(m.get("team_name"), m.get("team")) is None:
            continue
        if not isinstance(m.get("card"), str) or m["card"] in skip or match_key(m) in recent:
            continue
        a = m.get("action")
        if a:
            if not isinstance(a, dict) or (a.get("venue"), a.get("offer")) not in live:
                continue
            if _public(a.get("maker_name"), a.get("maker")) is None:
                continue
            if a.get("venue") not in (VENUE, "rastro", None) and not rival_venues:
                continue
        elif not isinstance((m.get("proposal") or {}).get("buyer"), dict):
            continue
        return m
    return None


def _holders_txt(m: dict, n: int = 2, dealers: bool = False) -> str:
    """"Team 6 and Team 12 hold copies (seen in public trades)." Teams only: a dealer cannot accept a team's offer.
    With dealers=True, "Abuela sells it." is added (an inferred need can be met there too)."""
    hs = [h for h in (_public(x.get("name"), x.get("team")) for x in m.get("holders") or []
                      if isinstance(x, dict) and x.get("team") != m.get("team")) if h][:n]
    out = ""
    if hs:
        who = " and ".join(hs) if len(hs) <= 2 else f"{', '.join(hs[:-1])} and {hs[-1]}"
        out = f"{who} hold{'s a copy' if len(hs) == 1 else ' copies'} (seen in public trades)."
    ds = [d.get("name") for d in (m.get("dealers") or [])[:1] if isinstance(d, dict) and d.get("name")]
    if dealers and ds:
        out = (out + " " if out else "") + f"{ds[0]} sells it."
    return out


def missing_line(m: dict, fee=(0, 0)) -> str:
    """One match in words: the live offer, the one action that completes it, and who holds the card. An inferred
    need is always said as one ("appears to be missing ... inferred from public trades, not confirmed")."""
    card = m["card"] + (f" ({m['card_name']})" if m.get("card_name") else "")
    buyer = _public(m.get("team_name"), m.get("team"))
    page = m.get("set_name") or m.get("set") or "its"
    inferred = f"{buyer} appears to be missing {m['card']} for the {page} page (inferred from public trades, not " \
               f"confirmed)"
    a = m.get("action")
    if a:
        where = "La Celestina (v20, 0 % fee)" if a["venue"] == VENUE else venue_name(a["venue"])
        until = f", open until tick {a['expires_tick']}" if isinstance(a.get("expires_tick"), int) else ""
        maker = _public(a.get("maker_name"), a.get("maker"))
        if a["side"] == "bid":
            head = f"{maker} bids {a['price']} P for {card} on {where}: offer #{a['offer']}{until}."
            act = (f"A team with a copy sells it by accepting: POST /api/offers/{a['offer']}/accept with "
                   f"{{\"assets\": [<your {m['card']} asset id>]}}.")
        elif a["side"] == "swap":
            head = f"{maker} gives {a.get('gives')} for any {card} on {where}: offer #{a['offer']}{until}."
            act = (f"A team with a copy takes it by accepting it directly (a swap is accepted, never crossed by a "
                   f"broker): POST /api/offers/{a['offer']}/accept with {{\"assets\": [<your {m['card']} asset id>]}}.")
        else:
            head = f"{maker} sells {card} for {a['price']} P on {where}: offer #{a['offer']}{until}."
            act = f"{inferred}: POST /api/offers/{a['offer']}/accept."
        bits = [head, act]
        if a["side"] != "ask":
            bits.append(_holders_txt(m))
        return " ".join(b for b in bits if b)
    pr = m["proposal"]
    price = pr.get("price") or (pr["buyer"]["post"]["give"] or {}).get("cash")
    bits = [f"{inferred}.", _holders_txt(m, dealers=True),
            f"A bid on La Celestina (v20, {fee_txt(fee)}): {json.dumps({k: v for k, v in pr['buyer']['post'].items() if k != 'expires_in_ticks'})};",
            f"a holder's ask: {{\"venue\": \"{VENUE}\", \"give\": {{\"assets\": [<your {m['card']} asset id>]}}, "
            f"\"want\": {{\"cash\": {price}}}}}.",
            "Our broker crosses a bid and an ask for the same card at the midpoint the tick they meet."]
    return " ".join(b for b in bits if b)


def missing_text(doc: dict, books: dict, exclude=(), fee=(0, 0), venue_offers=(), names: dict | None = None,
                 recent=(), rival_venues: bool = False) -> tuple:
    """The --variant missing message: ONE match (pick_match) and the one action that completes it, then v20's own live
    offers when there is room (so an event post can still name the new offer). (text, match key). LookupError when
    no match qualifies: nothing worth posting."""
    m = pick_match(doc, books, exclude, recent, rival_venues)
    if m is None:
        raise LookupError("no match to announce")
    text = "La Celestina (v20) matchmaker, public data: " + missing_line(m, fee)
    skip = set(exclude or ())
    shown = [d for o in venue_offers or [] if not refs(o) & skip for d in [describe(o, names)] if d][:SHOW_OFFERS]
    if shown:
        tail = " Live on v20 now: " + "; ".join(shown) + "."
        if len(text) + len(tail) <= MAX_CHARS:
            text += tail
    return text[:MAX_CHARS], match_key(m)


def named_outcome(events: list, t0: int, k: int, named: dict) -> dict:
    """Did the announced action happen? A settlement in (t0, t0 + k] on the named offer's venue that moves the named
    card with the offer's maker as a party (the counterparty accepted it), and any trade on v20 for that card."""
    out = {"settled": False, "settled_tick": None, "v20_trade": False}
    for e in events or []:
        t = e.get("tick") if isinstance(e, dict) else None
        if e.get("type") != "settlement" or not isinstance(t, int) or not t0 < t <= t0 + k:
            continue
        pl = e.get("payload") or {}
        refs_ = {i.get("ref") for i in pl.get("items") or [] if isinstance(i, dict)}
        if named.get("card") not in refs_ or pl.get("persona"):
            continue
        if (pl.get("venue") or "rastro") == (named.get("venue") or "rastro") and named.get("maker") in (pl.get("parties") or []):
            out.update(settled=True, settled_tick=t)
        if pl.get("venue") == VENUE:
            out["v20_trade"] = True
    return out


def variant_label(variant) -> str | int:
    return variant if variant == "missing" else int(variant) % 3


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

    def mark_posted(self, now: float, tick: int, why: str, fresh_ids=(), named: dict | None = None) -> None:
        self.posted += 1
        self.last_post, self.next_slot = now, now + self.every_s
        done = set(fresh_ids)   # only the offers this post actually advertised leave the queue
        self.queue = [o for o in self.queue if o.get("id") not in done]
        self.pending.append({"post": self.posted, "tick": tick, "why": why, "fresh": list(fresh_ids),
                             **({"named": named} if named else {})})

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
            if p.get("named"):   # --variant missing: did the one action it named happen?
                r["named_outcome"] = named_outcome(events, p["tick"], self.measure_ticks, p["named"])
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


def session_end(start: float, ticks, tick_s: float) -> float:
    """When a session's silence ends: QUIET_AFTER_S after its start (the team rule), or QUIET_TAIL_S after its last
    tick when its ticks at this pace run longer (60 s ticks: 16 ticks = 16 min)."""
    ticks = ticks if isinstance(ticks, int) and ticks > 0 else BENCH_TICKS
    return max(start + QUIET_AFTER_S, start + ticks * tick_s + QUIET_TAIL_S)


def quiet_windows(schedule: dict, clock: dict, now: float, horizon_h: float = 3.0) -> list:
    """[(start, end)] wall-clock epochs when no lane may call the API: each upcoming Market Test (schedule action
    "bench") from QUIET_BEFORE_S before its start to QUIET_AFTER_S after. A game hour is a wall hour at any tick
    length (tests/test_factory.py); on a paused clock that is the earliest the session can start, and the next read
    places it again. Only sessions within `horizon_h` game hours and before the day closes; rounded outwards."""
    try:
        t_now = float(clock["t_hours"])
    except (KeyError, TypeError, ValueError):
        return []
    try:
        tick_s = float(clock.get("tick_seconds") or 30.0)
    except (TypeError, ValueError):
        tick_s = 30.0
    out = []
    for ev in sorted((schedule or {}).get("upcoming") or [], key=lambda e: e.get("at_hours", 0)):
        at = ev.get("at_hours")
        if not isinstance(at, (int, float)) or at - t_now > horizon_h:
            continue
        if ev.get("action") == "day_closes":
            break
        if ev.get("action") == "bench":
            start = now + (at - t_now) * 3600          # in the past when the session has already begun
            end = session_end(start, (ev.get("params") or {}).get("ticks"), tick_s)
            if end > now:
                out.append((math.floor(start - QUIET_BEFORE_S), math.ceil(end)))
    return out


def active_windows(events: list, clock: dict, now: float) -> list:
    """Windows of Market Tests that have already started (the schedule lists only upcoming ones, so a restart in the
    middle of a session would miss it): every bench.started in the feed placed by its start tick. [(start, end)]."""
    try:
        tick, tick_s = int(clock["tick"]), float(clock["tick_seconds"])
    except (KeyError, TypeError, ValueError):
        return []
    out = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "bench.started":
            continue
        pl = e.get("payload") or {}
        st = pl.get("start_tick", e.get("tick"))
        if not isinstance(st, int) or st > tick:
            continue
        ticks = pl.get("ticks") if isinstance(pl.get("ticks"), int) and pl.get("ticks") > 0 else BENCH_TICKS
        start = now - (tick - st) * tick_s
        # the ticks still to run, at the clock's pace now (a pause or a slower clock only pushes the end later)
        end = max(session_end(start, ticks, tick_s), now + (st + ticks - tick) * tick_s + QUIET_TAIL_S)
        if end > now:
            out.append((math.floor(start - QUIET_BEFORE_S), math.ceil(end)))
    return out


class Silenced(Exception):
    """Raised instead of making a request inside a Market Test silence."""


class Gate:
    """Every request and every post asks the gate first (Codex BLOCKERs on #45: silence checked right before each
    request and right before posting; no post while the Market Test status is unknown or stale)."""

    def __init__(self, manual=(), clock=None):
        self.manual, self.windows, self.status_at, self.tried_at = list(manual), list(manual), None, None
        self.clock = clock or (lambda: time.time())  # looked up at call time, so a patched clock is honoured

    def quiet_end(self):
        return quiet_until(self.windows, self.clock())

    def check(self) -> None:
        if self.quiet_end() is not None:
            raise Silenced()

    def known(self) -> bool:
        return self.status_at is not None and self.clock() - self.status_at <= STATUS_MAX_AGE_S

    def due_refresh(self) -> bool:
        """Read the status again when it is 60 s from going stale, or STATUS_RETRY_S after a failed read."""
        now = self.clock()
        if self.status_at is not None and now - self.status_at < STATUS_MAX_AGE_S - 60:
            return False
        return self.tried_at is None or now - self.tried_at >= STATUS_RETRY_S

    def refresh(self, get, extra_events=()) -> bool:
        """Read the schedule, the clock and the feed (each request gated); True when the status is known again."""
        self.tried_at = self.clock()
        try:
            self.check()
            schedule = get(f"{URL}/api/schedule")
            self.check()
            clock = get(f"{URL}/api/clock")
            at_clock = self.clock()                    # the windows are placed from this instant, not later
        except Silenced:
            return False
        except Exception as e:
            print(f"Market Test status unavailable ({type(e).__name__}); no post until it is known", flush=True)
            return False
        try:  # sessions already running: the API's feed window, plus the recorded feed passed in
            self.check()
            events = get(f"{URL}/api/feed?limit=1000").get("events", [])
        except Silenced:
            return False
        except Exception as e:  # without the feed a session already running cannot be ruled out: status unknown
            print(f"Market Test status unavailable ({type(e).__name__}); no post until it is known", flush=True)
            return False
        self.windows = (self.manual + quiet_windows(schedule, clock, at_clock)
                        + active_windows(list(events) + list(extra_events), clock, at_clock))
        self.status_at = at_clock
        return True


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


_KEYLIKE = re.compile(r"(tk-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}|bk_[A-Za-z0-9_-]+|adm_[A-Za-z0-9_-]+)")  # no \b: a key
                                                                                         # glued to a word too


def clean(obj):
    """Anything that looks like a key, stripped (runlog.redact, then the same shapes even when glued to other
    characters), before it is printed or logged: an HTTP error body is the server's text and could echo a key back."""
    from runlog import redact
    obj = redact(obj)
    if isinstance(obj, str):
        return _KEYLIKE.sub("[redacted]", obj)
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


def post_announce(text: str, key: str) -> dict:
    """POST /api/broker/announce with the broker key. Returns the server's answer or {"http_error", "body"}, cleaned
    of anything that looks like a key."""
    req = urllib.request.Request(f"{URL}/api/broker/announce", method="POST", data=json.dumps({"text": text}).encode(),
                                 headers={"X-Broker-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return clean(json.load(r))
    except urllib.error.HTTPError as e:
        return clean({"http_error": e.code, "body": e.read().decode(errors="replace")[:300]})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Announce La Celestina (v20) on the feed")
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--yes", action="store_true", help="run only: really post")
    ap.add_argument("--variant", default=None, help='0, 1, 2 or "missing" (the matchmaker\'s missing-card board, '
                                                   'from --matches; default: rotate 0-2)')
    ap.add_argument("--matches", default=str(MATCHES), help="--variant missing: tools/matchmaker.py's json output")
    ap.add_argument("--rival-venues", action="store_true",
                    help="--variant missing: also name offers on other teams' venues (a trade there scores for them)")
    ap.add_argument("--no-link", action="store_true", help="leave out the web link (the default has none)")
    ap.add_argument("--link", default=LINK, help="append this link (off by default: agents do not open pages)")
    ap.add_argument("--exclude", default=",".join(MISSING),
                    help="comma list of cards never advertised (default: the cards we lack)")
    ap.add_argument("--every-min", type=float, default=0, help="run only: minutes between scheduled messages")
    ap.add_argument("--count", type=int, default=1, help="run only: how many messages at most")
    ap.add_argument("--on-event", action="store_true",
                    help="run only: also post at once when a new offer appears on v20 (never closer than --min-gap-min)")
    ap.add_argument("--min-gap-min", type=float, default=MIN_GAP_MIN, help="run: minutes between any two posts")
    ap.add_argument("--deadline-min", type=float, default=None,
                    help="run: stop after this many minutes whatever happens (default: count x every-min + 60)")
    ap.add_argument("--quiet", default="", help='run: extra silence windows today, e.g. "21:53-22:05" (Market Test '
                                                'silences from /api/schedule are always kept)')
    ap.add_argument("--key-file", default=str(KEY_FILE))
    args = ap.parse_args(argv)
    if args.variant is not None and args.variant != "missing":
        try:
            args.variant = int(args.variant)
        except ValueError:
            ap.error('--variant takes 0, 1, 2 or "missing"')
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
    gate = Gate(parse_quiet(args.quiet))

    def api(url: str) -> dict:
        """Every request of a run goes through the gate (plan mode never has windows)."""
        gate.check()
        return get_json(url)

    picked = {}   # --variant missing: the match the last compose chose (remembered only once it is posted)

    def compose(variant: int, first=()) -> tuple:
        """(text, ids of the v20 offers the text names). A failed feed read costs only the team names; a failed
        venue index only the other venues and v20's fee (taken as 0 %, 0 P; El Rastro's and v20's books are still
        read): one bad read never cancels the run. Silenced propagates: a post is never built across a silence."""
        try:
            events = api(f"{URL}/api/feed?limit=1000").get("events", [])
        except Silenced:
            raise
        except Exception as e:
            print(f"feed unavailable ({type(e).__name__}); no team names in this message", flush=True)
            events = []
        try:
            index = [v for v in api(f"{URL}/api/venues").get("venues", []) if isinstance(v, dict)]
        except Silenced:
            raise
        except Exception as e:
            print(f"venue index unavailable ({type(e).__name__}); El Rastro and v20 only", flush=True)
            index = []
        venues = [v.get("venue") for v in index if v.get("status") == "open" and v.get("venue")]
        ours = next((v for v in index if v.get("venue") == VENUE), {})
        fee = (ours.get("fee_bps") or 0, ours.get("fee_per_card") or 0)
        books = market_books(api, venues + [VENUE])
        offers = [o for v, book in books.items() if v != VENUE for o in book]
        names = learn_pseudonyms(books, {**offer_makers(recorded_events()), **offer_makers(events)})
        if team is not None:  # our own open offers, for sure: never paired, never named as anyone else's
            try:
                gate.check()
                names.update({i: OURS for i in our_offer_ids(team.my_offers())})
            except Silenced:
                raise
            except Exception as e:
                print(f"our offers unavailable ({type(e).__name__}); feed names and pseudonyms only", flush=True)
        firsts = {o.get("id") for o in first}
        v20 = sorted(books.get(VENUE, []), key=lambda o: o.get("id") not in firsts)  # the new offer leads
        if variant == "missing":   # the matchmaker's output, read as it is; LookupError = nothing fresh to post
            doc = load_matches(Path(args.matches))
            text, key = missing_text(doc, books, exclude, fee, v20, names, recent_matches(), args.rival_venues)
            m = next(x for x in doc.get("matches") or [] if isinstance(x, dict) and match_key(x) == key)
            a = m.get("action") or {}
            picked.update(key=key, named={"card": m.get("card"), "offer": a.get("offer"), "venue": a.get("venue") or VENUE,
                                          "maker": a.get("maker") or m.get("team"), "tier": m.get("tier")})
        else:
            text = build_text(offers, variant, link, exclude, v20, names, fee, firsts)
        return text, [o.get("id") for o in v20 if o.get("id") is not None and f"(offer {o.get('id')})" in text]

    if args.cmd == "plan":
        variant = args.variant if args.variant is not None else next_variant()
        try:
            text, _ = compose(variant)
        except LookupError as e:
            print(f"variant {variant_label(variant)}: nothing to post ({e})")
            return
        print(f"variant {variant_label(variant)}, {len(text)} chars:\n{text}")
        print(f"\nwould POST {URL}/api/broker/announce {json.dumps({'text': text}, ensure_ascii=False)[:120]}...")
        return

    skip = set(exclude)
    ann = Announcer(max(1, args.count), max(60.0, args.every_min * 60), args.on_event, args.min_gap_min * 60,
                    eligible=lambda o: describe(o) is not None and not refs(o) & skip)
    minutes = args.deadline_min if args.deadline_min is not None else max(1, args.count) * max(1.0, args.every_min) + 60
    deadline = time.time() + minutes * 60
    while ann.posted < ann.count or ann.pending:
        if time.time() >= deadline:  # a feed or status outage must not keep the process alive for ever
            for p in ann.pending:
                log.event("response_unavailable", reason="deadline", **p)
            print(f"[{time.strftime('%H:%M:%S')}] deadline reached: {ann.posted}/{ann.count} posts", flush=True)
            break
        end = gate.quiet_end()
        if end is not None:  # Market Test silence: no request at all until it ends
            print(f"[{time.strftime('%H:%M:%S')}] silence until {time.strftime('%H:%M:%S', time.localtime(end))}",
                  flush=True)
            log.event("silence", until=round(end, 1))
            time.sleep(max(1.0, min(end, deadline) - time.time()))
            continue
        if gate.due_refresh():
            gate.refresh(get_json, recorded_events(kinds=("bench.started",)))
            continue                                   # start again from the silence check with what was learnt
        if not gate.known():                           # status unknown: no request but the status read, no post
            time.sleep(POLL_S)
            continue
        try:
            tick = api(f"{URL}/api/clock").get("tick")
            v20 = api(f"{URL}/api/venues/{VENUE}/offers").get("offers") or []
        except Silenced:
            continue
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
            try:
                text, advertised = compose(variant, fresh if why == "event" else ())
                if why == "event" and not set(advertised) & {o.get("id") for o in fresh}:
                    raise LookupError("the new offer could not be verified on v20's book")
                gate.check()                           # right before the post, after every slow read
                if not gate.known():
                    raise LookupError("Market Test status went stale while composing")
            except Silenced:
                continue                               # the queue is kept: the event goes out after the silence
            except LookupError as e:
                print(f"[{time.strftime('%H:%M:%S')}] {why} post deferred: {e}", flush=True)
                log.event("deferred", why=why, reason=str(e), fresh=[o.get("id") for o in fresh])
                time.sleep(POLL_S)
                continue
            res = post_announce(text, key)
            print(clean(f"[{time.strftime('%H:%M:%S')}] {why} post {ann.posted + 1}/{ann.count} variant {variant_label(variant)} "
                        f"-> {json.dumps(res, ensure_ascii=False)[:200]}\n{text}"), flush=True)
            log.event("announce", why=why, variant=variant_label(variant), chars=len(text), text=text, result=clean(res),
                      tick=tick, fresh=[o.get("id") for o in fresh], advertised=advertised)
            if "http_error" in res:
                break
            done = [i for i in advertised if i in {o.get("id") for o in fresh}]
            named = picked.get("named") if variant == "missing" else None
            ann.mark_posted(time.time(), tick if isinstance(tick, int) else 0, why, done, named)
            if variant == "missing" and picked.get("key"):
                remember_match(picked["key"])
                log.event("named", key=picked["key"], **(named or {}))
            if why != "event" and variant != "missing":
                save_variant(variant + 1)
        if ann.pending and isinstance(tick, int) and any(tick >= p["tick"] + ann.measure_ticks for p in ann.pending):
            try:
                events = api(f"{URL}/api/feed?limit=1000").get("events", [])
                for r in ann.responses(tick, events, v20_ids={o.get("id") for o in v20 if isinstance(o, dict)}):
                    print(clean(f"[{time.strftime('%H:%M:%S')}] response {json.dumps(r)}"), flush=True)
                    log.event("response", **r)
            except Silenced:
                continue
            except Exception as e:
                print(f"feed read failed ({type(e).__name__})", flush=True)
                for p in ann.give_up(tick):
                    log.event("response_unavailable", **p)
        time.sleep(POLL_S)
    log.end()


if __name__ == "__main__":
    main()
