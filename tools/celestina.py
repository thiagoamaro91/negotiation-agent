"""La Celestina: Team 3's matchmaker for the cards. Keyless, public data only.

Every team runs a 0 % fee venue now and they all pitch the same thing; the game has dozens of open offers and no pair
that crosses. The real trades are between a team that holds a spare it never listed and a team that lacks that card.
La Celestina reads every venue's public book, the public feed and the leaderboard, and works out, for every card:
every offer on every venue, the best ask and bid across the market, who is known to hold it (from public trades), what
it traded for, and the matches waiting to happen (crossing orders stranded on different venues, a bid next to a known
spare, mirror swaps).

The holder map is Team 3's edge, so the output has two sides:
- PRIVATE (Team 3 only): everything, including who is known to hold which copies, the matches built on that (a bid
  next to a known spare) and drafted announcements for our broker. Served only by a second server bound to
  127.0.0.1 (--private-port), or printed by `once`. Never expose that port (no tunnel, no funnel).
- PUBLIC (what other teams see): open offers are public in every venue's book anyway, so it shows them per card and
  per team, each with its source and a "is this price fair?" verdict against the card's recent public trades, the
  matches built from open offers alone (crossing, near misses, mirror swaps), each with a ready-to-post order for our
  venue, our venue's own book, the pitch and our Market Test results. public_view() builds it from the private
  snapshot by whitelisting fields: the holder map never leaves.

    python3 tools/celestina.py serve --port 8795                  # public page on /, JSON on /api/celestina.json
                                                                  # private page + JSON on 127.0.0.1:8796
    python3 tools/celestina.py once                               # one live snapshot, a short private summary
    python3 tools/celestina.py once --json [--public]             # the private (or public) snapshot as JSON

Keyless by design: GET requests to public endpoints only, no team key and none of Team 3's private values; it never
sends anything to the game. Every string that comes from the game (offer, card and venue names, announcements) is
data: the page escapes it and nothing here acts on it.

Who is behind an offer. Venue books show one pseudonym per team and venue ("ma55bf699"); the public feed's offer.listed
event names the real team for the same offer id. In order: the offer's own listing in the feed ("listing"), another
offer by the same pseudonym that is attributed ("pseudonym", learnt from every book seen, recorded ones included), and
for a card on sale, the team its asset was last seen going to in a public settlement or pack reveal ("asset trail").
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = "https://bazaar.causaprima.ai/api/"
ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "celestina.html"
DEFAULT_FEED = ROOT / "logs" / "feed" / "feed.jsonl"
US = "t03"
SIGNATURE = "La Celestina · {vid} · Team 3"
PITCH = "Post your wants and spares on {vid}; we find the other side and our broker matches every tick. 0% fee."
FEED_LIMIT = 1000          # the server answers its newest window whatever the limit; dedupe by id
MIN_GAP = 0.05             # at least this long between two reads: at most 20 per second, a third of the keyless limit
INTERVAL = 15.0            # one refresh (about 25 reads) every 15 s
CATALOG_EVERY = 20         # re-read the catalog every 20 refreshes (a set release adds cards)
RECENT_N = 8               # recent prices kept per card
REF_N = 5                  # reference price = median of the last 5
PER_BID = 3                # near misses / spare holders listed per bid
NEAR_RATIO = 0.5           # a near miss: the bid is at least half the ask (a 1 P bid next to a 9 P ask is not near)
MAX_MATCHES = 80
ANNOUNCE_MAX = 280
ORDER_TICKS = 120          # expiry of the ready-to-post orders we suggest
RATE = (20.0, 60.0)        # per client address: 20 requests a second, bursts of 60
TEAM_RE = re.compile(r"^t\d+$")
VENUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
REF_RE = re.compile(r"^[A-Z]{2,5}-\d{1,3}$")
KEEP_TYPES = {"offer.listed", "offer.cancelled", "settlement", "gift.given", "pack.opened", "team.joined",
              "venue.opened", "venue.closed", "venue.announcement"}
TIERS = {"cross": 4, "mirror": 3, "near": 2, "spare": 1, "holder": 0}
PUBLIC_MATCHES = ("cross", "mirror", "near")  # built from open offers alone; spare and holder use the holder map
# Our Market Test efficiency per test next to the stall's: filled in by hand (or --market-test FILE) as results come.
MARKET_TEST = [
    {"test": "Market Test 1", "ours": None, "stall": None, "note": "pending"},
    {"test": "Market Test 2", "ours": None, "stall": None, "note": "pending"},
]


# ---------------------------------------------------------------- offers: shape and who is behind them

def num(x) -> float:
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e9 else 0


def card_types(side: dict) -> list:
    return [t.split(":", 1)[1] for t in side.get("types") or [] if isinstance(t, str) and t.startswith("card:")]


def shape(o: dict) -> dict:
    """What an offer is: ask (one card for cash), bid (cash for one card type), swap (one card for one card type) or
    other (bundles, packs, anything else), with the card(s) and the price."""
    give, want = o.get("give") or {}, o.get("want") or {}
    gives = [a for a in give.get("assets") or [] if isinstance(a, dict)]
    cards = [a.get("ref") for a in gives if a.get("kind", "card") == "card" and isinstance(a.get("ref"), str)]
    wants = card_types(want)
    gcash, wcash = num(give.get("cash")), num(want.get("cash"))
    plain = not give.get("types") and not want.get("assets")
    if plain and len(gives) == 1 and len(cards) == 1 and not gcash and wcash > 0 and not wants:
        return {"kind": "ask", "ref": cards[0], "price": wcash, "want_ref": None}
    if plain and not gives and gcash > 0 and len(wants) == 1 and not wcash:
        return {"kind": "bid", "ref": wants[0], "price": gcash, "want_ref": None}
    if plain and len(gives) == 1 and len(cards) == 1 and not gcash and not wcash and len(wants) == 1:
        return {"kind": "swap", "ref": cards[0], "price": None, "want_ref": wants[0]}
    a = " + ".join(cards + ([f"{gcash:g} P"] if gcash else [])) or "nothing"
    b = " + ".join(wants + ([f"{wcash:g} P"] if wcash else [])) or "nothing"
    return {"kind": "other", "ref": None, "price": None, "want_ref": None, "refs": sorted(set(cards + wants)),
            "summary": f"gives {a} for {b}"}


def offer_teams(events: list) -> dict:
    """offer id -> team, from the feed's offer.listed events (the actor is the real team behind the pseudonym)."""
    out = {}
    for e in events:
        if e.get("type") != "offer.listed":
            continue
        o = (e.get("payload") or {}).get("offer") or {}
        who = e.get("actor") if isinstance(e.get("actor"), str) and TEAM_RE.match(e["actor"]) else o.get("maker")
        if isinstance(o.get("id"), int) and isinstance(who, str) and TEAM_RE.match(who):
            out[o["id"]] = who
    return out


