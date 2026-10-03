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
        with knobs(DAYS_MODEL="distance"):                      # the pre-Duels II guess: w x |day - best|
            dl = one_duel("seller", 100, 150, days=days)
            self.assertEqual(dl.pie(), 40.0)                    # day 0 is efficient: 50 - 1 x 10 - 3 x 0
            self.assertAlmostEqual(arena.score_deal(dl, 140, 0, 0)[0], (140 - 100 - 10) / 40)
            self.assertAlmostEqual(arena.score_deal(dl, 140, 10, 0)[0], 40 / 40)
        dl = one_duel("seller", 100, 150, days=days)            # the server: the seller earns 1/day, the buyer pays 3
        self.assertEqual(dl.pie(), 50.0)                        # day 0 still: 50 + 1 x 0 - 3 x 0
        self.assertAlmostEqual(arena.score_deal(dl, 140, 0, 0)[0], 40 / 50)
        self.assertAlmostEqual(arena.score_deal(dl, 140, 10, 0)[0], (140 - 100 + 10) / 50)

    def test_the_referee_pays_what_the_duels2_server_paid(self):
        # Saturday's Duels II results (logs/duel, event "result"): our seller surplus x 0.92 ** rounds.
        # 5692: cost 53, w 2.36, sold at 87 on day 10, 1 round -> 53.0; 5626: cost 88, w 1.12, 132 on day 0, 1 round
        # -> 40.5; 5675: cost 30, w 2.26, 66 on day 0, no round -> 36.0. The old guess gave 10.5, 30.2 and 13.4.
        for cost, w, price, day, rounds, result in ((53, 2.36, 87, 10, 1, 53.0), (88, 1.12, 132, 0, 1, 40.5),
                                                     (30, 2.26, 66, 0, 0, 36.0)):
            dl = one_duel("seller", cost, 2 * cost, days={"ours": (10, w), "rival": (0, 1.0)})
            self.assertAlmostEqual(dl.our_surplus(price, day) * 0.92 ** rounds, result, places=1)
        buyer = one_duel("buyer", 150, 100, days={"ours": (0, 2.0), "rival": (10, 1.0)})
        self.assertEqual(buyer.our_surplus(120, 4), 150 - 120 - 2.0 * 4)   # a buyer pays w per day from day 0


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


