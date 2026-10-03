"""Market desk swaps: one card for one card, no cash. The fee, the gain rule, held and protected cards, structure,
never one asset in two offers, caps, our own swaps and the run path through the lease.

    python3 -m unittest discover -s tests

Values to us (tests/test_market_desk.py catalog, affinity LAV 1.6, MAL 0.7, LAT 1.1, SAL 1.3; copies 1, 0.25, 0.1):
LAV common 16 / uncommon 40 / rare 112, MAL 7 / 17.5 / 49, LAT 11 / 27.5 / 77, SAL 13 / 32.5 / 91.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "tests"))

import market_desk as md  # noqa: E402
import test_market_desk as base  # noqa: E402
from test_market_desk import AFFINITY, CAT, card, listing, bid, snap, rec  # noqa: E402


def swap(oid, give_ref, want_ref, *, aid=None, maker="m3", venue="rastro", **extra):
    """Another team's swap as the board shows it: they give one card, want any copy of one card."""
    o = {"id": oid, "maker": maker, "to": None, "venue": venue, "thread": None, "status": "open",
         "give": {"cash": 0, "assets": [card(aid or 8000 + oid, give_ref, 4)], "types": []},
         "want": {"cash": 0, "assets": [], "types": [f"card:{want_ref}"]}, "expires_tick": 200, "created_tick": 90}
    o.update(extra)
    return o


def cfg(**kw):
    kw.setdefault("bids", False)
    kw.setdefault("min_cash", 0)
    kw.setdefault("swap_post", False)
    return md.Config(**kw)


def run(boards, holdings=None, config=None, ledger=None, swapbook=None, reserved=(), bidbook=None, **kw):
    h = holdings or {}
    s = snap(boards, h, **kw)
    s["reserved"] = set(reserved)
    valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in h.items()})
    return md.decide(s, valuer, md.Tape(), ledger or md.Ledger(), config or cfg(), bidbook or {}, swapbook or {})


def two(ref, keep_id, spare_id):
    """Two copies: the keeper (lowest serial) and the spare."""
    return [card(keep_id, ref, serial=1), card(spare_id, ref, serial=9)]


def posts(res):
    return [s for s in res["swaps"] if s["action"] in ("post", "keep", "replace")]


