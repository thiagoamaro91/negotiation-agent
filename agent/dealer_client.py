"""Shared pieces of the dealer bots (agent/abuela.py, agent/chato.py): the client they build, the round accounting,
the guarded writes and the operator messages.

DealerBazaar is the kit client (kit/bazaar_sdk.py, unchanged) with three changes:
- Writes (every non-GET call) are never retried by the SDK: a refused accept, message or close, rate_limited
  included, raises at once and comes back to the bot, which waits a tick, re-checks the duel lock, re-reads the
  thread and decides again. (wait_on_tick=False alone is not enough: the SDK still retries a rate_limited write,
  and that resend could land after the duel lock turned fresh or on an offer the dealer replaced.) Reads keep the
  SDK's retries.
- Clock reads use a short timeout and no SDK retries, so the bound on an unreadable clock is real wall-clock time.
- wait_tick() returns a clock only once a new tick has started with the clock running and the doors open. While the
  game is paused, the doors are closed, or the clock cannot be read, it keeps polling and reports through on_wait
  once a minute. It returns {} when no new tick could be confirmed (clock unreadable for CLOCK_GIVE_UP seconds, or
  a running clock whose tick does not move, also reported once a minute as clock_stuck): a bot counts a round only
  for a confirmed new tick. It never raises.

Rounds keeps one conversation's budget: a round is a confirmed tick; lock deferrals are counted apart and bounded;
once the budget is spent the bot still makes a fresh decision each tick, with at most END_ACCEPTS accept attempts.
Rounds.wait() blocks until a tick is confirmed, so no decision or write follows an unconfirmed wait; after
MAX_FAILED_WAITS unconfirmed waits in a row the clock counts as lost and the bot closes the thread.
settle_trade() follows an accepted offer to its settlement and reports "unsettled" when it cannot confirm it.
"""
from __future__ import annotations

import math
import shlex
import time

from bazaar_sdk import Bazaar, BazaarError

PAUSE_POLL = 3.0        # seconds between clock reads while paused, doors closed or unreadable (Sunday ticks are 15 s)
CLOCK_TIMEOUT = 5.0     # seconds per clock read; no SDK retries on it
CLOCK_GIVE_UP = 60.0    # seconds of unreadable clock after which wait_tick returns {} (no round is counted)
REPORT_EVERY = 60.0     # while waiting on a pause or an unreadable clock: one on_wait report per minute
MAX_TICK_SLEEP = 65.0   # never trust a next_tick_in above this
STUCK_POLLS = 120       # running clock whose tick never moves: return {} after ~30 s of 0.25 s polls

END_ACCEPTS = 2         # accept attempts once the round budget is spent (each one after a fresh read)
CLOSE_TRIES = 3         # refused closes (each followed by a fresh read and decision) before reporting close_failed
MAX_FAILED_WAITS = 5    # unconfirmed waits in a row (about 1 min each) before the clock counts as lost
SETTLE_TRIES = 8        # waits to see an accepted offer settle (it settles on the next tick) before "unsettled"
MAX_DEFER_TICKS = 60    # default for --max-defer-ticks: ticks an accept may wait on the duel lock in one thread

ACCEPTED, DEFERRED, REFUSED = "accepted", "deferred", "refused"

# exit statuses of `run`: 0 ok, 1 crash, 2 usage or --floor refusal, and these six
EXIT_RESERVE = 3        # every buy was skipped because cash is under the reserve
EXIT_CLOSE_FAILED = 4   # a thread could not be closed: it still holds the dealer's only conversation slot
EXIT_LOCK_TIMEOUT = 5   # the duel lock stayed fresh for --max-defer-ticks: the thread was closed without a deal
EXIT_UNSETTLED = 6      # an accept went out but its settlement could not be confirmed: the plan stopped
EXIT_CLOCK_LOST = 7     # the game clock could not be confirmed for MAX_FAILED_WAITS waits: the thread was closed
EXIT_COOLOFF = 8        # a dealer is cooling off and the wait to its until_tick was refused or ran out: nothing was bought
MAX_WAIT_TICKS = 120    # default for --max-wait-ticks: longest cooloff (in confirmed ticks) a run waits out before retrying


def clock_running(c: dict) -> bool:
    """Same test as agent/rastro_seller.py: not paused, and doors open (a clock without a doors field counts as open)."""
    return not c.get("paused") and c.get("doors", "open") == "open"


