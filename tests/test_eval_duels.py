"""tools/eval_duels.py: the harness checks on frozen Friday duels (three pairs from tests/fixtures/duels_friday).

null never deals and scores 0, reckless lights up limit_breach, the oracle takes the best slot-feasible offers, the
score is the engine's own number, and no rival text reaches a row or a trace.

Run: python3 -m unittest tests.test_eval_duels
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRIDAY_DUELS = Path(__file__).resolve().parent / "fixtures" / "duels_friday"
sys.path.insert(0, str(ROOT / "tools"))
import eval_common as ec  # noqa: E402
import eval_duels as ed  # noqa: E402

# three pairs (soft pie from the partner), two deadline waves, all with rival prices; in 37 duel.py speaks (a round)
DUELS = (9, 10, 37, 38, 93, 94)


class FridayChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        (t / "logs" / "duels").mkdir(parents=True)
        for i in DUELS:
            shutil.copy(FRIDAY_DUELS / f"duel-{i:05d}.json", t / "logs" / "duels")
        cls.logs = t / "logs"
        saved = ec.EVALS
        cls.rows = {}
        try:
            for pol in ("duel", "oracle", "null", "reckless"):
                with redirect_stdout(io.StringIO()):
                    ed.main(["--flow", "duels-friday", "--logs", str(cls.logs), "--out-root", str(t / pol),
                             "--policy", pol])
                d = t / pol / "duels-friday" / "baseline"
                cls.rows[pol] = {r["prompt_id"]: r for r in map(json.loads, (d / "results.jsonl").read_text()
                                                                .splitlines())}
                cls.rows[pol + "_dir"] = d
        finally:
            ec.EVALS = saved

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def grades(self, pol, key):
        return [r["grade"][key] for r in self.rows[pol].values()]

    def test_every_fixture_duel_is_a_case(self):
        for pol in ("duel", "oracle", "null", "reckless"):
            self.assertEqual(sorted(self.rows[pol]), [f"fri-{i:04d}" for i in DUELS])

    def test_null_never_deals_scores_zero_and_misses_the_in_limit_offers(self):
        self.assertEqual(self.grades("null", "deal"), [0] * len(DUELS))
        self.assertEqual(self.grades("null", "score"), [0.0] * len(DUELS))
        self.assertEqual(self.grades("null", "missed_ok_offer"), [1] * len(DUELS))   # every rival ended inside
        self.assertEqual(self.grades("null", "limit_breach"), [0] * len(DUELS))

    def test_reckless_lights_up_limit_breach_and_duel_py_never_does(self):
        self.assertEqual(self.grades("reckless", "limit_breach"), [1] * len(DUELS))
        self.assertEqual(self.grades("duel", "limit_breach"), [0] * len(DUELS))
        self.assertEqual(self.grades("oracle", "limit_breach"), [0] * len(DUELS))

    def test_oracle_takes_every_duel_near_the_best_offer(self):
        o = self.rows["oracle"]
        self.assertEqual(self.grades("oracle", "deal"), [1] * len(DUELS))
        self.assertEqual(self.grades("oracle", "missed_ok_offer"), [0] * len(DUELS))
        mean = sum(self.grades("oracle", "score")) / len(DUELS)
        self.assertGreaterEqual(mean + 1e-9, sum(self.grades("duel", "score")) / len(DUELS))
        ceiling = sum(r["best_offer_score"] for r in o.values()) / len(DUELS)
        self.assertGreaterEqual(mean, 0.9 * ceiling)       # what one accept per tick leaves of the ceiling
        self.assertTrue(all(r["rounds"] == 0 and r["msgs_sent"] == 0 for r in o.values()))

    def test_score_is_the_engine_score(self):
        self.assertTrue(any(r["rounds"] > 0 for r in self.rows["duel"].values()))   # decay is exercised
        files = ed.arena.friday_duels(self.logs / "duels", 1)
        params, _ = ed.load_params(str(ed.BASELINE_PARAMS))
        engine = {r["duel"]: r for r in ed.arena.friday_replay(params, files=files)}
        for i in DUELS:
            row = self.rows["duel"][f"fri-{i:04d}"]
            self.assertAlmostEqual(row["grade"]["score"], ed.clip(engine[i]["score"]), places=4)
            self.assertEqual(row["grade"]["deal"], int(engine[i]["deal"]))

    def test_no_rival_text_in_rows_or_traces(self):
        texts = set()
        for i in DUELS:
            x = json.loads((FRIDAY_DUELS / f"duel-{i:05d}.json").read_text())
            texts |= {m["text"] for m in x.get("messages") or [] if m.get("from") != "you" and len(m.get("text")
                                                                                                   or "") >= 12}
        self.assertTrue(texts)
        for pol in ("duel", "oracle", "null", "reckless"):
            d = self.rows[pol + "_dir"]
            blob = (d / "results.jsonl").read_text() + "".join(p.read_text() for p in (d / "traces").glob("*.json"))
            for t in texts:
                self.assertNotIn(t[:40], blob)


class OraclePlan(unittest.TestCase):
    def test_one_accept_per_tick_maximises_the_total(self):
        cfg = type("C", (), {"late_poll": 0, "late_ticks": 1})()
        rec = ed.Recorder()
        # duel 1 best at tick 10 (0.9), duel 2 best at tick 10 too (0.8) but 0.7 at tick 9: 1 -> 10, 2 -> 9
        for did, path in ((1, {9: 50, 10: 90}), (2, {9: 70, 10: 80})):
            rec.deadline[did] = 12
            for t, s in path.items():
                rec.calls[did].append((t, (s, None), {}))
        plan = ed.oracle_plan(rec, lambda did, o: (o[0] / 100, o[0]), cfg)
        self.assertEqual(plan, {1: (10, 90), 2: (9, 70)})


if __name__ == "__main__":
    unittest.main()