class SwapFee(unittest.TestCase):
    def test_no_cash_fee(self):
        self.assertEqual(md.swap_fee(md.DEFAULT_FEE), 2)        # El Rastro: 0 % of 0 P + 1 P x 2 cards
        self.assertEqual(md.swap_fee((100, 0)), 0)              # v03 (t13): 1 % of nothing, no per-card fee
        self.assertEqual(md.swap_fee((0, 0)), 0)
        self.assertEqual(md.swap_fee(md.WORST_FEE), 10)         # an unknown venue: 5 P x 2 cards
        self.assertEqual(md.swap_fee(md.DEFAULT_FEE), md.fee_for(0, md.DEFAULT_FEE, 2))

    def test_fill_record_carries_the_fee(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        r = run({"rastro": [swap(1, "SAL-04", "LAV-08")]}, h)
        self.assertEqual((rec(r, 1)["fee"], rec(r, 1)["price"]), (2, 0))
        r = run({"v02": [swap(1, "SAL-04", "LAV-08", venue="v02")]}, h)
        self.assertEqual(rec(r, 1)["fee"], 0)


class FillGainRule(unittest.TestCase):
    # SAL-04 (13 to us) for our spare LAV-06 (40 x 0.25 = 10): 13 - 10 - fee vs need max(3, 1.3) = 3
    def test_boundary(self):
        h = {"LAV-06": two("LAV-06", 5, 6)}
        r = run({"v02": [swap(1, "SAL-04", "LAV-06", venue="v02")]}, h)     # 13 - 10 - 0 = 3 >= 3
        self.assertEqual(rec(r, 1)["action"], "take")
        self.assertEqual((rec(r, 1)["gain"], rec(r, 1)["give_value"]), (3.0, 10.0))
        r = run({"rastro": [swap(1, "SAL-04", "LAV-06")]}, h)                # 13 - 10 - 2 = 1 < 3
        self.assertEqual(rec(r, 1)["action"], "skip")
        self.assertIn("below need", rec(r, 1)["reason"])
        self.assertIsNone(r["accept"])

    def test_spare_for_a_card_we_lack(self):
        h = {"MAL-02": two("MAL-02", 5, 6)}                                  # spare worth 7 x 0.25 = 1.75
        r = run({"rastro": [swap(1, "MAL-01", "MAL-02")]}, h)                # 7 - 1.75 - 2 = 3.25 >= 3
        self.assertEqual(r["accept"]["offer"], 1)
        self.assertEqual((r["accept"]["side"], r["accept"]["asset"], r["accept"]["give_card"]), ("swap", 6, "MAL-02"))
        h = {"LAT-02": two("LAT-02", 5, 6)}                                  # spare worth 2.75: 7 - 2.75 - 2 < 3
        self.assertEqual(rec(run({"rastro": [swap(1, "MAL-01", "LAT-02")]}, h), 1)["action"], "skip")

    def test_ten_percent_of_value(self):
        # LAV-09 (112, need 11.2) for our only MAL-09 (49) in a --sell-first-copies set: 112 - 49 - 2 = 61
        h = {"MAL-09": [card(5, "MAL-09")]}
        c = cfg(sell_first_copies=("MAL",))
        self.assertEqual(rec(run({"rastro": [swap(1, "LAV-09", "MAL-09")]}, h, c), 1)["action"], "take")
        # LAV-06 (40, need 4) for our only MAL-10 (49): 40 - 49 - 2 < 4
        h = {"MAL-10": [card(5, "MAL-10")]}
        self.assertEqual(rec(run({"rastro": [swap(1, "LAV-06", "MAL-10")]}, h, c), 1)["action"], "skip")

    def test_never_a_card_we_hold(self):
        h = {"LAV-09": [card(1, "LAV-09")], "MAL-02": two("MAL-02", 5, 6)}
        r = run({"rastro": [swap(1, "LAV-09", "MAL-02")]}, h)                # 112 for a 1.75 spare, but we hold it
        self.assertEqual(rec(r, 1)["action"], "skip")
        self.assertIn("we hold 1 of LAV-09", rec(r, 1)["reason"])
        self.assertIsNone(r["accept"])

    def test_we_must_hold_what_they_want(self):
        r = run({"rastro": [swap(1, "LAV-09", "MAL-02")]}, {})
        self.assertIn("no copy of MAL-02", rec(r, 1)["reason"])

    def test_cash_floor_does_not_apply(self):
        # min cash 280 with 100 in hand blocks buys and bids, not a swap (it moves no cash; the 2 P fee is capped)
        h = {"MAL-02": two("MAL-02", 5, 6)}
        r = run({"rastro": [swap(1, "MAL-01", "MAL-02")]}, h, cfg(min_cash=280), cash=100)
        self.assertEqual(rec(r, 1)["action"], "take")
        r = run({"rastro": [swap(1, "MAL-01", "MAL-02")]}, h, cfg(min_cash=280), cash=1)
        self.assertIn("fee 2 > cash 1", rec(r, 1)["reason"])


class FillProtection(unittest.TestCase):
    def test_protected_page_only_copy(self):
        h = {"LAV-07": [card(5, "LAV-07")]}
        for c in (cfg(), cfg(sell_first_copies=("LAV",))):                   # even listed as a first-copy set
            r = run({"rastro": [swap(1, "SAL-09", "LAV-07")]}, h, c)         # 91 for our only LAV-07
            self.assertEqual(rec(r, 1)["action"], "skip")
            self.assertIn("protected", rec(r, 1)["reason"])
            self.assertIsNone(r["accept"])

    def test_single_copy_only_for_listed_sets(self):
        h = {"MAL-08": [card(5, "MAL-08")]}
        self.assertIn("not a spare", rec(run({"rastro": [swap(1, "SAL-09", "MAL-08")]}, h), 1)["reason"])
        r = run({"rastro": [swap(1, "SAL-09", "MAL-08")]}, h, cfg(sell_first_copies=("MAL",)))
        self.assertEqual((r["accept"]["offer"], r["accept"]["asset"]), (1, 5))

    def test_keeps_lowest_serial_and_specific_asset(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        self.assertEqual(run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h)["accept"]["asset"], 6)
        o = swap(1, "SAL-09", "LAV-08")
        o["want"] = {"cash": 0, "assets": [5], "types": []}                  # they want our keeper
        self.assertIn("keep", rec(run({"rastro": [o]}, h), 1)["reason"])
        o["want"] = {"cash": 0, "assets": [6], "types": []}
        self.assertEqual(run({"rastro": [o]}, h)["accept"]["asset"], 6)

    def test_settling_offer_blocks(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        mine = [{"id": 77, "maker": "t03", "status": "queued", "give": {"assets": [card(6, "LAV-08", 9)]},
                 "want": {"cash": 30}}]
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, mine=mine)
        self.assertIsNone(r["accept"])

    def test_listed_spare_left_to_the_seller(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        mine = [{"id": 50, "maker": "t03", "status": "open", "venue": "rastro", "give": {"assets": [card(6, "LAV-08", 9)]},
                 "want": {"cash": 30}}]
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, mine=mine)
        self.assertIn("listed by rastro_seller", rec(r, 1)["reason"])
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, cfg(sell_listed=True), mine=mine)
        self.assertEqual((r["accept"]["asset"], r["accept"]["cancel_listing"]), (6, 50))


