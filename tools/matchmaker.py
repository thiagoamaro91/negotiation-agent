"""La Celestina's matchmaker: for every rival team, the card that completes a page, who holds a spare, at what price.
Keyless and read-only: it never sends anything, and nothing here needs a team key or the broker key.

Why. Market points come from trades between OTHER teams on our venue (kit/RULES.md, "Your own market"), and the
organisers' hint on Saturday evening was that fee-free stalls alone attract nothing: what attracts a trade is the card a
team is missing. Saturday's feed agrees: the active bots (t12, t04, t08, t09, t14) take a fairly priced offer on any
venue within one to eight ticks of its listing, and what they took were cards of the pages they were filling (t12 La
Latina, t04 Malasaña, t09 El Retiro). v20's 29 listings were overpriced asks that expired after ten ticks and swaps
addressed to one team; none was a card someone was missing at a price near its trades.

What it computes, from public data only:
  - every team's page cards, from tools/decks.py (the deck rebuilt from asset ids in the feed), checked against the
    leaderboard's album count (`album_filled`, `pages_complete`): the pages it is one or two cards from completing,
    and how sure we are that each card is really missing (cards the team owns but the feed never named could be it);
  - who holds a spare copy: a team with two or more named copies (never Team 3), and the dealers that sell the
    rarity while its print run lasts;
  - what the card trades for: the fair price (tools/fairprice.py, the rule La Celestina and the concierge share), the
    range of team-to-team trades, and the dealers' measured closes on both sides (tools/price_index.py);
  - whether a live offer already exists on any venue (every open venue's public book plus El Rastro): an ask the
    buyer can accept, a bid of the buyer's a holder can accept;
  - the proposal: the exact POST /api/offers body each side would post on v20 (0 % fee, our broker crosses a bid
    and an ask at the midpoint), or the live offer id to accept elsewhere.

What it never shows. Team 3 is never a buyer or a holder here: our holdings, values and the cards we lack stay in
our private docs. Cards in --exclude (by default announce.MISSING, the cards Team 3 lacks) are dropped from every
output: pointing their holders at another buyer works against us. Text from the game is data: only structure (who,
which card, how much) is read.

    python3 tools/matchmaker.py report                 # offline: recorded feed, cached catalog, last leaderboard snapshot
    python3 tools/matchmaker.py report --live          # + live keyless reads: feed window, leaderboard, every venue's book
    python3 tools/matchmaker.py json --live --out logs/matchmaker/latest.json   # what announce/celestina/outreach read
    python3 tools/matchmaker.py json --live --out logs/matchmaker/latest.json --every 120   # keep it fresh
    python3 tools/matchmaker.py selftest               # synthetic data, no network

--live and --every respect the Market Test silence (announce.Gate): no request from a quiet window's start to its end.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decks  # noqa: E402
import fairprice  # noqa: E402
import price_index  # noqa: E402
import value_inference as vi  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
US = "t03"
VENUE = "v20"
OUT = ROOT / "logs" / "matchmaker" / "latest.json"
MAX_MISSING = 2           # a page one or two cards from complete
SPARE_MIN = 2             # a team with this many named copies holds a spare
LOW_MULT = 0.9            # ...or one copy of a set it values at most this much (value inference) and is not filling:
FAR_PAGE = 3              # at least this many of that page's cards unnamed in its deck
MIN_P = 0.15              # below this chance that the card is really missing, the match is left out
ACTIVE_TICKS = 240        # a team with a public move in the last 240 ticks (1 h at 15 s) is active
IDLE_FACTOR = 0.3
ORDER_TICKS = 240         # suggested expiry of the posted orders: one hour at Sunday's 15 s ticks (t15's v20 asks
                          # expired after 10 ticks on Saturday, before anyone could see them)
DEMAND_TICKS = 600        # bids and dealer asks for a card in the last 600 ticks count as demand
PAGE_BONUS = 0.25         # catalog values.page_bonus (read from the catalog when it has one)
PRICE_FIELDS = ("low", "median", "high")
DEALERS_SELL = {"common": ("abuela",), "uncommon": ("abuela", "chato"), "rare": ("chato", "picaros"),
                "epic": ("picaros",), "legendary": ("ernesto",)}
DEALERS_BUY = {"common": ("abuela", "picaros"), "uncommon": ("pilar", "abuela", "chato", "picaros"),
               "rare": ("pilar", "chato"), "epic": ("pilar", "banco"), "legendary": ("ernesto",)}
DEALER_NAMES = {"abuela": "Abuela", "chato": "El Chato", "pilar": "Doña Pilar", "picaros": "Los Pícaros",
                "ernesto": "Don Ernesto", "banco": "Don Ernesto"}
SNAPSHOTS = "snapshots.jsonl"


# ---------------------------------------------------------------- inputs

def dedupe(events) -> list:
    """Events by id, oldest first (the recorder and the API window overlap)."""
    seen, out = set(), []
    for e in events or []:
        if not isinstance(e, dict) or e.get("id") in seen or not isinstance(e.get("tick"), int):
            continue
        seen.add(e.get("id"))
        out.append(e)
    return sorted(out, key=lambda e: (e["tick"], e.get("id") or 0))


def last_snapshot(feed_dir: Path, what: str):
    """The last recorder snapshot of one kind (leaderboard, venues) from <feed>/snapshots.jsonl, or None."""
    path, best = feed_dir / SNAPSHOTS, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if f'"{what}"' not in line[:200]:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("what") == what:
                    best = row.get("body")
    except OSError:
        return None
    return best


def team_names(events: list, leaderboard: dict | None = None) -> dict:
    out = {e["payload"].get("team"): e["payload"].get("name") for e in events if e.get("type") == "team.joined"}
    for t in (leaderboard or {}).get("teams") or []:
        if isinstance(t, dict) and t.get("team") and t.get("name"):
            out[t["team"]] = t["name"]
    return {k: v for k, v in out.items() if isinstance(k, str) and isinstance(v, str)}


def albums(leaderboard: dict | None) -> dict:
    """team -> (album_filled, pages_complete) from the public leaderboard."""
    out = {}
    for t in (leaderboard or {}).get("teams") or []:
        if isinstance(t, dict) and isinstance(t.get("album_filled"), int):
            out[t["team"]] = (t["album_filled"], t.get("pages_complete") if isinstance(t.get("pages_complete"), int) else None)
    return out


def page_cards(cat: dict) -> dict:
    """set -> its page cards (commons, uncommons, rares), released sets only."""
    out = {}
    for s in cat.get("sets") or []:
        if not s.get("released"):
            continue
        refs = [c["id"] for c in s.get("cards") or [] if c.get("page", c.get("rarity") in ("common", "uncommon", "rare"))]
        if refs:
            out[s["id"]] = refs
    return out


def card_info(cat: dict) -> dict:
    return {c["id"]: {"rarity": c.get("rarity"), "book": c.get("book") or 0, "name": c.get("name"),
                      "set": s["id"], "set_name": s.get("name"),
                      "left": (c["print_run"] - c["minted"]) if isinstance(c.get("print_run"), int)
                      and isinstance(c.get("minted"), int) else None}
            for s in cat.get("sets") or [] for c in s.get("cards") or []}


def holdings(deck: dict) -> collections.Counter:
    """Copies we can name (assets seen in the feed, plus gifts and Workshop cards without an id)."""
    c = collections.Counter(deck.get("known") or {})
    c.update(deck.get("floating") or {})
    return c


def last_moves(events: list) -> dict:
    """team -> tick of its last public move (an offer, a dealer conversation, a trade)."""
    last = {}
    for e in events:
        p, who = e.get("payload") or {}, set()
        if e.get("type") in ("thread.opened", "thread.message"):
            who.add(p.get("team"))
        elif e.get("type") == "offer.listed" and isinstance(p.get("offer"), dict):
            who.add(p["offer"].get("maker"))
        elif e.get("type") == "settlement":
            who.update(p.get("parties") or [])
        for t in who:
            if isinstance(t, str):
                last[t] = e["tick"]
    return last


def demand(events: list, since: int) -> dict:
    """(team, ref) -> [evidence] from `since`: bids for that card on any venue and requests to a dealer for it.
    A team that bids for a card or asks a dealer for it wants a copy now."""
    out = collections.defaultdict(list)
    for e in events:
        if e["tick"] < since:
            continue
        p = e.get("payload") or {}
        if e.get("type") == "thread.opened" and p.get("kind") == "persona":
            ref = ((p.get("topic") or {}).get("buy") or {}).get("card")
            if isinstance(ref, str) and isinstance(p.get("team"), str):
                out[(p["team"], ref)].append({"kind": "dealer", "dealer": p.get("with"), "tick": e["tick"]})
        elif e.get("type") == "offer.listed":
            o = p.get("offer") or {}
            g, w = o.get("give") or {}, o.get("want") or {}
            if g.get("assets") or not g.get("cash"):
                continue
            for t in w.get("types") or []:
                if isinstance(t, str) and t.startswith("card:") and isinstance(o.get("maker"), str):
                    out[(o["maker"], t[5:])].append({"kind": "bid", "venue": o.get("venue") or "rastro",
                                                     "price": g.get("cash"), "offer": o.get("id"), "tick": e["tick"]})
    return out


# ---------------------------------------------------------------- pages

def near_pages(held: collections.Counter, pages: dict, max_missing: int = MAX_MISSING) -> list:
    """[(set, have, size, [missing refs])] for pages with 1..max_missing cards not named in the team's deck."""
    out = []
    for s, refs in pages.items():
        missing = [r for r in refs if held.get(r, 0) <= 0]
        if 1 <= len(missing) <= max_missing:
            out.append((s, len(refs) - len(missing), len(refs), missing))
    return out


