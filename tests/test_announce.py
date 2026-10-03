"""tools/announce.py: the market read right (best sides with ids, v20's live offers from the feed, makers named from
the feed), the message variants, and that nothing posts without --yes. Offline: no key, no network.
Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import announce as an  # noqa: E402

_ids = iter(range(1000, 10**6))


def ask(ref, cash, status="open", venue="rastro", maker=None, to=None, oid=None, asset=None):
    return {"id": oid or next(_ids), "maker": maker, "to": to, "venue": venue, "status": status,
            "give": {"cash": 0, "assets": [{"id": asset, "kind": "card", "ref": ref}], "types": []},
            "want": {"cash": cash, "assets": [], "types": []}}


def bid(ref, cash, status="open", venue="rastro", maker=None, to=None, oid=None):
    return {"id": oid or next(_ids), "maker": maker, "to": to, "venue": venue, "status": status,
            "give": {"cash": cash, "assets": [], "types": []},
            "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


def swap(give_ref, want_ref, **kw):
    o = ask(give_ref, 0, **kw)
    o["want"] = {"cash": 0, "assets": [], "types": [f"card:{want_ref}"]}
    return o


def listed(o, tick=100, actor=None):
    return {"type": "offer.listed", "tick": tick, "actor": actor or o.get("maker") or "",
            "payload": {"venue": o["venue"], "offer": dict(o, expires_tick=o.get("expires_tick", tick + 60))}}


BOOK = [ask("MAL-04", 8, oid=1), ask("MAL-04", 9), bid("MAL-04", 7, oid=2), bid("MAL-04", 6),
        ask("LAV-09", 120), bid("LAV-09", 99), bid("SAL-09", 68), bid("RET-01", 2),
        swap("LAT-02", "LAV-07"), ask("SAL-03", 5, status="cancelled")]
NAMES = {1: "t09", 2: "t16"}


class TestBook(unittest.TestCase):
    def test_best_bid_and_ask_per_card_swaps_and_closed_skipped(self):
        bids, asks = an.rastro_book(BOOK)
        self.assertEqual(bids, {"MAL-04": 7, "LAV-09": 99, "SAL-09": 68, "RET-01": 2})
        self.assertEqual(asks, {"MAL-04": 8, "LAV-09": 120})

    def test_market_sides_keep_ids_and_venues_and_skip_our_venue(self):
        bids, asks = an.market_sides(BOOK + [bid("MAL-04", 50, venue="v20"), ask("MAL-04", 7, venue="v07", oid=3)])
        self.assertEqual(bids["MAL-04"], (7, 2, "rastro"))       # the v20 bid of 50 is ours to cross, not to quote
        self.assertEqual(asks["MAL-04"], (7, 3, "v07"))

    def test_near_pairs_within_gap_closest_first_and_never_one_team_with_itself(self):
        self.assertEqual([p[0] for p in an.near_market_pairs(BOOK, NAMES)], ["MAL-04"])
        self.assertEqual(an.near_market_pairs(BOOK, {1: "t09", 2: "t09"}), [])
        self.assertEqual(an.near_market_pairs([ask("A", 10), bid("A", 6)], {}), [])  # 4 P apart > NEAR_GAP
        self.assertEqual(an.near_pairs({"A": 10, "B": 9}, {"A": 10, "B": 10}), [("A", 10, 10), ("B", 9, 10)])


class TestFeed(unittest.TestCase):
    def test_makers_come_from_the_feed(self):
        ev = [listed(ask("X", 5, maker="t15", oid=7)), listed(bid("Y", 3, maker="t06", oid=8)),
              {"type": "thread.message", "payload": {}}]
        self.assertEqual(an.offer_makers(ev), {7: "t15", 8: "t06"})

    def test_books_come_from_each_venue_and_an_unreadable_one_is_skipped(self):
        served = {"rastro": [ask("A", 5)], "v07": [bid("A", 4)], "v20": [ask("B", 9)]}

        def get(url):
            v = url.rsplit("/", 2)[-2]
            if v == "v99":
                raise OSError("down")
            return {"offers": served[v]}
        books = an.market_books(get, ["v07", "v99", "v20"])
        self.assertEqual(sorted(books), ["rastro", "v07", "v20"])
        self.assertEqual(books["v07"][0]["venue"], "v07")

    def test_describe_names_the_team_and_skips_ours_and_directed(self):
        self.assertEqual(an.describe(ask("LAT-07", 26, oid=9), {9: "t15"}), "t15 sells LAT-07 for 26 P (offer 9)")
        self.assertEqual(an.describe(bid("LAT-06", 14, maker="t06", oid=5)), "t06 buys LAT-06 for 14 P (offer 5)")
        self.assertEqual(an.describe(swap("SAL-03", "LAV-07", maker="t13", oid=4)),
                         "t13 swaps SAL-03 for any LAV-07 (offer 4), taken by accepting it")
        self.assertEqual(an.describe(ask("A", 5, maker="m8812", oid=3)), "a team sells A for 5 P (offer 3)")
        self.assertIsNone(an.describe(ask("A", 5, maker="t03")))
        self.assertIsNone(an.describe(ask("A", 5, maker="t13", to="t16")))


class TestText(unittest.TestCase):
    V20 = [ask("LAT-07", 26, venue="v20", oid=21), bid("MAL-08", 9, venue="v20", maker="t06", oid=22)]

    def test_book_variant_lists_v20_with_teams_and_the_order_that_takes_it(self):
        t = an.build_text([], 0, exclude=(), venue_offers=self.V20, names={21: "t15"})
        self.assertTrue(t.startswith("Live on La Celestina (v20) now: t15 sells LAT-07 for 26 P (offer 21); "
                                     "t06 buys MAL-08 for 9 P (offer 22)."))
        self.assertIn('{"venue": "v20", "give": {"cash": 26}, "want": {"cards": ["LAT-07"]}}', t)
        self.assertIn("POST /api/offers/21/accept", t)
        self.assertNotIn("http", t)                             # no web link: agents read the feed
        self.assertNotIn("Open bids on El Rastro", t)           # never send sellers to El Rastro

    def test_a_swap_is_never_promised_to_the_broker(self):
        t = an.build_text([], 0, venue_offers=[swap("LAT-07", "LAT-01", venue="v20", maker="t15", oid=31)])
        self.assertIn("t15 swaps LAT-07 for any LAT-01 (offer 31), taken by accepting it", t)
        self.assertIn("POST /api/offers/31/accept", t)
        self.assertNotIn("broker crosses", t)

    def test_pairs_variant_names_both_sides_and_falls_back_to_the_book(self):
        t = an.build_text(BOOK, 1, names=NAMES)
        self.assertTrue(t.startswith("Buyer and seller a few P apart"))
        self.assertIn("MAL-04: t09 asks 8 P on El Rastro (offer 1), t16 bids 7 P on El Rastro (offer 2)", t)
        none = [ask("LAT-06", 30), bid("LAT-06", 6)]
        self.assertEqual(an.build_text(none, 1, venue_offers=self.V20), an.build_text(none, 0, venue_offers=self.V20))

    def test_excluded_cards_never_appear_in_any_variant(self):
        book = BOOK + [ask("LAV-10", 70), bid("LAV-10", 69), ask("LAT-09", 60), bid("LAT-09", 60)]
        v20 = [ask("LAV-09", 100, venue="v20"), bid("LAT-09", 40, venue="v20")]
        for v in range(3):
            t = an.build_text(book, v, venue_offers=v20)       # default: the cards we lack
            for ref in ("LAV-09", "LAV-10", "LAT-09", "SAL-09"):
                self.assertNotIn(ref, t)
            self.assertNotIn("LAV-04", an.build_text([bid("LAV-04", 50), ask("LAV-04", 50)], v, exclude=("LAV-04",)))
        self.assertTrue({"LAV-09", "LAV-10", "LAT-09"} <= set(an.MISSING))

    def test_missing_card_variant_is_bilingual_and_carries_the_book(self):
        t = an.build_text([], 2, venue_offers=self.V20, names={21: "t15"})
        self.assertIn("Missing one card", t)
        self.assertIn("¿Te falta una carta?", t)
        self.assertIn("t15 sells LAT-07", t)

    def test_variants_rotate_and_fit_the_limit_and_link_is_optional(self):
        self.assertEqual(an.build_text(BOOK, 3), an.build_text(BOOK, 0))
        big = [bid(f"LAV-{i:02d}", 50 + i) for i in range(400)] + [ask(f"LAV-{i:02d}", 50 + i) for i in range(400)]
        v20 = [ask(f"MAL-{i:02d}", 9, venue="v20") for i in range(50)]
        for v in range(3):
            self.assertLessEqual(len(an.build_text(big, v, venue_offers=v20)), an.MAX_CHARS)
            self.assertNotIn("http", an.build_text(BOOK, v))
            self.assertEqual(len(an.build_text(BOOK, v, link="x" * 2000)), an.MAX_CHARS)
        self.assertIn("Selling a spare", an.build_text([], 0))  # nothing concrete: the plain pitch


class TestCli(unittest.TestCase):
    def test_run_without_yes_refuses_before_any_key_or_network(self):
        with self.assertRaises(SystemExit) as cm:
            an.main(["run"])
        self.assertEqual(cm.exception.code, 2)          # argparse refused it; no key was read

    def test_variant_state_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            self.assertEqual(an.next_variant(p), 0)
            an.save_variant(2, p)
            self.assertEqual(an.next_variant(p), 2)


if __name__ == "__main__":
    unittest.main()
