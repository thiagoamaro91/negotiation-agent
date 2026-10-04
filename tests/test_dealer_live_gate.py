"""The ladder gate while a thread runs (agent/dealer_client.py live_limit / limit_dropped / exact_offer, used by
agent/chato.py and agent/abuela.py). No key, no network, the fake server under the bots' real client.

Review of PR 69 found four ways the clipped limit still failed:
  1. the limit was priced once, from the holdings of plan time, while Abuela, Pilar, Picaros run at once on the same RET
     cards: a buy that became our second copy was still accepted at the first copy's limit, a spare whose kept copy left
     was still sold at the spare's floor. Now every decision re-reads /api/me and re-prices from what it reads; if the
     limit no longer allows the deal the thread is closed and the reason logged (limit_dropped, limit_unknown)
  2. a set without a multiplier gave gate 0 on a sale (a LAV spare passed --floor 2): now it is flagged and refused,
     for buys and for sales
  3. an offer for the right card plus one of OUR assets was accepted: the structure must be exact
  (4. the Picaros step split is checked in tests/test_ladder_steps.py)

    python3 -m unittest discover -s tests
"""
import unittest

from dealer_fakes import FakeAccount, FakeServer, NullRun, abuela, chato, run_main

import dealer_client as dc

LAT = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7, "CHA": 0.5}


def card(aid, ref, rarity, serial, your_value):
    return {"id": aid, "ref": ref, "kind": "card", "rarity": rarity, "serial": serial, "your_value": your_value,
            "name": ref, "set": ref.split("-")[0]}


def cat(ref, rarity, book):
    return {"id": ref, "rarity": rarity, "name": ref, "book": book}


def flip_after_open(srv, change):
    """Run `change(srv)` once, on the first request after the bot opened its thread: another bot trades the card
    while we talk."""
    done = []

    def hook(server, method, path):
        if server.thread is not None and not done:
            done.append(1)
            change(server)
    srv.request_hooks.append(hook)


def flip_after_first_bid(srv, change):
    done = []

    def hook(server, method, path):
        if server.said and not done:
            done.append(1)
            change(server)
    srv.request_hooks.append(hook)


# ---------------------------------------------------------------- live_limit

