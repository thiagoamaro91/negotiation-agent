"""The ladder value gate in the dealer bots (agent/chato.py, agent/abuela.py, helpers in agent/dealer_client.py).

A dealer deal on the wrong side of our private value earns no ladder credit. The API value can sit ABOVE the gate for a
buy (a card that completes a page carries the page bonus: LAT-09 read 77 before LAT-03 and 149.9 after), so the old
limit min(API value, --cap) let a deal close over value for nothing (Friday: LAT-06 at 28 of 27.5, LAT-07 at 29). The
gate is book x our set multiplier (from /api/me "affinity", never hardcoded): floor() for a first copy we buy,
ceil() x the copy marginal (100 % / 25 % / 10 %) for the copy we sell. Every test here fails without its rule:

  - buy limit clipped to floor(book x multiplier) in both build_plans, end to end through negotiate()
  - a set without a multiplier gets no buy target (never a guess)
  - --cap above the ceiling is refused: printed by `plan`, and `run` stops before any thread opens (exit 2)
  - --floor below ceil(book x multiplier x copy marginal) is refused, even when it clears the API value
  - the default sell floor is never below the gate; marginals follow the copies we hold
  - open logs the API value and the gate next to the limit
  - float noise (180 x 0.7 reads 125.99999999999999, 180 x 1.1 reads 198.00000000000003) never moves a floor or a ceiling

    python3 -m unittest tests.test_ladder_gate    (or: python3 -m unittest discover -s tests)
"""
import unittest

from dealer_fakes import FakeAccount, FakeServer, NullRun, abuela, chato, run_main

import dealer_client as dc

LAT = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7, "CHA": 0.5}   # our six multipliers (me.json)


def asset(aid, ref, rarity, serial, your_value, kind="card"):
    return {"id": aid, "ref": ref, "kind": kind, "rarity": rarity, "serial": serial, "your_value": your_value,
            "name": ref, "set": ref.split("-")[0]}


class Catalog:
    """The read-only surface build_plan needs: a catalog with one released set and an API value per card."""

    def __init__(self, cards, values, set_id="LAT"):
        self.cards, self.values, self.set_id = cards, values, set_id

    def catalog(self):
        return {"sets": [{"id": self.set_id, "released": True, "cards": list(self.cards)}]}

    def value(self, ref):
        return {"card": ref, "your_value": self.values[ref]}


def card(ref, rarity, book):
    return {"id": ref, "rarity": rarity, "name": ref, "book": book}


ME = {"cash": 1000, "affinity": LAT, "assets": []}


# ---------------------------------------------------------------- the helpers

