"""agent/chato.py: the picaros dealer row and sell:<REF> targets. No key, no network.

  - `--dealer picaros` buys rares only (he sells rares and epics; the epic leg is not a ladder deal inside our value)
    and never sells him anything: his bids sit below every value of ours, so SELL_RARITIES is empty, named ids included
  - a Pícaros thread runs through the same negotiate() as Chato's: the clipped limit, the walk above it
  - `--only sell:RET-09` names the copy of a card we just bought (its asset id is not known until the deal lands):
    the highest serial, the last copy only with --allow-single, nothing for a card we do not hold

    python3 -m unittest discover -s tests
"""
import unittest

from dealer_fakes import FakeAccount, FakeServer, chato, run_main

LAT = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7, "CHA": 0.5}


def asset(aid, ref, rarity, serial, your_value, kind="card"):
    return {"id": aid, "ref": ref, "kind": kind, "rarity": rarity, "serial": serial, "your_value": your_value,
            "name": ref, "set": ref.split("-")[0]}


def card(ref, rarity, book):
    return {"id": ref, "rarity": rarity, "name": ref, "book": book}


class Cat:
    cards = (card("RET-06", "uncommon", 25), card("RET-09", "rare", 70), card("RET-11", "epic", 180))

    def catalog(self):
        return {"sets": [{"id": "RET", "released": True, "cards": list(self.cards)}]}

    def value(self, ref):
        return {"card": ref, "your_value": {"RET-06": 22.5, "RET-09": 63.0, "RET-11": 162.0}[ref]}


ME = {"cash": 1000, "affinity": LAT, "assets": []}


class Dealer(unittest.TestCase):
    def tearDown(self):
        chato.apply_dealer("chato")


class TestPicaros(Dealer):
    def setUp(self):
        chato.apply_dealer("picaros")

    def test_the_row(self):
        self.assertEqual((chato.DEALER, chato.DEALER_NAME), ("picaros", "Los Pícaros"))
        self.assertEqual(chato.SELL_RARITIES, ())             # he buys nothing from us
        self.assertEqual(chato.SELL_CARD_RARITIES, ("rare",))
        self.assertTrue(chato.DEALER_SELLS_CARDS)
        self.assertEqual(chato.MAX_ROUNDS, 40)

    def test_buys_rares_only(self):
        plan = chato.build_plan(Cat(), ME, None, None)
        self.assertEqual([p["item"] for p in plan], ["RET-09"])          # not the uncommon, not the epic
        self.assertEqual((plan[0]["value"], plan[0]["ladder_value"], plan[0]["book"]), (63, 63, 70))

    def test_chato_still_buys_uncommons_and_rares(self):
        chato.apply_dealer("chato")
        plan = chato.build_plan(Cat(), ME, None, None)
        self.assertEqual(sorted(p["item"] for p in plan), ["RET-06", "RET-09"])   # no epic for him either

    def test_nothing_is_ever_sold_to_him_not_even_a_named_copy(self):
        me = dict(ME, assets=[asset(1, "RET-09", "rare", 1, 63.0), asset(2, "RET-09", "rare", 5, 15.75),
                              asset(3, "RET-06", "uncommon", 2, 22.5)])
        self.assertEqual([p for p in chato.build_plan(Cat(), me, None, None) if p["side"] == "sell"], [])
        named = chato.build_plan(Cat(), me, ["sell:1", "sell:2", "sell:RET-09", "sell:3"], None, allow_single=True)
        self.assertEqual([p for p in named if p["side"] == "sell"], [])

    def test_the_cap_rule_applies_to_him_too(self):
        class Acct(FakeAccount):
            made = []
            cash = 1000
            affinity = LAT
            cards = (card("RET-09", "rare", 70),)

            def catalog(self):
                return {"sets": [{"id": "RET", "released": True, "cards": list(self.cards)}]}

            def value(self, ref):
                return {"card": ref, "your_value": 63.0}
        code, out, _, _ = run_main(chato, ["run", "--dealer", "picaros", "--only", "RET-09", "--cap", "64"], Acct)
        self.assertEqual(code, 2, out)                     # 64 is above floor(70 x 0.9) = 63
        self.assertIn("above the ladder ceiling 63", out)

    def server(self, ask):
        return FakeServer(dealer="picaros", side="buy", item="RET-09", opening=ask, opening_final=True, expiry=100,
                          cash=1000, cards=[card("RET-09", "rare", 70)], values={"RET-09": 63.0}, affinity=LAT,
                          max_requests=2000)

    ARGS = ["run", "--dealer", "picaros", "--only", "RET-09", "--cap", "62", "--anchor", "40", "--step", "2",
            "--max-deals", "1", "--max-rounds", "40"]

    def test_a_final_inside_the_cap_is_taken(self):
        srv = self.server(59)
        code, out, run, _ = run_main(chato, self.ARGS, server=srv)
        self.assertEqual([p for _, p, _ in srv.accepted], [59], out)
        (o,) = run.named("open")
        self.assertEqual((o["value"], o["private"], o["ladder_value"]), (62, 63.0, 63))

    def test_a_final_over_the_cap_is_walked_from(self):
        srv = self.server(64)
        code, out, run, _ = run_main(chato, self.ARGS, server=srv)
        self.assertEqual(srv.accepted, [], out)
        self.assertEqual(srv.status(), "closed")


