import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))

from bazaar_sdk import BazaarError  # noqa: E402
import dealer_client  # noqa: E402


class RetryRateLimited(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(dealer_client.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def test_rate_limited_then_ok_returns_the_result(self):
        calls = iter([BazaarError("rate_limited"), BazaarError("rate_limited"), {"id": 7}])

        def call():
            r = next(calls)
            if isinstance(r, Exception):
                raise r
            return r
        self.assertEqual(dealer_client.retry_rate_limited(call), {"id": 7})
        self.assertEqual(self.sleep.call_count, 2)

    def test_other_refusals_are_raised_at_once(self):
        def call():
            raise BazaarError("cooloff")
        with self.assertRaises(BazaarError) as cm:
            dealer_client.retry_rate_limited(call)
        self.assertEqual(cm.exception.code, "cooloff")
        self.sleep.assert_not_called()

    def test_gives_up_after_the_last_try(self):
        n = []

        def call():
            n.append(1)
            raise BazaarError("rate_limited")
        with self.assertRaises(BazaarError):
            dealer_client.retry_rate_limited(call, tries=3)
        self.assertEqual(len(n), 3)


if __name__ == "__main__":
    unittest.main()