class knobs:
    """Set arena module globals for a block, restore them after (the days-world knobs, DAYS_FLIP, ARENA_DAYS...)."""

    def __init__(self, **kw):
        self.kw, self.saved = kw, {}

    def __enter__(self):
        self.saved = {k: getattr(arena, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(arena, k, v)

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(arena, k, v)


def duels2(seed=0):
    return arena.make_session(seed, arena.SESSIONS[2], arena.FITTED + arena.CLASSIC)


class DaysWorld(unittest.TestCase):
    """The days-world knobs (DAYS_W, DAYS_W_REL, DAYS_COMPAT, RIVAL_DMODE) and the days lab."""

    def fingerprint(self):
        import hashlib
        res = arena.evaluate({}, range(3), 2)
        key = [(r["seed"], r["duel"], r["score"], r.get("price"), r.get("day")) for r in res]
        return (len(res), sum(r["deal"] for r in res), round(sum(r["score"] for r in res), 4),
                hashlib.sha256(repr(key).encode()).hexdigest())

    def test_default_knobs_replay_the_arena_from_before_the_knobs(self):
        # measured on 9cf97d3 (before the knobs existed): 204 duels, 86 deals, score sum 39.9354, mean 0.19576
        # (the referee of that time: DAYS_MODEL "distance"; the server model changes the scores by design)
        before = (204, 86, 39.9354, "3aa66e5a9dac7b27aad67ff0c4d999999028342822805a84a631691b0d101c7d")
        with knobs(DAYS_MODEL="distance"):
            self.assertEqual(self.fingerprint(), before)
            with knobs(DAYS_W=(0.0, 4.0), DAYS_W_REL=None, DAYS_COMPAT=0.0, RIVAL_DMODE=None):
                self.assertEqual(self.fingerprint(), before)

    def test_the_knobs_never_touch_the_scenario_rng(self):
        def shape(ds):
            return [(d.id, d.pair, d.role, d.kind, d.our_limit, d.rival_limit) for d in ds]
        base = shape(duels2(4))
        for kw in ({"DAYS_COMPAT": 0.5}, {"RIVAL_DMODE": {"random": 1, "mid": 1}}, {"DAYS_W": (2.0, 8.0)},
                   {"DAYS_W_REL": (0.005, 0.04)}, {"RIVAL_DMODE": {"ignore": 1}}):
            with knobs(**kw):
                self.assertEqual(shape(duels2(4)), base, kw)

    def test_compat_one_gives_both_sides_the_same_best_day(self):
        seen = set()
        with knobs(DAYS_COMPAT=1.0):
            for seed in range(3):
                for dl in duels2(seed):
                    self.assertEqual(dl.days["ours"][0], dl.days["rival"][0])
                    seen.add(dl.days["ours"][0])
                    default = 0 if dl.role == "buyer" else 10
                    w = arena.server_view(dl, 2, 99)["your_days_weight"]
                    self.assertEqual(w < 0, dl.days["ours"][0] != default and dl.days["ours"][1] > 0)
        self.assertEqual(seen, {0, 10})
        for dl in duels2(0):                                   # default: opposed, buyer 0, seller 10
            self.assertNotEqual(dl.days["ours"][0], dl.days["rival"][0])

    def test_ignore_gives_the_rival_weight_zero_and_it_names_our_day(self):
        base = duels2(1)
        with knobs(RIVAL_DMODE={"ignore": 1}):
            ign = duels2(1)
        for a, b in zip(base, ign):
            self.assertEqual(b.rival.days[1], 0.0)
            self.assertEqual(b.days["ours"], a.days["ours"])
            self.assertEqual(b.rival.day_for((100, 7)), 7)
            self.assertEqual(b.rival.day_for(None), 0)
        self.assertTrue(any(a.rival.days[1] > 0 for a in base))

    def test_weight_ranges_rescale_the_same_draws(self):
        base = duels2(2)
        with knobs(DAYS_W=(2.0, 8.0)):
            heavy = duels2(2)
        with knobs(DAYS_W=(0.0, 1.0)):
            light = duels2(2)
        with knobs(DAYS_W_REL=(0.005, 0.04)):
            rel = duels2(2)
        for a, h, li, r in zip(base, heavy, light, rel):
            for side in ("ours", "rival"):
                w0 = a.days[side][1]
                self.assertAlmostEqual(h.days[side][1], 2.0 + 1.5 * w0, delta=0.02)
                self.assertAlmostEqual(li.days[side][1], w0 / 4, delta=0.01)
                self.assertTrue(0.005 * 65 - 0.01 <= r.days[side][1] <= 0.04 * 134 + 0.01)
        self.assertGreater(sum(h.days["ours"][1] for h in heavy), 1.9 * sum(a.days["ours"][1] for a in base))

    def test_mid_best_and_random_day_modes(self):
        with knobs(RIVAL_DMODE={"mid": 1}):
            self.assertTrue(all(d.rival.day_for((100, 2)) == 5 for d in duels2(0)))
        with knobs(RIVAL_DMODE={"best": 1}):
            self.assertTrue(all(d.rival.day_for((100, 2)) == d.rival.days[0] for d in duels2(0)))
        with knobs(RIVAL_DMODE={"random": 1}):
            a = [[d.rival.day_for(None) for _ in range(5)] for d in duels2(0)]
            b = [[d.rival.day_for(None) for _ in range(5)] for d in duels2(0)]
        self.assertEqual(a, b)                                  # seeded from (seed, pair, duel)
        days = {x for row in a for x in row}
        self.assertTrue(days <= set(range(11)) and len(days) > 5)

    def test_days_lab_has_one_row_per_variant_and_restores_the_globals(self):
        before = (arena.ARENA_DAYS, arena.PAIR_SEEN, arena.DAYS_FLIP, arena.RIVAL_DMODE, arena.DAYS_W)
        lines = arena.days_lab({"defaults": {}}, range(1)).splitlines()
        self.assertEqual(before, (arena.ARENA_DAYS, arena.PAIR_SEEN, arena.DAYS_FLIP, arena.RIVAL_DMODE,
                                  arena.DAYS_W))
        self.assertEqual(len(lines), 2 + len(arena.DAYS_STRESS))
        self.assertIn("defaults confirmed WRONG", lines[0])
        for (label, mods), line in zip(arena.DAYS_STRESS, lines[2:]):
            cells = [c.strip() for c in line.strip("|").split("|")]
            self.assertEqual(cells[0], label)
            self.assertEqual(len(cells), 4)
            self.assertNotEqual(cells[1], "-")
            self.assertNotEqual(cells[2], "-")
            self.assertEqual(cells[3] == "-", not mods.get("DAYS_FLIP"), label)


if __name__ == "__main__":
    unittest.main()


class ForcedDayModes(unittest.TestCase):
    """Codex on #47: the logroller and the splitter must follow a forced days world (RIVAL_DMODE) like the others."""

    def test_logroller_and_splitter_follow_rival_dmode(self):
        for kind in ("logroll", "split"):
            rp = {**arena._kind_params(kind, __import__("random").Random(1), 16, __import__("random").Random(1).uniform,
                                       {}, False), "dmode": "mid"}
            r = arena.KINDS[kind]("buyer", 120, 16, rp, (0, 2.0))
            r._msgs = [(1, 140, 10), (2, 138, 10)]          # we held day 10 twice: a logroller would follow it
            self.assertEqual(r.day_for((138, 10)), 5, kind)
        sp = arena.KINDS["split"]("buyer", 120, 16, {"m0": 0.3, "m_floor": 0.0, "tol": 0.0, "e0": 0, "dmode": "mid"},
                                  (0, 2.0))
        sp.act(0, {"our_offer": None, "our_msgs": []})
        out = sp.act(1, {"our_offer": (150, 10), "our_msgs": [(1, 150, 10)]})
        self.assertEqual(out["say"][1], 5)                   # not the midpoint of its day and ours
