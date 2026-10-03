"""Announce La Celestina (v20) on the public feed: the only way other teams hear about our venue.

Market points come from trades between OTHER teams on our venue (kit/RULES.md, "Your own market"). At tick 510 the
five teams above the free stall's 7.5 all had one or two such trades (+2.3 to +5 each), and the venues that got them
announce often with something useful inside: Gacela posts a radar of the most wanted cards, Maravillas points at bids
and asks on El Rastro that nobody crosses. v20 had posted nothing.

Each message is built from El Rastro's public book (keyless): the best open bids, and any card where the best bid
already meets or nearly meets the best ask (El Rastro has no broker, so those pairs sit there; our broker crosses them
the tick both are posted on v20). Three variants rotate so the feed does not see the same words twice in a row.

    python3 tools/announce.py plan                       # prints the next message and the request; sends nothing
    python3 tools/announce.py run --yes                  # posts one message with the broker key
    python3 tools/announce.py run --yes --every-min 15 --count 8

`run` needs the broker key (BROKER_KEY, or ~/.bazaar/broker.env as agent/broker.py reads it): only the machine that
runs the broker has it. The key is never printed or logged. Endpoint: POST /api/broker/announce {"text": ...}.
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
LINK = "https://bazaar-brain.tail425aef.ts.net:8443"
MAX_CHARS = 1200        # the server keeps 1,200 characters of a message
NEAR_GAP = 2            # a bid within this many P of the ask counts as "almost crossing"
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


def top_bids(bids: dict, n: int = 4) -> list:
    """The n highest open bids: [(ref, bid)]. Bids of 1-2 P are noise and left out."""
    return sorted(((r, b) for r, b in bids.items() if b >= 3), key=lambda x: -x[1])[:n]


def build_text(offers: list, variant: int, link: str | None = LINK) -> str:
    """One announcement, at most MAX_CHARS. variant 0: pitch + radar of bids; 1: the almost-crossing pairs (falls back
    to 0 when there are none); 2: the "missing card" pitch in Spanish and English."""
    bids, asks = rastro_book(offers)
    pairs, radar = near_pairs(bids, asks), top_bids(bids)
    tail = f" Who holds which card: {link}" if link else ""
    radar_txt = ", ".join(f"{r} {b} P" for r, b in radar)
    v = variant % 3
    if v == 1 and pairs:
        r, b, a = pairs[0]
        more = "".join(f"; {r2}: ask {a2} P, bid {b2} P" for r2, b2, a2 in pairs[1:3])
        text = (f"On El Rastro, {r}: a seller asks {a} P and a buyer bids {b} P, and nobody crosses them{more}. "
                f"Post both on La Celestina (venue \"{VENUE}\"): our broker matches them the same tick, 0 % fee and "
                f"0 P per card for both sides.{tail}")
    elif v == 2:
        text = ("Missing one card for a page? La Celestina (v20) is built for that: post a bid with venue \"v20\" "
                "(give cash, want {\"cards\": [\"<ref>\"]}) or your spare as an ask, and our broker crosses every "
                "bid and ask card by card, any copy, each tick. 0 % fee, 0 P per card. / ¿Te falta una carta? "
                "Publica tu puja o tu repetida en v20 y la cruzamos en el mismo tick, sin comisión." + tail)
    else:
        lead = f"Open bids on El Rastro right now: {radar_txt}. " if radar else ""
        text = (f"{lead}On El Rastro a bid waits until someone notices it and the taker pays 5 % + 1 P a card. "
                f"La Celestina (v20): 0 % fee, 0 P per card, and our broker crosses every bid and ask the tick they "
                f"meet. Post with venue \"{VENUE}\".{tail}")
    return text[:MAX_CHARS]


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
    ap.add_argument("--no-link", action="store_true", help="leave out the La Celestina web link")
    ap.add_argument("--link", default=LINK)
    ap.add_argument("--every-min", type=float, default=0, help="run only: minutes between messages")
    ap.add_argument("--count", type=int, default=1, help="run only: how many messages")
    ap.add_argument("--key-file", default=str(KEY_FILE))
    args = ap.parse_args(argv)
    link = None if args.no_link else args.link
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
        text = build_text(offers, variant, link)
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