class FillStructure(unittest.TestCase):
    def test_mismatches(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        ours = {5: "LAV-08", 6: "LAV-08"}
        cases = {
            "asks cash too": lambda o: o["want"].update(cash=5),
            "gives cash too": lambda o: o["give"].update(cash=5),
            "bool cash": lambda o: o["want"].update(cash=True),
            "gives two cards": lambda o: o["give"].update(assets=[card(1, "SAL-09"), card(2, "SAL-10")]),
            "gives a type": lambda o: o["give"].update(types=["card:SAL-10"]),
            "gives a pack": lambda o: o["give"]["assets"][0].update(kind="pack"),
            "wants two cards": lambda o: o["want"].update(types=["card:LAV-08", "card:LAV-01"]),
            "wants a pack": lambda o: o["want"].update(types=["pack:sobre_barrio"]),
            "wants an asset not ours": lambda o: o.update(want={"cash": 0, "assets": [999], "types": []}),
            "same card": lambda o: o["want"].update(types=["card:SAL-09"]),
            "unknown key": lambda o: o["give"].update(note_cash=5),
            "addressed elsewhere": lambda o: o.update(to="t09"),
            "expired": lambda o: o.update(expires_tick=100),
            "queued": lambda o: o.update(status="queued"),
            "maker us": lambda o: o.update(maker="t03"),
            "conversation": lambda o: o.update(thread=12),
        }
        for name, mutate in cases.items():
            o = swap(1, "SAL-09", "LAV-08")
            mutate(o)
            self.assertFalse(md.check_swap(o, "t03", ours, 100)["ok"], name)
            self.assertIsNone(run({"rastro": [o]}, h)["accept"], name)
        good = md.check_swap(swap(1, "SAL-09", "LAV-08"), "t03", ours, 100)
        self.assertEqual((good["ok"], good["ref"], good["want_ref"]), (True, "SAL-09", "LAV-08"))
        posted = swap(1, "SAL-09", "LAV-08", to="t03")
        posted["want"] = {"cards": ["LAV-08"]}                               # the posted form, addressed to us
        self.assertTrue(md.check_swap(posted, "t03", ours, 100)["ok"])
        self.assertEqual(run({"rastro": [posted]}, h)["accept"]["offer"], 1)

    def test_listing_and_bid_checks_still_refuse_swaps(self):
        o = swap(1, "SAL-09", "LAV-08")
        self.assertEqual(md.classify(o), "swap")
        self.assertFalse(md.check_listing(o, "t03", 100)["ok"])
        self.assertFalse(md.check_bid(o, "t03", {6: "LAV-08"}, 100)["ok"])

    def test_fills_off(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, cfg(swap_fill=False))
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["action"], "skip")


