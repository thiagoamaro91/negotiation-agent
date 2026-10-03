"""Confidence, reliability and calibration in tools/value_inference.py. Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import value_inference as vi  # noqa: E402

SETS = ["LAV", "MAL", "LAT", "SAL", "RET", "CHA"]
IN_PLAY = SETS[:5]
BOOK = {f"{s}-{n:02d}": 10 for s in SETS for n in range(1, 11)}


def choose(tick, ref):
    return {"tick": tick, "kind": "choose", "set": vi.set_of(ref), "ref": ref, "price": None, "how": "test"}


def floor(tick, ref, price):
    return {"tick": tick, "kind": "floor", "set": vi.set_of(ref), "ref": ref, "price": price, "how": "test"}


class Label(unittest.TestCase):
    def test_a_likely_favourite_on_few_choices_is_not_strong(self):
        # t01 on Friday: favourite at 95 % from five LAV asks to Abuela = 2.3 choice-equivalents
        self.assertEqual(vi.confidence_label(0.95, 2.28), "some")
        self.assertEqual(vi.confidence_label(0.95, 1.0), "weak")

    def test_strong_needs_both_probability_and_evidence(self):
        self.assertEqual(vi.confidence_label(0.95, 4.0), "strong")
        self.assertEqual(vi.confidence_label(0.59, 10.0), "some")
        self.assertEqual(vi.confidence_label(0.39, 10.0), "weak")

    def test_choices_of_one_set_count_one_over_k(self):
        evs = [choose(i, f"LAV-0{i}") for i in range(1, 6)] + [floor(6, "LAV-01", 9), choose(7, "MAL-01")]
        self.assertAlmostEqual(vi.choice_weight(evs), 1 + 1 / 2 + 1 / 3 + 1 / 4 + 1 / 5 + 1)

    def test_summary_labels_t01_like_evidence_some_not_strong(self):
        m = vi.Model(SETS, IN_PLAY, BOOK)
        evs = [choose(i, f"LAV-0{i}") for i in range(1, 6)] + [floor(i, f"LAV-0{i}", 9) for i in range(1, 6)]
        r = m.summary(m.posterior(evs), evs)
        self.assertEqual(r["favourite"], "LAV")
        self.assertGreaterEqual(r["p_favourite"], vi.STRONG_P)   # the old rule called this "strong"
        self.assertEqual(r["confidence"], "some")
        self.assertEqual(r["n_evidence"], 10)


class Reliability(unittest.TestCase):
    def test_bins_count_mean_and_observed(self):
        rows = vi.reliability([(0.25, True), (0.35, False), (0.3, False), (0.65, True), (0.62, False)])
        by = {(b["lo"], b["hi"]): b for b in rows}
        self.assertEqual(by[(0.0, 0.3)]["n"], 1)
        self.assertEqual(by[(0.0, 0.3)]["observed"], 1.0)
        self.assertEqual(by[(0.3, 0.4)]["n"], 2)   # a bin includes its lower edge
        self.assertEqual(by[(0.3, 0.4)]["observed"], 0.0)
        self.assertEqual(by[(0.6, 0.7)]["n"], 2)
        self.assertAlmostEqual(by[(0.6, 0.7)]["predicted"], 0.635)
        self.assertEqual(by[(0.6, 0.7)]["observed"], 0.5)
        self.assertEqual(sum(b["n"] for b in rows), 5)

    def test_time_split_reports_the_naive_baseline_and_the_table(self):
        m = vi.Model(SETS, IN_PLAY, BOOK)
        by_team = {"tA": [choose(1, "LAV-01"), choose(2, "LAV-02"), choose(3, "MAL-01")]}
        r = m.time_split(by_team)
        self.assertEqual(r["n"], 3)
        self.assertAlmostEqual(r["naive_hit"], 1 / 3)  # no past at the first choice, 'repeat LAV' right once, then wrong
        self.assertEqual(len(r["reliability"]), len(vi.RELIABILITY_BINS) - 1)
        self.assertEqual(sum(b["n"] for b in r["reliability"]), 3)
        self.assertEqual(sum(v["n"] for v in r["by_label"].values()), 3)
        self.assertIn("no evidence", r["by_label"])  # the first choice had nothing before it


class Calibration(unittest.TestCase):
    def test_an_overconfident_model_keeps_less_than_all_of_its_confidence(self):
        sets = ["A", "B", "C", "D"]
        sure = {"A": 0.97, "B": 0.01, "C": 0.01, "D": 0.01}
        preds = [(sure, "A")] * 5 + [(sure, "B")] * 5  # says 97 %, right half the time
        lam, _ = vi.fit_shrink(preds)
        self.assertGreater(lam, 0.0)
        self.assertLess(lam, 1.0)

    def test_a_model_that_is_always_right_keeps_it_all_and_one_always_wrong_keeps_none(self):
        sure = {"A": 0.97, "B": 0.01, "C": 0.01, "D": 0.01}
        self.assertEqual(vi.fit_shrink([(sure, "A")] * 10)[0], 1.0)
        self.assertEqual(vi.fit_shrink([(sure, "B")] * 10)[0], 0.0)

    def test_shrink_pulls_toward_uniform_and_stays_a_distribution(self):
        d = {1.6: 1.0, 1.3: 0.0, 1.1: 0.0, 0.9: 0.0, 0.7: 0.0, 0.5: 0.0}
        s = vi.shrink(d, 0.7)
        self.assertAlmostEqual(s[1.6], 0.7 + 0.3 / 6)
        self.assertAlmostEqual(s[0.5], 0.3 / 6)
        self.assertAlmostEqual(sum(s.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
