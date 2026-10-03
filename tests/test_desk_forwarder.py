import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import desk_forwarder as fw  # noqa: E402


class ToDesk(unittest.TestCase):
    def test_market_heartbeat(self):
        hb = {"desk": "market", "mode": "watch", "tick": 240, "last_decision": {"card": "SAL-05", "price": 9},
              "reason": "gain +2 below the +3 margin"}
        d = fw.to_desk("market", hb)
        self.assertEqual(d["mode"], "shadow")
        self.assertEqual(d["tick"], 240)
        self.assertEqual(json.loads(d["last_decision"]), {"card": "SAL-05", "price": 9})
        self.assertEqual(d["reason"], "gain +2 below the +3 margin")

    def test_broker_heartbeat_live_and_what(self):
        d = fw.to_desk("broker", {"agent": "broker", "mode": "run", "tick": 300, "what": "book", "last_decision": None})
        self.assertEqual(d["mode"], "live")
        self.assertEqual(d["reason"], "book")
        self.assertEqual(d["last_decision"], "")

    def test_bad_tick_and_long_text(self):
        d = fw.to_desk("x", {"mode": "run", "tick": True, "reason": "r" * 900})
        self.assertIsNone(d["tick"])
        self.assertEqual(len(d["reason"]), 500)
        self.assertIsNone(fw.to_desk("x", ["not", "a", "dict"]))


class Heartbeats(unittest.TestCase):
    def test_reads_desk_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "desk-market.json").write_text(json.dumps({"mode": "watch", "tick": 1}))
            (state / "desk-broken.json").write_text("{not json")
            (state / "lease.json").write_text("{}")
            names = [n for n, _, _ in fw.heartbeats(state)]
            self.assertEqual(names, ["market"])

    def test_unchanged_file_is_not_sent_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            f = state / "desk-market.json"
            f.write_text(json.dumps({"mode": "watch", "tick": 1}))
            sent, posted = {}, []
            self.assertEqual(fw.forward_once(state, sent, posted.append), 1)
            self.assertEqual(fw.forward_once(state, sent, posted.append), 0)
            f.write_text(json.dumps({"mode": "watch", "tick": 2}))
            os.utime(f, (time.time() + 5, time.time() + 5))
            self.assertEqual(fw.forward_once(state, sent, posted.append), 1)
            self.assertEqual([d["tick"] for d in posted], [1, 2])

    def test_failed_send_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "desk-broker.json").write_text(json.dumps({"mode": "run", "tick": 5}))
            sent, calls = {}, []

            def flaky(desk):
                calls.append(desk)
                if len(calls) == 1:
                    raise OSError("brain restarting")
            self.assertEqual(fw.forward_once(state, sent, flaky), 0)
            self.assertEqual(fw.forward_once(state, sent, flaky), 1)
            self.assertEqual(len(calls), 2)


class BrainEnv(unittest.TestCase):
    def test_reads_only_brain_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "brain.env"
            env.write_text("BRAIN_TOKEN=read\nBRAIN_WRITE_TOKEN=write\nBAZAAR_KEY=tk-should-never-load\n")
            for k in ("BRAIN_TOKEN", "BRAIN_WRITE_TOKEN", "BAZAAR_KEY"):
                os.environ.pop(k, None)
            try:
                fw.load_brain_env(env)
                self.assertEqual(os.environ.get("BRAIN_WRITE_TOKEN"), "write")
                self.assertIsNone(os.environ.get("BAZAAR_KEY"))
                self.assertIsNone(os.environ.get("BRAIN_TOKEN"))
            finally:
                os.environ.pop("BRAIN_WRITE_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
