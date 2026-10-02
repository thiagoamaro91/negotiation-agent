"""Pure rules of tools/market_plan.py. Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import market_plan as mp  # noqa: E402


class Fee(unittest.TestCase):
    def test_matches_every_settlement_seen_on_friday(self):
        # (price, fee) pairs read from team-to-team settlements in logs/feed on 2 Oct 2026
        for price, seen in ((9, 2), (12, 2), (21, 3), (26, 3), (53, 4), (65, 5), (80, 5)):
            self.assertEqual(mp.fee(price), seen, price)

    def test_one_extra_primas_per_card(self):
        self.assertEqual(mp.fee(80, cards=2), mp.fee(80) + 1)


class CopyValue(unittest.TestCase):
    MARGINALS = [1.0, 0.25, 0.1]

    def test_first_second_third_copy(self):
        self.assertAlmostEqual(mp.copy_value(70, 1.6, 0, self.MARGINALS), 112.0)
        self.assertAlmostEqual(mp.copy_value(25, 0.7, 1, self.MARGINALS), 4.375)
        self.assertAlmostEqual(mp.copy_value(10, 1.0, 5, self.MARGINALS), 1.0)  # past the table: last marginal


class Demand(unittest.TestCase):
    DIST = {1.6: 0.5, 1.3: 0.3, 1.1: 0.2, 0.9: 0.0, 0.7: 0.0, 0.5: 0.0}

    def test_chance_a_team_values_a_card_at_a_price(self):
        self.assertAlmostEqual(mp.p_value_at_least(self.DIST, 70, 1.0, 91), 0.8)    # 1.3 x 70 = 91 counts
        self.assertAlmostEqual(mp.p_value_at_least(self.DIST, 70, 1.0, 100), 0.5)
        self.assertAlmostEqual(mp.p_value_at_least(self.DIST, 70, 0.25, 30), 0.0)   # a second copy is worth 25 %

    def test_chance_a_holder_parts_with_it(self):
        self.assertAlmostEqual(mp.p_value_at_most(self.DIST, 70, 1.0, 77), 0.2)

    def test_any_of_independent_takers(self):
        self.assertAlmostEqual(mp.any_of([0.5, 0.5]), 0.75)
        self.assertEqual(mp.any_of([]), 0.0)

    def test_an_offer_posted_tonight_carries_over(self):
        # 40 % it fills tonight at half weight, else 50 % tomorrow at full weight
        self.assertAlmostEqual(mp.carry_over(0.4, 0.5, 0.5, 1.0), 0.4 * 0.5 + 0.6 * 0.5)
        self.assertAlmostEqual(mp.carry_over(0.0, 0.5, 0.7, 1.0), 0.7)


if __name__ == "__main__":
    unittest.main()
