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
4 when a thread could not be closed (one line with the --resume command, carrying every limit of this run:
the dealer's only slot may still be held); 5 when the duel lock stayed fresh for --max-defer-ticks (default 60) and the
thread was closed without a deal; 6 when an accept went out but its settlement could not be confirmed (the plan
stops: the trade may have happened); 7 when the game clock could not be confirmed for 5 waits in a row (the thread
was closed). The status line is printed before the final account read, which is best effort.
`--resume` skips the cash check for a new conversation: the thread is read and resolved inside its limit (a resumed
buy whose earlier bid is above what may be spent now, or with nothing spendable, is closed).
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
nothing is ever auto-selected that way: without an explicit id the agent sells spares only. `sell:<REF>` (sell:RET-09)
names the copy we hold of that card (the highest serial) when its asset id is not known yet, e.g. a card bought a
minute ago; a ref we hold no copy of is skipped with a reason.
--dealer picaros (L4, tricksters): buys RARES from him (`--only SAL-10,RET-09 --cap 62 --anchor 40 --step 2`); nothing is
ever sold to him (his bids are below every value of ours), named ids included. Feed: he opens at 73, then 64, 59, 54 and
a final at 52-63; steps of 1-2 P ended at 52-57.
--sell-anchor N (absolute first ask), --sell-step N and --max-rounds N override the dealer's defaults; the floor
still holds.
--floor P replaces the default sell floor (private value + 2) with P for this run; a copy whose private value is above
P (hard minimum ceil(private value)) is refused: plan shows it, run stops before opening any thread.
Ladder value gate (agent/dealer_client.py): a deal on the wrong side of our private value earns no ladder credit, and the
API value can sit above that gate (a page-completing card carries the page bonus). So a buy's limit is clipped to
floor(book x our set multiplier), the multiplier read from /api/me, and `plan` prints it next to the API value as
ladder=N; a --cap above it is refused (plan prints REFUSED, run stops before any thread opens, exit 2). Sells are
graded against the copy we give up (100 % / 25 % / 10 %): the default floor is never below ceil(book x multiplier x
marginal), and --floor below it is refused like one below the API value.
`open` logs the API value and the gate next to the limit.
The gate is re-priced while a thread runs: other bots trade the same cards, so before every priced message and every
accept the bot re-reads /api/me and takes live_limit() (a buy that became our second copy is worth 25 %; a spare whose kept
copy left is a first copy). A limit that no longer allows the deal closes the thread (limit_dropped when our own standing
number is on the wrong side, limit_unknown when the holdings, the copy or the set multiplier cannot be read), and an offer
must be exactly the deal: no extra asset or type of ours, no second card, no cash coming back. A card whose set has no
multiplier is refused (REFUSED, exit 2), never priced on a guess.
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
from dealer_client import (ACCEPTED, CLOSE_TRIES, DEFERRED, END_ACCEPTS, EXIT_CLOCK_LOST,  # noqa: E402,F401
                           EXIT_CLOSE_FAILED, EXIT_LOCK_TIMEOUT, EXIT_RESERVE, EXIT_UNSETTLED, MAX_DEFER_TICKS, MAX_FAILED_WAITS,
                           Rounds, buy_ceiling, clock_lost_line, close_failed_line, command, exact_offer, flag_value,
                           guarded_accept, limit_dropped, live_limit, lock_timeout_line, refuse_caps, refuse_unpriced,
                           reserve_line, sell_ladder_floor, settle_trade, try_close, unsettled_line)
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
    "chato": {"name": "El Chato", "buys": ("uncommon", "rare"), "sells_cards": True, "sells": ("uncommon", "rare"),
              "sell_anchor_mult": 1.6, "sell_anchor_over_floor": 0, "sell_step": 2, "example_bid": 13,
              "max_rounds": 12},
    # L3 collector: buys uncommon/rare/epic (loves SAL, RET), sells gold packs only. Opened 16, held 16 (feed).
    # She concedes by time, not by our steps: her finals were 19 to 21 on 7-8 round threads and 17 on 4-5 round
    # threads (Saturday). So: first ask max(1.25 x her bid, floor + 9) (27 for floor 18 against her usual 16; the
    # 1.25 only matters if she opens high, so we never take her opener outright), 1 P steps, a 40-round budget.
    "pilar": {"name": "Doña Pilar", "buys": ("uncommon", "rare", "epic"), "sells_cards": False,
              "sell_anchor_mult": 1.25, "sell_anchor_over_floor": 9, "sell_step": 1, "example_bid": 16,
              "max_rounds": 40},
    # L4 tricksters: they SELL rares (opening 73, then 64, 59, 54 and a final at 52-63 as we move; 52-57 when our
    # steps are 1-2 P) and epics (128-167), and buy only commons (4-5) and uncommons (10-12), always below our values.
    # So `buys` is empty: nothing is ever sold to them (not even a named sell:<id>), and only rares are bought. Offers
    # that switch the card (the topic LAV-09, the offer LAV-07 at 64) are refused by offer_matches() as for any dealer.
    "picaros": {"name": "Los Pícaros", "buys": (), "sells_cards": True, "sells": ("rare",),
                "sell_anchor_mult": 1.6, "sell_anchor_over_floor": 0, "sell_step": 1, "example_bid": 5,
                "max_rounds": 40},
}
DEFAULT_DEALER = "chato"
DEALER_NAME = DEALERS[DEFAULT_DEALER]["name"]
SELL_RARITIES = DEALERS[DEFAULT_DEALER]["buys"]       # what the dealer buys from us
DEALER_SELLS_CARDS = DEALERS[DEFAULT_DEALER]["sells_cards"]
SELL_CARD_RARITIES = DEALERS[DEFAULT_DEALER]["sells"]   # the rarities of card the dealer sells us (buy targets)


