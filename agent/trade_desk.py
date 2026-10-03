"""Trade desk: the standing trade engine (H2, team bus #5970008367 / #5970219418 / #5970220806), SHADOW BY DEFAULT.

A narrower, separate engine from agent/market_desk.py: a new file that imports market_desk's own offer validators and
fee math instead of editing it, so it cannot collide with live edits there. Three jobs, each a pure gain rule at our
private values. Words are never read: only the give/want structure, checked exactly (a switched or padded offer is
not a match).

  1. ACCEPT an open offer, in our inbox (GET /api/me/offers, addressed to us) or on El Rastro's board, that is a
     clean one-card-for-cash listing or bid (market_desk.check_listing / check_bid) when its surplus at our private
     values is at least --margin (3 P):
         buy:  value of one more copy (live /api/me/value) - price - fee
         sell: price - fee - the value of the very copy we would give up (that asset's own your_value)
     Never the wrong side of value. A sell may be a single copy (low-multiplier cards are sold above value, single
     copies included) EXCEPT our only copy of a card in a --protect set (LAT LAV SAL). Cash after a buy must stay at
     or above --reserve (40 P), except the --page-card buy, which may go down to --reserve-last-card (10 P).
  2. BID (post a want-to-buy on El Rastro, never accept a dealer's offer) for --page-card (LAV-10) ONLY once every
     other card of its page is held (read live from /api/me's album), ONLY if we have no live bid for it, and ONLY
     at a price a human named: --page-bid-price. The desk never opens a bid by itself at "value - margin", which is
     the WORST price we would accept, not a price to offer (sellers have taken 58 to 96 P for rares like this).
     With no --page-bid-price it logs the ceiling and does not post. The price is capped at the ceiling. The page
     card is also never ACCEPTED (rule 1) before its page is ready.

NOT done here, on purpose: listing spares for sale. agent/rastro_seller.py already owns that (a high anchor that
steps down to a floor, agent/rastro_floors.json); a desk listing at value + margin would undersell and compete with
it. This desk sells by ACCEPTING other teams' bids and inbox offers that clear the margin.

Venue routing: everything stays on El Rastro, or on a venue named in --pact-venue (empty until a pact lands). Never
v02 or v07 (capped, worth nothing to anyone, per the bus) and never our own v20 (the server refuses a self-trade).
An inbox offer that sits on a rival venue is therefore skipped, not accepted.

Safety, enforced in code:
  - SHADOW BY DEFAULT. Without --live the desk holds a ReadOnlyBazaar client that refuses every non-GET request
    before it leaves the machine, so shadow mode cannot write even through a bug. --live is the only way to send.
  - STOP FILE (--stop-file, default results/trade_desk.stop): if it exists the pass reads only the clock, logs one
    line and does nothing else, even under --live.
  - One accept per tick for the whole team: before any send, results/duel.lock and GET /api/duels are checked, and
    any live duel of ours (or an unreadable lock / failed read) defers the WHOLE pass, bids and listings too. In
    live mode one pass sends at most ONE write (an accept, else a bid, else a listing).
  - Market Test window: GET /api/schedule's "bench" events (never a hardcoded clock) make the desk quiet around a
    test on our venue: it still logs, sends nothing.
  - At most one full pass per tick; HTTP 429 backs off 30 s. Values are cached per (card, copies held) and a cache
    miss waits 0.3 s, because the key's 5 req/s budget is shared with the duel bot and the broker.
  - Every decision is one row straight into logs/decisions.jsonl, in the shape every lane agreed on the bus:
        {ts, tick, lane: "trade_desk", action, card, price, our_value, surplus, why, result}
    A row repeats only when something about it changed (price, gain, reason, result).

    python3 agent/trade_desk.py plan                      # one read-only pass, prints every decision, sends nothing
    python3 agent/trade_desk.py run                       # shadow loop: logs what it WOULD do each tick, sends nothing
    python3 agent/trade_desk.py run --live                # live loop: accepts / bids / lists (needs the team key)
    python3 agent/trade_desk.py run --live --margin 5 --reserve 50 --pact-venue v06
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402
from market_desk import (DEFAULT_FEE, WORST_FEE, ReadOnlyBazaar, check_bid, check_listing, fee_for,  # noqa: E402
                          holdings_of)

URL = "https://bazaar.causaprima.ai"
HOME = "rastro"
OUR_VENUE = "v20"
BLOCKED_VENUES = frozenset({"v02", "v07"})     # named on the bus: capped, worth nothing to trade on
DUEL_LOCK = ROOT / "results" / "duel.lock"
STOP_FILE = ROOT / "results" / "trade_desk.stop"
DECISIONS = ROOT / "logs" / "decisions.jsonl"
LANE = "trade_desk"
VALUE_CALL_GAP = 0.3                            # seconds between uncached /api/me/value calls


@dataclass(frozen=True)
class Config:
    margin: int = 3                 # minimum surplus to accept, bid or list at
    reserve: int = 40               # cash that must remain after a buy
    reserve_last_card: int = 10     # looser reserve, only for the --page-card buy
    page_card: str = "LAV-10"       # the one card we may bid for, once the rest of its page is held
    page_bid_price: int | None = None        # what we open the page-card bid at; None = never post one
    protect: tuple = ("LAT", "LAV", "SAL")   # never sell our only copy of a card in these sets
    pact_venue: tuple = ()          # other teams' venues we may also use, once a pact lands
    bench_margin_hours: float = 0.10         # quiet this many game-hours either side of a Market Test
    stop_file: str = str(STOP_FILE)


# ------------------------------------------------------------------------------------------------- pure decisions

def venue_allowed(venue: str | None, cfg: Config) -> bool:
    v = venue or HOME
    if v in BLOCKED_VENUES or v == OUR_VENUE:
        return False
    return v == HOME or v in cfg.pact_venue


def venue_fee(venue: str | None) -> tuple:
    """El Rastro's fee is known; any other (pact) venue is priced at the rules' worst case until proven cheaper."""
    return DEFAULT_FEE if (venue or HOME) == HOME else WORST_FEE


def page_card_ok(album: list | None, holdings: dict, cfg: Config) -> tuple[bool, str]:
    """May we buy/bid for cfg.page_card now? Only if it is not held and its page lacks exactly that one card."""
    ref = cfg.page_card
    if ref in holdings:
        return False, "already held"
    page = next((p for p in (album or []) if p.get("set") == ref[:3]), None)
    if page is None:
        return False, f"no album data for set {ref[:3]}"
    missing = page.get("of", 0) - page.get("have", 0)
    if missing > 1:
        return False, f"page {ref[:3]} still missing {missing} cards: wait for the rest before {ref}"
    return True, f"page {ref[:3]} is complete except {ref}: from a team only, never a dealer"


def _row(action, card, price, value, surplus, why, result, **extra) -> dict:
    return {"action": action, "card": card, "price": price, "our_value": value, "surplus": surplus, "why": why,
            "result": result, **extra}


def scan_offers(offers: list, venue: str, me_id: str, our_assets: dict, holdings: dict, cfg: Config, tick: int,
                value_of, page_ok: bool) -> list[dict]:
    """Score every offer of one venue. `value_of(ref)` = the live value of one more copy. Rows with result
    'candidate' are acceptable; every other row says why not. Nothing here sends anything."""
    rows = []
    allowed = venue_allowed(venue, cfg)
    fee_t = venue_fee(venue)
    for o in offers or []:
        oid = o.get("id")
        if not allowed:
            rows.append(_row("none", None, None, None, None, f"venue {venue} is not allowed", "skipped", offer=oid, venue=venue,
                             trivial=True))
            continue
        listing = check_listing(o, me_id, tick)
        if listing["ok"]:
            ref, price = listing["ref"], listing["price"]
            if ref in holdings:
                rows.append(_row("buy", ref, price, None, None, "we already hold it (a 2nd copy is worth 25%)", "skipped",
                                 offer=oid, venue=venue, trivial=True))
                continue
            if ref == cfg.page_card and not page_ok:
                rows.append(_row("buy", ref, price, None, None, f"{ref} only once the rest of its page is held", "skipped",
                                 offer=oid, venue=venue))
                continue
            value = value_of(ref)
            fee = fee_for(price, fee_t)
            if value is None:
                rows.append(_row("buy", ref, price, None, None, "live value unreadable", "skipped", offer=oid, venue=venue))
                continue
            gain = round(value - price - fee, 2)
            ok = gain >= cfg.margin
            rows.append(_row("buy", ref, price, value, gain, f"gain {gain} {'>=' if ok else '<'} margin {cfg.margin}",
                             "candidate" if ok else "skipped", offer=oid, venue=venue, asset=listing["asset"], fee=fee))
            continue
        bid = check_bid(o, me_id, our_assets, tick)
        if bid["ok"]:
            ref, price = bid["ref"], bid["price"]
            copies = holdings.get(ref) or []
            if not copies:
                rows.append(_row("sell", ref, price, None, None, "we do not hold that card", "skipped", offer=oid, venue=venue,
                                 trivial=True))
                continue
            if len(copies) == 1 and ref[:3] in cfg.protect:
                rows.append(_row("sell", ref, price, None, None, f"our only copy of a {ref[:3]} card is never sold", "skipped",
                                 offer=oid, venue=venue))
                continue
            give = next((a for a in copies if a.get("id") == bid["asset"]), None) if bid["asset"] else \
                max(copies, key=lambda a: a.get("serial") or 0)
            value = give.get("your_value") if give else None
            if give is None or value is None:
                rows.append(_row("sell", ref, price, None, None, "the copy they ask for has no known value", "skipped",
                                 offer=oid, venue=venue))
                continue
            fee = fee_for(price, fee_t)
            gain = round(price - fee - value, 2)
            ok = gain >= cfg.margin
            rows.append(_row("sell", ref, price, value, gain, f"gain {gain} {'>=' if ok else '<'} margin {cfg.margin}",
                             "candidate" if ok else "skipped", offer=oid, venue=venue, asset=give["id"], fee=fee))
            continue
        rows.append(_row("none", None, None, None, None, listing["reason"], "not_a_match", offer=oid, venue=venue,
                         trivial=True))
    return rows


def best_accept(rows: list[dict], cash: int, cfg: Config, page_ok: bool) -> dict | None:
    """The one accept this tick: highest surplus among candidates; a buy must leave cash >= its reserve."""
    ok = []
    for r in rows:
        if r["result"] != "candidate":
            continue
        if r["action"] == "buy":
            reserve = cfg.reserve_last_card if (r["card"] == cfg.page_card and page_ok) else cfg.reserve
            if cash - r["price"] - r["fee"] < reserve:
                continue
        ok.append(r)
    return max(ok, key=lambda r: r["surplus"]) if ok else None


def page_bid_row(cfg: Config, page_ok: bool, page_why: str, has_live_bid: bool, value: float | None) -> dict:
    """The page-card bid decision. Posts only at a price a human named (--page-bid-price), never above the ceiling
    (value - margin, the worst price we would accept) and never when we already have one live."""
    if not page_ok:
        return _row("bid", cfg.page_card, None, None, None, page_why, "skipped")
    if has_live_bid:
        return _row("bid", cfg.page_card, None, value, None, "a bid for it is already live", "skipped")
    if value is None:
        return _row("bid", cfg.page_card, None, None, None, "live value unreadable", "skipped")
    ceiling = int(value) - cfg.margin
    if cfg.page_bid_price is None:
        return _row("bid", cfg.page_card, None, value, None,
                    f"page ready, ceiling {ceiling} P: no --page-bid-price set, not posting", "skipped")
    price = min(cfg.page_bid_price, ceiling)
    return _row("bid", cfg.page_card, price, value, round(value - price, 2),
                f"page ready: open at {price} P (ceiling {ceiling}), from a team only", "candidate")


def live_bid_for(my_offers: list, me_id: str, ref: str) -> bool:
    return any(o.get("maker") == me_id and o.get("status") == "open" and f"card:{ref}" in ((o.get("want") or {}).get("types") or [])
               for o in my_offers or [])


def in_bench_window(schedule_events: list, t_hours: float, tick_seconds: float, cfg: Config) -> bool:
    """True if a Market Test ("bench") starts, runs or is about to start within the quiet margin, per the live
    schedule. Its length is ticks x the CURRENT tick length (Friday 60 s, Saturday 30 s, Sunday 15 s)."""
    for e in schedule_events or []:
        if e.get("action") != "bench" or e.get("at_hours") is None:
            continue
        ticks = (e.get("params") or {}).get("ticks") or 16
        end = e["at_hours"] + ticks * float(tick_seconds or 30) / 3600
        if e["at_hours"] - cfg.bench_margin_hours <= t_hours <= end + cfg.bench_margin_hours:
            return True
    return False


# ------------------------------------------------------------------------------------------------------- the desk

def emit(row: dict, tick, said: dict, path: Path = DECISIONS) -> bool:
    """Append one decision row to logs/decisions.jsonl and print it, unless it repeats an unchanged earlier row."""
    key = (row["action"], row.get("card"), row.get("offer"), row.get("asset"))
    sig = (row.get("price"), row.get("surplus"), row.get("why"), row["result"])
    if said.get(key) == sig:
        return False
    said[key] = sig
    out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tick": tick, "lane": LANE, "action": row["action"],
           "card": row.get("card"), "price": row.get("price"), "our_value": row.get("our_value"),
           "surplus": row.get("surplus"), "why": row.get("why"), "result": row["result"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"[{out['ts'][11:]}] tick {tick} {out['action']:<5} {out['card'] or '-':<7} price={out['price']} "
          f"value={out['our_value']} surplus={out['surplus']} -> {out['result']} ({out['why']})")
    return True


def duel_is_live(b: Bazaar) -> bool:
    if DUEL_LOCK.exists():
        try:
            if float(DUEL_LOCK.read_text().split()[0]) > time.time():
                return True
        except (ValueError, IndexError):
            return True           # an unreadable lock counts as held
    try:
        return bool((b.duels() or {}).get("duels"))
    except BazaarError:
        return True               # a failed read defers too (same rule as market_desk.py)


def one_pass(b: Bazaar, cfg: Config, live: bool, clock: dict, said: dict, vcache: dict, decisions: Path = DECISIONS) -> dict:
    """Read everything, decide everything, log everything; send at most one write, and only if live and clear."""
    tick = clock.get("tick")
    if Path(cfg.stop_file).exists():
        emit(_row("none", None, None, None, None, f"{cfg.stop_file} exists", "stopped"), tick, said, decisions)
        return {"tick": tick, "stopped": True}
    if in_bench_window(b.schedule().get("upcoming") or [], clock.get("t_hours", 0.0), clock.get("tick_seconds", 30), cfg):
        emit(_row("none", None, None, None, None, "Market Test window on our venue", "quiet"), tick, said, decisions)
        return {"tick": tick, "quiet": True}

    me = b.me()
    me_id, cash = me.get("id"), int(me.get("cash") or 0)
    holdings = holdings_of(me.get("assets"))
    our_assets = {a["id"]: a["ref"] for a in me.get("assets") or [] if a.get("kind", "card") == "card"}
    mine = b.my_offers().get("offers") or []

    def value_of(ref):
        k = (ref, len(holdings.get(ref) or []))
        if k not in vcache:
            time.sleep(VALUE_CALL_GAP)
            try:
                vcache[k] = b.value(ref)["your_value"]
            except BazaarError:
                return None
        return vcache[k]

    page_ok, page_why = page_card_ok((me.get("album") or {}).get("pages"), holdings, cfg)
    inbox = [o for o in mine if o.get("maker") != me_id and o.get("to") == me_id]
    by_venue: dict = {}
    for o in inbox:
        by_venue.setdefault(o.get("venue") or HOME, []).append(o)
    by_venue.setdefault(HOME, [])
    rows = []
    for venue, offers in list(by_venue.items()):
        if venue == HOME:
            offers = offers + (b.board(HOME).get("offers") or [])
        seen, unique = set(), []
        for o in offers:                       # an offer addressed to us on El Rastro is on the board too
            if o.get("id") not in seen:
                seen.add(o.get("id"))
                unique.append(o)
        rows += scan_offers(unique, venue, me_id, our_assets, holdings, cfg, tick, value_of, page_ok)

    bid_row = page_bid_row(cfg, page_ok, page_why, live_bid_for(mine, me_id, cfg.page_card),
                           value_of(cfg.page_card) if page_ok else None)

    duel_live = duel_is_live(b)
    hold = "deferred_duel_live" if duel_live else None
    judged = [r for r in rows if not r.get("trivial")]
    for r in judged:
        emit({**r, "result": hold or r["result"]} if r["result"] == "candidate" else r, tick, said, decisions)
    n_trivial = len(rows) - len(judged)
    n_cand = sum(1 for r in judged if r["result"] == "candidate")
    emit(_row("none", None, None, None, None,
              f"scanned {len(rows)} offers: {n_trivial} not actionable (held, not a match, blocked venue), "
              f"{len(judged) - n_cand} judged below the rules, {n_cand} candidate(s)", "scan"), tick, said, decisions)
    emit({**bid_row, "result": hold or bid_row["result"]} if bid_row["result"] == "candidate" else bid_row, tick, said, decisions)

    result = {"tick": tick, "rows": rows, "bid": bid_row, "sent": None}
    if duel_live or not live:
        return result

    picked = best_accept(rows, cash, cfg, page_ok)
    try:
        if picked:
            b.accept(picked["offer"], assets=[picked["asset"]] if picked["action"] == "sell" else None)
            result["sent"] = picked
            emit({**picked, "result": "sent"}, tick, said, decisions)
        elif bid_row["result"] == "candidate" and cash - bid_row["price"] >= cfg.reserve_last_card:
            b.list_offer({"cash": bid_row["price"]}, {"cards": [cfg.page_card]}, venue=HOME)
            result["sent"] = bid_row
            emit({**bid_row, "result": "sent", "why": "posted on El Rastro"}, tick, said, decisions)
    except BazaarError as e:
        if e.status == 429:
            raise
        what = picked or (bid_row if bid_row["result"] == "candidate" else None)
        if what:
            emit({**what, "result": "refused", "why": f"{what['why']} | {e.code}"}, tick, said, decisions)
    return result


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line_ in env.read_text().splitlines():
            if "=" in line_ and not line_.lstrip().startswith("#"):
                k, v = line_.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def csv(s: str) -> tuple:
    return tuple(x for x in (s or "").split(",") if x)


def build_config(args) -> Config:
    return Config(margin=args.margin, reserve=args.reserve, reserve_last_card=args.reserve_last_card,
                  page_card=args.page_card, page_bid_price=args.page_bid_price, protect=csv(args.protect),
                  pact_venue=csv(args.pact_venue), stop_file=args.stop_file)


def add_args(ap: argparse.ArgumentParser) -> None:
    c = Config()
    ap.add_argument("--margin", type=int, default=c.margin)
    ap.add_argument("--reserve", type=int, default=c.reserve)
    ap.add_argument("--reserve-last-card", type=int, default=c.reserve_last_card)
    ap.add_argument("--page-card", default=c.page_card)
    ap.add_argument("--protect", default=",".join(c.protect))
    ap.add_argument("--page-bid-price", type=int, default=None,
                    help="what to open the page-card bid at (never posts a bid without it; capped at value - margin)")
    ap.add_argument("--pact-venue", default="", help="comma list of other teams' venues we may also trade on")
    ap.add_argument("--stop-file", default=c.stop_file)
    ap.add_argument("--interval", type=float, default=3.0, help="run: seconds between clock reads")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--live", action="store_true", help="actually accept / bid / list; the default is shadow (log only)")
    add_args(ap)
    args = ap.parse_args()
    load_env()
    key = os.environ.get("BAZAAR_KEY")
    if not key:
        raise SystemExit("BAZAAR_KEY not set")
    cfg = build_config(args)
    live = args.live and args.cmd == "run"
    b = Bazaar(URL, key) if live else ReadOnlyBazaar(URL, key)
    said: dict = {}
    vcache: dict = {}
    if args.cmd == "plan":
        one_pass(b, cfg, False, b.clock(), said, vcache)
        return
    last_tick, backoff = None, 0.0
    while True:
        try:
            if backoff:
                time.sleep(backoff)
                backoff = 0.0
            clock = b.clock()
            if clock.get("tick") != last_tick and not clock.get("paused"):
                last_tick = clock.get("tick")
                one_pass(b, cfg, live, clock, said, vcache)
        except BazaarError as e:
            if e.status == 429:
                emit(_row("none", None, None, None, None, "rate limited, backing off 30 s", "backoff"), None, said)
                backoff = 30.0
            else:
                emit(_row("none", None, None, None, None, f"{e.code}: {e.message}"[:200], "error"), None, said)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