def learn_pseudonyms(offers, offer_team: dict, sets: dict | None = None) -> dict:
    """pseudonym -> set of teams seen behind it (an offer id the feed attributes, under that pseudonym). Pass the
    previous result as `sets` to keep learning across refreshes."""
    sets = sets if sets is not None else {}
    for o in offers:
        if not isinstance(o, dict):
            continue
        team, maker = offer_team.get(o.get("id")), o.get("maker")
        if team and isinstance(maker, str) and not TEAM_RE.match(maker):
            sets.setdefault(maker, set()).add(team)
    return sets


def resolve(sets: dict) -> dict:
    """pseudonym -> team, only where every attributed offer agrees (a pseudonym is one team on one venue)."""
    return {p: next(iter(ts)) for p, ts in sets.items() if len(ts) == 1}


def asset_owners(events: list) -> dict:
    """asset id -> the party it last went to in public: settlements (team or dealer) and pack reveals (the best card)."""
    owner = {}
    for e in sorted(events, key=lambda e: e.get("id") or 0):
        p = e.get("payload") or {}
        if e.get("type") == "settlement":
            for i in p.get("items") or []:
                if isinstance(i, dict) and isinstance(i.get("id"), int) and isinstance(i.get("to"), str):
                    owner[i["id"]] = i["to"]
        elif e.get("type") == "pack.opened" and isinstance(p.get("best"), dict) and isinstance(p.get("team"), str):
            if isinstance(p["best"].get("id"), int):
                owner[p["best"]["id"]] = p["team"]
    return owner


def attribute(o: dict, offer_team: dict, pseudo: dict, owners: dict) -> tuple:
    """(team or None, how): listing, pseudonym, asset trail, or unknown."""
    maker = o.get("maker")
    if isinstance(maker, str) and TEAM_RE.match(maker):
        return maker, "listing"
    if o.get("id") in offer_team:
        return offer_team[o["id"]], "listing"
    if maker in pseudo:
        return pseudo[maker], "pseudonym"
    assets = [a for a in (o.get("give") or {}).get("assets") or [] if isinstance(a, dict)]
    trail = {owners.get(a.get("id")) for a in assets}
    if assets and len(trail) == 1:
        t = next(iter(trail))
        if isinstance(t, str) and TEAM_RE.match(t):
            return t, "asset trail"
    return None, "unknown"


# ---------------------------------------------------------------- the consolidated book

def venue_rows(body) -> list:
    rows = body.get("venues") if isinstance(body, dict) else body
    out = []
    for v in rows if isinstance(rows, list) else []:
        if isinstance(v, dict) and isinstance(v.get("venue"), str) and VENUE_ID.match(v["venue"]):
            out.append({"venue": v["venue"], "name": str(v.get("name") or v["venue"]), "owner": v.get("owner"),
                        "owner_name": v.get("owner_name"), "status": v.get("status"), "fee_bps": v.get("fee_bps"),
                        "fee_per_card": v.get("fee_per_card"), "starter": bool(v.get("starter")),
                        "house": bool(v.get("house")), "trades": v.get("trades"),
                        "mechanism": (v.get("rules") or {}).get("mechanism") or ("house" if v.get("house") else None)})
    return out


def our_venue(venues: list) -> dict | None:
    """Team 3's own (non-starter) venue, the newest if there are several; None until it opens."""
    mine = [v for v in venues if v["owner"] == US and not v["starter"] and v["status"] == "open"]
    return sorted(mine, key=lambda v: v["venue"])[-1] if mine else None


def consolidate(venues: list, books: dict, offer_team: dict, pseudo: dict, owners: dict) -> list:
    """Every open offer on every venue, one row each: shape, price, venue, maker pseudonym and the team behind it."""
    meta = {v["venue"]: v for v in venues}
    rows = []
    for vid, offers in books.items():
        v = meta.get(vid, {"name": vid, "owner": None, "fee_bps": None, "fee_per_card": None})
        for o in offers or []:
            if not isinstance(o, dict) or not isinstance(o.get("id"), int) or o.get("status") not in (None, "open"):
                continue
            team, how = attribute(o, offer_team, pseudo, owners)
            rows.append({"id": o["id"], "venue": vid, "venue_name": v["name"], "venue_owner": v["owner"],
                         "fee_bps": v["fee_bps"], "fee_per_card": v["fee_per_card"], **shape(o),
                         "maker": o.get("maker"), "team": team, "how": how, "to": o.get("to"),
                         "assets": [a.get("id") for a in (o.get("give") or {}).get("assets") or [] if isinstance(a, dict)],
                         "created_tick": o.get("created_tick"), "expires_tick": o.get("expires_tick"),
                         "source": source_url(vid), "verdict": None})
    rows.sort(key=lambda r: r["id"])
    return rows


def refs_of(r: dict) -> list:
    return r.get("refs") or [x for x in (r["ref"], r["want_ref"]) if x]


def card_book(rows: list) -> dict:
    """ref -> asks (cheapest first), bids (highest first), swaps and other offers touching the card, and the best
    public ask and bid across every venue (an offer addressed to one team is shown but not counted as best)."""
    out = {}
    for r in rows:
        for ref in refs_of(r):
            b = out.setdefault(ref, {"asks": [], "bids": [], "swaps": [], "other": [], "best_ask": None, "best_bid": None})
            b[{"ask": "asks", "bid": "bids", "swap": "swaps"}.get(r["kind"], "other")].append(r)
    for b in out.values():
        b["asks"].sort(key=lambda r: (r["price"], r["id"]))
        b["bids"].sort(key=lambda r: (-r["price"], r["id"]))
        asks, bids = [r for r in b["asks"] if not r["to"]], [r for r in b["bids"] if not r["to"]]
        b["best_ask"] = {"price": asks[0]["price"], "venue": asks[0]["venue"]} if asks else None
        b["best_bid"] = {"price": bids[0]["price"], "venue": bids[0]["venue"]} if bids else None
    return out


# ---------------------------------------------------------------- holders and prices (public trades only)

