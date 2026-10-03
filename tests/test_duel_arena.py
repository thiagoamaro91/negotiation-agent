"""tools/duel_arena.py and tools/duel_tune.py: scoring as the rules describe it, the measured rounds rule, one
accept per tick, our limit, and tuned params that load through agent/duel.py's own --params path.

Run: python3 -m unittest discover tests
"""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Friday's 18 closed practice duels, frozen as committed before the Saturday log block (logs/duels/ keeps growing).
FRIDAY_DUELS = Path(__file__).resolve().parent / "fixtures" / "duels_friday"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import duel  # noqa: E402
import duel_arena as arena  # noqa: E402
import duel_tune as tune  # noqa: E402


def one_duel(role="seller", ours=100, theirs=150, kind="absent", decay=0.06, days=None, rp=None):
    return arena.Duel(1, 0, role, ours, theirs, kind, rp or {}, 16, decay,
                      ["price", "days"] if days else ["price"], days)


class Scoring(unittest.TestCase):
    def test_share_of_the_pie_times_decay_per_round(self):
        dl = one_duel("seller", 100, 150)                       # pie 50
        self.assertEqual(arena.score_deal(dl, 140, None, 0), (0.8, 0.8))
        share, score = arena.score_deal(dl, 140, None, 2)
        self.assertAlmostEqual(share, 0.8)
        self.assertAlmostEqual(score, 0.8 * 0.94 ** 2)
        buyer = one_duel("buyer", 150, 100, decay=0.1)          # we buy: value 150, rival cost 100
        self.assertAlmostEqual(arena.score_deal(buyer, 110, None, 1)[1], 0.8 * 0.9)

    def test_a_deal_outside_our_limit_loses_points_and_no_decay_softens_it(self):
        dl = one_duel("seller", 100, 150)
        share, score = arena.score_deal(dl, 90, None, 3)        # sold 10 under cost
        self.assertAlmostEqual(share, -0.2)
        self.assertAlmostEqual(score, -0.2)
        self.assertEqual(arena.score_deal(dl, 10, None, 0), (-1.0, -1.0))   # floored at -1
        self.assertLess(arena.score_deal(one_duel("buyer", 150, 100), 151, None, 0)[1], 0)

    def test_no_deal_scores_zero(self):
        res = arena.play_session([one_duel("seller", 100, 150, kind="absent")], {**arena.SESSIONS[1], "concurrent": 1},
                                 arena.cfg_for({}, 16), 1)
        self.assertEqual((res[0]["deal"], res[0]["score"]), (False, 0.0))

    def test_two_issues_the_pie_is_the_best_joint_pie_over_days(self):
        days = {"ours": (10, 1.0), "rival": (0, 3.0)}           # we sell and want day 10; the buyer wants day 0
        dl = one_duel("seller", 100, 150, days=days)
        self.assertEqual(dl.pie(), 40.0)                        # day 0 is efficient: 50 - 1 x 10 - 3 x 0
        self.assertAlmostEqual(arena.score_deal(dl, 140, 0, 0)[0], (140 - 100 - 10) / 40)
        self.assertAlmostEqual(arena.score_deal(dl, 140, 10, 0)[0], 40 / 40)


class RoundsRule(unittest.TestCase):
    def test_a_round_needs_both_sides(self):
        for rule in ("exchange", "min"):
            self.assertEqual(arena.rounds_of([], rule), 0)
            self.assertEqual(arena.rounds_of([(1, "them"), (2, "them"), (3, "them")], rule), 0)
            self.assertEqual(arena.rounds_of([(1, "us"), (2, "us")], rule), 0)
            self.assertEqual(arena.rounds_of([(1, "them"), (2, "us")], rule), 1)
            self.assertEqual(arena.rounds_of([(1, "us"), (2, "them")], rule), 1)
            self.assertEqual(arena.rounds_of([(1, "them"), (2, "us"), (3, "them"), (4, "us")], rule), 2)
        self.assertEqual(arena.rounds_of([(1, "them"), (2, "us"), (3, "us"), (4, "them")], "exchange"), 1)
        self.assertEqual(arena.rounds_of([(1, "them"), (2, "us"), (3, "us"), (4, "them")], "min"), 2)

    def test_both_rules_reproduce_all_18_friday_duels(self):
        files = sorted(f for f in FRIDAY_DUELS.glob("duel-*.json") if "-first" not in f.name)
        self.assertEqual(len(files), 18)
        for f in files:
            d = json.loads(f.read_text())
            seq = [(m["tick"], "us" if m.get("from") == "you" else "them") for m in d.get("messages") or []]
            for rule in ("exchange", "min"):
                self.assertEqual(arena.rounds_of(seq, rule), d["rounds"], f"{f.name} {rule}")

    def test_in_play_an_opening_to_a_silent_rival_costs_no_round(self):
        cfg = arena.cfg_for({"max_msgs": 3, "absent_last": True}, 16)
        res = arena.play_session([one_duel("seller", 100, 150, kind="absent")],
                                 {**arena.SESSIONS[1], "concurrent": 1}, cfg, 1)
        self.assertEqual(res[0]["sent"], 2)                      # the absent offer and the last chance
        self.assertEqual(res[0]["rounds"], 0)


