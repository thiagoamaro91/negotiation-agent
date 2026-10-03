"""Announce La Celestina (v20) on the public feed: the only way other teams hear about our venue.

Market points come from trades between OTHER teams on our venue (kit/RULES.md, "Your own market"): each one added
+1.3 to +2 to the free stalls that got one (t17, t07, t14 on Saturday). v20 had none by 19:00 on Saturday, although
t15 listed 16 asks on it at ticks 384-395: nobody heard of them, and t12 bought two of those very cards from t15 on
t14's and t17's free stalls half an hour later. Our messages at the time led with El Rastro's open bids, which sends
sellers to El Rastro.

So a message now sells what is on v20 and what v20 would cross, all inside the text (other teams' agents read the feed;
they do not open web pages):
  - the live offers on v20, with the team that posted them (public: the feed's offer.listed names every maker), the
    price, the offer id, and the exact order that takes it;
  - El Rastro pairs a broker would cross, ask at or just above the bid (NEAR_GAP), with both teams and offer ids:
    El Rastro has no broker and its taker pays 5 % + 1 P, so those pairs sit there; on v20 they meet at the midpoint;
  - a short pitch.
Three variants rotate the order so the feed does not see the same words twice in a row. Only public facts, no asks in
return. Cards we are missing ourselves never appear (--exclude): pointing their sellers at v20, where we cannot buy,
works against us. Offers addressed to one team (to: tXX) are left out: nobody else can take them.

    python3 tools/announce.py plan                       # prints the next message and the request; sends nothing
    python3 tools/announce.py run --yes                  # posts one message with the broker key
    python3 tools/announce.py run --yes --every-min 12 --count 40

`plan` is keyless: v20's live offers come from the public feed (listed, minus cancelled, expired or settled). `run`
reads them from our broker's book instead (authoritative) and needs the broker key (BROKER_KEY, or ~/.bazaar/broker.env
as agent/broker.py reads it): only the machine that runs the broker has it. The key is never printed or logged.
Endpoints: GET /api/feed?limit=1000, GET /api/venues/rastro/offers, GET /api/broker/book, POST /api/broker/announce.
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


def rastro_book(offers: list) -> tuple[dict, dict]:
    """Best bid and best ask per card on El Rastro: ({ref: bid}, {ref: ask}). A bid gives cash and wants a card (any
    copy or a named asset); an ask gives exactly one card and wants cash. Swaps and bundles are skipped."""
    bids, asks = {}, {}
    for o in offers or []:
        if not isinstance(o, dict) or o.get("status", "open") != "open":
            continue
        g, w = o.get("give") or {}, o.get("want") or {}
        wanted = [t.split(":", 1)[1] for t in w.get("types") or [] if str(t).startswith("card:")]
        wanted += [a.get("ref") for a in w.get("assets") or [] if a.get("ref")]
        if g.get("cash") and not g.get("assets") and len(wanted) == 1 and not w.get("cash"):
            ref = wanted[0]
            bids[ref] = max(bids.get(ref, 0), int(g["cash"]))
        elif len(g.get("assets") or []) == 1 and w.get("cash") and not wanted and not g.get("cash"):
            ref = g["assets"][0].get("ref")
            if ref:
                asks[ref] = min(asks.get(ref, 10**9), int(w["cash"]))
    return bids, asks


def near_pairs(bids: dict, asks: dict, gap: int = NEAR_GAP) -> list:
    """Cards whose best bid is within `gap` P of the best ask, closest first: [(ref, bid, ask)]."""
    out = [(r, bids[r], asks[r]) for r in bids if r in asks and asks[r] - bids[r] <= gap]
    return sorted(out, key=lambda x: (x[2] - x[1], -x[1]))


def _wanted(o: dict) -> list:
    w = o.get("want") or {}
    refs = [t.split(":", 1)[1] for t in w.get("types") or [] if str(t).startswith("card:")]
    return refs + [x.get("ref") for x in w.get("assets") or [] if isinstance(x, dict) and x.get("ref")]


def _given(o: dict) -> list:
    return [x.get("ref") for x in (o.get("give") or {}).get("assets") or [] if isinstance(x, dict) and x.get("ref")]


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


def live_on_venue(events: list, venue: str = VENUE, tick=None) -> list:
    """Offers listed on `venue` in the feed window that are still open: not cancelled, not expired at `tick` (default:
    the newest tick seen), and, for an ask, its card not moved by a later settlement. Keyless, so a little stale; run
    mode reads the broker's book instead."""
    listed, gone, moved, last = {}, set(), set(), 0
    for e in events or []:
        if not isinstance(e, dict):
            continue
        last = max(last, e.get("tick") or 0)
        pl = e.get("payload") or {}
        if e.get("type") == "offer.listed" and (pl.get("offer") or {}).get("venue") == venue:
            listed[pl["offer"].get("id")] = pl["offer"]
        elif e.get("type") == "offer.cancelled":
            gone.add(pl.get("offer"))
        elif e.get("type") == "settlement":
            moved.update(i.get("id") for i in pl.get("items") or [] if isinstance(i, dict))
    tick = last if tick is None else tick
    out = []
    for oid, o in listed.items():
        exp = o.get("expires_tick")
        assets = {x.get("id") for x in (o.get("give") or {}).get("assets") or [] if isinstance(x, dict)}
        if oid in gone or (isinstance(exp, int) and exp < tick) or assets & moved or o.get("status", "open") != "open":
            continue
        out.append(o)
    return out


