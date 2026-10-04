import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "kit"))

import snapshot  # noqa: E402

ME = {"tick": 1700, "cash": 239, "level": 5, "unlocked": ["abuela"], "collection_value": 1600.0,
      "album": {"filled": 37}, "assets": [{"kind": "card", "ref": "SAL-10"}],
      "score": {"score": 27.71, "negotiating": 22.6, "market": 5.1, "rank": 5}}


class MeOnlyScore(unittest.TestCase):
    def run_main(self, argv):
        tmp = Path(tempfile.mkdtemp())
        fake = mock.Mock()
        fake.me.return_value = ME
        with mock.patch.object(snapshot, "LOGS", tmp), mock.patch.object(snapshot, "load_env"), \
                mock.patch.object(snapshot, "Bazaar", return_value=fake), \
                mock.patch.object(snapshot, "save_me"), mock.patch.dict("os.environ", {"BAZAAR_KEY": "x"}):
            snapshot.main(argv)
        return tmp, fake

    def test_me_only_with_score_appends_one_row_and_makes_one_request(self):
        tmp, fake = self.run_main(["--me-only", "--score"])
        rows = [json.loads(x) for x in (tmp / "score.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tick"], 1700)
        self.assertEqual(rows[0]["score"]["score"], 27.71)
        self.assertIsNone(rows[0]["threads"])
        fake.my_threads.assert_not_called()
        fake.duels.assert_not_called()

    def test_me_only_without_score_writes_no_row(self):
        tmp, _ = self.run_main(["--me-only"])
        self.assertFalse((tmp / "score.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
