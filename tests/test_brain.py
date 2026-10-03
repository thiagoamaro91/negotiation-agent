"""Safety rules of the account relay and the brain's intake. Run: python3 -m unittest discover tests"""
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
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


class DeskHeartbeat(unittest.TestCase):
    GOOD = {"name": "market-desk", "mode": "shadow", "tick": 241, "last_decision": "list LAV-08 at 26",
            "reason": "spare worth 10 to us"}

    def test_accepts_a_heartbeat_and_keeps_only_its_fields(self):
        out = brain.valid_desk({**self.GOOD, "extra": "ignored"})
        self.assertEqual(out, self.GOOD)

    def test_drops_any_field_named_like_a_key_and_redacts_key_shapes(self):
        out = brain.valid_desk({**self.GOOD, "api_key": "tk-1234-abcd-5678", "Broker_Key": "bk-x",
                                "reason": "used tk-1234-abcd-5678 to read"})
        self.assertNotIn("1234-abcd", str(out))
        self.assertEqual(out["reason"], "used [redacted] to read")

    def test_rejects_anything_else(self):
        for bad in ([], "x", {**self.GOOD, "mode": "auto"}, {**self.GOOD, "name": "<script>"}, {**self.GOOD, "name": ""},
                    {**self.GOOD, "name": "x" * 41}, {**self.GOOD, "tick": True}, {**self.GOOD, "tick": -1},
                    {**self.GOOD, "tick": "241"}, {**self.GOOD, "reason": {"nested": 1}}, {k: v for k, v in self.GOOD.items() if k != "name"}):
            self.assertIsNone(brain.valid_desk(bad), bad)

    def test_text_is_cut_to_its_limit(self):
        out = brain.valid_desk({**self.GOOD, "reason": "r" * 5000, "last_decision": "d" * 5000})
        self.assertEqual(len(out["reason"]), brain.DESK_TEXT["reason"])
        self.assertEqual(len(out["last_decision"]), brain.DESK_TEXT["last_decision"])


class DeskStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (brain.OUT, brain.DESK_FILE, dict(brain.DESKS))
        brain.OUT = Path(self.tmp.name)
        brain.DESK_FILE = brain.OUT / "desks.json"
        brain.DESKS.clear()

    def tearDown(self):
        brain.OUT, brain.DESK_FILE = self.saved[0], self.saved[1]
        brain.DESKS.clear()
        brain.DESKS.update(self.saved[2])
        self.tmp.cleanup()

    def test_age_newest_first_and_the_oldest_is_forgotten(self):
        for i in range(brain.DESK_MAX + 2):
            brain.record_desk({**DeskHeartbeat.GOOD, "name": f"desk{i}"}, now=1000.0 + i)
        rows = brain.desk_rows(now=1000.0 + brain.DESK_MAX + 1 + 5)
        self.assertEqual(len(rows), brain.DESK_MAX)
        self.assertEqual(rows[0]["name"], f"desk{brain.DESK_MAX + 1}")
        self.assertEqual(rows[0]["age_s"], 5.0)
        self.assertNotIn("desk0", [r["name"] for r in rows])

    def test_survives_a_restart(self):
        brain.record_desk(DeskHeartbeat.GOOD, now=1000.0)
        brain.DESKS.clear()
        brain.load_desks()
        self.assertEqual(brain.desk_rows(now=1010.0)[0]["last_decision"], "list LAV-08 at 26")