def apply_dealer(dealer: str, sell_anchor: int | None = None, sell_step: int | None = None,
                 max_rounds: int | None = None) -> None:
    """Point every dealer-specific global at one row of DEALERS (plus the --sell-anchor/--sell-step/--max-rounds
    overrides: an explicit flag always wins over the dealer's default)."""
    global DEALER, DEALER_NAME, SELL_RARITIES, DEALER_SELLS_CARDS, SELL_CARD_RARITIES, SELL_ANCHOR_MULT
    global SELL_ANCHOR_OVER_FLOOR
    global SELL_ANCHOR_ABS, SELL_STEP, MAX_ROUNDS
    d = DEALERS[dealer]
    DEALER, DEALER_NAME = dealer, d["name"]
    SELL_RARITIES, DEALER_SELLS_CARDS = d["buys"], d["sells_cards"]
    SELL_CARD_RARITIES = d.get("sells", ("uncommon", "rare"))
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
    """Read the structure, not the words: the offer must be exactly the deal we negotiated (agent/dealer_client.py
    exact_offer): the one card for cash only, or our one copy for cash only. An extra card of ours riding on an offer for
    the right card is refused."""
    return exact_offer(o, side, item, asset_id)


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

def gate_numbers(target: dict) -> dict:
    """The two numbers a thread is judged by, logged at open: the limit the bot will trade at, and the ladder gate
    (buy: floor(book x multiplier); sell: ceil(book x multiplier x copy marginal)) next to our API value."""
    out = {"private": target.get("private")}
    out["ladder_value" if target["side"] == "buy" else "ladder_floor"] = target.get(
        "ladder_value" if target["side"] == "buy" else "ladder_floor")
    return out


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
    resumed = bool(resume)  # a resumed buy never goes on above what it may spend now (see below)
    if not resume:
        try:   # priced from the holdings of this moment, before a thread takes the dealer's only slot
            live0, why0 = live_limit(b.me(), target)
        except BazaarError as e:
            log("open_refused", item=item, side=side, code=e.code, msg=e.message)
            return {"result": "refused", "code": e.code}
        if live0 is None:
            log("open_refused", item=item, side=side, code=why0, msg="no limit can be computed from /api/me")
            return {"result": "refused", "code": why0}
        try:
            th = b.open_thread(DEALER, topic=topic)
        except BazaarError as e:
            log("open_refused", item=item, side=side, code=e.code, msg=e.message)
            return {"result": "refused", "code": e.code}
        tid = th["id"]
        log("open", thread=tid, side=side, item=item, value=value, **gate_numbers(target))

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
        if rounds.lost:  # no tick could be confirmed for MAX_FAILED_WAITS waits: decide nothing, close
            r = close("clock_lost", "clock_lost", waits=rounds.failed_waits, ours=ours, her=last_her)
            if r:
                return r
            continue
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
            log("resume", thread=tid, side=side, item=item, value=value, ours=ours, answered=answered,
                **gate_numbers(target))
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
            me_now = b.me()   # holdings and cash as of this decision: other bots trade the same cards while we talk
            cash = me_now["cash"] if side == "buy" else None
        except BazaarError as e:
            log("read_refused", thread=tid, code=e.code, msg=e.message, round=rounds.used)
            if spent:
                r = close("max_rounds", "max_rounds", ours=ours, her=her)
                if r:
                    return r
                continue
            rounds.wait()
            continue
        value_now, why_live = live_limit(me_now, target)   # the gate re-priced from the holdings just read
        if value_now is None:   # no holdings in the read, the copy is gone, or no multiplier: decide nothing, close
            r = close("limit_unknown", "walked_by_us", reason=why_live, ours=ours, her=her)
            if r:
                return r
            continue
        if limit_dropped(side, ours, value_now):   # our standing number is now on the wrong side: it could be accepted
            r = close("limit_dropped", "walked_by_us", ours=ours, limit=value_now, planned=value, her=her)
            if r:
                return r
            continue
        reservation = (min(value_now, cash - CASH_RESERVE) if side == "buy" else value_now)
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
        elif resumed and side == "buy" and ((ours is not None and ours > reservation) or reservation < 1):
            # 1b) a resumed buy whose earlier bid is above what we may spend now (cash, reserve, --cap), or with
            #     nothing spendable at all: close it, never a new number above the limit (or at or below zero)
            r = close("resume_over_limit", "walked_by_us", ours=ours, reservation=reservation)
            if r:
                return r
            continue
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
    """It settles on the next tick; "unsettled" if that cannot be confirmed (the caller stops the plan)."""
    return settle_trade(b, tid, price, log)