def seconds_to_tick(c: dict, default: float = 1.0) -> float:
    """Seconds until the next tick from a clock read; tolerates a null or missing next_tick_in."""
    for k in ("next_tick_in", "tick_seconds"):
        try:
            v = float(c.get(k))
        except (TypeError, ValueError):
            continue
        if v >= 0:
            return min(v, MAX_TICK_SLEEP)
    return default


class DealerBazaar(Bazaar):
    """The kit client for a dealer bot: writes never retried by the SDK, bounded clock reads, a pause-safe wait."""

    def __init__(self, url: str, key: str, *, wait_on_tick: bool = False, **kw):
        super().__init__(url, key, wait_on_tick=wait_on_tick, **kw)
        # optional callback(kind, clock, waited_seconds), kind "paused", "doors_closed", "clock_unreadable" or
        # "clock_stuck": called when a wait first finds the game not running, then once per REPORT_EVERY seconds
        self.on_wait = None
        self._stuck_since = self._stuck_told = None  # a running clock that does not move, across successive waits

    def _call(self, method, path, body=None, query=None):
        if method == "GET":
            return super()._call(method, path, body, query)
        retries, self.retries = self.retries, 0   # a write is sent once; the bot decides what to do on a refusal
        try:
            return super()._call(method, path, body, query)
        finally:
            self.retries = retries

    def read_clock(self) -> dict | None:
        """One clock read, short timeout, no SDK retries. None if it failed."""
        timeout, retries = self.timeout, self.retries
        self.timeout, self.retries = CLOCK_TIMEOUT, 0
        try:
            c = self.clock()
            return c if isinstance(c, dict) else None
        except BazaarError:
            return None
        finally:
            self.timeout, self.retries = timeout, retries

    def wait_tick(self) -> dict:
        """The clock of a new tick (running, doors open), or {} if no new tick could be confirmed. Never raises."""
        start, naps = None, 0
        failing_since = waiting_since = told_at = None
        while True:
            c = self.read_clock()
            now = time.monotonic()
            if c is None or not clock_running(c):
                kind = "clock_unreadable" if c is None else ("paused" if c.get("paused") else "doors_closed")
                if waiting_since is None:
                    waiting_since = now
                if told_at is None or now - told_at >= REPORT_EVERY:
                    told_at = now
                    if self.on_wait is not None:
                        self.on_wait(kind, c or {}, now - waiting_since)
                if c is None:
                    failing_since = now if failing_since is None else failing_since
                    if now - failing_since >= CLOCK_GIVE_UP:
                        return {}
                else:
                    failing_since = None
                    if start is None:
                        start = c.get("tick")
                naps = 0  # after the wait, sleep the real time to the next tick again
                time.sleep(PAUSE_POLL)
                continue
            failing_since = waiting_since = told_at = None
            tick = c.get("tick")
            if start is None:
                start = tick
            elif tick is not None and tick > start:
                self._stuck_since = self._stuck_told = None
                return c
            if naps >= STUCK_POLLS:  # the clock runs but its tick does not move: tell the operator, spend nothing
                if self._stuck_since is None:
                    self._stuck_since = now
                if self._stuck_told is None or now - self._stuck_told >= REPORT_EVERY:
                    self._stuck_told = now
                    if self.on_wait is not None:
                        self.on_wait("clock_stuck", c, now - self._stuck_since)
                return {}
            time.sleep(seconds_to_tick(c) + 0.15 if naps == 0 else 0.25)
            naps += 1


class Rounds:
    """Round accounting for one conversation.

    used: rounds spent, one per confirmed new tick (a wait that could not confirm a tick spends nothing).
    deferred: ticks spent waiting on the duel lock (they cost no round; bounded by max_defer).
    end_tries: accept attempts refused after the budget was spent (bounded by END_ACCEPTS).
    close_refusals: refused closes in this thread (bounded by CLOSE_TRIES).
    lost: MAX_FAILED_WAITS waits in a row could not confirm a tick; the caller closes the thread. A later confirmed
    tick (for instance while that close is refused) clears it, so the bot decides again on a fresh read."""

    def __init__(self, b, max_rounds: int, max_defer: int = MAX_DEFER_TICKS):
        self.b, self.max_rounds, self.max_defer = b, int(max_rounds), int(max_defer)
        self.used = self.deferred = self.end_tries = self.close_refusals = self.failed_waits = 0
        self.lost = False

    def spent(self) -> bool:
        return self.used >= self.max_rounds

    def wait(self, free: bool = False) -> bool:
        """Block until a new tick is confirmed, and spend a round for it unless the wait is free. An unconfirmed wait
        is never followed by a decision or a write: it waits again. False once MAX_FAILED_WAITS waits in a row
        could not confirm a tick (self.lost): the caller must close the thread instead of deciding anything."""
        while True:
            c = self.b.wait_tick() or {}
            if c.get("tick") is not None:
                self.failed_waits = 0
                self.lost = False  # the clock is back: decide on a fresh read again (an in-limit final may stand)
                if not free:
                    self.used += 1
                return True
            self.failed_waits += 1
            if self.failed_waits >= MAX_FAILED_WAITS:
                self.lost = True
                return False

    def defer(self) -> None:
        """The duel lock is fresh: wait a tick without spending a round."""
        if self.wait(free=True):
            self.deferred += 1

    def lock_timed_out(self) -> bool:
        return self.deferred >= self.max_defer