class TestLiveLimit(unittest.TestCase):
    def me(self, *assets, affinity=LAT):
        return {"cash": 1000, "affinity": dict(affinity), "assets": list(assets)}

    buy = {"side": "buy", "item": "RET-09", "book": 70, "value": 62}

    def test_a_first_copy_buy_keeps_its_planned_limit(self):
        self.assertEqual(dc.live_limit(self.me(), self.buy), (62, ""))

    def test_a_buy_that_became_our_second_copy_is_worth_a_quarter(self):
        me = self.me(card(5, "RET-09", "rare", 3, 63.0))
        self.assertEqual(dc.live_limit(me, self.buy), (15, ""))              # floor(70 x 0.9 x 0.25) = 15.75 -> 15

    def test_a_third_copy_is_worth_a_tenth(self):
        me = self.me(card(5, "RET-09", "rare", 3, 15.0), card(6, "RET-09", "rare", 4, 6.0))
        self.assertEqual(dc.live_limit(me, self.buy), (6, ""))               # floor(70 x 0.9 x 0.1) = 6.3 -> 6

    def test_the_planned_limit_still_wins_when_lower(self):
        self.assertEqual(dc.live_limit(self.me(), dict(self.buy, value=40)), (40, ""))

    sell = {"side": "sell", "item": "RET-09", "asset_id": 901, "value": 17.75}

    def test_a_spare_keeps_its_floor_while_the_other_copy_is_held(self):
        me = self.me(card(902, "RET-09", "rare", 1, 63.0), card(901, "RET-09", "rare", 9, 15.75))
        self.assertEqual(dc.live_limit(me, self.sell), (17.75, ""))          # gate ceil(15.75) = 16, API 16

    def test_a_spare_becomes_a_first_copy_when_the_kept_copy_leaves(self):
        me = self.me(card(901, "RET-09", "rare", 9, 63.0))
        self.assertEqual(dc.live_limit(me, self.sell), (63, ""))             # the whole value, not 17.75

    def test_the_live_api_value_can_raise_the_floor(self):
        me = self.me(card(902, "RET-09", "rare", 1, 63.0), card(901, "RET-09", "rare", 9, 40.2))   # e.g. a page bonus
        self.assertEqual(dc.live_limit(me, self.sell), (41, ""))             # ceil(40.2) beats the planned 17.75 and 16

    def test_a_stale_low_api_value_cannot_lower_the_gate(self):
        me = self.me(card(901, "RET-09", "rare", 9, 1.0))
        self.assertEqual(dc.live_limit(me, self.sell), (63, ""))             # ceil(70 x 0.9 x 1.0) from the multiplier

    def test_a_copy_we_no_longer_hold_has_no_limit(self):
        me = self.me(card(902, "RET-09", "rare", 1, 63.0))
        self.assertEqual(dc.live_limit(me, self.sell), (None, "asset_gone"))

    def test_a_read_without_holdings_has_no_limit(self):
        self.assertEqual(dc.live_limit({"cash": 1000, "affinity": LAT}, self.buy), (None, "no_holdings"))
        self.assertEqual(dc.live_limit({"cash": 1000, "affinity": LAT, "assets": "x"}, self.sell), (None, "no_holdings"))

    def test_a_set_without_a_multiplier_has_no_limit_buy_or_sell(self):
        me = self.me(card(901, "RET-09", "rare", 9, 15.75), affinity={"LAV": 1.6})
        self.assertEqual(dc.live_limit(me, self.buy), (None, "no_multiplier"))
        self.assertEqual(dc.live_limit(me, self.sell), (None, "no_multiplier"))

    def test_a_buy_without_a_book_has_no_limit(self):
        self.assertEqual(dc.live_limit(self.me(), {"side": "buy", "item": "RET-09", "value": 62}), (None, "no_book"))

    def test_limit_dropped_only_when_our_own_number_is_on_the_wrong_side(self):
        self.assertTrue(dc.limit_dropped("buy", 40, 15))
        self.assertFalse(dc.limit_dropped("buy", 15, 15))
        self.assertFalse(dc.limit_dropped("buy", None, 15))
        self.assertTrue(dc.limit_dropped("sell", 27, 63))
        self.assertFalse(dc.limit_dropped("sell", 63, 63))
        self.assertTrue(dc.limit_dropped("sell", 62, 62.5))                   # a 62.5 floor is 63 once rounded up


# ---------------------------------------------------------------- end to end: another bot trades the card mid-thread