RARITY_WEIGHT = {"common": 1.0, "uncommon": 0.4, "rare": 0.15}   # an unseen card is more often a common: starter hands
                                                                   # are 11 commons, 3 uncommons, 1 rare; packs alike


def missing_odds(held: collections.Counter, pages: dict, album: tuple | None, rarity: dict | None = None) -> dict:
    """How sure we are that the team lacks each page card we cannot name, from the leaderboard's album count.
    `unseen` = album_filled minus the page cards we can name: exactly that many of the unnamed page cards are in fact
    held, and exactly pages_complete pages are complete. Every way of choosing which unnamed cards are held that fits
    both counts is weighed (each card by RARITY_WEIGHT: an unseen card is more likely a common), set by set with a
    forward-backward pass; p[ref] = the weight of the ways where ref is NOT held. Without an album count every
    unnamed card gets 0.5; with counts that no choice fits (our deck names a card the team burned), the count of
    complete pages is dropped, then everything falls back to 1 - unseen / unnamed."""
    rarity = rarity or {}
    sets = list(pages)
    unnamed = {s: [r for r in pages[s] if held.get(r, 0) <= 0] for s in sets}
    named = sum(len(pages[s]) - len(unnamed[s]) for s in sets)
    complete = sum(1 for s in sets if not unnamed[s])
    out = {"unseen": None, "named": named, "complete_named": complete, "pages_exact": False,
           "p": {r: 0.5 for s in sets for r in unnamed[s]}}
    if not album:
        return out
    filled, pages_complete = album
    unseen = max(0, filled - named)
    out["unseen"] = unseen
    total_unnamed = sum(len(u) for u in unnamed.values())

    def options(s):
        """[(weight, k held, completes the page, frozenset held)] for every subset of the set's unnamed cards."""
        u, res = unnamed[s], []
        for mask in range(1 << len(u)):
            chosen = frozenset(u[i] for i in range(len(u)) if mask >> i & 1)
            w = 1.0
            for r in chosen:
                w *= RARITY_WEIGHT.get(rarity.get(r), 0.5)
            res.append((w, len(chosen), bool(u) and len(chosen) == len(u), chosen))
        return res

    if any(len(u) > 12 for u in unnamed.values()):
        return {**out, "p": {r: round(1 - unseen / total_unnamed, 3) if total_unnamed else 0.0
                             for u in unnamed.values() for r in u}}
    opts = [options(s) for s in sets]

    def solve(use_pages: bool):
        target_c = (pages_complete - complete) if (use_pages and pages_complete is not None) else None

        def step(dist, o):
            nxt = collections.defaultdict(float)
            for (k, c), w in dist.items():
                for ow, ok, oc, _ in o:
                    if k + ok <= unseen:
                        nxt[(k + ok, c + oc)] += w * ow
            return nxt
        fwd = [{(0, 0): 1.0}]
        for o in opts:
            fwd.append(step(fwd[-1], o))
        bwd = [None] * (len(opts) + 1)
        bwd[-1] = {(0, 0): 1.0}
        for i in range(len(opts) - 1, -1, -1):
            bwd[i] = step(bwd[i + 1], opts[i])

        def ok(k, c):
            return k == unseen and (target_c is None or c == target_c)
        total = sum(w for (k, c), w in fwd[-1].items() if ok(k, c))
        if total <= 0:
            return None
        p = {}
        for i, s in enumerate(sets):
            held_w = collections.Counter()
            for (k1, c1), w1 in fwd[i].items():
                for ow, ok_, oc, chosen in opts[i]:
                    for (k2, c2), w2 in bwd[i + 1].items():
                        if ok(k1 + ok_ + k2, c1 + oc + c2):
                            for r in chosen:
                                held_w[r] += w1 * ow * w2
            for r in unnamed[s]:
                p[r] = round(max(0.0, min(1.0, 1 - held_w[r] / total)), 3)
        return p
    p = solve(True)
    exact = p is not None and pages_complete is not None
    if p is None:
        p = solve(False)
    if p is None:
        p = {r: round(1 - unseen / total_unnamed, 3) if total_unnamed else 0.0 for u in unnamed.values() for r in u}
    return {**out, "p": p, "pages_exact": exact}