# ---------------------------------------------------------------- what to trade

def listed_sell_ids(only: list[str] | None, assets: list[dict] | None = None) -> list[int]:
    """The asset ids named as sell:<asset_id> in --only, in order. With `assets` (our cards), a sell:<REF> entry
    (sell:RET-09: a card bought a minute ago, whose asset id nobody knows yet) names the copy we would give up of
    that card: the highest serial, as the default spare rule does (it is the only copy when we hold one)."""
    out = []
    for x in only or []:
        k, _, v = x.partition(":")
        if k != "sell":
            continue
        if v.isdigit():
            out.append(int(v))
        elif v and assets is not None:
            copies = [a for a in assets if a.get("kind") == "card" and a.get("ref") == v]
            if copies:
                out.append(max(copies, key=lambda a: a["serial"])["id"])
    return out


def listed_sell_entries(only: list[str] | None) -> list[str]:
    """Every sell:<something> entry of --only: an asset id or a card ref."""
    return [x for x in only or [] if x.partition(":")[0] == "sell" and x.partition(":")[2]]


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
                if c["rarity"] not in SELL_CARD_RARITIES or c["id"] in held:
                    continue
                if only and c["id"] not in only:
                    continue
                top = buy_ceiling(me, c["id"], c["book"])   # floor(book x our set multiplier): the ladder gate
                if top is None:   # no multiplier for this set in /api/me: flagged, refused by main(), never priced
                    buys.append({"side": "buy", "item": c["id"], "name": c["name"], "book": c["book"], "value": 0,
                                 "private": 0, "ladder_value": None})
                    continue
                v = b.value(c["id"])["your_value"]
                limit = min(v, top)   # the API value can sit above the gate (page bonus); --cap only lowers further
                buys.append({"side": "buy", "item": c["id"], "name": c["name"], "book": c["book"],
                             "value": min(limit, cap) if cap else limit, "private": v, "ladder_value": top})
        buys.sort(key=lambda x: -x["private"])
    sells = []
    for ref, copies in held.items():
        if len(copies) > 1 and copies[0]["rarity"] in SELL_RARITIES:
            spare = max(copies, key=lambda a: a["serial"])  # keep the lowest serial
            gate = sell_ladder_floor(me, spare, len(copies))   # the copy we give up: 2nd 25 %, 3rd 10 % of a first
            sells.append({"side": "sell", "item": ref, "name": spare["name"], "asset_id": spare["id"],
                          "value": max(spare["your_value"] + 2, gate or 0), "private": spare["your_value"],
                          "ladder_floor": gate})
    if allow_single:  # only explicitly named ids; the floor is still that copy's private value + 2
        by_id = {a["id"]: a for copies in held.values() for a in copies}
        planned = {s["asset_id"] for s in sells}
        for aid in listed_sell_ids(only, me["assets"]):
            a = by_id.get(aid)
            if a is None or aid in planned or a["rarity"] not in SELL_RARITIES:
                continue
            gate = sell_ladder_floor(me, a, len(held[a["ref"]]))
            sells.append({"side": "sell", "item": a["ref"], "name": a["name"], "asset_id": aid,
                          "value": max(a["your_value"] + 2, gate or 0), "private": a["your_value"], "single": True,
                          "last": len(held[a["ref"]]) == 1, "ladder_floor": gate})
            planned.add(aid)
    plan = sells + buys  # sells first: they bring cash in
    if only:
        keys = set(only)
        plan = [p for p in plan if (p["side"] == "buy" and p["item"] in keys) or f"sell:{p.get('asset_id')}" in keys
                or (p["side"] == "sell" and f"sell:{p['item']}" in keys)]
    return plan