class TestBuyBecomesSecondCopy(unittest.TestCase):
    """The dealer's offer is inside the planned limit and above the live one; the fake server's holdings change after the
    bot opened its thread, as when another of our bots finishes a deal on the same card."""

    def server(self, mod, dealer, item, rarity, book, api, ask, ask_final=True):
        return FakeServer(dealer=dealer, side="buy", item=item, opening=ask, opening_final=ask_final, expiry=100,
                          cash=1000, cards=[cat(item, rarity, book)], values={item: api}, affinity=LAT, max_requests=2000)

    def test_chato_walks_from_a_59_that_is_now_a_second_copy(self):
        srv = self.server(chato, "picaros", "RET-09", "rare", 70, 63.0, 59)
        flip_after_open(srv, lambda s: s.assets.append(card(500, "RET-09", "rare", 2, 63.0)))   # another bot bought it
        code, out, run, _ = run_main(chato, ["run", "--dealer", "picaros", "--only", "RET-09", "--cap", "62", "--anchor", "40",
                                             "--step", "2", "--max-deals", "1", "--max-rounds", "6"], server=srv)
        self.assertEqual(srv.accepted, [], out)               # 59 was inside the planned 62; the second copy is worth 15
        (w,) = run.named("walk")
        self.assertEqual((w["price"], w["reservation"]), (59, 15))

    def test_abuela_walks_from_a_22_that_is_now_a_second_uncommon(self):
        srv = self.server(abuela, "abuela", "RET-06", "uncommon", 25, 22.5, 22)
        flip_after_open(srv, lambda s: s.assets.append(card(500, "RET-06", "uncommon", 2, 22.5)))
        code, out, run, _ = run_main(abuela, ["run", "--only", "RET-06", "--cap", "22", "--reserve", "20", "--max-deals", "1"],
                                     server=srv)
        self.assertEqual(srv.accepted, [], out)
        (w,) = run.named("walk")
        self.assertEqual((w["price"], w["reservation"]), (22, 5))     # floor(25 x 0.9 x 0.25) = 5.6 -> 5

    def test_a_first_copy_buy_is_still_taken(self):
        srv = self.server(chato, "picaros", "RET-09", "rare", 70, 63.0, 59)
        code, out, run, _ = run_main(chato, ["run", "--dealer", "picaros", "--only", "RET-09", "--cap", "62", "--anchor", "40",
                                             "--step", "2", "--max-deals", "1", "--max-rounds", "6"], server=srv)
        self.assertEqual([p for _, p, _ in srv.accepted], [59], out)

    def test_our_standing_bid_is_withdrawn_when_the_limit_falls_under_it(self):
        srv = self.server(chato, "picaros", "RET-09", "rare", 70, 63.0, 73, ask_final=False)
        flip_after_first_bid(srv, lambda s: s.assets.append(card(500, "RET-09", "rare", 2, 63.0)))
        code, out, run, _ = run_main(chato, ["run", "--dealer", "picaros", "--only", "RET-09", "--cap", "62", "--anchor", "40",
                                             "--step", "2", "--max-deals", "1", "--max-rounds", "30"], server=srv)
        self.assertEqual(srv.accepted, [], out)
        self.assertEqual(srv.status(), "closed")
        (d,) = run.named("limit_dropped")
        self.assertEqual((d["ours"], d["limit"], d["planned"]), (40, 15, 62))
        self.assertEqual(srv.said, [(srv.said[0][0], 40)])     # not a second, lower bid on the same thread


    def test_abuela_withdraws_its_standing_bid_too(self):
        srv = self.server(abuela, "abuela", "RET-06", "uncommon", 25, 22.5, 30, ask_final=False)
        flip_after_first_bid(srv, lambda s: s.assets.append(card(500, "RET-06", "uncommon", 2, 22.5)))
        code, out, run, _ = run_main(abuela, ["run", "--only", "RET-06", "--cap", "22", "--reserve", "20", "--max-deals", "1"],
                                     server=srv)
        self.assertEqual(srv.accepted, [], out)
        self.assertEqual(srv.status(), "closed")
        (d,) = run.named("limit_dropped")
        self.assertEqual((d["limit"], d["planned"]), (5, 22))


class TestSpareBecomesFirstCopy(unittest.TestCase):
    """Pilar is offered 20 for the spare RET-09 (floor 17.75 at plan time); the copy we kept leaves while she talks."""

    def server(self):
        return FakeServer(dealer="pilar", side="sell", item="RET-09", asset_id=901, opening=20, opening_final=True,
                          expiry=100, cash=1000, affinity=LAT, max_requests=2000,
                          assets=[card(902, "RET-09", "rare", 1, 63.0), card(901, "RET-09", "rare", 9, 15.75)])

    ARGS = ["run", "--dealer", "pilar", "--only", "sell:901", "--max-deals", "1", "--max-rounds", "6"]

    def leave(self, s):
        s.assets[:] = [dict(a, your_value=63.0) for a in s.assets if a["id"] == 901]    # the kept copy went to Abuela

    def test_the_spare_is_not_sold_at_20_once_it_is_the_only_copy(self):
        srv = self.server()
        flip_after_open(srv, self.leave)
        code, out, run, _ = run_main(chato, self.ARGS, server=srv)
        self.assertEqual(srv.accepted, [], out)
        (w,) = run.named("walk")
        self.assertEqual((w["price"], w["reservation"]), (20, 63))

    def test_the_spare_is_still_sold_at_20_while_the_other_copy_stays(self):
        srv = self.server()
        code, out, run, _ = run_main(chato, self.ARGS, server=srv)
        self.assertEqual([p for _, p, _ in srv.accepted], [20], out)

    def test_a_copy_that_left_closes_the_thread(self):
        srv = self.server()
        flip_after_open(srv, lambda s: s.assets.__setitem__(slice(None), [a for a in s.assets if a["id"] != 901]))
        code, out, run, _ = run_main(chato, self.ARGS, server=srv)
        self.assertEqual(srv.accepted, [], out)
        (u,) = run.named("limit_unknown")
        self.assertEqual(u["reason"], "asset_gone")


