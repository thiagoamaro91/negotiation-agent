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


class Matches(unittest.TestCase):
    def test_a_team_one_card_from_a_page_gets_the_holder_of_a_spare_and_both_orders(self):
        res = build(T01 + T02, values={})
        m = next(m for m in res["matches"] if (m["team"], m["card"]) == ("t01", "LAV-04"))
        self.assertEqual([h["team"] for h in m["holders"]], ["t02"])
        price = m["price"]
        self.assertEqual(m["proposal"]["buyer"]["post"], {"venue": "v20", "give": {"cash": price},
                                                          "want": {"cards": ["LAV-04"]}, "expires_in_ticks": 240})
        self.assertEqual(m["proposal"]["sellers"][0]["post"]["give"], {"assets": [N + 2]})
        self.assertEqual(m["proposal"]["sellers"][0]["post"]["want"], {"cash": price})

    def test_team_3_is_never_a_buyer(self):
        # t03 holds LAV-01..03 by name too, so its LAV page lacks LAV-04 only: it must still not appear
        us = [ask(11, 5, "t03", 2 * N + 3, "LAV-01", 9), ask(12, 5, "t03", 2 * N + 4, "LAV-02", 9),
              ask(13, 5, "t03", 2 * N + 5, "LAV-03", 9)]
        res = build(us + T02, values={})
        self.assertNotIn("t03", {m["team"] for m in res["matches"]})
        self.assertNotIn("t03", res["teams"])

    def test_team_3_is_never_a_holder_even_with_spares(self):
        res = build(T01 + T03, values={})
        for m in res["matches"]:
            self.assertNotIn("t03", [h["team"] for h in m["holders"]])
            self.assertFalse(m["proposal"]["sellers"])

    def test_excluded_cards_never_appear(self):
        res = build(T01 + T02, values={}, exclude=("LAV-04",))
        self.assertEqual(res["matches"], [])
        self.assertEqual(res["withheld"], 1)

    def test_a_single_copy_is_no_spare_unless_its_holder_values_the_set_low_and_is_not_filling_it(self):
        one = [ask(7, 6, "t02", N + 1, "LAV-04", 90)]
        self.assertEqual(build(T01 + one, values={})["matches"][0]["holders"], [])
        low = build(T01 + one, values={"t02": {"LAV": 0.5}})["matches"][0]["holders"]
        self.assertEqual([(h["team"], h["spare"]) for h in low], [("t02", False)])

    def test_a_card_that_is_surely_held_is_no_match(self):
        lb = {"teams": [{"team": "t01", "album_filled": 4, "pages_complete": 1}]}   # the fourth card is held, unseen
        self.assertEqual(build(T01 + T02, lb=lb, values={})["matches"], [])


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


class Books(unittest.TestCase):
    def test_offers_the_feed_cannot_name_or_ours_are_never_pointed_at(self):
        book = {"rastro": [
            {"id": 1, "maker": "mX", "status": "open", "give": {"assets": [{"id": 9, "kind": "card", "ref": "LAV-04"}]},
             "want": {"cash": 50}},
            {"id": 2, "maker": "mY", "status": "open", "give": {"assets": [{"id": 8, "kind": "card", "ref": "LAV-04"}]},
             "want": {"cash": 40}},
            {"id": 3, "maker": "mZ", "status": "open", "give": {"assets": [{"id": 7, "kind": "card", "ref": "LAV-04"}]},
             "want": {"cash": 30}}]}
        live = mm.live_offers(book, {1: "t02", 3: "t03"}, mm.venue_fees([]))
        self.assertEqual([a["offer"] for a in live["LAV-04"]["asks"]], [1])

    def test_a_live_ask_makes_its_maker_a_holder_and_an_accept_for_the_buyer(self):
        book = {"rastro": [{"id": 1007, "maker": "m2", "status": "open", "give": {
            "assets": [{"id": N + 1, "kind": "card", "ref": "LAV-04"}]}, "want": {"cash": 90}}]}
        res = build(T01 + [ask(7, 6, "t02", N + 1, "LAV-04", 90, oid=1007)], books=book, values={})
        m = res["matches"][0]
        self.assertEqual(m["holders"][0]["asking"], {"price": 90, "venue": "rastro", "offer": 1007})
        self.assertEqual(m["proposal"]["accept"][0]["call"], "POST /api/offers/1007/accept")
        self.assertEqual(m["proposal"]["accept"][0]["fee"], 6)      # El Rastro: 5 % + 1 P


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
