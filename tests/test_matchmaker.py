"""La Celestina's matchmaker (tools/matchmaker.py). Run: python3 -m unittest discover tests"""
import collections
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import decks  # noqa: E402
import matchmaker as mm  # noqa: E402

N = decks.STARTER


def ev(i, tick, etype, **p):
    return {"id": i, "tick": tick, "type": etype, "payload": p}


def ask(i, tick, maker, aid, ref, cash, venue="rastro", oid=None):
    return ev(i, tick, "offer.listed", offer={"id": oid or 1000 + i, "maker": maker, "venue": venue, "give": {
        "cash": 0, "assets": [{"id": aid, "kind": "card", "ref": ref}], "types": []},
        "want": {"cash": cash, "assets": [], "types": []}})


def cat(n_page=4):
    return {"sets": [{"id": "LAV", "name": "Lavapiés", "released": True, "cards": [
        {"id": f"LAV-0{i}", "name": f"Card {i}", "rarity": "common" if i < 4 else "rare", "book": 10 if i < 4 else 70,
         "print_run": 300 if i < 4 else 30, "minted": 20, "page": True} for i in range(1, n_page + 1)]}],
        "packs": [], "values": {"page_bonus": 0.25}}


JOIN = [ev(1, 0, "team.joined", team="t01", name="Team 1"), ev(2, 0, "team.joined", team="t02", name="Team 2"),
        ev(3, 0, "team.joined", team="t03", name="Team 3")]
LB = {"teams": [{"team": "t01", "name": "Team 1", "album_filled": 3, "pages_complete": 0},
                {"team": "t02", "name": "Team 2", "album_filled": 1, "pages_complete": 0},
                {"team": "t03", "name": "Team 3", "album_filled": 3, "pages_complete": 0}]}
# t01 holds LAV-01..03 (lacks LAV-04); t02 two copies of LAV-04; t03 (us) LAV-01..03 and two LAV-04... and lacks nothing
T01 = [ask(4, 5, "t01", 1, "LAV-01", 9), ask(5, 5, "t01", 2, "LAV-02", 9), ask(6, 5, "t01", 3, "LAV-03", 9)]
T02 = [ask(7, 6, "t02", N + 1, "LAV-04", 90), ask(8, 6, "t02", N + 2, "LAV-04", 90)]
T03 = [ask(9, 6, "t03", 2 * N + 1, "LAV-04", 90), ask(10, 6, "t03", 2 * N + 2, "LAV-04", 90)]


def build(events, **kw):
    return mm.build(JOIN + events, kw.pop("catalog", cat()), kw.pop("lb", LB), kw.pop("books", {}), [], **kw)