def holders(events: list, rows: list = ()) -> dict:
    """ref -> team -> {copies, net}. `net` = copies received minus sent in public (settlements, gifts, pack reveals);
    `copies` = what we can prove they still hold: the larger of `net` and the copies whose last public move (or an open
    offer of theirs on a venue) ends with them. Starting hands and pack contents other than the revealed best card are
    not public: this is a lower bound, "known from public trades"."""
    net = collections.defaultdict(lambda: collections.Counter())
    owner, ref_of = {}, {}
    for e in sorted(events, key=lambda e: e.get("id") or 0):
        p, kind = e.get("payload") or {}, e.get("type")
        if kind == "settlement":
            for i in p.get("items") or []:
                if not isinstance(i, dict) or i.get("kind", "card") != "card" or not isinstance(i.get("ref"), str):
                    continue
                if isinstance(i.get("to"), str) and TEAM_RE.match(i["to"]):
                    net[i["ref"]][i["to"]] += 1
                if isinstance(i.get("frm"), str) and TEAM_RE.match(i["frm"]):
                    net[i["ref"]][i["frm"]] -= 1
                if isinstance(i.get("id"), int):
                    owner[i["id"]], ref_of[i["id"]] = i.get("to"), i["ref"]
        elif kind == "gift.given" and isinstance(p.get("team"), str):
            for ref in p.get("cards") or []:
                if isinstance(ref, str):
                    net[ref][p["team"]] += 1
        elif kind == "pack.opened" and isinstance(p.get("best"), dict) and isinstance(p.get("team"), str):
            b = p["best"]
            if isinstance(b.get("ref"), str) and b.get("kind", "card") == "card":
                net[b["ref"]][p["team"]] += 1
                if isinstance(b.get("id"), int):
                    owner[b["id"]], ref_of[b["id"]] = p["team"], b["ref"]
    for r in rows:  # a card on sale right now is a card its maker holds right now
        if r["team"] and r["kind"] in ("ask", "swap"):
            for aid in r["assets"]:
                if isinstance(aid, int):
                    owner[aid], ref_of[aid] = r["team"], r["ref"]
    tracked = collections.Counter((ref_of[a], t) for a, t in owner.items() if isinstance(t, str) and TEAM_RE.match(t))
    out = {}
    for ref in set(net) | {ref for ref, _ in tracked}:
        teams = set(net[ref]) | {t for r, t in tracked if r == ref}
        for t in teams:
            n, c = net[ref][t], max(net[ref][t], tracked[(ref, t)])
            if c > 0 or n:
                out.setdefault(ref, {})[t] = {"copies": c, "net": n}
    return out


def recent_prices(events: list, n: int = RECENT_N) -> dict:
    """ref -> the last n cash trades of that card, newest first, price per card (a settlement of k copies of one card
    from one party to another counts at price / k; bundles of different cards and swaps are skipped)."""
    out = collections.defaultdict(list)
    for e in sorted((e for e in events if e.get("type") == "settlement"), key=lambda e: e.get("id") or 0):
        p = e.get("payload") or {}
        items = [i for i in p.get("items") or [] if isinstance(i, dict)]
        if not items or any(i.get("kind", "card") != "card" for i in items) or num(p.get("price")) <= 0:
            continue
        if len({i.get("ref") for i in items}) != 1 or len({i.get("frm") for i in items}) != 1 or len({i.get("to") for i in items}) != 1:
            continue
        i = items[0]
        out[i.get("ref")].append({"settlement": p.get("settlement"), "tick": p.get("tick", e.get("tick")),
                                  "price": round(num(p["price"]) / len(items), 1), "qty": len(items),
                                  "venue": p.get("venue"), "dealer": p.get("persona"), "frm": i.get("frm"), "to": i.get("to")})
    return {ref: rows[-n:][::-1] for ref, rows in out.items() if isinstance(ref, str)}


def reference_price(recent: list, n: int = REF_N) -> dict:
    ps = [r["price"] for r in recent[:n]]
    return {"price": round(statistics.median(ps), 1) if ps else None, "n": len(ps)}


def verdict(r: dict, ref: dict) -> dict | None:
    """Is this price fair? An open ask or bid next to the card's reference price (dealer trades included)."""
    if r["kind"] not in ("ask", "bid") or not ref.get("price") or not r["price"]:
        return None
    x = r["price"] / ref["price"]
    if r["kind"] == "ask":
        flag = "high" if x > 1.5 else "bargain" if x < 0.75 else "fair"
    else:
        flag = "generous" if x > 1.25 else "low" if x < 0.6 else "fair"
    trades = f"{ref['n']} public trade{'s' if ref['n'] != 1 else ''}"
    return {"ratio": round(x, 2), "flag": flag, "reference": ref["price"], "n": ref["n"],
            "text": f"{x:.1f}x the reference ({ref['price']:g} P, median of the last {trades})"}


def source_url(vid: str) -> str:
    """Where anyone can check an offer: the venue's public book."""
    return f"{BASE}venues/{urllib.parse.quote(vid)}/offers"


def order(kind: str, ref: str, price, vid: str | None, asset=None, want_ref: str | None = None) -> dict | None:
    """A ready-to-post order for our venue: the exact POST /api/offers body (kit/bazaar_sdk.py list_offer). An ask or
    swap needs the poster's own asset id; when we cannot know it, a placeholder says so."""
    if not vid:
        return None
    price = int(price) if isinstance(price, float) and price.is_integer() else price
    mine = asset if isinstance(asset, int) else f"<your {ref} asset id>"
    give, want = {"bid": ({"cash": price}, {"cards": [ref]}), "ask": ({"assets": [mine]}, {"cash": price}),
                  "swap": ({"assets": [mine]}, {"cards": [want_ref]})}[kind]
    return {"method": "POST", "path": "/api/offers",
            "body": {"venue": vid, "give": give, "want": want, "expires_in_ticks": ORDER_TICKS}}


def accept_call(r: dict) -> dict:
    """Taking an offer that already sits on our venue: POST /api/offers/{id}/accept (a card wanted: your copy's id)."""
    want = r["ref"] if r["kind"] == "bid" else r["want_ref"] if r["kind"] == "swap" else None
    return {"method": "POST", "path": f"/api/offers/{r['id']}/accept",
            "body": {"assets": [f"<your {want} asset id>"]} if want else {}}


# ---------------------------------------------------------------- matches waiting to happen

def who(r: dict) -> str:
    return r["team"] or r["maker"] or "?"


def same_party(a: dict, b: dict) -> bool:
    return a["maker"] == b["maker"] or (a["team"] is not None and a["team"] == b["team"])


def party(r: dict) -> dict:
    return {"offer": r["id"], "team": r["team"], "maker": r["maker"], "venue": r["venue"], "price": r["price"],
            "asset": r["assets"][0] if r["assets"] else None, "source": r["source"]}


