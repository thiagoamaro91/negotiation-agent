"""Abuela Carmen negotiator (the L1 dealer at El Rastro).

Numbers are decided here, in code; the words around them are decoration (structure binds).

What the feed showed on Friday evening, before this was written:
- A team's first deal with her is a fixed "welcome" price (about 0.7 x list: 17 P for a pack or an uncommon,
  7 P for a common). It never moves, and a deal at her opening price does not count toward unlocking L2.
  So we take it once, on the item with the biggest private-value gain.
- After that she opens at about 1.15 x list, concedes ~4 P on her first move, then mirrors our step size.
  She only moves when we move; the same price twice earns nothing.
- When her patience runs out she names a final offer at her limit ("final": true): take it or she walks.

Plan per negotiated deal: anchor low enough that meeting in the middle would cross her limit, then step
1 P per round. Either she holds at her limit, accepts us, or names her limit as a final offer; in every case we
end at (or near) her limit, which is the full share of her price range, the thing the ladder score counts.

Usage (from the repo root):
    python3 agent/abuela.py plan          # show what we would trade and our private values
    python3 agent/abuela.py run           # work through the plan, one conversation at a time
    python3 agent/abuela.py run --only LAV-07,sell:39
    python3 agent/abuela.py run --only SAL-01 --reserve 200 --cap 10   # --cap only lowers our limit
    python3 agent/abuela.py run --only LAV-07 --resume 412              # continue a thread a run left open
When the round budget runs out we take her standing offer if it is inside our limit instead of closing on it.
Sell floors are rounded up before any price is built (a 19.5 floor never yields a binding 19).
Ladder value gate (agent/dealer_client.py): a deal on the wrong side of our private value earns no ladder credit, and the
API value can sit above that gate (a page-completing card carries the page bonus). So a buy's limit is clipped to
floor(book x our set multiplier), the multiplier read from /api/me, and `plan` prints it next to the API value as
ladder=N; a --cap above it is refused (plan prints REFUSED, run stops before any thread opens, exit 2). Sells are
graded against the copy we give up (100 % / 25 % / 10 %): the default floor is never below ceil(book x multiplier x
marginal).
`open` logs the API value and the gate next to the limit.
The gate is re-priced while a thread runs: other bots trade the same cards, so before every priced message and every
accept the bot re-reads /api/me and takes live_limit() (a buy that became our second copy is worth 25 %; a spare whose kept
copy left is a first copy). A limit that no longer allows the deal closes the thread (limit_dropped when our own standing
number is on the wrong side, limit_unknown when the holdings, the copy or the set multiplier cannot be read), and an offer
must be exactly the deal: no extra asset or type of ours, no second card, no cash coming back. A card whose set has no
multiplier is refused (REFUSED, exit 2), never priced on a guess.
`run` refuses to start (exit 0) while agent/duel.py holds results/duel.lock (one line: expiry, epoch seconds), and
re-checks the lock before every accept: while it is fresh the accept waits a tick (no round spent).
`run` exits 3 when the cash reserve (--reserve, default 280 P) blocked every buy, with one line saying how to pass it;
4 when a thread could not be closed (one line with the --resume command, carrying every limit of this run:
her only slot may still be held); 5 when the duel lock stayed fresh for --max-defer-ticks (default 60) and the
thread was closed without a deal; 6 when an accept went out but its settlement could not be confirmed (the plan
stops: the trade may have happened); 7 when the game clock could not be confirmed for 5 waits in a row (the thread
was closed). The status line is printed before the final account read, which is best effort.
`--resume` skips the cash check for a new conversation: the thread is read and resolved inside its limit (a resumed
buy whose earlier bid is above what may be spent now, or with nothing spendable, is closed).
The client never lets the SDK resend a write, counts a round only for a confirmed new tick, and waits through a paused
clock with one line a minute (agent/dealer_client.py).
Only ONE process per team may talk to Abuela at a time (one open conversation per dealer).
"""
from __future__ import annotations

import argparse
import json
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

RUN = RunLog("abuela")      # logs/abuela/<date>.jsonl, committed; keys are redacted
DEALER = "abuela"
CASH_RESERVE = 280          # keep the L2 venue bond (250 + 20) plus a little
DUEL_LOCK = ROOT / "results" / "duel.lock"   # written by agent/duel.py run while any of our duels is live


