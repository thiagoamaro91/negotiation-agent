"""evals/broker-search: the pure parts of the overnight broker search (WP11).
Run: python3 -m unittest discover tests"""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals" / "broker-search"))
import lab  # noqa: E402
import leave_model as lm  # noqa: E402
import policies as pol  # noqa: E402
import eval_broker as eb  # noqa: E402  (on the path through lab)
import bench_sim as bs  # noqa: E402

BOOK = {"fee_bps": 0, "fee_per_card": 0}


def row(diff, se, drop=0, bad=0):
    return {"diff": diff, "se": se, "ci95": 1.96 * se, "z": diff / se if se else 0.0, "dropped_vs_stall": drop,
            "bad": bad}


def passing_rows():
    rows = {k: row(0.0, 0.001) for k in lab.battery(extra=False)}
    rows["hard"] = row(0.003, 0.001)
    return rows


class Verdict(unittest.TestCase):
    def test_hard_win_and_nothing_worse_is_hard_only(self):
        v, why = lab.verdict(passing_rows())
        self.assertEqual(v, "recommendable for the hard test")

    def test_hard_win_must_exceed_two_se(self):
        rows = passing_rows()
        rows["hard"] = row(0.0019, 0.001)  # 1.9 SE
        self.assertEqual(lab.verdict(rows)[0], "not recommended")
        rows["hard"] = row(0.0021, 0.001)
        self.assertEqual(lab.verdict(rows)[0], "recommendable for the hard test")

    def test_worse_beyond_noise_on_a_refit_fails(self):
        rows = passing_rows()
        rows["refit b88"] = row(-0.00197, 0.001)  # CI upper bound just below 0
        v, why = lab.verdict(rows)
        self.assertEqual(v, "not recommended")
        self.assertIn("refit b88", why[0])
        rows["refit b88"] = row(-0.00195, 0.001)  # CI upper bound just above 0: noise
        self.assertEqual(lab.verdict(rows)[0], "recommendable for the hard test")

    def test_the_pooled_refit_does_not_decide(self):
        rows = passing_rows()
        rows["refit all"] = row(-0.01, 0.001)
        self.assertEqual(lab.verdict(rows)[0], "recommendable for the hard test")

    def test_one_dropped_pair_fails(self):
        rows = passing_rows()
        rows["thin_overlap"]["dropped_vs_stall"] = 1
        self.assertEqual(lab.verdict(rows)[0], "not recommended")

    def test_bad_match_fails(self):
        rows = passing_rows()
        rows["standard"]["bad"] = 1
        self.assertEqual(lab.verdict(rows)[0], "not recommended")

    def test_everywhere_needs_standard_and_each_refit(self):
        rows = passing_rows()
        for k in ["standard"] + [f"refit {r}" for r in lab.REFITS]:
            rows[k] = row(0.003, 0.001)
        self.assertEqual(lab.verdict(rows)[0], "recommendable everywhere")
        rows["refit b104"] = row(0.0015, 0.001)
        self.assertEqual(lab.verdict(rows)[0], "recommendable for the hard test")

    def test_missing_scenario_is_incomplete(self):
        rows = passing_rows()
        del rows["arrive_late"]
        self.assertEqual(lab.verdict(rows)[0], "incomplete")

    def test_screen_margin_sign_matches_the_rule_without_drops(self):
        rows = passing_rows()
        self.assertGreater(lab.screen_margin(rows), 0)
        rows["wide_overlap"] = row(-0.003, 0.001)
        self.assertLess(lab.screen_margin(rows), 0)


class Stats(unittest.TestCase):
    def test_merge_equals_one_pass(self):
        rng = random.Random(3)
        d = [rng.gauss(0.001, 0.01) for _ in range(300)]
        s = [rng.random() for _ in d]
        c = [x + y for x, y in zip(s, d)]
        whole = lab.summarise("x", d, s, c, bad=0, dropped=2, dropped_sessions=1, dropped_vs_stall=1, secs=1.0)
        a = lab.summarise("x", d[:120], s[:120], c[:120], bad=0, dropped=2, dropped_sessions=1, dropped_vs_stall=1,
                          secs=0.5)
        b = lab.summarise("x", d[120:], s[120:], c[120:], bad=0, dropped=0, dropped_sessions=0, dropped_vs_stall=0,
                          secs=0.5)
        m = lab.merge(a, b)
        for k in ("n", "diff", "se", "z", "stall", "cand", "win", "loss", "dropped", "dropped_vs_stall"):
            self.assertAlmostEqual(m[k], whole[k], places=9, msg=k)


