"""tools/ledger.py against the committed feed (ticks 0-48). Run: python3 -m unittest discover tests"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["BAZAAR_FEED"] = str(ROOT / "logs" / "feed")  # the committed slice, never the live recorder's files
sys.path.insert(0, str(ROOT / "tools"))
import ledger  # noqa: E402
import value_inference as vi  # noqa: E402


class Ledger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = [e for e in vi.rows("feed.jsonl") if e["tick"] <= 48]
        cls.led = ledger.build(cls.events)

    def test_our_cash_matches_the_dealer_deals_we_made(self):
        # start 400, LAV-06 at 17 (tick 28), LAV-07 at 22 (tick 46): what /api/me showed
        self.assertEqual(self.led["t03"]["cash"], 400 - 17 - 22)

    def test_every_team_is_present_and_starts_at_400(self):
        self.assertEqual(len(self.led), 18)
        self.assertEqual(ledger.build(self.events, upto=-1)["t05"]["cash"], 400)

    def test_cash_is_conserved_in_a_team_trade_except_the_fee(self):
        # t06 sold LAV-02 to t10 for 12 P at tick 40 with a 2 P fee
        t10 = [m for m in self.led["t10"]["moves"] if "LAV-02" in m["what"]]
        t06 = [m for m in self.led["t06"]["moves"] if "LAV-02" in m["what"]]
        self.assertEqual(sum(m["delta"] for m in t10 + t06), -2)


if __name__ == "__main__":
    unittest.main()
