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


class ScoredLikeTheGame(unittest.TestCase):
    def test_a_team_buy_scores_value_minus_price_minus_our_fee(self):
        self.assertEqual(mp.trade_gain("buy", 100, 112, we_accept=True), 112 - 100 - mp.fee(100))
        self.assertEqual(mp.trade_gain("buy", 100, 112, we_accept=False), 12)  # our bid: the seller accepts and pays

    def test_a_team_sale_scores_price_minus_fee_minus_that_copys_value(self):
        # t14's 55 P bid for LAV-07 (worth 40 to us): +11 after the 4 P fee (analysis-friday section 10)
        self.assertEqual(mp.trade_gain("sell", 55, 40, we_accept=True), 11)
        # our MAL-06 spare (4.375 = 25 % of 17.5) listed at 24 and taken: no fee for us
        self.assertAlmostEqual(mp.trade_gain("sell", 24, 4.375, we_accept=False), 19.625)

    def test_no_estimated_chance_is_a_certainty(self):
        self.assertLess(mp.cap(1.0), 1.0)
        self.assertEqual(mp.cap(-0.2), 0.0)
        self.assertEqual(mp.cap(0.3), 0.3)


class Ladder(unittest.TestCase):
    CHATO_UNCOMMON = {"side": "sells", "opening": 33, "low": 28, "median": 29, "high": 32}
    ABUELA_BUYS = {"side": "buys", "opening": 5, "low": 6, "median": 6, "high": 6}

    def test_best_three_with_missing_ones_at_zero(self):
        self.assertEqual(mp.ladder_slots([0.8]), [0.8, 0.0, 0.0])
        self.assertEqual(mp.ladder_slots([0.2, 0.9, 0.5, 0.7]), [0.9, 0.7, 0.5])

    def test_a_deal_only_adds_what_it_beats(self):
        self.assertAlmostEqual(mp.ladder_gain([0.8, 0.0, 0.0], 0.4), 0.4 / 3)
        self.assertEqual(mp.ladder_gain([0.9, 0.9, 0.9], 0.4), 0.0)

    def test_fridays_chato_deals_score_only_below_our_value(self):
        # SAL-08 at 29 (worth 32.5) scored; LAT-06 at 28 and LAT-07 at 29 (worth 27.5) did not
        self.assertEqual(mp.deal_share(self.CHATO_UNCOMMON, 29, 33, 32.5), 0.8)
        self.assertEqual(mp.deal_share(self.CHATO_UNCOMMON, 28, 33, 27.5), 0.0)
        saved = mp.LADDER_VALUE_GATE
        try:
            mp.LADDER_VALUE_GATE = False
            self.assertEqual(mp.deal_share(self.CHATO_UNCOMMON, 28, 33, 27.5), 1.0)
        finally:
            mp.LADDER_VALUE_GATE = saved

    def test_a_deal_at_the_dealers_opening_scores_nothing(self):
        self.assertEqual(mp.deal_share(self.CHATO_UNCOMMON, 33, 33, 50), 0.0)
        self.assertEqual(mp.deal_share({"side": "sells", "opening": 30, "low": 19, "median": 22, "high": 24}, 17, 17, None), 0.0)

    def test_a_sale_to_a_dealer_mirrors_the_gate(self):
        self.assertEqual(mp.deal_share(self.ABUELA_BUYS, 6, 5, 4.0), 1.0)   # a LAV common spare (worth 4) at 6
        self.assertEqual(mp.deal_share(self.ABUELA_BUYS, 6, 5, 16.0), 0.0)  # a first copy worth 16: below value

    def test_no_measured_range_means_no_estimate(self):
        self.assertIsNone(mp.deal_share(None, 50, 60, 70))

    def test_the_ladder_resets_with_the_day(self):
        events = [{"tick": 0, "type": "day.opened"}, {"tick": 50, "type": "settlement"}, {"tick": 160, "type": "day.opened"}]
        self.assertEqual(mp.day_start_tick(events), 160)
        self.assertEqual(mp.day_start_tick([]), 0)


