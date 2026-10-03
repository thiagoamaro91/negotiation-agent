"""Fakes shared by the dealer-bot tests (agent/chato.py and agent/abuela.py). No key, no network, nothing written to
logs/: every test swaps the bot's RunLog for NullRun, its save_thread for a no-op and its duel lock for a function it
controls.

FakeServer is an in-process game server under the REAL kit SDK: tests patch urllib.request.urlopen, so the SDK's own
retry, timeout and error handling run unchanged (a client that lets the SDK resend a write shows up as two writes in
one tick). Like the real server (kit/RULES.md, thread 335): one message per thread per tick and one accept per team
per tick (wait_for_tick otherwise), an accept must name an open offer of the dealer in this thread, an accepted offer
settles on the NEXT tick, the dealer answers our message on the next tick, and dealer offers lapse 4 ticks after they
are posted. The error code for accepting a stale offer is not documented; the fake uses offer_not_open (409).

Not a test module itself (no test_ prefix); the test files import it from the tests/ directory.
"""
import contextlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))

from bazaar_sdk import Bazaar as KitBazaar  # noqa: E402,F401  (the plain kit client, for fake self-tests)
from bazaar_sdk import BazaarError  # noqa: E402,F401

import abuela  # noqa: E402
import chato  # noqa: E402

BOTS = (chato, abuela)

# module globals that main() or a test may change; saved and restored around every test
GLOBALS = ("CASH_RESERVE", "MAX_ROUNDS", "ANCHOR_ABS", "STEP", "MAX_BID", "RUN", "DEALER", "DEALER_NAME",
           "SELL_RARITIES", "DEALER_SELLS_CARDS", "SELL_ANCHOR_MULT", "SELL_ANCHOR_OVER_FLOOR", "SELL_ANCHOR_ABS",
           "SELL_STEP", "MAX_DEFER_TICKS", "Bazaar", "load_env", "duel_lock_fresh", "save_thread", "RunLog")


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


# ---------------------------------------------------------------- virtual time

class VirtualClock:
    """A game clock driven by virtual time (time.sleep and time.monotonic are patched to it): 15 s ticks from tick
    100, paused between virtual seconds [pause_from, pause_to). While paused the tick is frozen and next_tick_in is
    `paused_next`."""

    def __init__(self, pause_from=None, pause_to=None, tick_seconds=15.0, paused_next=5.0, doors_closed=(),
                 frozen=None):
        self.now = 0.0
        self.pause_from, self.pause_to = pause_from, pause_to
        self.frozen = frozen  # (from, to) virtual seconds in which the clock says running but its tick does not move
        self.ts, self.paused_next = tick_seconds, paused_next
        self.doors_closed = doors_closed  # (from, to) virtual seconds with doors closed and the clock running
        self.reads = 0

    def sleep(self, s):
        self.now += max(0.0, float(s))

    def monotonic(self):
        return self.now

    def paused(self):
        return self.pause_from is not None and self.pause_from <= self.now < self.pause_to

    def running_time(self):
        rt = self.now
        for a, z in ((self.pause_from, self.pause_to), self.frozen or (None, None)):
            if a is None or self.now < a:
                continue
            rt -= (min(self.now, z) - a)
        return rt

    def tick(self):
        return 100 + int(self.running_time() // self.ts)

    def read(self):
        self.reads += 1
        if self.reads > 20000:
            raise RuntimeError("clock polled more than 20000 times")
        rt = self.running_time()
        doors = "closed" if self.doors_closed and self.doors_closed[0] <= self.now < self.doors_closed[1] else "open"
        if self.paused():
            return {"tick": self.tick(), "paused": True, "doors": doors, "tick_seconds": self.ts,
                    "next_tick_in": self.paused_next}
        return {"tick": self.tick(), "paused": False, "doors": doors, "tick_seconds": self.ts,
                "next_tick_in": self.ts - (rt % self.ts)}


@contextlib.contextmanager
def virtual_time(clock):
    """time.sleep and time.monotonic follow `clock` (the kit and agent modules both call them through the time
    module, so one patch covers both)."""
    real = time.sleep, time.monotonic
    time.sleep, time.monotonic = clock.sleep, clock.monotonic
    try:
        yield clock
    finally:
        time.sleep, time.monotonic = real


def patched_sleep(clock):
    return virtual_time(clock)


# ---------------------------------------------------------------- the fake game server

# our set multipliers as /api/me reports them (kit/RULES.md: the same six numbers, shuffled per team). The ladder
# ceiling of a buy is floor(book x affinity[set]); LAV 1.6 keeps the old fixtures' limits (LAV-09 90 of book 77, LAV-01
# 12 of book 10) under it, so only tests that set their own affinity see a clip.
AFFINITY = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7, "CHA": 0.5}


