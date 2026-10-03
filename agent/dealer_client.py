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

# exit statuses of `run`: 0 ok, 1 crash, 2 usage or --floor refusal, and these five
EXIT_RESERVE = 3        # every buy was skipped because cash is under the reserve
EXIT_CLOSE_FAILED = 4   # a thread could not be closed: it still holds the dealer's only conversation slot
EXIT_LOCK_TIMEOUT = 5   # the duel lock stayed fresh for --max-defer-ticks: the thread was closed without a deal
EXIT_UNSETTLED = 6      # an accept went out but its settlement could not be confirmed: the plan stopped
EXIT_CLOCK_LOST = 7     # the game clock could not be confirmed for MAX_FAILED_WAITS waits: the thread was closed


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
    lost: MAX_FAILED_WAITS waits in a row could not confirm a tick; the caller closes the thread."""

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


def unsettled_line(tid: int, price: int) -> str:
    """The one line run prints when an accept went out but its settlement could not be confirmed (EXIT_UNSETTLED)."""
    return (f"Thread {tid}: our accept at {price} P went out but its settlement could not be confirmed (thread "
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