class FillCaps(unittest.TestCase):
    def test_fee_cap_on_an_unknown_venue(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        r = run({"v09": [swap(1, "SAL-09", "LAV-08", venue="v09")]}, h)      # unknown venue: worst fee 10
        self.assertIn("swap fee 10 > max 3", rec(r, 1)["reason"])

    def test_partner_per_hour(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        led = md.Ledger([{"side": "sell", "t_hours": 1.5, "partner": "m3"}, {"side": "swap", "t_hours": 1.6,
                                                                               "partner": "m3", "cost": 2}])
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, ledger=led)
        self.assertIn("trades with m3", rec(r, 1)["reason"])
        led = md.Ledger([{"side": "sell", "t_hours": 0.5, "partner": "m3"}, {"side": "swap", "t_hours": 1.6,
                                                                               "partner": "m3", "cost": 2}])
        self.assertEqual(rec(run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, ledger=led), 1)["action"], "take")

    def test_fees_count_toward_the_spend_caps(self):
        led = md.Ledger([{"side": "swap", "t_hours": 1.5, "cost": 2}, {"side": "buy", "t_hours": 1.5, "cost": 9}])
        self.assertEqual(led.spent(1.6, 1.0), 11)
        h = {"LAV-08": two("LAV-08", 5, 6)}
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h, cfg(cap_hour=12), ledger=led)
        self.assertIn("hour spend 11+2 > 12", rec(r, 1)["reason"])

    def test_one_accept_per_tick_across_kinds(self):
        h = {"LAV-08": two("LAV-08", 5, 6), "MAL-02": two("MAL-02", 7, 8)}
        r = run({"rastro": [listing(1, "SAL-05", 8), swap(2, "SAL-09", "LAV-08"), swap(3, "SAL-09", "MAL-02")]}, h)
        self.assertEqual(r["accept"]["offer"], 3)                # 91 - 1.75 - 2 beats 91 - 10 - 2 and the buy
        self.assertEqual(rec(r, 2)["action"], "skip")            # same card (SAL-09), worse gain
        self.assertEqual(rec(r, 1)["action"], "defer")
        self.assertEqual(sum(1 for x in r["records"] if x["action"] == "take"), 1)

    def test_live_bid_and_swap_on_the_card_are_cancelled_first(self):
        h = {"LAV-08": two("LAV-08", 5, 6)}
        r = run({"rastro": [swap(1, "SAL-09", "LAV-08")]}, h,
                bidbook={"SAL-09": {"offer": 501, "price": 60}}, swapbook={"SAL-09": {"offer": 601, "asset": 99}})
        self.assertIn("cancel our bid 501 first", rec(r, 1)["reason"])
        self.assertIn("cancel our swap 601 first", rec(r, 1)["reason"])


