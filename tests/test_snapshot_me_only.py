"""tools/snapshot.py --me-only: one keyed read, only logs/state/me.json written. Run: python3 -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as um
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
import snapshot  # noqa: E402


class FakeBazaar:
    calls = []

    def __init__(self, url, key):
        pass

    def me(self):
        FakeBazaar.calls.append("me")
        return {"id": "t03", "tick": 1500, "assets": [{"id": 31, "kind": "card", "ref": "LAT-01"}]}

    def __getattr__(self, name):   # any other read is a failure of --me-only
        def call(*a, **k):
            FakeBazaar.calls.append(name)
            return {}
        return call


class MeOnly(unittest.TestCase):
    def test_me_only_reads_once_and_writes_only_the_account(self):
        FakeBazaar.calls = []
        with tempfile.TemporaryDirectory() as d, um.patch.object(snapshot, "Bazaar", FakeBazaar), \
                um.patch.object(snapshot, "LOGS", Path(d)), um.patch.object(snapshot, "load_env", lambda: None), \
                um.patch.dict(os.environ, {"BAZAAR_KEY": "test-not-a-key"}), um.patch("builtins.print"):
            snapshot.main(["--me-only"])
            files = sorted(str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file())
            me = json.loads((Path(d) / "state" / "me.json").read_text())
        self.assertEqual(FakeBazaar.calls, ["me"])
        self.assertEqual(files, ["state/me.json"])
        self.assertEqual(me["tick"], 1500)


if __name__ == "__main__":
    unittest.main()