class Dropped(unittest.TestCase):
    def test_kuhn_matches_eval_broker_dp(self):
        rng = random.Random(7)
        for _ in range(400):
            sells = [f"b1-s{i}" for i in range(rng.randint(1, 7))]
            buys = [f"b1-b{i}" for i in range(rng.randint(1, 7))]
            edges = {(s, b) for s in sells for b in buys if rng.random() < 0.35}
            matched = {x for x in sells + buys if rng.random() < 0.2}
            self.assertEqual(lab.dropped_count(edges, matched), eb.dropped_count(edges, matched))

    def test_stall_never_drops_and_dropped_vs_stall_counts(self):
        for seed in range(60):
            sc = bs.scenario("hard")
            tr = bs.make_session(random.Random(f"d:{seed}"), sc)
            st = lab.session(tr, sc, lambda b, t: bs.bench_plan(b), 0)
            self.assertEqual(lab.dropped_count(st["edges"], st["matched"]), 0)
        self.assertEqual(lab.dropped_vs_stall([("s1", "b1"), ("s2", "b2")], {"s1"}), 1)
        self.assertEqual(lab.dropped_vs_stall([("s1", "b1")], set()), 1)
        self.assertEqual(lab.dropped_vs_stall([("s1", "b1")], {"b9"}), 1)

    def test_a_policy_that_never_matches_drops_what_the_stall_crossed(self):
        sc = bs.scenario("standard")
        tr = bs.make_session(random.Random("null"), sc)
        st = lab.session(tr, sc, lambda b, t: bs.bench_plan(b), 0)
        nul = lab.session(tr, sc, lambda b, t: [], 0)
        self.assertEqual(lab.dropped_vs_stall(st["pairs"], nul["matched"]), len(st["pairs"]))
        self.assertGreater(lab.dropped_count(nul["edges"], nul["matched"]), 0)


class Paths(unittest.TestCase):
    def test_path_stats(self):
        tr = {"side": "sell", "quotes": [(10, 100), (11, 95), (12, 95), (13, 90)]}
        ps = pol.path_stats(tr, 13, 8, window=1)
        self.assertEqual((ps["n"], ps["st"], ps["first"]), (4, 5, False))
        self.assertAlmostEqual(ps["move"], 0.10)
        self.assertAlmostEqual(ps["rho"], 0.10 / 3)
        self.assertTrue(ps["recent"])
        tr["quotes"] = [(10, 100), (11, 95), (12, 95), (13, 95)]
        self.assertFalse(pol.path_stats(tr, 13, 8, window=2)["recent"])
        self.assertTrue(pol.path_stats(tr, 13, 8, window=3)["recent"])

    def test_heuristic_urgency(self):
        cfg = {"end_margin": 1, "u_first": 0.5, "u_firm": 0.0, "rho_fast": 0.1, "rho_slow": 0.02}
        base = {"st": 3, "first": False, "move": 0.2, "rho": 0.05}
        self.assertEqual(pol.heuristic_urgency(base, cfg), 0.5)
        self.assertEqual(pol.heuristic_urgency({**base, "rho": 0.1}, cfg), 1.0)
        self.assertEqual(pol.heuristic_urgency({**base, "rho": 0.02}, cfg), 0.0)
        self.assertEqual(pol.heuristic_urgency({**base, "first": True}, cfg), 0.5)
        self.assertEqual(pol.heuristic_urgency({**base, "move": 0.0}, cfg), 0.0)
        self.assertEqual(pol.heuristic_urgency({**base, "st": 14}, cfg), 1.0)  # 16-tick session, margin 1
        self.assertEqual(pol.heuristic_urgency({**base, "st": 13}, cfg), 0.5)


SWAP = {"hi": 0.5, "lo": 0.5, "delta": 1.0, "max_swaps": 3, "refill": False, "sides": "both"}