class OurSwaps(unittest.TestCase):
    def cfg(self, **kw):
        kw.setdefault("swap_post", True)
        kw.setdefault("swap_max", 4)
        return cfg(**kw)

    HOLD = {"LAV-01": two("LAV-01", 1, 2),        # common spare, 4.0 to us
            "MAL-06": two("MAL-06", 3, 4),        # uncommon spare, 4.375
            "LAV-08": two("LAV-08", 5, 6)}        # uncommon spare, 10.0

    def test_cheapest_spare_same_rarity_or_higher(self):
        res = run({}, self.HOLD, self.cfg())
        got = {s["card"]: (s["give_card"], s["asset"]) for s in posts(res)}
        # rares we lack get nothing (no rare spare); LAV-06 (40) the cheapest uncommon, LAV-07 the next,
        # the best common we lack (LAV-02, 16) the common spare
        self.assertEqual(got, {"LAV-06": ("MAL-06", 4), "LAV-07": ("LAV-08", 6), "LAV-02": ("LAV-01", 2)})
        for s in posts(res):
            r = s["record"]
            self.assertEqual((r["venue"], r["to"], s["action"]), ("rastro", None, "post"))
            self.assertGreaterEqual(r["value"] - r["give_value"], md.need_buy(r["value"], self.cfg()))

    def test_any_rarity_flag(self):
        res = run({}, self.HOLD, self.cfg(swap_any_rarity=True, swap_max=1))
        self.assertEqual([(s["card"], s["give_card"]) for s in posts(res)], [("LAV-09", "LAV-01")])

    def test_swap_max(self):
        res = run({}, self.HOLD, self.cfg(swap_max=2))
        self.assertEqual(sorted(s["card"] for s in posts(res)), ["LAV-06", "LAV-07"])
        self.assertEqual(posts(run({}, self.HOLD, self.cfg(swap_post=False))), [])

    def test_gain_rule_boundary(self):
        # our only SAL-01 (13, --sell-first-copies SAL) for a LAV common (16): 16 - 13 = 3 = need -> post;
        # for a SAL or LAT common (13, 11) it falls short; MAL commons (7) are under --swap-min-value
        res = run({}, {"SAL-01": [card(1, "SAL-01")]}, self.cfg(sell_first_copies=("SAL",), swap_max=10))
        self.assertEqual(sorted(s["card"] for s in posts(res)), ["LAV-01"])  # one copy given: one swap
        self.assertEqual(posts(res)[0]["record"]["gain"], 3.0)
        res = run({}, {"SAL-01": [card(1, "SAL-01")]}, self.cfg(sell_first_copies=("SAL",), margin_min=3.01))
        self.assertEqual(posts(res), [])

    def test_never_offers_a_held_cards_last_protected_copy(self):
        h = {"LAV-07": [card(1, "LAV-07")], "LAV-04": [card(2, "LAV-04")]}
        for c in (self.cfg(), self.cfg(sell_first_copies=("LAV",), swap_any_rarity=True)):
            self.assertEqual(posts(run({}, h, c)), [])

    def test_never_an_asset_another_offer_holds(self):
        mine = [{"id": 50, "maker": "t03", "status": "open", "venue": "rastro", "give": {"assets": [card(6, "LAV-08", 9)]},
                 "want": {"cash": 30}}]
        res = run({}, self.HOLD, self.cfg(), mine=mine)
        self.assertNotIn(6, [s["asset"] for s in posts(res)])
        note = next(s for s in res["swaps"] if s["action"] == "note")["record"]["reason"]
        self.assertIn("LAV-08 #6 (in our offer 50)", note)
        # a third copy that no offer holds may go
        h = {**self.HOLD, "LAV-08": two("LAV-08", 5, 6) + [card(7, "LAV-08", 12)]}
        self.assertIn(7, [s["asset"] for s in posts(run({}, h, self.cfg(), mine=mine))])

    def test_seller_config_assets_stay_with_the_seller(self):
        res = run({}, self.HOLD, self.cfg(), reserved={6, 4})
        self.assertEqual([(s["card"], s["asset"]) for s in posts(res)], [("LAV-02", 2)])
        res = run({}, self.HOLD, self.cfg(swap_seller_spares=True), reserved={6, 4})
        self.assertEqual(len(posts(res)), 3)

    def test_each_asset_and_card_once(self):
        h = {**self.HOLD, "LAV-08": two("LAV-08", 5, 6) + [card(7, "LAV-08", 12)]}
        res = run({}, h, self.cfg(swap_max=10, swap_any_rarity=True))
        assets = [s["asset"] for s in posts(res)]
        self.assertEqual(len(assets), len(set(assets)))
        gives = [s["give_card"] for s in posts(res)]
        self.assertEqual(len(gives), len(set(gives)))            # one copy per card given

    def test_a_live_swaps_copy_is_not_reused_while_it_is_cancelled(self):
        # our live swap asks MAL-01 (7, now under --swap-min-value) for LAV-08 #6: it is cancelled this tick,
        # and LAV-06 must not take #6 in the same tick (the cancel may fail)
        h = {"LAV-08": two("LAV-08", 5, 6)}
        book = {"MAL-01": {"offer": 900, "asset": 6, "give_card": "LAV-08", "to": None, "since": 90}}
        res = run({}, h, self.cfg(), swapbook=book)
        self.assertEqual(posts(res), [])
        self.assertEqual([(s["action"], s["card"]) for s in res["swaps"] if s["action"] != "note"],
                         [("cancel", "MAL-01")])

    def test_keep_replace_cancel(self):
        h = dict(self.HOLD)
        book = {"LAV-06": {"offer": 900, "asset": 4, "give_card": "MAL-06", "to": None, "since": 90},
                "LAV-07": {"offer": 901, "asset": 2, "give_card": "LAV-01", "to": None, "since": 90},
                "LAV-03": {"offer": 902, "asset": 99, "give_card": "LAV-05", "to": None, "since": 90}}
        res = run({}, h, self.cfg(), swapbook=book)
        acts = {s["card"]: s["action"] for s in res["swaps"] if s["action"] != "note"}
        self.assertEqual(acts["LAV-06"], "keep")
        self.assertEqual(acts["LAV-07"], "replace")              # a common for an uncommon: now LAV-08 #6
        self.assertEqual(acts["LAV-03"], "cancel")               # LAV-05 #99 is not ours any more

    def test_cancel_when_the_card_arrives_or_is_bought(self):
        h = {**self.HOLD, "LAV-06": [card(10, "LAV-06")]}
        book = {"LAV-06": {"offer": 900, "asset": 4, "give_card": "MAL-06", "to": None, "since": 90}}
        res = run({}, h, self.cfg(), swapbook=book)
        self.assertIn(("cancel", "card arrived"), [(s["action"], s["record"]["reason"]) for s in res["swaps"]
                                                   if s["card"] == "LAV-06"])
        res = run({"rastro": [listing(1, "LAV-06", 20)]}, self.HOLD, self.cfg(), swapbook=book)
        self.assertEqual(res["accept"]["card"], "LAV-06")
        self.assertIn("cancel our swap 900 first", rec(res, 1)["reason"])
        self.assertEqual([s["action"] for s in res["swaps"] if s["card"] == "LAV-06"], ["cancel"])

    def test_no_swap_for_a_card_we_bid_for(self):
        # without the bid, LAV-09 (112) is the first swap with --swap-any-rarity; with a live bid on it, never both
        self.assertEqual(posts(run({}, self.HOLD, self.cfg(swap_any_rarity=True)))[0]["card"], "LAV-09")
        res = run({}, self.HOLD, self.cfg(bids=True, bid_max=1, swap_any_rarity=True))
        bids = {b["card"] for b in res["bids"] if b["action"] == "post"}
        self.assertEqual(bids, {"LAV-09"})
        self.assertFalse(bids & {s["card"] for s in posts(res)})

    def test_the_copy_we_sell_this_tick_is_not_offered(self):
        res = run({"rastro": [bid(1, "LAV-08", 40)]}, self.HOLD, self.cfg())
        self.assertEqual((res["accept"]["side"], res["accept"]["asset"]), ("sell", 6))
        self.assertNotIn(6, [s["asset"] for s in posts(res)])
        self.assertNotIn("LAV-08", [s["give_card"] for s in posts(res)])

    def test_address_to_a_public_holder_lacking_our_card(self):
        tape = md.Tape().ingest([
            {"id": 1, "tick": 50, "type": "settlement", "payload": {"settlement": 1, "parties": ["t07", "t08"],
             "venue": "rastro", "price": 20, "items": [{"id": 70, "kind": "card", "ref": "LAV-06", "frm": "t07",
                                                        "to": "t08"}]}},
            {"id": 2, "tick": 51, "type": "gift.given", "payload": {"team": "t09", "cards": ["LAV-06", "MAL-06"]}}])
        h = {"MAL-06": two("MAL-06", 3, 4)}
        s = snap({}, h)
        res = md.decide(s, md.Valuer(CAT, AFFINITY, {"MAL-06": 2}), tape, md.Ledger(),
                        self.cfg(address_swaps=True, swap_max=1), {}, {})
        self.assertEqual([(p["card"], p["to"]) for p in posts(res)], [("LAV-06", "t08")])   # t09 holds MAL-06