class OneAcceptPerTick(unittest.TestCase):
    def test_never_two_of_our_accepts_in_one_tick_across_a_wave(self):
        params = {"accept_any_ticks": 6, "early_share": 0.3, "window_wait": False}
        res = arena.evaluate(params, range(40), 1)
        ours = {}
        for r in res:
            if r["deal"] and r["by"] == "us":
                k = (r["seed"], r["wave"], r["tick"])
                ours[k] = ours.get(k, 0) + 1
        self.assertGreater(len(ours), 200)
        self.assertEqual(max(ours.values()), 1)

    def test_a_busy_slot_costs_deals(self):
        params = {"accept_any_ticks": 1, "near_ticks": -1, "early_share": 2.0}
        free = sum(r["deal"] for r in arena.evaluate(params, range(30), 1))
        busy = sum(r["deal"] for r in arena.evaluate(params, range(30), 1, slot_busy=0.5))
        self.assertLess(busy, free)


    def test_unsettled_deadline_minus_one_accepts_score_nothing(self):
        params = {"accept_any_ticks": 1, "near_ticks": -1, "early_share": 2.0, "window_wait": False}
        on = arena.evaluate(params, range(20), 1)
        off = arena.evaluate(params, range(20), 1, d1_settles=False)
        late = {(r["seed"], r["duel"]) for r in on if r["deal"] and r["at"] == 15}
        lost = {(r["seed"], r["duel"]) for r in off if r.get("lost_at_d1")}
        self.assertGreater(len(late), 20)
        self.assertEqual(late, lost)
        self.assertTrue(all(r["score"] == 0 and not r["deal"] for r in off if r.get("lost_at_d1")))


class OurLimit(unittest.TestCase):
    def test_never_offer_or_accept_across_our_limit(self):
        """Random params (the tuner's own generator), both sessions: every number we say is strictly inside our
        limit, and every deal (ours or theirs) is inside it with a non-negative share."""
        said, bad = [], []
        real = duel.decide

        def spy(d, st, tick, cfg):
            dec = real(d, st, tick, cfg)
            if dec["action"] == "say":
                said.append(1)
                lim, p = d["your_limit"], dec["price"]
                if (p <= lim) if d["role"] == "seller" else (p >= lim):
                    bad.append((d["duel"], d["role"], lim, p, dec["why"]))
            return dec
        rng = random.Random(7)
        duel.decide = spy
        try:
            for session in (1, 2):
                for i in range(25):
                    p = tune.random_params(rng, session)
                    if i % 2:
                        p.update(pair_sell=rng.uniform(0.5, 1.3), pair_buy=rng.uniform(0.7, 1.5), absent_at=0.0,
                                 absent_share=rng.choice([0.0, rng.uniform(0, 1)]), absent_last=True)
                    for r in arena.evaluate(p, range(i * 10, i * 10 + 4), session):
                        if r["deal"]:
                            self.assertTrue(r["inside"], r)
                            self.assertGreaterEqual(r["share"], 0, r)
        finally:
            duel.decide = real
        self.assertGreater(len(said), 1000)
        self.assertEqual(bad, [])

    def test_friday_replay_reads_only_structure_and_scores_the_closed_duels(self):
        rr = arena.friday_replay({}, files=arena.friday_duels(FRIDAY_DUELS))
        scored = [r for r in rr if r["scored"]]
        self.assertEqual(sorted(r["duel"] for r in scored), [9, 10, 29, 30, 37, 38, 93, 94])
        for r in scored:
            if r["deal"]:
                self.assertGreaterEqual(r["share"], 0)


class ParamsFile(unittest.TestCase):
    """The tuner's output is a duel.py --params file: duel.py's own loader reads it, unchanged."""

    def tuning_values(self, cfg) -> dict:
        return {k: v for k, v in duel.params_of(cfg).items() if k != "mirror"}

    def test_empty_params_are_duel_py_defaults(self):
        self.assertEqual(self.tuning_values(arena.cfg_for({}, 16)), self.tuning_values(duel.make_cfg(["watch"])))

    def test_a_tuned_file_loads_through_make_cfg_exactly_as_the_arena_used_it(self):
        rng = random.Random(3)
        for session in (1, 2):
            p = tune.random_params(rng, session)
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "duel-params.json"
                f.write_text(json.dumps({**tune.flat_to_file(p), "duel_ticks": 16}))
                live = duel.make_cfg(["run", "--params", str(f)])
                self.assertEqual(self.tuning_values(live), self.tuning_values(arena.cfg_for(p, 16)))
                for k in tune.TUNABLE:
                    self.assertEqual(getattr(live, k), p[k], k)
                self.assertEqual(duel.make_cfg(["run", "--params", str(f), "--max-msgs", "1"]).max_msgs, 1)

    def test_unknown_keys_are_refused_by_duel_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bad.json"
            f.write_text(json.dumps({"quiet_ticks": 3}))
            with self.assertRaises(SystemExit):
                arena.load_policy(f)

    def test_the_committed_duels1_params_load_and_change_only_what_they_name(self):
        base = self.tuning_values(duel.make_cfg(["run"]))
        for name in ("duel-params-duels1.json", "duel-params-duels1-safe.json"):
            f = ROOT / "docs" / "duel-lab" / name
            p = arena.load_policy(f)
            self.assertTrue(set(p) <= set(tune.TUNABLE), name)
            got = self.tuning_values(duel.make_cfg(["run", "--params", str(f)]))
            self.assertEqual({k for k in got if got[k] != base[k]}, set(p), name)
            self.assertEqual((got["min_surplus"], got["duel_ticks"]), (1, 16))


if __name__ == "__main__":
    unittest.main()
