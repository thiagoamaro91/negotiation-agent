"""Key lease: one accept per tick in priority order, windows, quotas, STOP, the shared token bucket, several processes.

    python3 -m unittest discover -s tests
"""
import multiprocessing as mp
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from lease import Lease  # noqa: E402

LIMITS = {"accepts_per_team_per_tick": 1, "offers_per_team_per_tick": 12, "max_open_offers_per_team": 30}
T0 = 1_000_000.0


class FakeTime:
    """The wall clock all desks share in a test; a tick of `ts` seconds starts at T0 + tick x ts."""

    def __init__(self, ts=30.0):
        self.ts, self.t = ts, T0

    def at(self, tick, frac):
        self.t = T0 + tick * self.ts + frac * self.ts
        return self

    def clock(self, tick, limits=None):
        nxt = (T0 + (tick + 1) * self.ts) - self.t
        return {"tick": tick, "tick_seconds": self.ts, "next_tick_in": nxt, "limits": dict(limits or LIMITS)}

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class MemLog:
    def __init__(self):
        self.rows = []

    def event(self, event, **data):
        self.rows.append({"event": event, **data})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ft = FakeTime()
        self.log = MemLog()

    def tearDown(self):
        self.tmp.cleanup()

    def desk(self, name, **kw):
        return Lease(name, state_dir=self.dir, now=self.ft, sleep=self.ft.sleep, log=self.log, **kw)


class Accept(Base):
    def test_priority_order_one_per_tick(self):
        duel, dealer, market = self.desk("duel"), self.desk("chato"), self.desk("market")
        wants = {"duel": [10], "chato": [10, 11], "market": [10, 11, 12]}
        winners = {}
        for tick in (10, 11, 12):
            self.ft.at(tick, 0.1)
            c = self.ft.clock(tick)
            for d, p, tl in ((duel, Lease.DUEL, 3), (dealer, Lease.DEALER_FINAL, None), (market, Lease.MARKET, None)):
                if tick in wants[d.desk]:
                    d.intend_accept(c, p, ticks_left=tl)
            self.ft.at(tick, 0.6)
            c = self.ft.clock(tick)
            got = []
            for d, p, tl in ((market, Lease.MARKET, None), (dealer, Lease.DEALER_FINAL, None), (duel, Lease.DUEL, 3)):
                if tick in wants[d.desk] and d.claim_accept(c, p, ticks_left=tl):
                    got.append(d.desk)
            self.assertEqual(len(got), 1, (tick, got))
            winners[tick] = got[0]
        self.assertEqual(winners, {10: "duel", 11: "chato", 12: "market"})

    def test_fewest_ticks_left_first(self):
        a, b = self.desk("duel-a"), self.desk("duel-b")
        c = self.ft.at(5, 0.2).clock(5)
        a.intend_accept(c, Lease.DUEL, ticks_left=6)
        b.intend_accept(c, Lease.DUEL, ticks_left=1)
        self.assertFalse(a.claim_accept(c, Lease.DUEL, ticks_left=6))
        self.assertTrue(b.claim_accept(c, Lease.DUEL, ticks_left=1))

    def test_market_only_in_second_half(self):
        m = self.desk("market")
        self.assertFalse(m.claim_accept(self.ft.at(7, 0.49).clock(7), Lease.MARKET))
        self.assertEqual(self.log.rows[-1]["why"], "first_half")
        self.assertTrue(m.claim_accept(self.ft.at(7, 0.51).clock(7), Lease.MARKET))

    def test_higher_desks_any_time_and_only_if_unclaimed(self):
        dealer, market = self.desk("chato"), self.desk("market")
        self.assertTrue(dealer.claim_accept(self.ft.at(3, 0.01).clock(3), Lease.DEALER_FINAL))
        self.assertFalse(market.claim_accept(self.ft.at(3, 0.9).clock(3), Lease.MARKET))
        self.assertEqual(self.log.rows[-1]["why"], "taken")

    def test_duel_window(self):
        duel, dealer, market = self.desk("duel"), self.desk("chato"), self.desk("market")
        duel.register_duel(self.ft.at(100, 0.0).clock(100), 77, deadline_tick=105)
        self.assertTrue(dealer.claim_accept(self.ft.at(101, 0.9).clock(101), Lease.DEALER_FINAL))   # 4 ticks left
        for tick in (102, 103, 104, 105):
            c = self.ft.at(tick, 0.9).clock(tick)
            self.assertFalse(dealer.claim_accept(c, Lease.DEALER_FINAL), tick)
            self.assertFalse(market.claim_accept(c, Lease.MARKET), tick)
            self.assertEqual(self.log.rows[-1]["why"], "duel_window")
            self.assertTrue(duel.claim_accept(c, Lease.DUEL, ticks_left=105 - tick), tick)
        self.assertTrue(market.claim_accept(self.ft.at(106, 0.9).clock(106), Lease.MARKET))         # window over

    def test_claims_expire_with_their_tick(self):
        a, b = self.desk("chato"), self.desk("market")
        self.assertTrue(a.claim_accept(self.ft.at(20, 0.1).clock(20), Lease.DEALER_FINAL))
        self.assertTrue(b.claim_accept(self.ft.at(21, 0.6).clock(21), Lease.MARKET))
        self.assertFalse(a.claim_accept(self.ft.at(21, 0.7).clock(20), Lease.DEALER_FINAL))         # stale clock
        self.assertEqual(self.log.rows[-1]["why"], "stale_tick")

    def test_release(self):
        a, b = self.desk("chato"), self.desk("market")
        c = self.ft.at(30, 0.6).clock(30)
        self.assertTrue(a.claim_accept(c, Lease.DEALER_FINAL))
        a.release_accept(c, "not_open")
        self.assertTrue(b.claim_accept(c, Lease.MARKET))

    def test_limits_from_the_clock(self):
        a = self.desk("chato")
        c = self.ft.at(40, 0.6).clock(40, {**LIMITS, "accepts_per_team_per_tick": 0})
        self.assertFalse(a.claim_accept(c, Lease.DEALER_FINAL))

    def test_stop_file(self):
        a = self.desk("duel")
        (self.dir / "STOP").touch()
        c = self.ft.at(50, 0.9).clock(50)
        self.assertTrue(a.stopped())
        self.assertFalse(a.claim_accept(c, Lease.DUEL, ticks_left=1))
        self.assertEqual(a.claim_listings(c, 3), 0)
        (self.dir / "STOP").unlink()
        self.assertTrue(a.claim_accept(c, Lease.DUEL, ticks_left=1))