def match(kind: str, ref: str, buy: dict, sell: dict, value: float, why: str, ours: str | None, **extra) -> dict:
    venues = {x.get("venue") for x in (buy, sell) if x.get("venue")}
    return {"kind": kind, "ref": ref, "score": TIERS[kind] * 1000 + max(0, min(999, round(value, 1))),
            "buy": buy, "sell": sell, "stranded": len(venues) > 1, "on_ours": bool(ours) and ours in venues,
            "why": why, **extra}


def find_matches(rows: list, hold: dict, ours: str | None = None) -> list:
    """Crossing pairs first (a bid at or above an ask, different makers; 'stranded' when on different venues, so no
    broker sees both), then mirror swaps, then near misses (a bid at least half a higher ask, smallest gap first), then
    known spares (a bid, and a team known to hold 2+ copies that lists none), then weak leads (a team known to hold one
    copy: it may need it for its album). Each offer crosses at most once."""
    live = [r for r in rows if not r["to"]]
    asks, bids = collections.defaultdict(list), [r for r in live if r["kind"] == "bid"]
    for r in live:
        if r["kind"] == "ask":
            asks[r["ref"]].append(r)
    out, used = [], set()
    pairs = sorted(((b["price"] - a["price"], b, a) for b in bids for a in asks[b["ref"]]
                    if b["price"] >= a["price"] and not same_party(a, b)), key=lambda p: (-p[0], p[1]["id"], p[2]["id"]))
    for surplus, b, a in pairs:
        if b["id"] in used or a["id"] in used:
            continue
        used |= {b["id"], a["id"]}
        where = f"different venues ({b['venue']} and {a['venue']}): no broker sees both" if b["venue"] != a["venue"] else f"both on {a['venue']}"
        out.append(match("cross", b["ref"], party(b), party(a), b["price"],
                         f"{who(b)} bids {b['price']:g} P and {who(a)} asks {a['price']:g} P for {b['ref']}: they cross by "
                         f"{surplus:g} P, on {where}", ours, gap=-surplus,
                         orders={"buyer": order("bid", b["ref"], b["price"], ours),
                                 "seller": order("ask", a["ref"], a["price"], ours, a["assets"][0] if a["assets"] else None)}))
    swaps = [r for r in live if r["kind"] == "swap"]
    for i, s in enumerate(swaps):
        for t in swaps[i + 1:]:
            if s["ref"] == t["want_ref"] and s["want_ref"] == t["ref"] and not same_party(s, t):
                out.append(match("mirror", s["ref"], party(t), party(s), 0,
                                 f"{who(s)} gives {s['ref']} for {s['want_ref']} on {s['venue']}; {who(t)} gives "
                                 f"{t['ref']} for {t['want_ref']} on {t['venue']}: a swap both want", ours,
                                 want_ref=s["want_ref"],
                                 orders={"seller": order("swap", s["ref"], None, ours, (s["assets"] or [None])[0], s["want_ref"]),
                                         "buyer": order("swap", t["ref"], None, ours, (t["assets"] or [None])[0], t["want_ref"])}))
    for b in bids:
        if b["id"] in used:
            continue
        sellers, near = set(), []
        for a in asks[b["ref"]]:
            if a["price"] > b["price"] >= NEAR_RATIO * a["price"] and not same_party(a, b) and who(a) not in sellers:
                sellers.add(who(a))
                near.append(a)
        for a in near[:PER_BID]:
            gap, mid = a["price"] - b["price"], round((a["price"] + b["price"]) / 2)
            out.append(match("near", b["ref"], party(b), party(a), b["price"] - gap,
                             f"{who(b)} bids {b['price']:g} P on {b['venue']}; {who(a)} asks {a['price']:g} P on "
                             f"{a['venue']}: {gap:g} P apart; halfway is {mid:g} P", ours, gap=gap, meet=mid,
                             orders={"buyer": order("bid", b["ref"], mid, ours),
                                     "seller": order("ask", a["ref"], mid, ours, a["assets"][0] if a["assets"] else None)}))
        known = sorted(((h["copies"], t) for t, h in (hold.get(b["ref"]) or {}).items()
                        if h["copies"] >= 1 and t != b["team"] and t not in sellers), key=lambda x: (-x[0], x[1]))
        for copies, t in known[:PER_BID]:
            kind = "spare" if copies >= 2 else "holder"
            out.append(match(kind, b["ref"], party(b), {"team": t, "copies": copies, "venue": None, "price": None},
                             b["price"] + copies,
                             f"{who(b)} bids {b['price']:g} P on {b['venue']}; {t} holds {copies} known "
                             + ("copies and lists none" if copies >= 2 else "copy and lists none (it may need it)"), ours,
                             orders={"buyer": order("bid", b["ref"], b["price"], ours),
                                     "seller": order("ask", b["ref"], b["price"], ours)}))
    out.sort(key=lambda m: (-m["score"], m["ref"], m["buy"].get("offer") or 0))
    return out[:MAX_MATCHES]


# ---------------------------------------------------------------- per team, market, announcements

def brief(r: dict) -> dict:
    """An open offer as the per-team lists show it (public fields only)."""
    return {"offer": r["id"], "kind": r["kind"], "ref": r["ref"], "price": r["price"], "want_ref": r["want_ref"],
            "summary": r.get("summary"), "venue": r["venue"], "venue_name": r["venue_name"], "team": r["team"],
            "maker": r["maker"], "how": r["how"], "to": r["to"], "expires_tick": r["expires_tick"],
            "source": r["source"], "verdict": r["verdict"]}