class SnapshotTail(unittest.TestCase):
    def test_reads_only_new_whole_lines_and_keeps_the_latest_of_each(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.jsonl"
            snaps = brain.Snapshots(path)
            snaps.update()  # no file yet
            with open(path, "w") as f:
                f.write(json.dumps({"what": "leaderboard", "tick": 1, "body": {"snapshot_tick": 1}}) + "\n")
                f.write(json.dumps({"what": "book", "venue": "v01", "tick": 1, "body": {"offers": []}}) + "\n")
                f.write('{"what": "leaderboard", "tick": 2, "bo')  # the recorder is mid-write
            snaps.update()
            self.assertEqual(snaps.body("leaderboard"), {"snapshot_tick": 1})
            with open(path, "a") as f:
                f.write('dy": {"snapshot_tick": 2}}\n')
                f.write(json.dumps({"what": "book", "venue": "v01", "tick": 2, "body": {"offers": [{"status": "open"}]}}) + "\n")
            snaps.update()
            self.assertEqual(snaps.body("leaderboard"), {"snapshot_tick": 2})
            self.assertEqual(snaps.books["v01"]["tick"], 2)
            path.write_text(json.dumps({"what": "venues", "tick": 3, "body": {"venues": []}}) + "\n")  # rotated
            snaps.update()
            self.assertEqual(snaps.body("leaderboard"), {})
            self.assertEqual(snaps.body("venues"), {"venues": []})

    def test_venues_panel_counts_open_offers_and_trades(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.jsonl"
            rows = [{"what": "venues", "tick": 5, "body": {"venues": [
                        {"venue": "rastro", "status": "open", "fee_bps": 500, "fee_per_card": 1, "rules": {}, "house": True,
                         "trades": 45},
                        {"venue": "v02", "status": "open", "fee_bps": 0, "rules": {"mechanism": "board"}, "trades": 0}]}},
                    {"what": "rastro", "tick": 5, "body": {"offers": [{"status": "open"}, {"status": "open"}]}},
                    {"what": "book", "venue": "v02", "tick": 5, "body": {"offers": [{"status": "open"}, {"status": "filled"}]}}]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
            events = [{"type": "settlement", "tick": 4, "payload": {"venue": "v02", "items": []}},
                      {"type": "settlement", "tick": 4, "payload": {"venue": None, "persona": "abuela", "items": []}}]
            panel = {v["venue"]: v for v in brain.venues_panel(brain.Snapshots(path).update(), events)}
            self.assertEqual((panel["rastro"]["open_offers"], panel["rastro"]["mechanism"], panel["rastro"]["trades"]), (2, "house", 45))
            self.assertEqual((panel["v02"]["open_offers"], panel["v02"]["mechanism"], panel["v02"]["feed_trades"]), (1, "board", 1))


class Endpoints(unittest.TestCase):
    """The real HTTP server on a free local port: the write token gates both intakes, the read token every read."""
    READ, WRITE = "read-token-test", "write-token-test"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (brain.OUT, brain.DESK_FILE, brain.vi.ME_LIVE, dict(brain.DESKS))
        brain.OUT = Path(cls.tmp.name)
        brain.DESK_FILE = brain.OUT / "desks.json"
        brain.vi.ME_LIVE = brain.OUT / "me_live.json"
        brain.DESKS.clear()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        threading.Thread(target=brain.serve, args=(cls.port, "127.0.0.1", cls.READ, cls.WRITE), daemon=True).start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        brain.OUT, brain.DESK_FILE, brain.vi.ME_LIVE = cls.saved[0], cls.saved[1], cls.saved[2]
        brain.DESKS.clear()
        brain.DESKS.update(cls.saved[3])
        cls.tmp.cleanup()

    def call(self, path, body=None, token=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST" if data else "GET",
                                     headers={"X-Brain-Write": token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_a_desk_heartbeat_needs_the_write_token(self):
        self.assertEqual(self.call("/ingest/desk", DeskHeartbeat.GOOD)[0], 403)
        self.assertEqual(self.call("/ingest/desk", DeskHeartbeat.GOOD, token=self.READ)[0], 403)
        self.assertEqual(self.call("/ingest/desk", DeskHeartbeat.GOOD, token=self.WRITE)[0], 200)

    def test_a_bad_or_oversized_heartbeat_is_refused(self):
        self.assertEqual(self.call("/ingest/desk", {"name": "x", "mode": "auto"}, token=self.WRITE)[0], 400)
        self.assertEqual(self.call("/ingest/desk", raw=b"{not json", token=self.WRITE)[0], 400)
        big = {**DeskHeartbeat.GOOD, "reason": "r" * brain.DESK_MAX_BYTES}
        self.assertEqual(self.call("/ingest/desk", big, token=self.WRITE)[0], 413)

    def test_the_page_data_shows_desks_only_with_the_read_token(self):
        self.call("/ingest/desk", {**DeskHeartbeat.GOOD, "name": "duel-lab", "mode": "live"}, token=self.WRITE)
        self.assertEqual(self.call("/data")[0], 403)
        self.assertEqual(self.call("/data?t=wrong")[0], 403)
        code, body = self.call(f"/data?t={self.READ}")
        self.assertEqual(code, 200)
        desks = {d["name"]: d for d in json.loads(body)["desks"]}
        self.assertEqual(desks["duel-lab"]["mode"], "live")

    def test_the_account_intake_still_works_and_other_paths_are_refused(self):
        self.assertEqual(self.call("/ingest/me", Intake.GOOD, token=self.WRITE)[0], 200)
        self.assertEqual(self.call("/ingest/other", Intake.GOOD, token=self.WRITE)[0], 403)


if __name__ == "__main__":
    unittest.main()
