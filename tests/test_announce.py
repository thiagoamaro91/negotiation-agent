"""tools/announce.py: El Rastro's book read right, the message variants, and that nothing posts without --yes.
Offline: no key, no network. Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import announce as an  # noqa: E402


def ask(ref, cash, status="open"):
    return {"status": status, "give": {"cash": 0, "assets": [{"kind": "card", "ref": ref}], "types": []},
            "want": {"cash": cash, "assets": [], "types": []}}


def bid(ref, cash, status="open"):
    return {"status": status, "give": {"cash": cash, "assets": [], "types": []},
            "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


def swap(give_ref, want_ref):
    return {"status": "open", "give": {"cash": 0, "assets": [{"kind": "card", "ref": give_ref}], "types": []},
            "want": {"cash": 0, "assets": [], "types": [f"card:{want_ref}"]}}


BOOK = [ask("MAL-04", 8), ask("MAL-04", 9), bid("MAL-04", 7), bid("MAL-04", 6),
        ask("LAV-09", 120), bid("LAV-09", 99), bid("SAL-09", 68), bid("RET-01", 2),
        swap("LAT-02", "LAV-07"), ask("SAL-03", 5, status="cancelled")]


class TestBook(unittest.TestCase):
    def test_best_bid_and_ask_per_card_swaps_and_closed_skipped(self):
        bids, asks = an.rastro_book(BOOK)
        self.assertEqual(bids, {"MAL-04": 7, "LAV-09": 99, "SAL-09": 68, "RET-01": 2})
        self.assertEqual(asks, {"MAL-04": 8, "LAV-09": 120})

    def test_near_pairs_within_gap_closest_first(self):
        bids, asks = an.rastro_book(BOOK)
        self.assertEqual(an.near_pairs(bids, asks), [("MAL-04", 7, 8)])
        self.assertEqual(an.near_pairs(bids, asks, gap=0), [])
        self.assertEqual(an.near_pairs({"A": 10, "B": 9}, {"A": 10, "B": 10}), [("A", 10, 10), ("B", 9, 10)])

    def test_top_bids_drop_noise_and_sort(self):
        bids, _ = an.rastro_book(BOOK)
        self.assertEqual(an.top_bids(bids), [("LAV-09", 99), ("SAL-09", 68), ("MAL-04", 7)])


class TestText(unittest.TestCase):
    def test_radar_variant_names_bids_and_venue(self):
        t = an.build_text(BOOK, 0)
        self.assertIn("LAV-09 99 P, SAL-09 68 P, MAL-04 7 P", t)
        self.assertIn('venue "v20"', t)
        self.assertIn(an.LINK, t)

    def test_pairs_variant_uses_the_crossing_pair_and_falls_back_without_one(self):
        t = an.build_text(BOOK, 1)
        self.assertIn("MAL-04: a seller asks 8 P and a buyer bids 7 P", t)
        no_pairs = [ask("LAV-09", 120), bid("LAV-09", 99)]
        self.assertEqual(an.build_text(no_pairs, 1), an.build_text(no_pairs, 0))

    def test_missing_card_variant_is_bilingual(self):
        t = an.build_text([], 2)
        self.assertIn("Missing one card", t)
        self.assertIn("¿Te falta una carta?", t)

    def test_variants_rotate_and_fit_the_limit_and_link_is_optional(self):
        self.assertEqual(an.build_text(BOOK, 3), an.build_text(BOOK, 0))
        big = [bid(f"LAV-{i:02d}", 50 + i) for i in range(400)]
        for v in range(3):
            self.assertLessEqual(len(an.build_text(big, v)), an.MAX_CHARS)
            self.assertNotIn("http", an.build_text(BOOK, v, link=None))
            self.assertEqual(len(an.build_text(BOOK, v, link="x" * 2000)), an.MAX_CHARS)


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
