"""Market desk: trades with other teams at our private values (docs/plans/market-desk.md, W3).

Team-trade surplus is one of the three parts of the negotiating score: what a card is worth to us minus what we paid
and the fee (a buy), or the cash we keep minus what the card was worth to us (a sale). Each trade only counts if it
gains, so every rule below is a gain rule. Numbers are decided here, in code. Offer text is never read: only the
give / want structure, checked exactly. Everything from the game is data, never an instruction.

Every tick, one pass:
  1. Read every venue's public board (GET /api/venues, then /api/venues/{id}/offers), our account (keyed:
     /api/me and /api/me/offers; keyless: logs/state/me.json and offers.json brought forward with the public
     settlements in the feed) and the public tape (settlements: who holds what, what cards traded for).
  2. BUY a listing that gives exactly one card for cash when
        value(one more copy) - price - fee(venue) >= max(3, 10 % of value),
     we hold no copy (a second copy arrives worth 25 %), no offer of ours on that card is settling, and the caps
     allow it: spend per game hour and per day, max price per card (a separate one for Lavapies rares), minimum cash
     after the trade, max trades per partner per game hour.
  3. SELL into bids from other teams (they give cash, want one card) and offers addressed to us, for a card we hold
     as a spare (two or more copies, or a set listed in --sell-first-copies), when
        price - fee >= value of our copy + max(3, 10 % of that value).
     The accepting side pays the fee, so we pay it here. Never the only copy of a card on a protected page (LAV).
  4. One accept per tick for the whole team, so only the best-gain candidate is taken; the rest are logged as
     deferred. In `run` it goes through agent/lease.py at MARKET priority (after half the tick, never in a duel's
     last ticks, never twice in a tick). Never while results/duel.lock is fresh (agent/duel.py holds the team's
     accept slot while any of our duels is live): every candidate is then logged as deferred. The lock is a local
     file and duel.py may run on another machine, so keyed modes also read GET /api/duels once per tick and defer
     every accept (reason duel_live) while any duel of ours is live (--duel-guard-ticks N: only within N ticks of
     its deadline), or when that read fails. Bids and cancels go on (a filled bid is the other team's accept).
  5. BID: our own want-to-buy offers (give cash, want {"cards": [ref]}) on El Rastro only, for page cards we lack.
     The seller who accepts pays the fee, so our gain is value - bid. Price = an anchor from the observed prices
     (team trades for that card, else its set and rarity, else its rarity, else 80 % of book), raised by --bid-step
     every --bid-step-ticks without a fill, never above value - margin or the price caps. One bid per card, at most
     --bid-max live, their sum within cash - min cash. A bid is cancelled when the card arrives or the price is stale.
  6. SWAPS (off by default: --swap-fills and --swap-posts turn them on): one card for one card, no cash on either
     side (give {"assets": [id]}, want {"cards": [ref]}, which the board shows as want.types ["card:REF"]). A spare
     is worth 25 % or 10 % of a first copy to us and a card we lack 100 %, so a swap creates value at our private
     values without spending cash: it is held to the buy margin and the spend caps for its fee, and to a hard cash
     floor (cash - live bids - fee >= 200 P, Config.swap_cash_floor). The fee is paid by the side that accepts: 0 %
     of 0 P plus the per-card fee for both cards (El Rastro 2 P; v03 at 1 % and 0 per card: 0 P).
     Both directions give only a spare: never our last copy of a card (--sell-first-copies does not apply to
     swaps), never the lowest serial, and never an asset in rastro_seller's config (agent/rastro_floors.json, every
     line, re-read every tick) unless --swap-seller-spares.
     FILL another team's swap (they give X, want Y) on El Rastro only (another team's venue with --swap-team-venue)
     when
        value(one more X) - value of our copy of Y - fee >= max(3, 10 % of value(X)),
     we hold no X, we hold Y at least twice, no offer of ours on X or Y is settling, the fee is <= --swap-max-fee,
     the cash floor holds and the per-partner cap allows it. Same one-accept-per-tick ranking, lease, duel.lock and
     re-read before the accept as buys; we pass our copy's asset id.
     POST our own: for each page card we lack worth >= --swap-min-value (most valuable first, live swaps keep their
     place), the spare whose value to us is lowest, of the same rarity or higher, passing the same rule without a
     fee (the side that accepts pays it); one swap per card asked, one copy per card given, at most --swap-max live,
     on El Rastro (another team's venue only with --swap-team-venue), --swap-expires ticks, optionally addressed to a
     public holder (--address-swaps). Never a card we bid for, buy or swap for this tick; never an asset that another
     live offer of ours holds. Renewed, replaced and cancelled like bids.
  7. Every decision, taken or not, is one human line and one JSON record (logs/market/<date>.jsonl in watch/run);
     a heartbeat goes to logs/state/desk-market.json.
  8. PAGE MODE (--page REF:CAP[:FLOOR], repeatable): the last card of a page, bought from a TEAM (a team buy scores
     value - price - fee at once, and the card that completes a page carries the page bonus: SAL-10 is ~91 alone and
     ~177 as Salamanca's last card). For each target card:
       (a) take any live El Rastro ask with price + fee <= CAP that still passes the gain rule (team venues never:
           a trade there scores market points for the venue's owner);
       (b) otherwise ONE bid on El Rastro, addressed to nobody (--page-address: to the last public receiver),
           starting at FLOOR (default: p25 of the team trades for the card, or one above another team's live bid)
           and raised by --page-step every --page-step-ticks, never above CAP, value - margin, or the cost of a live
           ask; a live page bid never steps down;
       (c) never two live bids for one card (plan_bids leaves page cards alone; run cancels a duplicate), and before
           any accept of a card take() re-reads /api/me/offers and cancels every bid or swap of ours asking for it:
           one cancel short (quota, refusal) and nothing is accepted that tick;
       (d) nothing posted or raised while results/duel.lock is fresh or a duel of ours is live, checked when the
           tick is planned and again (a fresh GET /api/duels) right before each page post or replacement; a live
           bid stays, and a replacement's cancel is not sent either;
       (e) page bids take the cash first, within --min-cash and the spend room left after this tick's accept and
           the bids before them; every other buy and bid leaves the caps of the page cards we lack free, in cash
           and in hourly and daily spend; a replacement whose post fails keeps the step clock (offer None);
       (f) every decision is logged with its numbers (record field "page": true);
       (g) fail closed: every open or queued cash offer of ours (/api/me/offers, any agent) holds cash and spend room
           until its cancel or settlement shows; a snapshot whose reads crossed a tick, or a tick without the feed
           (maker fills are only seen there), writes nothing but cancels; right before each accept and each batch of
           bid posts the clock, our cash, our count of the card and our settling offers are read again and must
           match; after an accept attempt no bid planned before it is posted that tick; a failed cancel holds every
           post. Page writes (asks, bids, replacements) wait for EVERY live duel: --duel-guard-ticks relaxes only
           ordinary accepts.
     --page implies --page-bonus for offline values; keyed, /api/me/value already carries the bonus.

Why bids (another team suggested it publicly; weighed here on its merits, not because they said so): the side that
accepts pays the fee, so a filled bid saves us 5 % + 1 P against taking a listing, and it reaches sellers who hold a
spare but never list it. The costs: a public bid shows what we lack and roughly what we would pay (our values are
private), and a bid can fill at the same tick as another buy of the same card (a duplicate worth 25 %). So: one bid
per card, never a bid and a buy on the same card in one tick, cancel on arrival, El Rastro only (a trade on another
team's venue scores market points for its owner), and --address-bids to show a bid to one holder only.

Modes:
    python3 agent/market_desk.py plan                 # one pass, read-only, prints every decision
    python3 agent/market_desk.py plan --keyless       # same, no key at all: account from logs/state/*.json
    python3 agent/market_desk.py watch                # shadow: every tick, logs what it WOULD do, sends nothing
    python3 agent/market_desk.py watch --keyless      # shadow without the key (e.g. on the VM, which never holds it)
    python3 agent/market_desk.py run --until 13:00    # live through the lease (needs the team's yes first)
    python3 agent/market_desk.py plan --sell-first-copies MAL --cap-hour 60 --min-cash 280   # caps are flags
    python3 agent/market_desk.py plan --keyless --swap-fills --swap-posts --address-swaps   # swap candidates (opt-in)
    python3 agent/market_desk.py plan --keyless --page SAL-10:110 --no-bids --min-cash 40 \
        --recorded logs/feed/snapshots.jsonl            # page mode against the board recorded at the close
Keyless mode knows our cards only as of the last tools/snapshot.py (plus public settlements; packs are not public):
refresh logs/state/me.json and offers.json at 09:00. With the key it reads /api/me every tick and asks
/api/me/value for the cards that come close to the rule (cached until our holdings change).
Wiring with the other agents: when the desk fills bids, run rastro_seller.py without --take-bids (one owner per
bid), and the desk leaves alone any spare the seller has listed (unless --sell-listed).
`plan` and `watch` never send a write: their client refuses anything but GET before it leaves the machine.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402
from runlog import LOGS, RunLog, redact, write_json  # noqa: E402

URL = "https://bazaar.causaprima.ai"
HOME = "rastro"
STATE = LOGS / "state"
HEARTBEAT = STATE / "desk-market.json"
DUEL_LOCK = ROOT / "results" / "duel.lock"   # agent/duel.py run: expiry (epoch seconds) while any duel is live
YIELD_DIR = ROOT / "logs" / "state"   # page-yield-<REF>: a fallback step buys REF; the desk stops and acks (.ack)
PAGE_SWEEP_TICKS = 20                 # page mode with --no-team-venues: every N ticks, read every eligible team board
SELLER_CONFIG = ROOT / "agent" / "rastro_floors.json"   # rastro_seller.py's spares: our swaps leave them alone
ME_SNAPSHOT = STATE / "me.json"
OFFERS_SNAPSHOT = STATE / "offers.json"
FEED_FILES = [LOGS / "feed-vm" / "feed.jsonl", LOGS / "feed" / "feed.jsonl"]
MADRID = ZoneInfo("Europe/Madrid")
DEFAULT_FEE = (500, 1)          # El Rastro: 5 % + 1 P per card (all 46 team settlements on Friday fit it)
WORST_FEE = (1000, 5)           # unknown venue: the rules cap any venue at 10 % and 5 P per card
REF_RE = re.compile(r"^[A-Z]{3}-\d{2}$")
TEAM_RE = re.compile(r"^t\d+$")
TICKS_PER_GAME_HOUR = 60        # tick 159 = hour 2.65 on Friday; used only when a clock has no t_hours
SERVER_SLACK = 5.0              # a listing this far short on the offline value is skipped without asking the server


@dataclass
class Config:
    margin_min: float = 3.0             # a buy must gain at least max(margin_min, margin_frac x value)
    margin_frac: float = 0.10
    sell_margin_min: float = 3.0        # a sale must net our copy's value + max(sell_margin_min, frac x value)
    sell_margin_frac: float = 0.10
    cap_hour: int = 100                 # spend per game hour (buys and filled bids, fees included)
    cap_day: int = 250                  # spend per day
    max_price: int = 80                 # max price per card (Friday's team trades: rares 53-80)
    max_price_rare: int = 100           # max price for a rare of a set in rare_cap_sets
    rare_cap_sets: tuple = ("LAV",)
    min_cash: int = 280                 # cash left after the trade (team rule: 250 bond + 20 + margin)
    partner_hour: int = 2               # max trades with one partner per game hour
    protect: tuple = ("LAV",)           # never sell the only copy of a card on these pages
    sell_first_copies: tuple = ()       # sets whose single copies we also sell (e.g. MAL, our x0.7 set)
    sell_listed: bool = False           # may hand over a copy that rastro_seller has listed (run cancels it first)
    team_venues: bool = True            # take listings and bids on other teams' venues (scores market points for them)
    bids: bool = True
    bid_venue: str = HOME
    bid_max: int = 6                    # live bids at once
    bid_min_value: float = 8.0          # do not bid for cards worth less than this to us
    bid_step: int = 1                   # P added to a bid after bid_step_ticks without a fill
    bid_step_ticks: int = 20
    bid_expires: int = 30               # expires_in_ticks for our bids (El Rastro caps listings at 30)
    address_bids: bool = False          # address each bid to one team that holds the card (public settlements)
    page_bonus: bool = False            # offline value adds the page bonus to a page's last missing card
    price_window: int = 15              # last N observed trades in the price index
    # swaps: one card for one card, no cash either way (docs in the module docstring, step 6)
    swap_fill: bool = False             # accept other teams' swaps that pass the rule (opt-in: --swap-fills)
    swap_post: bool = False             # post our own swaps, a spare for a card we lack (opt-in: --swap-posts)
    swap_venue: str = HOME              # another team's venue only with --swap-team-venue (it scores for its owner)
    swap_team_venue: bool = False       # fills and posts on another team's venue (El Rastro only without it)
    swap_cash_floor: int = 200          # hard floor: cash - live bids - swap fee never below this
    swap_max: int = 4                   # our live swaps at once
    swap_expires: int = 30              # expires_in_ticks for our swaps
    swap_min_value: float = 8.0         # do not ask a swap for cards worth less than this to us
    swap_max_fee: int = 3               # max fee we pay to fill a swap (El Rastro: 1 P per card, 2 cards = 2 P)
    address_swaps: bool = False         # address each swap to one team that holds the card (public settlements)
    swap_any_rarity: bool = False       # offer a lower-rarity spare for a card (default: same rarity or higher)
    swap_seller_spares: bool = False    # may offer copies in rastro_seller's config (it would adopt the offer)
    duel_guard_ticks: int | None = None  # keyed: no accept while a duel of ours is live (N: within N ticks of its end)
    # page mode (--page REF:CAP[:FLOOR]): the last cards of our pages, bought from a team (docstring, step 8)
    page_targets: dict = field(default_factory=dict)   # {ref: {"cap": max P we pay, fee included; "floor": P or None}}
    page_step: int = 4                  # P added to a page bid every page_step_ticks
    page_step_ticks: int = 8
    page_address: bool = False          # address the page bid to the last public receiver of the card


# ---------------------------------------------------------------- pure: fees, margins, structure

def fee_for(price: int, venue_fee: tuple, n_cards: int = 1) -> int:
    """Venue fee: ceil(price x bps / 10000) + per-card fee x cards (integer math, as the server charges it)."""
    bps, per_card = venue_fee
    return -(-int(price) * int(bps) // 10000) + int(per_card) * int(n_cards)


def need_buy(value: float, cfg: Config) -> float:
    return max(cfg.margin_min, cfg.margin_frac * value)


def need_sell(value: float, cfg: Config) -> float:
    return max(cfg.sell_margin_min, cfg.sell_margin_frac * value)


def _int_cash(x) -> int | None:
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def _side(d) -> tuple:
    """(cash, assets, types, unknown_key) of one side of an offer, or None for a malformed side."""
    if not isinstance(d, dict):
        return None
    unknown = [k for k, v in d.items() if k not in ("cash", "assets", "types") and v]
    cash = d.get("cash") or 0
    assets = d.get("assets") or []
    types = d.get("types") or []
    if not isinstance(assets, list) or not isinstance(types, list):
        return None
    return cash, assets, types, (unknown[0] if unknown else None)


def check_listing(o: dict, me_id: str, tick: int | None = None) -> dict:
    """A sell listing we could take: they give exactly one card (an asset with a card ref) and nothing else; they
    want cash only. Open, not ours, addressed to nobody or to us, not a conversation offer, not expired."""
    bad = {"ok": False, "ref": None, "asset": None, "price": None}
    if not isinstance(o, dict):
        return {**bad, "reason": "not_an_offer"}
    if o.get("status") != "open":
        return {**bad, "reason": f"status_{o.get('status')}"}
    if o.get("maker") == me_id:
        return {**bad, "reason": "maker_is_us"}
    if o.get("to") not in (None, "", me_id):
        return {**bad, "reason": "addressed_elsewhere"}
    if o.get("thread") is not None:
        return {**bad, "reason": "conversation_offer"}
    if tick is not None and isinstance(o.get("expires_tick"), int) and o["expires_tick"] <= tick:
        return {**bad, "reason": "expired"}
    g, w = _side(o.get("give")), _side(o.get("want"))
    if g is None or w is None:
        return {**bad, "reason": "bad_shape"}
    if g[3] or w[3]:
        return {**bad, "reason": f"unknown_{g[3] or w[3]}"}
    gcash, gassets, gtypes, _ = g
    wcash, wassets, wtypes, _ = w
    if gcash or gtypes:
        return {**bad, "reason": "they_give_more_than_a_card"}
    if len(gassets) != 1:
        return {**bad, "reason": f"they_give_{len(gassets)}_assets"}
    a = gassets[0]
    if not isinstance(a, dict) or a.get("kind", "card") != "card" or not isinstance(a.get("ref"), str) \
            or not REF_RE.match(a["ref"]) or not isinstance(a.get("id"), int):
        return {**bad, "reason": "not_a_card"}
    if wassets or wtypes:
        return {**bad, "reason": "they_want_items"}
    price = _int_cash(wcash)
    if price is None or price < 1:
        return {**bad, "reason": "no_cash_price"}
    return {"ok": True, "reason": "listing", "ref": a["ref"], "asset": a["id"], "price": price,
            "rarity": a.get("rarity"), "set": a.get("set") or a["ref"][:3], "serial": a.get("serial")}


def check_bid(o: dict, me_id: str, our_assets: dict, tick: int | None = None) -> dict:
    """A bid we could fill: they give cash only; they want exactly one item, which is either any copy of a card
    (types ["card:REF"]) or one specific asset of ours. Open, not ours, addressed to nobody or to us, not expired.
    our_assets: {asset_id: ref}."""
    bad = {"ok": False, "ref": None, "asset": None, "price": None}
    if not isinstance(o, dict):
        return {**bad, "reason": "not_an_offer"}
    if o.get("status") != "open":
        return {**bad, "reason": f"status_{o.get('status')}"}
    if o.get("maker") == me_id:
        return {**bad, "reason": "maker_is_us"}
    if o.get("to") not in (None, "", me_id):
        return {**bad, "reason": "addressed_elsewhere"}
    if o.get("thread") is not None:
        return {**bad, "reason": "conversation_offer"}
    if tick is not None and isinstance(o.get("expires_tick"), int) and o["expires_tick"] <= tick:
        return {**bad, "reason": "expired"}
    g, w = _side(o.get("give")), _side(o.get("want"))
    if g is None or w is None:
        return {**bad, "reason": "bad_shape"}
    if g[3] or w[3]:
        return {**bad, "reason": f"unknown_{g[3] or w[3]}"}
    gcash, gassets, gtypes, _ = g
    wcash, wassets, wtypes, _ = w
    if gassets or gtypes:
        return {**bad, "reason": "they_give_items"}
    price = _int_cash(gcash)
    if price is None or price < 1:
        return {**bad, "reason": "no_cash"}
    if wcash:
        return {**bad, "reason": "wants_our_cash"}
    if len(wassets) + len(wtypes) != 1:
        return {**bad, "reason": f"wants_{len(wassets) + len(wtypes)}_items"}
    if wtypes:
        t = wtypes[0]
        if not isinstance(t, str) or not t.startswith("card:") or not REF_RE.match(t[5:]):
            return {**bad, "reason": "wants_non_card"}
        return {"ok": True, "reason": "bid_type", "ref": t[5:], "asset": None, "price": price}
    a = wassets[0]
    aid = a.get("id") if isinstance(a, dict) else a
    if not isinstance(aid, int) or aid not in our_assets:
        return {**bad, "reason": "wants_asset_not_ours"}
    return {"ok": True, "reason": "bid_asset", "ref": our_assets[aid], "asset": aid, "price": price}


SWAP_CARDS = 2   # a swap moves two cards (one each way); the per-card fee counts both, as (18 P, 2 cards) -> 3 did


def swap_fee(venue_fee: tuple) -> int:
    """Fee for a no-cash swap, paid by the side that accepts: 0 % of 0 P + the per-card fee x 2 cards
    (El Rastro: 2 P; a team venue with no per-card fee, e.g. v03 at 1 %: 0 P)."""
    return fee_for(0, venue_fee, SWAP_CARDS)


def check_swap(o: dict, me_id: str, our_assets: dict, tick: int | None = None) -> dict:
    """A swap we could fill: they give exactly one card (an asset with a card ref) and want exactly one card back,
    either any copy (types ["card:REF"], or cards ["REF"] as it is posted) or one specific asset of ours; no cash on
    either side and nothing else. Open, not ours, addressed to nobody or to us, not a conversation offer, not expired.
    our_assets: {asset_id: ref}. "ref" is the card we would get, "want_ref" the card we would give."""
    bad = {"ok": False, "ref": None, "asset": None, "want_ref": None, "want_asset": None}
    if not isinstance(o, dict):
        return {**bad, "reason": "not_an_offer"}
    if o.get("status") != "open":
        return {**bad, "reason": f"status_{o.get('status')}"}
    if o.get("maker") == me_id:
        return {**bad, "reason": "maker_is_us"}
    if o.get("to") not in (None, "", me_id):
        return {**bad, "reason": "addressed_elsewhere"}
    if o.get("thread") is not None:
        return {**bad, "reason": "conversation_offer"}
    if tick is not None and isinstance(o.get("expires_tick"), int) and o["expires_tick"] <= tick:
        return {**bad, "reason": "expired"}
    want = o.get("want")
    if isinstance(want, dict) and "cards" in want:   # the posted form; the board shows it as types ["card:REF"]
        cards = want.get("cards")
        if not isinstance(cards, list) or not all(isinstance(c, str) for c in cards):
            return {**bad, "reason": "bad_shape"}
        types = want.get("types") or []
        if not isinstance(types, list):
            return {**bad, "reason": "bad_shape"}
        want = {**{k: v for k, v in want.items() if k != "cards"}, "types": types + [f"card:{c}" for c in cards]}
    g, w = _side(o.get("give")), _side(want)
    if g is None or w is None:
        return {**bad, "reason": "bad_shape"}
    if g[3] or w[3]:
        return {**bad, "reason": f"unknown_{g[3] or w[3]}"}
    gcash, gassets, gtypes, _ = g
    wcash, wassets, wtypes, _ = w
    if gcash or wcash:
        return {**bad, "reason": "swap_with_cash"}
    if gtypes:
        return {**bad, "reason": "they_give_a_type"}
    if len(gassets) != 1:
        return {**bad, "reason": f"they_give_{len(gassets)}_assets"}
    a = gassets[0]
    if not isinstance(a, dict) or a.get("kind", "card") != "card" or not isinstance(a.get("ref"), str) \
            or not REF_RE.match(a["ref"]) or not isinstance(a.get("id"), int):
        return {**bad, "reason": "not_a_card"}
    if len(wassets) + len(wtypes) != 1:
        return {**bad, "reason": f"wants_{len(wassets) + len(wtypes)}_items"}
    if wtypes:
        t = wtypes[0]
        if not isinstance(t, str) or not t.startswith("card:") or not REF_RE.match(t[5:]):
            return {**bad, "reason": "wants_non_card"}
        want_ref, want_asset = t[5:], None
    else:
        x = wassets[0]
        want_asset = x.get("id") if isinstance(x, dict) else x
        if not isinstance(want_asset, int) or isinstance(want_asset, bool) or want_asset not in our_assets:
            return {**bad, "reason": "wants_asset_not_ours"}
        want_ref = our_assets[want_asset]
    if want_ref == a["ref"]:
        return {**bad, "reason": "same_card"}
    return {"ok": True, "reason": "swap_asset" if want_asset is not None else "swap_type", "ref": a["ref"],
            "asset": a["id"], "want_ref": want_ref, "want_asset": want_asset, "rarity": a.get("rarity"),
            "set": a.get("set") or a["ref"][:3], "serial": a.get("serial")}


def classify(o: dict) -> str:
    """Rough shape, for routing and the log: listing | bid | swap | other (each check_* then checks it exactly)."""
    want = (o or {}).get("want")
    if isinstance(want, dict) and isinstance(want.get("cards"), list) and isinstance(want.get("types") or [], list):
        want = {**{k: v for k, v in want.items() if k != "cards"},
                "types": list(want.get("types") or []) + [f"card:{c}" for c in want["cards"]]}
    g, w = _side((o or {}).get("give")), _side(want)
    if g is None or w is None:
        return "other"
    if g[1] and not g[0] and w[0] and not (w[1] or w[2]):
        return "listing"
    if g[0] and not (g[1] or g[2]) and (w[1] or w[2]):
        return "bid"
    if (g[1] or g[2]) and (w[1] or w[2]):
        return "swap"
    return "other"


# ---------------------------------------------------------------- values

class Valuer:
    """Our private value of a card. Online (keyed): GET /api/me/value?card=X, cached until our holdings change.
    Offline: catalog book x our set multiplier x copy marginal for the copies we hold (1, 0.25, 0.1). The page
    bonus is added offline only with page_bonus=True (unconfirmed whether trades score it)."""

    def __init__(self, catalog: dict, affinity: dict, counts: dict, *, page_bonus: bool = False, online=None,
                 copy_values: dict | None = None):
        self.cards: dict = {}
        self.pages: dict = {}
        for s in catalog.get("sets", []):
            for c in s.get("cards", []):
                self.cards[c["id"]] = {"set": s["id"], "rarity": c.get("rarity"), "book": float(c.get("book") or 0),
                                       "page": bool(c.get("page")), "hidden": bool(c.get("hidden")),
                                       "released": bool(s.get("released"))}
                if c.get("page"):
                    self.pages.setdefault(s["id"], []).append(c["id"])
        vals = catalog.get("values") or {}
        self.marginals = [float(x) for x in vals.get("copy_marginals") or [1.0, 0.25, 0.1]]
        self.page_frac = float(vals.get("page_bonus") or 0.0)
        self.affinity = {k: float(v) for k, v in (affinity or {}).items()}
        self.counts = dict(counts)
        self.page_bonus = page_bonus
        self.online = online
        self.copy_values = dict(copy_values or {})   # {ref: your_value of our last copy} from /api/me
        self.cache: dict = {}
        self.mismatches: list = []

    def set_counts(self, counts: dict, copy_values: dict | None = None) -> None:
        if counts != self.counts:
            self.cache.clear()
        self.counts = dict(counts)
        if copy_values is not None:
            self.copy_values = dict(copy_values)

    def info(self, ref: str) -> dict:
        return self.cards.get(ref) or {"set": ref[:3], "rarity": None, "book": 0.0, "page": False, "hidden": False,
                                       "released": False}

    def first(self, ref: str) -> float:
        c = self.info(ref)
        if c["hidden"]:
            return 0.0
        return c["book"] * self.affinity.get(c["set"], 0.0)

    def marginal(self, k: int) -> float:
        return self.marginals[k] if k < len(self.marginals) else self.marginals[-1]

    def _bonus(self, ref: str, after: dict) -> float:
        s = self.info(ref)["set"]
        page = self.pages.get(s) or []
        if ref not in page or not all(after.get(c, 0) > 0 for c in page):
            return 0.0
        return self.page_frac * sum(self.first(c) for c in page)

    def completes_page(self, ref: str) -> bool:
        """True when one copy of ref would complete its page (the server's value may then carry a page bonus)."""
        page = self.pages.get(self.info(ref)["set"]) or []
        return ref in page and self.counts.get(ref, 0) == 0 and all(self.counts.get(c, 0) > 0 for c in page if c != ref)

    def offline_more(self, ref: str) -> float:
        k = self.counts.get(ref, 0)
        v = self.first(ref) * self.marginal(k)
        if self.page_bonus and k == 0:
            v += self._bonus(ref, {**self.counts, ref: 1})
        return round(v, 3)

    def offline_copy(self, ref: str) -> float:
        k = self.counts.get(ref, 0)
        if k <= 0:
            return 0.0
        v = self.first(ref) * self.marginal(k - 1)
        if self.page_bonus and k == 1:
            v += self._bonus(ref, self.counts)
        return round(v, 3)

    def more(self, ref: str) -> tuple:
        """(value of one more copy, source)."""
        off = self.offline_more(ref)
        if self.online is None:
            return off, "offline"
        if ref in self.cache:
            return self.cache[ref], "server"
        try:
            v = self.online(ref)
        except Exception:
            return off, "offline(server_failed)"
        if v is None:
            return off, "offline(no_server_value)"
        v = float(v)
        self.cache[ref] = v
        if abs(v - off) > 0.05:
            self.mismatches.append({"card": ref, "server": v, "offline": off})
        return v, "server"

    def copy(self, ref: str) -> tuple:
        """(value of our last copy of ref, i.e. what selling one loses us, source)."""
        if ref in self.copy_values:
            return float(self.copy_values[ref]), "server"
        return self.offline_copy(ref), "offline"


# ---------------------------------------------------------------- the public tape

class Tape:
    """What the public feed says: who listed which offer, what cards traded for, who holds what."""

    def __init__(self):
        self.seen: set = set()
        self.maker: dict = {}        # offer id -> team id (offer.listed actor)
        self.trades: list = []       # team-to-team single-card trades
        self.dealer: list = []       # dealer -> team single-card sales
        self.holds: dict = {}        # ref -> {team: copies}, from public settlements and gifts only
        self.settled: list = []      # every settlement payload with its tick
        self.cancelled: dict = {}    # offer id -> tick
        self.listed_on: dict = {}    # offer id -> (venue, ref) of one-card listings off El Rastro

    def ingest(self, events) -> "Tape":
        for e in sorted((e for e in events if isinstance(e, dict)), key=lambda e: (e.get("tick") or 0, e.get("id") or 0)):
            eid = e.get("id")
            if eid in self.seen:
                continue
            self.seen.add(eid)
            t, p = e.get("type"), e.get("payload") or {}
            if t == "offer.listed":
                o = p.get("offer") or {}
                if isinstance(o.get("id"), int) and isinstance(e.get("actor"), str) and TEAM_RE.match(e["actor"]):
                    self.maker[o["id"]] = e["actor"]
                gave = ((o.get("give") or {}).get("assets") or []) if isinstance(o.get("give"), dict) else []
                ven = p.get("venue") or o.get("venue")
                if isinstance(o.get("id"), int) and len(gave) == 1 and isinstance(gave[0], dict) \
                        and isinstance(gave[0].get("ref"), str) and isinstance(ven, str) and ven != HOME:
                    self.listed_on[o["id"]] = (ven, gave[0]["ref"])
            elif t == "offer.cancelled" and isinstance(p.get("offer"), int):
                self.cancelled[p["offer"]] = e.get("tick")
            elif t == "settlement":
                self._settle(e.get("tick") or 0, p)
            elif t == "gift.given":
                team = p.get("team")
                for ref in p.get("cards") or []:
                    if isinstance(ref, str) and isinstance(team, str):
                        h = self.holds.setdefault(ref, {})
                        h[team] = h.get(team, 0) + 1
        return self

    def _settle(self, tick: int, p: dict) -> None:
        items = [i for i in p.get("items") or [] if isinstance(i, dict)]
        self.settled.append({"tick": tick, **p})
        cards = [i for i in items if i.get("kind") == "card"]
        for i in cards:
            ref = i.get("ref")
            h = self.holds.setdefault(ref, {})
            if isinstance(i.get("to"), str) and TEAM_RE.match(i["to"]):
                h[i["to"]] = h.get(i["to"], 0) + 1
            if isinstance(i.get("frm"), str) and TEAM_RE.match(i["frm"]):
                h[i["frm"]] = h.get(i["frm"], 0) - 1
        if len(cards) != 1 or not isinstance(p.get("price"), int):
            return
        i = cards[0]
        row = {"tick": tick, "ref": i.get("ref"), "set": i.get("set") or str(i.get("ref"))[:3],
               "rarity": i.get("rarity"), "price": p["price"], "frm": i.get("frm"), "to": i.get("to"),
               "venue": p.get("venue")}
        if p.get("venue"):
            self.trades.append(row)
        elif p.get("persona") and i.get("frm") == p.get("persona"):
            self.dealer.append(row)

    def prices(self, ref: str, set_id: str, rarity: str | None, before: int | None = None, last: int = 15,
               min_n: int = 2) -> tuple:
        """(prices, scope) from team trades: the card, else its set and rarity, else its rarity."""
        rows = [r for r in self.trades if before is None or r["tick"] < before]
        for scope, pred in (("card", lambda r: r["ref"] == ref),
                            ("set+rarity", lambda r: r["set"] == set_id and r["rarity"] == rarity),
                            ("rarity", lambda r: r["rarity"] == rarity)):
            ps = [r["price"] for r in rows if pred(r)][-last:]
            if len(ps) >= min_n or (scope == "card" and ps):
                return ps, scope
        return [], "none"

    def owners(self, ref: str, exclude: str = "") -> list:
        """Teams that, by public settlements and gifts, still hold a copy (starting hands and packs are not public)."""
        return sorted(t for t, n in (self.holds.get(ref) or {}).items() if n > 0 and t != exclude)

    def last_receiver(self, ref: str, exclude: str = "", among=None) -> str | None:
        own = set(self.owners(ref, exclude))
        if among is not None:
            own &= set(among)
        for r in reversed(self.settled):
            for i in r.get("items") or []:
                if i.get("ref") == ref and i.get("to") in own:
                    return i["to"]
        return None


def percentile(xs: list, q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# ---------------------------------------------------------------- caps

class Ledger:
    """Our trades this day (taken in run, simulated in watch), for the caps."""

    def __init__(self, rows: list | None = None):
        self.rows = list(rows or [])

    def add(self, **row) -> None:
        self.rows.append(row)

    def spent(self, t_hours: float, window: float | None = 1.0) -> int:
        """Cash out on buys, filled bids and the fees of the swaps we filled."""
        return sum(int(r.get("cost") or 0) for r in self.rows if r.get("side") in ("buy", "swap")
                   and (window is None or r.get("t_hours", 0) > t_hours - window))

    def partner_trades(self, partner: str, t_hours: float) -> int:
        return sum(1 for r in self.rows if r.get("partner") == partner and r.get("t_hours", 0) > t_hours - 1.0)


def price_cap(cfg: Config, info: dict) -> int:
    if info.get("rarity") == "rare" and info.get("set") in cfg.rare_cap_sets:
        return cfg.max_price_rare
    return cfg.max_price


def buy_caps(cfg: Config, *, price: int, fee: int, info: dict, cash: int, ledger: Ledger, t_hours: float,
             partner: str | None, committed: int = 0, max_price: int | None = None,
             spend_committed: int = 0) -> str | None:
    """The first cap a buy would break, or None. `committed`: cash already promised to live bids;
    `spend_committed`: spend room held back for them (page mode: the caps of the page cards we still lack).
    `max_price` replaces the per-card price cap (page mode: the --page cap, checked on price + fee before this)."""
    cost = price + fee
    cap = price_cap(cfg, info) if max_price is None else max_price
    if price > cap:
        return f"cap: price {price} > max {cap}"
    if cash - committed - cost < cfg.min_cash:
        return f"cap: cash after {cash - committed - cost} < min {cfg.min_cash}"
    held = f" (+{spend_committed} held for page bids)" if spend_committed else ""
    h = ledger.spent(t_hours, 1.0)
    if h + cost + spend_committed > cfg.cap_hour:
        return f"cap: hour spend {h}+{cost}{held} > {cfg.cap_hour}"
    d = ledger.spent(t_hours, None)
    if d + cost + spend_committed > cfg.cap_day:
        return f"cap: day spend {d}+{cost}{held} > {cfg.cap_day}"
    if partner and ledger.partner_trades(partner, t_hours) >= cfg.partner_hour:
        return f"cap: {cfg.partner_hour} trades with {partner} this game hour"
    return None


def cash_commitments(mine: list, me: str) -> dict:
    """{offer id: cash} for every open or queued offer of ours that gives cash (a bid on any venue, an offer in a
    dealer thread): cash that leaves if the other side accepts."""
    out = {}
    for o in mine or []:
        if not isinstance(o, dict) or o.get("maker") != me or o.get("status") not in ("open", "queued"):
            continue
        cash = _int_cash((o.get("give") or {}).get("cash"))
        if cash and cash > 0:
            out[o.get("id")] = cash
    return out


def accept_cost(accept: dict | None) -> int:
    """Cash and spend this tick's accept takes: price + fee for a buy, the fee for a swap fill, nothing for a sale."""
    if not accept:
        return 0
    return {"buy": int(accept.get("price") or 0) + int(accept.get("fee") or 0),
            "swap": int(accept.get("fee") or 0)}.get(accept.get("side"), 0)


def rival_bid(o) -> tuple | None:
    """(ref, price) of a well-formed bid on the board: open, cash only, for exactly one card (types ["card:REF"]) and
    nothing else. A malformed "bid" (cash wanted back, assets, two cards) never moves our price."""
    if not isinstance(o, dict) or o.get("status") != "open":
        return None
    g, w = _side(o.get("give")), _side(o.get("want"))
    if g is None or w is None or g[3] or w[3]:
        return None
    gcash, gassets, gtypes, _ = g
    wcash, wassets, wtypes, _ = w
    price = _int_cash(gcash)
    if price is None or price < 1 or gassets or gtypes or wcash or wassets or len(wtypes) != 1:
        return None
    t = wtypes[0]
    if not isinstance(t, str) or not t.startswith("card:") or not REF_RE.match(t[5:]):
        return None
    return t[5:], price


def swap_caps(cfg: Config, *, fee: int, cash: int, ledger: Ledger, t_hours: float, partner: str | None,
              committed: int = 0) -> str | None:
    """The first cap filling a swap would break, or None. A swap moves no cash, only the fee: it is held to
    --swap-max-fee, the spend caps and a hard cash floor (cash - committed - fee >= cfg.swap_cash_floor, 200 P),
    not to --min-cash. `committed`: cash already promised to live bids."""
    if fee > cfg.swap_max_fee:
        return f"cap: swap fee {fee} > max {cfg.swap_max_fee}"
    if fee > cash:
        return f"cap: fee {fee} > cash {cash}"
    if cash - committed - fee < cfg.swap_cash_floor:
        return f"cap: cash after swap fee {cash - committed - fee} < floor {cfg.swap_cash_floor}"
    h = ledger.spent(t_hours, 1.0)
    if fee and h + fee > cfg.cap_hour:
        return f"cap: hour spend {h}+{fee} > {cfg.cap_hour}"
    d = ledger.spent(t_hours, None)
    if fee and d + fee > cfg.cap_day:
        return f"cap: day spend {d}+{fee} > {cfg.cap_day}"
    if partner and ledger.partner_trades(partner, t_hours) >= cfg.partner_hour:
        return f"cap: {cfg.partner_hour} trades with {partner} this game hour"
    return None


# ---------------------------------------------------------------- the decision (pure)

def _num(x) -> str:
    return f"{x:.1f}" if isinstance(x, float) else str(x)


def line(d: dict) -> str:
    """One human-readable line per decision."""
    k = d["kind"]
    head = f"tick {d.get('tick')} {k.upper():<4} {d.get('card') or '-':<6}"
    where = f"on {d.get('venue')}" + (f" ({d['venue_owner']}'s venue)" if d.get("venue_owner") else "")
    who = f" {d['partner']}" if d.get("partner") else ""
    if k == "buy" and d.get("price") is not None and d.get("value") is not None:
        nums = (f"@ {d['price']} {where} from{who}: value {_num(d['value'])} - price {d['price']} - fee {d['fee']} = "
                f"gain {d['gain']:+.1f} vs need {_num(d['need'])}")
    elif k == "sell" and d.get("price") is not None and d.get("value") is not None:
        nums = (f"bid {d['price']} {where} by{who}: net {d['price']} - fee {d['fee']} = {d['price'] - d['fee']} "
                f"vs copy {_num(d['value'])} + need {_num(d['need'])}, gain {d['gain']:+.1f}")
    elif k == "bid":
        nums = (f"@ {d.get('price')} {where}{' to ' + d['to'] if d.get('to') else ''}: value {_num(d.get('value'))}, "
                f"ceiling {d.get('ceiling')}, anchor {d.get('anchor')} ({d.get('price_basis')}), "
                f"gain if filled {d['gain']:+.1f}" if d.get("gain") is not None else f"{where}")
        if d.get("page"):
            nums = f"PAGE cap {d.get('cap')} " + nums
    elif k == "swap" and d.get("value") is not None and d.get("give_value") is not None:
        mine = f"our {d.get('give_card')}" + (f" #{d['asset']}" if d.get("asset") else "")
        nums = (f"for {mine} {where} from{who}: value {_num(d['value'])} - our copy {_num(d['give_value'])} - fee "
                f"{d['fee']} = gain {d['gain']:+.1f} vs need {_num(d['need'])}")
    elif k == "myswap" and d.get("give_card"):
        nums = (f"give {d['give_card']} #{d.get('give_asset')} {where}{' to ' + d['to'] if d.get('to') else ''}: "
                f"value {_num(d.get('value'))} - our copy {_num(d.get('give_value'))} = gain if filled "
                f"{d['gain']:+.1f} vs need {_num(d.get('need'))}" if d.get("gain") is not None else f"{where}")
    elif k == "swap":
        nums = f"offer {d.get('offer')} {where}" + (f" for our {d['give_card']}" if d.get("give_card") else "")
    else:
        nums = f"offer {d.get('offer')} {where}"
    return f"{head} {nums} -> {d['action'].upper()}: {d['reason']}"


def decide(snap: dict, valuer: Valuer, tape: Tape, ledger: Ledger, cfg: Config, bidbook: dict | None = None,
           swapbook: dict | None = None) -> dict:
    """One tick's decisions. Pure: reads the snapshot, returns records; sends nothing.

    snap: tick, t_hours, me_id, cash, holdings {ref: [asset dicts]}, venues {vid: {fee, owner, house}},
          boards {vid: [offers]}, mine [our open/queued offers and offers addressed to us], released {set ids},
          reserved {asset ids rastro_seller's config may list} (optional).
    bidbook: our live bids {ref: {offer, price, to, since, anchor}} (run: from /api/me/offers; watch: simulated).
    swapbook: our live swaps {ref we ask: {offer, asset, give_card, to, since}} (same sources)."""
    tick, th, me = snap["tick"], float(snap.get("t_hours") or 0.0), snap["me_id"]
    cash = int(snap.get("cash") or 0)
    holdings = snap.get("holdings") or {}
    counts = {r: len(a) for r, a in holdings.items() if a}
    valuer.set_counts(counts)
    venues = snap.get("venues") or {}
    bidbook = dict(bidbook or {})
    swapbook = dict(swapbook or {})
    reserved = set(snap.get("reserved") or ())
    bid_committed = sum(int(b.get("price") or 0) for b in bidbook.values() if b.get("offer") is not None)
    # page mode: the most each page card we still lack may cost stays free for it, in cash and in spend room
    page_reserve = sum(int(p["cap"]) for r, p in cfg.page_targets.items() if counts.get(r, 0) == 0)
    yields = set(snap.get("page_yield") or ())   # page-yield files: a fallback step buys these, the desk stands down
    # every open or queued cash offer of ours (/api/me/offers: bids of any agent, dealer-thread offers) is cash that
    # may leave at any tick: it stays held, in cash and in spend room, until its cancel or settlement shows
    commit = cash_commitments(snap.get("mine") or [], me)
    page_live = {(bidbook.get(r) or {}).get("offer") for r in cfg.page_targets} - {None}
    own_live = {b.get("offer") for r, b in bidbook.items() if r not in cfg.page_targets} - {None}
    outside_page = sum(v for k, v in commit.items() if k not in page_live)            # beyond our page bids
    outside_bids = sum(v for k, v in commit.items() if k not in page_live | own_live)  # beyond every bid we plan
    mine = [o for o in snap.get("mine") or [] if isinstance(o, dict)]
    my_ids = {o.get("id") for o in mine if o.get("maker") == me}
    our_assets = {a["id"]: r for r, lst in holdings.items() for a in lst if isinstance(a, dict) and "id" in a}
    listed_assets = {}
    for o in mine:
        if o.get("maker") == me and o.get("status") in ("open", "queued"):
            for a in (o.get("give") or {}).get("assets") or []:
                listed_assets[a.get("id") if isinstance(a, dict) else a] = o.get("id")
    pending = set()   # cards with an offer of ours that is settling: do not touch them this tick
    for o in mine:
        if o.get("maker") == me and o.get("status") == "queued":
            for a in (o.get("give") or {}).get("assets") or []:
                pending.add(a.get("ref") if isinstance(a, dict) else our_assets.get(a))
            for t in (o.get("want") or {}).get("types") or []:
                if isinstance(t, str) and t.startswith("card:"):
                    pending.add(t[5:])
    records, cands = [], []
    base = {"tick": tick, "t_hours": round(th, 3)}

    def fee_of(vid: str) -> tuple:
        v = venues.get(vid) or {}
        return tuple(v.get("fee") or (DEFAULT_FEE if vid == HOME else WORST_FEE))

    def owner_of(vid: str):
        v = venues.get(vid) or {}
        return None if v.get("house") or vid == HOME else v.get("owner")

    # our pseudonyms: a board offer whose id is ours tells us which maker label is us on that venue
    ours_label = {(vid, o.get("maker")) for vid, offs in (snap.get("boards") or {}).items() for o in offs
                  if isinstance(o, dict) and o.get("id") in my_ids}

    seen_ids = set()
    sources = [(vid, o) for vid, offs in (snap.get("boards") or {}).items() for o in offs or []]
    sources += [(o.get("venue") or HOME, o) for o in mine if o.get("to") == me and o.get("maker") != me]
    for vid, o in sources:
        if not isinstance(o, dict) or o.get("id") in seen_ids:
            continue
        seen_ids.add(o.get("id"))
        if o.get("id") in my_ids or (vid, o.get("maker")) in ours_label:
            continue
        shape = classify(o)
        partner = tape.maker.get(o.get("id")) or o.get("maker")
        rec = {**base, "offer": o.get("id"), "venue": vid, "venue_owner": owner_of(vid), "partner": partner,
               "addressed": o.get("to") == me}
        if shape == "listing":
            chk = check_listing(o, me, tick)
            rec.update(kind="buy", card=chk.get("ref"))
            if not chk["ok"]:
                records.append({**rec, "action": "skip", "reason": f"structure: {chk['reason']}"})
                continue
            ref, price = chk["ref"], chk["price"]
            info = valuer.info(ref)
            fee = fee_for(price, fee_of(vid))
            rec.update(price=price, fee=fee, set=info["set"], rarity=info["rarity"], asset=chk["asset"])
            page = cfg.page_targets.get(ref)
            if page:   # every page-card record carries the page numbers, the held-card skip below included
                rec.update(page=True, cap=page["cap"], ceiling=page["cap"],
                           anchor=(bidbook.get(ref) or {}).get("anchor"))
            if counts.get(ref, 0) > 0:
                v, src = valuer.offline_more(ref), "offline"
                records.append({**rec, "value": v, "value_src": src, "gain": round(v - price - fee, 2),
                                "need": round(need_buy(v, cfg), 2), "action": "skip",
                                "reason": f"we hold {counts[ref]} (another copy is worth {v:.1f}, 25 % or less)"})
                continue
            off = valuer.offline_more(ref)
            if off - price - fee < need_buy(off, cfg) - SERVER_SLACK and not valuer.completes_page(ref):
                v, src = off, "offline"   # clearly short: no keyed request for it
            else:
                v, src = valuer.more(ref)
            gain, need = round(v - price - fee, 2), round(need_buy(v, cfg), 2)
            rec.update(value=round(v, 2), value_src=src, gain=gain, need=need)
            page_venue = page_venue_ok(venues, vid, me) if page and vid != HOME else None
            if ref in pending:
                records.append({**rec, "action": "skip", "reason": "an offer of ours on this card is settling"})
            elif page and ref in yields:
                records.append({**rec, "action": "skip", "reason": f"page-yield file for {ref}: the fallback buys it"})
            elif page_venue:
                records.append({**rec, "action": "skip", "reason": page_venue})
            elif page and price + fee > page["cap"]:
                records.append({**rec, "action": "skip",
                                "reason": f"page cap: price {price} + fee {fee} = {price + fee} > cap {page['cap']}"})
            elif gain < need:
                records.append({**rec, "action": "skip", "reason": f"gain {gain:+.1f} below need {need:.1f}"})
            elif owner_of(vid) and not cfg.team_venues and not page:   # a page card may come from a team board
                records.append({**rec, "action": "skip", "reason": "team venue (off by --no-team-venues)"})
            else:
                # live bids do not hold back a buy: a buy is the surer gain, and the bid planner below then
                # cancels the bids that no longer fit in cash - min cash (run sends those cancels first)
                why = buy_caps(cfg, price=price, fee=fee, info=info, cash=cash, ledger=ledger, t_hours=th,
                               partner=partner, max_price=page["cap"] if page else None,
                               committed=outside_page + (0 if page else page_reserve),
                               spend_committed=outside_page + (0 if page else page_reserve))
                if why:
                    records.append({**rec, "action": "skip", "reason": why})
                else:
                    cands.append({**rec, "side": "buy"})
        elif shape == "bid":
            chk = check_bid(o, me, our_assets, tick)
            rec.update(kind="sell", card=chk.get("ref"))
            if not chk["ok"]:
                records.append({**rec, "action": "skip", "reason": f"structure: {chk['reason']}"})
                continue
            ref, price = chk["ref"], chk["price"]
            info = valuer.info(ref)
            fee = fee_for(price, fee_of(vid))
            k = counts.get(ref, 0)
            rec.update(price=price, fee=fee, set=info["set"], rarity=info["rarity"], copies=k)
            if k == 0:
                records.append({**rec, "action": "skip", "reason": "we hold no copy"})
                continue
            v, src = valuer.copy(ref)
            need = round(need_sell(v, cfg), 2)
            gain = round(price - fee - v, 2)
            rec.update(value=round(v, 2), value_src=src, need=need, gain=gain)
            asset, why = pick_asset(holdings.get(ref) or [], chk["asset"], listed_assets, cfg, k, info)
            if ref in pending:
                why = why or "an offer of ours on this card is settling"
            if why is None and price - fee < v + need:
                why = f"net {price - fee} below copy {v:.1f} + need {need:.1f}"
            if why is None and owner_of(vid) and not cfg.team_venues:
                why = "team venue (off by --no-team-venues)"
            if why is None and partner and ledger.partner_trades(partner, th) >= cfg.partner_hour:
                why = f"cap: {cfg.partner_hour} trades with {partner} this game hour"
            if why:
                records.append({**rec, "action": "skip", "reason": why})
            else:
                cands.append({**rec, "side": "sell", "asset": asset,
                              "cancel_listing": listed_assets.get(asset)})
        elif shape == "swap" and cfg.swap_fill:
            chk = check_swap(o, me, our_assets, tick)
            rec.update(kind="swap", card=chk.get("ref"), give_card=chk.get("want_ref"))
            if not chk["ok"]:
                records.append({**rec, "action": "skip", "reason": f"structure: {chk['reason']}"})
                continue
            if vid != HOME and not cfg.swap_team_venue:
                records.append({**rec, "action": "skip", "reason": f"swap on {vid}: fills on {HOME} only "
                                                                   f"(--swap-team-venue to allow a team venue)"})
                continue
            ref, yref = chk["ref"], chk["want_ref"]
            info, yinfo = valuer.info(ref), valuer.info(yref)
            fee = swap_fee(fee_of(vid))
            k = counts.get(yref, 0)
            rec.update(price=0, fee=fee, set=info["set"], rarity=info["rarity"], their_asset=chk["asset"], copies=k)
            if counts.get(ref, 0) > 0:
                records.append({**rec, "action": "skip", "reason": f"we hold {counts[ref]} of {ref}"})
                continue
            if k == 0:
                records.append({**rec, "action": "skip", "reason": f"we hold no copy of {yref}"})
                continue
            vy, ysrc = valuer.copy(yref)
            off = valuer.offline_more(ref)
            if off - vy - fee < need_buy(off, cfg) - SERVER_SLACK and not valuer.completes_page(ref):
                v, src = off, "offline"   # clearly short: no keyed request for it
            else:
                v, src = valuer.more(ref)
            gain, need = round(v - vy - fee, 2), round(need_buy(v, cfg), 2)
            rec.update(value=round(v, 2), value_src=src, give_value=round(vy, 2), give_value_src=ysrc, gain=gain,
                       need=need)
            asset, why = pick_swap_asset(holdings.get(yref) or [], chk["want_asset"], listed_assets, reserved, cfg,
                                         k, yinfo)
            if why is None and (ref in pending or yref in pending):
                why = "an offer of ours on this card is settling"
            if why is None and gain < need:
                why = f"gain {gain:+.1f} below need {need:.1f}"
            if why is None and owner_of(vid) and not cfg.team_venues:
                why = "team venue (off by --no-team-venues)"
            if why is None:
                why = swap_caps(cfg, fee=fee, cash=cash, ledger=ledger, t_hours=th, partner=partner,
                                committed=bid_committed)
            if why:
                records.append({**rec, "action": "skip", "reason": why})
            else:
                cands.append({**rec, "side": "swap", "asset": asset, "cancel_listing": listed_assets.get(asset)})
        elif shape == "swap":
            records.append({**rec, "kind": "swap", "card": None, "action": "skip",
                            "reason": "swap fills off (--swap-fills to accept other teams' swaps)"})
        else:
            records.append({**rec, "kind": shape if shape != "other" else "skip", "card": None, "action": "skip",
                            "reason": f"structure: {shape} (not a one-card listing or bid)"})

    # one accept per tick: the best gain; one per card. Never while agent/duel.py holds results/duel.lock.
    cands.sort(key=lambda c: (-c["gain"], c.get("price") or 0, c.get("offer") or 0))
    accept, taken_refs = None, set()
    for c in cands:
        if c["card"] in taken_refs:
            records.append({**c, "action": "skip", "reason": "a better offer on the same card"})
            continue
        taken_refs.add(c["card"])
        if snap.get("duel_lock"):
            records.append({**c, "action": "defer", "reason": "results/duel.lock is fresh: the duel bot holds "
                                                              "the team's accept slot"})
        elif snap.get("duel_live"):
            records.append({**c, "action": "defer", "reason": snap["duel_live"]})
        elif c.get("page") and snap.get("duel_any"):   # --duel-guard-ticks never relaxes a page write
            records.append({**c, "action": "defer", "reason": snap["duel_any"]})
        elif snap.get("feed_down") or snap.get("spans_ticks"):
            records.append({**c, "action": "defer", "reason": snap.get("feed_down") or snap["spans_ticks"]})
        elif accept is None:
            accept = c
            note = ""
            if c["side"] in ("buy", "swap") and (bidbook.get(c["card"]) or {}).get("offer") is not None:
                note = f"; cancel our bid {bidbook[c['card']]['offer']} first"
            if c["side"] in ("buy", "swap") and (swapbook.get(c["card"]) or {}).get("offer") is not None:
                note += f"; cancel our swap {swapbook[c['card']]['offer']} first"
            if c.get("cancel_listing"):
                note += f"; cancel our listing {c['cancel_listing']} first"
            records.append({**c, "action": "take", "reason": f"best gain this tick ({c['gain']:+.1f}){note}"})
        else:
            records.append({**c, "action": "defer", "reason": f"one accept per tick (taking {accept['card']} "
                                                              f"{accept['gain']:+.1f})"})

    # page bids first: they take the cash before the other bids, which never touch a page card
    page_actions = plan_page_bids(snap, valuer, tape, ledger, cfg, bidbook, counts, pending, accept, cash,
                                  outside=outside_page) if cfg.page_targets else []
    page_committed = sum(int(b["price"] or 0) for b in page_actions if b["action"] in ("post", "keep", "replace"))
    bid_actions = page_actions + (plan_bids(snap, valuer, tape, ledger, cfg, bidbook, counts, pending, accept, cash,
                                            committed=max(page_committed, page_reserve) + outside_bids,
                                            skip=set(cfg.page_targets))
                                  if cfg.bids else [])
    for b in bid_actions:
        records.append({**base, **b["record"]})
    bid_cards = {b["card"] for b in bid_actions if b["action"] in ("post", "keep", "replace")}
    live_swaps = any(s.get("offer") is not None for s in swapbook.values())
    swap_actions = plan_swaps(snap, valuer, tape, cfg, swapbook, holdings, counts, pending, accept, listed_assets,
                              bid_cards) if cfg.swap_post or live_swaps else []
    for s in swap_actions:
        records.append({**base, **s["record"]})
    return {"records": records, "accept": accept, "bids": bid_actions, "swaps": swap_actions}


def pick_asset(copies: list, wanted, listed: dict, cfg: Config, k: int, info: dict) -> tuple:
    """Which of our copies a sale would hand over, or why none may go. Keeps the lowest serial; never the only copy
    on a protected page; a single copy only for --sell-first-copies sets; a listed copy only with --sell-listed."""
    s = info.get("set")
    if k == 1:
        if s in cfg.protect:
            return None, f"protected: our only copy on the {s} page"
        if s not in cfg.sell_first_copies:
            return None, "not a spare (our only copy; set not in --sell-first-copies)"
    ordered = sorted((a for a in copies if isinstance(a, dict)), key=lambda a: (a.get("serial") or 0, a.get("id")))
    keep = ordered[0]["id"] if k >= 2 and ordered else None
    pool = [a["id"] for a in reversed(ordered) if a["id"] != keep]
    if wanted is not None:
        if wanted == keep:
            return None, "they want the copy we keep (lowest serial)"
        pool = [a for a in pool if a == wanted]
    free = [a for a in pool if a not in listed]
    if free:
        return free[0], None
    if pool and cfg.sell_listed:
        return pool[0], None
    if pool:
        return None, f"the spare is listed by rastro_seller (offer {listed.get(pool[0])}); --sell-listed to override"
    return None, "no copy we may hand over"


def pick_swap_asset(copies: list, wanted, listed: dict, reserved: set, cfg: Config, k: int, info: dict) -> tuple:
    """Which of our copies a swap fill would hand over, or why none may go. Stricter than a sale: never our last
    copy of a card (--sell-first-copies does not apply), the lowest serial stays, and never an asset in
    rastro_seller's config (reserved) unless --swap-seller-spares."""
    if k <= 1:
        if info.get("set") in cfg.protect:
            return None, f"protected: our only copy on the {info.get('set')} page"
        return None, "not a spare (our only copy: swaps never give a last copy)"
    seller = set() if cfg.swap_seller_spares else set(reserved)
    ordered = sorted((a for a in copies if isinstance(a, dict)), key=lambda a: (a.get("serial") or 0, a.get("id")))
    keep = ordered[0]["id"] if ordered else None
    pool = [a["id"] for a in reversed(ordered) if a["id"] != keep]
    if wanted is not None:
        if wanted == keep:
            return None, "they want the copy we keep (lowest serial)"
        pool = [a for a in pool if a == wanted]
    held = [a for a in pool if a in seller]
    pool = [a for a in pool if a not in seller]
    if held and not pool:
        return None, f"#{held[0]} is in rastro_seller's config (--swap-seller-spares to override)"
    free = [a for a in pool if a not in listed]
    if free:
        return free[0], None
    if pool and cfg.sell_listed:
        return pool[0], None
    if pool:
        return None, f"the spare is listed by rastro_seller (offer {listed.get(pool[0])}); --sell-listed to override"
    return None, "no copy we may hand over"


def plan_bids(snap, valuer, tape, ledger, cfg, bidbook, counts, pending, accept, cash, committed: int = 0,
              skip=()) -> list:
    """Our want-to-buy offers on El Rastro: which cards, at what price, and what to post, keep or cancel.
    `committed`: cash the page bids hold; `skip`: the page cards (plan_page_bids owns their bids).
    Two rules against churn (Saturday 2026-10-03, ticks 216-257: LAV-09 and LAV-10 bids cancelled and reposted every
    few ticks): the step clock's base (the anchor) a post or replace carries is the one its price was computed from,
    so the next tick finds the same price; and a live bid whose stepped price no longer fits the cash or the spend
    caps stays at its live price when that still fits, instead of being cancelled for another card."""
    tick, th, me = snap["tick"], float(snap.get("t_hours") or 0.0), snap["me_id"]
    released = set(snap.get("released") or [])
    boards = snap.get("boards") or {}
    competing: dict = {}   # best other bid per card
    lowest_ask: dict = {}
    for vid, offs in boards.items():
        for o in offs or []:
            if not isinstance(o, dict) or o.get("status") != "open":
                continue
            g, w = (o.get("give") or {}), (o.get("want") or {})
            rb = rival_bid(o)
            if rb and (bidbook.get(rb[0]) or {}).get("offer") != o.get("id"):
                competing[rb[0]] = max(competing.get(rb[0], 0), rb[1])
            if len(g.get("assets") or []) == 1 and isinstance(g["assets"][0], dict) and _int_cash(w.get("cash")):
                r = g["assets"][0].get("ref")
                lowest_ask[r] = min(lowest_ask.get(r, 10 ** 9), w["cash"])
    pre = []
    for ref, info in valuer.cards.items():
        if not info["page"] or info["hidden"] or info["set"] not in released or counts.get(ref, 0) > 0:
            continue
        if ref in pending or ref in skip or (accept and accept["card"] == ref):
            continue
        pre.append((-valuer.offline_more(ref), ref, info))
    pre.sort()
    wanted = []
    for i, (_, ref, info) in enumerate(pre):
        # the server's value only for the cards that could make the list (each one is a keyed request)
        v, src = valuer.more(ref) if i < cfg.bid_max + 4 else (valuer.offline_more(ref), "offline")
        if v < cfg.bid_min_value:
            continue
        need = need_buy(v, cfg)
        ceiling = int(math.floor(min(v - need, price_cap(cfg, info))))
        if ceiling < 1:
            continue
        ps, scope = tape.prices(ref, info["set"], info["rarity"], before=snap.get("tape_before"), last=cfg.price_window)
        if ps:
            anchor = int(round(percentile(ps, 0.25)))
            basis = f"p25 of {len(ps)} {scope} trades {min(ps)}-{max(ps)}"
        else:
            anchor = int(round(0.8 * info["book"]))
            basis = "80 % of book (no trades seen)"
        if competing.get(ref):
            anchor = max(anchor, competing[ref] + 1)
            basis += f", other bid {competing[ref]}"
        anchor = max(1, min(anchor, ceiling))
        live = bidbook.get(ref) or {}
        since = live.get("since", tick)
        steps = max(0, (tick - since) // max(1, cfg.bid_step_ticks))
        base = max(anchor, int(live.get("anchor") or anchor))
        price = min(ceiling, base + cfg.bid_step * steps)
        wanted.append({"card": ref, "value": round(v, 2), "value_src": src, "ceiling": ceiling, "anchor": anchor,
                       "base": base, "price": price, "gain": round(v - price, 2), "price_basis": basis,
                       "set": info["set"], "rarity": info["rarity"], "since": since, "lowest_ask": lowest_ask.get(ref)})
    wanted.sort(key=lambda w: (-w["gain"], w["card"]))
    out = []
    budget = cash - cfg.min_cash - committed - accept_cost(accept)
    # spend room: this tick's accept, the page bids and every bid chosen before this one come off it too
    room_hour = cfg.cap_hour - ledger.spent(th, 1.0) - accept_cost(accept) - committed
    room_day = cfg.cap_day - ledger.spent(th, None) - accept_cost(accept) - committed
    chosen = set()
    for w in wanted:
        live = bidbook.get(w["card"])
        held = int(live["price"]) if live and live.get("offer") is not None and _int_cash(live.get("price")) else None
        if len(chosen) >= cfg.bid_max:
            reason, act = f"not in the top {cfg.bid_max} by gain", "skip"
        elif w["price"] > budget:
            reason, act = f"cash: bid {w['price']} > room {budget} (cash {cash} - min {cfg.min_cash} - other bids)", "skip"
        elif w["price"] > min(room_hour, room_day):
            reason, act = f"spend caps: room {min(room_hour, room_day)}", "skip"
        else:
            reason, act = "", "post"
            budget -= w["price"]
            room_hour, room_day = room_hour - w["price"], room_day - w["price"]
            chosen.add(w["card"])
        if act == "skip" and len(chosen) < cfg.bid_max and held is not None \
                and held <= min(budget, room_hour, room_day, w["ceiling"]):
            # the step does not fit, the live bid does: keep it (cancelling it for another card was Saturday's churn)
            act, reason = "keep", f"live bid {live['offer']} stays at {held}: the step to {w['price']} does not fit " \
                                  f"({reason})"
            w = {**w, "price": held, "gain": round(w["value"] - held, 2)}
            budget -= held
            room_hour, room_day = room_hour - held, room_day - held
            chosen.add(w["card"])
        to = None
        if act == "post" and cfg.address_bids:
            to = tape.last_receiver(w["card"], exclude=me)
        if act == "keep":
            to = live.get("to")
        if act == "post" and live and live.get("offer") is not None:
            if live.get("price") == w["price"] and live.get("to") == to:
                act, reason = "keep", f"live bid {live['offer']} at {w['price']}"
            else:
                act, reason = "replace", f"bid {live['offer']} {live.get('price')} -> {w['price']}"
        elif act == "post":
            reason = f"new bid (gain if filled {w['gain']:+.1f})"
        if act == "skip" and w["gain"] < 1:
            continue  # nothing to say about cards we would not bid for anyway
        rec = {"kind": "bid", "card": w["card"], "venue": cfg.bid_venue, "to": to, "price": w["price"],
               "value": w["value"], "value_src": w["value_src"], "ceiling": w["ceiling"], "anchor": w["anchor"],
               "gain": w["gain"], "price_basis": w["price_basis"], "set": w["set"], "rarity": w["rarity"],
               "lowest_ask": w["lowest_ask"], "action": act, "reason": reason, "offer": (live or {}).get("offer")}
        out.append({"action": act, "card": w["card"], "price": w["price"], "to": to, "anchor": w["base"],
                    "since": w["since"], "offer": (live or {}).get("offer"), "record": rec})
    for ref, live in bidbook.items():
        if ref in chosen or ref in skip or live.get("offer") is None:
            continue
        why = "card arrived" if counts.get(ref, 0) > 0 else ("buying it this tick" if accept and accept["card"] == ref
                                                             else "no longer among the bids we want")
        rec = {"kind": "bid", "card": ref, "venue": cfg.bid_venue, "price": live.get("price"), "offer": live["offer"],
               "action": "cancel", "reason": why}
        out.append({"action": "cancel", "card": ref, "offer": live["offer"], "price": live.get("price"), "record": rec})
    return out


def page_floor(ref: str, info: dict, spec: dict, tape: Tape, cfg: Config, before=None) -> tuple:
    """(first price of a page bid, basis): the --page floor, else the p25 of the team trades for the card (else its
    set and rarity, else its rarity), else 80 % of book."""
    if spec.get("floor"):
        return int(spec["floor"]), "--page floor"
    ps, scope = tape.prices(ref, info["set"], info["rarity"], before=before, last=cfg.price_window)
    if ps:
        return int(round(percentile(ps, 0.25))), f"p25 of {len(ps)} {scope} team trades {min(ps)}-{max(ps)}"
    return int(round(0.8 * info["book"])), "80 % of book (no team trades seen)"


def plan_page_bids(snap, valuer, tape, ledger, cfg, bidbook, counts, pending, accept, cash, outside: int = 0) -> list:
    """Page mode (--page REF:CAP[:FLOOR], docstring step 8): ONE bid per target card on El Rastro, addressed to nobody
    (any holder can hit it) unless --page-address. It starts at the team price floor (page_floor, or one above
    another team's live bid for the card), steps up by --page-step every --page-step-ticks since it was first posted,
    and never goes above the cap, value - margin, the cost of a live El Rastro ask for the card (that one is taken
    instead), the cash above --min-cash or the spend caps. A live bid never steps down (no churn); when its next step
    does not fit it stays at its live price if that fits, else it is cancelled. During our duels it is still posted
    and raised (a fill uses the seller's accept, not ours); only an unread /api/duels holds it (a live bid stays
    as it is; cancels still go). A page-yield file for the card cancels the bid and stops it. Page bids take the
    cash first; plan_bids never touches a page card."""
    tick, th, me = snap["tick"], float(snap.get("t_hours") or 0.0), snap["me_id"]
    # a page bid is posted and raised during our duels too: a holder filling it spends THEIR accept, not ours, so the
    # duel bot keeps the team's one accept per tick (duel.lock / the lease are about accepts only), and a duel moves
    # no cash (kit/RULES.md "Duels": points on the pie share). Held: /api/duels unread, an unread feed, a torn snapshot.
    hold = snap.get("duels_unread") or snap.get("feed_down") or snap.get("spans_ticks")
    home_fee = tuple(((snap.get("venues") or {}).get(HOME) or {}).get("fee") or DEFAULT_FEE)
    ours = {b.get("offer") for b in bidbook.values() if b.get("offer") is not None}
    ours |= {o.get("id") for o in snap.get("mine") or [] if isinstance(o, dict) and o.get("maker") == me}
    asks, rivals = {}, {}
    for o in (snap.get("boards") or {}).get(HOME) or []:
        if not isinstance(o, dict) or o.get("id") in ours or o.get("status") != "open":
            continue
        chk = check_listing(o, me, tick)
        if chk["ok"] and chk["ref"] in cfg.page_targets:
            cost = chk["price"] + fee_for(chk["price"], home_fee)
            asks[chk["ref"]] = min(asks.get(chk["ref"], 10 ** 9), cost)
        rb = rival_bid(o)
        if rb and rb[0] in cfg.page_targets:
            rivals[rb[0]] = max(rivals.get(rb[0], 0), rb[1])
    # `outside`: our other open or queued cash offers (decide); they stay held until cancelled or settled
    budget = cash - cfg.min_cash - accept_cost(accept) - outside
    # spend room: this tick's accept and those offers come off it, and so does every page bid kept or posted before
    room = min(cfg.cap_hour - ledger.spent(th, 1.0), cfg.cap_day - ledger.spent(th, None)) - accept_cost(accept) \
        - outside
    out = []
    for ref, spec in sorted(cfg.page_targets.items()):
        live = bidbook.get(ref) or {}
        lid = live.get("offer")
        held = int(live["price"]) if lid is not None and _int_cash(live.get("price")) else None
        rec = {"kind": "bid", "page": True, "card": ref, "venue": HOME, "cap": spec["cap"], "offer": lid,
               "to": live.get("to"), "price": held}

        def emit(act, reason, price=None, to=None, base=None, first=None, **extra):
            r = {**rec, **extra, "action": act, "reason": reason}
            if price is not None:
                r["price"] = price
            if act in ("post", "replace"):
                r["to"] = to
            out.append({"action": act, "card": ref, "price": r["price"], "to": r["to"], "anchor": base,
                        "since": first, "offer": lid, "page": True, "record": r})

        info = valuer.info(ref)
        v, src = valuer.more(ref)
        need = need_buy(v, cfg)
        ceiling, why_ceiling = int(math.floor(min(spec["cap"], v - need))), "cap / value - margin"
        if ref in asks and asks[ref] - 1 < ceiling:
            ceiling, why_ceiling = asks[ref] - 1, f"a live ask costs {asks[ref]}"
        start, basis = page_floor(ref, info, spec, tape, cfg, before=snap.get("tape_before"))
        if rivals.get(ref):
            start, basis = max(start, rivals[ref] + 1), basis + f", other bid {rivals[ref]}"
        anchor = int(live.get("anchor") or start) if live else start
        since = live.get("since", tick)
        steps = max(0, (tick - since) // max(1, cfg.page_step_ticks))
        price = max(anchor + cfg.page_step * steps, start, held or 0)
        price = min(price, ceiling)
        limit = min(budget, room)
        to = tape.last_receiver(ref, exclude=me) if cfg.page_address else None
        nums = dict(value=round(v, 2), value_src=src, need=round(need, 2), ceiling=ceiling, anchor=anchor,
                    price_basis=basis, set=info["set"], rarity=info["rarity"], lowest_ask=asks.get(ref),
                    other_bid=rivals.get(ref), gain=round(v - price, 2))
        if ref in set(snap.get("page_yield") or ()):   # a fallback step buys it: cancel ours, bid no more
            emit("cancel" if lid is not None else "skip", f"page-yield file for {ref}: the fallback buys it", **nums)
            continue
        if counts.get(ref, 0) > 0:   # value is then what one more copy is worth: the page is complete
            if lid is not None:
                emit("cancel", "page card arrived", **nums)
            else:
                emit("skip", f"we hold {ref}: the page is complete", **nums)
            continue
        if accept and accept["card"] == ref:
            if lid is not None:
                emit("cancel", "buying it this tick", **nums)
            continue
        if ref in pending:
            emit("skip", "an offer of ours on this card is settling", **nums)
            continue
        if ceiling < max(1, start if held is None else 1):
            why = f"ceiling {ceiling} ({why_ceiling}) below the first price {start}"
            emit("cancel" if lid is not None else "skip", why, **nums)
            continue
        if held is not None and held > ceiling:
            emit("cancel", f"live bid {held} above the ceiling {ceiling} ({why_ceiling})", **nums)
            continue
        if price > limit or hold:
            short = f"cash: bid {{}} > room {limit} (cash {cash} - min {cfg.min_cash}, spend caps {room})"
            if held is not None and held <= limit:
                budget, room = budget - held, room - held
                why = f"hold: {hold}" if hold else short.format(price)
                emit("keep", f"live bid {lid} stays at {held} ({why})", **{**nums, "gain": round(v - held, 2)})
            elif held is not None:
                emit("cancel", short.format(held), **nums)
            else:
                emit("skip", f"hold: {hold}: no new page bid" if hold else short.format(price), price=price, **nums)
            continue
        budget, room = budget - price, room - price
        if held is None:
            emit("post", f"page bid {price} (gain if filled {v - price:+.1f}, steps to {ceiling})", price=price,
                 to=to, base=anchor, first=since, **nums)
        elif held == price and live.get("to") == to:
            emit("keep", f"live bid {lid} at {price}", **nums)
        else:
            emit("replace", f"bid {lid} {held} -> {price}", price=price, to=to, base=anchor, first=since, **nums)
    return out


RARITY_RANK = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4}


def swap_pool(holdings: dict, counts: dict, cfg: Config, valuer: Valuer, busy: dict, reserved: set, skip_refs: set):
    """Our copies a swap of ours may give: {ref: {assets (offer order), value of our copy, rarity}}, plus notes on
    the spares held back. Stricter than a sale: keep the lowest serial and never give our last copy of a card
    (--sell-first-copies does not apply to swaps), and an asset that another live offer of ours holds (busy:
    {asset: offer}, e.g. a rastro_seller listing) is never offered again. Copies in rastro_seller's config stay with
    the seller unless --swap-seller-spares: its sync adopts any single-asset El Rastro offer of ours as its listing."""
    pool, held_back = {}, []
    for ref in sorted(holdings):
        k = counts.get(ref, 0)
        if k == 0 or ref in skip_refs:
            continue
        info = valuer.info(ref)
        if k <= 1:                               # our last copy never goes in a swap
            continue
        ordered = sorted((a for a in holdings[ref] if isinstance(a, dict) and isinstance(a.get("id"), int)),
                         key=lambda a: (a.get("serial") or 0, a["id"]))
        keep = ordered[0]["id"] if k >= 2 and ordered else None
        free = []
        for a in reversed(ordered):
            aid = a["id"]
            if aid == keep or aid < 0:          # negative ids: watch's would-be buys, not real assets
                continue
            if aid in busy:
                held_back.append(f"{ref} #{aid} (in our offer {busy[aid]})")
            elif aid in reserved and not cfg.swap_seller_spares:
                held_back.append(f"{ref} #{aid} (rastro_seller's config)")
            else:
                free.append(aid)
        if free:
            v, src = valuer.copy(ref)
            pool[ref] = {"assets": free, "value": round(v, 2), "src": src, "rarity": info["rarity"]}
    return pool, held_back


def plan_swaps(snap, valuer, tape, cfg, swapbook, holdings, counts, pending, accept, listed_assets, bid_cards) -> list:
    """Our own swaps on cfg.swap_venue: give one spare, want {"cards": [ref]}, no cash either way. The side that
    accepts pays the fee, so our gain is value(one more of ref) - value of our copy, held to the buy margin. For each
    page card we lack (most valuable first) the spare whose value to us is lowest, of the same rarity or higher
    (--swap-any-rarity drops that), one copy per card given, one swap per card asked, at most --swap-max live. Never a
    card we are bidding for, buying this tick or that is settling; never an asset another offer of ours holds."""
    tick, me = snap["tick"], snap["me_id"]
    released = set(snap.get("released") or [])
    reserved = set(snap.get("reserved") or ())
    limit = cfg.swap_max if cfg.swap_post else 0
    our_swap_offers = {s.get("offer") for s in swapbook.values() if s.get("offer") is not None}
    busy = {a: oid for a, oid in listed_assets.items() if oid not in our_swap_offers}
    skip_refs = set(pending)
    if accept and accept.get("side") in ("sell", "swap"):
        busy[accept.get("asset")] = f"accept {accept.get('offer')}"
        skip_refs.add(accept.get("give_card") if accept["side"] == "swap" else accept["card"])
    pool, held_back = swap_pool(holdings, counts, cfg, valuer, busy, reserved, skip_refs)
    out = []
    if limit and (pool or held_back):
        note = ("spares we may give: " + (", ".join(f"{r} #{p['assets'][0]} ({p['value']:.1f})" for r, p in
                                                     sorted(pool.items(), key=lambda x: x[1]["value"])) or "none"))
        if held_back:
            note += "; held back: " + ", ".join(held_back)
        out.append({"action": "note", "card": None, "record": {"kind": "myswap", "card": None, "action": "note",
                                                               "venue": cfg.swap_venue, "reason": note}})
    wanted = []
    for ref, info in valuer.cards.items():
        if not info["page"] or info["hidden"] or info["set"] not in released or counts.get(ref, 0) > 0:
            continue
        if ref in pending or ref in bid_cards or (accept and accept["card"] == ref):
            continue
        live_first = 0 if (swapbook.get(ref) or {}).get("offer") is not None else 1   # live swaps keep their place
        wanted.append((live_first, -valuer.offline_more(ref), ref, info))
    wanted.sort()
    owner = {s["asset"]: x for x, s in swapbook.items() if s.get("offer") is not None and s.get("asset") is not None}
    chosen, used = {}, set()
    for i, (_, _, ref, info) in enumerate(wanted):
        if not pool or len(chosen) >= limit:
            break
        # the server's value only for the cards that could make the list (each one is a keyed request)
        v, src = valuer.more(ref) if i < limit + 4 else (valuer.offline_more(ref), "offline")
        if v < cfg.swap_min_value:
            continue
        need = need_buy(v, cfg)
        live = swapbook.get(ref) or {}
        options = []
        for y, p in pool.items():
            if y in used or v - p["value"] < need:
                continue
            if not cfg.swap_any_rarity and RARITY_RANK.get(p["rarity"], 0) < RARITY_RANK.get(info["rarity"], 0):
                continue
            mine = [a for a in p["assets"] if owner.get(a, ref) == ref]   # a copy another live swap holds stays there
            if mine:
                options.append((p["value"], y, mine))
        if not options:
            continue
        # keep the live swap's copy while it still passes (no churn of the listing quota), else the cheapest to us
        same = [o for o in options if live.get("asset") in o[2]]
        vy, yref, assets = same[0] if same else min(options, key=lambda o: (o[0], o[1]))
        asset = live["asset"] if same else assets[0]
        used.add(yref)
        to = None
        if cfg.address_swaps:   # a public holder of the card, preferring one not known to hold the card we give
            holders = tape.owners(ref, exclude=me)
            lacking = [t for t in holders if t not in set(tape.owners(yref))]
            to = tape.last_receiver(ref, exclude=me, among=lacking or holders)
        chosen[ref] = {"card": ref, "give_card": yref, "asset": asset, "to": to, "value": round(v, 2),
                       "value_src": src, "give_value": vy, "gain": round(v - vy, 2), "need": round(need, 2),
                       "set": info["set"], "rarity": info["rarity"], "since": live.get("since", tick)}
    for ref, c in chosen.items():
        live = swapbook.get(ref) or {}
        if live.get("offer") is not None and live.get("asset") == c["asset"] and live.get("to") == c["to"]:
            act, reason = "keep", f"live swap {live['offer']} gives {c['give_card']} #{c['asset']}"
        elif live.get("offer") is not None:
            act, reason = "replace", (f"swap {live['offer']} {live.get('give_card')} #{live.get('asset')} -> "
                                      f"{c['give_card']} #{c['asset']}")
        else:
            act, reason = "post", f"new swap (gain if filled {c['gain']:+.1f})"
        rec = {"kind": "myswap", "card": ref, "give_card": c["give_card"], "give_asset": c["asset"],
               "venue": cfg.swap_venue, "to": c["to"], "value": c["value"], "value_src": c["value_src"],
               "give_value": c["give_value"], "gain": c["gain"], "need": c["need"], "set": c["set"],
               "rarity": c["rarity"], "action": act, "reason": reason, "offer": live.get("offer")}
        out.append({"kind": "myswap", "action": act, "card": ref, "give_card": c["give_card"], "asset": c["asset"],
                    "to": c["to"], "since": c["since"], "offer": live.get("offer"), "record": rec})
    for ref, live in swapbook.items():
        if ref in chosen or live.get("offer") is None:
            continue
        if counts.get(ref, 0) > 0:
            why = "card arrived"
        elif accept and accept["card"] == ref:
            why = "getting it this tick"
        elif ref in bid_cards:
            why = "we bid for it instead"
        elif live.get("asset") in busy or live.get("give_card") not in pool:
            why = f"{live.get('give_card')} #{live.get('asset')} may no longer go"
        else:
            why = "no longer among the swaps we want"
        rec = {"kind": "myswap", "card": ref, "give_card": live.get("give_card"), "give_asset": live.get("asset"),
               "venue": cfg.swap_venue, "offer": live["offer"], "action": "cancel", "reason": why}
        out.append({"kind": "myswap", "action": "cancel", "card": ref, "offer": live["offer"], "record": rec})
    return out


# ---------------------------------------------------------------- data sources

class PublicClient:
    """Keyless GETs to the public routes only, at most `rate` per second. Never sends a key or a write."""

    PATHS = re.compile(r"^/api/(clock|catalog|venues|feed|schedule|levels|venues/[A-Za-z0-9_-]{1,40}/offers)$")

    def __init__(self, url: str = URL, rate: float = 2.0, timeout: float = 15.0):
        self.url, self.gap, self.timeout = url.rstrip("/"), 1.0 / rate, timeout
        self._last = 0.0
        self._lock = threading.Lock()

    def get(self, path: str, query: dict | None = None):
        if not self.PATHS.match(path):
            raise BazaarError("not_public", f"refused {path}", 0)
        with self._lock:
            wait = self._last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        url = self.url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise BazaarError(f"http_{e.code}", path, e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BazaarError("network", f"{path}: {e}", 0) from None

    def clock(self):
        return self.get("/api/clock")

    def catalog(self):
        return self.get("/api/catalog")

    def venues(self):
        return self.get("/api/venues")

    def board(self, vid: str):
        return self.get(f"/api/venues/{vid}/offers")

    def feed(self, limit: int = 500):
        return self.get("/api/feed", {"limit": int(limit)})


class RecordedPublic:
    """plan --recorded: the public reads from tools/feed_recorder.py's snapshots.jsonl (the last El Rastro board and
    venue table it saw) and a saved catalog. Offline: no network at all, so the plan for a closed market can be read
    against the board as it was at the close."""

    def __init__(self, snapshots, catalog_path, release: str = ""):
        self.last: dict = {}
        with open(snapshots, encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("what") in ("rastro", "venues"):
                    self.last[r["what"]] = r
        if "rastro" not in self.last:
            raise SystemExit(f"{snapshots}: no El Rastro board recorded")
        self.cat = json.loads(Path(catalog_path).read_text())
        extra = {x.strip().upper() for x in release.split(",") if x.strip()}
        for st in self.cat.get("sets", []):
            if st.get("id") in extra:
                st["released"] = True

    def clock(self):
        r = self.last["rastro"]
        return {"tick": int(r["tick"]), "doors": "open", "paused": False, "recorded_at": r.get("seen_at")}

    def catalog(self):
        return self.cat

    def venues(self):
        return (self.last.get("venues") or {}).get("body") or {"venues": [{"venue": HOME, "fee_bps": 500,
                                                                            "fee_per_card": 1, "house": True}]}

    def board(self, vid: str):
        if vid != HOME:
            raise BazaarError("not_recorded", vid, 0)
        return self.last["rastro"].get("body") or {"offers": []}

    def feed(self, limit: int = 500):
        return {"events": []}


class ReadOnlyBazaar(Bazaar):
    """A keyed Bazaar that refuses every request except GET before it leaves the machine (plan / watch)."""

    def __init__(self, *a, lease=None, **kw):
        super().__init__(*a, **kw)
        self.lease = lease

    def _call(self, method, path, body=None, query=None):
        if method != "GET":
            raise BazaarError("read_only", f"refused {method} {path}", 0)
        if self.lease is not None:
            self.lease.throttle()
        return super()._call(method, path, body, query)


class LeasedBazaar(Bazaar):
    """run mode: every request waits for a token from the shared bucket."""

    def __init__(self, *a, lease=None, **kw):
        super().__init__(*a, **kw)
        self.lease = lease

    def _call(self, method, path, body=None, query=None):
        if self.lease is not None:
            self.lease.throttle()
        return super()._call(method, path, body, query)


def holdings_of(assets: list) -> dict:
    out: dict = {}
    for a in assets or []:
        if isinstance(a, dict) and a.get("kind", "card") == "card" and isinstance(a.get("ref"), str):
            out.setdefault(a["ref"], []).append(a)
    return out


def offline_account(me: dict, offers: list, tape: Tape, tick: int) -> dict:
    """Our account without a key: the last /api/me snapshot brought forward with the public settlements after it.
    Packs opened since are not public, so a card pulled after the snapshot is missing until the next snapshot."""
    me_id, t0 = me.get("id"), int(me.get("tick") or 0)
    assets = {a["id"]: dict(a) for a in me.get("assets") or [] if isinstance(a, dict) and "id" in a}
    cash = int(me.get("cash") or 0)
    applied = []
    for s in tape.settled:
        if s["tick"] <= t0 or me_id not in (s.get("parties") or []):
            continue
        parties = s.get("parties") or []
        price, fee = int(s.get("price") or 0), int(s.get("fee") or 0)
        for i in s.get("items") or []:
            if i.get("frm") == me_id:
                assets.pop(i.get("id"), None)
            elif i.get("to") == me_id and i.get("kind") == "card":
                assets[i["id"]] = {k: i.get(k) for k in ("id", "kind", "ref", "serial", "rarity", "set", "print_run")}
        gave_cards = any(i.get("frm") == me_id for i in s.get("items") or [])
        cash += price if gave_cards else -price
        if len(parties) == 2 and parties[1] == me_id:   # parties[1] accepted, and the accepting side pays the fee
            cash -= fee
        applied.append(s.get("settlement"))
    live = []
    for o in offers or []:
        if not isinstance(o, dict) or o.get("status") not in ("open", "queued"):
            continue
        if o.get("id") in tape.cancelled or (isinstance(o.get("expires_tick"), int) and o["expires_tick"] <= tick):
            continue
        gone = [a for a in (o.get("give") or {}).get("assets") or [] if (a.get("id") if isinstance(a, dict) else a)
                not in assets]
        if gone:
            continue
        live.append(o)
    return {"id": me_id, "cash": cash, "assets": list(assets.values()), "affinity": me.get("affinity") or {},
            "offers": live, "source": f"snapshot tick {t0} + {len(applied)} public settlements", "snapshot_tick": t0}


def read_feed_files(paths) -> list:
    rows = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                continue
    return rows


def page_venue_ok(venues: dict, vid: str, me: str) -> str | None:
    """None when a page-card listing on team venue `vid` may be taken: the venue is open (venue_table keeps open ones
    only), owned by another team (never ours: the rules forbid trading on our own venue) and a plain `board`
    venue. Otherwise the reason it may not."""
    v = venues.get(vid)
    if not v:
        return f"page card on {vid}: venue not open"
    if v.get("house") or vid == HOME:
        return None
    owner = v.get("owner")
    if not owner or owner == me:
        return f"page card on {vid}: our own venue" if owner == me else f"page card on {vid}: no owner"
    if v.get("mechanism") != "board":
        return f"page card on {vid}: mechanism {v.get('mechanism')!r}, board only"
    return None


def venue_table(venues_body: dict, tick: int) -> dict:
    """{vid: {fee, owner, house, status}}. A pending fee change counts from its effective tick; if it is due within
    a tick we use the higher of the two (a trade we accept now settles next tick)."""
    out = {}
    for v in (venues_body or {}).get("venues", []):
        vid = v.get("venue")
        if not vid or v.get("status", "open") != "open":
            continue
        fee = (int(v.get("fee_bps") or 0), int(v.get("fee_per_card") or 0))
        pend = v.get("pending_fee")
        if isinstance(pend, dict) and int(pend.get("effective_tick") or 0) <= tick + 1:
            p = (int(pend.get("fee_bps") or 0), int(pend.get("fee_per_card") or 0))
            fee = (max(fee[0], p[0]), max(fee[1], p[1]))
        out[vid] = {"fee": fee, "owner": v.get("owner"), "house": bool(v.get("house")) or vid == HOME,
                    "mechanism": (v.get("rules") or {}).get("mechanism") if isinstance(v.get("rules"), dict) else None}
    return out


# ---------------------------------------------------------------- the desk

def read_seller_assets(path) -> set:
    """Every asset id in rastro_seller's config, enabled or not (a disabled line is still a copy the owner set
    aside). Raises OSError or ValueError when the file is missing or malformed."""
    cfg = json.loads(Path(path).read_text())
    cards = cfg.get("cards") if isinstance(cfg, dict) else None
    if not isinstance(cards, list):
        raise ValueError("no 'cards' list")
    out = set()
    for c in cards:
        aid = c.get("asset_id") if isinstance(c, dict) else None
        if isinstance(aid, bool):
            continue
        if isinstance(aid, int):
            out.add(aid)
        elif isinstance(aid, str) and aid.strip().isdigit():
            out.add(int(aid.strip()))
    return out


def seller_assets(path) -> set:
    """Asset ids in rastro_seller's config (every line). Our swaps leave them alone by default. Empty when the file
    is missing or malformed (Desk.reload_reserved keeps the last good set instead)."""
    try:
        return read_seller_assets(path)
    except (OSError, ValueError):
        return set()


class Desk:
    def __init__(self, mode: str, cfg: Config, public: PublicClient, *, keyed=None, lease=None, log=None,
                 feed_files=None, me_path: Path = ME_SNAPSHOT, offers_path: Path = OFFERS_SNAPSHOT,
                 heartbeat: Path | None = HEARTBEAT, out=print, seller_config: Path | None = SELLER_CONFIG):
        self.mode, self.cfg, self.public, self.keyed, self.lease = mode, cfg, public, keyed, lease
        self.log, self.out, self.heartbeat = log, out, heartbeat
        self.me_path, self.offers_path = Path(me_path), Path(offers_path)
        self.tape = Tape().ingest(read_feed_files(feed_files or []))
        self.catalog = None
        self.valuer = None
        self.ledger = Ledger()
        self.bidbook: dict = {}           # watch: simulated bids; run: synced from /api/me/offers
        self.swapbook: dict = {}          # our swaps, same sources: {card asked: {offer, asset, give_card, to, since}}
        self.seller_config = Path(seller_config) if seller_config else None
        self.reserved: set = set()        # asset ids in rastro_seller's config, re-read every tick
        self._reserved_err = None
        self.reload_reserved()
        self.shadow_counts: dict = {}     # watch: cards a would-be buy brought in
        self.shadow_gone: set = set()     # watch: our assets a would-be sale or swap handed over
        self.swap_dupes: list = []        # run: a second live swap of ours asking the same card (cancelled)
        self.bid_dupes: list = []         # run: a second live bid of ours on the same card (cancelled)
        self.cancelled_ids: set = set()   # run: offers of ours we cancelled (never cancelled twice, never re-read)
        self._duels_tick, self._duels_why = None, None   # GET /api/duels, read once per tick
        self.said: dict = {}              # last logged decision per offer/card (log on change only)
        self.ticks = 0
        self.yield_dir = YIELD_DIR
        self.page_seen: set = set()   # team board venues whose last read showed a listing of a page card we lack
        self._swept = None            # the tick of the last full sweep of the team boards (page mode)
        self.last = None
        self.last_snap = None
        self.start_tick = None            # trades from the tape count toward the caps from here on
        self.assume_cash = None           # plan --keyless --assume-cash: the cash to plan with

    def maker_trades(self, me_id: str, tick: int, t_hours: float) -> None:
        """Trades where another team accepted OUR offer (a filled bid, or a listing rastro_seller posted) spend cash
        and count per partner too; our own accepts are already in the ledger. They come from the public tape."""
        seen = {r.get("settlement") for r in self.ledger.rows if r.get("settlement") is not None}
        for s in self.tape.settled:
            sid, parties = s.get("settlement"), s.get("parties") or []
            if sid in seen or not s.get("venue") or len(parties) < 2 or parties[0] != me_id:
                continue
            if self.start_tick is None or s["tick"] < self.start_tick:
                continue
            items = s.get("items") or []
            got = [i for i in items if i.get("to") == me_id and i.get("kind") == "card"]
            row = {"side": "buy" if got else "sell", "t_hours": round(t_hours - (tick - s["tick"]) / TICKS_PER_GAME_HOUR, 3),
                   "tick": s["tick"], "cost": int(s.get("price") or 0) if got else 0, "partner": parties[1],
                   "card": (got or items or [{}])[0].get("ref"), "settlement": sid}
            self.ledger.add(**row)
            seen.add(sid)
            if self.log is not None and self.mode == "run":
                self.log.event("maker_trade", **row)

    # ------------------------------------------------ inputs
    def account(self, tick: int) -> dict:
        if self.keyed is not None:
            me = self.keyed.me()
            offers = self.keyed.my_offers().get("offers", [])
            return {"id": me["id"], "cash": int(me.get("cash") or 0), "assets": me.get("assets") or [],
                    "affinity": me.get("affinity") or {}, "offers": offers, "source": "api"}
        me = json.loads(self.me_path.read_text())
        offers = json.loads(self.offers_path.read_text()).get("offers", []) if self.offers_path.exists() else []
        return offline_account(me, offers, self.tape, tick)

    def reload_reserved(self) -> set:
        """Re-read rastro_seller's config so the reserved set follows edits made during the day. A missing or
        malformed file keeps the last good set (logged once per distinct error)."""
        if self.seller_config is None:
            return self.reserved
        try:
            self.reserved = read_seller_assets(self.seller_config)
            self._reserved_err = None
        except (OSError, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            if err != self._reserved_err:
                self._reserved_err = err
                self.out(f"seller config {self.seller_config} unreadable ({err}); keeping the last good set of "
                         f"{len(self.reserved)} reserved assets")
                if self.log is not None:
                    self.log.event("seller_config_unreadable", path=str(self.seller_config), error=err,
                                   kept=sorted(self.reserved))
        return self.reserved

    def snapshot(self, clock: dict) -> dict:
        tick = int(clock["tick"])
        self.reload_reserved()
        if self.catalog is None or self.ticks % 120 == 0:
            self.catalog = self.public.catalog()
        feed_down = None
        try:
            self.tape.ingest(self.public.feed(500).get("events", []))
        except BazaarError as e:
            # maker fills (another team taking our bid) are only seen in the feed: no cash write this tick
            feed_down = f"feed_down: /api/feed unread ({e.code}); spending by our filled bids unknown"
            self._say_once(("feed", tick), f"tick {tick} feed unread ({e.code}); no cash write this tick")
        acct = self.account(tick)
        if self.assume_cash is not None and self.keyed is None:
            acct = {**acct, "cash": int(self.assume_cash), "source": f"{acct.get('source')}, cash assumed"}
        if self.start_tick is None:
            self.start_tick = tick
        self.maker_trades(acct["id"], tick, float(clock.get("t_hours") or tick / TICKS_PER_GAME_HOUR))
        vt = venue_table(self.public.venues(), tick)
        boards = {}
        page_boards = set(self.page_boards(vt, acct["id"], tick))
        for vid in vt:
            if vid != HOME and not self.cfg.team_venues and vid not in page_boards:
                continue
            try:
                boards[vid] = self.public.board(vid).get("offers", [])
            except BazaarError as e:
                self._say_once(("board", vid, tick), f"tick {tick} board {vid} unread ({e.code})")
        if page_boards:   # keep reading a team board while it still shows a listing of a page card
            self.page_seen = {vid for vid in page_boards if any(
                (chk := check_listing(o, acct["id"], tick))["ok"] and chk["ref"] in self.cfg.page_targets
                for o in boards.get(vid) or [])}
        holdings = holdings_of([a for a in acct["assets"] if not (isinstance(a, dict) and a.get("id") in self.shadow_gone)])
        for ref, n in self.shadow_counts.items():   # watch: what our would-be buys brought in
            holdings.setdefault(ref, []).extend({"id": -i - 1, "ref": ref, "serial": 10 ** 6} for i in range(n))
        copy_values = {}
        if acct.get("source") == "api":
            for ref, lst in holdings.items():
                vs = [a.get("your_value") for a in lst if isinstance(a.get("your_value"), (int, float))]
                if vs:
                    copy_values[ref] = min(vs)
        if self.valuer is None:
            online = (lambda ref: self.keyed.value(ref).get("your_value")) if self.keyed is not None else None
            self.valuer = Valuer(self.catalog, acct["affinity"], {}, page_bonus=self.cfg.page_bonus, online=online)
        self.valuer.set_counts({r: len(v) for r, v in holdings.items()}, copy_values if copy_values else None)
        released = {s["id"] for s in self.catalog.get("sets", []) if s.get("released")}
        shadow_cash = sum((r.get("cash") or 0) - (r.get("cost") or 0) for r in self.ledger.rows if r.get("shadow"))
        snap = {"tick": tick, "t_hours": float(clock.get("t_hours") or tick / TICKS_PER_GAME_HOUR),
                "me_id": acct["id"], "cash": acct["cash"] + shadow_cash,
                "holdings": holdings, "venues": vt, "boards": boards, "mine": acct["offers"], "released": released,
                "account_source": acct.get("source"), "duel_lock": self.duel_lock_fresh(), "reserved": set(self.reserved),
                "duel_live": self.duel_guard(tick), "duel_any": self.duel_guard(tick, any_live=True),
                "duels_unread": self.duel_guard(tick, unread=True), "page_yield": self.page_yields(),
                "feed_down": feed_down}
        # the reads above take time: if the tick moved while they ran, the account and the offers may disagree
        # (a bid of ours that settled between /api/me and /api/me/offers), so the snapshot is not used for writes
        try:
            after = int(self.public.clock()["tick"])
        except (BazaarError, KeyError, TypeError, ValueError) as e:
            after = f"unread ({getattr(e, 'code', type(e).__name__)})"
        if after != tick:
            snap["spans_ticks"] = f"snapshot_spans_ticks: reads began at tick {tick}, clock now {after}"
        return snap

    def duel_guard(self, tick: int, fresh: bool = False, any_live: bool = False, unread: bool = False) -> str | None:
        """Server-side duel guard (keyed modes): results/duel.lock is a file on the machine that runs duel.py, which
        need not be the desk's, so the desk also reads GET /api/duels, once per tick (cached: take()'s re-read
        reuses it). While any of our duels is live (--duel-guard-ticks N: only while one is within N ticks of its
        deadline) every accept is deferred with reason duel_live; bids and cancels go on. A failed read defers too.
        Keyless modes cannot read it (the route needs the key) and keep the local lock only.
        any_live=True: every live duel of ours counts, whatever --duel-guard-ticks says (page writes use it)."""
        if self.keyed is None:
            return None
        if self._duels_tick != tick or fresh or self._duels_why is None:
            self._duels_why = self._read_duels(tick)
            self._duels_tick = tick
        return self._duels_why[2 if unread else 1 if any_live else 0]

    def _read_duels(self, tick: int) -> tuple:
        """(why for ordinary accepts, within --duel-guard-ticks; why for every live duel; why for page bid writes:
        only an unread /api/duels) from one read."""
        why, why_any, why_unread = None, None, None
        try:
            body = self.keyed.duels()
            duels = body.get("duels") if isinstance(body, dict) else None
            if not isinstance(duels, list):
                raise BazaarError("bad_response", "no duels list", 0)
            n = self.cfg.duel_guard_ticks
            live, every = [], []
            for d in duels:
                if not isinstance(d, dict) or d.get("status") != "live":
                    continue
                dl = d.get("deadline_tick")
                left = dl - tick if isinstance(dl, int) and not isinstance(dl, bool) else None
                row = (left if left is not None else -1, d.get("duel"), dl)
                every.append(row)
                if n is None or left is None or left <= n:   # no deadline: count it, to be safe
                    live.append(row)

            def say(rows):
                left, did, dl = min(rows)
                more = f" (+{len(rows) - 1} more)" if len(rows) > 1 else ""
                return (f"duel_live: duel {did} is live, deadline tick {dl} ({left} ticks left){more}: the duel bot "
                        f"holds the team's accept slot")
            why = say(live) if live else None
            why_any = say(every) if every else None
        except Exception as e:   # unread (network, 429, a client without the route): defer, never guess
            why = f"duel_live: /api/duels unread ({getattr(e, 'code', type(e).__name__)}); accepts deferred to be safe"
            why_any = why_unread = why
        return why, why_any, why_unread

    def page_yields(self) -> set:
        """The --page cards a fallback step has taken over: logs/state/page-yield-<REF> exists."""
        return {r for r in self.cfg.page_targets if (Path(self.yield_dir) / f"page-yield-{r}").exists()}

    def ack_yields(self, snap: dict) -> None:
        """run: for each yielded page card, once /api/me/offers (this tick's read) shows no open or queued offer of
        ours asking for it, write logs/state/page-yield-<REF>.ack (atomically) for the fallback step."""
        if self.mode != "run":
            return
        for ref in sorted(snap.get("page_yield") or ()):
            busy = [o.get("id") for o in snap.get("mine") or [] if isinstance(o, dict)
                    and o.get("maker") == snap["me_id"] and o.get("status") in ("open", "queued")
                    and o.get("id") not in self.cancelled_ids
                    and (f"card:{ref}" in ((o.get("want") or {}).get("types") or [])
                         or ref in ((o.get("want") or {}).get("cards") or []))]
            if busy or (self.bidbook.get(ref) or {}).get("offer") is not None:
                continue
            path = Path(self.yield_dir) / f"page-yield-{ref}.ack"
            body = {"ref": ref, "tick": snap["tick"], "open_bid": False,
                    "held": len((snap.get("holdings") or {}).get(ref) or [])}
            try:
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(json.dumps(body) + "\n")
                os.replace(tmp, path)
            except OSError as e:
                self._say_once(("ack", ref, snap["tick"]), f"page-yield ack for {ref} not written ({e})")
                continue
            if self.log is not None:
                self.log.event("page_yield_ack", tick=snap["tick"], card=ref, held=body["held"])

    def page_boards(self, vt: dict, me: str, tick: int | None = None) -> list:
        """Page mode under --no-team-venues: the team boards to read for a page card we lack. Only plain `board`
        venues of other teams; those the feed shows a live listing of the card on, and all of them on the first
        tick and every PAGE_SWEEP_TICKS (a listing older than the feed window)."""
        if self.cfg.team_venues or not self.cfg.page_targets:
            return []
        lacking = set(self.cfg.page_targets) - self.page_yields()
        if self.valuer is not None:
            lacking = {r for r in lacking if self.valuer.counts.get(r, 0) == 0}
        if not lacking:
            return []
        ok = [vid for vid in vt if vid != HOME and page_venue_ok(vt, vid, me) is None]
        if self.ticks % PAGE_SWEEP_TICKS == 0 and (tick is None or self._swept != tick):
            self._swept = tick   # once per tick: take()'s fresh snapshot reads only the venues found
            return ok
        hinted = {ven for oid, (ven, ref) in self.tape.listed_on.items() if ref in lacking and oid not in self.tape.cancelled}
        return [vid for vid in ok if vid in hinted | self.page_seen]

    def duel_lock_fresh(self) -> bool:
        """agent/duel.py's stopgap: while results/duel.lock is fresh the desk never accepts (bids and cancels go
        on: a seller filling our bid uses THEIR accept, not ours)."""
        if self.lease is not None:
            return self.lease.duel_lock_fresh()
        try:
            return float(DUEL_LOCK.read_text().split()[0]) > time.time()
        except (OSError, ValueError, IndexError):
            return False

    def sync_bids(self, snap: dict) -> None:
        """Our live bids. run: what /api/me/offers says (give cash, want one card, on our bid venue). watch: the
        simulated ones, which expire like real ones. A bid that expired or filled stays in the book with offer None,
        so its step clock (since, anchor) carries over when we post it again."""
        if self.mode == "watch":
            for b in self.bidbook.values():
                if b.get("offer") is not None and snap["tick"] >= b.get("expires", 10 ** 9):
                    b["offer"] = None
            return
        self.bid_dupes = []
        if self.mode != "run":
            return
        live = {}
        # never a conversation offer: a dealer bot's offer in a thread (venue None) looks like a bid and was cancelled
        for o in sorted(snap["mine"], key=lambda o: o.get("id") or 0):
            if o.get("maker") != snap["me_id"] or o.get("status") != "open" or o.get("thread") is not None \
                    or (o.get("venue") or HOME) != self.cfg.bid_venue or o.get("id") in self.cancelled_ids:
                continue
            types = (o.get("want") or {}).get("types") or []
            give = o.get("give") or {}
            cash = give.get("cash")
            if len(types) == 1 and isinstance(types[0], str) and types[0].startswith("card:") and _int_cash(cash) \
                    and not give.get("assets") and not give.get("types"):
                ref = types[0][5:]
                if ref in live:   # a second live bid of ours on the same card: cancelled in execute()
                    self.bid_dupes.append({"card": ref, "offer": o["id"]})
                    continue
                old = self.bidbook.get(ref) or {}
                live[ref] = {"offer": o["id"], "price": cash, "to": o.get("to"), "since": old.get("since", snap["tick"]),
                             "anchor": old.get("anchor", cash)}
        for ref, old in self.bidbook.items():
            if ref not in live:
                live[ref] = {**old, "offer": None}
        self.bidbook = live

    def sync_swaps(self, snap: dict) -> None:
        """Our live swaps. run: what /api/me/offers says (one card given, one card asked, no cash, on our swap venue);
        a second swap asking the same card is cancelled (self.swap_dupes). watch: the simulated ones, which expire."""
        self.swap_dupes = []
        if self.mode == "watch":
            for x in [x for x, s in self.swapbook.items() if snap["tick"] >= s.get("expires", 10 ** 9)]:
                self.swapbook.pop(x)
            return
        if self.mode != "run":
            return
        live = {}
        for o in sorted(snap["mine"], key=lambda o: o.get("id") or 0):
            if o.get("maker") != snap["me_id"] or o.get("status") != "open" or o.get("thread") is not None \
                    or (o.get("venue") or HOME) != self.cfg.swap_venue or o.get("id") in self.cancelled_ids:
                continue
            g, w = o.get("give") or {}, o.get("want") or {}
            assets, types = g.get("assets") or [], w.get("types") or []
            if g.get("cash") or w.get("cash") or g.get("types") or w.get("assets") or len(assets) != 1 \
                    or len(types) != 1 or not isinstance(types[0], str) or not types[0].startswith("card:"):
                continue
            a = assets[0]
            ref = types[0][5:]
            if ref in live:
                self.swap_dupes.append({"card": ref, "offer": o["id"]})
                continue
            old = self.swapbook.get(ref) or {}
            live[ref] = {"offer": o["id"], "asset": a.get("id") if isinstance(a, dict) else a,
                         "give_card": a.get("ref") if isinstance(a, dict) else None, "to": o.get("to"),
                         "since": old.get("since", snap["tick"])}
        self.swapbook = live

    # ------------------------------------------------ one tick
    def tick(self, clock: dict) -> dict:
        snap = self.snapshot(clock)
        self.last_snap = snap
        if snap.get("spans_ticks"):
            self._say_once(("spans", snap["tick"]), f"tick {snap['tick']} {snap['spans_ticks']}: no write this tick")
        self.sync_bids(snap)
        self.sync_swaps(snap)
        self.ack_yields(snap)
        res = decide(snap, self.valuer, self.tape, self.ledger, self.cfg, self.bidbook, self.swapbook)
        self.report(snap, res)
        if self.mode == "watch":
            self.shadow(snap, res)
        elif self.mode == "run":
            self.execute(clock, snap, res)
        self.beat(snap, res)
        self.ticks += 1
        return res

    def report(self, snap: dict, res: dict) -> None:
        if self.valuer and self.valuer.mismatches:
            for m in self.valuer.mismatches:
                self.emit({"tick": snap["tick"], "kind": "value", "card": m["card"], "action": "note",
                           "reason": f"server value {m['server']} != offline {m['offline']} (page bonus or rule change?)"})
            self.valuer.mismatches.clear()
        for d in res["records"]:
            key = (d["kind"], d.get("offer") if d["kind"] in ("buy", "sell", "swap") else d.get("card"))
            sig = (d["action"], d.get("price"), d.get("reason"))
            if self.mode != "plan" and self.said.get(key) == sig:
                continue
            self.said[key] = sig
            self.emit(d)

    def emit(self, d: dict) -> None:
        d = {**d, "mode": self.mode}
        self.out(line(d) if d.get("kind") in ("buy", "sell", "bid", "swap", "myswap") and d.get("action") != "note" else
                 f"tick {d.get('tick')} {str(d.get('kind')).upper():<4} {d.get('card') or '-':<6} -> "
                 f"{str(d.get('action')).upper()}: {d.get('reason')}")
        if self.log is not None:
            self.log.event("decision", **d)

    def _say_once(self, key, text: str) -> None:
        if key not in self.said:
            self.said[key] = True
            self.out(text)

    def shadow(self, snap: dict, res: dict) -> None:
        """watch: pretend the decisions went through, so the next tick's caps and holdings follow them."""
        a = res["accept"]
        if a:
            if a["side"] == "buy":
                self.shadow_counts[a["card"]] = self.shadow_counts.get(a["card"], 0) + 1
                self.ledger.add(side="buy", t_hours=snap["t_hours"], tick=snap["tick"], cost=a["price"] + a["fee"],
                                partner=a.get("partner"), card=a["card"], shadow=True)
            elif a["side"] == "swap":
                self.shadow_counts[a["card"]] = self.shadow_counts.get(a["card"], 0) + 1
                self.shadow_gone.add(a.get("asset"))
                self.ledger.add(side="swap", t_hours=snap["t_hours"], tick=snap["tick"], cost=a["fee"],
                                partner=a.get("partner"), card=a["card"], give_card=a.get("give_card"), shadow=True)
            else:
                self.shadow_gone.add(a.get("asset"))
                self.ledger.add(side="sell", t_hours=snap["t_hours"], tick=snap["tick"], cash=a["price"] - a["fee"],
                                partner=a.get("partner"), card=a["card"], shadow=True)
        for b in res["bids"]:
            if b["action"] in ("post", "replace"):
                self.bidbook[b["card"]] = {"offer": f"shadow-{b['card']}", "price": b["price"], "to": b["to"],
                                           "since": b["since"], "anchor": b["anchor"],
                                           "expires": snap["tick"] + self.cfg.bid_expires}
            elif b["action"] == "cancel":
                self.bidbook.pop(b["card"], None)
        for s in res.get("swaps") or []:
            if s["action"] in ("post", "replace"):
                self.swapbook[s["card"]] = {"offer": f"shadow-swap-{s['card']}", "asset": s["asset"],
                                            "give_card": s["give_card"], "to": s["to"], "since": s["since"],
                                            "expires": snap["tick"] + self.cfg.swap_expires}
            elif s["action"] == "cancel":
                self.swapbook.pop(s["card"], None)

    # ------------------------------------------------ run (never started without the team's yes)
    def execute(self, clock: dict, snap: dict, res: dict) -> None:
        if self.lease is None or self.keyed is None:
            raise SystemExit("run needs the key and the lease")
        if self.lease.stopped():
            self.out(f"tick {snap['tick']} STOP file present: nothing sent")
            return
        # cancels first (a stale bid or swap must not fill while we buy), then the accept, then new bids and swaps
        swaps = res.get("swaps") or []
        bids = self.hold_page_writes(snap, res["bids"], "before the cancels")
        cancels = [("cancel", b) for b in bids if b["action"] in ("cancel", "replace")]
        cancels += [("cancel", {**d, "dupe": True}) for d in self.bid_dupes]
        cancels += [("cancel", {**d, "kind": "myswap", "dupe": True}) for d in self.swap_dupes]
        cancels += [("cancel", s) for s in swaps if s["action"] in ("cancel", "replace")]
        stop = snap.get("spans_ticks") or snap.get("feed_down")
        if stop:   # cancels only: no cash write on a torn snapshot or without the feed's maker fills
            self.log.event(stop.split(":")[0], tick=snap["tick"], why=stop)
            self.send(clock, snap, cancels)
            return
        failed = self.send(clock, snap, cancels)
        if res["accept"]:
            self.take(clock, snap, res["accept"])
            # the bids below were planned before take()'s fresh reads (which may show new spending): none is posted
            # this tick; the next tick plans them again from scratch
            self.log.event("posts_deferred", tick=snap["tick"], why="an accept was attempted this tick",
                           cards=[b["card"] for b in bids if b["action"] in ("post", "replace")])
            return
        if failed:   # an offer of ours we meant to cancel is still live: its cash stays out, so nothing new goes up
            self.log.event("posts_deferred", tick=snap["tick"], why=f"cancel failed for {sorted(failed)}",
                           cards=[b["card"] for b in bids if b["action"] in ("post", "replace")])
            return
        # a page post is checked again against the duel guards right before it is sent (send)
        posts = [("post", b) for b in bids if b["action"] in ("post", "replace")]
        posts += [("post", s) for s in swaps if s["action"] in ("post", "replace")]
        why = self.write_check(snap, [b["card"] for _, b in posts if b.get("kind") != "myswap"]) if posts else None
        if why:
            self.log.event("posts_deferred", tick=snap["tick"], why=why, cards=[b["card"] for _, b in posts])
            return
        # the 30 open offers are shared with rastro_seller: leave 2 free, as it does
        cap = int((clock.get("limits") or {}).get("max_open_offers_per_team", 30)) - 2
        open_now = sum(1 for o in snap["mine"] if o.get("maker") == snap["me_id"] and o.get("status") in ("open", "queued"))
        room = max(0, cap - open_now + len(cancels) - len(failed))
        if len(posts) > room:
            self.log.event("offer_cap", tick=snap["tick"], open=open_now, room=room, skipped=[p[1]["card"] for p in posts[room:]])
        self.send(clock, snap, posts[:room])

    def hold_page_writes(self, snap: dict, bids: list, when: str) -> list:
        """Drop the page posts and replacements (and a replacement's cancel) while page_hold() says a duel holds the
        team; the live page bid stays as it is. Other bids and every cancel go on."""
        if not any(b.get("page") and b["action"] in ("post", "replace") for b in bids):
            return bids
        out = []
        for b in bids:
            why = self.page_hold(snap["tick"], b["card"]) if b.get("page") and b["action"] in ("post", "replace") \
                else None
            if why:
                self.log.event("page_hold", tick=snap["tick"], card=b["card"], action=b["action"], price=b["price"],
                               offer=b.get("offer"), why=why, when=when)
                continue
            out.append(b)
        return out

    def send(self, clock: dict, snap: dict, ops: list) -> set:
        """Listing operations through the lease's per-tick quota. Returns the cards whose cancel failed."""
        failed = set()
        if not ops:
            return failed
        n = self.lease.claim_listings(clock, len(ops))
        for op, b in ops[n:]:
            if op == "cancel":
                failed.add(b["card"])
        for op, b in ops[:n]:
            swap = b.get("kind") == "myswap"
            book = self.swapbook if swap else self.bidbook
            try:
                if op == "cancel":
                    self.keyed.cancel(b["offer"])
                    self.cancelled_ids.add(b["offer"])
                    if not swap and b.get("action") == "replace":
                        # until the replacement is up, the card keeps its step clock (since, anchor) with no offer
                        book[b["card"]] = {**(book.get(b["card"]) or {}), "offer": None}
                    elif not b.get("dupe"):
                        book.pop(b["card"], None)
                elif b.get("page") and (held := self.page_hold(snap["tick"], b["card"])):
                    # read again right before the write: planning, the accept wait and the throttle came between
                    self.log.event("page_hold", tick=snap["tick"], card=b["card"], action=b["action"],
                                   price=b["price"], offer=b.get("offer"), why=held, when="at the post")
                    continue
                elif swap:
                    # one card for one card, no cash either way: give our spare, want any copy of the card
                    r = self.keyed.list_offer({"assets": [int(b["asset"])]}, {"cards": [b["card"]]},
                                              venue=self.cfg.swap_venue, to=b.get("to"),
                                              expires_in_ticks=self.cfg.swap_expires)
                    o = r.get("offer", r) if isinstance(r, dict) else {}
                    book[b["card"]] = {"offer": o.get("id"), "asset": b["asset"], "give_card": b["give_card"],
                                       "to": b.get("to"), "since": b["since"]}
                else:
                    r = self.keyed.list_offer({"cash": int(b["price"])}, {"cards": [b["card"]]}, venue=self.cfg.bid_venue,
                                              to=b.get("to"), expires_in_ticks=self.cfg.bid_expires)
                    o = r.get("offer", r) if isinstance(r, dict) else {}
                    book[b["card"]] = {"offer": o.get("id"), "price": b["price"], "to": b.get("to"),
                                       "since": b["since"], "anchor": b["anchor"]}
                self.log.event("sent", tick=snap["tick"], op=op, kind="swap" if swap else "bid", card=b["card"],
                               price=b.get("price"), give_card=b.get("give_card"), asset=b.get("asset"),
                               offer=b.get("offer"))
            except BazaarError as e:
                self.log.event("refused", tick=snap["tick"], op=op, kind="swap" if swap else "bid", card=b["card"],
                               code=e.code, msg=e.message[:200])
                if op == "cancel":
                    failed.add(b["card"])   # never post the replacement if the old offer could not be cancelled
        return failed

    def take(self, clock: dict, snap: dict, a: dict) -> None:
        """Re-read, wait for the second half of the tick, claim the accept, accept. One attempt, never repeated."""
        ts = float(clock.get("tick_seconds") or 30)
        elapsed = ts - float(clock.get("next_tick_in") or 0)
        if elapsed < ts / 2:
            time.sleep(ts / 2 - elapsed + 0.3)
        c2 = self.keyed.clock()
        if int(c2["tick"]) != snap["tick"]:
            self.log.event("skip_accept", tick=snap["tick"], why="tick moved while waiting", offer=a["offer"])
            return
        fresh = self.snapshot(c2)   # stale inventory is the main risk: decide again on fresh reads
        self.sync_swaps(fresh)
        res = decide(fresh, self.valuer, self.tape, self.ledger, self.cfg, self.bidbook, self.swapbook)
        b = res["accept"]
        if not b or b["offer"] != a["offer"]:
            self.log.event("skip_accept", tick=snap["tick"], why="fresh reads changed the decision", offer=a["offer"])
            return
        if not self.lease.claim_accept(c2, self.lease.MARKET, ref=f"offer {b['offer']} {b['card']}"):
            self.log.event("skip_accept", tick=snap["tick"], why="lease refused", offer=b["offer"])
            return
        if b["side"] in ("buy", "swap"):
            # a card we get must not also arrive through an offer of ours: cancel EVERY live bid or swap of ours that
            # asks for it, as /api/me/offers says now (a duplicate whose cancel failed earlier in the tick is one),
            # and accept nothing this tick unless every one of those cancels went through (a queued one never gets
            # here: decide() on the fresh read already skips a card with a settling offer of ours)
            ids = self.offers_asking(fresh, b["card"])
            for book in (self.bidbook, self.swapbook):
                oid = (book.get(b["card"]) or {}).get("offer")
                if isinstance(oid, int) and oid not in self.cancelled_ids and oid not in ids:
                    ids.append(oid)
            why = None
            if ids and self.lease.claim_listings(c2, len(ids)) < len(ids):
                why = f"no quota to cancel our offers {ids} asking {b['card']} first"
            for oid in ids if why is None else []:
                try:
                    self.keyed.cancel(oid)
                except BazaarError as e:
                    why = f"cancel of our offer {oid} asking {b['card']} failed ({e.code})"
                    break
                self.cancelled_ids.add(oid)
            if why:
                self.lease.release_accept(c2, why)
                self.log.event("skip_accept", tick=snap["tick"], why=why, offer=b["offer"])
                return
            for book in (self.bidbook, self.swapbook):
                if (book.get(b["card"]) or {}).get("offer") in self.cancelled_ids:
                    book.pop(b["card"], None)
        why = self.write_check(fresh, [b["card"]] if b["side"] in ("buy", "swap") else [])
        if why:
            self.lease.release_accept(c2, why)
            self.log.event("skip_accept", tick=snap["tick"], why=why, offer=b["offer"])
            return
        try:
            if b.get("cancel_listing"):
                if not self.lease.claim_listings(c2, 1):
                    self.lease.release_accept(c2, "could not cancel our listing first")
                    return
                self.keyed.cancel(b["cancel_listing"])
                self.cancelled_ids.add(b["cancel_listing"])
            assets = [b["asset"]] if b["side"] in ("sell", "swap") and b.get("asset") else None
            self.keyed.accept(b["offer"], assets=assets)
        except BazaarError as e:
            self.log.event("refused", tick=snap["tick"], op="accept", offer=b["offer"], code=e.code, msg=e.message[:200])
            if e.status not in (0, 429) and e.code not in ("wait_for_tick", "rate_limited"):
                self.lease.release_accept(c2, e.code)
            return
        cost = {"buy": b["price"] + b["fee"], "swap": b["fee"]}.get(b["side"], 0)
        self.ledger.add(side=b["side"], t_hours=fresh["t_hours"], tick=fresh["tick"], cost=cost,
                        partner=b.get("partner"), card=b["card"])
        self.log.event("accepted", tick=fresh["tick"], side=b["side"], offer=b["offer"], card=b["card"],
                       price=b["price"], fee=b["fee"], value=b["value"], gain=b["gain"], partner=b.get("partner"),
                       t_hours=fresh["t_hours"], cost=cost, give_card=b.get("give_card"), asset=b.get("asset"))
        if self.valuer:
            self.valuer.cache.clear()

    def offers_asking(self, snap: dict, ref: str) -> tuple:
        """Open offers of ours that ask for `ref` (a bid or a swap: want types "card:REF"), from the account read in
        `snap`; offers we already cancelled are left out."""
        ids = []
        for o in sorted(snap.get("mine") or [], key=lambda o: o.get("id") or 0):
            if not isinstance(o, dict) or o.get("maker") != snap["me_id"] or o.get("id") in self.cancelled_ids:
                continue
            want = o.get("want") or {}
            asks = [t for t in want.get("types") or [] if t == f"card:{ref}"] + \
                   [c for c in want.get("cards") or [] if c == ref]
            if not asks:
                continue
            if o.get("status") == "open":
                ids.append(o["id"])
        return ids

    def write_check(self, snap: dict, refs: list) -> str | None:
        """Right before a cash write (an accept, a bid post): read the clock, /api/me and /api/me/offers again. The
        tick must be the snapshot's, our cash the same (a bid of ours filled meanwhile spends it), each card in
        `refs` held as many times as in the snapshot, and no offer of ours asking for one of them settling.
        Keyless modes send nothing and are not checked."""
        if self.keyed is None or self.mode != "run":
            return None
        try:
            tick = int(self.keyed.clock()["tick"])
            me = self.keyed.me()
            offers = self.keyed.my_offers().get("offers", [])
        except (BazaarError, KeyError, TypeError, ValueError) as e:
            return f"write_check: reads failed ({getattr(e, 'code', type(e).__name__)})"
        if tick != snap["tick"]:
            return f"write_check: tick moved {snap['tick']} -> {tick}"
        if int(me.get("cash") or 0) != int(snap.get("cash") or 0):
            return f"write_check: cash {snap.get('cash')} -> {me.get('cash')}"
        now = holdings_of(me.get("assets") or [])
        for ref in refs:
            if len(now.get(ref) or []) != len((snap.get("holdings") or {}).get(ref) or []):
                return f"write_check: our {ref} count changed"
            for o in offers:
                want = (o or {}).get("want") or {}
                if o.get("maker") == snap["me_id"] and o.get("status") == "queued" and \
                        (f"card:{ref}" in (want.get("types") or []) or ref in (want.get("cards") or [])):
                    return f"write_check: our offer {o.get('id')} asking {ref} is settling"
        return None

    def page_hold(self, tick: int, ref: str | None = None) -> str | None:
        """Why a page bid may not be posted or raised right now: a page-yield file for the card, or GET /api/duels
        (read again, not the tick's cached answer) cannot be read. A live duel does not hold it, nor does
        results/duel.lock: a fill of our bid is the seller's accept, the lock and the lease guard only OUR accept
        (agent/lease.py _accept_check), and a duel moves no cash."""
        if ref is not None and ref in self.page_yields():
            return f"page-yield file for {ref}: the fallback step buys it"
        return self.duel_guard(tick, fresh=True, unread=True)

    # ------------------------------------------------ heartbeat
    def beat(self, snap: dict, res: dict) -> None:
        self.last = res["accept"] or next((r for r in res["records"] if r["action"] in ("post", "replace")), None)
        if self.heartbeat is None or self.mode == "plan":
            return
        top = self.last or {}
        write_json(self.heartbeat, {
            "desk": "market", "mode": self.mode, "tick": snap["tick"], "t_hours": snap["t_hours"],
            "time": datetime.now(MADRID).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "last_decision": {k: top.get(k) for k in ("kind", "action", "card", "offer", "price", "fee", "value",
                                                       "gain", "venue", "partner", "give_card")} if top else None,
            "reason": top.get("reason") if top else "nothing passes the rules this tick",
            "counts": {"records": len(res["records"]), "candidates": sum(1 for r in res["records"]
                                                                         if r["action"] in ("take", "defer")),
                       "bids": sum(1 for b in res["bids"] if b["action"] in ("post", "keep", "replace")),
                       "swaps": sum(1 for s in res.get("swaps") or [] if s["action"] in ("post", "keep", "replace")),
                       "swap_fills": sum(1 for r in res["records"] if r["kind"] == "swap"
                                         and r["action"] in ("take", "defer"))},
            "account": snap.get("account_source"), "stop": bool(self.lease and self.lease.stopped()),
            "duel_guard": snap.get("duel_live"), "duel_lock": bool(snap.get("duel_lock")),
        })


def today_ledger(path: Path) -> Ledger:
    """Trades an earlier `run` process accepted today (so a restart keeps the caps)."""
    rows = []
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("event") in ("accepted", "maker_trade"):
                rows.append({k: r.get(k) for k in ("side", "t_hours", "tick", "cost", "partner", "card", "settlement")})
    return Ledger(rows)


class QuietRunLog(RunLog):
    """The JSON record only; the desk prints its own human line."""

    def event(self, event: str, **data) -> None:
        row = redact({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": self.run_id, "agent": self.agent,
                      "event": event, **data})
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------- main

def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for ln in env.read_text().splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def parse_pages(specs) -> dict:
    """--page REF:CAP[:FLOOR] (repeatable, or comma-separated) -> {ref: {"cap", "floor"}}. CAP is the most we pay
    for the card, fee included; FLOOR is the first bid (default: from the team trades)."""
    out = {}
    for spec in specs or []:
        for part in str(spec).split(","):
            part = part.strip()
            if not part:
                continue
            bits = part.split(":")
            if len(bits) not in (2, 3) or not REF_RE.match(bits[0].upper()) or not all(b.isdigit() for b in bits[1:]):
                raise ValueError(f"--page {part!r}: expected REF:CAP or REF:CAP:FLOOR, e.g. SAL-10:110")
            ref, cap = bits[0].upper(), int(bits[1])
            floor = int(bits[2]) if len(bits) == 3 else None
            if cap < 1 or (floor is not None and not 1 <= floor <= cap):
                raise ValueError(f"--page {part!r}: need 1 <= FLOOR <= CAP")
            out[ref] = {"cap": cap, "floor": floor}
    return out


def build_config(args) -> Config:
    sets = lambda s: tuple(x.strip().upper() for x in (s or "").split(",") if x.strip())  # noqa: E731
    return Config(margin_min=args.margin_min, margin_frac=args.margin_frac, sell_margin_min=args.sell_margin_min,
                  sell_margin_frac=args.sell_margin_frac, cap_hour=args.cap_hour, cap_day=args.cap_day,
                  max_price=args.max_price, max_price_rare=args.max_price_rare, rare_cap_sets=sets(args.rare_cap_sets),
                  min_cash=args.min_cash, partner_hour=args.partner_hour, protect=sets(args.protect),
                  sell_first_copies=sets(args.sell_first_copies), sell_listed=args.sell_listed,
                  team_venues=not args.no_team_venues, bids=not args.no_bids, bid_max=args.bid_max,
                  bid_min_value=args.bid_min_value, bid_step=args.bid_step, bid_step_ticks=args.bid_step_ticks,
                  bid_expires=args.bid_expires, address_bids=args.address_bids,
                  page_bonus=args.page_bonus or bool(args.page),
                  swap_fill=args.swap_fills, swap_post=args.swap_posts, swap_venue=args.swap_venue,
                  swap_team_venue=args.swap_team_venue,
                  swap_max=args.swap_max, swap_expires=args.swap_expires, swap_min_value=args.swap_min_value,
                  swap_max_fee=args.swap_max_fee, address_swaps=args.address_swaps,
                  swap_any_rarity=args.swap_any_rarity, swap_seller_spares=args.swap_seller_spares,
                  duel_guard_ticks=args.duel_guard_ticks, page_targets=parse_pages(args.page),
                  page_step=args.page_step, page_step_ticks=args.page_step_ticks, page_address=args.page_address)


def add_config_args(ap: argparse.ArgumentParser) -> None:
    c = Config()
    ap.add_argument("--margin-min", type=float, default=c.margin_min)
    ap.add_argument("--margin-frac", type=float, default=c.margin_frac)
    ap.add_argument("--sell-margin-min", type=float, default=c.sell_margin_min)
    ap.add_argument("--sell-margin-frac", type=float, default=c.sell_margin_frac)
    ap.add_argument("--cap-hour", type=int, default=c.cap_hour, help="max spend per game hour (P, fees included)")
    ap.add_argument("--cap-day", type=int, default=c.cap_day, help="max spend per day (P)")
    ap.add_argument("--max-price", type=int, default=c.max_price, help="max price per card")
    ap.add_argument("--max-price-rare", type=int, default=c.max_price_rare, help="max price for a rare in --rare-cap-sets")
    ap.add_argument("--rare-cap-sets", default=",".join(c.rare_cap_sets))
    ap.add_argument("--min-cash", type=int, default=c.min_cash, help="cash that must remain after a buy")
    ap.add_argument("--partner-hour", type=int, default=c.partner_hour, help="max trades per partner per game hour")
    ap.add_argument("--protect", default=",".join(c.protect), help="pages whose only copies are never sold")
    ap.add_argument("--sell-first-copies", default="", help="sets whose single copies we may sell (e.g. MAL)")
    ap.add_argument("--sell-listed", action="store_true", help="may sell a copy rastro_seller has listed")
    ap.add_argument("--no-team-venues", action="store_true", help="only El Rastro (team venues score for their owner)")
    ap.add_argument("--no-bids", action="store_true")
    ap.add_argument("--bid-max", type=int, default=c.bid_max)
    ap.add_argument("--bid-min-value", type=float, default=c.bid_min_value)
    ap.add_argument("--bid-step", type=int, default=c.bid_step)
    ap.add_argument("--bid-step-ticks", type=int, default=c.bid_step_ticks)
    ap.add_argument("--bid-expires", type=int, default=c.bid_expires, help="expires_in_ticks for our bids")
    ap.add_argument("--address-bids", action="store_true", help="address each bid to one public holder of the card")
    ap.add_argument("--page-bonus", action="store_true", help="offline values add the page bonus (unconfirmed)")
    ap.add_argument("--swap-fills", action="store_true",
                    help="opt in: accept other teams' swaps that pass the rule (off by default)")
    ap.add_argument("--swap-posts", action="store_true",
                    help="opt in: post swaps of our own (off by default; without it live ones are cancelled)")
    ap.add_argument("--no-swap-fills", action="store_true", help=argparse.SUPPRESS)   # old flag: swaps are off anyway
    ap.add_argument("--no-swap-posts", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--swap-venue", default=c.swap_venue, help="venue for our swaps (another team's needs "
                                                               "--swap-team-venue)")
    ap.add_argument("--swap-team-venue", action="store_true",
                    help="allow swaps (fills and --swap-venue) on another team's venue (its trades score market "
                         "points for its owner)")
    ap.add_argument("--swap-max", type=int, default=c.swap_max, help="max live swaps of ours")
    ap.add_argument("--swap-expires", type=int, default=c.swap_expires, help="expires_in_ticks for our swaps")
    ap.add_argument("--swap-min-value", type=float, default=c.swap_min_value)
    ap.add_argument("--swap-max-fee", type=int, default=c.swap_max_fee, help="max fee we pay to fill a swap")
    ap.add_argument("--address-swaps", action="store_true", help="address each swap to one public holder of the card")
    ap.add_argument("--swap-any-rarity", action="store_true", help="may offer a lower-rarity spare for a card")
    ap.add_argument("--swap-seller-spares", action="store_true",
                    help="may offer copies in rastro_seller's config (only when the seller is not running)")
    ap.add_argument("--page", action="append", default=[], metavar="REF:CAP[:FLOOR]",
                    help="page mode: buy REF from a team for at most CAP (fee included) on El Rastro: take an ask, "
                         "else one bid stepping up from FLOOR (default: team prices); implies --page-bonus")
    ap.add_argument("--page-step", type=int, default=c.page_step, help="P added to a page bid per step")
    ap.add_argument("--page-step-ticks", type=int, default=c.page_step_ticks, help="ticks between page-bid steps")
    ap.add_argument("--page-address", action="store_true",
                    help="address the page bid to the last public receiver of the card (default: to nobody)")
    ap.add_argument("--duel-guard-ticks", type=int, default=c.duel_guard_ticks, metavar="N",
                    help="keyed: defer ordinary accepts only while a live duel of ours is within N ticks of its "
                         "deadline (default: while any duel of ours is live). Page writes (--page asks, bids and "
                         "replacements) always wait for every live duel: N never relaxes them")


def default_feeds(files=None) -> list:
    """Every recorded feed that exists (the tape dedupes by event id). logs/feed-vm alone is Friday's ticks 0-159:
    reading only the first file left the price anchors without a single Saturday trade."""
    return [p for p in (FEED_FILES if files is None else files) if Path(p).exists()]


def until_time(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    now = datetime.now(MADRID)
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now:
        raise SystemExit(f"--until {hhmm} is already past (Madrid time {now:%H:%M})")
    return t


def main() -> None:
    ap = argparse.ArgumentParser(description="Market desk: trades with other teams at our private values")
    ap.add_argument("cmd", choices=["plan", "watch", "run"])
    ap.add_argument("--keyless", action="store_true", help="never use the key: account from logs/state/*.json")
    ap.add_argument("--feed", action="append", default=None, help="recorded feed JSONL for the tape (repeatable)")
    ap.add_argument("--me", default=str(ME_SNAPSHOT), help="keyless: /api/me snapshot")
    ap.add_argument("--offers", default=str(OFFERS_SNAPSHOT), help="keyless: /api/me/offers snapshot")
    ap.add_argument("--until", default=None, help="HH:MM Madrid time to stop (required for run)")
    ap.add_argument("--json", action="store_true", help="plan: print the JSON records too")
    ap.add_argument("--recorded", default=None, metavar="SNAPSHOTS",
                    help="plan --keyless against a recorded board (tools/feed_recorder.py snapshots.jsonl), offline")
    ap.add_argument("--catalog", default=str(LOGS / "public" / "catalog.json"), help="--recorded: catalog JSON")
    ap.add_argument("--release", default="", help="--recorded: sets to treat as released (e.g. CHA for Sunday)")
    ap.add_argument("--assume-cash", type=int, default=None, help="plan --keyless: cash to plan with (e.g. +150 P)")
    ap.add_argument("--seller-config", default=str(SELLER_CONFIG),
                    help="rastro_seller's config: its assets stay out of our swaps ('' = none)")
    add_config_args(ap)
    args = ap.parse_args()
    try:
        cfg = build_config(args)
    except ValueError as e:
        ap.error(str(e))
    if args.cmd == "run" and (args.keyless or not args.until):
        ap.error("run needs the key and --until HH:MM")
    for ref, spec in cfg.page_targets.items():
        if spec["cap"] > min(cfg.cap_hour, cfg.cap_day):
            ap.error(f"--page {ref}:{spec['cap']} is above --cap-hour {cfg.cap_hour} / --cap-day {cfg.cap_day}: "
                     f"that buy could never pass; raise them")
    if args.recorded and (args.cmd != "plan" or not args.keyless):
        ap.error("--recorded is for `plan --keyless` only")
    if args.assume_cash is not None and (args.cmd != "plan" or not args.keyless):
        ap.error("--assume-cash is for `plan --keyless` only")
    if cfg.swap_venue != HOME and not cfg.swap_team_venue:
        ap.error(f"--swap-venue {cfg.swap_venue} is another team's venue (its trades score for its owner): "
                 f"add --swap-team-venue to mean it")
    until = until_time(args.until) if args.until else None
    url = os.environ.get("BAZAAR_URL", URL)
    public = RecordedPublic(args.recorded, args.catalog, release=args.release) if args.recorded else PublicClient(url)
    keyed, lease, log = None, None, None
    if not args.keyless:
        load_env()
        key = os.environ.get("BAZAAR_KEY")
        if key:
            from lease import Lease
            lease = Lease("market")
            cls = LeasedBazaar if args.cmd == "run" else ReadOnlyBazaar
            keyed = cls(url, key, wait_on_tick=False, retries=2, lease=lease)
        elif args.cmd == "run":
            raise SystemExit("BAZAAR_KEY missing: run needs the key in .env")
        else:
            print(f"(no BAZAAR_KEY: keyless {args.cmd} from logs/state/*.json and the public feed)")
    if args.cmd in ("watch", "run"):
        log = QuietRunLog("market")
    feeds = args.feed if args.feed is not None else default_feeds()
    desk = Desk(args.cmd, cfg, public, keyed=keyed, lease=lease, log=log, feed_files=feeds,
                me_path=Path(args.me), offers_path=Path(args.offers),
                seller_config=Path(args.seller_config) if args.seller_config else None)
    desk.assume_cash = args.assume_cash
    if log is not None:
        desk.ledger = today_ledger(log.path) if args.cmd == "run" else Ledger()
        log.start(mode=args.cmd, config=asdict(cfg), feeds=[str(f) for f in feeds], keyed=keyed is not None)
    loop(desk, public, until=until, once=args.cmd == "plan", json_out=args.json)


def loop(desk: Desk, public: PublicClient, *, until=None, once=False, json_out=False) -> None:
    last, errors = None, 0
    while True:
        if until and datetime.now(MADRID) >= until:
            desk.out("until reached")
            return
        try:
            clock = public.clock()
        except BazaarError as e:
            desk.out(f"clock unread ({e.code}); retrying")
            time.sleep(5)
            continue
        is_open = clock.get("doors", "open") == "open" and not clock.get("paused")
        if once or (is_open and clock.get("tick") != last):
            try:
                res = desk.tick(clock)
                errors = 0
                if once:
                    summary(desk, clock, res, json_out)
                    return
            except Exception as e:  # unattended: log it and go on next tick
                errors += 1
                tb = traceback.extract_tb(e.__traceback__)[-1]
                desk.out(f"error at line {tb.lineno}: {type(e).__name__}: {e}"[:300])
                if desk.log:
                    desk.log.event("error", where=tb.lineno, error=f"{type(e).__name__}: {e}"[:300])
                if once:
                    raise
                if errors >= 5:
                    time.sleep(30)
            last = clock.get("tick")
        elif not is_open:
            time.sleep(30)
            continue
        wait = float(clock.get("next_tick_in") or 5) + 1.0
        time.sleep(max(1.0, min(35.0, wait)))


def summary(desk: Desk, clock: dict, res: dict, json_out: bool) -> None:
    recs = res["records"]
    print()
    snap = desk.last_snap or {}
    print(f"plan at tick {clock.get('tick')} (doors {clock.get('doors')}); account: {snap.get('account_source')}; "
          f"cash {snap.get('cash')}; boards: " + ", ".join(f"{v} {len(o)}" for v, o in (snap.get("boards") or {}).items()))
    by = {}
    for r in recs:
        by.setdefault((r["kind"], r["action"]), 0)
        by[(r["kind"], r["action"])] += 1
    print("  decisions:", ", ".join(f"{k}/{a} {n}" for (k, a), n in sorted(by.items())))
    a = res["accept"]
    print(f"  accept this tick: {line(a) if a else 'none'}")
    for r in recs:
        if r.get("page") and r["kind"] == "buy":
            print(f"  page ask: {line(r)}")
    for b in res["bids"]:
        if b.get("page"):
            print(f"  page bid: {line({**b['record'], 'tick': clock.get('tick')})}")
        elif b["action"] in ("post", "replace", "keep"):
            print(f"  bid: {line({**b['record'], 'tick': clock.get('tick')})}")
    fills = [r for r in recs if r["kind"] == "swap" and r.get("value") is not None]
    print(f"  swaps on the boards: {sum(1 for r in recs if r['kind'] == 'swap')} seen, "
          f"{sum(1 for r in fills if r['action'] in ('take', 'defer'))} pass the rule")
    for r in sorted(fills, key=lambda r: -(r.get("gain") or 0))[:10]:
        print(f"  swap fill: {line(r)}")
    for s in res.get("swaps") or []:
        if s["action"] == "note":
            print(f"  our swaps: {s['record']['reason']}")
        elif s["action"] in ("post", "replace", "keep", "cancel"):
            print(f"  our swap: {line({**s['record'], 'tick': clock.get('tick')})}")
    if json_out:
        print(json.dumps(redact(recs), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