def apply_floor(plan: list[dict], floor: int | None) -> tuple[list[dict], list[dict]]:
    """--floor P replaces the default sell floor (private value + 2) with P for this run. P below our private value of
    a copy (hard minimum ceil(private)), or below its ladder floor (ceil(book x multiplier x copy marginal): a sale
    under it earns no ladder credit), is refused for that copy: it comes back in the second list and is never sold."""
    if floor is None:
        return plan, []
    kept, refused = [], []
    for p in plan:
        gate = p.get("ladder_floor")
        if p["side"] != "sell":
            kept.append(p)
        elif gate is None:   # no multiplier for the card's set: the ladder floor is unknown, so no floor is good enough
            refused.append(dict(p, why=f"--floor {floor}: /api/me has no multiplier for the {p['item'].split('-')[0]} "
                                       f"set, so the ladder floor cannot be computed"))
        elif int(floor) < math.ceil(p["private"]):
            refused.append(dict(p, why=f"--floor {floor} is below our private value {p['private']} "
                                       f"(minimum {math.ceil(p['private'])})"))
        elif int(floor) < gate:
            refused.append(dict(p, why=f"--floor {floor} is below the ladder floor {gate} "
                                       f"(book x our multiplier x copy marginal, rounded up): a sale under it "
                                       f"earns no ladder credit"))
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
    if args.allow_single and not listed_sell_entries(only):
        ap.error("--allow-single needs explicit --only sell:<asset_id> or sell:<REF> entries (nothing is auto-selected)")
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
    for entry in listed_sell_entries(only):
        ids = listed_sell_ids([entry], me["assets"])
        if not ids:   # a sell:<REF> for a card we do not hold (yet)
            out.append(f"  skip {entry}: we hold no copy of {entry.partition(':')[2]}")
            continue
        aid = ids[0]
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
        named = "" if entry.partition(":")[2].isdigit() else f" (asset {aid})"   # a sell:<REF> shows the copy it picked
        out.append(f"  skip {entry}{named} {(a or {}).get('ref', '')}: {why}")
    return out