def team_rows(leaderboard: dict, rows: list, hold: dict, book: dict) -> list:
    """Every team: its open bids (wants), asks (spares), swaps, known holdings, score and album, and for each want the
    teams that could fill it (an ask anywhere, a known spare, a known single copy)."""
    lb = {t["team"]: t for t in leaderboard.get("teams") or [] if isinstance(t, dict) and isinstance(t.get("team"), str)}
    teams = set(lb) | {r["team"] for r in rows if r["team"]}
    out = []
    for t in sorted(teams, key=lambda t: (lb.get(t, {}).get("rank") or 99, t)):
        mine = [r for r in rows if r["team"] == t]
        wants = sorted({r["want_ref"] if r["kind"] == "swap" else r["ref"] for r in mine if r["kind"] in ("bid", "swap")})
        fillers = []
        for ref in wants:
            for a in (book.get(ref) or {}).get("asks", []):
                if a["team"] != t and not a["to"]:
                    fillers.append({"ref": ref, "team": a["team"], "maker": a["maker"], "how": f"asks {a['price']:g} P on {a['venue']}"})
            for h, info in sorted((hold.get(ref) or {}).items(), key=lambda x: -x[1]["copies"]):
                if h != t and info["copies"] >= 1:
                    fillers.append({"ref": ref, "team": h, "maker": None,
                                    "how": f"holds {info['copies']} known {'copies' if info['copies'] > 1 else 'copy'}"
                                           + ("" if info["copies"] > 1 else " (may need it)")})
        L = lb.get(t, {})
        out.append({"team": t, "name": L.get("name") or t, "rank": L.get("rank"), "score": L.get("score"),
                    "album_filled": L.get("album_filled"), "album_slots": L.get("album_slots"),
                    "pages_complete": L.get("pages_complete"), "venue": L.get("venue"),
                    "bids": [brief(r) for r in mine if r["kind"] == "bid"],
                    "asks": [brief(r) for r in mine if r["kind"] == "ask"],
                    "swaps": [brief(r) for r in mine if r["kind"] == "swap"],
                    "holdings": sorted(({"ref": ref, "copies": h[t]["copies"]} for ref, h in hold.items()
                                        if t in h and h[t]["copies"] > 0), key=lambda x: x["ref"]),
                    "fillers": fillers[:24]})
    for maker in sorted({r["maker"] for r in rows if not r["team"] and isinstance(r["maker"], str)}):
        mine = [r for r in rows if not r["team"] and r["maker"] == maker]
        out.append({"team": None, "maker": maker, "name": f"unknown maker {maker}", "rank": None, "score": None,
                    "album_filled": None, "album_slots": None, "pages_complete": None, "venue": None,
                    "bids": [brief(r) for r in mine if r["kind"] == "bid"], "asks": [brief(r) for r in mine if r["kind"] == "ask"],
                    "swaps": [brief(r) for r in mine if r["kind"] == "swap"], "holdings": [], "fillers": []})
    return out


def demand_rows(rows: list, cards: dict, recent: dict) -> list:
    """Per card, aggregated across the whole market without who or where: how many open bids and asks, the best of
    each, swaps wanting or giving it, distinct bidders, and the reference price from public trades."""
    acc = {}
    for r in rows:
        if r["to"] or r["kind"] == "other":
            continue
        for ref, role in ((r["ref"], r["kind"]), (r["want_ref"], "swap_want")):
            if not ref or (role == "swap_want" and r["kind"] != "swap"):
                continue
            d = acc.setdefault(ref, {"bids": 0, "asks": 0, "swaps_wanting": 0, "swaps_giving": 0, "best_bid": None,
                                     "best_ask": None, "bidders": set()})
            if role == "bid":
                d["bids"] += 1
                d["bidders"].add(who(r))
                d["best_bid"] = max(d["best_bid"] or 0, r["price"])
            elif role == "ask":
                d["asks"] += 1
                d["best_ask"] = r["price"] if d["best_ask"] is None else min(d["best_ask"], r["price"])
            elif role == "swap":
                d["swaps_giving"] += 1
            else:
                d["swaps_wanting"] += 1
    out = []
    for ref, d in acc.items():
        c, rp = cards.get(ref, {}), reference_price(recent.get(ref, []))
        out.append({"ref": ref, "name": c.get("name"), "rarity": c.get("rarity"), "bids": d["bids"],
                    "bidders": len(d["bidders"]), "best_bid": d["best_bid"], "asks": d["asks"], "best_ask": d["best_ask"],
                    "swaps_wanting": d["swaps_wanting"], "swaps_giving": d["swaps_giving"],
                    "ref_price": rp["price"], "trades": rp["n"]})
    out.sort(key=lambda d: (-(d["bids"] + d["swaps_wanting"]), -(d["best_bid"] or 0), d["ref"]))
    return out


def sign(body: str, vid: str) -> str:
    sig = " · " + SIGNATURE.format(vid=vid)
    return (body if len(body) + len(sig) <= ANNOUNCE_MAX else body[:ANNOUNCE_MAX - len(sig) - 1] + "…") + sig


def announcements(matches: list, demand: list, cards: dict, vid: str | None) -> list:
    """Draft texts for our broker, built from the private matches but saying only what is on our venue (or the
    aggregate demand the public page shows anyway). `targets` (who to nudge) stays private. Nothing is sent."""
    if not vid:
        return []
    dem, out, seen = {d["ref"]: d for d in demand}, [], {}

    def add(ref: str, body: str, targets: list, basis: str) -> None:
        text = sign(body, vid)
        if text not in seen:
            seen[text] = {"ref": ref, "text": text, "targets": [], "basis": basis}
            out.append(seen[text])
        seen[text]["targets"] = sorted(set(seen[text]["targets"]) | {t for t in targets if t and t != US})

    for m in matches:
        ref, name = m["ref"], cards.get(m["ref"], {}).get("name")
        card = f"{ref} ({name})" if name else ref
        buy, sell = m["buy"], m["sell"]
        if m["kind"] == "mirror":
            continue
        if buy.get("venue") == vid and sell.get("venue") != vid:
            add(ref, f"Spare {card}? A bid at {buy['price']:g} P is waiting on La Celestina ({vid}). Fill it here, 0% fee.",
                [sell.get("team")], m["kind"])
        elif sell.get("venue") == vid and buy.get("venue") != vid:
            add(ref, f"Need {card}? One is for sale at {sell['price']:g} P on La Celestina ({vid}). Take it here, 0% fee.",
                [buy.get("team")], m["kind"])
        elif buy.get("venue") != vid and sell.get("venue") != vid:
            d = dem.get(ref) or {}
            if d.get("bids"):
                add(ref, f"Holding a spare {card}? {d['bids']} open bid{'s' if d['bids'] > 1 else ''} in the market, best "
                         f"{d['best_bid']:g} P. List it on La Celestina ({vid}): we find the buyer, 0% fee.",
                    [sell.get("team")], m["kind"])
            add(ref, f"Looking for {card}? Post your bid on La Celestina ({vid}): we find the other side and our broker "
                     f"matches every tick, 0% fee.", [buy.get("team")], m["kind"])
    return out


# ---------------------------------------------------------------- snapshots

def catalog_cards(catalog: dict) -> dict:
    out = {}
    for s in catalog.get("sets") or []:
        for c in s.get("cards") or [] if isinstance(s, dict) else []:
            if isinstance(c, dict) and isinstance(c.get("id"), str):
                out[c["id"]] = {"ref": c["id"], "name": c.get("name"), "rarity": c.get("rarity"), "set": s.get("id"),
                                "set_name": s.get("name"), "released": s.get("released"), "book": c.get("book"),
                                "print_run": c.get("print_run"), "minted": c.get("minted")}
    return out