class _Resp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeServer:
    TEAM = "t03"
    WRITES = ("accept", "messages", "close")

    def __init__(self, dealer="chato", side="sell", opening=16, replies=(), final=None, item="MAL-06", asset_id=42,
                 expiry=4, cash=1000, opening_final=False, pause=None, clock_down=None, tick_seconds=15.0,
                 max_requests=5000, assets=(), cards=None, values=None, frozen=None, affinity=None):
        self.vc = VirtualClock(*(pause or (None, None)), tick_seconds=tick_seconds, frozen=frozen)
        self.dealer, self.side, self.item, self.asset_id = dealer, side, item, asset_id
        self.opening, self.opening_final = opening, opening_final
        self.replies, self.final, self.expiry, self.cash = list(replies), final, expiry, cash
        self.clock_down = clock_down          # (from, to) virtual seconds in which /api/clock times out
        self.max_requests = max_requests
        self.assets, self.cards, self.values = list(assets), cards, values or {}
        self.affinity = dict(AFFINITY if affinity is None else affinity)
        self.tid = 7
        self.thread = None
        self.offers, self.messages = {}, []
        self.next_id = 3000
        self.dealer_price = None
        self.final_named = False
        self.pending_accept = None
        self.our_msg_ticks, self.pending_replies = set(), []
        self.accept_ticks, self.teammate_accepts = set(), set()
        self.inject = {k: [] for k in ("accept", "say", "close", "thread", "open", "me")}
        self.reply_delay = {}                 # our price -> ticks until the dealer answers (default 1)
        self.hooks = []                       # fn(server, tick), run after the dealer's own turn each tick
        self.request_hooks = []               # fn(server, method, path), run before each request is handled
        self.lock_probe, self.lock_violations, self.first_accept_at = None, [], None
        self.requests, self.said, self.accepted, self.closes = [], [], [], []
        self.processed = self.vc.tick()

    # ---- state
    def tick(self):
        return self.vc.tick()

    def price_of(self, o):
        return o["want"]["cash"] if self.side == "buy" else o["give"]["cash"]

    def dealer_offer(self):
        open_ = [o for o in self.offers.values() if o["maker"] == self.dealer and o["status"] == "open"]
        return open_[-1] if open_ else None

    def status(self):
        return self.thread["status"] if self.thread else None

    def post(self, price, final=False, t=None):
        """The dealer posts a new offer (his earlier open offer is cancelled)."""
        t = self.tick() if t is None else t
        for o in self.offers.values():
            if o["maker"] == self.dealer and o["status"] == "open":
                o["status"] = "cancelled"
        self.next_id += 1
        if self.side == "buy":
            give = {"cash": 0, "assets": [], "types": [f"card:{self.item}"]}
            want = {"cash": price, "assets": [], "types": []}
        else:
            give = {"cash": price, "assets": [], "types": []}
            want = {"cash": 0, "assets": [{"id": self.asset_id}], "types": []}
        o = {"id": self.next_id, "maker": self.dealer, "to": self.TEAM, "thread": self.tid, "status": "open",
             "final": final, "give": give, "want": want, "created_tick": t, "expires_tick": t + self.expiry}
        self.offers[o["id"]] = o
        self.messages.append({"id": len(self.messages) + 1, "tick": t, "sender": self.dealer, "offer": o})
        self.dealer_price = price
        return o

    def our_offer(self, price):
        """The structured offer the server attaches to our message (we buy: cash for the card; we sell: the card for
        cash)."""
        if self.side == "buy":
            give, want = {"cash": price, "assets": [], "types": []}, {"cash": 0, "assets": [], "types": [f"card:{self.item}"]}
        else:
            give, want = {"cash": 0, "assets": [self.asset_id], "types": []}, {"cash": price, "assets": [], "types": []}
        return {"maker": self.TEAM, "to": self.dealer, "thread": self.tid, "status": "open", "give": give, "want": want}

    def preopen(self, ours, theirs, ago=2):
        """A conversation an earlier process left open: we said `ours` `ago` ticks ago, the dealer answered `theirs`."""
        t = self.tick()
        self.thread = {"id": self.tid, "status": "open", "closed_reason": None, "opened": t - ago}
        self.post(self.opening, t=t - ago)
        self.our_msg_ticks.add(t - ago)
        self.messages.append({"id": len(self.messages) + 1, "tick": t - ago, "sender": self.TEAM,
                              "offer": dict(self.our_offer(ours), status="cancelled")})
        self.post(theirs, t=t - ago + 1)

    def _turn(self, t):
        th = self.thread
        if th is None:
            return
        if self.pending_accept is not None:     # an accept settles on the next tick
            oid, self.pending_accept = self.pending_accept, None
            if th["status"] == "open":
                th["status"] = "deal"
                self.offers[oid]["status"] = "accepted"
            return
        if th["status"] != "open":
            return
        for o in self.offers.values():
            if o["status"] == "open" and o["expires_tick"] <= t:
                o["status"] = "expired"
        answered = False
        for m in list(self.pending_replies):
            m_tick, price = m
            if t >= m_tick + self.reply_delay.get(price, 1):
                self.pending_replies.remove(m)
                self.post(self.replies.pop(0) if self.replies else self.dealer_price, t=t)
                answered = True
        if (not answered and not self.pending_replies and self.final is not None and not self.final_named
                and (t - 1) not in self.our_msg_ticks and t - 1 >= th["opened"]):
            self.post(self.final, final=True, t=t)  # we let a tick pass without moving: patience runs out
            self.final_named = True
        for h in self.hooks:
            h(self, t)

    def _process(self):
        t = self.tick()
        while self.processed < t:
            self.processed += 1
            self._turn(self.processed)

    # ---- HTTP
    def _err(self, status, code, msg=""):
        return status, {"error": code, "message": msg or code}

    def _injected(self, kind):
        if self.inject.get(kind):
            spec = self.inject[kind].pop(0)
            return spec if spec == "timeout" else self._err(*spec)
        return None

    def handle(self, method, path, query, body):
        self._process()
        for h in self.request_hooks:
            h(self, method, path)
        t = self.tick()
        self.requests.append((t, method, path))
        if len(self.requests) > self.max_requests:
            raise RuntimeError(f"runaway bot: more than {self.max_requests} requests")
        parts = [p for p in path.split("/") if p]
        th = self.thread
        if path == "/api/clock":
            if self.clock_down and self.clock_down[0] <= self.vc.now < self.clock_down[1]:
                return "timeout"
            return 200, self.vc.read()
        if path == "/api/me" and method == "GET":
            return self._injected("me") or (200, {
                "name": self.TEAM, "cash": self.cash, "level": 2, "unlocked": [], "assets": list(self.assets),
                "affinity": dict(self.affinity),
                "score": {"deals": 3, "ladder_points": 0, "score": 0, "rank": 16}})
        if path == "/api/me/value":
            return 200, {"card": query.get("card"), "your_value": self.values.get(query.get("card"), 50)}
        if path == "/api/catalog":
            return 200, {"sets": [{"id": "LAV", "released": True, "cards": list(self.cards or [])}]}
        if parts[:2] == ["api", "dealers"]:
            return 200, {}
        if path == "/api/threads" and method == "POST":
            got = self._injected("open")
            if got:
                return got
            if th is not None and th["status"] == "open":
                return self._err(409, "thread_exists")
            self.thread = {"id": self.tid, "status": "open", "closed_reason": None, "opened": t}
            self.post(self.opening, final=self.opening_final, t=t)
            return 200, {"id": self.tid, "status": "open"}
        if parts[:2] == ["api", "threads"] and len(parts) >= 3:
            if th is None or int(parts[2]) != self.tid:
                return self._err(404, "not_found")
            if len(parts) == 3 and method == "GET":
                return self._injected("thread") or (200, {
                    "id": self.tid, "status": th["status"], "closed_reason": th["closed_reason"],
                    "standing_offers": [dict(o) for o in self.offers.values()
                                        if o["thread"] == self.tid and o["status"] in ("open", "queued")],
                    "messages": [dict(m) for m in self.messages]})
            if parts[3:] == ["messages"]:
                got = self._injected("say")
                if got:
                    return got
                if th["status"] != "open":
                    return self._err(409, "thread_closed")
                if t in self.our_msg_ticks:
                    return self._err(429, "wait_for_tick", "one message per thread per tick")
                price = int(body.get("price"))
                self.our_msg_ticks.add(t)
                self.pending_replies.append((t, price))
                self.said.append((t, price))
                self.messages.append({"id": len(self.messages) + 1, "tick": t, "sender": self.TEAM,
                                      "offer": self.our_offer(price)})
                return 200, {"ok": True}
            if parts[3:] == ["close"]:
                got = self._injected("close")
                if got:
                    return got
                if th["status"] != "open":
                    return self._err(409, "thread_closed")
                th["status"] = "closed"
                for o in self.offers.values():
                    if o["status"] == "open":
                        o["status"] = "cancelled"
                self.closes.append(t)
                return 200, {"ok": True}
        if parts[:2] == ["api", "offers"] and parts[3:] == ["accept"]:
            oid = int(parts[2])
            if self.lock_probe is not None and self.lock_probe():
                self.lock_violations.append((t, oid))
            if self.first_accept_at is None:
                self.first_accept_at = self.vc.now
            got = self._injected("accept")
            if got:
                return got
            if t in self.teammate_accepts or t in self.accept_ticks:
                return self._err(429, "wait_for_tick", "one accept per team per tick")
            o = self.offers.get(oid)
            if (o is None or o["maker"] != self.dealer or o["thread"] != self.tid or o["status"] != "open"
                    or t >= o["expires_tick"]):
                return self._err(409, "offer_not_open")
            if th["status"] != "open":
                return self._err(409, "thread_closed")
            self.accept_ticks.add(t)
            self.pending_accept = oid
            o["status"] = "accepted"
            self.accepted.append((oid, self.price_of(o), t))
            return 200, {"ok": True, "settles": "next tick"}
        return self._err(404, "not_found", f"{method} {path}")

    def urlopen(self, req, timeout=None, **_kw):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        data = getattr(req, "data", None)
        body = json.loads(data) if data else None
        split = urllib.parse.urlsplit(url)
        got = self.handle(method, split.path, dict(urllib.parse.parse_qsl(split.query)), body)
        if got == "timeout":
            self.vc.sleep(timeout if timeout is not None else 15.0)
            raise TimeoutError("timed out")
        status, payload = got
        raw = json.dumps(payload).encode()
        if status >= 400:
            raise urllib.error.HTTPError(url, status, payload.get("error", "error"), {}, io.BytesIO(raw))
        return _Resp(raw)

    @contextlib.contextmanager
    def serving(self):
        real = urllib.request.urlopen
        urllib.request.urlopen = self.urlopen
        try:
            with virtual_time(self.vc):
                yield self
        finally:
            urllib.request.urlopen = real

    # ---- what the bot did
    def client(self, mod):
        """The bot's client, built exactly as its main() builds it."""
        return mod.Bazaar("http://fake.invalid", "test-dummy", wait_on_tick=False)

    def writes(self, kind=None):
        out = []
        for t, m, p in self.requests:
            k = p.rsplit("/", 1)[-1]
            if m == "POST" and k in self.WRITES and (kind is None or k == kind):
                out.append((t, k, p))
        return out

    def same_tick_resends(self):
        """(tick, kind) pairs in which the bot sent the same kind of write more than once."""
        seen, dup = set(), []
        for t, k, _ in self.writes():
            if (t, k) in seen:
                dup.append((t, k))
            seen.add((t, k))
        return dup

    def accept_ids(self):
        return [int(p.split("/")[3]) for _, _, p in self.writes("accept")]


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
    affinity = AFFINITY
    cards = ({"id": "LAV-09", "rarity": "rare", "name": "LAV-09", "book": 77},
             {"id": "LAV-01", "rarity": "common", "name": "LAV-01", "book": 10})

    def me(self):
        return {"name": "t03", "cash": self.cash, "level": 2, "score": {"deals": 3}, "unlocked": [],
                "assets": list(self.assets), "affinity": dict(self.affinity)}

    def catalog(self):
        return {"sets": [{"id": "LAV", "released": True, "cards": list(self.cards)}]}

    def value(self, ref):
        return {"card": ref, "your_value": 90 if ref == "LAV-09" else 12}

    def dealer(self, d):
        return {}

    def open_thread(self, *a, **k):
        self.opened.append(a)
        raise AssertionError("main() opened a thread in a test that must not open one")


