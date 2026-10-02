"""Safety rules of the account relay and the brain's intake. Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import brain  # noqa: E402
import me_relay  # noqa: E402


class Relay(unittest.TestCase):
    def test_no_field_named_like_a_key_leaves_the_laptop(self):
        me = {"cash": 10, "starter_broker_key": "bk-secret", "venue": {"broker_key": "x", "name": "v"},
              "assets": [{"ref": "LAV-01", "apiKey": "y"}]}
        out = me_relay.scrub(me)
        self.assertNotIn("bk-secret", str(out))
        self.assertEqual(out, {"cash": 10, "venue": {"name": "v"}, "assets": [{"ref": "LAV-01"}]})


class Intake(unittest.TestCase):
    GOOD = {"affinity": {"LAV": 1.6}, "assets": [], "cash": 291, "tick": 93}

    def test_accepts_an_account(self):
        self.assertTrue(brain.valid_account(self.GOOD))

    def test_rejects_anything_else(self):
        for bad in ({}, [], {**self.GOOD, "cash": "291"}, {**self.GOOD, "cash": float("nan")},
                    {**self.GOOD, "tick": None}, {**self.GOOD, "assets": {}}):
            self.assertFalse(brain.valid_account(bad), bad)


if __name__ == "__main__":
    unittest.main()
