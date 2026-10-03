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
cancelled or expired is advertised; the feed (GET /api/feed?limit=1000) only names who posted each one. Swaps are
advertised as taken by accepting them (POST /api/offers/<id>/accept): our broker crosses cash asks and bids only.
`plan` is keyless. `run` posts with the broker key (BROKER_KEY, or ~/.bazaar/broker.env as agent/broker.py reads it):
only the machine that runs the broker has it. The key is never printed or logged. POST /api/broker/announce.
"""
from __future__ import annotations

import argparse
import json
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


def take_order(o: dict) -> str | None:
    """The order that meets a plain v20 ask or bid on the other side, as RULES.md writes it; None otherwise."""
    sh = shape(o)
    if sh is None or sh[0] == "swap":
        return None
    kind, ref, price = sh
    if kind == "ask":
        return f'{{"venue": "{VENUE}", "give": {{"cash": {price}}}, "want": {{"cards": ["{ref}"]}}}}'
    return f'{{"venue": "{VENUE}", "give": {{"assets": [<your {ref}>]}}, "want": {{"cash": {price}}}}}'


def venue_name(v) -> str:
    return "El Rastro" if v in (None, "rastro") else str(v)


def market_sides(offers: list) -> tuple[dict, dict]:
    """Best bid and ask per card across the offers given (El Rastro's book plus other venues' live offers), with the
    offer id and venue: ({ref: (bid, id, venue)}, {ref: (ask, id, venue)}). Only plain asks and bids (shape); offers
    on our venue and offers to one team are left out."""
    bids, asks = {}, {}
    for o in offers or []:
        if not isinstance(o, dict) or o.get("status", "open") != "open" or o.get("to") or o.get("venue") == VENUE:
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
    bids, asks = market_sides(offers)
    out = []
    for r, b in bids.items():
        a = asks.get(r)
        if a is None or r in skip or a[0] - b[0] > NEAR_GAP:
            continue
        nb, na = names.get(b[1]), names.get(a[1])
        if nb is not None and nb == na:
            continue
        out.append((r, b, a))
    return sorted(out, key=lambda x: (x[2][0] - x[1][0], -x[1][0]))


def build_text(offers: list, variant: int, link: str | None = LINK, exclude=MISSING, venue_offers=(),
               names: dict | None = None) -> str:
    """One announcement, at most MAX_CHARS. `offers`: open offers off our venue (El Rastro's book, other venues' live
    offers); `venue_offers`: v20's live offers; `names`: {offer id: team} from the feed. variant 0: v20's book first;
    1: the crossable pairs first; 2: the "missing card" pitch in Spanish and English, then v20's book. Cards in
    `exclude` never appear."""
    skip = set(exclude or ())
    names = names or {}
    live = [o for o in venue_offers or [] if not refs(o) & skip]
    shown = [(o, d) for o in live for d in [describe(o, names)] if d][:SHOW_OFFERS]
    book = ""
    if shown:
        first = shown[0][0]
        order = next((take_order(o) for o, _ in shown if crossable(o) and take_order(o)), None)
        book = (f"Live on La Celestina ({VENUE}) now: " + "; ".join(d for _, d in shown) + ". "
                + f"Take one directly: POST /api/offers/{first.get('id', '<id>')}/accept (any offer id above). "
                + (f"Or post the other side of a cash offer on venue \"{VENUE}\", e.g. {order}, and our broker "
                   f"crosses it the same tick. " if order else "")
                + "0 % fee, 0 P per card. ")
    pairs = near_market_pairs(offers, names, skip)

    def who(oid, fallback):
        w = names.get(oid)
        return w if w and w != OURS else fallback

    def pair_txt(r, b, a):
        return (f"{r}: {who(a[1], 'a seller')} asks {a[0]} P on {venue_name(a[2])} (offer {a[1]}), "
                f"{who(b[1], 'a buyer')} bids {b[0]} P on {venue_name(b[2])} (offer {b[1]})")

    pairs_txt = ""
    if pairs:
        pairs_txt = ("Buyer and seller a few P apart, nobody crossing them: "
                     + "; ".join(pair_txt(*p) for p in pairs[:3])
                     + f". Post both sides on venue \"{VENUE}\": no fee (El Rastro's taker pays 5 % + 1 P a card), "
                       f"and our broker matches them at the midpoint the tick they meet. ")
    pitch = (f"La Celestina ({VENUE}): 0 % fee, 0 P per card; our broker crosses every bid and ask card by card, any "
             f"copy, the tick they meet.")
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
    ap.add_argument("--every-min", type=float, default=0, help="run only: minutes between messages")
    ap.add_argument("--count", type=int, default=1, help="run only: how many messages")
    ap.add_argument("--key-file", default=str(KEY_FILE))
    args = ap.parse_args(argv)
    link = None if args.no_link else args.link
    exclude = tuple(x.strip() for x in args.exclude.split(",") if x.strip())
    if args.cmd == "run" and not args.yes:
        ap.error("run posts on the public feed: add --yes")
    key = None
    if args.cmd == "run":
        from broker import load_broker_key  # same key source as agent/broker.py
        key = load_broker_key(Path(args.key_file))
        from runlog import RunLog
        log = RunLog("announce")
        log.start(plan={"count": args.count, "every_min": args.every_min, "link": bool(link)})
    for i in range(max(1, args.count) if args.cmd == "run" else 1):
        if i:
            time.sleep(max(60.0, args.every_min * 60))
        variant = args.variant if args.variant is not None else next_variant()
        events = get_json(f"{URL}/api/feed?limit=1000").get("events", [])
        venues = [v.get("venue") for v in get_json(f"{URL}/api/venues").get("venues", [])
                  if isinstance(v, dict) and v.get("status") == "open" and v.get("venue")]
        books = market_books(get_json, venues + [VENUE])
        offers = [o for v, book in books.items() if v != VENUE for o in book]
        text = build_text(offers, variant, link, exclude, books.get(VENUE, []), offer_makers(events))
        print(f"variant {variant % 3}, {len(text)} chars:\n{text}")
        if args.cmd == "plan":
            print(f"\nwould POST {URL}/api/broker/announce {json.dumps({'text': text}, ensure_ascii=False)[:120]}...")
            return
        res = post_announce(text, key)
        print("->", json.dumps(res, ensure_ascii=False)[:300])
        log.event("announce", variant=variant % 3, chars=len(text), text=text, result=res)
        if "http_error" in res:
            break
        save_variant(variant + 1)
    log.end()


if __name__ == "__main__":
    main()