def guarded_accept(b, offer_id: int, lock_fresh, log, **ctx) -> str:
    """One accept attempt. DEFERRED: the duel lock is fresh, nothing was sent (logged accept_deferred_lock).
    REFUSED: the server said no (logged accept_refused with its code); it is never resent from here, the caller waits
    a tick, re-checks the lock, re-reads the thread and decides again. ACCEPTED: it settles on the next tick."""
    if lock_fresh():
        log("accept_deferred_lock", offer=offer_id, **ctx)
        return DEFERRED
    try:
        b.accept(offer_id)
    except BazaarError as e:
        log("accept_refused", offer=offer_id, code=e.code, msg=e.message, **ctx)
        return REFUSED
    return ACCEPTED


def try_close(b, tid: int, log, rounds: Rounds, why: str) -> bool:
    """One close attempt. On a refusal it logs close_refused, counts it, waits one tick without spending a round and
    returns False: the caller re-reads the thread and decides again (the dealer's offer may have changed)."""
    try:
        b.close_thread(tid)
        return True
    except BazaarError as e:
        rounds.close_refusals += 1
        log("close_refused", thread=tid, code=e.code, msg=e.message, why=why, attempt=rounds.close_refusals)
    rounds.wait(free=True)
    return False


def settle_trade(b, tid: int, price: int, log) -> dict:
    """Follow an accepted offer to its settlement (the next tick). Only a confirmed tick followed by a good read
    counts: a wait that could not confirm a tick, or a read that failed, proves nothing. Result "unsettled" after
    SETTLE_TRIES waits without seeing the thread leave "open": the caller must stop, the trade may have happened."""
    for tries in range(1, SETTLE_TRIES + 1):
        c = b.wait_tick() or {}
        if c.get("tick") is None:
            continue
        try:
            t = b.thread(tid)
        except BazaarError as e:
            log("read_refused", thread=tid, code=e.code, msg=e.message)
            continue
        if t.get("status") != "open":
            log("result", thread=tid, status=t.get("status"), price=price, reason=t.get("closed_reason"))
            return {"result": t.get("status"), "thread": tid, "price": price}
    log("unsettled", thread=tid, price=price, tries=SETTLE_TRIES)
    return {"result": "unsettled", "thread": tid, "price": price}


def command(script: str, flags: list) -> str:
    """A shell command line: python3 <script> run <flags...>, each value quoted for the shell."""
    return " ".join(["python3", script, "run"] + [shlex.quote(str(f)) for f in flags])