class TestHelpers(unittest.TestCase):
    def test_ceiling_is_floor_of_book_times_multiplier(self):
        self.assertEqual(dc.ladder_ceiling(25, 0.9), 22)        # 22.5: the page needs 22, never 23
        self.assertEqual(dc.ladder_ceiling(70, 1.3), 91)        # SAL-10
        self.assertEqual(dc.ladder_ceiling(180, 0.5), 90)       # a CHA epic
        self.assertEqual(dc.ladder_ceiling(25, 1.1), 27)        # 27.5: Friday's LAT-06 at 28 failed the gate

    def test_unknown_multiplier_has_no_ceiling(self):
        self.assertIsNone(dc.ladder_ceiling(70, None))
        self.assertIsNone(dc.buy_ceiling({"affinity": {"LAV": 1.6}}, "CHA-09", 70))
        self.assertIsNone(dc.buy_ceiling({}, "LAV-09", 70))

    def test_ceiling_comes_from_the_affinity_not_a_constant(self):
        a = dc.buy_ceiling({"affinity": {"LAT": 1.1}}, "LAT-09", 70)
        b = dc.buy_ceiling({"affinity": {"LAT": 1.6}}, "LAT-09", 70)
        self.assertEqual((a, b), (77, 112))

    def test_float_noise_never_moves_a_floor_or_a_ceiling(self):
        self.assertEqual(dc.ladder_ceiling(180, 0.7), 126)      # a MAL epic: 125.99999999999999 floors to 125
        self.assertEqual(dc.ladder_floor(180, 1.1), 198)        # a LAT epic: 198.00000000000003 ceils to 199
        self.assertEqual(dc.ladder_floor(450, 1.1), 495)
        self.assertEqual(dc.ladder_floor(10, 1.1), 11)
        self.assertEqual(dc.ladder_floor(25, 1.6, 0.25), 10)    # 10.0 exactly: no rounding up past it

    def test_copy_marginals(self):
        self.assertEqual([dc.copy_marginal(n) for n in (1, 2, 3, 4)], [1.0, 0.25, 0.1, 0.1])

    def test_sell_floor_follows_the_copies_held(self):
        me = {"affinity": LAT}
        a = asset(9, "LAV-06", "uncommon", 3, 1.0)               # book 25 x 1.6 = 40
        self.assertEqual(dc.sell_ladder_floor(me, a, 1), 40)     # the only copy: all of it
        self.assertEqual(dc.sell_ladder_floor(me, a, 2), 10)     # the second copy: 25 %
        self.assertEqual(dc.sell_ladder_floor(me, a, 3), 4)      # the third: 10 %
        self.assertIsNone(dc.sell_ladder_floor({}, a, 2))

    def test_refuse_caps_only_above_the_ceiling_and_only_buys(self):
        plan = [{"side": "buy", "item": "LAT-09", "book": 70, "ladder_value": 77},
                {"side": "buy", "item": "LAT-06", "book": 25, "ladder_value": 27},
                {"side": "sell", "item": "SAL-03", "asset_id": 5, "ladder_floor": 4}]
        kept, refused = dc.refuse_caps(plan, 77)
        self.assertEqual([p["item"] for p in refused], ["LAT-06"])       # 77 is above 27, not above 77
        self.assertEqual([p["item"] for p in kept], ["LAT-09", "SAL-03"])
        self.assertIn("ladder ceiling 27", refused[0]["why"])
        self.assertEqual([p["item"] for p in dc.refuse_caps(plan, 78)[1]], ["LAT-09", "LAT-06"])
        self.assertEqual(dc.refuse_caps(plan, None), (plan, []))
        self.assertEqual(dc.refuse_caps(plan, 0), (plan, []))


# ---------------------------------------------------------------- the limit in build_plan, both bots

class BuyLimit:
    """LAT-09 would complete our page: the API says 149.9, the gate says floor(70 x 1.1) = 77."""
    mod = chato
    ref, rarity, book, api = "LAT-09", "rare", 70, 149.9
    ceiling, low_cap, low_api, rich_ceiling = 77, 60, 50.0, 112    # rich_ceiling: the same card if LAT were x1.6

    def plan(self, me=None, cap=None, only=None):
        b = Catalog([card(self.ref, self.rarity, self.book)], {self.ref: self.api})
        return self.mod.build_plan(b, me or ME, only, cap)

    def buys(self, plan):
        return [p for p in plan if p["side"] == "buy"]

    def test_limit_is_the_ceiling_when_the_api_value_is_higher(self):
        (p,) = self.buys(self.plan())
        self.assertEqual(p["ladder_value"], self.ceiling)
        self.assertEqual(p["value"], self.ceiling)       # not the API number
        self.assertEqual(p["private"], self.api)         # the API number stays visible next to it

    def test_a_cap_below_the_ceiling_still_lowers_the_limit(self):
        (p,) = self.buys(self.plan(cap=self.low_cap))
        self.assertEqual((p["value"], p["ladder_value"]), (self.low_cap, self.ceiling))

    def test_an_api_value_below_the_ceiling_still_wins(self):
        b = Catalog([card(self.ref, self.rarity, self.book)], {self.ref: self.low_api})
        (p,) = self.buys(self.mod.build_plan(b, ME, None, None))
        self.assertEqual(p["value"], self.low_api)

    def test_the_multiplier_is_read_from_the_account(self):
        (p,) = self.buys(self.plan(me=dict(ME, affinity=dict(LAT, LAT=1.6))))
        self.assertEqual((p["ladder_value"], p["value"]), (self.rich_ceiling, self.rich_ceiling))

    def test_a_set_without_a_multiplier_gets_no_target(self):
        me = dict(ME, affinity={"LAV": 1.6})
        self.assertEqual(self.buys(self.plan(me=me)), [])
        self.assertEqual(self.buys(self.plan(me={"cash": 1000, "assets": []})), [])