class Swap(unittest.TestCase):
    asks = [(35, "b1-s35"), (45, "b1-s45")]
    bids = [(50, "b1-b50"), (40, "b1-b40")]

    def test_no_urgency_is_the_stall(self):
        self.assertEqual(pol.swap_run(self.asks, self.bids, BOOK, {}, SWAP),
                         bs.brk.stall_run(self.asks, self.bids, BOOK))

    def test_leaving_buyer_takes_the_patient_buyers_seller(self):
        urg = {"b1-b40": 1.0, "b1-b50": 0.0}
        plan = pol.swap_run(self.asks, self.bids, BOOK, urg, SWAP)
        self.assertEqual(plan, [("b1-s35", "b1-b40", 37)])
        refill = pol.swap_run(self.asks, self.bids, BOOK, urg, {**SWAP, "refill": True})
        self.assertEqual(refill, [("b1-s35", "b1-b40", 37), ("b1-s45", "b1-b50", 47)])

    def test_no_swap_when_the_patient_one_also_looks_urgent_or_loss_too_big(self):
        self.assertEqual(pol.swap_run(self.asks, self.bids, BOOK, {"b1-b40": 1.0, "b1-b50": 0.9}, SWAP),
                         [("b1-s35", "b1-b50", 42)])
        self.assertEqual(pol.swap_run(self.asks, self.bids, BOOK, {"b1-b40": 1.0}, {**SWAP, "delta": 0.1}),
                         [("b1-s35", "b1-b50", 42)])  # 40 is 20 % below 50
        self.assertEqual(pol.swap_run(self.asks, self.bids, BOOK, {"b1-b40": 1.0}, {**SWAP, "sides": "sell"}),
                         [("b1-s35", "b1-b50", 42)])

    def test_never_pairs_offers_that_do_not_cross(self):
        asks, bids = [(35, "b1-s35")], [(50, "b1-b50"), (30, "b1-b30")]
        self.assertEqual(pol.swap_run(asks, bids, BOOK, {"b1-b30": 1.0}, SWAP), [("b1-s35", "b1-b50", 42)])

    def test_random_books_respect_quotes_and_use_each_offer_once(self):
        rng = random.Random(11)
        for _ in range(500):
            asks = [(rng.randint(20, 80), f"b1-s{i}") for i in range(rng.randint(1, 6))]
            bids = [(rng.randint(20, 80), f"b1-b{i}") for i in range(rng.randint(1, 6))]
            urg = {o: rng.random() for _, o in asks + bids}
            cfg = {**SWAP, "hi": rng.random(), "lo": rng.random(), "refill": rng.random() < 0.5,
                   "delta": rng.random()}
            plan = pol.swap_run(asks, bids, BOOK, urg, cfg)
            book = {**BOOK, "bench_offers": [bs.offer({"side": "sell", "a": 0, "P": 16}, o, q,
                                                      {"makers": False, "expiry": "none"}) for q, o in asks]
                    + [bs.offer({"side": "buy", "a": 0, "P": 16}, o, q, {"makers": False, "expiry": "none"})
                       for q, o in bids], "offers": []}
            ok, bad = bs.brk.guard(plan, book)
            self.assertEqual(bad, [])


class Hold(unittest.TestCase):
    asks = [(35, "b1-s35")]
    bids = [(50, "b1-b50"), (40, "b1-b40"), (38, "b1-b38")]
    cfg = {"lo": 0.0, "N": 2, "persp": "sell", "t_max": 10}

    def test_holds_only_when_every_condition_holds(self):
        urg = {"b1-s35": 0.0, "b1-b50": 0.0, "b1-b40": 0.0, "b1-b38": 0.0}
        recent = {"b1-b50": True}
        self.assertEqual(pol.hold_run(self.asks, self.bids, BOOK, urg, recent, 3, self.cfg), [])
        stall = [("b1-s35", "b1-b50", 42)]
        self.assertEqual(pol.hold_run(self.asks, self.bids, BOOK, urg, {}, 3, self.cfg), stall)  # not relaxing
        self.assertEqual(pol.hold_run(self.asks, self.bids, BOOK, urg, recent, 10, self.cfg), stall)  # too late
        self.assertEqual(pol.hold_run(self.asks, self.bids, BOOK, {**urg, "b1-b38": 1.0}, recent, 3, self.cfg),
                         stall)  # only one other patient buyer
        self.assertEqual(pol.hold_run(self.asks, self.bids, BOOK, {**urg, "b1-s35": 1.0}, recent, 3, self.cfg),
                         stall)  # the seller looks impatient
        self.assertEqual(pol.hold_run(self.asks, self.bids, BOOK, urg, recent, 3, {**self.cfg, "persp": "buy"}),
                         stall)


