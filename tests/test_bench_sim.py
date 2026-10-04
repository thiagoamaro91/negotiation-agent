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


class MaxPairs(unittest.TestCase):
    """maxpairs (docs/plans/market-test-sunday.md): the most crossing pairs, then the largest sum of (bid - ask)."""

    @staticmethod
    def book(asks, bids, fee_bps=0, fee_card=0):
        bench = [{"id": f"b5-{i}", "maker": "bench", "give": {"cash": 0, "assets": [], "types": ["bench:cromo"]},
                  "want": {"cash": q, "assets": [], "types": []}} for i, q in enumerate(asks)]
        bench += [{"id": f"b5-{len(asks) + i}", "maker": "bench", "give": {"cash": q, "assets": [], "types": []},
                   "want": {"cash": 0, "assets": [], "types": ["bench:cromo"]}} for i, q in enumerate(bids)]
        return {"venue": "v99", "fee_bps": fee_bps, "fee_per_card": fee_card, "offers": [], "bench_offers": bench}

    def test_the_task_example_gets_both_pairs(self):
        book = self.book([45, 35], [50, 40])
        self.assertEqual(len(bs.bench_plan(book)), 1)  # the stall: 50 x 35, then 40 < 45 stops it
        plan = bs.maxpairs_plan(book)
        self.assertEqual(sorted(plan), [("b5-0", "b5-2", 47), ("b5-1", "b5-3", 37)])

    def test_exact_against_an_exhaustive_matching(self):
        rng = random.Random("maxpairs")
        checked = 0
        for _ in range(1500):
            na, nb = rng.randint(0, 6), rng.randint(0, 6)
            fee = rng.choice(((0, 0), (0, 0), (150, 1), (500, 2)))
            book = self.book([rng.randint(10, 60) for _ in range(na)], [rng.randint(10, 60) for _ in range(nb)],
                             *fee)
            (asks, bids), = bs.brk.bench_quotes(book).values() or [([], [])]
            plan = bs.maxpairs_plan(book)
            q = {o["id"]: o["want"]["cash"] or o["give"]["cash"] for o in book["bench_offers"]}
            ok, bad = bs.brk.guard(plan, book)
            self.assertEqual(bad, [], (book, plan))  # every pair respects the quotes and the fee, each offer once
            big = 1 + sum(q.values())

            def w(i, j):
                (qa, _), (qb, _) = asks[i], bids[j]
                if qb < qa or bs.brk.price_for(book, qa, qb) is None:
                    return None
                return big + qb - qa
            best = bs.brk.best_matching(len(asks), len(bids), w)
            self.assertEqual(len(plan), len(best), (book, plan, best))
            self.assertEqual(sum(q[b] - q[s] for s, b, _ in plan),
                             sum(bids[j][0] - asks[i][0] for i, j in best), (book, plan))
            checked += len(plan) > len(bs.brk.stall_plan(book, fees=True))
        self.assertGreater(checked, 50)  # books where maxpairs adds a pair to the stall's were part of the check

    def test_the_stalls_plan_is_kept_when_it_is_already_the_most_pairs(self):
        rng = random.Random("same")
        same = 0
        for _ in range(500):
            book = self.book([rng.randint(10, 60) for _ in range(rng.randint(0, 6))],
                             [rng.randint(10, 60) for _ in range(rng.randint(0, 6))])
            stall, mp = bs.bench_plan(book), bs.maxpairs_plan(book)
            if len(mp) == len(stall):
                self.assertEqual(mp, stall)
                same += 1
        self.assertGreater(same, 300)

    def test_runs_never_mix_and_the_simulator_refuses_nothing(self):
        book = self.book([45, 35], [50, 40])
        other = self.book([10], [90])["bench_offers"]
        for o in other:
            o["id"] = o["id"].replace("b5-", "b6-")
        book["bench_offers"] += other
        for s, b, _ in bs.maxpairs_plan(book):
            self.assertEqual(bs.brk.run_of(s), bs.brk.run_of(b))
        row = bs.run_scenario(("hard", 40, None, None))
        self.assertEqual(row["mp_bad_match"], 0)
        self.assertGreater(row["mp_win"] + row["mp_loss"], 0)  # it does play differently from the stall