def resume_command(args: argparse.Namespace, target: dict, tid: int) -> str:
    """The command that continues thread `tid` with every limit and override this run had, so following it can
    never take a price this run was not allowed to take (--cap, --reserve, --floor, anchors, steps, --max-bid...)."""
    spec = target["item"] if target["side"] == "buy" else f"sell:{target['asset_id']}"
    flags = [] if args.dealer == DEFAULT_DEALER else ["--dealer", args.dealer]
    flags += ["--only", spec]
    if args.allow_single and target["side"] == "sell":
        flags.append("--allow-single")
    for name, v in (("--cap", args.cap), ("--reserve", args.reserve), ("--floor", args.floor),
                    ("--sell-anchor", args.sell_anchor), ("--sell-step", args.sell_step), ("--anchor", args.anchor),
                    ("--step", args.step), ("--max-bid", args.max_bid), ("--max-rounds", args.max_rounds),
                    ("--max-defer-ticks", args.max_defer_ticks)):
        if v is not None:
            flags += [name, flag_value(v)]
    return command("agent/chato.py", flags + ["--resume", tid])


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
    plan, unpriced = refuse_unpriced(plan)   # a target whose own set has no multiplier: never traded on a guess
    plan, floor_refused = apply_floor(plan, args.floor)
    plan, cap_refused = refuse_caps(plan, args.cap)
    CASH_RESERVE = args.reserve
    print(f"{me['name']} cash={me['cash']} level={me['level']} deals={me['score'].get('deals')}")
    if not me.get("affinity"):   # without our multipliers no buy has a ladder ceiling: build_plan planned none
        print("WARNING: /api/me carries no set multipliers (affinity): every target is refused, the ladder gate is unknown.")
    for p in plan:
        gate = p.get("ladder_value") if p["side"] == "buy" else p.get("ladder_floor")
        print(f"  {p['side']:4} {p['item']:7} limit={p['value']:6.1f} private={p['private']:6.1f} "
              f"{'ladder' if p['side'] == 'buy' else 'ladder_floor'}={gate}  {p.get('name', '')}"
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
        for s in sell_skips(me, only, plan + floor_refused + unpriced, args.allow_single):
            print(s)
        for p in floor_refused:
            print(f"  REFUSED sell:{p['asset_id']} {p['item']}: {p['why']}")
    for p in cap_refused:   # printed by plan too, so the operator sees it before run
        print(f"  REFUSED buy:{p['item']}: {p['why']}")
    for p in unpriced:
        print(f"  REFUSED {p['side']}:{p['item']}: {p['why']}")
    if args.cmd == "plan":
        return
    if unpriced:   # no multiplier for the set of a named (or planned) card: no ladder gate, so no trade
        print(f"Not starting: {len(unpriced)} target(s) have no multiplier in /api/me, so no ladder gate can be computed.",
              flush=True)
        sys.exit(2)
    if floor_refused:  # never sell a copy below our private value: stop before any thread opens
        print(f"Not starting: {len(floor_refused)} sell(s) refused by --floor; raise it or drop those ids.", flush=True)
        sys.exit(2)
    if cap_refused:  # a cap above the ladder ceiling would let a deal close over value for no credit: stop here
        print(f"Not starting: {len(cap_refused)} buy(s) refused by --cap; lower it to the ladder ceiling or drop those "
              f"cards.", flush=True)
        sys.exit(2)
    if args.dealer != DEFAULT_DEALER:
        RUN = RunLog(args.dealer)  # logs/<dealer>/<date>.jsonl
    RUN.start(cash=me["cash"], level=me["level"], deals=me["score"].get("deals"), reserve=CASH_RESERVE, cap=args.cap,
              plan=[{k: p.get(k) for k in ("side", "item", "asset_id", "value", "private", "ladder_value", "ladder_floor")}
                    for p in plan[:args.max_deals + 3]],
              **({"dealer": DEALER, "allow_single": args.allow_single, "sell_anchor": SELL_ANCHOR_ABS,
                  "sell_step": SELL_STEP, "floor": args.floor} if extra else {}))
    done = 0
    stop = None   # (exit status, the one line for the operator) when the plan must stop
    buys_reached, buys_short = 0, []
    need = max(5, ANCHOR_ABS or 0)   # the least a buy needs above the reserve: never open below --anchor
    last_cash = me["cash"]
    for target in plan:
        if done >= args.max_deals:
            break
        me = b.me()
        last_cash = me["cash"]
        resuming = args.resume is not None and target is plan[0]
        if target["side"] == "buy":
            buys_reached += 1
            # the cash check is for a NEW conversation; a resumed one is read and resolved inside its limit
            if not resuming and me["cash"] - CASH_RESERVE < need:
                log("skip_cash", item=target["item"], cash=me["cash"], reserve=CASH_RESERVE, anchor=ANCHOR_ABS)
                buys_short.append(target["item"])
                continue   # e.g. before the grant: never open at a bid below --anchor and burn a dealer slot
        r = negotiate(b, target, False, resume=args.resume if resuming else None)
        if r.get("thread"):
            try:
                save_thread(b, r["thread"])  # full transcript, her words included
            except BazaarError as e:
                log("save_thread_failed", thread=r["thread"], code=e.code)
        if r.get("result") == "deal":
            done += 1
        if r.get("result") == "close_failed":  # the dealer's only conversation slot may still be held
            stop = (EXIT_CLOSE_FAILED, close_failed_line(r["thread"], DEALER_NAME,
                                                         resume_command(args, target, r["thread"])))
            log("stop", code="close_failed", thread=r["thread"])
            break
        if r.get("result") == "lock_timeout":
            stop = (EXIT_LOCK_TIMEOUT, lock_timeout_line(r["thread"], r.get("ticks", MAX_DEFER_TICKS)))
            log("stop", code="lock_timeout", thread=r["thread"])
            break
        if r.get("result") == "unsettled":  # an accept went out and may have traded: start nothing else
            stop = (EXIT_UNSETTLED, unsettled_line(r["thread"], r.get("price"), target["side"], target["item"],
                                                   target.get("asset_id")))
            log("stop", code="unsettled", thread=r["thread"])
            break
        if r.get("result") == "clock_lost":
            stop = (EXIT_CLOCK_LOST, clock_lost_line(r["thread"], MAX_FAILED_WAITS))
            log("stop", code="clock_lost", thread=r["thread"])
            break
        if r.get("code") in ("persona_quota", "cooloff", "locked"):
            log("stop", code=r["code"])
            break
    if not stop and buys_reached and len(buys_short) == buys_reached:  # say it instead of finishing silently
        stop = (EXIT_RESERVE, reserve_line(last_cash, CASH_RESERVE, need, len(buys_short)))
        log("reserve_blocks_buys", cash=last_cash, reserve=CASH_RESERVE, need=need, items=buys_short)
    if stop:  # the status line first: it must never depend on the account read below
        print(stop[1], flush=True)
    try:  # best effort: a failing read or log here must not hide the status
        me = b.me()
        s = me["score"]
        RUN.end(cash=me["cash"], level=me["level"], unlocked=me["unlocked"], deals=s.get("deals"),
                ladder_points=s.get("ladder_points"), score=s.get("score"), rank=s.get("rank"))
    except Exception as e:  # noqa: BLE001
        try:
            log("summary_failed", error=f"{type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001
            pass
    if stop:
        sys.exit(stop[0])


if __name__ == "__main__":
    main()
