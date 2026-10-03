"""Fakes shared by the dealer-bot tests (agent/chato.py and agent/abuela.py). No key, no network, nothing written to
logs/: every test swaps the bot's RunLog for NullRun and its duel lock for a function it controls.

Not a test module itself (no test_ prefix); the test files import it from the tests/ directory.
"""
import contextlib
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))

from bazaar_sdk import BazaarError  # noqa: E402

import abuela  # noqa: E402
import chato  # noqa: E402

BOTS = (chato, abuela)

# module globals that main() or a test may change; saved and restored around every test
GLOBALS = ("CASH_RESERVE", "MAX_ROUNDS", "ANCHOR_ABS", "STEP", "MAX_BID", "RUN", "DEALER", "DEALER_NAME",
           "SELL_RARITIES", "DEALER_SELLS_CARDS", "SELL_ANCHOR_MULT", "SELL_ANCHOR_OVER_FLOOR", "SELL_ANCHOR_ABS",
           "SELL_STEP", "Bazaar", "load_env", "duel_lock_fresh")


class NullRun:
    """Stands in for RunLog so tests never append to the committed logs/<agent>/<date>.jsonl."""

    def __init__(self):
        self.events = []

    def event(self, event, **data):
        self.events.append((event, data))

    def start(self, **data):
        self.events.append(("run_start", data))

    def end(self, **data):
        self.events.append(("run_end", data))

    def named(self, name):
        return [d for e, d in self.events if e == name]


def save_globals(mod):
    return {n: getattr(mod, n) for n in GLOBALS if hasattr(mod, n)}


def restore_globals(mod, saved):
    for n, v in saved.items():
        setattr(mod, n, v)


def lock_sequence(*fresh):
    """A duel_lock_fresh stand-in: answers the given values in order, then False forever."""
    seq = list(fresh)

    def check(*_a, **_k):
        return seq.pop(0) if seq else False
    return check


class Thread:
    """One scripted dealer conversation, buy or sell side, with the structure the real server sends.

    The dealer opens at `opening`, answers each of our messages with the next number in `replies` (or holds her last
    price under a new offer id), and names `final` once we let a tick pass without moving. With `expiry` an offer
    lapses that many ticks after it was posted (the server uses 4: thread 335 shows expires_tick = created_tick + 4).
    `refuse[kind]` queues BazaarError codes, one per call of that kind (accept, say, close)."""

    def __init__(self, dealer, side="sell", opening=16, replies=(), final=None, item="MAL-06", asset_id=42,
                 expiry=None, cash=1000, opening_final=False):
        self.dealer, self.side, self.item, self.asset_id = dealer, side, item, asset_id
        self.replies, self.final, self.expiry, self.cash = list(replies), final, expiry, cash
        self.tick, self.status, self.next_id, self.moved = 0, "open", 100, False
        self.calls, self.says, self.accepts = [], [], []
        self.refuse = {"accept": [], "say": [], "close": []}
        self.offer = None
        self.post(opening, final=opening_final)

    def post(self, price, final=False):
        self.next_id += 1
        if self.side == "buy":
            give = {"cash": 0, "assets": [], "types": [f"card:{self.item}"]}
            want = {"cash": price, "assets": [], "types": []}
        else:
            give, want = {"cash": price}, {"assets": [{"id": self.asset_id}]}
        self.offer = {"id": self.next_id, "maker": self.dealer, "status": "open", "final": final,
                      "give": give, "want": want, "created_tick": self.tick}

    def price(self):
        o = self.offer
        return o["want"]["cash"] if self.side == "buy" else o["give"]["cash"]

    def _refused(self, kind):
        if self.refuse[kind]:
            raise BazaarError(self.refuse[kind].pop(0), f"fake {kind} refused", 429)

    def live(self):
        return (self.status == "open" and self.offer is not None
                and (self.expiry is None or self.tick < self.offer["created_tick"] + self.expiry))

    # ---- the client surface the bots use
    def open_thread(self, with_, topic=None, venue=None):
        self.calls.append(("open_thread", with_, topic))
        return {"id": 7}

    def thread(self, tid):
        self.calls.append(("read", self.tick))
        return {"id": tid, "status": self.status, "standing_offers": [self.offer] if self.live() else [],
                "messages": []}

    def say(self, tid, text="", price=None, offer=None, topic=None):
        self.calls.append(("say_attempt", price, self.tick))
        self._refused("say")
        self.calls.append(("say", price, self.tick))
        self.says.append(price)
        self.moved = True
        self.post(self.replies.pop(0) if self.replies else self.price())
        return {}

    def wait_tick(self):
        self.calls.append(("wait", self.tick))
        if self.status == "open" and not self.moved and self.final is not None and not self.offer["final"]:
            self.post(self.final, final=True)  # we stopped moving: her patience runs out
        self.moved = False
        self.tick += 1
        return {"tick": self.tick}

    def accept(self, oid):
        self.calls.append(("accept_attempt", oid, self.tick))
        self._refused("accept")
        self.accepts.append((oid, self.price(), self.tick))
        self.status = "deal"
        return {}

    def close_thread(self, tid):
        self.calls.append(("close_attempt", tid, self.tick))
        self._refused("close")
        self.calls.append(("close", tid, self.tick))
        self.status = "walked"
        return {}

    def me(self):
        return {"cash": self.cash}

    def kinds(self):
        return [c[0] for c in self.calls]