class TestBuyLimitChato(BuyLimit, unittest.TestCase):
    mod = chato


class TestBuyLimitAbuela(BuyLimit, unittest.TestCase):
    mod = abuela
    ref, rarity, book, api = "LAT-03", "common", 10, 83.9    # a page-completing common: ceiling floor(10 x 1.1) = 11
    ceiling, low_cap, low_api, rich_ceiling = 11, 8, 9.0, 16


# ---------------------------------------------------------------- the clip, end to end through negotiate()

class ClipEndToEnd:
    """The fake server under the bot's real client: his final offer is above the gate and below the API value."""
    mod = chato
    item, rarity, book, api = "LAT-09", "rare", 70, 149.9
    over, at, ceiling = 80, 77, 77     # his final: over the ceiling / exactly at it

    def server(self, ask):
        return FakeServer(dealer=self.mod.DEALER, side="buy", item=self.item, opening=ask, opening_final=True,
                          expiry=100, cash=1000, cards=[card(self.item, self.rarity, self.book)],
                          values={self.item: self.api}, affinity=LAT, max_requests=2000)

    def go(self, ask, *extra):
        srv = self.server(ask)
        code, out, run, _ = run_main(self.mod, ["run", "--only", self.item, "--max-deals", "1", *extra], server=srv)
        return srv, code, out, run

    def test_a_final_over_the_ceiling_is_never_accepted(self):
        srv, code, out, run = self.go(self.over)
        self.assertEqual(srv.accepted, [], out)          # 80 is under the API value 149.9, over the gate 77
        self.assertEqual(srv.status(), "closed")

    def test_a_final_at_the_ceiling_is_taken(self):
        srv, code, out, run = self.go(self.at)
        self.assertEqual([p for _, p, _ in srv.accepted], [self.at], out)

    def test_open_logs_the_api_value_and_the_gate_next_to_the_limit(self):
        srv, code, out, run = self.go(self.at)
        (o,) = run.named("open")
        self.assertEqual((o["value"], o["private"], o["ladder_value"]), (self.ceiling, self.api, self.ceiling))
        self.assertEqual(o["side"], "buy")


class TestClipChato(ClipEndToEnd, unittest.TestCase):
    pass


class TestClipAbuela(ClipEndToEnd, unittest.TestCase):
    mod = abuela
    item, rarity, book, api = "LAT-03", "common", 10, 83.9
    over, at, ceiling = 13, 11, 11


# ---------------------------------------------------------------- --cap above the ceiling

class CapBase(FakeAccount):
    made = []
    cash = 1000
    affinity = LAT
    cards = (card("LAT-09", "rare", 70), card("LAT-06", "uncommon", 25))

    def catalog(self):
        return {"sets": [{"id": "LAT", "released": True, "cards": list(self.cards)}]}

    def value(self, ref):
        return {"card": ref, "your_value": 149.9 if ref == "LAT-09" else 100.4}   # both read page-bonus numbers


class CapBaseAbuela(CapBase):
    made = []
    cards = (card("LAT-03", "common", 10), card("LAT-06", "uncommon", 25))