# ---------------------------------------------------------------- the desk loop against fakes (no network)

class SwapDeskLoop(unittest.TestCase):
    setUp = base.DeskLoop.setUp          # a temp lease 25 s into tick 100 (no inherited tests)
    tearDown = base.DeskLoop.tearDown

    def desk(self, mode, board, assets, **kw):
        keyed = base.FakeKeyed(board, assets)
        kw.setdefault("swap_max", 2)
        c = md.Config(min_cash=0, bids=False, **kw)
        d = md.Desk(mode, c, base.FakePublic(board), keyed=keyed, lease=self.lease, log=base.MemLog(),
                    heartbeat=self.dir / "desk-market.json", out=self.lines.append, seller_config=None)
        return d, keyed

    ASSETS = [card(5, "LAV-08", 1), card(6, "LAV-08", 9)]

    def test_run_fills_with_our_asset_through_the_lease(self):
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS, swap_post=False)
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [("accept", 1, [6])])
        self.assertEqual(self.lease.snapshot()["accept"]["desk"], "market")
        self.assertEqual([(r["side"], r["cost"]) for r in d.ledger.rows], [("swap", 2)])

    def test_run_posts_swaps_in_the_right_shape(self):
        d, k = self.desk("run", [], self.ASSETS)
        d.tick(d.public.clock())
        lists = [w for w in k.writes if w[0] == "list"]
        self.assertEqual(len(lists), 1)                          # one spare: one swap
        _, give, want, venue, to, exp = lists[0]
        self.assertEqual(give, {"assets": [6]})
        self.assertEqual(list(want), ["cards"])
        self.assertEqual((venue, to, exp), ("rastro", None, 30))
        self.assertEqual(d.swapbook[want["cards"][0]]["asset"], 6)

    def test_run_swap_venue_and_expiry_flags(self):
        d, k = self.desk("run", [], self.ASSETS, swap_venue="v03", swap_expires=120)
        d.tick(d.public.clock())
        _, give, want, venue, to, exp = next(w for w in k.writes if w[0] == "list")
        self.assertEqual((venue, exp), ("v03", 120))

    def test_run_respects_stop_and_duel_lock(self):
        (self.dir / "STOP").touch()
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS)
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [])
        (self.dir / "STOP").unlink()
        (self.dir / "duel.lock").write_text(f"{self.now + 90:.1f}\n")
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS, swap_post=False)
        res = d.tick(d.public.clock())
        self.assertIsNone(res["accept"])
        self.assertEqual(rec(res, 1)["action"], "defer")
        self.assertEqual(k.writes, [])

    def test_run_yields_a_taken_accept(self):
        from lease import Lease
        other = Lease("chato", state_dir=self.dir, now=lambda: self.now, log=base.MemLog(), duel_lock=None)
        self.assertTrue(other.claim_accept(base.FakePublic([]).clock(), Lease.DEALER_FINAL))
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS, swap_post=False)
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [])

    def test_run_decides_again_on_fresh_reads(self):
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS, swap_post=False)
        calls = {"n": 0}
        first = d.public.board

        def board(vid):
            calls["n"] += 1
            return first(vid) if calls["n"] == 1 else {"offers": []}
        d.public.board = board
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [])

    def test_run_cancels_our_live_swap_on_the_card_before_accepting(self):
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS + [card(7, "MAL-06", 1),
                                                                                card(8, "MAL-06", 9)],
                         swap_post=False)
        mine = [{"id": 640, "maker": "t03", "status": "open", "venue": "rastro", "thread": None,
                 "give": {"cash": 0, "assets": [card(8, "MAL-06", 9)], "types": []},
                 "want": {"cash": 0, "assets": [], "types": ["card:SAL-09"]}}]
        k.my_offers = lambda: {"offers": mine}
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] in ("cancel", "accept")], [("cancel", 640), ("accept", 1, [6])])

    def test_take_cancels_a_live_swap_on_the_card_even_if_the_tick_did_not(self):
        # the safety net in take(): our swap asking SAL-09 is still live at the accept (its cancel in the tick's
        # batch was refused, say): it is cancelled first, then the accept goes
        d, k = self.desk("run", [swap(1, "SAL-09", "LAV-08")], self.ASSETS + [card(7, "MAL-06", 1),
                                                                                card(8, "MAL-06", 9)],
                         swap_post=False)
        mine = [{"id": 640, "maker": "t03", "status": "open", "venue": "rastro", "thread": None,
                 "give": {"cash": 0, "assets": [card(8, "MAL-06", 9)], "types": []},
                 "want": {"cash": 0, "assets": [], "types": ["card:SAL-09"]}}]
        k.my_offers = lambda: {"offers": mine}
        clock = d.public.clock()
        s = d.snapshot(clock)
        d.sync_swaps(s)
        res = md.decide(s, d.valuer, d.tape, d.ledger, d.cfg, d.bidbook, d.swapbook)
        d.take(clock, s, res["accept"])
        self.assertEqual([w for w in k.writes if w[0] in ("cancel", "accept")], [("cancel", 640), ("accept", 1, [6])])

    def test_watch_sends_nothing_and_follows_the_swap(self):
        d, k = self.desk("watch", [swap(1, "SAL-09", "LAV-08")], self.ASSETS)
        res = d.tick(d.public.clock())
        self.assertEqual(res["accept"]["offer"], 1)
        self.assertEqual(k.writes, [])
        self.assertTrue(any("SWAP" in ln and "TAKE" in ln for ln in self.lines))
        hb = json.loads((self.dir / "desk-market.json").read_text())
        self.assertEqual((hb["last_decision"]["kind"], hb["last_decision"]["give_card"]), ("swap", "LAV-08"))
        d.tick(d.public.clock())                                  # shadow: SAL-09 in, LAV-08 #6 out
        self.assertTrue(any("we hold 1 of SAL-09" in ln for ln in self.lines))
        self.assertEqual(d.last_snap["holdings"]["LAV-08"], [card(5, "LAV-08", 1)])

    def test_sync_reads_our_live_swaps_and_cancels_a_duplicate(self):
        d, k = self.desk("run", [], self.ASSETS + [card(7, "MAL-06", 1), card(8, "MAL-06", 9)], swap_max=0)
        mine = [{"id": oid, "maker": "t03", "status": "open", "venue": "rastro", "thread": None,
                 "give": {"cash": 0, "assets": [card(aid, ref, 9)], "types": []},
                 "want": {"cash": 0, "assets": [], "types": ["card:SAL-04"]}}
                for oid, aid, ref in ((700, 6, "LAV-08"), (701, 8, "MAL-06"))]
        k.my_offers = lambda: {"offers": mine}
        d.tick(d.public.clock())
        cancels = [w for w in k.writes if w[0] == "cancel"]
        self.assertEqual(sorted(cancels), [("cancel", 700), ("cancel", 701)])   # dupe + no longer wanted (max 0)


class Cli(unittest.TestCase):
    def test_team_venue_needs_its_flag(self):
        import contextlib
        import io
        argv = sys.argv
        try:
            sys.argv = ["market_desk.py", "plan", "--keyless", "--swap-venue", "v03"]
            with self.assertRaises(SystemExit) as e, contextlib.redirect_stderr(io.StringIO()) as err:
                md.main()
            self.assertIn("--swap-team-venue", err.getvalue())
            self.assertEqual(e.exception.code, 2)
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main()