# ---------------------------------------------------------------- sell:<REF>

class SellRefs(Dealer):
    def setUp(self):
        chato.apply_dealer("pilar")        # she buys uncommons, rares and epics

    def me(self, *assets):
        return dict(ME, assets=list(assets))

    def plan(self, me, only, allow_single=True):
        return chato.build_plan(Cat(), me, only, None, allow_single=allow_single)

    def test_a_ref_names_the_copy_we_hold(self):
        me = self.me(asset(901, "RET-09", "rare", 4, 63.0))
        (p,) = self.plan(me, ["sell:RET-09"])
        self.assertEqual((p["side"], p["asset_id"], p["item"], p["single"], p["last"]), ("sell", 901, "RET-09", True, True))
        self.assertEqual((p["private"], p["ladder_floor"], p["value"]), (63.0, 63, 65.0))

    def test_the_last_copy_still_needs_allow_single(self):
        me = self.me(asset(901, "RET-09", "rare", 4, 63.0))
        self.assertEqual(self.plan(me, ["sell:RET-09"], allow_single=False), [])
        skips = chato.sell_skips(me, ["sell:RET-09"], [], False)
        self.assertEqual(len(skips), 1)
        self.assertIn("--allow-single", skips[0])
        self.assertIn("sell:RET-09 (asset 901)", skips[0])

    def test_with_two_copies_the_spare_is_named_and_the_lowest_serial_stays(self):
        me = self.me(asset(901, "RET-09", "rare", 2, 63.0), asset(902, "RET-09", "rare", 9, 15.75))
        for allow in (False, True):          # --allow-single must not add the kept copy next to the spare
            (p,) = self.plan(me, ["sell:RET-09"], allow_single=allow)
            self.assertEqual((p["asset_id"], p["ladder_floor"]), (902, 16))      # 25 % of 63, rounded up

    def test_a_card_we_do_not_hold_is_skipped_with_a_reason(self):
        me = self.me(asset(901, "RET-06", "uncommon", 1, 22.5))
        self.assertEqual(self.plan(me, ["sell:RET-09"]), [])
        (s,) = chato.sell_skips(me, ["sell:RET-09"], [], True)
        self.assertIn("we hold no copy of RET-09", s)

    def test_only_the_named_cards_are_planned(self):
        me = self.me(asset(901, "RET-09", "rare", 4, 63.0), asset(903, "RET-06", "uncommon", 3, 22.5))
        self.assertEqual([p["item"] for p in self.plan(me, ["sell:RET-06"])], ["RET-06"])
        self.assertEqual(sorted(p["item"] for p in self.plan(me, ["sell:RET-06", "sell:RET-09"])), ["RET-06", "RET-09"])

    def test_ids_still_work_next_to_refs(self):
        me = self.me(asset(901, "RET-09", "rare", 4, 63.0), asset(903, "RET-06", "uncommon", 3, 22.5))
        self.assertEqual(sorted(p["asset_id"] for p in self.plan(me, ["sell:903", "sell:RET-09"])), [901, 903])

    def test_allow_single_accepts_a_ref_and_still_refuses_none(self):
        args = chato.parse_args(["plan", "--dealer", "pilar", "--only", "sell:RET-09", "--allow-single"])
        self.assertTrue(args.allow_single)
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                chato.parse_args(["plan", "--dealer", "pilar", "--allow-single"])
            with self.assertRaises(SystemExit):
                chato.parse_args(["plan", "--dealer", "pilar", "--allow-single", "--only", "RET-09"])

    def test_floor_goes_through_the_ladder_floor_for_a_ref(self):
        me = self.me(asset(901, "RET-09", "rare", 4, 1.0))        # a stale API number on the only copy
        plan = self.plan(me, ["sell:RET-09"])
        self.assertEqual(chato.apply_floor(plan, 60)[0], [])      # 60 clears ceil(1.0) but not 70 x 0.9
        (p,) = chato.apply_floor(plan, 64)[0]
        self.assertEqual(p["value"], 64)

    def test_main_plans_the_ref_end_to_end(self):
        class Acct(FakeAccount):
            made = []
            affinity = LAT
            assets = [asset(901, "RET-09", "rare", 4, 63.0)]
        code, out, _, _ = run_main(chato, ["plan", "--dealer", "pilar", "--only", "sell:RET-09", "--allow-single",
                                           "--floor", "64"], Acct)
        self.assertIsNone(code, out)
        self.assertIn("asset=901 LAST COPY", out)
        self.assertIn("ladder_floor=63", out)
        self.assertNotIn("REFUSED", out)
        code, out, _, _ = run_main(chato, ["plan", "--dealer", "pilar", "--only", "sell:RET-09", "--allow-single",
                                           "--floor", "62"], Acct)
        self.assertIn("REFUSED sell:901", out)


if __name__ == "__main__":
    unittest.main()