def run_main(mod, argv, account_cls=None, lock=False, server=None):
    """Run mod.main() with argv, against a fake account class or (server=) the fake server under the real client.
    Returns (exit code or None, stdout, NullRun, the module globals as main() left them). Everything main() changed
    is put back afterwards."""
    saved = save_globals(mod)
    env = {k: os.environ.get(k) for k in ("BAZAAR_KEY", "BAZAAR_URL")}
    argv0 = sys.argv
    run = NullRun()
    after = {}
    if account_cls is not None:
        mod.Bazaar = account_cls
    mod.load_env, mod.RUN, mod.save_thread = (lambda: None), run, (lambda *a, **k: None)
    mod.RunLog = lambda *a, **k: run   # main() rebinds RUN = RunLog(dealer) for a non-default dealer: keep it fake
    mod.duel_lock_fresh = lock if callable(lock) else (lambda *a: lock)
    os.environ["BAZAAR_KEY"], os.environ["BAZAAR_URL"] = "test-dummy", "http://fake.invalid"
    sys.argv = [f"{mod.__name__}.py"] + list(argv)
    code = None
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with (server.serving() if server is not None else contextlib.nullcontext()):
                try:
                    mod.main()
                except SystemExit as e:
                    code = e.code
        after = save_globals(mod)
    finally:
        restore_globals(mod, saved)
        sys.argv = argv0
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return code, out.getvalue(), run, after