class CapCases:
    mod, account = chato, CapBase
    fine = ["--only", "LAT-09", "--cap", "77"]            # at the ceiling: allowed
    over = ["--only", "LAT-09", "--cap", "88"]            # the Sunday line that would have paid over value
    over_by_one = ["--only", "LAT-06", "--cap", "28"]     # Friday's LAT-06: ceiling 27

    def test_plan_prints_the_refusal_and_does_not_exit(self):
        code, out, _, _ = run_main(self.mod, ["plan", *self.over], self.account)
        self.assertIsNone(code, out)
        self.assertIn("REFUSED buy:", out)
        self.assertIn("above the ladder ceiling 77", out)

    def test_run_stops_before_any_thread_opens(self):
        code, out, run, _ = run_main(self.mod, ["run", *self.over], self.account)   # open_thread would raise
        self.assertEqual(code, 2, out)
        self.assertIn("Not starting: 1 buy(s) refused by --cap", out)
        self.assertEqual(run.named("run_start"), [])

    def test_one_over_the_ceiling_is_enough(self):
        code, out, _, _ = run_main(self.mod, ["run", *self.over_by_one], self.account)
        self.assertEqual(code, 2, out)
        self.assertIn("above the ladder ceiling 27", out)

    def test_a_cap_at_the_ceiling_is_not_refused(self):
        code, out, _, _ = run_main(self.mod, ["plan", *self.fine], self.account)
        self.assertIsNone(code, out)
        self.assertNotIn("REFUSED", out)
        self.assertIn("limit=  77.0", out if self.mod is chato else out.replace("value=  77.0", "limit=  77.0"))

    def test_no_cap_means_nothing_to_refuse(self):
        code, out, _, _ = run_main(self.mod, ["plan", "--only", "LAT-09"], self.account)
        self.assertIsNone(code, out)
        self.assertNotIn("REFUSED", out)

    def test_plan_shows_the_gate_next_to_the_api_value(self):
        _, out, _, _ = run_main(self.mod, ["plan", *self.fine], self.account)
        self.assertIn("ladder=77", out)
        self.assertIn("private= 149.9", out)

    def test_run_refuses_to_start_without_multipliers(self):
        class NoAffinity(self.account):
            made = []
            affinity = {}
        code, out, _, _ = run_main(self.mod, ["run", "--only", "LAT-09"], NoAffinity)
        self.assertEqual(code, 2, out)
        self.assertIn("no set multipliers", out)


class TestCapChato(CapCases, unittest.TestCase):
    pass


class TestCapAbuela(CapCases, unittest.TestCase):
    mod, account = abuela, CapBaseAbuela
    fine = ["--only", "LAT-06", "--cap", "27"]
    over = ["--only", "LAT-06", "--cap", "40"]
    over_by_one = ["--only", "LAT-06", "--cap", "28"]

    def test_plan_prints_the_refusal_and_does_not_exit(self):
        code, out, _, _ = run_main(self.mod, ["plan", *self.over], self.account)
        self.assertIsNone(code, out)
        self.assertIn("REFUSED buy:LAT-06", out)

    def test_a_cap_at_the_ceiling_is_not_refused(self):
        code, out, _, _ = run_main(self.mod, ["plan", *self.fine], self.account)
        self.assertIsNone(code, out)
        self.assertNotIn("REFUSED", out)
        self.assertIn("value=  27.0", out)

    def test_plan_shows_the_gate_next_to_the_api_value(self):
        _, out, _, _ = run_main(self.mod, ["plan", *self.fine], self.account)
        self.assertIn("ladder=27", out)
        self.assertIn("private= 100.4", out)

    def test_run_stops_before_any_thread_opens(self):
        code, out, run, _ = run_main(self.mod, ["run", *self.over], self.account)
        self.assertEqual(code, 2, out)
        self.assertEqual(run.named("run_start"), [])

    def test_one_over_the_ceiling_is_enough(self):
        code, out, _, _ = run_main(self.mod, ["run", *self.over_by_one], self.account)
        self.assertEqual(code, 2, out)
        self.assertIn("above the ladder ceiling 27", out)


# ---------------------------------------------------------------- sells: --floor and the default floor