class PlanOnTheCommittedFeed(unittest.TestCase):
    """The whole plan on the committed feed (logs/feed, Friday to tick 146) and our committed snapshot, offline: the
    keyless reads are replaced by a closed Friday clock, an empty schedule, both dealers and an empty board."""
    DEALERS = {"personas": [
        {"id": "abuela", "status": "active", "enabled": True, "unlock": {"always": True}, "open_to_all": True,
         "menu": {"sells": [{"pack": "sobre_barrio", "list_price": 26, "opening_ask": 30},
                            {"rarity": "common", "list_price": 10}, {"rarity": "uncommon", "list_price": 25}]}},
        {"id": "chato", "status": "active", "enabled": True, "unlock": {"always": False, "open_to_all_at": "+2.63h"},
         "open_to_all": True, "menu": {"sells": [{"rarity": "uncommon", "list_price": 26}, {"rarity": "rare", "list_price": 77}]}}]}

    @classmethod
    def setUpClass(cls):
        import value_inference as vi
        saved = (vi.FEED, vi.public, mp.live_board)
        public = {"clock": {"today": "fri", "t_hours": 2.65, "doors": "closed"},
                  "schedule": {"upcoming": [{"action": "grant_all", "at_hours": 4.05, "params": {"cash": 150}}]},
                  "dealers": cls.DEALERS}
        try:
            vi.FEED = Path(__file__).resolve().parent.parent / "logs" / "feed"
            vi.public = lambda name, refresh=False: public[name] if name in public else saved[1](name, False)
            mp.live_board = lambda events: ([], "test: empty board")
            cls.p = mp.plan()
        finally:
            vi.FEED, vi.public, mp.live_board = saved

    def test_chato_rares_are_priced_at_measured_closes_not_95_percent_of_list(self):
        row = next(d for d in self.p["dealer"] if d["dealer"] == "chato" and d["kind"] == "rare")
        self.assertGreaterEqual(row["price"], 82)          # 0.95 x 77 = 73 was the old price
        self.assertEqual(row["opening"], 97)
        self.assertEqual(row["share"], round((97 - row["price"]) / (97 - row["low"]), 2))
        self.assertEqual(row["scores"], "dealer ladder (estimate)")

    def test_dealer_deals_never_appear_as_p_gains_and_team_buys_never_from_a_dealer(self):
        self.assertTrue(all(b["scores"] == "team trade" for b in self.p["buys"] + self.p["sells"]))
        self.assertFalse(any(b.get("counterparty") in ("abuela", "chato") for b in self.p["buys"]))
        self.assertTrue(all("ev" not in d and "gain" not in d for d in self.p["dealer"]))

    def test_no_collection_value_line_and_no_page_holds_while_the_bonus_is_unconfirmed(self):
        self.assertFalse(self.p["page_bonus_confirmed"])
        self.assertEqual(self.p["holds"], [])
        for line in self.p["decisions"]:
            self.assertNotIn("net ~", line)
            self.assertNotIn("completing it from dealers", line)

    def test_no_chance_is_shown_as_a_certainty(self):
        ps = [b["p"] for b in self.p["sells"] for b in b.get("likely_buyers", [])] + [m["p"] for m in self.p["sells"] + self.p["buys"]]
        self.assertTrue(ps)
        self.assertLessEqual(max(ps), mp.P_CAP)

    def test_one_teams_chance_includes_whether_it_notices_at_all(self):
        buyers = [b["p"] for s in self.p["sells"] for b in s.get("likely_buyers", [])]
        self.assertTrue(buyers)
        self.assertLessEqual(max(buyers), mp.ATTENTION)  # was 1.0 for t04, t14, t07 on LAV-08 before the fix


class PageBonus(unittest.TestCase):
    def test_off_unless_the_desk_confirms_it_read_at_plan_time(self):
        import os
        saved = os.environ.pop(mp.PAGE_BONUS_ENV, None)
        try:
            self.assertFalse(mp.page_bonus_on())
            os.environ[mp.PAGE_BONUS_ENV] = "1"
            self.assertTrue(mp.page_bonus_on())
        finally:
            os.environ.pop(mp.PAGE_BONUS_ENV, None)
            if saved is not None:
                os.environ[mp.PAGE_BONUS_ENV] = saved


if __name__ == "__main__":
    unittest.main()