class Listings(Base):
    def test_quota_split(self):
        seller, market, chato = self.desk("seller"), self.desk("market"), self.desk("chato")
        c = self.ft.at(60, 0.1).clock(60)
        self.assertEqual(market.claim_listings(c, 10), 6)    # own 4 + the 2 spare
        self.assertEqual(chato.claim_listings(c, 5), 0)      # spare pool used up
        self.assertEqual(seller.claim_listings(c, 10), 6)    # own 6
        self.assertEqual(seller.claim_listings(c, 1), 0)     # 12 in all: nothing left
        c = self.ft.at(61, 0.1).clock(61)                    # new tick, fresh budget
        self.assertEqual(chato.claim_listings(c, 5), 2)

    def test_quota_follows_the_clock_limit(self):
        market, seller = self.desk("market"), self.desk("seller")
        c = self.ft.at(70, 0.1).clock(70, {**LIMITS, "offers_per_team_per_tick": 6})
        self.assertEqual(market.claim_listings(c, 10), 3)    # floor(4 x 6/12) = 2 own + 1 spare
        self.assertEqual(seller.claim_listings(c, 10), 3)    # floor(6 x 6/12) = 3
        self.assertEqual(seller.claim_listings(c, 1), 0)


class Bucket(Base):
    def test_rate(self):
        a, b = self.desk("market", rate=4, burst=4), self.desk("duel", rate=4, burst=4)
        self.ft.at(0, 0.0)
        for _ in range(2):
            self.assertEqual(a.try_token(), 0.0)
            self.assertEqual(b.try_token(), 0.0)
        self.assertGreater(a.try_token(), 0.0)               # 4 shared tokens are gone
        self.ft.sleep(0.25)
        self.assertEqual(b.try_token(), 0.0)                 # one more after a quarter second
        start = self.ft.t
        for _ in range(8):
            self.assertTrue(a.throttle())
        self.assertGreaterEqual(self.ft.t - start, 8 / 4 - 1e-6)


# ---------------------------------------------------------------- several processes on one state file

def _desk_proc(name, state_dir, ticks, seed, barrier, out):
    rng = random.Random(seed)
    ft = FakeTime()
    lz = Lease(name, state_dir=state_dir, now=ft, log=MemLog())
    for tick in ticks:
        plan = {d: (rng.choice([Lease.DUEL, Lease.DEALER_FINAL, Lease.MARKET]), rng.randint(0, 9))
                for d in ("p0", "p1", "p2")}   # every process draws the same plan for the tick
        pr, tl = plan[name]
        c = ft.at(tick, 0.6).clock(tick)
        lz.intend_accept(c, pr, ticks_left=tl)
        barrier.wait()
        got = lz.claim_accept(c, pr, ticks_left=tl)
        out.put((tick, name, got, plan))
        barrier.wait()


def _token_proc(state_dir, n, barrier, out):
    lz = Lease("x", state_dir=state_dir, log=MemLog(), rate=50, burst=1)
    barrier.wait()
    first = None
    for _ in range(n):
        lz.throttle()
        first = first or time.monotonic()
    out.put((first, time.monotonic()))


class Processes(unittest.TestCase):
    def test_one_accept_per_tick_across_processes(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = mp.get_context("spawn")
            barrier, out = ctx.Barrier(3), ctx.Queue()
            ticks = list(range(200, 230))
            ps = [ctx.Process(target=_desk_proc, args=(f"p{i}", d, ticks, 1234, barrier, out)) for i in range(3)]
            for p in ps:
                p.start()
            rows = [out.get(timeout=60) for _ in range(3 * len(ticks))]
            for p in ps:
                p.join(timeout=30)
            for tick in ticks:
                got = [name for t, name, g, _ in rows if t == tick and g]
                plan = next(p for t, _, _, p in rows if t == tick)
                ranks = {d: Lease._rank(*plan[d]) for d in plan}
                best = {d for d, r in ranks.items() if r == min(ranks.values())}
                self.assertEqual(len(got), 1, (tick, got))
                self.assertIn(got[0], best, (tick, plan))   # a tie in rank may go to either desk

    def test_token_bucket_across_processes(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = mp.get_context("spawn")
            out, barrier = ctx.Queue(), ctx.Barrier(3)
            ps = [ctx.Process(target=_token_proc, args=(d, 25, barrier, out)) for _ in range(3)]
            for p in ps:
                p.start()
            spans = [out.get(timeout=60) for _ in ps]
            for p in ps:
                p.join(timeout=30)
            # 75 tokens shared at 50/s: ~1.5 s from the first to the last; a bucket per process would take ~0.5 s
            self.assertGreaterEqual(max(e for _, e in spans) - min(f for f, _ in spans), 1.3)


if __name__ == "__main__":
    unittest.main()