# ---------------------------------------------------------------- books

def offer_shape(o: dict):
    """("ask", ref, price, asset id) | ("bid", ref, price, None) for a plain one-card cash offer, else None."""
    if not isinstance(o, dict):
        return None
    g, w = o.get("give") or {}, o.get("want") or {}
    if not isinstance(g, dict) or not isinstance(w, dict) or g.get("types") or w.get("assets"):
        return None
    ga, wt = g.get("assets") or [], w.get("types") or []
    if len(ga) == 1 and isinstance(ga[0], dict) and ga[0].get("kind") == "card" and not wt and not g.get("cash") \
            and isinstance(w.get("cash"), int) and w["cash"] > 0:
        return ("ask", ga[0].get("ref"), w["cash"], ga[0].get("id"))
    if not ga and len(wt) == 1 and isinstance(wt[0], str) and wt[0].startswith("card:") and not w.get("cash") \
            and isinstance(g.get("cash"), int) and g["cash"] > 0:
        return ("bid", wt[0][5:], g["cash"], None)
    return None


def offer_makers(events: list) -> dict:
    """{offer id: team} from the feed's offer.listed events (every listing names its maker)."""
    out = {}
    for e in events:
        if e.get("type") == "offer.listed":
            o = (e.get("payload") or {}).get("offer") or {}
            if o.get("id") is not None and isinstance(o.get("maker"), str):
                out[o["id"]] = o["maker"]
    return out


