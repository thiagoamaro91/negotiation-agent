"""agent/chato.py bid schedule. Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
import chato  # noqa: E402


class BidSchedule(unittest.TestCase):
    def test_rare_anchor_then_steady_steps_then_small_near_his_ask(self):
        bids, ours = [], None
        for her in (97, 96, 95, 92, 88, 84, 82, 81, 81):  # an El Chato who mirrors and slows near his limit
            ours = chato.next_buy_price(ours, her, rare=True)
            bids.append(ours)
        self.assertEqual(bids[0], 58)                      # 0.6 x 97
        self.assertEqual(bids[1:5], [62, 66, 70, 74])      # +4 while the gap is wide
        self.assertEqual(bids[5:7], [76, 78])              # +2 once within 10
        self.assertEqual(bids[7:], [79, 80])               # +1 in the last 3

    def test_uncommons_keep_the_old_one_primas_steps(self):
        self.assertEqual(chato.next_buy_price(None, 33, rare=False), 13)
        self.assertEqual(chato.next_buy_price(13, 33, rare=False), 14)

    def test_rare_step_zero_restores_the_old_behaviour(self):
        saved = chato.RARE_STEP
        try:
            chato.RARE_STEP = 0
            self.assertEqual(chato.next_buy_price(None, 97, rare=True), int(97 * chato.ANCHOR_FRAC))
            self.assertEqual(chato.next_buy_price(40, 97, rare=True), 41)
        finally:
            chato.RARE_STEP = saved


if __name__ == "__main__":
    unittest.main()