def build(venues_body, books: dict, events: list, catalog: dict, leaderboard: dict, clock: dict,
          history_offers=(), pseudo_sets: dict | None = None, market_test: list | None = None) -> dict:
    """The PRIVATE snapshot: everything, Team 3 only. public_view() cuts the public one out of it."""
    venues = venue_rows(venues_body)
    ours = our_venue(venues)
    vid = ours["venue"] if ours else None
    cards = catalog_cards(catalog or {})
    offer_team = offer_teams(events)
    sets = learn_pseudonyms(list(history_offers) + [o for offs in books.values() for o in offs or []], offer_team, pseudo_sets)
    rows = consolidate(venues, books, offer_team, resolve(sets), asset_owners(events))
    hold = holders(events, rows)
    recent = recent_prices(events)
    for r in rows:
        r["verdict"] = verdict(r, reference_price(recent.get(r["ref"], [])))
    book = card_book(rows)
    matches = find_matches(rows, hold, vid)
    demand = demand_rows(rows, cards, recent)
    per_card = {}
    for ref in sorted(set(cards) | set(book) | set(hold) | set(recent)):
        b = book.get(ref, {})
        per_card[ref] = {**cards.get(ref, {"ref": ref}), "best_ask": b.get("best_ask"), "best_bid": b.get("best_bid"),
                         "offers": [r for k in ("asks", "bids", "swaps", "other") for r in b.get(k, [])],
                         "holders": sorted(({"team": t, **h} for t, h in (hold.get(ref) or {}).items() if h["copies"] > 0),
                                           key=lambda h: (-h["copies"], h["team"])),
                         "recent": recent.get(ref, []), "reference": reference_price(recent.get(ref, []))}
    counts = collections.Counter((r["venue"], r["kind"]) for r in rows)
    venue_list = [{**v, "ours": v["venue"] == vid, "open": sum(counts[(v["venue"], k)] for k in ("ask", "bid", "swap", "other")),
                   **{k + "s": counts[(v["venue"], k)] for k in ("ask", "bid", "swap")}, "others": counts[(v["venue"], "other")]}
                  for v in venues]
    venue_list.sort(key=lambda v: (-v["open"], v["venue"]))
    unknown = collections.Counter(r["maker"] for r in rows if not r["team"])
    return {
        "scope": "private",
        "about": "La Celestina, Team 3's matchmaker. PRIVATE: holders, teams and every venue's book. Never publish.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tick": (clock or {}).get("tick"),
        "clock": {k: (clock or {}).get(k) for k in ("tick", "tick_seconds", "paused", "round_name", "doors", "today_name")},
        "our_venue": ours, "pitch": PITCH.format(vid=vid or "our venue"),
        "venues": venue_list, "cards": per_card, "matches": matches, "teams": team_rows(leaderboard or {}, rows, hold, book),
        "demand": demand,
        "market": {"open_offers": len(rows), "venues_with_offers": len({r["venue"] for r in rows}),
                   **{k + "s": sum(1 for r in rows if r["kind"] == k) for k in ("ask", "bid", "swap", "other")},
                   "crossing": sum(1 for m in matches if m["kind"] == "cross"),
                   "stranded": sum(1 for m in matches if m["kind"] == "cross" and m["stranded"]),
                   "unattributed": [{"maker": m, "offers": n} for m, n in unknown.most_common()]},
        "attribution": dict(collections.Counter(r["how"] for r in rows)),
        "announcements": announcements(matches, demand, cards, vid),
        "market_test": market_test if market_test is not None else MARKET_TEST,
        "sources": {"events": len(events), "first_event": events[0].get("id") if events else None,
                    "last_event": events[-1].get("id") if events else None, "pseudonyms": len(resolve(sets)),
                    "venues_read": sorted(books)},
    }


def counter(r: dict, vid: str | None) -> dict | None:
    """The order that meets an offer on our venue at its own price: an ask for a bid, a bid for an ask, the mirror swap."""
    if r["kind"] == "bid":
        return order("ask", r["ref"], r["price"], vid)
    if r["kind"] == "ask":
        return order("bid", r["ref"], r["price"], vid)
    if r["kind"] == "swap":
        return order("swap", r["want_ref"], None, vid, want_ref=r["ref"])
    return None


def public_view(snap: dict) -> dict:
    """The PUBLIC snapshot, cut out of the private one by whitelisting. Open offers are public in every venue's book,
    so they are shown per card and per team (with the team behind them when the feed says so), each with its source
    and a price verdict; matches built from open offers alone come with ready-to-post orders for our venue. The holder
    map (who is known to hold which copies), the matches built on it and the announcement drafts never leave here."""
    ours = snap.get("our_venue") or None
    vid = ours["venue"] if ours else None
    cards = snap.get("cards") or {}
    rows = {r["id"]: r for c in cards.values() for r in c.get("offers") or []}

    def name(ref):
        return (cards.get(ref) or {}).get("name")

    book = sorted((r for r in rows.values() if vid and r["venue"] == vid and not r["to"]),
                  key=lambda r: ({"bid": 0, "ask": 1, "swap": 2}.get(r["kind"], 3), -(r["price"] or 0), r["id"]))
    our_book, invitations = [], []
    for r in book:
        our_book.append({**brief(r), "name": name(r["ref"]), "accept": accept_call(r), "counter": counter(r, vid)})
        card = f"{r['ref']} ({name(r['ref'])})" if name(r["ref"]) else (r["ref"] or "")
        text = {"bid": lambda: f"A bid for {card} at {r['price']:g} P is waiting on {vid}: if you hold a spare, fill it here.",
                "ask": lambda: f"{card} is for sale at {r['price']:g} P on {vid}: if you need it, take it here.",
                "swap": lambda: f"Someone on {vid} gives {card} for {r['want_ref']}: if you hold a spare {r['want_ref']}, swap it here."
                }.get(r["kind"])
        if text:
            invitations.append({"offer": r["id"], "kind": r["kind"], "ref": r["ref"], "price": r["price"], "text": text(),
                                "source": r["source"], "accept": accept_call(r), "counter": counter(r, vid)})
    pub_cards = {}
    for ref, c in cards.items():
        pub_cards[ref] = {**{k: c.get(k) for k in ("ref", "name", "rarity", "set", "print_run", "minted")},
                          "best_ask": c.get("best_ask"), "best_bid": c.get("best_bid"), "reference": c.get("reference"),
                          "recent": [{k: t.get(k) for k in ("settlement", "tick", "price", "qty", "venue", "dealer")}
                                     for t in c.get("recent") or []],
                          "offers": [brief(r) for r in c.get("offers") or []]}
    teams = [{**{k: t.get(k) for k in ("team", "maker", "name", "rank", "score", "album_filled", "album_slots",
                                        "pages_complete", "venue")},
              **{k: [dict(o) for o in t.get(k) or []] for k in ("bids", "asks", "swaps")}} for t in snap.get("teams") or []]
    matches = [{k: m.get(k) for k in ("kind", "ref", "want_ref", "score", "buy", "sell", "stranded", "on_ours", "why",
                                      "gap", "meet", "orders")}
               for m in snap.get("matches") or [] if m.get("kind") in PUBLIC_MATCHES]
    demand = [{k: d[k] for k in ("ref", "name", "rarity", "bids", "bidders", "best_bid", "asks", "best_ask",
                                 "swaps_wanting", "swaps_giving", "ref_price", "trades")} for d in snap.get("demand") or []]
    m = snap.get("market") or {}
    return {
        "scope": "public",
        "about": "La Celestina · finds your missing card. Public data only (no key), refreshed every 15 s.",
        "pitch": snap.get("pitch"), "generated_at": snap.get("generated_at"), "tick": snap.get("tick"),
        "our_venue": {k: ours.get(k) for k in ("venue", "name", "status", "fee_bps", "fee_per_card", "mechanism")} if ours else None,
        "our_book": our_book, "invitations": invitations, "matches": matches, "teams": teams, "cards": pub_cards,
        "demand": demand,
        "market": {k: m.get(k) for k in ("open_offers", "venues_with_offers", "asks", "bids", "swaps", "crossing", "stranded")},
        "market_test": [{k: t.get(k) for k in ("test", "ours", "stall", "note")} for t in snap.get("market_test") or []
                        if isinstance(t, dict)],
        "sources": {"offers": BASE + "venues/{venue}/offers", "feed": BASE + "feed?limit=1000",
                    "settlements": "settlement ids are in the public feed (type settlement)",
                    "post": "POST /api/offers with your own key, from your own machine; we never ask for it"},
    }