class LeaveModel(unittest.TestCase):
    def test_features(self):
        x = lm.features("buy", [(5, 50), (6, 55)], 6, 2)
        self.assertEqual(dict(zip(lm.FEATURES, x)),
                         {"bias": 1.0, "age": 2 / 16, "move": 0.1, "step": 0.1, "firm": 0.0, "first": 0.0,
                          "st": 4 / 16, "st2": (4 / 16) ** 2, "buy": 1.0})
        x = lm.features("sell", [(5, 50)], 5, 5)
        self.assertEqual((x[4], x[5], x[2]), (0.0, 1.0, 0.0))
        x = lm.features("sell", [(5, 50), (6, 52)], 6, 5)
        self.assertEqual(x[4], 1.0)  # moved away from its limit: read as firm
        x = lm.features("buy", [(5, 50), (6, 50)], 6, 5)
        self.assertEqual(x[4], 1.0)  # never moved: firm

    def test_fit_recovers_a_known_signal(self):
        rng = random.Random(5)
        X, y = [], []
        for _ in range(3000):
            a = rng.random()
            X.append([1.0, a])
            y.append(1.0 if rng.random() < 1 / (1 + 2.718281828 ** -(-2 + 4 * a)) else 0.0)
        w = lm.fit(X, y, l2=1e-6)
        self.assertAlmostEqual(w[0], -2, delta=0.35)
        self.assertAlmostEqual(w[1], 4, delta=0.6)
        self.assertLess(lm.log_loss(w, X, y), lm.log_loss([0.0, 0.0], X, y))

    def test_samples_censor_matched_traders(self):
        runs = {"b1": {"b1-1": {"side": "buy", "quotes": [(0, 10), (1, 11)], "first": 0, "last": 1, "how": "left"},
                       "b1-2": {"side": "sell", "quotes": [(0, 20), (1, 19)], "first": 0, "last": 1,
                                "how": "ours"}}}
        X, y = lm.samples_from_runs(runs)
        self.assertEqual(y, [0.0, 1.0, 0.0])  # b1-2's last tick has no label
        self.assertEqual(len(X), 3)


class Policies(unittest.TestCase):
    def test_every_family_runs_without_bad_matches(self):
        rng = random.Random(1)
        for fam in ("blind_est", "timing", "hybrid", "hybrid_est"):
            for _ in range(3):
                spec = {"family": fam, "params": pol.sample(fam, rng)}
                r = lab.evaluate(spec, "hard", 3, "test")
                self.assertEqual(r["bad"], 0, spec)
                self.assertEqual(r["n"], 12)

    def test_stall_spec_equals_the_stall(self):
        r = lab.evaluate({"family": "stall"}, "standard", 5, "test")
        self.assertEqual((r["diff"], r["dropped"], r["dropped_vs_stall"]), (0.0, 0, 0))

    def test_hybrid_with_unreachable_threshold_is_the_stall(self):
        spec = {"family": "hybrid", "params": {"model": "real", "hi": 1.01, "lo": 0.0, "delta": 1.0,
                                               "max_swaps": 3, "refill": True, "sides": "both"}}
        r = lab.evaluate(spec, "standard", 5, "test")
        self.assertEqual(r["diff"], 0.0)

    def test_blind_est_hazard_slope_runs(self):
        p = pol.BlindEstimate({"slope": "hazard"})
        tr = {"side": "buy", "quotes": [(0, 40), (1, 42), (2, 44)], "first": 0, "id": "b1-1"}
        e = p.estimate(tr, 2)
        self.assertEqual(e["kind"], "relaxing")
        self.assertGreater(e["limit"], 44)


if __name__ == "__main__":
    unittest.main()