def learn_pseudonyms(books: dict, names: dict) -> dict:
    """A pseudonym is one team on one venue: an offer the feed names ties every other offer of that pseudonym on that
    venue to the same team (announce.learn_pseudonyms, kept here so this file reads no key-holding module)."""
    out = dict(names)
    for venue, book in (books or {}).items():
        alias = {}
        for o in book or []:
            t, m = out.get(o.get("id")), o.get("maker")
            if isinstance(t, str) and t[:1] == "t" and m and m != t:
                alias[m] = t
        for o in book or []:
            if o.get("id") not in out and o.get("maker") in alias:
                out[o["id"]] = alias[o["maker"]]
    return out


def venue_fees(venues: list) -> dict:
    out = {"rastro": (500, 1)}
    for v in venues or []:
        if isinstance(v, dict) and v.get("venue"):
            out[v["venue"]] = (v.get("fee_bps") or 0, v.get("fee_per_card") or 0)
    return out


def fee_of(fee, price: int) -> int:
    bps, per_card = fee or (0, 0)
    return math.ceil((bps or 0) * price / 10000) + (per_card or 0)


def live_offers(books: dict, names: dict, fees: dict) -> dict:
    """ref -> {"asks": [...], "bids": [...]} over every venue's open, undirected or directed, plain cash offers,
    each {venue, offer, price, team, to, asset, fee}. Our venue's own book is included (a v20 order is the best news
    of all). Team 3's offers, offers addressed to us and offers the feed cannot tie to a team are left out."""
    out = collections.defaultdict(lambda: {"asks": [], "bids": []})
    for venue, book in (books or {}).items():
        for o in book or []:
            if not isinstance(o, dict) or o.get("status", "open") != "open":
                continue
            sh = offer_shape(o)
            if sh is None or not isinstance(sh[1], str):
                continue
            team = names.get(o.get("id"))
            if not (isinstance(team, str) and team[:1] == "t" and team[1:].isdigit()) or team == US \
                    or o.get("maker") == US or o.get("to") == US:
                continue   # an offer the feed cannot name could be ours: never pointed at
            row = {"venue": venue, "offer": o.get("id"), "price": sh[2], "team": team,
                   "to": o.get("to"), "asset": sh[3], "fee": fee_of(fees.get(venue, (0, 0)), sh[2]),
                   "expires_tick": o.get("expires_tick")}
            out[sh[1]]["asks" if sh[0] == "ask" else "bids"].append(row)
    for v in out.values():
        v["asks"].sort(key=lambda r: r["price"] + r["fee"])
        v["bids"].sort(key=lambda r: -r["price"])
    return out


# ---------------------------------------------------------------- prices

def dealer_rows(dprices: dict, rarity: str) -> tuple:
    """([(dealer, row)] that sell this rarity, [(dealer, row)] that buy it), from price_index's measured closes."""
    sells = [(d, dprices[f"{d}/sells/{rarity}"]) for d in DEALERS_SELL.get(rarity, ()) if f"{d}/sells/{rarity}" in dprices]
    buys = [(d, dprices[f"{d}/buys/{rarity}"]) for d in DEALERS_BUY.get(rarity, ()) if f"{d}/buys/{rarity}" in dprices]
    return sells, buys


def suggest_price(fair, team_median, sell_floor, buy_cap) -> int | None:
    """One price both sides can post: the card's fair price (else the rarity's team median), kept between what the
    holder gets from a dealer (`sell_floor`: below it the holder sells to the dealer instead) and what the buyer pays
    a dealer (`buy_cap`: above it the buyer goes to the dealer). When the floor is above the cap, their midpoint."""
    p = fair if fair else team_median
    if not p:
        return None
    lo, hi = sell_floor or 0, buy_cap or 10**9
    if lo > hi:
        return int(round((lo + hi) / 2))
    return int(round(min(max(p, lo), hi)))


def proposal(buyer: str, ref: str, price: int | None, sellers: list, live: dict | None) -> dict:
    """The exact orders: the buyer's bid on v20, each seller's ask on v20 (its named asset id), and the live offers
    elsewhere that already do it (an ask the buyer can accept, a bid of the buyer's the sellers can accept)."""
    out = {"venue": VENUE, "price": price, "buyer": None, "sellers": [], "accept": []}
    if price:
        out["buyer"] = {"team": buyer, "post": {"venue": VENUE, "give": {"cash": price}, "want": {"cards": [ref]},
                                                "expires_in_ticks": ORDER_TICKS}}
        for s in sellers:
            if s.get("asset") is not None:
                out["sellers"].append({"team": s["team"], "post": {"venue": VENUE, "give": {"assets": [s["asset"]]},
                                                                   "want": {"cash": price},
                                                                   "expires_in_ticks": ORDER_TICKS}})
    holders = {s["team"] for s in sellers}
    for a in (live or {}).get("asks", []):
        if a["team"] != buyer and a.get("to") in (None, buyer):
            out["accept"].append({"who": buyer, "offer": a["offer"], "venue": a["venue"], "side": "ask",
                                  "price": a["price"], "fee": a["fee"], "team": a["team"],
                                  "call": f"POST /api/offers/{a['offer']}/accept"})
    for b in (live or {}).get("bids", []):
        if b["team"] == buyer and (b.get("to") is None or b.get("to") in holders):
            out["accept"].append({"who": sorted(holders) if b.get("to") is None else [b["to"]], "offer": b["offer"],
                                  "venue": b["venue"], "side": "bid", "price": b["price"], "fee": b["fee"],
                                  "team": buyer, "call": f"POST /api/offers/{b['offer']}/accept"})
    out["accept"] = out["accept"][:4]
    return out