class NoLimitNoThread:
    mod, dealer = chato, "picaros"
    item, rarity, book = "RET-09", "rare", 70

    def test_a_thread_is_not_opened_when_no_limit_can_be_computed(self):
        srv = FakeServer(dealer=self.dealer, side="buy", item=self.item, opening=59, opening_final=True, expiry=100,
                         cash=1000, cards=[cat(self.item, self.rarity, self.book)], values={self.item: 63.0},
                         affinity={}, max_requests=500)
        saved, self.mod.RUN = self.mod.RUN, NullRun()
        try:
            if self.mod is chato:
                chato.apply_dealer(self.dealer)
            with srv.serving():
                r = self.mod.negotiate(srv.client(self.mod),
                                       {"side": "buy", "item": self.item, "value": 20, "book": self.book}, False)
            events = self.mod.RUN.events
        finally:
            self.mod.RUN = saved
            if self.mod is chato:
                chato.apply_dealer("chato")
        self.assertEqual(r, {"result": "refused", "code": "no_multiplier"})
        self.assertIsNone(srv.thread)                          # the dealer's only slot was never taken
        self.assertEqual([e for e, _ in events], ["open_refused"])


class TestNoLimitNoThreadChato(NoLimitNoThread, unittest.TestCase):
    pass


class TestNoLimitNoThreadAbuela(NoLimitNoThread, unittest.TestCase):
    mod, dealer = abuela, "abuela"
    item, rarity, book = "RET-06", "uncommon", 25


class TestAbuelaSaleLosesItsCopy(unittest.TestCase):
    def test_the_thread_is_closed_when_the_copy_we_sell_is_gone(self):
        srv = FakeServer(dealer="abuela", side="sell", item="RET-06", asset_id=901, opening=6, opening_final=True,
                         expiry=100, cash=1000, affinity=LAT, max_requests=2000,
                         assets=[card(902, "RET-06", "uncommon", 1, 22.5), card(901, "RET-06", "uncommon", 9, 5.6)])
        flip_after_open(srv, lambda s: s.assets.__setitem__(slice(None), [a for a in s.assets if a["id"] != 901]))
        code, out, run, _ = run_main(abuela, ["run", "--only", "sell:901", "--max-deals", "1"], server=srv)
        self.assertEqual(srv.accepted, [], out)
        (u,) = run.named("limit_unknown")
        self.assertEqual(u["reason"], "asset_gone")


# ---------------------------------------------------------------- an unknown multiplier fails closed on a sale too

class NoLav(FakeAccount):
    made = []
    cash = 1000
    affinity = {"SAL": 1.3, "RET": 0.9}                       # no LAV
    assets = [card(10, "LAV-06", "uncommon", 1, 40.0), card(11, "LAV-06", "uncommon", 9, 10.0)]
    cards = (cat("LAV-06", "uncommon", 25),)

    def catalog(self):
        return {"sets": [{"id": "LAV", "released": True, "cards": list(self.cards)}]}

    def value(self, ref):
        return {"card": ref, "your_value": 40.0}