def bid_offer(oid, ref, cash, to=None, expires=None):
    return {"id": oid, "maker": "mB", "status": "open", "to": to, "expires_tick": expires,
            "give": {"cash": cash, "assets": [], "types": []}, "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


def named(oid, team, venue="rastro"):
    """The feed's offer.listed that names the maker of a book offer."""
    return ev(oid, 7, "offer.listed", offer={"id": oid, "maker": team, "venue": venue})


class Matches(unittest.TestCase):
    def test_an_inferred_need_with_a_spare_holder_gets_the_v20_orders_and_is_labelled_inferred(self):
        res = build(T01 + T02, values={})
        m = next(m for m in res["matches"] if (m["team"], m["card"]) == ("t01", "LAV-04"))
        self.assertEqual((m["tier"], m["inferred"], m["action"]), (4, True, None))
        self.assertIsNotNone(m["p_missing"])
        self.assertEqual([h["team"] for h in m["holders"]], ["t02"])
        price = m["price"]
        self.assertEqual(m["proposal"]["buyer"]["post"], {"venue": "v20", "give": {"cash": price},
                                                          "want": {"cards": ["LAV-04"]}, "expires_in_ticks": 240})
        self.assertEqual(m["proposal"]["sellers"][0]["post"]["give"], {"assets": [N + 2]})
        self.assertEqual(m["proposal"]["sellers"][0]["post"]["want"], {"cash": price})

    def test_team_3_is_never_a_buyer(self):
        # t03 holds LAV-01..03 by name too, so its LAV page lacks LAV-04 only; and it bids for LAV-04 live
        us = [ask(11, 5, "t03", 2 * N + 3, "LAV-01", 9), ask(12, 5, "t03", 2 * N + 4, "LAV-02", 9),
              ask(13, 5, "t03", 2 * N + 5, "LAV-03", 9), named(77, "t03")]
        res = build(us + T02, values={}, books={"rastro": [bid_offer(77, "LAV-04", 80)]})
        self.assertNotIn("t03", {m["team"] for m in res["matches"]})
        self.assertNotIn("t03", res["teams"])

    def test_team_3_is_never_a_holder_even_with_spares(self):
        res = build(T01 + T03 + [named(78, "t01")], values={}, books={"rastro": [bid_offer(78, "LAV-04", 80)]})
        self.assertTrue(res["matches"])
        for m in res["matches"]:
            self.assertNotIn("t03", [h["team"] for h in m["holders"]])
            self.assertNotIn("t03", (m["action"] or {}).get("who", []))
            self.assertFalse((m["proposal"] or {}).get("sellers"))

    def test_excluded_cards_never_appear_live_or_inferred(self):
        res = build(T01 + T02 + [named(78, "t01")], values={}, exclude=("LAV-04",),
                    books={"rastro": [bid_offer(78, "LAV-04", 80)]})
        self.assertEqual(res["matches"], [])
        self.assertEqual(res["withheld"], 1)

    def test_a_single_copy_is_no_spare_unless_its_holder_values_the_set_low_and_is_not_filling_it(self):
        one = [ask(7, 6, "t02", N + 1, "LAV-04", 90)]
        self.assertEqual(build(T01 + one, values={})["matches"][0]["holders"], [])
        low = build(T01 + one, values={"t02": {"LAV": 0.5}})["matches"][0]["holders"]
        self.assertEqual([(h["team"], h["spare"]) for h in low], [("t02", False)])

    def test_a_card_that_is_surely_held_is_no_inferred_match(self):
        lb = {"teams": [{"team": "t01", "album_filled": 4, "pages_complete": 1}]}   # the fourth card is held, unseen
        self.assertEqual(build(T01 + T02, lb=lb, values={})["matches"], [])


class LiveFirst(unittest.TestCase):
    FLOOR = {"chato/buys/rare": {"low": 45, "median": 49, "high": 52, "n": 5}}

    def test_a_live_bid_with_a_known_holder_is_tier_1_and_the_holder_accepting_it_is_the_action(self):
        res = build(T01 + T02 + [named(78, "t01")], values={}, books={"rastro": [bid_offer(78, "LAV-04", 80)]})
        m = res["matches"][0]
        self.assertEqual((m["tier"], m["inferred"], m["p_missing"]), (1, False, None))
        self.assertEqual((m["action"]["offer"], m["action"]["who"], m["action"]["side"]), (78, ["t02"], "bid"))
        self.assertEqual(m["action"]["call"], "POST /api/offers/78/accept")
        self.assertEqual(len([x for x in res["matches"] if (x["team"], x["card"]) == ("t01", "LAV-04")]), 1)

    def test_a_fair_live_bid_with_no_supplier_we_can_name_is_tier_2_any_holder(self):
        res = build(T01 + [named(78, "t01")], values={}, books={"rastro": [bid_offer(78, "LAV-04", 80)]})
        m = res["matches"][0]
        self.assertEqual((m["tier"], m["action"]["who"], m["holders"]), (2, [], []))

    def test_a_bid_below_what_the_dealers_pay_is_only_tier_2(self):
        books = {"rastro": [bid_offer(78, "LAV-04", 20)]}
        res = build(T01 + T02 + [named(78, "t01")], values={}, books=books, dprices=self.FLOOR)
        self.assertEqual(res["matches"][0]["tier"], 2)
        res = build(T01 + T02 + [named(78, "t01")], values={}, books={"rastro": [bid_offer(78, "LAV-04", 50)]},
                    dprices=self.FLOOR)
        self.assertEqual(res["matches"][0]["tier"], 1)

    def test_a_swap_is_accepted_directly_and_a_lopsided_one_is_only_tier_2(self):
        def swap(oid, gives, aid):
            return {"id": oid, "maker": "mS", "status": "open", "give": {"assets": [{"id": aid, "kind": "card",
                                                                                     "ref": gives}]},
                    "want": {"types": ["card:LAV-04"]}}
        res = build(T01 + T02 + [named(79, "t01")], values={}, books={"v02": [swap(79, "LAV-01", 1)]})
        m = res["matches"][0]
        self.assertEqual((m["action"]["side"], m["action"]["gives"], m["tier"]), ("swap", "LAV-01", 2))
        self.assertEqual(m["action"]["call"], "POST /api/offers/79/accept")

    def test_offers_about_to_expire_are_never_named(self):
        book = {"rastro": [bid_offer(78, "LAV-04", 80, expires=105)]}
        live = mm.live_offers(book, {78: "t01"}, mm.venue_fees([]), now_tick=100)
        self.assertEqual(live, {})
        live = mm.live_offers(book, {78: "t01"}, mm.venue_fees([]), now_tick=90)
        self.assertEqual([b["offer"] for b in live["LAV-04"]["bids"]], [78])

    def test_within_a_tier_our_venue_comes_first_then_el_rastro_then_other_teams_venues(self):
        t04 = [ev(14, 0, "team.joined", team="t04", name="Team 4")]
        books = {"v07": [bid_offer(80, "LAV-04", 90)], "rastro": [bid_offer(81, "LAV-04", 85)],
                 "v20": [bid_offer(82, "LAV-04", 70)]}
        feed = T01 + T02 + t04 + [named(80, "t01", "v07"), named(81, "t04"), named(82, "t04", "v20")]
        res = build(feed, values={}, books=books)
        self.assertEqual([m["action"]["venue"] for m in res["matches"]], ["v20", "v07"])   # t04 on v20, t01 best
        books = {"v07": [bid_offer(80, "LAV-04", 90)], "rastro": [bid_offer(81, "LAV-04", 85)]}
        res = build(T01 + T02 + t04 + [named(80, "t01", "v07"), named(81, "t04")], values={}, books=books)
        self.assertEqual([m["action"]["venue"] for m in res["matches"]], ["rastro", "v07"])

    def test_a_live_ask_and_an_inferred_need_make_tier_3_for_the_buyer_to_accept(self):
        events, catalog, lb, books = mm.sample()
        m = mm.build(events, catalog, lb, books, [], values={})["matches"][0]
        self.assertEqual((m["tier"], m["action"]["who"], m["action"]["offer"]), (3, ["t01"], 1007))


class Odds(unittest.TestCase):
    PAGES = {"A": ["A1", "A2", "A3"], "B": ["B1", "B2", "B3"]}

    def test_the_count_of_complete_pages_pins_which_page_is_complete(self):
        held = collections.Counter({"A1": 1, "A2": 1, "B1": 1})
        odds = mm.missing_odds(held, self.PAGES, (4, 1))            # one unseen card, and it completes a page: A3
        self.assertEqual((odds["p"]["A3"], odds["p"]["B2"], odds["p"]["B3"]), (0.0, 1.0, 1.0))
        self.assertTrue(odds["pages_exact"])
        odds = mm.missing_odds(held, self.PAGES, (4, 2))            # two complete pages from one card: impossible,
        self.assertTrue(0 < odds["p"]["A3"] < 1)                    # so the page count is dropped, the album kept
        self.assertFalse(odds["pages_exact"])

    def test_no_unseen_card_means_every_unnamed_card_is_missing(self):
        held = collections.Counter({"A1": 1, "A2": 1, "B1": 1})
        odds = mm.missing_odds(held, self.PAGES, (3, 0))
        self.assertEqual(odds["p"], {"A3": 1.0, "B2": 1.0, "B3": 1.0})
        self.assertTrue(odds["pages_exact"])

    def test_without_an_album_count_every_unnamed_card_is_a_coin_flip(self):
        odds = mm.missing_odds(collections.Counter({"A1": 1}), self.PAGES, None)
        self.assertEqual(set(odds["p"].values()), {0.5})


class Review67(unittest.TestCase):
    """Review BLOCK on #67 (A2-A5): directed offers, the venue owner, every card of an offer, holdings as of a tick."""

    def test_a_bid_addressed_to_one_team_is_for_that_team_only(self):
        t07 = [ev(15, 0, "team.joined", team="t07", name="Team 7")]
        bid = dict(bid_offer(78, "LAV-04", 80), to="t07")
        res = build(T01 + T02 + t07 + [named(78, "t01")], values={}, books={"rastro": [bid]})
        m = res["matches"][0]
        self.assertEqual((m["action"]["to"], m["action"]["who"], m["holders"], m["tier"]), ("t07", ["t07"], [], 2))
        bid = dict(bid_offer(78, "LAV-04", 80), to="t02")
        m = build(T01 + T02 + [named(78, "t01")], values={}, books={"rastro": [bid]})["matches"][0]
        self.assertEqual((m["action"]["who"], m["tier"]), (["t02"], 1))

    def test_a_team_is_never_asked_to_accept_on_its_own_venue(self):
        venues = [{"venue": "v07", "owner": "t02", "status": "open"}]
        res = mm.build(JOIN + T01 + T02 + [named(80, "t01", "v07")], cat(), LB, {"v07": [bid_offer(80, "LAV-04", 90)]},
                       venues, values={})
        m = res["matches"][0]
        self.assertNotIn("t02", m["action"]["who"])                      # the only holder owns v07
        self.assertEqual(m["tier"], 2)
        ask_v = [{"venue": "v05", "owner": "t01", "status": "open"}]     # the buyer owns the venue of the only ask
        book = {"v05": [{"id": 1007, "maker": "m2", "status": "open", "give": {
            "assets": [{"id": N + 1, "kind": "card", "ref": "LAV-04"}]}, "want": {"cash": 90}}]}
        res = mm.build(JOIN + T01 + [ask(7, 6, "t02", N + 1, "LAV-04", 90, venue="v05", oid=1007)], cat(), LB, book,
                       ask_v, values={})
        self.assertEqual([m["tier"] for m in res["matches"]], [4])

    def test_the_action_itself_never_names_the_owner_or_anyone_but_the_addressee(self):
        o = {"offer": 1, "venue": "v07", "team": "t01", "price": 9, "fee": 0, "to": None}
        self.assertEqual(mm.accept_action(o, "bid", ["t02", "t05"], {}, {"v07": "t02"})["who"], ["t05"])
        self.assertEqual(mm.accept_action(dict(o, to="t06"), "bid", ["t05", "t06"], {}, {})["who"], ["t06"])

    def test_a_swap_that_gives_an_excluded_card_never_appears(self):
        swap = {"id": 79, "maker": "mS", "status": "open", "give": {"assets": [{"id": 1, "kind": "card", "ref": "LAV-01"}]},
                "want": {"types": ["card:LAV-04"]}}
        res = build(T01 + T02 + [named(79, "t01")], values={}, books={"v02": [swap]}, exclude=("LAV-01",))
        self.assertEqual([m for m in res["matches"] if m["action"]], [])

    def test_a_holding_from_public_trades_is_dated_and_a_live_ask_is_live(self):
        m = build(T01 + T02, values={})["matches"][0]
        self.assertEqual((m["holders"][0]["seen"], m["holders"][0]["as_of"]), ("reconstructed", 6))
        self.assertIn("Team 2 ×2 at tick 6 (reconstructed)", mm.report(build(T01 + T02, values={})))
        book = {"rastro": [{"id": 1007, "maker": "m2", "status": "open", "give": {
            "assets": [{"id": N + 1, "kind": "card", "ref": "LAV-04"}]}, "want": {"cash": 90}}]}
        m = build(T01 + [ask(7, 6, "t02", N + 1, "LAV-04", 90, oid=1007)], books=book, values={})["matches"][0]
        self.assertEqual(m["holders"][0]["seen"], "live ask")


class Books(unittest.TestCase):
    def test_offers_the_feed_cannot_name_or_ours_are_never_pointed_at(self):
        book = {"rastro": [
            {"id": 1, "maker": "mX", "status": "open", "give": {"assets": [{"id": 9, "kind": "card", "ref": "LAV-04"}]},
             "want": {"cash": 50}},
            {"id": 2, "maker": "mY", "status": "open", "give": {"assets": [{"id": 8, "kind": "card", "ref": "LAV-04"}]},
             "want": {"cash": 40}},
            {"id": 3, "maker": "mZ", "status": "open", "give": {"assets": [{"id": 7, "kind": "card", "ref": "LAV-04"}]},
             "want": {"cash": 30}}]}
        book["rastro"].append({"id": 4, "maker": "mW", "status": "open", "to": "t03", "want": {"cash": 20},
                               "give": {"assets": [{"id": 6, "kind": "card", "ref": "LAV-04"}]}})   # addressed to us
        live = mm.live_offers(book, {1: "t02", 3: "t03", 4: "t02"}, mm.venue_fees([]))
        self.assertEqual([a["offer"] for a in live["LAV-04"]["asks"]], [1])

    def test_a_live_ask_makes_its_maker_a_holder(self):
        book = {"rastro": [{"id": 1007, "maker": "m2", "status": "open", "give": {
            "assets": [{"id": N + 1, "kind": "card", "ref": "LAV-04"}]}, "want": {"cash": 90}}]}
        res = build(T01 + [ask(7, 6, "t02", N + 1, "LAV-04", 90, oid=1007)], books=book, values={})
        m = res["matches"][0]
        self.assertEqual(m["holders"][0]["asking"], {"price": 90, "venue": "rastro", "offer": 1007})
        self.assertEqual(m["action"]["fee"], 6)      # El Rastro: 5 % + 1 P


class Price(unittest.TestCase):
    def test_the_fair_price_stays_between_the_dealers(self):
        self.assertEqual(mm.suggest_price(17.5, 20, 14, 23), 18)
        self.assertEqual(mm.suggest_price(5, 7, 6, 9), 6)          # below the holder's dealer floor
        self.assertEqual(mm.suggest_price(30, 20, 14, 23), 23)     # above the buyer's dealer price
        self.assertEqual(mm.suggest_price(17, 20, 25, 23), 24)     # floor above cap: their midpoint
        self.assertEqual(mm.suggest_price(None, 20, None, None), 20)
        self.assertIsNone(mm.suggest_price(None, None, 5, 9))


class Report(unittest.TestCase):
    def test_the_report_never_names_team_3(self):
        text = mm.report(build(T01 + T02 + T03, values={}))
        self.assertNotIn("Team 3", text)
        self.assertNotIn("t03", text)

    def test_selftest_runs(self):
        mm.selftest()


if __name__ == "__main__":
    unittest.main()


def two_pages():
    """LAV and SAL, four page cards each (three commons, one rare), plus a non-page epic in LAV."""
    sets = []
    for sid in ("LAV", "SAL"):
        cards = [{"id": f"{sid}-0{i}", "name": f"{sid} {i}", "rarity": "common" if i < 4 else "rare",
                  "book": 10 if i < 4 else 70, "print_run": 300, "minted": 20, "page": True} for i in range(1, 5)]
        if sid == "LAV":
            cards.append({"id": "LAV-11", "name": "Epic", "rarity": "epic", "book": 150, "print_run": 9, "minted": 3,
                          "page": False})
        sets.append({"id": sid, "name": sid, "released": True, "cards": cards})
    return {"sets": sets, "packs": [], "values": {"page_bonus": 0.25}}


def lb(**rows):
    """{"t01": (album_filled, pages_complete[, rarest ref])} -> a leaderboard body."""
    out = []
    for t, r in rows.items():
        row = {"team": t, "name": f"Team {int(t[1:])}", "album_filled": r[0], "pages_complete": r[1]}
        if len(r) > 2:
            row["rarest"] = {"ref": r[2]}
        out.append(row)
    return {"teams": out}


def need(res, team, card):
    return next((m for m in res["matches"] if (m["team"], m["card"]) == (team, card) and m["tier"] >= 3), None)


T01_LAV2 = [ask(4, 5, "t01", 1, "LAV-01", 9), ask(5, 5, "t01", 2, "LAV-02", 9)]


class LeaderboardFacts(unittest.TestCase):
    """Hard facts of the public leaderboard bound the deck inference (mutation-first: each test fails without its
    guard in build())."""

    def test_a_teams_rarest_card_is_held_so_it_is_never_missing(self):
        # t01 names LAV-01, LAV-02; one more page card unseen: LAV-04 (a rare) is "missing" at p ~0.87 by rarity alone
        base = build(T01_LAV2 + T02, values={}, lb=lb(t01=(3, 0), t02=(1, 0)))
        self.assertIsNotNone(need(base, "t01", "LAV-04"))
        res = build(T01_LAV2 + T02, values={}, lb=lb(t01=(3, 0, "LAV-04"), t02=(1, 0)))
        self.assertIsNone(need(res, "t01", "LAV-04"))
        self.assertEqual(res["teams"]["t01"]["held_by_leaderboard"], ["LAV-04"])

    def test_a_deck_naming_more_page_cards_than_album_filled_gets_no_inferred_need(self):
        # t01 names LAV-01..03 but the leaderboard says it fills 2 slots: one named card is gone. Without the guard,
        # unseen = max(0, 2 - 3) = 0 and LAV-04 reads as missing at p 1.0, the most confident exactly when wrong.
        res = build(T01 + T02, values={}, lb=lb(t01=(2, 0), t02=(1, 0)))
        self.assertIsNone(need(res, "t01", "LAV-04"))
        self.assertFalse(res["teams"]["t01"]["consistent"])
        self.assertIn("album_filled is 2", res["teams"]["t01"]["inconsistent"])
        self.assertEqual(res["withheld_inconsistent"], 1)

    def test_a_deck_no_choice_of_unnamed_cards_fits_gets_no_inferred_need(self):
        # t01 names three cards of each page; album 7 with 2 complete pages needs LAV-04 AND SAL-04 from 1 unseen card.
        # Without the guard the fallback drops the page count and both read as missing at p 0.5.
        n = N
        t01 = T01 + [ask(20, 5, "t01", 4, "SAL-01", 9), ask(21, 5, "t01", 5, "SAL-02", 9),
                     ask(22, 5, "t01", 6, "SAL-03", 9)]
        t02 = T02 + [ask(23, 6, "t02", n + 3, "SAL-04", 90), ask(24, 6, "t02", n + 4, "SAL-04", 90)]
        res = build(t01 + t02, values={}, catalog=two_pages(), lb=lb(t01=(7, 2), t02=(2, 0)))
        self.assertEqual([m for m in res["matches"] if m["team"] == "t01"], [])
        self.assertFalse(res["teams"]["t01"]["consistent"])
        self.assertIn("pages_complete 2", res["teams"]["t01"]["inconsistent"])
        ok = build(t01 + t02, values={}, catalog=two_pages(), lb=lb(t01=(7, 1), t02=(2, 0)))   # one page: it fits
        self.assertTrue(ok["teams"]["t01"]["consistent"])

    def test_a_consistent_deck_still_gets_its_inferred_need(self):
        res = build(T01 + T02, values={}, lb=lb(t01=(3, 0), t02=(1, 0)))
        self.assertIsNotNone(need(res, "t01", "LAV-04"))
        self.assertTrue(res["teams"]["t01"]["consistent"])


def census(tick=10, cards=()):
    return {"meta": {"tick_start": tick - 2, "tick_end": tick},
            "cards": [{"id": i, "ref": r, "owner": o} for i, r, o in cards]}


class Census(unittest.TestCase):
    """--census: holdings read from the server replace the rebuilt decks."""
    CARDS = [(1, "LAV-01", "t01"), (2, "LAV-02", "t01"), (3, "LAV-03", "t01"), (100, "LAV-04", "t02"),
             (101, "LAV-04", "t02"), (102, "LAV-04", "abuela")]

    def test_census_holders_are_facts_dated_by_the_census_tick_with_their_asset_ids(self):
        # the feed names nothing at all: only the census can say who holds what
        res = build([], values={}, lb=lb(t01=(3, 0), t02=(1, 0)), census=census(10, self.CARDS))
        m = need(res, "t01", "LAV-04")
        self.assertIsNotNone(m)
        self.assertEqual(m["basis"], "census tick 10")
        h = m["holders"][0]
        self.assertEqual((h["team"], h["seen"], h["asset"], h["copies"]), ("t02", "census tick 10", 101, 2))
        self.assertEqual(res["census_tick"], 10)
        self.assertEqual(m["p_missing"], 1.0)    # album_filled 3 = the three the census names: nothing unseen

    def test_a_settlement_after_the_census_moves_the_card(self):
        moved = [ev(30, 12, "settlement", parties=["t02", "t01"], venue="rastro", persona=None, price=60,
                    items=[{"id": 100, "kind": "card", "ref": "LAV-04", "frm": "t02", "to": "t01"}])]
        res = build(moved, values={}, lb=lb(t01=(4, 1), t02=(1, 0)), census=census(10, self.CARDS))
        self.assertIsNone(need(res, "t01", "LAV-04"))
        self.assertEqual(res["teams"]["t01"]["named_page_cards"], 4)      # the moved copy is t01's now
        before = build(moved, values={}, lb=lb(t01=(4, 1), t02=(1, 0)), census=census(20, self.CARDS))
        self.assertEqual(before["teams"]["t01"]["named_page_cards"], 3)   # a settlement before the census is in it

    def test_load_census_picks_the_newest_snapshot_in_a_directory(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for t in (900, 1450):
                (Path(d) / f"cards-2026-10-04-t{t}.json").write_text(json.dumps(census(t, self.CARDS)))
            (Path(d) / "cards-2026-10-04-t9999-history.json").write_text("{}")
            self.assertEqual(mm.census_tick(mm.load_census(d)), 1450)
            (Path(d) / "cards-2026-10-04-t1500-topup.json").write_text(json.dumps(census(1500, self.CARDS)))
            self.assertEqual(mm.census_tick(mm.load_census(d)), 1500)

    def test_a_card_that_moved_during_the_walk_ends_with_its_last_holder(self):
        # the walk ran from tick 8 to 10; id 100 was read at t02 before it settled to t01 at tick 9
        moved = [ev(30, 9, "settlement", parties=["t02", "t01"], venue="rastro", persona=None, price=60,
                    items=[{"id": 100, "kind": "card", "ref": "LAV-04", "frm": "t02", "to": "t01"}])]
        _, by_team = mm.census_holdings(census(10, self.CARDS), moved)
        self.assertEqual(by_team["t01"]["held"]["LAV-04"], 1)
        self.assertEqual(by_team["t02"]["held"]["LAV-04"], 1)


class RunOnce(unittest.TestCase):
    def test_a_missing_census_falls_back_to_the_feed_and_never_stops_the_board(self):
        import argparse
        import io
        import unittest.mock as um
        data = {"events": JOIN + T01 + T02, "catalog": cat(), "leaderboard": LB, "venues": [], "books": {}}
        args = argparse.Namespace(feed="/nonexistent", live=False, exclude="", exclude_from=None, no_values=True,
                                  census="/nonexistent/census", exclude_max_age_min=60)
        err = io.StringIO()
        with um.patch.object(mm, "offline_inputs", return_value=data), um.patch("sys.stderr", err):
            res = mm.run_once(args)
        self.assertIsNone(res["census_tick"])
        self.assertIsNotNone(need(res, "t01", "LAV-04"))
        self.assertIn("census: WARNING", err.getvalue())


class ExcludeFrom(unittest.TestCase):
    """--exclude-from: the cards we lack, from our freshest holdings snapshot; the built-in list when it is not."""
    FALLBACK = ("SAL-01", "SAL-02")

    def write(self, d, name, assets, age_min=0, account="t03"):
        import json
        import os
        import time as _t
        f = Path(d) / name
        f.write_text(json.dumps({"id": account, "tick": 1500, "assets": [{"id": i, "kind": "card", "ref": r}
                                                                          for i, r in enumerate(assets)]
                                 + [{"id": 99, "kind": "pack", "ref": "sobre_oro"}]}))
        t = _t.time() - age_min * 60
        os.utime(f, (t, t))
        return str(f)

    def run_(self, paths, **kw):
        said = []
        cards, line = mm.exclude_from(paths, two_pages(), self.FALLBACK, say=said.append, **kw)
        return cards, line, said

    def test_a_fresh_snapshot_excludes_exactly_the_page_cards_we_lack(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = self.write(d, "me.json", ["LAV-01", "LAV-02", "LAV-03", "LAV-04", "SAL-01", "SAL-03", "LAV-11"])
            cards, line, said = self.run_([f])
        self.assertEqual(cards, {"SAL-02", "SAL-04"})     # every lacking page card; no epic, nothing we hold
        self.assertEqual(said, [])
        self.assertIn("2 cards we lack", line)
        self.assertNotIn("SAL-02", line)                   # the line is counts only, never the cards

    def test_a_missing_file_falls_back_to_the_built_in_list_and_says_so(self):
        cards, line, said = self.run_(["/nonexistent/me.json"])
        self.assertEqual(cards, set(self.FALLBACK))
        self.assertEqual(len(said), 1)
        self.assertIn("WARNING", said[0])

    def test_a_stale_file_adds_the_built_in_list_and_says_so(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = self.write(d, "me.json", ["LAV-01", "LAV-02", "LAV-03", "LAV-04", "SAL-01", "SAL-02", "SAL-03"],
                           age_min=90)
            cards, line, said = self.run_([f], max_age_min=60)
        self.assertEqual(cards, {"SAL-04"} | set(self.FALLBACK))
        self.assertEqual(len(said), 1)
        self.assertIn("min old", said[0])

    def test_age_is_game_time_when_the_tick_is_known(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:   # an old file (git pull overnight) but the clock was paused: fresh
            f = self.write(d, "me.json", ["LAV-01", "LAV-02", "LAV-03", "LAV-04", "SAL-01", "SAL-02", "SAL-03"],
                           age_min=600)
            self.assertEqual(self.run_([f], now_tick=1510)[0], {"SAL-04"})          # 10 ticks x 15 s
            self.assertEqual(self.run_([f], now_tick=1800)[0], {"SAL-04"} | set(self.FALLBACK))   # 75 min of play

    def test_another_teams_account_or_garbage_falls_back(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = self.write(d, "me.json", ["LAV-01"], account="t05")
            g = Path(d) / "bad.json"
            g.write_text("{not json")
            self.assertEqual(self.run_([f])[0], set(self.FALLBACK))
            self.assertEqual(self.run_([str(g)])[0], set(self.FALLBACK))

    def test_the_freshest_of_several_snapshots_is_used(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            old = self.write(d, "me.json", [], age_min=30)
            new = self.write(d, "me_live.json", ["LAV-01", "LAV-02", "LAV-03", "LAV-04", "SAL-01", "SAL-02",
                                                 "SAL-03"], age_min=1)
            cards, _, _ = self.run_([old, new])
        self.assertEqual(cards, {"SAL-04"})


class Validate(unittest.TestCase):
    def test_validation_counts_recall_precision_and_a_false_missing(self):
        # we listed LAV-01..03 (ids 31-33 in the test's join order: t03 is third), then sold LAV-03; we hold LAV-04
        # unseen. The album says 3 filled, 0 complete: one of LAV-03 / LAV-04 unseen, and by rarity LAV-04 (a rare)
        # reads as missing at p ~0.87 although we hold it.
        b = 2 * N
        events = JOIN + [ask(4, 5, "t03", b + 1, "LAV-01", 9), ask(5, 5, "t03", b + 2, "LAV-02", 9),
                         ask(6, 5, "t03", b + 3, "LAV-03", 9),
                         ev(7, 6, "settlement", parties=["t03", "t01"], venue="rastro", persona=None, price=9,
                            items=[{"id": b + 3, "kind": "card", "ref": "LAV-03", "frm": "t03", "to": "t01"}])]
        me = {"id": "t03", "tick": 10, "assets": [{"id": b + 1, "kind": "card", "ref": "LAV-01"},
                                                 {"id": b + 2, "kind": "card", "ref": "LAV-02"},
                                                 {"id": 500, "kind": "card", "ref": "LAV-04"}],
              "album": {"filled": 3, "pages": [{"set": "LAV", "have": 3, "of": 4, "complete": False}]}}
        r = mm.validate(events, cat(), me)
        self.assertEqual((r["page_cards"], r["page_named"], r["page_right"]), (3, 2, 2))
        self.assertEqual((r["recall"], r["precision"]), (0.667, 1.0))
        self.assertEqual([f["card"] for f in r["false_missing"]], ["LAV-04"])
        self.assertTrue(r["consistent"])
