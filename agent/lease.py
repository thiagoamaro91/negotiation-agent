"""Key lease: one hand on the team key, shared by every process on the key machine.

The server gives the whole team one accept per tick, twelve new listings per tick (a cancelled one still counts) and
5 requests per second. Every agent on the key (duel.py, chato.py, abuela.py, rastro_seller.py, market_desk.py) shares
those, so each one asks this lease first. State lives in logs/state/lease.json, guarded by an fcntl lock on
logs/state/lease.lock, so it works across processes on ONE machine (the key machine). The OS drops an fcntl lock when
its process dies, so a crash never leaves the lock held; claims carry their tick and expire with it.

Rules (docs/plans/key-lease.md):
  - Accept: one per tick. Rank: DUEL (fewest ticks left first) > DEALER_FINAL > MARKET > OTHER. DUEL and
    DEALER_FINAL may claim at any moment of the tick; MARKET and OTHER only after half the tick has passed, and only
    if nobody has claimed. A desk that knows early that it will accept can say so with intend_accept(); a claim is
    refused while a better-ranked intent from another desk is live in the same tick.
  - Duel window: while any registered duel is within DUEL_WINDOW (3) ticks of its deadline (deadline - 3 <= tick <=
    deadline), nothing but DUEL may accept. The duel desk registers each deadline with register_duel().
  - Listings: the per-tick limit from the clock's `limits` is split by quota (QUOTAS, out of QUOTA_BASE = 12, scaled
    to the limit in force); whatever no named desk owns is a spare pool any desk may use. Claim cancels too.
  - Requests: a shared token bucket at RATE (4) per second, one below the server's 5, so one desk's burst cannot make
    another desk's call fail. Call throttle() before every keyed request.
  - STOP: while logs/state/STOP exists every claim is refused (reads go on). `touch logs/state/STOP` to stop every
    desk at its next tick, `rm logs/state/STOP` to resume.
  - Limits are read from the clock dict passed in (GET /api/clock -> limits), never hard-coded; DEFAULT_LIMITS is
    only used when a clock carries no `limits`.
  - Every claim, grant and refusal goes to logs/lease/<date>.jsonl through agent/runlog.py.

Wiring (every desk, every tick; the client must be built with wait_on_tick=False so a refused accept is never
repeated on the next tick):

    from lease import Lease
    lease = Lease("duel")                      # desk name: duel, dealer, market, seller, abuela, ...
    clock = b.clock()
    if lease.stopped():
        ...                                    # reads only this tick
    # duel desk: register every live duel's deadline once per tick, then claim with the ticks left
    lease.register_duel(clock, duel_id, deadline_tick)
    if lease.claim_accept(clock, Lease.DUEL, ticks_left=deadline_tick - clock["tick"], ref=f"duel {duel_id}"):
        b.duel_accept(duel_id)                 # on a refusal that did not use the accept: lease.release_accept(clock)
    # dealer final offer (chato.py / abuela.py)
    if lease.claim_accept(clock, Lease.DEALER_FINAL, ref=f"offer {oid}"):
        b.accept(oid)
    # El Rastro seller: listings and cancels share the per-tick budget
    n = lease.claim_listings(clock, 2)          # how many of the 2 it may post or cancel this tick
    # before every keyed request (blocks until a token is free)
    lease.throttle()
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

STATE_DIR = ROOT / "logs" / "state"
DUEL_WINDOW = 3            # ticks before a duel's deadline (inclusive) in which only duels may accept
RATE = 4.0                 # shared requests per second (the server allows 5, bursts of 20)
BURST = 4.0                # bucket size
QUOTA_BASE = 12            # the quotas below are out of this many listings per tick
QUOTAS = {"seller": 6, "market": 4}   # the rest (2 of 12) is a spare pool for any desk
DEFAULT_LIMITS = {"accepts_per_team_per_tick": 1, "offers_per_team_per_tick": 12, "max_open_offers_per_team": 30,
                  "messages_per_side_per_tick": 1, "max_open_threads_per_team": 6}


class _QuietLog:
    """runlog.RunLog without the stdout echo (a lease line per claim would drown a desk's own output)."""

    def __init__(self, agent: str = "lease"):
        from runlog import RunLog, redact
        self._redact = redact
        self._run = RunLog(agent)

    def event(self, event: str, **data) -> None:
        row = self._redact({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": self._run.run_id, "agent": "lease",
                            "event": event, **data})
        with self._run.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


class Lease:
    DUEL, DEALER_FINAL, MARKET, OTHER = 0, 1, 2, 3
    NAMES = {0: "duel", 1: "dealer_final", 2: "market", 3: "other"}

    def __init__(self, desk: str, *, state_dir: Path | str | None = None, now=time.time, sleep=time.sleep,
                 log=None, rate: float = RATE, burst: float = BURST, quotas: dict | None = None,
                 duel_window: int = DUEL_WINDOW):
        self.desk = str(desk)
        self.dir = Path(state_dir) if state_dir else STATE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "lease.json"
        self.lock_path = self.dir / "lease.lock"
        self.stop_path = self.dir / "STOP"
        self.now, self.sleep = now, sleep
        self.rate, self.burst = float(rate), float(burst)
        self.quotas = dict(QUOTAS if quotas is None else quotas)
        self.duel_window = int(duel_window)
        self._log = log

    # ------------------------------------------------ plumbing
    @property
    def log(self):
        if self._log is None:
            self._log = _QuietLog()
        return self._log

    @contextlib.contextmanager
    def _locked(self):
        with open(self.lock_path, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                st = self._read()
                yield st
                st["updated"] = self.now()
                tmp = self.path.with_name(f".lease.{os.getpid()}.tmp")
                tmp.write_text(json.dumps(st, separators=(",", ":")))
                os.replace(tmp, self.path)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict:
        try:
            st = json.loads(self.path.read_text())
            if isinstance(st, dict):
                return st
        except (OSError, ValueError):
            pass
        return {"tick": None}

    def _roll(self, st: dict, clock: dict) -> str | None:
        """Bring the shared state to the clock's tick. Returns a refusal reason for a clock older than the state."""
        tick = int(clock["tick"])
        cur = st.get("tick")
        if cur is not None and tick < cur:
            return "stale_tick"
        if cur != tick:
            ts = float(clock.get("tick_seconds") or 30.0)
            nxt = clock.get("next_tick_in")
            nxt = ts if nxt is None else min(ts, max(0.0, float(nxt)))
            st.update({"tick": tick, "tick_started": self.now() - (ts - nxt), "tick_seconds": ts,
                       "accept": None, "intents": {}, "listings": {}, "spare_used": 0})
            st["duels"] = {k: d for k, d in (st.get("duels") or {}).items() if int(d) >= tick}
        lim = clock.get("limits")
        st["limits"] = {**DEFAULT_LIMITS, **(st.get("limits") or {}), **(lim if isinstance(lim, dict) else {})}
        return None

    def _event(self, event: str, **data) -> None:
        try:
            self.log.event(event, desk=self.desk, **data)
        except Exception:  # logging must never break a desk
            pass

    # ------------------------------------------------ STOP
    def stopped(self) -> bool:
        return self.stop_path.exists()

    # ------------------------------------------------ duels
    def register_duel(self, clock: dict, duel_id, deadline_tick: int) -> None:
        with self._locked() as st:
            if self._roll(st, clock):
                return
            st.setdefault("duels", {})[str(duel_id)] = int(deadline_tick)

    def clear_duel(self, clock: dict, duel_id) -> None:
        with self._locked() as st:
            if self._roll(st, clock):
                return
            (st.get("duels") or {}).pop(str(duel_id), None)

    def _window(self, st: dict) -> list:
        t = st["tick"]
        return sorted(k for k, d in (st.get("duels") or {}).items() if int(d) - self.duel_window <= t <= int(d))

    # ------------------------------------------------ accept
    @staticmethod
    def _rank(priority: int, ticks_left) -> tuple:
        return (int(priority), int(ticks_left) if (priority == Lease.DUEL and ticks_left is not None) else 10 ** 6)

    def intend_accept(self, clock: dict, priority: int, ticks_left: int | None = None, ref: str = "") -> None:
        """Say early in the tick that this desk will claim the accept; lower-ranked desks then wait. Expires with
        the tick. Only a desk that will really claim should intend: an intent blocks lower desks for the tick."""
        with self._locked() as st:
            if self._roll(st, clock):
                return
            st.setdefault("intents", {})[self.desk] = {"rank": list(self._rank(priority, ticks_left)), "ref": ref,
                                                      "at": self.now()}
        self._event("intent", tick=int(clock["tick"]), priority=self.NAMES.get(priority, priority),
                    ticks_left=ticks_left, ref=ref)

    def claim_accept(self, clock: dict, priority: int, ticks_left: int | None = None, ref: str = "") -> bool:
        """True: this desk owns this tick's accept and should send it now. False: do not accept this tick."""
        tick = int(clock["tick"])
        why = None
        with self._locked() as st:
            why = self._roll(st, clock)
            if why is None:
                why = self._accept_check(st, priority, ticks_left)
            if why is None:
                st["accept"] = {"desk": self.desk, "priority": int(priority), "ticks_left": ticks_left, "ref": ref,
                                "at": self.now()}
                (st.get("intents") or {}).pop(self.desk, None)
            elif why in ("outranked", "first_half", "duel_window"):  # still wants it: let lower desks know
                st.setdefault("intents", {}).setdefault(self.desk, {"rank": list(self._rank(priority, ticks_left)),
                                                                    "ref": ref, "at": self.now()})
            holder = (st.get("accept") or {}).get("desk")
        self._event("grant" if why is None else "refuse", kind="accept", tick=tick,
                    priority=self.NAMES.get(priority, priority), ticks_left=ticks_left, ref=ref, why=why,
                    holder=holder if why else None)
        return why is None

    def _accept_check(self, st: dict, priority: int, ticks_left) -> str | None:
        if self.stopped():
            return "stop"
        if int(st["limits"].get("accepts_per_team_per_tick", 1)) < 1:
            return "no_accepts_in_limits"
        if st.get("accept"):
            return "taken"
        if priority != self.DUEL and self._window(st):
            return "duel_window"
        if priority >= self.MARKET:
            elapsed = self.now() - float(st.get("tick_started") or 0)
            if elapsed < float(st.get("tick_seconds") or 30.0) / 2:
                return "first_half"
        mine = self._rank(priority, ticks_left)
        for desk, it in (st.get("intents") or {}).items():
            if desk != self.desk and tuple(it.get("rank") or ()) < mine:
                return "outranked"
        return None

    def release_accept(self, clock: dict, why: str = "") -> None:
        """Give the accept back when the server refused it without using it (offer gone, insufficient cash...)."""
        with self._locked() as st:
            if self._roll(st, clock) is None and (st.get("accept") or {}).get("desk") == self.desk:
                st["accept"] = None
        self._event("release", kind="accept", tick=int(clock["tick"]), why=why)

    def accept_holder(self, clock: dict) -> str | None:
        with self._locked() as st:
            if self._roll(st, clock):
                return None
            return (st.get("accept") or {}).get("desk")

    # ------------------------------------------------ listings
    def quota(self, limit: int) -> tuple:
        """(this desk's own quota, the spare pool) for a per-tick listing limit."""
        own = {d: int(math.floor(q * limit / QUOTA_BASE)) for d, q in self.quotas.items()}
        spare = max(0, limit - sum(own.values()))
        return own.get(self.desk, 0), spare

    def claim_listings(self, clock: dict, n: int = 1) -> int:
        """How many of `n` new listings (or cancels) this desk may send this tick: 0..n."""
        tick = int(clock["tick"])
        got, why = 0, None
        with self._locked() as st:
            why = self._roll(st, clock)
            if why is None and self.stopped():
                why = "stop"
            if why is None:
                limit = int(st["limits"].get("offers_per_team_per_tick", 12))
                own_q, spare_q = self.quota(limit)
                used = st.setdefault("listings", {})
                total = sum(used.values()) + 0
                own_used = used.get(self.desk, 0)
                spare_used = int(st.get("spare_used") or 0)
                from_own = max(0, min(int(n), own_q - min(own_used, own_q)))
                from_spare = max(0, min(int(n) - from_own, spare_q - spare_used))
                got = max(0, min(from_own + from_spare, limit - total))
                from_spare = max(0, got - from_own)
                used[self.desk] = own_used + got
                st["spare_used"] = spare_used + from_spare
                if got < n:
                    why = "quota"
        self._event("grant" if got else "refuse", kind="listings", tick=tick, asked=int(n), got=got, why=why)
        return got

    # ------------------------------------------------ requests
    def try_token(self) -> float:
        """Take one request token if there is one: returns 0.0. Otherwise returns the seconds to wait."""
        with self._locked() as st:
            b = st.get("bucket") or {"tokens": self.burst, "at": self.now()}
            t = self.now()
            tokens = min(self.burst, float(b.get("tokens", self.burst)) + max(0.0, t - float(b.get("at", t))) * self.rate)
            if tokens >= 1.0:
                st["bucket"] = {"tokens": tokens - 1.0, "at": t}
                return 0.0
            st["bucket"] = {"tokens": tokens, "at": t}
            return (1.0 - tokens) / self.rate

    def throttle(self, max_wait: float = 10.0) -> bool:
        """Block until one request token is ours (True), or give up after max_wait seconds (False)."""
        waited = 0.0
        while True:
            w = self.try_token()
            if w <= 0:
                return True
            if waited >= max_wait:
                return False
            w = min(w + 0.001, max_wait - waited)
            self.sleep(w)
            waited += w

    # ------------------------------------------------ status (for the brain page / a human)
    def snapshot(self) -> dict:
        return self._read()


if __name__ == "__main__":  # python3 agent/lease.py  -> print the shared state
    lz = Lease("status")
    print(json.dumps({"stop": lz.stopped(), **lz.snapshot()}, indent=1))
