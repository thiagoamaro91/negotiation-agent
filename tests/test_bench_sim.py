"""tools/bench_sim.py: the denominator, the engine's refusals, refit, determinism.
Run: python3 -m unittest discover tests"""
import itertools
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import bench_sim as bs  # noqa: E402


def brute_best(traders):
    """Max-weight matching on true limits by trying every assignment (small sessions only)."""
    b = [t["limit"] for t in traders if t["side"] == "buy"]
    s = [t["limit"] for t in traders if t["side"] == "sell"]
    if len(b) > len(s):
        b, s = s, b
        sign = -1
    else:
        sign = 1
    best = 0.0
    for perm in itertools.permutations(range(len(s)), len(b)):
        best = max(best, sum(max(0.0, sign * (b[i] - s[j])) for i, j in enumerate(perm)))
    return best


class Denominator(unittest.TestCase):
    def test_best_gain_is_the_max_weight_matching(self):
        for seed in range(150):
            sc = {**bs.scenario("sides_random"), "traders": 7}
            tr = bs.make_session(random.Random(seed), sc)
            self.assertAlmostEqual(bs.best_gain(tr), brute_best(tr), places=9)

    def test_ceiling_sits_between_the_stall_and_the_best(self):
        sc = bs.scenario("standard")
        for seed in range(80):
            tr = bs.make_session(random.Random(f"c:{seed}"), sc)
            stall = bs.simulate(tr, sc, lambda b, t: bs.bench_plan(b))["gain"]
            ceil = bs.ceiling_gain(tr, sc)
            self.assertLessEqual(stall, ceil + 1e-9)
            self.assertLessEqual(ceil, bs.best_gain(tr) + 1e-9)


class Engine(unittest.TestCase):
    def test_the_engine_refuses_what_the_server_would(self):
        sc = bs.scenario("standard")
        tr = bs.make_session(random.Random(1), sc)

        def cheater(book, t):
            offers = book["bench_offers"]
            sells = [o["id"] for o in offers if o["want"]["cash"]]
            buys = [o["id"] for o in offers if o["give"]["cash"]]
            return [(s, b, 1) for s in sells for b in buys]  # price 1: under every ask
        r = bs.simulate(tr, sc, cheater)
        self.assertEqual((r["gain"], r["matches"]), (0.0, 0))
        self.assertGreater(r["refused"], 0)

    def test_quotes_never_pass_the_limit(self):
        for name in ("standard", "hard", "shade_40", "relax_half", "concede_early"):
            sc = bs.scenario(name)
            for seed in range(40):
                for t in bs.make_session(random.Random(seed), sc):
                    for tick in range(bs.TICKS):
                        q = bs.quote(t, tick, sc)
                        self.assertTrue(q <= t["limit"] if t["side"] == "buy" else q >= t["limit"])


class Refit(unittest.TestCase):
    def test_refit_recovers_a_simulated_session(self):
        sc = bs.scenario("expiry_exact")
        tr = bs.make_session(random.Random("refit"), sc, run="b9")
        rows = []
        for t in range(bs.TICKS):  # what `broker.py watch` records: one book per tick, nothing matched
            offers = [bs.offer(x, x["id"], bs.quote(x, t, sc), sc, 500) for x in tr if bs.present(x, t)]
            rows.append({"event": "book", "tick": 500 + t, "book": {"bench_offers": offers, "offers": []}})
        rows.append({"event": "book", "tick": 516, "book": {"bench_offers": [], "offers": []}})
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rec.jsonl"
            f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            shows, fitted = bs.fit(bs.read_runs(f))
        self.assertEqual(shows["offers"], 10)
        self.assertEqual((fitted["traders"], fitted["sides"], fitted["expiry"]), (10, "balanced", "exact"))
        self.assertEqual(shows["ends"]["ours"], 0)


class Determinism(unittest.TestCase):
    def test_same_seeds_same_numbers(self):
        a = bs.run_scenario(("hard_expiry_exact", 15, None, None))
        b = bs.run_scenario(("hard_expiry_exact", 15, None, None))
        for k in ("stall_mean", "ours_mean", "ceiling_mean", "win", "loss"):
            self.assertEqual(a[k], b[k])


if __name__ == "__main__":
    unittest.main()