def other_venues(events: list) -> list:
    """Live offers on every team venue but ours, from the feed window (live_on_venue per venue)."""
    venues = {((e.get("payload") or {}).get("offer") or {}).get("venue") for e in events or []
              if isinstance(e, dict) and e.get("type") == "offer.listed"}
    return [o for v in sorted(x for x in venues if x and x not in ("rastro", VENUE)) for o in live_on_venue(events, v)]


def describe(o: dict, names: dict | None = None) -> str | None:
    """One offer in a few words: "t15 sells LAT-07 for 26 P (offer 9123)". None for shapes we do not advertise
    (bundles, offers to one team, our own)."""
    if not isinstance(o, dict) or o.get("to"):
        return None
    who = (names or {}).get(o.get("id")) or o.get("maker") or ""
    if who == OURS:
        return None
    who = who if isinstance(who, str) and who[:1] == "t" and who[1:].isdigit() else "a team"
    g, w = o.get("give") or {}, o.get("want") or {}
    given, wanted = _given(o), _wanted(o)
    oid = f" (offer {o['id']})" if o.get("id") is not None else ""
    if len(given) == 1 and w.get("cash") and not wanted and not g.get("cash"):
        return f"{who} sells {given[0]} for {int(w['cash'])} P{oid}"
    if g.get("cash") and not given and len(wanted) == 1 and not w.get("cash"):
        return f"{who} buys {wanted[0]} for {int(g['cash'])} P{oid}"
    if len(given) == 1 and len(wanted) == 1 and not g.get("cash") and not w.get("cash"):
        return f"{who} swaps {given[0]} for any {wanted[0]}{oid}"
    return None


def take_order(o: dict) -> str | None:
    """The order that takes a live v20 offer, as RULES.md writes it."""
    g, w = o.get("give") or {}, o.get("want") or {}
    given, wanted = _given(o), _wanted(o)
    if len(given) == 1 and w.get("cash"):
        return (f'{{"venue": "{VENUE}", "give": {{"cash": {int(w["cash"])}}}, '
                f'"want": {{"cards": ["{given[0]}"]}}}}')
    if g.get("cash") and len(wanted) == 1:
        return f'{{"venue": "{VENUE}", "give": {{"assets": [<your {wanted[0]}>]}}, "want": {{"cash": {int(g["cash"])}}}}}'
    return None


def venue_name(v) -> str:
    return "El Rastro" if v in (None, "rastro") else str(v)


def market_sides(offers: list) -> tuple[dict, dict]:
    """Best bid and ask per card across the offers given (El Rastro's book plus other venues' live offers), with the
    offer id and venue: ({ref: (bid, id, venue)}, {ref: (ask, id, venue)}). Offers on our venue and offers to one team
    are left out."""
    bids, asks = {}, {}
    for o in offers or []:
        if not isinstance(o, dict) or o.get("status", "open") != "open" or o.get("to") or o.get("venue") == VENUE:
            continue
        g, w = o.get("give") or {}, o.get("want") or {}
        given, wanted = _given(o), _wanted(o)
        v = o.get("venue") or "rastro"
        if g.get("cash") and not given and len(wanted) == 1 and not w.get("cash"):
            if int(g["cash"]) > bids.get(wanted[0], (0,))[0]:
                bids[wanted[0]] = (int(g["cash"]), o.get("id"), v)
        elif len(given) == 1 and w.get("cash") and not wanted and not g.get("cash"):
            if int(w["cash"]) < asks.get(given[0], (10**9,))[0]:
                asks[given[0]] = (int(w["cash"]), o.get("id"), v)
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
    live = [o for o in venue_offers or [] if not (set(_given(o)) | set(_wanted(o))) & skip]
    shown = [(o, d) for o in live for d in [describe(o, names)] if d][:SHOW_OFFERS]
    book = ""
    if shown:
        order = next((take_order(o) for o, _ in shown if take_order(o)), None)
        book = (f"Live on La Celestina ({VENUE}) now: " + "; ".join(d for _, d in shown) + ". "
                + (f"To take one, post the other side on venue \"{VENUE}\", e.g. {order}: " if order else
                   f"Post the other side on venue \"{VENUE}\": ")
                + "our broker crosses it the same tick, 0 % fee, 0 P per card. ")
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
        offers = get_json(f"{URL}/api/venues/rastro/offers").get("offers", [])
        events = get_json(f"{URL}/api/feed?limit=1000").get("events", [])
        offers = [dict(o, venue="rastro") for o in offers] + other_venues(events)
        venue_offers = live_on_venue(events)
        if key:  # run: the broker's own book is the truth about what is live on v20
            try:
                from bazaar_sdk import Broker
                venue_offers = Broker(URL, key, timeout=10, retries=1).book().get("offers") or []
            except Exception as e:  # the feed's view is a fine fallback for one message
                print(f"broker book unavailable ({type(e).__name__}); using the feed", flush=True)
        text = build_text(offers, variant, link, exclude, venue_offers, offer_makers(events))
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