# ---------------------------------------------------------------- the build

def team_values(events: list, cat: dict) -> dict:
    """team -> expected multiplier per set (tools/value_inference.py, Bayes over the public evidence)."""
    book = {c["id"]: c["book"] for s in cat["sets"] for c in s["cards"]}
    sets = [s["id"] for s in cat["sets"]]
    by_team = vi.evidence(events, book)
    seen = {ev["set"] for evs in by_team.values() for ev in evs}
    in_play = [s["id"] for s in cat["sets"] if s.get("released") or s["id"] in seen]
    model = vi.Model(sets, in_play, book)
    return {t: model.summary(model.posterior(evs), evs)["expected"] for t, evs in by_team.items()}


def build(events: list, cat: dict, leaderboard: dict | None = None, books: dict | None = None,
          venues: list | None = None, exclude=(), values: dict | None = None, now_tick: int | None = None,
          dprices: dict | None = None) -> dict:
    """Every match: a rival team one or two cards from a page, the card, who holds a spare, the prices, the live
    offers and the orders. Pure: the caller passes every input. Team 3 is never a buyer or a holder; cards in
    `exclude` never appear."""
    events = dedupe(events)
    now_tick = now_tick if isinstance(now_tick, int) else (events[-1]["tick"] if events else 0)
    skip = set(exclude or ())
    info, pages = card_info(cat), page_cards(cat)
    page_book = {s: sum(info[r]["book"] for r in refs) for s, refs in pages.items()}
    bonus = ((cat.get("values") or {}).get("page_bonus")) or PAGE_BONUS
    deck = decks.build(events, cat)
    names = team_names(events, leaderboard)
    alb = albums(leaderboard)
    held = {t: holdings(d) for t, d in deck.items()}
    last = last_moves(events)
    want = demand(events, now_tick - DEMAND_TICKS)
    trades = fairprice.cash_trades(events)
    tindex = price_index.team_index(events, {r: i["rarity"] for r, i in info.items()})["all"]["rarity"]
    if dprices is None:
        _, kind_of, kind_of_topic = price_index.card_kinds(cat)
        dprices = price_index.dealer_prices(events, kind_of, kind_of_topic)
    makers = learn_pseudonyms(books or {}, offer_makers(events))
    live = live_offers(books or {}, makers, venue_fees(venues))
    values = values or {}
    matches, teams, withheld = [], {}, 0
    for team in sorted(deck):
        if team == US:
            continue
        odds = missing_odds(held[team], pages, alb.get(team), {r: i["rarity"] for r, i in info.items()})
        active = now_tick - last.get(team, -10**9) <= ACTIVE_TICKS
        near = near_pages(held[team], pages)
        teams[team] = {"name": names.get(team, team), "album": (alb.get(team) or (None, None))[0],
                       "pages_complete": (alb.get(team) or (None, None))[1], "named_page_cards": odds["named"],
                       "unseen": odds["unseen"], "pages_exact": odds["pages_exact"], "active": active,
                       "last_move_tick": last.get(team),
                       "near_pages": [{"set": s, "have": h, "size": n, "missing": m} for s, h, n, m in near]}
        for s, have, size, missing in near:
            for ref in missing:
                if ref in skip:
                    withheld += 1
                    continue
                ci = info.get(ref) or {}
                rarity = ci.get("rarity")
                p = odds["p"].get(ref, 0.5)
                asked = want.get((team, ref), [])
                if asked:
                    p = max(p, 0.9)  # it asked for this very card lately
                if p < MIN_P:
                    continue
                sellers = []
                for other, h in held.items():
                    if other in (team, US) or h.get(ref, 0) <= 0:
                        continue
                    spare = h[ref] >= SPARE_MIN
                    far = sum(1 for r in pages[s] if h.get(r, 0) <= 0) >= FAR_PAGE
                    low = (values.get(other) or {}).get(s, 1.02) <= LOW_MULT
                    if not spare and not (far and low):
                        continue
                    ids = (deck[other].get("assets") or {}).get(ref) or []
                    sellers.append({"team": other, "name": names.get(other, other), "copies": h[ref], "spare": spare,
                                    "asset": ids[-1] if ids else None, "active": now_tick - last.get(other, -10**9)
                                    <= ACTIVE_TICKS})
                lv = live.get(ref) or {"asks": [], "bids": []}
                for a in lv["asks"]:   # a team asking for cash for this card right now holds it and sells it
                    if a["team"] in (team, US) or a.get("to") not in (None, team):
                        continue
                    row = next((x for x in sellers if x["team"] == a["team"]), None)
                    if row is None:
                        row = {"team": a["team"], "name": names.get(a["team"], a["team"]),
                               "copies": held.get(a["team"], {}).get(ref, 1) or 1, "spare": False,
                               "asset": a.get("asset"), "active": True}
                        sellers.append(row)
                    row["asking"] = {"price": a["price"], "venue": a["venue"], "offer": a["offer"]}
                sellers.sort(key=lambda x: ("asking" not in x, not x["active"], x["asset"] is None, not x["spare"],
                                            -x["copies"], x["team"]))
                sells, buys = dealer_rows(dprices, rarity)
                left = ci.get("left")
                dealers = [{"dealer": d, "name": DEALER_NAMES.get(d, d), "sells": {k: r.get(k) for k in PRICE_FIELDS},
                            "n": r.get("n")} for d, r in sells] if left is None or left > 0 else []
                fair = fairprice.fair_price(list(reversed(trades.get(ref, []))))
                trng = tindex.get(rarity) or {}
                sell_floor = max((r.get("median") or 0 for _, r in buys), default=0) or None
                buy_cap = min((r.get("median") or 10**9 for _, r in sells), default=None) if dealers else None
                price = suggest_price(fair.get("price"), trng.get("median") or ci.get("book"), sell_floor, buy_cap)
                mult = (values.get(team) or {}).get(s, 1.02)
                gain = mult * (ci.get("book", 0) + bonus * page_book.get(s, 0) / len(missing))
                feasible = 1.0 if (sellers or lv["asks"]) else (0.5 if dealers else 0.1)
                score = p * feasible * (1.0 if active else IDLE_FACTOR) * gain
                matches.append({
                    "team": team, "team_name": names.get(team, team), "set": s, "set_name": ci.get("set_name"),
                    "have": have, "size": size, "missing": missing, "card": ref, "card_name": ci.get("name"),
                    "rarity": rarity, "p_missing": round(p, 2), "pages_exact": odds["pages_exact"],
                    "buyer_active": active, "buyer_mult": round(mult, 2), "demand": asked[-3:],
                    "holders": sellers[:4], "dealers": dealers, "dealer_left": left,
                    "prices": {"fair": fair.get("price"), "fair_text": fair.get("text"), "team_range": fair.get("range"),
                               "rarity_median": trng.get("median"),
                               "dealer_sells": {d: r.get("median") for d, r in sells},
                               "dealer_buys": {d: r.get("median") for d, r in buys}},
                    "live": {"asks": lv["asks"][:3], "bids": [b for b in lv["bids"] if b["team"] == team][:3]},
                    "price": price, "proposal": proposal(team, ref, price, sellers[:3], lv),
                    "score": round(score, 1)})
    matches.sort(key=lambda m: (-m["score"], m["team"], m["card"]))
    for i, m in enumerate(matches, 1):
        m["rank"] = i
    return {"generated_at": round(time.time()), "tick": now_tick, "venue": VENUE, "matches": matches, "teams": teams,
            "withheld": withheld, "rules": {"max_missing": MAX_MISSING, "spare_min": SPARE_MIN,
                                            "active_ticks": ACTIVE_TICKS, "order_ticks": ORDER_TICKS}}