class TestUnknownMultiplier(unittest.TestCase):
    def test_a_lav_spare_is_not_sold_at_floor_2_without_a_lav_multiplier(self):
        code, out, run, _ = run_main(chato, ["run", "--dealer", "pilar", "--only", "sell:11", "--floor", "2"], NoLav)
        self.assertEqual(code, 2, out)                         # the review's repro: it used to pass (gate 0)
        self.assertIn("no multiplier for the LAV set", out)
        self.assertEqual(run.named("run_start"), [])

    def test_the_same_without_a_floor(self):
        code, out, _, _ = run_main(chato, ["run", "--dealer", "pilar", "--only", "sell:11"], NoLav)
        self.assertEqual(code, 2, out)

    def test_abuela_does_not_sell_a_spare_it_cannot_price(self):
        code, out, run, _ = run_main(abuela, ["run", "--only", "sell:11"], NoLav)
        self.assertEqual(code, 2, out)
        self.assertEqual(run.named("run_start"), [])

    def test_plan_shows_the_refusal(self):
        code, out, _, _ = run_main(chato, ["plan", "--dealer", "pilar", "--only", "sell:11", "--floor", "2"], NoLav)
        self.assertIsNone(code, out)
        self.assertIn("REFUSED sell:LAV-06", out)

    def test_apply_floor_alone_refuses_an_unpriced_sale(self):
        plan = [{"side": "sell", "item": "LAV-06", "asset_id": 11, "value": 12, "private": 10.0, "ladder_floor": None}]
        kept, refused = chato.apply_floor(plan, 2)
        self.assertEqual(kept, [])
        self.assertIn("no multiplier", refused[0]["why"])

    def test_a_priced_sale_in_the_same_run_does_not_hide_it(self):
        class OneLav(NoLav):
            made = []
            affinity = {"LAV": 1.6}
        code, out, _, _ = run_main(chato, ["plan", "--dealer", "pilar", "--only", "sell:11", "--floor", "2"], OneLav)
        self.assertIn("REFUSED sell:11", out)                  # 2 is under the gate 10 once the multiplier is known


# ---------------------------------------------------------------- the offer must be exactly the deal

def buy_offer(**kw):
    o = {"give": {"cash": 0, "assets": [], "types": ["card:RET-09"]}, "want": {"cash": 59, "assets": [], "types": []}}
    for k, v in kw.items():
        side, key = k.split("_", 1)
        o[side][key] = v
    return o


def sell_offer(**kw):
    o = {"give": {"cash": 20, "assets": [], "types": []}, "want": {"cash": 0, "assets": [{"id": 901}], "types": []}}
    for k, v in kw.items():
        side, key = k.split("_", 1)
        o[side][key] = v
    return o


class OfferShape:
    mod = chato

    def m(self, o, side="buy", item="RET-09", aid=901):
        return self.mod.offer_matches(o, side, item, aid)

    def test_the_exact_buy_and_sell_match(self):
        self.assertTrue(self.m(buy_offer()))
        self.assertTrue(self.m(sell_offer(), side="sell"))
        asset_form = buy_offer(give_assets=[{"ref": "RET-09", "id": 7}], give_types=[])
        self.assertTrue(self.m(asset_form))
        self.assertTrue(self.m(sell_offer(want_assets=[901]), side="sell"))     # a bare id is the same asset

    def test_a_buy_that_also_takes_one_of_our_assets_is_refused(self):
        self.assertFalse(self.m(buy_offer(want_assets=[{"id": 999, "kind": "card", "ref": "SAL-01"}])))
        self.assertFalse(self.m(buy_offer(want_assets=[999])))

    def test_a_buy_that_also_wants_a_type_of_ours_is_refused(self):
        self.assertFalse(self.m(buy_offer(want_types=["card:LAV-01"])))

    def test_a_buy_with_two_cards_or_cash_back_is_refused(self):
        self.assertFalse(self.m(buy_offer(give_types=["card:RET-09", "card:RET-10"])))
        self.assertFalse(self.m(buy_offer(give_cash=5)))
        self.assertFalse(self.m(buy_offer(give_types=["card:RET-10"])))

    def test_a_buy_without_cash_is_refused(self):
        self.assertFalse(self.m(buy_offer(want_cash=0)))

    def test_a_sale_that_wants_a_second_card_is_refused(self):
        self.assertFalse(self.m(sell_offer(want_assets=[{"id": 901}, {"id": 999}]), side="sell"))
        self.assertFalse(self.m(sell_offer(want_assets=[{"id": 999}]), side="sell"))
        self.assertFalse(self.m(sell_offer(want_types=["card:SAL-01"]), side="sell"))

    def test_a_sale_that_wants_cash_too_or_gives_a_card_is_refused(self):
        self.assertFalse(self.m(sell_offer(want_cash=3), side="sell"))
        self.assertFalse(self.m(sell_offer(give_assets=[{"id": 5}]), side="sell"))
        self.assertFalse(self.m(sell_offer(give_types=["card:LAV-01"]), side="sell"))
        self.assertFalse(self.m(sell_offer(give_cash=0), side="sell"))