class Sells(unittest.TestCase):
    """LAV-06 held twice: the spare is our second copy, worth 25 % of book 25 x 1.6 = 10. The API number is stale/low."""

    def me(self, api_value, copies=2):
        a = [asset(10 + i, "LAV-06", "uncommon", i + 1, 40.0 if i == 0 else api_value) for i in range(copies)]
        return dict(ME, assets=a)

    def setUp(self):
        self._dealer = chato.DEALER
        chato.apply_dealer("chato")

    def tearDown(self):
        chato.apply_dealer(self._dealer)

    def plan(self, api_value, copies=2):
        return chato.build_plan(Catalog([], {}), self.me(api_value, copies), None, None)

    def test_the_default_floor_is_never_below_the_gate(self):
        (p,) = [x for x in self.plan(3.0) if x["side"] == "sell"]
        self.assertEqual(p["ladder_floor"], 10)
        self.assertEqual(p["value"], 10)                  # max(3.0 + 2, 10): the old rule would have said 5

    def test_floor_below_the_gate_is_refused_even_when_it_clears_the_api_value(self):
        plan = self.plan(3.0)
        kept, refused = chato.apply_floor(plan, 6)        # 6 >= ceil(3.0): the old rule let it through
        self.assertEqual(kept, [])
        self.assertIn("below the ladder floor 10", refused[0]["why"])

    def test_floor_at_the_gate_is_kept(self):
        kept, refused = chato.apply_floor(self.plan(3.0), 10)
        self.assertEqual((len(kept), refused), (1, []))
        self.assertEqual(kept[0]["value"], 10)

    def test_the_api_value_still_refuses_when_it_is_the_higher_number(self):
        kept, refused = chato.apply_floor(self.plan(14.5), 12)   # gate 10, API 14.5: 12 < ceil(14.5)
        self.assertEqual(kept, [])
        self.assertIn("below our private value 14.5", refused[0]["why"])

    def test_the_third_copy_is_graded_at_ten_percent(self):
        (p,) = [x for x in self.plan(1.0, copies=3) if x["side"] == "sell"]
        self.assertEqual(p["ladder_floor"], 4)            # ceil(25 x 1.6 x 0.1)
        kept, refused = chato.apply_floor([p], 3)
        self.assertEqual(kept, [])
        self.assertIn("below the ladder floor 4", refused[0]["why"])

    def test_a_named_last_copy_is_graded_at_its_whole_value(self):
        me = dict(ME, assets=[asset(10, "LAV-06", "uncommon", 1, 1.0)])   # stale API number on the only copy
        plan = chato.build_plan(Catalog([], {}), me, ["sell:10"], None, allow_single=True)
        (p,) = plan
        self.assertEqual(p["ladder_floor"], 40)           # 100 % of 25 x 1.6
        self.assertEqual(chato.apply_floor(plan, 20)[0], [])

    def test_open_logs_the_floor_and_the_gate(self):
        plan = self.plan(3.0)

        class Dealer:
            """Opens a thread and reports it already dealt: enough to reach the open log line."""

            def open_thread(self, *a, **k):
                return {"id": 7}

            def thread(self, tid):
                return {"id": tid, "status": "deal", "standing_offers": [], "messages": []}

        saved, chato.RUN = chato.RUN, NullRun()
        try:
            chato.negotiate(Dealer(), plan[0], False)
            (o,) = chato.RUN.named("open")
        finally:
            chato.RUN = saved
        self.assertEqual((o["value"], o["private"], o["ladder_floor"]), (10, 3.0, 10))
        self.assertNotIn("ladder_value", o)


class TestAbuelaSells(unittest.TestCase):
    def test_default_sell_floor_is_never_below_the_gate(self):
        a1, a2 = asset(1, "LAV-01", "common", 1, 16.0), asset(2, "LAV-01", "common", 7, 0.5)   # second copy, stale API
        me = dict(ME, assets=[a1, a2])
        plan = abuela.build_plan(Catalog([], {}), me, None, None)
        (p,) = [x for x in plan if x["side"] == "sell"]
        self.assertEqual(p["ladder_floor"], 4)            # ceil(10 x 1.6 x 0.25)
        self.assertEqual(p["value"], 4)                   # max(0.5 + 2, 4)


if __name__ == "__main__":
    unittest.main()
