"""agent/broker.py --policy swap (SwapPolicy): the same plans as the overnight search's lab member it implements,
the stall's fallbacks, the guard. Run: python3 -m unittest discover tests"""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals" / "broker-search"))
import policies as pol  # noqa: E402
import bench_sim as bs  # noqa: E402
import broker as brk  # noqa: E402

LAB = {"delta": 0.099, "end_margin": 1, "hi": 0.5, "lo": 0.0, "max_swaps": 1, "mech": "second", "refill": False,
       "rho_fast": 0.09, "rho_slow": 0.09, "sides": "buy", "u_firm": 1.0, "u_first": 1.0}  # member 79977000b8


class SameAsTheLab(unittest.TestCase):
    def test_plans_equal_the_lab_member_tick_by_tick(self):
        swaps = [0]
        for name in ("hard", "standard", "short_patience", "arrive_late"):
            sc = bs.scenario(name)
            for seed in range(60):
                rng = random.Random(f"swap:{name}:{seed}")
                lab, live = pol.Timing(dict(LAB)), brk.SwapPolicy()
                for k in range(2):
                    traders = bs.make_session(rng, sc, run=f"b{k + 1}")
                    plans = []

                    def both(book, t):
                        a, b = lab.plan(book, t), live.plan(book, t)
                        plans.append((sorted(a), sorted(b)))
                        swaps[0] += sum(v == "swap:1" for v in live.notes.values())
                        for s, bb, _ in b:
                            live.sent(s, bb, t)
                        return b
                    bs.simulate(traders, sc, both, t0=100 * k)
                    for a, b in plans:
                        self.assertEqual(a, b)
        self.assertGreater(swaps[0], 5)  # the comparison covers ticks where the swap fires (14 here)

    def test_it_does_swap_and_differs_from_the_stall_somewhere(self):
        sc = bs.scenario("hard")
        differ = 0
        for seed in range(80):
            traders = bs.make_session(random.Random(f"d:{seed}"), sc)
            live = brk.SwapPolicy()
            st = bs.simulate(traders, sc, lambda b, t: bs.bench_plan(b))
            sw = bs.simulate(traders, sc, lambda b, t: live.plan(b, t))
            differ += st["gain"] != sw["gain"]
            self.assertEqual(sw["refused"], 0)
        self.assertGreater(differ, 0)


class Rules(unittest.TestCase):
    def book(self, offers, tick=0):
        return {"venue": "v20", "tick": tick, "fee_bps": 0, "fee_per_card": 0, "offers": [],
                "bench_offers": [bs.offer({"side": side, "a": 0, "P": 16}, oid, q, {"makers": False,
                                                                                    "expiry": "none"})
                                 for oid, side, q in offers]}

    def run_ticks(self, p, ticks):
        out = None
        for t, offers in enumerate(ticks):
            out = p.plan(self.book(offers, t), t)
        return out

    def test_patient_buyer_waits_for_the_leaving_looking_one(self):
        # b1-1 relaxes slowly (40 -> 41: 2.5 % per tick): patient; b1-2 never moved: leaving-looking
        ticks = [[("b1-1", "buy", 40), ("b1-2", "buy", 38)],
                 [("b1-1", "buy", 41), ("b1-2", "buy", 38), ("b1-3", "sell", 37)]]
        self.assertEqual(self.run_ticks(brk.SwapPolicy(), ticks), [("b1-3", "b1-2", 37)])

    def test_no_swap_when_the_gap_is_too_wide_or_the_bid_does_not_cross(self):
        ticks = [[("b1-1", "buy", 40), ("b1-2", "buy", 30)],
                 [("b1-1", "buy", 41), ("b1-2", "buy", 30), ("b1-3", "sell", 29)]]  # 30 is 27 % below 41
        self.assertEqual(self.run_ticks(brk.SwapPolicy(), ticks), [("b1-3", "b1-1", 35)])
        ticks = [[("b1-1", "buy", 40), ("b1-2", "buy", 38)],
                 [("b1-1", "buy", 41), ("b1-2", "buy", 38), ("b1-3", "sell", 39)]]  # 38 < 39
        self.assertEqual(self.run_ticks(brk.SwapPolicy(), ticks), [("b1-3", "b1-1", 40)])

    def test_fast_relaxer_is_not_patient(self):
        ticks = [[("b1-1", "buy", 40), ("b1-2", "buy", 38)],
                 [("b1-1", "buy", 44), ("b1-2", "buy", 38), ("b1-3", "sell", 37)]]  # 10 % per tick
        self.assertEqual(self.run_ticks(brk.SwapPolicy(), ticks), [("b1-3", "b1-1", 40)])

    def test_session_end_makes_everyone_leaving(self):
        def ticks(n):  # b1-1 relaxes slowly (patient), b1-2 never moves and is 7 % below it; the seller comes at n
            out = [[("b1-1", "buy", 40 + t // 4), ("b1-2", "buy", 40)] for t in range(n)]
            out.append([("b1-1", "buy", 43), ("b1-2", "buy", 40), ("b1-3", "sell", 37)])
            return out
        self.assertEqual(self.run_ticks(brk.SwapPolicy(), ticks(13)), [("b1-3", "b1-2", 38)])  # tick 13: swap
        self.assertEqual(self.run_ticks(brk.SwapPolicy(), ticks(14)), [("b1-3", "b1-1", 40)])  # 14 = 16 - 1 - 1

    def test_a_refused_pair_is_not_swapped_in(self):
        p = brk.SwapPolicy()
        ticks = [[("b1-1", "buy", 40), ("b1-2", "buy", 38)],
                 [("b1-1", "buy", 41), ("b1-2", "buy", 38), ("b1-3", "sell", 37)]]
        p.plan(self.book(ticks[0], 0), 0)
        p.refused_pair("b1-3", "b1-2", 1)
        self.assertEqual(p.plan(self.book(ticks[1], 1), 1), [("b1-3", "b1-1", 39)])

    def test_first_tick_is_the_stall_and_an_exception_falls_back(self):
        p = brk.SwapPolicy()
        offers = [("b1-1", "buy", 40), ("b1-2", "sell", 30)]
        self.assertEqual(p.plan(self.book(offers), 0), [("b1-2", "b1-1", 35)])
        self.assertEqual(p.notes["b1"], "stall:no_history")

        class Broken(brk.SwapPolicy):
            def urgency(self, oid, tick):
                raise RuntimeError("boom")
        b = Broken()
        b.plan(self.book(offers), 0)
        self.assertEqual(b.plan(self.book(offers, 1), 1), [("b1-2", "b1-1", 35)])
        self.assertTrue(b.notes["b1"].startswith("fallback:"))

    def test_cli_and_desk_know_the_policy(self):
        self.assertIn("swap", brk.POLICIES)
        self.assertIsInstance(brk.make_policy("swap"), brk.SwapPolicy)
        self.assertIsNone(brk.make_policy("stall"))
        self.assertIsInstance(brk.make_policy("ours"), brk.BenchPolicy)


if __name__ == "__main__":
    unittest.main()