class TestOfferShapeChato(OfferShape, unittest.TestCase):
    mod = chato


class TestOfferShapeAbuela(OfferShape, unittest.TestCase):
    mod = abuela


class Padded(FakeServer):
    """A dealer whose every offer carries one extra asset of ours: for a buy it wants card 999 on top of the cash, for a
    sale it wants card 999 on top of our copy."""

    def post(self, price, final=False, t=None):
        o = super().post(price, final, t)
        if self.side == "buy":
            o["want"]["assets"] = [{"id": 999, "kind": "card", "ref": "SAL-01"}]
        else:
            o["want"]["assets"].append({"id": 999, "kind": "card", "ref": "SAL-01"})
        return o


class TestPaddedOffersEndToEnd(unittest.TestCase):
    def test_a_final_for_ret09_plus_our_asset_999_is_never_accepted(self):
        srv = Padded(dealer="picaros", side="buy", item="RET-09", opening=59, opening_final=True, expiry=100, cash=1000,
                     cards=[cat("RET-09", "rare", 70)], values={"RET-09": 63.0}, affinity=LAT, max_requests=2000)
        code, out, run, _ = run_main(chato, ["run", "--dealer", "picaros", "--only", "RET-09", "--cap", "62", "--anchor", "40",
                                             "--step", "2", "--max-deals", "1", "--max-rounds", "6"], server=srv)
        self.assertEqual(srv.accepted, [], out)
        self.assertTrue(run.named("mismatch"))

    def test_the_same_for_a_sale(self):
        srv = Padded(dealer="pilar", side="sell", item="RET-09", asset_id=901, opening=30, opening_final=True, expiry=100,
                     cash=1000, affinity=LAT, max_requests=2000,
                     assets=[card(902, "RET-09", "rare", 1, 63.0), card(901, "RET-09", "rare", 9, 15.75)])
        code, out, run, _ = run_main(chato, ["run", "--dealer", "pilar", "--only", "sell:901", "--max-deals", "1",
                                             "--max-rounds", "6"], server=srv)
        self.assertEqual(srv.accepted, [], out)
        self.assertTrue(run.named("mismatch"))

    def test_abuela_too(self):
        srv = Padded(dealer="abuela", side="buy", item="RET-06", opening=22, opening_final=True, expiry=100, cash=1000,
                     cards=[cat("RET-06", "uncommon", 25)], values={"RET-06": 22.5}, affinity=LAT, max_requests=2000)
        code, out, run, _ = run_main(abuela, ["run", "--only", "RET-06", "--cap", "22", "--reserve", "20", "--max-deals", "1"],
                                     server=srv)
        self.assertEqual(srv.accepted, [], out)
        self.assertTrue(run.named("mismatch"))


if __name__ == "__main__":
    unittest.main()