def flag_value(v):
    """A flag value as the operator would type it: 50.0 prints as 50."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


def unsettled_line(tid: int, price: int, side: str, item: str, asset_id: int | None = None) -> str:
    """The one line run prints when an accept went out but its settlement could not be confirmed (EXIT_UNSETTLED).
    It names the planned trade (side and card, and the copy for a sell) so the operator knows what to check."""
    what = f"{side} {item}" + (f", asset {asset_id}" if side == "sell" and asset_id is not None else "")
    return (f"Thread {tid} ({what}): our accept at {price} P went out but its settlement could not be confirmed (thread "
            f"unreadable or clock not advancing). The plan was stopped so no further trade can start; check thread "
            f"{tid} and our holdings before running again.")


def clock_lost_line(tid: int, waits: int) -> str:
    """The one line run prints when the game clock was lost and the thread was closed (EXIT_CLOCK_LOST)."""
    return (f"Thread {tid} closed without a deal: the game clock could not be confirmed for {waits} waits in a row "
            f"(unreadable or not advancing). Check the game before running again.")


def reserve_line(cash: int, reserve: int, need: int, skipped: int, team_reserve: int = 280) -> str:
    """The one line run prints when the cash reserve blocked every buy (it then exits with EXIT_RESERVE)."""
    room = cash - need
    how = (f"to spend below it on purpose, rerun with --reserve N (N at most {room})" if room >= 0
           else f"even --reserve 0 leaves less than the {need} P a buy needs")
    return (f"No buy started: {skipped} buy(s) skipped because cash {cash} P minus the {reserve} P reserve leaves "
            f"{cash - reserve} P, under the {need} P a buy needs. The {team_reserve} P default is the team rule "
            f"(level-2 bond); {how}.")


def close_failed_line(tid: int, dealer_name: str, command: str) -> str:
    """The one line run prints when a thread could not be closed (it then exits with EXIT_CLOSE_FAILED)."""
    return (f"Thread {tid} with {dealer_name} could not be closed and may still be open, holding the dealer's only "
            f"conversation slot. Continue it with: {command}")


def lock_timeout_line(tid: int, ticks: int) -> str:
    """The one line run prints when the duel lock outlasted --max-defer-ticks (it then exits with EXIT_LOCK_TIMEOUT)."""
    return (f"Thread {tid} closed without a deal: the duel lock stayed fresh for {ticks} ticks, so the accept never "
            f"went out. Run again after the duel wave, or raise --max-defer-ticks.")


# ---------------------------------------------------------------- the ladder value gate
#
# A dealer deal on the wrong side of our private value earns no ladder credit (docs/findings.md, "Ladder value gate"):
# a buy above, or a sale below, what the card is worth to us. The API value (/api/me/value, /api/me) can sit ABOVE the
# gate for a buy (a card that completes a page carries the page bonus: LAT-09 read 77 before LAT-03 and 149.9 after),
# so a limit of min(API value, --cap) let Friday's LAT-06 and LAT-07 close over value for nothing. The gate the bots
# enforce is book x our set multiplier (from /api/me "affinity", never hardcoded), first copy for a buy; a sale is
# graded against the copy we give up: 100 % for the only copy, 25 % for the second, 10 % for the third.

BOOK_BY_RARITY = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}   # fallback: the catalog wins
COPY_MARGINALS = (1.0, 0.25, 0.1)   # catalog "values.copy_marginals": what the 1st, 2nd and 3rd copy of a card are worth


def card_set(ref: str) -> str:
    return str(ref).split("-")[0]


def _round6(x: float) -> float:
    return round(x, 6)   # 10 x 1.1 reads 11.000000000000002: never let float noise move a floor or a ceiling


def ladder_ceiling(book, multiplier) -> int | None:
    """The most a first copy may cost for the ladder to credit it: floor(book x set multiplier). None when the
    multiplier is unknown (the caller must then refuse, never guess)."""
    if not book or multiplier is None:
        return None
    return int(math.floor(_round6(float(book) * float(multiplier))))


def ladder_floor(book, multiplier, marginal: float = 1.0) -> int | None:
    """The least a copy may be sold for: ceil(book x set multiplier x the marginal of the copy we give up)."""
    if not book or multiplier is None:
        return None
    return int(math.ceil(_round6(float(book) * float(multiplier) * float(marginal))))


def copy_marginal(copies_held: int, marginals=COPY_MARGINALS) -> float:
    """What the copy we sell is worth, as a share of a first copy, when we hold `copies_held` of the card."""
    return float(marginals[max(0, min(int(copies_held), len(marginals)) - 1)])


def buy_ceiling(me: dict, ref: str, book) -> int | None:
    """floor(book x our multiplier for the card's set), from the affinities of /api/me; None if /api/me has none."""
    return ladder_ceiling(book, (me.get("affinity") or {}).get(card_set(ref)))


def sell_ladder_floor(me: dict, asset: dict, copies_held: int, book=None, marginals=COPY_MARGINALS) -> int | None:
    """ceil(book x multiplier x marginal) for the copy `asset` we would give up; None if the affinity is unknown."""
    book = book or BOOK_BY_RARITY.get(asset.get("rarity"))
    mult = (me.get("affinity") or {}).get(asset.get("set") or card_set(asset.get("ref", "")))
    return ladder_floor(book, mult, copy_marginal(copies_held, marginals))


def refuse_caps(plan: list, cap) -> tuple[list, list]:
    """--cap above the ladder ceiling of a buy is refused for that buy (it comes back in the second list with the
    reason; run stops before any thread opens). A cap at or below the ceiling, no cap, and sells are untouched."""
    if cap is None or cap <= 0:
        return plan, []
    kept, refused = [], []
    for p in plan:
        top = p.get("ladder_value")
        if p["side"] == "buy" and top is not None and cap > top:
            refused.append(dict(p, why=f"--cap {flag_value(cap)} is above the ladder ceiling {top} "
                                       f"(book {flag_value(p.get('book'))} x our {card_set(p['item'])} multiplier, floored): "
                                       f"a deal above it earns no ladder credit"))
        else:
            kept.append(p)
    return kept, refused


# ---------------------------------------------------------------- the gate, re-read while a thread runs

def refuse_unpriced(plan: list) -> tuple[list, list]:
    """A target whose own set has no multiplier in /api/me has no ladder gate (build_plan flags it with a None
    ladder_value / ladder_floor): it is refused, never traded on a guess. The second list carries the reason."""
    kept, refused = [], []
    for p in plan:
        gate = p.get("ladder_value") if p["side"] == "buy" else p.get("ladder_floor")
        if gate is None:
            refused.append(dict(p, why=f"/api/me has no multiplier for the {card_set(p['item'])} set: the ladder gate "
                                       f"cannot be computed, so nothing is traded on it"))
        else:
            kept.append(p)
    return kept, refused


def live_limit(me: dict, target: dict, marginals=COPY_MARGINALS) -> tuple:
    """The limit this target may trade at RIGHT NOW, from a fresh /api/me read: (limit, "") or (None, reason).

    The plan was priced from the holdings of plan time, but other bots (Abuela, Chato, Pilar, Pícaros run at once) buy
    and sell the same cards while a thread is open: a buy that has become our second copy is worth 25 % of the first,
    the spare we offer Pilar becomes a first copy (worth the whole value) when the copy we kept leaves. So every
    decision re-prices from the holdings it reads:
      buy:  min(planned limit, floor(book x multiplier x marginal of the copy we would then hold))
      sell: max(planned floor, ceil(API value of the copy now), ceil(book x multiplier x marginal of the copy we give up))
    A read without holdings, a copy we no longer own, or a set without a multiplier is (None, reason): the caller
    closes the thread."""
    assets = me.get("assets")
    if not isinstance(assets, list):
        return None, "no_holdings"
    item = target["item"]
    held = [a for a in assets if isinstance(a, dict) and a.get("kind") == "card" and a.get("ref") == item]
    mult = (me.get("affinity") or {}).get(card_set(item))
    if mult is None:
        return None, "no_multiplier"
    if target["side"] == "buy":
        top = ladder_ceiling(target.get("book"), mult * copy_marginal(len(held) + 1, marginals))
        if top is None:
            return None, "no_book"
        return min(target["value"], top), ""
    mine = [a for a in held if a.get("id") == target.get("asset_id")]
    if not mine:
        return None, "asset_gone"
    gate = sell_ladder_floor(me, mine[0], len(held), marginals=marginals)
    if gate is None:
        return None, "no_multiplier"
    now = math.ceil(_round6(float(mine[0].get("your_value") or 0)))
    return max(target["value"], gate, now), ""


def limit_dropped(side: str, ours, limit) -> bool:
    """True when our own standing number is already on the wrong side of the limit just recomputed (a bid above it, an
    ask under it): the dealer could still accept it, so the thread must be closed, not just no longer raised."""
    if ours is None:
        return False
    return ours > int(limit) if side == "buy" else ours < int(-(-limit // 1))


def exact_offer(o: dict, side: str, item: str, asset_id) -> bool:
    """The dealer's offer is exactly the deal we negotiated and nothing more. Buy: he gives that one card (an asset of
    that ref or the type card:<ref>) and wants cash only, no asset and no type of ours. Sell: he wants exactly our
    one copy and gives cash only. An extra card of ours riding on an offer for the right card is refused."""
    give, want = o.get("give") or {}, o.get("want") or {}

    def lst(side_):
        return [list(side_.get("assets") or []), list(side_.get("types") or [])]
    g_assets, g_types = lst(give)
    w_assets, w_types = lst(want)
    if side == "buy":
        refs = [a.get("ref") if isinstance(a, dict) else None for a in g_assets] + [str(t).split(":", 1)[-1] for t in g_types]
        return (refs == [item] and not give.get("cash") and bool(want.get("cash")) and not w_assets and not w_types)
    ids = [a.get("id") if isinstance(a, dict) else a for a in w_assets]
    return (ids == [asset_id] and not w_types and not want.get("cash") and bool(give.get("cash"))
            and not g_assets and not g_types)


# ---------------------------------------------------------------- a cooloff is waited out, not given up on

def until_tick_of(e) -> int | None:
    """The until_tick a cooloff refusal carries (top level of the error body, or inside a details object)."""
    extra = getattr(e, "extra", None) or {}
    for src in (extra, extra.get("details") if isinstance(extra.get("details"), dict) else {}):
        v = src.get("until_tick")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def until_epoch(hhmm: str | None, now: float | None = None) -> float | None:
    """--until HH:MM (local wall time, as agent/duel.py reads it) as epoch seconds of today; None when not given."""
    if not hhmm:
        return None
    h, m = (int(x) for x in hhmm.split(":"))
    t = time.localtime(time.time() if now is None else now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, 0, 0, 0, -1))


def cooloff_line(item: str, until_tick, tick, why: str, max_wait_ticks: int) -> str:
    """The one line run prints when a cooloff could not be waited out (it then exits with EXIT_COOLOFF)."""
    left = "unknown" if until_tick is None or tick is None else str(int(until_tick) - int(tick) + 1)
    return (f"{item}: the dealer is cooling off until tick {until_tick} (now {tick}, {left} ticks to go) and the wait was "
            f"not possible ({why}; --max-wait-ticks {max_wait_ticks}). Nothing was bought for this target: run it again "
            f"once the cooloff is over, or raise --max-wait-ticks.")


def wait_out_cooloff(b, r: dict, retry, log, max_wait_ticks: int = MAX_WAIT_TICKS, until_wall: float | None = None,
                     item: str = "") -> tuple:
    """`r` is a refused-open result with code cooloff (carrying until_tick). Wait, pause-safe (a pause or closed doors
    spends no tick), until the game tick has passed until_tick, then call `retry()` ONCE for a fresh result.
    Returns (result, stop): stop is None, or (EXIT_COOLOFF, the one line) when the cooloff has no until_tick, is longer
    than max_wait_ticks, would pass --until (a wall time, checked between ticks), the clock is lost, or the retry meets a
    cooloff again. `cooloff_wait` is logged with the ticks and how it ended."""
    until_tick = r.get("until_tick")
    clock = b.read_clock() or {}
    tick = clock.get("tick")

    def end(result: str, waited: int, res: dict):
        log("cooloff_wait", item=item, until_tick=until_tick, tick=tick, waited=waited, result=result,
            max_wait_ticks=max_wait_ticks)
        return res, (EXIT_COOLOFF, cooloff_line(item, until_tick, tick, result, max_wait_ticks))

    if until_tick is None or tick is None:
        return end("until_tick_unknown", 0, r)
    if int(until_tick) - int(tick) + 1 > max_wait_ticks:
        return end("too_long", 0, r)
    waited = failed = 0
    while True:
        if until_wall is not None and time.time() >= until_wall:
            return end("past_until", waited, r)
        c = b.wait_tick() or {}
        if c.get("tick") is None:
            failed += 1
            if failed >= MAX_FAILED_WAITS:
                return end("clock_lost", waited, r)
            continue
        failed = 0
        waited += 1
        if c["tick"] > int(until_tick):
            break
        if waited > max_wait_ticks:
            return end("too_long", waited, r)
    log("cooloff_wait", item=item, until_tick=until_tick, tick=tick, waited=waited, result="waited",
        max_wait_ticks=max_wait_ticks)
    r2 = retry()
    if r2.get("code") == "cooloff":   # once is enough: a second refusal is the operator's call, not a loop
        until_tick, tick = r2.get("until_tick"), c.get("tick")
        return end("cooloff_again", waited, r2)
    return r2, None


def retry_rate_limited(call, tries: int = 4, pause_s: float = 1.2):
    """Run `call()`; on a `rate_limited` refusal wait `pause_s` and try again, at most `tries` times in all.
    A rate_limited write is refused before the server acts, so a retry cannot double it. Any other refusal,
    and the last rate_limited one, is raised as is."""
    for i in range(tries):
        try:
            return call()
        except BazaarError as e:
            if e.code != "rate_limited" or i == tries - 1:
                raise
            time.sleep(pause_s * (i + 1))