def sell_target(asset_id, ref, floor):
    """A sell whose floor (the bot's reservation) is exactly `floor`."""
    return {"side": "sell", "item": ref, "asset_id": asset_id, "value": floor, "private": floor - 2}


def buy_target(ref, value, book=77):
    return {"side": "buy", "item": ref, "value": value, "private": value, "book": book}


class FakeAccount:
    """Read-only surface main() needs for plan/run up to the first thread: me, catalog, value, dealer menu.
    Records the constructor kwargs (class attribute `made`) and any thread it is asked to open."""

    made = []

    def __init__(self, url=None, key=None, **kw):
        type(self).made.append(kw)
        self.opened = []

    cash = 169
    assets = []
    cards = ({"id": "LAV-09", "rarity": "rare", "name": "LAV-09", "book": 77},
             {"id": "LAV-01", "rarity": "common", "name": "LAV-01", "book": 10})

    def me(self):
        return {"name": "t03", "cash": self.cash, "level": 2, "score": {"deals": 3}, "unlocked": [],
                "assets": list(self.assets)}

    def catalog(self):
        return {"sets": [{"id": "LAV", "released": True, "cards": list(self.cards)}]}

    def value(self, ref):
        return {"card": ref, "your_value": 90 if ref == "LAV-09" else 12}

    def dealer(self, d):
        return {}

    def open_thread(self, *a, **k):
        self.opened.append(a)
        raise AssertionError("main() opened a thread in a test that must not open one")


def run_main(mod, argv, account_cls, lock=False):
    """Run mod.main() with argv against a fake account class. Returns (exit code or None, stdout, NullRun, the
    module globals as main() left them). Everything main() changed is put back afterwards."""
    saved = save_globals(mod)
    key = os.environ.get("BAZAAR_KEY")
    argv0 = sys.argv
    run = NullRun()
    after = {}
    mod.Bazaar, mod.load_env, mod.duel_lock_fresh, mod.RUN = account_cls, (lambda: None), (lambda *a: lock), run
    os.environ["BAZAAR_KEY"] = "test-dummy"
    sys.argv = [f"{mod.__name__}.py"] + list(argv)
    code = None
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                mod.main()
            except SystemExit as e:
                code = e.code
        after = save_globals(mod)
    finally:
        restore_globals(mod, saved)
        sys.argv = argv0
        if key is None:
            os.environ.pop("BAZAAR_KEY", None)
        else:
            os.environ["BAZAAR_KEY"] = key
    return code, out.getvalue(), run, after


class VirtualClock:
    """A game clock driven by virtual time (time.sleep is patched to advance it): 15 s ticks from tick 100, paused
    between virtual seconds [pause_from, pause_to). While paused the tick is frozen and next_tick_in is `paused_next`."""

    def __init__(self, pause_from=None, pause_to=None, tick_seconds=15.0, paused_next=5.0, doors_closed=()):
        self.now = 0.0
        self.pause_from, self.pause_to = pause_from, pause_to
        self.ts, self.paused_next = tick_seconds, paused_next
        self.doors_closed = doors_closed  # (from, to) virtual seconds with doors closed and the clock running
        self.reads = 0

    def sleep(self, s):
        self.now += max(0.0, float(s))

    def paused(self):
        return self.pause_from is not None and self.pause_from <= self.now < self.pause_to

    def running_time(self):
        if self.pause_from is None or self.now < self.pause_from:
            return self.now
        if self.now < self.pause_to:
            return self.pause_from
        return self.now - (self.pause_to - self.pause_from)

    def read(self):
        self.reads += 1
        if self.reads > 10000:
            raise AssertionError("clock polled more than 10000 times")
        rt = self.running_time()
        doors = "closed" if self.doors_closed and self.doors_closed[0] <= self.now < self.doors_closed[1] else "open"
        if self.paused():
            return {"tick": 100 + int(rt // self.ts), "paused": True, "doors": doors, "tick_seconds": self.ts,
                    "next_tick_in": self.paused_next}
        return {"tick": 100 + int(rt // self.ts), "paused": False, "doors": doors, "tick_seconds": self.ts,
                "next_tick_in": self.ts - (rt % self.ts)}


def patched_sleep(clock):
    """Context manager: time.sleep advances `clock` instead of sleeping (the kit and agent modules both call
    time.sleep through the time module, so one patch covers both)."""
    real = time.sleep

    @contextlib.contextmanager
    def cm():
        time.sleep = clock.sleep
        try:
            yield clock
        finally:
            time.sleep = real
    return cm()
