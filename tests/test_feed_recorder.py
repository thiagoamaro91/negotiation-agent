"""tools/feed_recorder.py: which venue books it reads. Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import feed_recorder as fr  # noqa: E402


class VenueBooks(unittest.TestCase):
    def test_every_open_venue_but_el_rastro(self):
        body = {"venues": [{"venue": "v01", "status": "open"}, {"venue": "v02", "status": "closed"},
                           {"venue": "rastro", "status": "open"}, {"venue": "v04", "status": "open"}]}
        self.assertEqual(fr.open_venue_ids(body), ["v01", "v04"])

    def test_ids_that_could_change_the_url_are_skipped(self):
        body = {"venues": [{"venue": "../me", "status": "open"}, {"venue": "v01?key=1", "status": "open"},
                           {"venue": "v 2", "status": "open"}, {"venue": 7, "status": "open"}, "v09",
                           {"venue": "v03", "status": "open"}]}
        self.assertEqual(fr.open_venue_ids(body), ["v03"])

    def test_anything_else_reads_as_no_venues(self):
        for body in (None, "x", {}, {"venues": None}, []):
            self.assertEqual(fr.open_venue_ids(body), [], body)

    def test_reads_are_paced(self):
        self.assertGreaterEqual(fr.MIN_GAP, 1 / 60 * 3)  # at least three times under the 60 per second keyless limit


if __name__ == "__main__":
    unittest.main()
