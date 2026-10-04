"""tools/ladder_value.py on the committed Saturday feed (ticks 160 to 1445, which no later recorder run changes):
the numbers docs/plans/ladder-sunday.md quotes. Each assertion fails if its rule is dropped: the common drift k, the
duel and other-event exclusions, the rank count, the interval a settlement falls in.

    python3 -m unittest tests.test_ladder_value
"""
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import ladder_value as lv  # noqa: E402


class TestLadderValue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = lv.Data(160, 1445)
        cls.deals = cls.d.deals()
        cls.groups = cls.d.groups(cls.deals)

    def test_the_exclusions_leave_156_single_deals(self):
        usable = [r for r in self.deals if r["change"] is not None]
        self.assertEqual(len(self.deals), 470)
        self.assertEqual(len(usable), 465)
        self.assertEqual(sum(1 for r in usable if r["duel"]), 136)                              # duel result in the interval
        self.assertEqual(sum(1 for r in usable if not r["duel"] and not r["single"]), 173)      # another event of the team
        self.assertEqual(sum(1 for r in usable if r["single"]), 156)

    def test_the_three_ernesto_deals(self):
        l5 = [r for r in self.deals if r["level"] == 5]
        self.assertEqual([(r["team"], r["T"], r["price"]) for r in l5],
                         [("t08", 1083, 120), ("t16", 1110, 116), ("t06", 1226, 120)])
        self.assertEqual([round(r["change"], 2) for r in l5], [0.14, -5.54, -2.45])    # with k; raw would be 0.10, -5.60, -2.17
        self.assertTrue(all(r["single"] and r["rank"] == 1 for r in l5))

    def test_the_drift_is_removed_with_the_quiet_teams_ratio(self):
        r = [x for x in self.deals if x["T"] == 1226][0]
        raw = 18.63 - 20.8
        self.assertAlmostEqual(r["change"] - raw, -0.28, places=2)       # k = 1.013 on 20.8: the board itself rose 0.27
        self.assertNotAlmostEqual(r["change"], raw, places=1)

    def test_the_best_three_count_and_the_rest_do_not(self):
        def med(level, top):
            return statistics.median(r["change"] for r in self.deals if r["single"] and r["level"] == level
                                     and (r["rank"] <= 3) == top)
        self.assertAlmostEqual(med(1, True), 1.18, places=2)
        self.assertAlmostEqual(med(1, False), 0.00, places=2)
        self.assertAlmostEqual(med(3, True), 0.82, places=2)
        self.assertAlmostEqual(med(4, True), 0.72, places=2)
        self.assertLess(med(4, False), 0.1)
        extra = [g for g in self.groups if g["kind"] == "extra"]
        self.assertEqual((sum(1 for g in extra if g["per_deal"] > 0.3), len(extra)), (12, 94))

    def test_groups_hold_only_dealer_deals_of_one_level(self):
        self.assertEqual((len(self.groups), sum(g["n"] for g in self.groups)), (172, 188))
        for g in self.groups:
            self.assertEqual({r["level"] for r in g["rows"]}, {g["level"]})
            self.assertEqual(g["rows"][0]["events"], len(g["rows"]))

    def test_a_settlement_lands_in_the_interval_that_contains_its_tick(self):
        placed = [r for r in self.deals if 0 <= r["i"] < len(self.d.intervals)]
        self.assertEqual(len(placed), 469)
        for r in placed:
            iv = self.d.intervals[r["i"]]
            self.assertTrue(iv["a"] < r["T"] <= iv["b"], r)

    def test_the_quiet_teams_barely_move(self):
        xs = []
        for i, iv in enumerate(self.d.intervals):
            if iv["duel"] or iv["k"] is None:
                continue
            xs += [self.d.change(tm, i) for tm in self.d.snaps[iv["a"]]
                   if tm not in iv["busy"] and self.d.snaps[iv["a"]][tm]["negotiating"] > 1]
        xs = [x for x in xs if x is not None]
        self.assertEqual(len(xs), 1015)
        self.assertLess(abs(statistics.median(xs)), 0.005)


if __name__ == "__main__":
    unittest.main()