# ---------------------------------------------------------------- output

def who_holds(m: dict, n: int = 2) -> list:
    """Public names of who can supply the card: teams with a spare (active first), then the dealers that sell it."""
    out = [h["name"] for h in m.get("holders", [])[:n]]
    out += [d["name"] for d in m.get("dealers", [])[:1]]
    return out


def report(res: dict, top: int = 15) -> str:
    lines = [f"# La Celestina matchmaker — tick {res['tick']}", "",
             f"{len(res['matches'])} matches (a rival one or two cards from a page); {res['withheld']} withheld "
             f"(cards in --exclude). Price = the card's fair price kept between the dealers' buy and sell closes.", "",
             "| # | buyer | page | card | p missing | spare holders | dealers sell | price | live | score |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for m in res["matches"][:top]:
        holders = ", ".join(f"{h['name']} ×{h['copies']}" + ("" if h["active"] else " (idle)") for h in m["holders"]) or "—"
        dl = ", ".join(f"{d['name']} ~{d['sells'].get('median')}" for d in m["dealers"]) or "—"
        live = "; ".join(f"ask {a['price']} on {a['venue']} #{a['offer']}" for a in m["live"]["asks"][:2])
        live += ("; " if live and m["live"]["bids"] else "") + "; ".join(
            f"its bid {b['price']} on {b['venue']} #{b['offer']}" for b in m["live"]["bids"][:2])
        lines.append(f"| {m['rank']} | {m['team_name']}{'' if m['buyer_active'] else ' (idle)'} | {m['set']} "
                     f"{m['have']}/{m['size']} | {m['card']} ({m['rarity']}) | {m['p_missing']:.2f} | {holders} | {dl} | "
                     f"{m['price'] if m['price'] is not None else '—'} (fair {m['prices']['fair']}) | {live or '—'} | "
                     f"{m['score']} |")
    lines += ["", "## Orders for the top matches", ""]
    for m in res["matches"][:min(top, 5)]:
        pr = m["proposal"]
        lines.append(f"**{m['team_name']} · {m['card']}** ({m['card_name']}), {m['set_name']} {m['have']}/{m['size']}")
        if pr["buyer"]:
            lines.append(f"- buyer posts: `POST /api/offers {json.dumps(pr['buyer']['post'])}`")
        for s in pr["sellers"]:
            lines.append(f"- {res['teams'].get(s['team'], {}).get('name', s['team'])} posts: "
                         f"`POST /api/offers {json.dumps(s['post'])}`")
        for a in pr["accept"]:
            lines.append(f"- or accept offer #{a['offer']} on {a['venue']} ({a['side']} {a['price']} P + fee {a['fee']}): "
                         f"`{a['call']}`")
        lines.append("")
    lines += ["## Pages one or two cards from complete, per team", ""]
    for t, d in sorted(res["teams"].items()):
        if not d["near_pages"]:
            continue
        pages = "; ".join(f"{p['set']} {p['have']}/{p['size']} lacks {', '.join(p['missing'])}" for p in d["near_pages"])
        lines.append(f"- {d['name']} ({t}): album {d['album']}, pages {d['pages_complete']}, named page cards "
                     f"{d['named_page_cards']}, unseen {d['unseen']}{', pages exact' if d['pages_exact'] else ''}"
                     f"{'' if d['active'] else ', idle'}: {pages}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- live reads

def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
        return json.load(r)


def live_inputs(get, gate=None) -> dict:
    """Keyless reads: the feed window, catalog, leaderboard, venues and every open venue's book (El Rastro too).
    `gate.check()` runs before every request (Market Test silence)."""
    def api(path):
        if gate is not None:
            gate.check()
        return get(f"{URL}{path}")
    out = {"events": api("/api/feed?limit=1000").get("events", []), "catalog": api("/api/catalog"),
           "leaderboard": api("/api/leaderboard")}
    venues = [v for v in api("/api/venues").get("venues", []) if isinstance(v, dict)]
    out["venues"], out["books"] = venues, {}
    for v in ["rastro"] + [v["venue"] for v in venues if v.get("status") == "open" and v.get("venue")]:
        try:
            out["books"][v] = [dict(o, venue=v) for o in api(f"/api/venues/{v}/offers").get("offers") or []
                               if isinstance(o, dict)]
        except Exception as e:  # noqa: BLE001 — one unreadable book costs that venue only (a silence propagates)
            if type(e).__name__ == "Silenced":
                raise
            print(f"book of {v} unavailable ({type(e).__name__})", file=sys.stderr)
    return out


def offline_inputs(feed_dir: Path) -> dict:
    """The recorded feed, the cached catalog, the last leaderboard and venue snapshots, and the last recorded book of
    every venue (the recorder keeps El Rastro's board and the venues' books)."""
    books, last = {}, {}
    try:
        with open(feed_dir / SNAPSHOTS, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                what, body = row.get("what"), row.get("body")
                if what == "rastro" and isinstance(body, dict):
                    books["rastro"] = [dict(o, venue="rastro") for o in body.get("offers") or [] if isinstance(o, dict)]
                elif what == "book" and isinstance(body, dict) and body.get("venue"):
                    books[body["venue"]] = [dict(o, venue=body["venue"]) for o in body.get("offers") or []
                                            if isinstance(o, dict)]
                elif what in ("leaderboard", "venues"):
                    last[what] = body
    except OSError:
        pass
    venues = (last.get("venues") or {}).get("venues") if isinstance(last.get("venues"), dict) else last.get("venues")
    return {"events": [json.loads(x) for x in (feed_dir / "feed.jsonl").read_text(encoding="utf-8").splitlines()
                       if x.strip()] if (feed_dir / "feed.jsonl").exists() else [],
            "catalog": vi.catalog(), "leaderboard": last.get("leaderboard"), "venues": venues or [], "books": books}


def run_once(args, gate=None) -> dict:
    feed_dir = Path(args.feed).expanduser() if args.feed else vi.FEED
    data = offline_inputs(feed_dir)
    if args.live:
        fresh = live_inputs(get_json, gate)
        data = {**fresh, "events": data["events"] + fresh["events"]}
    exclude = tuple(x.strip() for x in (args.exclude or "").split(",") if x.strip())
    values = {} if args.no_values else team_values(dedupe(data["events"]), data["catalog"])
    return build(data["events"], data["catalog"], data["leaderboard"], data["books"], data["venues"], exclude, values)


def write_out(res: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)   # readers (announce, celestina, outreach) never see half a file


def default_exclude() -> str:
    try:
        sys.path.insert(0, str(ROOT / "kit"))
        sys.path.insert(0, str(ROOT / "agent"))
        import announce   # noqa: E402  (the list of cards Team 3 lacks lives there)
        return ",".join(announce.MISSING)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- selftest

def sample() -> tuple:
    """A tiny game: LAV has 4 page cards; t01 holds three of them, t02 holds two copies of the fourth, t03 (us) holds
    a spare too and is missing one; a live ask for the card on El Rastro."""
    cat = {"sets": [{"id": "LAV", "name": "Lavapiés", "released": True, "cards": [
        {"id": f"LAV-0{i}", "name": f"Card {i}", "rarity": "common" if i < 4 else "rare", "book": 10 if i < 4 else 70,
         "print_run": 300 if i < 4 else 30, "minted": 20, "page": True} for i in range(1, 5)]}],
        "packs": [], "values": {"page_bonus": 0.25}}

    def ev(i, tick, etype, **p):
        return {"id": i, "tick": tick, "type": etype, "payload": p}

    def lst(i, tick, maker, aid, ref, cash, venue="rastro", oid=None):
        return ev(i, tick, "offer.listed", offer={"id": oid or 1000 + i, "maker": maker, "venue": venue, "give": {
            "cash": 0, "assets": [{"id": aid, "kind": "card", "ref": ref}], "types": []},
            "want": {"cash": cash, "assets": [], "types": []}})
    n = decks.STARTER
    events = [ev(1, 0, "team.joined", team="t01", name="Team 1"), ev(2, 0, "team.joined", team="t02", name="Team 2"),
              ev(3, 0, "team.joined", team="t03", name="Team 3"),
              lst(4, 5, "t01", 1, "LAV-01", 9), lst(5, 5, "t01", 2, "LAV-02", 9), lst(6, 5, "t01", 3, "LAV-03", 9),
              lst(7, 6, "t02", n + 1, "LAV-04", 90), lst(8, 6, "t02", n + 2, "LAV-04", 90),
              lst(9, 6, "t03", 2 * n + 1, "LAV-04", 90), lst(10, 6, "t03", 2 * n + 2, "LAV-04", 90),
              ev(11, 7, "settlement", parties=["t02", "t05"], venue="rastro", persona=None, price=72,
                 items=[{"id": 999, "kind": "card", "ref": "LAV-04", "frm": "t02", "to": "t05"}]),
              ev(12, 8, "thread.opened", thread=1, kind="persona", team="t01", **{"with": "chato"},
                 topic={"buy": {"card": "LAV-04"}})]
    lb = {"teams": [{"team": "t01", "name": "Team 1", "album_filled": 3, "pages_complete": 0},
                    {"team": "t02", "name": "Team 2", "album_filled": 1, "pages_complete": 0}]}
    books = {"rastro": [{"id": 1007, "maker": "m2", "status": "open", "give": {"cash": 0, "assets": [
        {"id": n + 1, "kind": "card", "ref": "LAV-04"}], "types": []}, "want": {"cash": 90, "assets": [], "types": []}}]}
    return events, cat, lb, books


def selftest() -> None:
    events, cat, lb, books = sample()
    res = build(events, cat, lb, books, [], exclude=(), values={})
    by = {(m["team"], m["card"]): m for m in res["matches"]}
    assert ("t01", "LAV-04") in by, res["matches"]
    m = by[("t01", "LAV-04")]
    assert [h["team"] for h in m["holders"]] == ["t02"], m["holders"]          # never t03, though it has two
    assert m["p_missing"] == 1.0 and m["proposal"]["buyer"]["post"]["want"] == {"cards": ["LAV-04"]}
    assert m["proposal"]["sellers"][0]["post"]["give"] == {"assets": [decks.STARTER + 2]}
    assert m["proposal"]["accept"] and m["proposal"]["accept"][0]["offer"] == 1007
    assert all(m["team"] != US for m in res["matches"])
    assert not build(events, cat, lb, books, [], exclude=("LAV-04",), values={})["matches"]
    text = report(res)
    assert "Team 3" not in text and "t03" not in text, text
    print(f"selftest ok: {len(res['matches'])} match, holder {m['holders'][0]['name']}, price {m['price']}, "
          f"live offer #{m['proposal']['accept'][0]['offer']}")


# ---------------------------------------------------------------- main

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Rival teams' missing page cards, who holds spares, and the v20 orders.")
    ap.add_argument("cmd", choices=["report", "json", "selftest"])
    ap.add_argument("--live", action="store_true", help="add live keyless reads (feed window, leaderboard, books)")
    ap.add_argument("--feed", default=None, help="the recorder's directory (default: BAZAAR_FEED or logs/feed)")
    ap.add_argument("--exclude", default=None, help="comma list of cards never shown (default: announce.MISSING)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", default=None, help="json: write here (atomically) instead of printing")
    ap.add_argument("--every", type=float, default=0, help="json --out: rebuild every N seconds (silence respected)")
    ap.add_argument("--no-values", action="store_true", help="skip the value inference (faster; multiplier 1.02)")
    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    if args.exclude is None:
        args.exclude = default_exclude()
    gate = None
    if args.live:
        sys.path.insert(0, str(ROOT / "kit"))
        sys.path.insert(0, str(ROOT / "agent"))
        import announce   # noqa: E402  (the Market Test gate every lane shares)
        gate = announce.Gate()
    while True:
        try:
            if gate is not None and not gate.known():
                gate.refresh(get_json)
                if not gate.known():
                    raise RuntimeError("Market Test status unknown")
            res = run_once(args, gate)
        except Exception as e:  # noqa: BLE001 — Silenced or a failed read: try again after the pause
            print(f"[{time.strftime('%H:%M:%S')}] no build ({type(e).__name__}: {e})", file=sys.stderr)
            if not args.every:
                raise SystemExit(1)
            time.sleep(args.every)
            continue
        if args.cmd == "report":
            print(report(res, args.top))
        elif args.out:
            write_out(res, Path(args.out))
            print(f"[{time.strftime('%H:%M:%S')}] tick {res['tick']}: {len(res['matches'])} matches -> {args.out}",
                  file=sys.stderr)
        else:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        if not args.every or args.cmd != "json":
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