def card_view(snap: dict, ref: str) -> dict | None:
    """One card from either snapshot (the public one only carries public fields)."""
    if ref not in (snap.get("cards") or {}):
        return None
    out = {"scope": snap.get("scope"), "tick": snap.get("tick"), "card": snap["cards"][ref],
           "demand": next((d for d in snap.get("demand") or [] if d["ref"] == ref), None),
           "matches": [m for m in snap.get("matches") or [] if ref in (m["ref"], m.get("want_ref"))]}
    if snap.get("scope") == "public":
        out["our_book"] = [b for b in snap.get("our_book") or [] if ref in (b["ref"], b["want_ref"])]
        out["invitations"] = [i for i in snap.get("invitations") or [] if i["ref"] == ref]
    return out


# ---------------------------------------------------------------- reading the game (keyless GETs only)

class Reader:
    def __init__(self, base: str = BASE, gap: float = MIN_GAP):
        self.base, self.gap, self.last, self.count = base, gap, 0.0, 0

    def get(self, path: str):
        wait = self.last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        self.count += 1
        req = urllib.request.Request(self.base + path, headers={"User-Agent": "la-celestina/1 (Team 3, keyless)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())


class FeedStore:
    """Every public event we keep (the types this tool reads), by id: the recorded file, read incrementally (the
    recorder may still be appending), merged with each live window."""

    def __init__(self, path: Path | None):
        self.path, self.offset, self.events = path, 0, {}

    def load_file(self) -> "FeedStore":
        if not self.path or not self.path.exists():
            return self
        if self.path.stat().st_size < self.offset:
            self.offset = 0
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # whole lines only
        for line in chunk[:end].splitlines():
            try:
                self.merge([json.loads(line)])
            except ValueError:
                continue
        self.offset += end
        return self

    def merge(self, events) -> "FeedStore":
        for e in events or []:
            if isinstance(e, dict) and isinstance(e.get("id"), int) and e.get("type") in KEEP_TYPES:
                self.events.setdefault(e["id"], e)
        return self

    def all(self) -> list:
        return [self.events[k] for k in sorted(self.events)]


def history_offers(path: Path | None) -> list:
    """Offers from the recorder's book snapshots ({id, maker} only): more offer ids to learn pseudonyms from."""
    out = {}
    if not path or not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("what") not in ("book", "rastro"):
                continue
            body = row.get("body")
            for o in (body.get("offers") if isinstance(body, dict) else body) or []:
                if isinstance(o, dict) and isinstance(o.get("id"), int) and isinstance(o.get("maker"), str):
                    out[o["id"]] = {"id": o["id"], "maker": o["maker"]}
    return list(out.values())


def fetch(reader: Reader, catalog: dict | None) -> dict:
    venues = reader.get("venues")
    books = {}
    for v in venue_rows(venues):
        if v["status"] == "open":
            try:
                body = reader.get(f"venues/{urllib.parse.quote(v['venue'])}/offers")
                books[v["venue"]] = body.get("offers", []) if isinstance(body, dict) else []
            except (OSError, ValueError):
                continue  # one venue down: the rest still counts
    return {"venues": venues, "books": books, "feed": reader.get(f"feed?limit={FEED_LIMIT}").get("events", []),
            "leaderboard": reader.get("leaderboard"), "clock": reader.get("clock"),
            "catalog": catalog if catalog is not None else reader.get("catalog")}


class Engine:
    """One refresh = one fetch + one build; keeps what it learnt (events, pseudonyms, catalog) between refreshes."""

    def __init__(self, feed_file: Path | None, snapshots_file: Path | None, market_test: list | None = None):
        self.store = FeedStore(feed_file).load_file()
        self.history = history_offers(snapshots_file)
        self.sets: dict = {}
        self.catalog, self.n, self.market_test = None, 0, market_test
        self.reader = Reader()

    def refresh(self) -> dict:
        raw = fetch(self.reader, self.catalog if self.n % CATALOG_EVERY else None)
        self.n += 1
        self.catalog = raw["catalog"]
        self.store.load_file().merge(raw["feed"])
        return build(raw["venues"], raw["books"], self.store.all(), raw["catalog"], raw["leaderboard"], raw["clock"],
                     self.history, self.sets, self.market_test)


# ---------------------------------------------------------------- server

STATE = {"private": None, "public": None, "private_bytes": None, "public_bytes": None, "error": None, "updated": 0.0}
LOCK = threading.Lock()


def publish(snap: dict) -> None:
    pub = public_view(snap)
    with LOCK:
        STATE.update(private=snap, public=pub, private_bytes=json.dumps(snap, default=list).encode(),
                     public_bytes=json.dumps(pub).encode(), error=None, updated=time.time())


def worker(engine: Engine, interval: float) -> None:
    while True:
        t0 = time.time()
        try:
            publish(engine.refresh())
        except Exception:  # noqa: BLE001  keep serving the last good snapshot
            with LOCK:
                STATE["error"] = traceback.format_exc(limit=2)[-400:]
        time.sleep(max(1.0, interval - (time.time() - t0)))


class Limiter:
    """Token bucket per client address: a public page should not be a way to burn our CPU."""

    def __init__(self, rate: float, burst: float):
        self.rate, self.burst, self.buckets, self.lock = rate, burst, {}, threading.Lock()

    def allow(self, addr: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            tokens, last = self.buckets.get(addr, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if len(self.buckets) > 5000:
                self.buckets.clear()
            if tokens < 1:
                self.buckets[addr] = (tokens, now)
                return False
            self.buckets[addr] = (tokens - 1, now)
            return True


def handler(scope: str):
    """Request handler for one side: 'public' serves the public view, 'private' the whole snapshot."""
    limiter = Limiter(*RATE)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if ctype.startswith("application/json") and scope == "public":
                self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            if scope == "public":
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if not limiter.allow(self.client_address[0]):
                return self._send(429, b'{"error": "too many requests"}', "application/json")
            path = urllib.parse.urlparse(self.path).path
            with LOCK:
                snap, body, err, updated = STATE[scope], STATE[scope + "_bytes"], STATE["error"], STATE["updated"]
            if path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/healthz":
                age = round(time.time() - updated, 1) if updated else None
                return self._send(200, json.dumps({"ok": snap is not None and not err, "scope": scope, "age_s": age,
                                                   "tick": (snap or {}).get("tick"),
                                                   "error": bool(err) if scope == "public" else err}).encode(),
                                  "application/json")
            if snap is None:
                return self._send(503, b'{"error": "warming up, try again in a few seconds"}', "application/json")
            if path == "/api/celestina.json":
                return self._send(200, body, "application/json")
            m = re.match(r"^/api/card/([A-Za-z0-9-]{1,12})\.json$", path)
            if m and REF_RE.match(m.group(1).upper()):
                view = card_view(snap, m.group(1).upper())
                if view is not None:
                    return self._send(200, json.dumps(view, default=list).encode(), "application/json")
            return self._send(404, b'{"error": "not found"}', "application/json")

    return Handler


def serve(args) -> None:
    market_test = json.loads(Path(args.market_test).read_text(encoding="utf-8")) if args.market_test else None
    engine = Engine(args.feed_file, args.snapshots_file, market_test)
    threading.Thread(target=worker, args=(engine, args.interval), daemon=True).start()
    servers = [ThreadingHTTPServer((args.host, args.port), handler("public"))]
    if args.private_port:
        if args.private_port == args.port:
            raise SystemExit("celestina: --private-port must differ from --port")
        servers.append(ThreadingHTTPServer(("127.0.0.1", args.private_port), handler("private")))  # never another host
    for s in servers:
        s.daemon_threads = True
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(f"La Celestina: public on http://{args.host}:{args.port}/"
          + (f", private on http://127.0.0.1:{args.private_port}/ (Team 3 only: never tunnel this port)" if args.private_port else "")
          + f"; {len(engine.store.events)} recorded events, refresh every {args.interval:g} s", flush=True)
    servers[0].serve_forever()


def summary(snap: dict, top: int = 10) -> str:
    m, ours = snap["market"], snap.get("our_venue")
    lines = [f"La Celestina · tick {snap['tick']} · {m['open_offers']} open offers on {m['venues_with_offers']} venues "
             f"({m['asks']} asks, {m['bids']} bids, {m['swaps']} swaps, {m['others']} other) · {m['crossing']} crossing "
             f"({m['stranded']} stranded)",
             f"Our venue: {ours['venue']} {ours['name']} ({ours['status']})" if ours else "Our venue: opening soon",
             "Attribution: " + ", ".join(f"{n} {k}" for k, n in sorted(snap["attribution"].items(), key=lambda x: -x[1]))
             + f" · {snap['sources']['events']} events, {snap['sources']['pseudonyms']} pseudonyms known",
             f"Top matches ({len(snap['matches'])}):"]
    for i, x in enumerate(snap["matches"][:top], 1):
        lines.append(f"  {i:>2}. [{x['kind']}{' stranded' if x['kind'] == 'cross' and x['stranded'] else ''}] {x['why']}")
    lines.append("Most wanted: " + ", ".join(
        f"{d['ref']} ({d['bids']} bid{'s' if d['bids'] != 1 else ''}, best {d['best_bid']:g} P"
        + (f", ask {d['best_ask']:g} P)" if d["best_ask"] is not None else ")")
        for d in snap["demand"][:8] if d["bids"]))
    lines.append("Venues: " + ", ".join(f"{v['venue']} {v['open']}" for v in snap["venues"] if v["open"]))
    if snap["announcements"]:
        lines.append(f"Announcement drafts ({len(snap['announcements'])}, not sent):")
        lines += [f"  - {a['text']}  [for {', '.join(a['targets']) or 'all'}]" for a in snap["announcements"][:5]]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="La Celestina: Team 3's keyless market finder and matchmaker.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "once"):
        p = sub.add_parser(name)
        p.add_argument("--feed-file", type=Path, default=DEFAULT_FEED if DEFAULT_FEED.exists() else None)
        p.add_argument("--snapshots-file", type=Path, default=None,
                       help="recorder book snapshots to learn pseudonyms from (default: snapshots.jsonl next to the feed)")
        p.add_argument("--market-test", default=None, help="JSON list of {test, ours, stall, note} for the public page")
    s = sub.choices["serve"]
    s.add_argument("--port", type=int, default=8795)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--private-port", type=int, default=None, help="Team 3's private side, on 127.0.0.1 only "
                                                                   "(default: --port + 1; 0 turns it off)")
    s.add_argument("--interval", type=float, default=INTERVAL)
    o = sub.choices["once"]
    o.add_argument("--json", action="store_true")
    o.add_argument("--public", action="store_true", help="with --json: the public snapshot instead of the private one")
    args = ap.parse_args()
    if args.snapshots_file is None and args.feed_file:
        guess = Path(args.feed_file).with_name("snapshots.jsonl")
        args.snapshots_file = guess if guess.exists() else None
    if args.cmd == "serve":
        args.private_port = args.port + 1 if args.private_port is None else args.private_port
        serve(args)
        return
    market_test = json.loads(Path(args.market_test).read_text(encoding="utf-8")) if args.market_test else None
    snap = Engine(args.feed_file, args.snapshots_file, market_test).refresh()
    if args.json:
        json.dump(public_view(snap) if args.public else snap, sys.stdout, indent=1, default=list)
        print()
    else:
        print(summary(snap))


if __name__ == "__main__":
    main()
