"""Shared pieces of the dealer bots (agent/abuela.py, agent/chato.py): the client they build and the guarded writes.

DealerBazaar is the kit client (kit/bazaar_sdk.py, unchanged) with two changes:
- wait_on_tick defaults to False, as in agent/rastro_seller.py and agent/duel.py: a refused accept or message raises
  at once and comes back to the bot, which waits for the next tick, re-reads the thread and decides again. The kit
  default resends the same write on the next tick against an offer the dealer may have replaced, and a fourth
  refusal raised out of negotiate() with the thread still open.
- wait_tick() returns only once a new tick has started with the clock running and the doors open. While /api/clock
  says paused, or the doors are closed, it polls every PAUSE_POLL seconds; a null next_tick_in falls back to
  tick_seconds. All of that happens inside one call, so a pause never costs the negotiation a round. The kit's
  wait_tick returns at once while the clock is paused (the bots burned their whole round budget in seconds during a
  pause) and does float(None) on a null next_tick_in.

guarded_accept() is the one way the bots accept: it re-checks the duel lock first (the duel bot holds the team's one
accept per tick) and never lets a refusal raise. close_safely() closes a thread without ever raising.
"""
from __future__ import annotations

import time

from bazaar_sdk import Bazaar, BazaarError

PAUSE_POLL = 3.0        # seconds between clock reads while paused or doors closed (Sunday ticks are 15 s)
MAX_TICK_SLEEP = 65.0   # never trust a next_tick_in above this
STUCK_POLLS = 120       # running clock whose tick never moves: return after ~30 s of 0.25 s polls (bot spends a round)
CLOCK_FAILS = 20        # consecutive failed clock reads (each PAUSE_POLL apart) before wait_tick gives up

ACCEPTED, DEFERRED, REFUSED = "accepted", "deferred", "refused"
EXIT_RESERVE = 3        # run: every buy was skipped because cash is under the reserve (0 ok, 1 crash, 2 usage/refusal)


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
    """The kit client for a dealer bot: no automatic resend of refused writes, and a pause-safe wait_tick."""

    def __init__(self, url: str, key: str, *, wait_on_tick: bool = False, **kw):
        super().__init__(url, key, wait_on_tick=wait_on_tick, **kw)
        self.on_pause = None  # optional callback(clock), called once per wait when it finds the game paused or closed

    def _read_clock(self) -> dict | None:
        """The clock, or None once CLOCK_FAILS reads in a row failed (about a minute): the caller then returns."""
        for _ in range(CLOCK_FAILS):
            try:
                c = self.clock()
                return c if isinstance(c, dict) else {}
            except BazaarError:
                time.sleep(PAUSE_POLL)
        return None

    def wait_tick(self) -> dict:
        """Sleep until a new tick has started with the clock running and the doors open; returns that clock.
        Never raises: if the clock cannot be read for about a minute it returns {} and the bot spends a round."""
        c = self._read_clock()
        if c is None:
            return {}
        start = c.get("tick")
        naps, told = 0, False
        while True:
            if not clock_running(c):
                if not told and self.on_pause is not None:
                    self.on_pause(c)
                    told = True
                time.sleep(PAUSE_POLL)
                naps = 0  # after the pause, sleep the real time to the next tick again
                c = self._read_clock()
                if c is None:
                    return {}
                continue
            tick = c.get("tick")
            if start is None:
                start = tick
            elif tick is not None and tick > start:
                return c
            if naps >= STUCK_POLLS:
                return c
            time.sleep(seconds_to_tick(c) + 0.15 if naps == 0 else 0.25)
            naps += 1
            c = self._read_clock()
            if c is None:
                return {}


def guarded_accept(b, offer_id: int, lock_fresh, log, **ctx) -> str:
    """One accept attempt. DEFERRED: the duel lock is fresh, nothing was sent (logged accept_deferred_lock).
    REFUSED: the server said no (logged accept_refused with its code); it is never resent from here, the caller waits
    a tick, re-reads the thread and decides again. ACCEPTED: the server took it; it settles on the next tick."""
    if lock_fresh():
        log("accept_deferred_lock", offer=offer_id, **ctx)
        return DEFERRED
    try:
        b.accept(offer_id)
    except BazaarError as e:
        log("accept_refused", offer=offer_id, code=e.code, msg=e.message, **ctx)
        return REFUSED
    return ACCEPTED


def close_safely(b, tid: int, log, tries: int = 3) -> bool:
    """Close a thread; on a refusal wait a tick, re-read, and try again only if it is still open. Never raises."""
    for attempt in range(1, tries + 1):
        try:
            b.close_thread(tid)
            return True
        except BazaarError as e:
            log("close_refused", thread=tid, code=e.code, msg=e.message, attempt=attempt)
        try:
            b.wait_tick()
            if b.thread(tid).get("status") != "open":
                return True
        except BazaarError as e:
            log("read_refused", thread=tid, code=e.code, msg=e.message)
    log("close_failed", thread=tid, tries=tries)
    return False


def reserve_line(cash: int, reserve: int, need: int, skipped: int, team_reserve: int = 280) -> str:
    """The one line run prints when the cash reserve blocked every buy (it then exits with EXIT_RESERVE)."""
    room = cash - need
    how = (f"to spend below it on purpose, rerun with --reserve N (N at most {room})" if room >= 0
           else f"even --reserve 0 leaves less than the {need} P a buy needs")
    return (f"No buy started: {skipped} buy(s) skipped because cash {cash} P minus the {reserve} P reserve leaves "
            f"{cash - reserve} P, under the {need} P a buy needs. The {team_reserve} P default is the team rule "
            f"(level-2 bond); {how}.")