class MaxWeight(unittest.TestCase):
    """maxweight, the review's second candidate: valid plans only, the best estimated-surplus matching."""

    def test_plans_respect_quotes_fees_runs_and_reuse(self):
        rng = random.Random("maxweight")
        n = 0
        for _ in range(800):
            book = MaxPairs.book([rng.randint(10, 60) for _ in range(rng.randint(0, 6))],
                                 [rng.randint(10, 60) for _ in range(rng.randint(0, 6))],
                                 *rng.choice(((0, 0), (150, 1), (500, 2))))
            plan = bs.maxweight_plan(book)
            self.assertEqual(bs.brk.guard(plan, book)[1], [], (book, plan))
            n += len(plan)
        self.assertGreater(n, 500)

    def test_the_reviewers_book(self):
        # asks 50, 65; bids 70, 55: the stall takes 70 x 50; maxweight's estimated surplus prefers both pairs
        book = MaxPairs.book([50, 65], [70, 55])
        self.assertEqual(sorted(m[:2] for m in bs.maxweight_plan(book)), [("b5-0", "b5-3"), ("b5-1", "b5-2")])

    def test_candidate_rows_are_reproducible_and_clean(self):
        a = bs.candidate_row("hard", bs.scenario("hard"), bs.CANDIDATES["maxweight"], 10, "unseen")
        b = bs.candidate_row("hard", bs.scenario("hard"), bs.CANDIDATES["maxweight"], 10, "unseen")
        self.assertEqual(a, b)
        self.assertEqual(a["bad"], 0)


class Replay(unittest.TestCase):
    """bench_sim replay: a recorded run that nothing matched, replayed against a plan, matches what the simulator
    gives that plan on the same session (quotes do not react to the broker, so the paths are the whole truth)."""

    def recorded(self, sc, traders, t0=700):
        rows = []
        for t in range(bs.TICKS):  # nothing matched on record: every path is whole
            offers = [bs.offer(x, x["id"], bs.quote(x, t, sc), sc) for x in traders if bs.present(x, t)]
            rows.append({"event": "book", "tick": t0 + t, "book": {"bench_offers": offers, "offers": []}})
        rows.append({"event": "book", "tick": t0 + bs.TICKS, "book": {"bench_offers": [], "offers": []}})
        return rows

    def test_replay_equals_the_simulator(self):
        sc = bs.scenario("hard")
        n = 0
        for seed in range(40):
            traders = bs.make_session(random.Random(f"rp:{seed}"), sc, run="b9")
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "rec.jsonl"
                f.write_text("\n".join(json.dumps(r) for r in self.recorded(sc, traders)) + "\n")
                offers = bs.read_runs(f)["b9"]
            for plan in (lambda b: bs.brk.stall_plan(b, fees=True), bs.maxpairs_plan):
                trace = []
                bs.simulate(traders, sc, lambda b, t: plan(b), trace, t0=700)
                sim = [(t + 700, s, b, p) for t, s, b, p, *_ in (r for r in trace if r[1] != "book")]
                self.assertEqual(bs.replay_run(offers, plan), sim)
                n += len(sim)
        self.assertGreater(n, 100)

    def test_a_run_matched_on_record_is_refused(self):
        sc = bs.scenario("standard")
        traders = bs.make_session(random.Random("rp"), sc, run="b9")
        rows = self.recorded(sc, traders)
        rows.insert(3, {"event": "matched", "sell": traders[0]["id"], "buy": traders[1]["id"]})
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rec.jsonl"
            f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            with self.assertRaises(SystemExit):
                bs.main(["replay", "--log", str(f), "--run", "b9"])


class Determinism(unittest.TestCase):
    def test_same_seeds_same_numbers(self):
        a = bs.run_scenario(("hard_expiry_exact", 15, None, None))
        b = bs.run_scenario(("hard_expiry_exact", 15, None, None))
        for k in ("stall_mean", "ours_mean", "ceiling_mean", "win", "loss"):
            self.assertEqual(a[k], b[k])


if __name__ == "__main__":
    unittest.main()