def duel_lock_fresh(path: Path = DUEL_LOCK) -> bool:
    """True while the duel bot holds the team's accept slot (first token of the file = expiry, epoch seconds)."""
    try:
        return float(path.read_text().split()[0]) > time.time()
    except (OSError, ValueError, IndexError):
        return False

ANCHOR_FRAC = 0.40          # first counter, as a share of her opening price (buying)
SELL_ANCHOR_MULT = 2.2      # first ask, as a multiple of her opening bid (selling)
STEP = 1                    # primas per round: small steps earn small steps, and run her patience out
WELCOME_MAX_FRAC = 0.75     # a first-deal price at or under 0.75 x book is her fixed welcome price
MAX_ROUNDS = 40


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
    "Buenas tardes, Abuela Carmen! What a beautiful stall. Could you do {p} P for it?",
    "Ay, Abuela, you are very kind. I am a young collector on a small budget: {p} P?",
    "Gracias for your patience, Abuela. I can stretch a little, {p} P.",
    "Your cards remind me of my grandmother's album. {p} P, por favor?",
    "I would treasure it, Abuela. {p} P is what I can manage today.",
    "Que amable! Let me add a little: {p} P.",
    "Abuela, you have the best stall in El Rastro. {p} P?",
    "One more small step from me: {p} P. Gracias, de verdad.",
]
SELL_LINES = [
    "Buenas tardes, Abuela Carmen! I have a spare for your boxes. Would {p} P be fair?",
    "Ay, Abuela, it is in perfect condition, look. {p} P?",
    "Gracias, Abuela. For you I can come down a little: {p} P.",
    "Some child at El Rastro will love it. {p} P, por favor?",
    "You are very kind, Abuela. {p} P and it is yours.",
    "A small step from me: {p} P. Que tenga un buen dia!",
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


# ---------------------------------------------------------------- one negotiation

def gate_numbers(target: dict) -> dict:
    """The two numbers a thread is judged by, logged at open: our API value and the ladder gate (buy: floor(book x
    multiplier); sell: ceil(book x multiplier x copy marginal)); `value` next to them is the limit the bot trades at."""
    key = "ladder_value" if target["side"] == "buy" else "ladder_floor"
    return {"private": target.get("private"), key: target.get(key)}


def negotiate(b: Bazaar, target: dict, first_deal: bool, resume: int | None = None) -> dict:
    side, item, value = target["side"], target["item"], target["value"]
    asset_id = target.get("asset_id")
    topic = {"buy": {"card": item}} if side == "buy" else {"sell": {"assets": [asset_id]}}
    ours: int | None = None
    said = 0
    last_her = None
    answered = None  # id of her offer we last countered
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
        log("open", thread=tid, side=side, item=item, value=value, welcome=first_deal, **gate_numbers(target))

    rounds = Rounds(b, MAX_ROUNDS, MAX_DEFER_TICKS)  # a round is a confirmed tick; deferrals and pauses are free

    def close(event: str, result: str, **info) -> dict | None:
        """Close for `result`. None: the close was refused and the loop decides again on a fresh read."""
        if try_close(b, tid, log, rounds, event):
            log(event, thread=tid, **info)
            return {"result": result, "thread": tid}
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
                if msgs[-1].get("sender") != DEALER:  # our number is the latest word: wait for her answer
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
        # sells: the floor rounded UP before any price is built (a 19.5 floor must never yield a binding 19)
        reservation = (min(value_now, cash - CASH_RESERVE) if side == "buy" else int(-(-value_now // 1)))

        def good(p: int) -> bool:
            return p <= reservation if side == "buy" else p >= reservation

        why = None
        # 1) the welcome price (~0.7 x book) never moves and is far below our value: take it at once.
        #    Capped at WELCOME_MAX_FRAC x book so a normal opening is never mistaken for it.
        if first_deal and side == "buy" and good(her) and her <= WELCOME_MAX_FRAC * target["book"]:
            why = "welcome"
        # 2) her last word: take it if it is still a good deal, else walk
        elif final:
            if not good(her):
                r = close("walk", "walked_by_us", price=her, reservation=reservation)
                if r:
                    return r
                continue
            why = "final"
        # 2b) a resumed buy whose earlier bid is above what we may spend now (cash, reserve, --cap), or with
        #     nothing spendable at all: close it, never a new number above the limit (or at or below zero)
        elif resumed and side == "buy" and ((ours is not None and ours > reservation) or reservation < 1):
            r = close("resume_over_limit", "walked_by_us", ours=ours, reservation=reservation)
            if r:
                return r
            continue
        # 3) the round budget is spent: never close on a standing offer inside our reservation
        elif spent:
            if not good(her):
                r = close("max_rounds", "max_rounds", ours=ours, her=her)
                if r:
                    return r
                continue
            why = "budget_end"
        # 4) she has not answered our last number yet: never bid against ourselves
        elif o["id"] == answered:
            rounds.wait()
            continue
        else:
            # 5) our next number: low anchor, then STEP per round toward her
            if ours is None:
                nxt = int(her * ANCHOR_FRAC) if side == "buy" else int(round(her * SELL_ANCHOR_MULT))
            else:
                nxt = ours + STEP if side == "buy" else ours - STEP
            nxt = int(min(nxt, reservation)) if side == "buy" else int(max(nxt, reservation))
            # 6) she is already at (or past) our next number: take her price
            crossed = her <= nxt if side == "buy" else her >= nxt
            if crossed and good(her):
                why = "crossed"
            elif ours is not None and nxt == ours:  # pinned at our reservation: wait for her final offer
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

def build_plan(b: Bazaar, me: dict, only: list[str] | None, cap: float | None = None) -> list[dict]:
    """Buys: cards Abuela sells (released commons/uncommons) that complete our best pages, ranked by value.
    Sells: our duplicate copies, which are worth only 25% to us."""
    catalog = b.catalog()
    released = {s["id"] for s in catalog["sets"] if s["released"]}
    held = {}
    for a in me["assets"]:
        if a["kind"] == "card":
            held.setdefault(a["ref"], []).append(a)
    buys = []
    for s in catalog["sets"]:
        if s["id"] not in released:
            continue
        for c in s["cards"]:
            if c["rarity"] not in ("common", "uncommon") or c["id"] in held:
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
    buys.sort(key=lambda x: -(x["value"] - 0.8 * x["book"]))
    sells = []
    for ref, copies in held.items():
        if len(copies) > 1 and copies[0]["rarity"] in ("common", "uncommon"):
            spare = max(copies, key=lambda a: a["serial"])  # keep the lowest serial
            gate = sell_ladder_floor(me, spare, len(copies))   # the copy we give up: 2nd 25 %, 3rd 10 % of a first
            sells.append({"side": "sell", "item": ref, "name": spare["name"], "asset_id": spare["id"],
                          "value": max(spare["your_value"] + 2, gate or 0), "private": spare["your_value"],
                          "ladder_floor": gate})
    plan = []
    for i in range(max(len(buys), len(sells))):  # alternate so cash stays above the reserve
        if i < len(buys):
            plan.append(buys[i])
        if i < len(sells):
            plan.append(sells[i])
    if only:
        keys = set(only)
        plan = [p for p in plan if p["item"] in keys or f"sell:{p.get('asset_id')}" in keys]
    return plan


def resume_command(args: argparse.Namespace, target: dict, tid: int) -> str:
    """The command that continues thread `tid` with every limit this run had (--cap and --reserve above all), so
    following it can never take a price this run was not allowed to take."""
    spec = target["item"] if target["side"] == "buy" else f"sell:{target['asset_id']}"
    flags = ["--only", spec, "--reserve", args.reserve]
    if args.cap is not None:
        flags += ["--cap", flag_value(args.cap)]
    return command("agent/abuela.py", flags + ["--max-defer-ticks", args.max_defer_ticks, "--resume", tid])


def on_wait(kind: str, clock: dict, waited: float) -> None:
    """Called by the client when a wait finds the game paused, the doors closed or the clock unreadable, then once a
    minute while it lasts: one line for the operator, one log event."""
    log("clock_wait", kind=kind, tick=clock.get("tick"), waited=int(waited))
    print(f"waiting: {kind.replace('_', ' ')} at tick {clock.get('tick', '?')}, {int(waited)} s so far "
          "(no round is spent while waiting)", flush=True)


def main() -> None:
    global CASH_RESERVE, MAX_DEFER_TICKS
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--only", default="", help="comma list of card refs and/or sell:<asset_id>")
    ap.add_argument("--max-deals", type=int, default=6)
    ap.add_argument("--reserve", type=int, default=CASH_RESERVE, help="cash we never spend below")
    ap.add_argument("--cap", type=float, default=None, help="most we pay for any card (only lowers our value)")
    ap.add_argument("--resume", type=int, default=None,
                    help="thread id to continue for the first target (e.g. after a close that failed)")
    ap.add_argument("--max-defer-ticks", type=int, default=MAX_DEFER_TICKS,
                    help="ticks an accept may wait on the duel lock in one thread before the thread is closed "
                         f"(exit {EXIT_LOCK_TIMEOUT}; default {MAX_DEFER_TICKS})")
    args = ap.parse_args()
    if args.max_defer_ticks < 1:
        ap.error("--max-defer-ticks must be >= 1")
    MAX_DEFER_TICKS = args.max_defer_ticks
    if args.cmd == "run" and duel_lock_fresh():
        print(f"WARNING: {DUEL_LOCK.relative_to(ROOT)} is fresh: the duel bot holds the team's accept slot. "
              "Not starting Abuela; try again after the duel wave.", flush=True)
        return
    CASH_RESERVE = args.reserve
    # wait_on_tick=False: a refused write comes back to negotiate(), which re-reads and decides again (never resent)
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"],
               wait_on_tick=False)
    b.on_wait = on_wait
    me = b.me()
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    plan = build_plan(b, me, only, args.cap)
    plan, unpriced = refuse_unpriced(plan)   # a target whose own set has no multiplier: never traded on a guess
    plan, cap_refused = refuse_caps(plan, args.cap)
    print(f"{me['name']} cash={me['cash']} level={me['level']} deals={me['score'].get('deals')}")
    if not me.get("affinity"):   # without our multipliers no buy has a ladder ceiling: build_plan planned none
        print("WARNING: /api/me carries no set multipliers (affinity): every target is refused, the ladder gate is unknown.")
    for p in plan:
        gate = p.get("ladder_value") if p["side"] == "buy" else p.get("ladder_floor")
        print(f"  {p['side']:4} {p['item']:7} value={p['value']:6.1f} private={p.get('private', p['value']):6.1f} "
              f"{'ladder' if p['side'] == 'buy' else 'ladder_floor'}={gate}  {p.get('name', '')}")
    for p in cap_refused:   # printed by plan too, so the operator sees it before run
        print(f"  REFUSED buy:{p['item']}: {p['why']}")
    for p in unpriced:
        print(f"  REFUSED {p['side']}:{p['item']}: {p['why']}")
    print(f"reserve={CASH_RESERVE} (spendable {me['cash'] - CASH_RESERVE} P) cap={args.cap}")
    if args.cmd == "plan":
        return
    if cap_refused:  # a cap above the ladder ceiling would let a deal close over value for no credit: stop here
        print(f"Not starting: {len(cap_refused)} buy(s) refused by --cap; lower it to the ladder ceiling or drop those "
              f"cards.", flush=True)
        sys.exit(2)
    if unpriced:   # no multiplier for the set of a named (or planned) card: no ladder gate, so no trade
        print(f"Not starting: {len(unpriced)} target(s) have no multiplier in /api/me, so no ladder gate can be computed.",
              flush=True)
        sys.exit(2)
    RUN.start(cash=me["cash"], level=me["level"], deals=me["score"].get("deals"), reserve=CASH_RESERVE, cap=args.cap,
              plan=[{k: p.get(k) for k in ("side", "item", "asset_id", "value", "private", "ladder_value", "ladder_floor")}
                    for p in plan[:args.max_deals + 3]])
    done = 0
    stop = None   # (exit status, the one line for the operator) when the plan must stop
    buys_reached, buys_short = 0, []
    need = 5   # the least a buy needs above the reserve
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
                log("skip_cash", item=target["item"], cash=me["cash"])
                buys_short.append(target["item"])
                continue
        first = (me["score"].get("deals") or 0) == 0
        r = negotiate(b, target, first, resume=args.resume if resuming else None)
        if r.get("thread"):
            try:
                save_thread(b, r["thread"])  # full transcript, her words included
            except BazaarError as e:
                log("save_thread_failed", thread=r["thread"], code=e.code)
        if r.get("result") == "deal":
            done += 1
        if r.get("result") == "close_failed":  # Abuela's only conversation slot may still be held
            stop = (EXIT_CLOSE_FAILED, close_failed_line(r["thread"], "Abuela",
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
