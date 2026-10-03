"""El Chato negotiator (the L2 dealer at El Rastro, next to Abuela Carmen).

Copied from agent/abuela.py (owned by the Abuela queue session; left untouched). Numbers are decided here, in code;
the words around them are decoration (structure binds).

What the feed showed in his first hour (Friday 22:00, 70 public messages, no deal closed yet):
- He sells uncommons and rares and buys them; no neighbourhood packs ("Abuela handles those").
- He opens at ~1.27 x list: 33 P for an uncommon (list 26), 97 P for a rare (list 77), 188 P for a silver pack.
- He concedes as much as we move or less ("You move, I move", "You moved three, I moved nothing").
- Buying from us he bids ~13 P for an uncommon and holds there.
- Strict, shrewd, long memory, low patience: every message carries a new price and new words, and we never
  call him Carmen or abuela ("Keep calling me abuela, the number goes the other way").
- One thread said "Silver pack" about a card topic: only the structured offer counts, offer_matches() stays.

Plan per deal is Abuela's: anchor low, step 1 P, and take his final offer if it is inside our limit. The ladder
scores the share of his price range we capture, so ending at his limit is the goal; our private value is a cap.
With --max-bid our bids stop there; we keep listening while his offer improved in the last 2 ticks, then take it if
it is inside our limit, or close at once (max_bid_no_deal). When the round budget runs out we take his standing
offer if it is inside our limit (buy: at or under it; sell: at or over our floor) instead of closing on it.

Usage (from the repo root):
    python3 agent/chato.py plan
    python3 agent/chato.py run --only SAL-08 --max-deals 1 --reserve 200 --cap 30
    python3 agent/chato.py run --only LAV-09 --max-deals 1 --anchor 60 --step 4 --cap 93 --reserve 200
Only ONE process per team may talk to El Chato at a time (one open conversation per dealer).
`run` refuses to start (exit 0) while agent/duel.py holds results/duel.lock (one line: expiry, epoch seconds), and
re-checks the lock before every accept: while it is fresh the accept waits a tick (no round spent).
`run` exits 3 when the cash reserve (--reserve, default 280 P) blocked every buy, with one line saying how to pass it;
4 when a thread could not be closed (one line with the --resume command: the dealer's only slot may still be held);
5 when the duel lock stayed fresh for --max-defer-ticks (default 60) and the thread was closed without a deal.
The client never lets the SDK resend a write, counts a round only for a confirmed new tick, and waits through a paused
clock with one line a minute (agent/dealer_client.py).

Doña Pilar (--dealer pilar, L3 collector): she only BUYS from us (uncommon, rare, epic; she loves SAL and RET) and
sells gold packs only, so `plan`/`run` refuse buy targets for her and list sells only. Feed evidence: she opened at
16 and held 16 across 9 threads; another team asked 49, then 42, and sold LAV-08 at 19. Our Saturday threads showed
she concedes by time: her finals were 19 to 21 on 7-8 round threads and 17 on 4-5 round threads. So our first ask
is max(1.25 x her opening bid, floor + 9) (27 for floor 18), we come down 1 P per round over a 40-round budget,
never below the floor (our private value of that copy + 2), and take her final offer if it is at or above the
floor. Logs go to logs/pilar/<date>.jsonl.
    python3 agent/chato.py plan --dealer pilar --only sell:42,sell:44 --allow-single
    python3 agent/chato.py run --dealer pilar --only sell:42,sell:44 --allow-single --max-deals 2
--allow-single lets an explicitly listed `sell:<asset_id>` go even when it is our last copy (or the copy we keep);
nothing is ever auto-selected that way: without an explicit id the agent sells spares only.
--sell-anchor N (absolute first ask), --sell-step N and --max-rounds N override the dealer's defaults; the floor
still holds.
--floor P replaces the default sell floor (private value + 2) with P for this run; a copy whose private value is above
P (hard minimum ceil(private value)) is refused: plan shows it, run stops before opening any thread.
    python3 agent/chato.py run --dealer pilar --only sell:42,sell:44 --allow-single --floor 18 --max-deals 2
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import BazaarError  # noqa: E402
# the kit client with wait_on_tick off and a pause-safe wait_tick (agent/dealer_client.py); kit/ stays unchanged
from dealer_client import DealerBazaar as Bazaar  # noqa: E402
from dealer_client import (ACCEPTED, CLOSE_TRIES, DEFERRED, END_ACCEPTS, EXIT_CLOSE_FAILED,  # noqa: E402,F401
                           EXIT_LOCK_TIMEOUT, EXIT_RESERVE, MAX_DEFER_TICKS, Rounds, close_failed_line,
                           guarded_accept, lock_timeout_line, reserve_line, try_close)
from runlog import RunLog, save_thread  # noqa: E402

RUN = RunLog("chato")       # logs/chato/<date>.jsonl, committed; keys are redacted (main() swaps it per --dealer)
DEALER = "chato"
CASH_RESERVE = 280          # default; the owner may lower it per run with --reserve
ANCHOR_FRAC = 0.40          # first counter, as a share of her opening price (buying)
ANCHOR_ABS = None           # --anchor N: absolute first bid when buying (overrides ANCHOR_FRAC)
SELL_ANCHOR_MULT = 1.6      # first ask, as a multiple of his opening bid (selling); he holds his bid, so stay short
SELL_ANCHOR_OVER_FLOOR = 0  # first ask is at least floor + this (selling); 0 for Chato, so his anchor is unchanged
SELL_ANCHOR_ABS = None      # --sell-anchor N: absolute first ask when selling (overrides the multiple; floor holds)
STEP = 1                    # primas per round when buying: he mirrors our step, his final comes at his limit
MAX_BID = None              # --max-bid N: our bids stop here; his offer is still taken up to the reservation
MAX_BID_STALL = 2           # pinned at --max-bid: listen while his offer improved in the last 2 ticks, then decide
SELL_STEP = 2               # primas per round when selling (time is short and his bid barely moves)
MAX_ROUNDS = 12             # 60 s ticks: 12 rounds is 12 minutes; his patience is low (per dealer: DEALERS)
DUEL_LOCK = ROOT / "results" / "duel.lock"   # written by agent/duel.py run while any of our duels is live

# Per-dealer table. Chato's row is exactly the constants above, so no --dealer flag means no change.
DEALERS = {
    "chato": {"name": "El Chato", "buys": ("uncommon", "rare"), "sells_cards": True,
              "sell_anchor_mult": 1.6, "sell_anchor_over_floor": 0, "sell_step": 2, "example_bid": 13,
              "max_rounds": 12},
    # L3 collector: buys uncommon/rare/epic (loves SAL, RET), sells gold packs only. Opened 16, held 16 (feed).
    # She concedes by time, not by our steps: her finals were 19 to 21 on 7-8 round threads and 17 on 4-5 round
    # threads (Saturday). So: first ask max(1.25 x her bid, floor + 9) (27 for floor 18 against her usual 16; the
    # 1.25 only matters if she opens high, so we never take her opener outright), 1 P steps, a 40-round budget.
    "pilar": {"name": "Doña Pilar", "buys": ("uncommon", "rare", "epic"), "sells_cards": False,
              "sell_anchor_mult": 1.25, "sell_anchor_over_floor": 9, "sell_step": 1, "example_bid": 16,
              "max_rounds": 40},
}
DEFAULT_DEALER = "chato"
DEALER_NAME = DEALERS[DEFAULT_DEALER]["name"]
SELL_RARITIES = DEALERS[DEFAULT_DEALER]["buys"]       # what the dealer buys from us
DEALER_SELLS_CARDS = DEALERS[DEFAULT_DEALER]["sells_cards"]


def apply_dealer(dealer: str, sell_anchor: int | None = None, sell_step: int | None = None,
                 max_rounds: int | None = None) -> None:
    """Point every dealer-specific global at one row of DEALERS (plus the --sell-anchor/--sell-step/--max-rounds
    overrides: an explicit flag always wins over the dealer's default)."""
    global DEALER, DEALER_NAME, SELL_RARITIES, DEALER_SELLS_CARDS, SELL_ANCHOR_MULT, SELL_ANCHOR_OVER_FLOOR
    global SELL_ANCHOR_ABS, SELL_STEP, MAX_ROUNDS
    d = DEALERS[dealer]
    DEALER, DEALER_NAME = dealer, d["name"]
    SELL_RARITIES, DEALER_SELLS_CARDS = d["buys"], d["sells_cards"]
    SELL_ANCHOR_MULT, SELL_ANCHOR_OVER_FLOOR = d["sell_anchor_mult"], d["sell_anchor_over_floor"]
    SELL_ANCHOR_ABS = sell_anchor
    SELL_STEP = d["sell_step"] if sell_step is None else int(sell_step)
    MAX_ROUNDS = d["max_rounds"] if max_rounds is None else int(max_rounds)


def duel_lock_fresh(path: Path = DUEL_LOCK) -> bool:
    """True while the duel bot holds the team's accept slot (first token of the file = expiry, epoch seconds)."""
    try:
        return float(path.read_text().split()[0]) > time.time()
    except (OSError, ValueError, IndexError):
        return False


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def log(event: str, **data) -> None:
    RUN.event(event, **data)


# ---------------------------------------------------------------- words (never contradict the number)

BUY_LINES = [
    "Buenas. Straight offer, cash ready: {p} P.",
    "I hear you. I move, you move: {p} P.",
    "Fair is fair. {p} P, paid on the spot.",
    "One more step from me: {p} P.",
    "No theatre. {p} P.",
    "I am still here and still serious: {p} P.",
    "Moving again. {p} P.",
    "Let us close it. {p} P.",
    "Another step: {p} P. Your turn.",
    "{p} P. Clean card, clean deal.",
    "Up again, {p} P.",
    "{p} P, and I keep moving.",
]
SELL_LINES = [
    "Buenas. Clean card, straight price: {p} P.",
    "I move, you move. {p} P.",
    "Coming down: {p} P.",
    "Fair is fair. {p} P.",
    "No theatre. {p} P and it is yours.",
    "Another step down: {p} P.",
    "{p} P. Your turn.",
    "Down again, {p} P.",
]


def line(lines: list, n: int, p: int) -> str:
    return lines[n % len(lines)].format(p=p)


# ---------------------------------------------------------------- offers

def her_open_offer(thread: dict) -> dict | None:
    hers = [o for o in thread.get("standing_offers") or []
            if o.get("maker") == DEALER and o.get("status") in ("open", "queued")]
    return hers[-1] if hers else None


def offer_price(o: dict) -> int:
    """Cash in her offer: what she wants when she sells, what she gives when she buys."""
    return int((o.get("want") or {}).get("cash") or (o.get("give") or {}).get("cash") or 0)


def offer_matches(o: dict, side: str, item: str, asset_id: int | None) -> bool:
    """Read the structure, not the words: the offer must move the item we negotiated."""
    give, want = o.get("give") or {}, o.get("want") or {}
    if side == "buy":
        refs = [a.get("ref") for a in give.get("assets") or []] + [t.split(":", 1)[-1] for t in give.get("types") or []]
        return item in refs and bool(want.get("cash"))
    ids = [a.get("id") if isinstance(a, dict) else a for a in want.get("assets") or []]
    return asset_id in ids and bool(give.get("cash"))


def sell_anchor(her: int, floor: int) -> int:
    """Our first ask when selling: --sell-anchor if set, else max(mult x her opening bid, floor + over_floor).
    For Chato (over_floor 0) this is round(1.6 x her), exactly as before; the caller still clamps it to the floor."""
    if SELL_ANCHOR_ABS is not None:
        return int(SELL_ANCHOR_ABS)
    return max(int(round(her * SELL_ANCHOR_MULT)), int(floor) + SELL_ANCHOR_OVER_FLOOR)


def sell_ladder(her: int, floor: int) -> list:
    """The asks a sell walks through if the dealer holds `her` (shown by plan; she may cross or stop us earlier)."""
    out, a = [], max(sell_anchor(her, floor), int(floor))
    while a > floor and len(out) < 30:
        out.append(a)
        a -= SELL_STEP
    return out + [int(floor)]


# ---------------------------------------------------------------- one negotiation

def negotiate(b: Bazaar, target: dict, first_deal: bool, resume: int | None = None) -> dict:
    side, item, value = target["side"], target["item"], target["value"]
    asset_id = target.get("asset_id")
    if side == "buy" and not DEALER_SELLS_CARDS:  # e.g. Pilar sells gold packs only: never open a card buy
        log("refuse_buy", item=item, dealer=DEALER)
        return {"result": "refused", "code": "dealer_sells_no_cards"}
    topic ={"buy": {"card": item}} if side == "buy" else {"sell": {"assets": [asset_id]}}
    ours: int | None = None
    said = 0
    last_her = None
    answered = None  # id of his offer we last countered
    if resume:
        # pick up a conversation an earlier process left open: our last number comes from the first good read
        tid = resume
    else:
        try:
            th = b.open_thread(DEALER, topic=topic)
        except BazaarError as e:
            log("open_refused", item=item, side=side, code=e.code, msg=e.message)
            return {"result": "refused", "code": e.code}
        tid = th["id"]
        log("open", thread=tid, side=side, item=item, value=value)

    rounds = Rounds(b, MAX_ROUNDS, MAX_DEFER_TICKS)  # a round is a confirmed tick; deferrals and pauses are free
    stall = 0  # reads since his price last improved or we last moved (the --max-bid pin listens meanwhile)

    def close(event: str, result: str, **info) -> dict | None:
        """Close for `result`. None: the close was refused and the loop decides again on a fresh read."""
        if try_close(b, tid, log, rounds, event):
            log(event, thread=tid, **info)
            return {"result": result, "thread": tid, **{k: info[k] for k in ("ours", "her") if k in info}}
        if rounds.close_refusals >= CLOSE_TRIES:
            log("close_failed", thread=tid, wanted=result, refusals=rounds.close_refusals)
            return {"result": "close_failed", "thread": tid, "wanted": result}
        return None

    while True:
        spent = rounds.spent()
        try:
            t = b.thread(tid)
        except BazaarError as e:
            log("read_refused", thread=tid, code=e.code, msg=e.message, round=rounds.used)
            if spent:  # cannot see the offer and the budget is gone: close
                r = close("max_rounds", "max_rounds", ours=ours, her=last_her)
                if r:
                    return r
                continue
            rounds.wait()
            continue
        if resume:
            msgs = sorted(t.get("messages") or [], key=lambda m: m.get("id") or 0)
            mine = [m for m in msgs if m.get("sender") != DEALER and m.get("offer")]
            if mine:  # continue from our last number, never step back
                ours = offer_price(mine[-1]["offer"])
                said = len(mine)
                if msgs[-1].get("sender") != DEALER:  # our number is the latest word: wait for his answer
                    o = her_open_offer(t)
                    answered = o["id"] if o else None
            log("resume", thread=tid, side=side, item=item, value=value, ours=ours, answered=answered)
            resume = None
        status = t.get("status")
        if status != "open":
            log("closed", thread=tid, status=status, reason=t.get("closed_reason"), ours=ours, her=last_her)
            return {"result": status, "thread": tid, "ours": ours, "her": last_her}
        o = her_open_offer(t)
        if o is not None and not offer_matches(o, side, item, asset_id):
            log("mismatch", thread=tid, offer=o)  # a switched item: never accept it
            o = None
        if o is None:
            if spent:
                r = close("max_rounds", "max_rounds", ours=ours, her=last_her)
                if r:
                    return r
                continue
            rounds.wait()
            continue
        her = offer_price(o)
        final = bool(o.get("final"))
        improved = last_her is None or (her < last_her if side == "buy" else her > last_her)
        stall = 0 if improved else stall + 1
        if her != last_her:
            log("her", thread=tid, price=her, final=final, round=rounds.used)
        last_her = her
        try:
            cash = b.me()["cash"] if side == "buy" else None
        except BazaarError as e:
            log("read_refused", thread=tid, code=e.code, msg=e.message, round=rounds.used)
            if spent:
                r = close("max_rounds", "max_rounds", ours=ours, her=her)
                if r:
                    return r
                continue
            rounds.wait()
            continue
        reservation = (min(value, cash - CASH_RESERVE) if side == "buy" else value)
        reservation = int(reservation) if side == "buy" else int(-(-reservation // 1))  # sells: floor rounded UP

        def good(p: int) -> bool:
            return p <= reservation if side == "buy" else p >= reservation

        # our bid sits at --max-bid (at or below our reservation) while his offer is still above it
        at_max_bid = (side == "buy" and MAX_BID is not None and ours is not None and ours >= int(MAX_BID)
                      and int(MAX_BID) <= reservation)
        why = None
        if final:
            # 1) his last word: take it if it is still a good deal, else walk
            if not good(her):
                r = close("walk", "walked_by_us", price=her, reservation=reservation)
                if r:
                    return r
                continue
            why = "final"
        elif spent:
            # 2) the round budget is spent: never close on a standing offer inside our reservation
            if not good(her):
                r = close("max_rounds", "max_rounds", ours=ours, her=her)
                if r:
                    return r
                continue
            why = "budget_end"
        elif at_max_bid and stall >= MAX_BID_STALL:
            # 3) pinned at --max-bid and he stopped improving: take his offer if it is inside our reservation
            if not good(her):
                r = close("max_bid_no_deal", "max_bid_no_deal", ours=ours, her=her, reservation=reservation,
                          max_bid=MAX_BID, stall=stall)
                if r:
                    return r
                continue
            why = "max_bid_stall"
        elif o["id"] == answered:
            # 4) he has not answered our last number yet: never bid against ourselves
            rounds.wait()
            continue
        else:
            # 5) our next number: low anchor, then STEP per round toward him
            if ours is None:
                if side == "buy":
                    nxt = int(ANCHOR_ABS) if ANCHOR_ABS is not None else int(her * ANCHOR_FRAC)
                else:
                    nxt = sell_anchor(her, reservation)
            else:
                nxt = ours + STEP if side == "buy" else ours - SELL_STEP
            nxt = int(min(nxt, reservation)) if side == "buy" else int(max(nxt, reservation))
            if side == "buy" and MAX_BID is not None:
                nxt = min(nxt, int(MAX_BID))  # stop bidding here; his offer is still taken up to the reservation
            # 6) he is already at (or past) our next number: take his price
            crossed = her <= nxt if side == "buy" else her >= nxt
            if crossed and good(her):
                why = "crossed"
            elif ours is not None and nxt == ours:  # pinned: listen (his final, or the --max-bid stall rule)
                rounds.wait()
                continue
            else:
                try:
                    b.say(tid, line(BUY_LINES if side == "buy" else SELL_LINES, said, nxt), price=nxt)
                except BazaarError as e:  # nothing moved: decide again next tick, after a fresh read
                    log("say_refused", thread=tid, price=nxt, code=e.code, msg=e.message, round=rounds.used)
                    rounds.wait()
                    continue
                ours = nxt
                answered = o["id"]
                said += 1
                stall = 0  # our move restarts his window: a late answer to our capped bid is still heard
                log("say", thread=tid, price=ours, her=her)
                rounds.wait()
                continue
        # 7) accept, behind the duel lock; once the budget is spent only END_ACCEPTS attempts, each on a fresh read
        if spent and rounds.end_tries >= END_ACCEPTS:
            r = close("max_rounds", "max_rounds", ours=ours, her=her)
            if r:
                return r
            continue
        r = guarded_accept(b, o["id"], duel_lock_fresh, log, thread=tid, price=her, why=why, round=rounds.used)
        if r == ACCEPTED:
            log("accept", thread=tid, price=her, why=why, ours=ours, round=rounds.used)
            return settle(b, tid, her)
        if r == DEFERRED:
            if rounds.lock_timed_out():  # the duel bot kept the team's accept for --max-defer-ticks
                r = close("lock_timeout", "lock_timeout", ticks=rounds.deferred, price=her)
                if r:
                    return dict(r, ticks=rounds.deferred)
                continue
            rounds.defer()  # wait a tick, no round spent; then re-check the lock on a fresh read
            continue
        if spent:  # REFUSED: never resent blindly; wait, re-read, decide again
            rounds.end_tries += 1
        rounds.wait()


def settle(b: Bazaar, tid: int, price: int) -> dict:
    t: dict = {}
    for _ in range(4):  # it settles on the next tick
        b.wait_tick()
        try:
            t = b.thread(tid)
        except BazaarError as e:
            log("read_refused", thread=tid, code=e.code, msg=e.message)
            continue
        if t.get("status") != "open":
            break
    log("result", thread=tid, status=t.get("status"), price=price, reason=t.get("closed_reason"))
    return {"result": t.get("status"), "thread": tid, "price": price}


# ---------------------------------------------------------------- what to trade

def listed_sell_ids(only: list[str] | None) -> list[int]:
    """The asset ids named as sell:<asset_id> in --only, in order."""
    out = []
    for x in only or []:
        k, _, v = x.partition(":")
        if k == "sell" and v.isdigit():
            out.append(int(v))
    return out


def build_plan(b: Bazaar, me: dict, only: list[str] | None, cap: float | None, allow_single: bool = False) -> list[dict]:
    """Buys: uncommons and rares Chato sells that we do not hold, ranked by our value (none for a dealer that sells
    no cards, e.g. Pilar). Sells: our duplicate cards of a rarity the dealer buys (a spare is worth much less to us).
    With allow_single, an asset named as sell:<asset_id> in `only` may go even if it is our last copy; nothing is
    auto-selected that way. --cap lowers (never raises) our value as the most we pay (the ladder scores his price
    range, not our value)."""
    held = {}
    for a in me["assets"]:
        if a["kind"] == "card":
            held.setdefault(a["ref"], []).append(a)
    buys = []
    if DEALER_SELLS_CARDS:
        catalog = b.catalog()
        released = {s["id"] for s in catalog["sets"] if s["released"]}
        for s in catalog["sets"]:
            if s["id"] not in released:
                continue
            for c in s["cards"]:
                if c["rarity"] not in ("uncommon", "rare") or c["id"] in held:
                    continue
                if only and c["id"] not in only:
                    continue
                v = b.value(c["id"])["your_value"]
                buys.append({"side": "buy", "item": c["id"], "name": c["name"], "book": c["book"],
                             "value": min(v, cap) if cap else v, "private": v})
        buys.sort(key=lambda x: -x["private"])
    sells = []
    for ref, copies in held.items():
        if len(copies) > 1 and copies[0]["rarity"] in SELL_RARITIES:
            spare = max(copies, key=lambda a: a["serial"])  # keep the lowest serial
            sells.append({"side": "sell", "item": ref, "name": spare["name"], "asset_id": spare["id"],
                          "value": spare["your_value"] + 2, "private": spare["your_value"]})
    if allow_single:  # only explicitly named ids; the floor is still that copy's private value + 2
        by_id = {a["id"]: a for copies in held.values() for a in copies}
        planned = {s["asset_id"] for s in sells}
        for aid in listed_sell_ids(only):
            a = by_id.get(aid)
            if a is None or aid in planned or a["rarity"] not in SELL_RARITIES:
                continue
            sells.append({"side": "sell", "item": a["ref"], "name": a["name"], "asset_id": aid,
                          "value": a["your_value"] + 2, "private": a["your_value"], "single": True,
                          "last": len(held[a["ref"]]) == 1})
            planned.add(aid)
    plan = sells + buys  # sells first: they bring cash in
    if only:
        keys = set(only)
        plan = [p for p in plan if (p["side"] == "buy" and p["item"] in keys) or f"sell:{p.get('asset_id')}" in keys]
    return plan


def apply_floor(plan: list[dict], floor: int | None) -> tuple[list[dict], list[dict]]:
    """--floor P replaces the default sell floor (private value + 2) with P for this run. P below our private value of
    a copy (hard minimum ceil(private)) is refused for that copy: it comes back in the second list and is never sold."""
    if floor is None:
        return plan, []
    kept, refused = [], []
    for p in plan:
        if p["side"] != "sell":
            kept.append(p)
        elif int(floor) < math.ceil(p["private"]):
            refused.append(dict(p, why=f"--floor {floor} is below our private value {p['private']} "
                                       f"(minimum {math.ceil(p['private'])})"))
        else:
            kept.append(dict(p, value=int(floor), floor_override=True))
    return kept, refused


def bid_ladder(limit: float, spendable: int) -> list:
    """The bids a buy would walk through with --anchor (shown by plan; she may cross or stop us earlier)."""
    top = int(min(limit, spendable, MAX_BID if MAX_BID is not None else limit))
    if ANCHOR_ABS is None or top < 1:
        return []
    out, b = [], int(ANCHOR_ABS)
    while b < top and len(out) < 30:
        out.append(b)
        b += STEP
    return out + [top]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--only", default="", help="comma list of card refs and/or sell:<asset_id>")
    ap.add_argument("--max-deals", type=int, default=3)
    ap.add_argument("--resume", type=int, default=None, help="thread id to continue for the first target")
    ap.add_argument("--max-rounds", type=int, default=None,
                    help="round budget per thread, one round per tick (default per dealer: chato 12, pilar 40)")
    ap.add_argument("--reserve", type=int, default=CASH_RESERVE, help="cash we never spend below")
    ap.add_argument("--cap", type=float, default=None, help="most we pay for any card (default: our value)")
    ap.add_argument("--anchor", type=int, default=None, help="absolute first bid when buying (overrides ANCHOR_FRAC)")
    ap.add_argument("--step", type=int, default=STEP, help="primas per round when buying (default 1)")
    ap.add_argument("--max-bid", type=int, default=None, help="highest number we send when buying; his final is still taken up to the cap")
    ap.add_argument("--dealer", choices=sorted(DEALERS), default=DEFAULT_DEALER,
                    help="which dealer to talk to (default chato; pilar buys from us only)")
    ap.add_argument("--allow-single", action="store_true",
                    help="with explicit sell:<asset_id> entries only: sell that copy even if it is our last one")
    ap.add_argument("--sell-anchor", type=int, default=None,
                    help="absolute first ask when selling, in P (default per dealer: chato 1.6 x his bid, "
                         "pilar max(1.25 x her bid, floor + 9)); never below the floor")
    ap.add_argument("--sell-step", type=int, default=None, help="primas per round when selling (default chato 2, pilar 1)")
    ap.add_argument("--max-defer-ticks", type=int, default=MAX_DEFER_TICKS,
                    help="ticks an accept may wait on the duel lock in one thread before the thread is closed "
                         f"(exit {EXIT_LOCK_TIMEOUT}; default {MAX_DEFER_TICKS})")
    ap.add_argument("--floor", type=int, default=None,
                    help="sell floor in P for this run, replacing private value + 2; refused below ceil(private value)")
    args = ap.parse_args(argv)
    if args.step < 1 or (args.anchor is not None and args.anchor < 1):
        ap.error("--step and --anchor must be >= 1")
    if (args.sell_step is not None and args.sell_step < 1) or (args.sell_anchor is not None and args.sell_anchor < 1):
        ap.error("--sell-step and --sell-anchor must be >= 1")
    if args.floor is not None and args.floor < 1:
        ap.error("--floor must be >= 1")
    if args.max_rounds is not None and args.max_rounds < 1:
        ap.error("--max-rounds must be >= 1")
    if args.max_defer_ticks < 1:
        ap.error("--max-defer-ticks must be >= 1")
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if args.allow_single and not listed_sell_ids(only):
        ap.error("--allow-single needs explicit --only sell:<asset_id> entries (nothing is auto-selected)")
    if not DEALERS[args.dealer]["sells_cards"]:
        buys = [x for x in only if not x.startswith("sell:")]
        if buys:
            ap.error(f"{args.dealer} sells no cards to us (gold packs only): refusing buy targets {','.join(buys)}; "
                     "list sell:<asset_id> entries only")
    return args


def sell_skips(me: dict, only: list[str] | None, plan: list[dict], allow_single: bool) -> list[str]:
    """Why each explicitly listed sell:<asset_id> is not in the plan (plan output only)."""
    by_id = {a["id"]: a for a in me["assets"]}
    planned = {p.get("asset_id") for p in plan}
    out = []
    for aid in listed_sell_ids(only):
        if aid in planned:
            continue
        a = by_id.get(aid)
        if a is None:
            why = "not one of our assets"
        elif a.get("kind") != "card":
            why = f"not a card ({a.get('kind')})"
        elif a.get("rarity") not in SELL_RARITIES:
            why = f"{DEALER} does not buy {a.get('rarity')}"
        elif not allow_single:
            why = "not a spare (our last copy, or the copy we keep): add --allow-single to sell it"
        else:
            why = "not planned"
        out.append(f"  skip sell:{aid} {(a or {}).get('ref', '')}: {why}")
    return out


def on_wait(kind: str, clock: dict, waited: float) -> None:
    """Called by the client when a wait finds the game paused, the doors closed or the clock unreadable, then once a
    minute while it lasts: one line for the operator, one log event."""
    log("clock_wait", kind=kind, tick=clock.get("tick"), waited=int(waited))
    print(f"waiting: {kind.replace('_', ' ')} at tick {clock.get('tick', '?')}, {int(waited)} s so far "
          "(no round is spent while waiting)", flush=True)


def main() -> None:
    global CASH_RESERVE, MAX_ROUNDS, ANCHOR_ABS, STEP, MAX_BID, RUN, MAX_DEFER_TICKS
    load_env()
    args = parse_args()
    apply_dealer(args.dealer, args.sell_anchor, args.sell_step, args.max_rounds)
    extra = (args.dealer != DEFAULT_DEALER or args.allow_single or args.sell_anchor is not None
             or args.sell_step is not None or args.floor is not None)  # print/log the new selling details; plain chato output is unchanged
    if args.cmd == "run" and duel_lock_fresh():
        print(f"WARNING: {DUEL_LOCK.relative_to(ROOT)} is fresh: the duel bot holds the team's accept slot. "
              f"Not starting {DEALER_NAME}; try again after the duel wave.", flush=True)
        return
    ANCHOR_ABS, STEP, MAX_BID, MAX_DEFER_TICKS = args.anchor, args.step, args.max_bid, args.max_defer_ticks
    # wait_on_tick=False: a refused write comes back to negotiate(), which re-reads and decides again (never resent)
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"],
               wait_on_tick=False)
    b.on_wait = on_wait
    me = b.me()
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    plan = build_plan(b, me, only, args.cap, allow_single=args.allow_single)
    plan, floor_refused = apply_floor(plan, args.floor)
    CASH_RESERVE = args.reserve
    print(f"{me['name']} cash={me['cash']} level={me['level']} deals={me['score'].get('deals')}")
    for p in plan:
        print(f"  {p['side']:4} {p['item']:7} limit={p['value']:6.1f} private={p['private']:6.1f}  {p.get('name', '')}"
              + (f"  asset={p.get('asset_id')}{(' LAST COPY' if p.get('last') else ' KEPT COPY') if p.get('single') else ''}"
                 if extra and p['side'] == 'sell' else ""))
    print(f"reserve={CASH_RESERVE} (spendable {me['cash'] - CASH_RESERVE} P) anchor={ANCHOR_ABS or f'{ANCHOR_FRAC} x her ask'} "
          f"step={STEP} cap={args.cap}")
    for p in plan:
        if p["side"] == "buy" and ANCHOR_ABS is not None:
            print(f"  bids {p['item']}: {' '.join(str(x) for x in bid_ladder(p['value'], me['cash'] - CASH_RESERVE))}"
                  f" (then take his offer once it is <= {int(min(p['value'], me['cash'] - CASH_RESERVE))}"
                  + (", or close if he stalls 2 ticks above it" if MAX_BID is not None else "") + ")")
    if extra:
        first = (f"{SELL_ANCHOR_ABS}" if SELL_ANCHOR_ABS is not None
                 else f"max({SELL_ANCHOR_MULT} x her bid, floor + {SELL_ANCHOR_OVER_FLOOR})")
        print(f"dealer={DEALER} ({DEALER_NAME}) buys={','.join(SELL_RARITIES)} first ask={first} sell_step={SELL_STEP} "
              f"allow_single={args.allow_single}")
        if args.dealer != DEFAULT_DEALER and args.cmd == "plan":
            try:  # her live menu, to cross-check the table above (read-only GET)
                menu = (b.dealer(DEALER) or {}).get("menu") or {}
                print(f"  menu buys: {[x.get('rarity') for x in menu.get('buys') or []]} "
                      f"sells: {[x.get('pack') or x.get('rarity') for x in menu.get('sells') or []]}")
            except Exception as e:  # noqa: BLE001  (plan output must not die on a menu read)
                print(f"  menu read failed: {e}")
        for p in plan:
            if p["side"] == "sell":
                eg = DEALERS[DEALER]["example_bid"]
                floor = int(-(-p["value"] // 1))
                asks = []
                for x in sell_ladder(eg, floor):
                    asks.append(x)
                    if x <= eg:  # she is at our ask: we take her price there
                        break
                then = f"she crosses: deal at {eg}" if asks[-1] <= eg else f"then her final; take it if >= {floor}"
                print(f"  asks {p['item']} (asset {p['asset_id']}) if she bids {eg}: "
                      f"{' '.join(str(x) for x in asks)} ({then})")
        for s in sell_skips(me, only, plan + floor_refused, args.allow_single):
            print(s)
        for p in floor_refused:
            print(f"  REFUSED sell:{p['asset_id']} {p['item']}: {p['why']}")
    if args.cmd == "plan":
        return
    if floor_refused:  # never sell a copy below our private value: stop before any thread opens
        print(f"Not starting: {len(floor_refused)} sell(s) refused by --floor; raise it or drop those ids.", flush=True)
        sys.exit(2)
    if args.dealer != DEFAULT_DEALER:
        RUN = RunLog(args.dealer)  # logs/<dealer>/<date>.jsonl
    RUN.start(cash=me["cash"], level=me["level"], deals=me["score"].get("deals"), reserve=CASH_RESERVE, cap=args.cap,
              plan=[{k: p.get(k) for k in ("side", "item", "asset_id", "value")} for p in plan[:args.max_deals + 3]],
              **({"dealer": DEALER, "allow_single": args.allow_single, "sell_anchor": SELL_ANCHOR_ABS,
                  "sell_step": SELL_STEP, "floor": args.floor} if extra else {}))
    done = 0
    stop = None   # (exit status, the one line for the operator) when a thread ends in close_failed or lock_timeout
    buys_reached, buys_short = 0, []
    need = max(5, ANCHOR_ABS or 0)   # the least a buy needs above the reserve: never open below --anchor
    for target in plan:
        if done >= args.max_deals:
            break
        me = b.me()
        if target["side"] == "buy":
            buys_reached += 1
            if me["cash"] - CASH_RESERVE < need:
                log("skip_cash", item=target["item"], cash=me["cash"], reserve=CASH_RESERVE, anchor=ANCHOR_ABS)
                buys_short.append(target["item"])
                continue   # e.g. before the grant: never open at a bid below --anchor and burn a dealer slot
        r = negotiate(b, target, False, resume=args.resume if target is plan[0] else None)
        if r.get("thread"):
            try:
                save_thread(b, r["thread"])  # full transcript, her words included
            except BazaarError as e:
                log("save_thread_failed", thread=r["thread"], code=e.code)
        if r.get("result") == "deal":
            done += 1
        if r.get("result") == "close_failed":  # the dealer's only conversation slot may still be held
            spec = target["item"] if target["side"] == "buy" else f"sell:{target['asset_id']}"
            cmd = (f"python3 agent/chato.py run{'' if DEALER == DEFAULT_DEALER else ' --dealer ' + DEALER} "
                   f"--only {spec}{' --allow-single' if target.get('single') else ''} --resume {r['thread']}")
            stop = (EXIT_CLOSE_FAILED, close_failed_line(r["thread"], DEALER_NAME, cmd))
            log("stop", code="close_failed", thread=r["thread"])
            break
        if r.get("result") == "lock_timeout":
            stop = (EXIT_LOCK_TIMEOUT, lock_timeout_line(r["thread"], r.get("ticks", MAX_DEFER_TICKS)))
            log("stop", code="lock_timeout", thread=r["thread"])
            break
        if r.get("code") in ("persona_quota", "cooloff", "locked"):
            log("stop", code=r["code"])
            break
    me = b.me()
    blocked = not stop and buys_reached and len(buys_short) == buys_reached
    if blocked:  # say it out loud instead of finishing silently with nothing done
        log("reserve_blocks_buys", cash=me["cash"], reserve=CASH_RESERVE, need=need, items=buys_short)
    s = me["score"]
    RUN.end(cash=me["cash"], level=me["level"], unlocked=me["unlocked"], deals=s.get("deals"),
            ladder_points=s.get("ladder_points"), score=s.get("score"), rank=s.get("rank"))
    if stop:
        print(stop[1], flush=True)
        sys.exit(stop[0])
    if blocked:
        print(reserve_line(me["cash"], CASH_RESERVE, need, len(buys_short)), flush=True)
        sys.exit(EXIT_RESERVE)


if __name__ == "__main__":
    main()
