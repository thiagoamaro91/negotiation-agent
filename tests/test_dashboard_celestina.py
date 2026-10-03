"""The La Celestina panel's pure parts in tools/dashboard.py: our venue, its offers, the broker heartbeat and log."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import dashboard as d  # noqa: E402

VENUES = {"venues": [
    {"id": "rastro", "name": "El Rastro", "owner": None, "status": "open", "fee_bps": 500, "fee_per_card": 1},
    {"id": "v07", "name": "Other market", "owner": "t07", "status": "open", "fee_bps": 100},
    {"id": "v12", "name": "Old Celestina", "owner": "t03", "status": "closed", "fee_bps": 0},
    {"id": "v20", "name": "La Celestina · finds your missing card", "owner": "t03", "status": "open",
     "fee_bps": 0, "fee_per_card": 0, "rules": {"mechanism": "board"}},
]}

SELL = {"id": 501, "maker": "t07", "give": {"assets": [{"kind": "card", "ref": "LAV-09", "id": 9}], "cash": 0},
        "want": {"cash": 40, "types": []}}
BUY = {"id": 502, "maker": "t11", "give": {"assets": [], "cash": 46}, "want": {"cash": 0, "types": ["card:LAV-09"]}}
BENCH_S = {"id": "b3-1", "give": {"cash": 0}, "want": {"cash": 30}}
BENCH_B = {"id": "b3-2", "give": {"cash": 36}, "want": {"cash": 0}}


def row(event, **kw):
    return json.dumps({"ts": "2026-10-03T11:53:07", "run": "r1", "agent": "broker", "event": event, **kw})


class VenueTest(unittest.TestCase):
    def test_picks_our_open_venue(self):
        v = d.find_our_venue(VENUES, "t03")
        self.assertEqual(v["id"], "v20")
        self.assertEqual(v["name"], "La Celestina · finds your missing card")
        self.assertEqual((v["status"], v["fee_bps"], v["mechanism"], v["listed"]), ("open", 0, "board", True))

    def test_list_and_owner_object(self):
        v = d.find_our_venue([{"id": "v21", "owner": {"id": "t03"}, "status": "open"}], "t03")
        self.assertEqual(v["id"], "v21")

    def test_closed_only_still_shown(self):
        v = d.find_our_venue([{"id": "v12", "owner": "t03", "status": "closed"}], "t03")
        self.assertEqual((v["id"], v["status"]), ("v12", "closed"))

    def test_fallback_when_not_listed(self):
        for venues in ({"venues": []}, [], None, {"venues": [{"id": "v07", "owner": "t07"}]}, ["junk"]):
            v = d.find_our_venue(venues, "t03")
            self.assertEqual((v["id"], v["listed"]), ("v20", False))


class OffersTest(unittest.TestCase):
    def test_rows(self):
        out = d.offer_rows({"offers": [SELL, BUY, "junk"]})
        self.assertEqual(out["count"], 2)
        s, b = out["rows"]
        self.assertEqual((s["maker"], s["gives"], s["wants"], s["price"]), ("t07", "LAV-09", "40 P", 40))
        self.assertEqual((b["maker"], b["gives"], b["wants"], b["price"]), ("t11", "46 P", "LAV-09", 46))

    def test_bare_list_empty_and_limit(self):
        self.assertEqual(d.offer_rows([]), {"count": 0, "rows": []})
        self.assertEqual(d.offer_rows({"offers": None}), {"count": 0, "rows": []})
        out = d.offer_rows([dict(SELL, id=i) for i in range(30)], limit=5)
        self.assertEqual((out["count"], len(out["rows"])), (30, 5))

    def test_malformed_sides(self):
        r = d.offer_rows([{"id": 1, "give": "x", "want": None}])["rows"][0]
        self.assertEqual((r["gives"], r["wants"], r["price"]), ("-", "-", None))


class HeartbeatTest(unittest.TestCase):
    HB = {"agent": "broker", "mode": "run", "policy": "stall", "pid": 4242, "tick": 1311, "what": "same_book",
          "time": "2026-10-03T11:02:10", "epoch": 1000.0, "reads": 77, "read_errors_in_a_row": 0,
          "last_decision": {"tick": 1310, "matches": [["b3-1", "b3-2", 33]]}, "sent": 1, "accepted": 1,
          "refused": 0, "dropped": 0}

    def test_alive(self):
        v = d.heartbeat_view(self.HB, now=1012.0)
        self.assertEqual((v["state"], v["age"], v["tick"], v["policy"]), ("alive", 12.0, 1311, "stall"))
        self.assertEqual((v["read_errors_in_a_row"], v["decision_tick"], v["decision_matches"]), (0, 1310, 1))
        self.assertNotIn("pid", v)

    def test_stale_after_90s(self):
        self.assertEqual(d.heartbeat_view(self.HB, now=1090.0)["state"], "alive")
        self.assertEqual(d.heartbeat_view(self.HB, now=1091.0)["state"], "stale")

    def test_missing_and_no_epoch(self):
        self.assertEqual(d.heartbeat_view(None, now=1.0), {"state": "missing"})
        self.assertEqual(d.heartbeat_view({"tick": 5}, now=1.0)["state"], "stale")


class LogTest(unittest.TestCase):
    LINES = [
        row("run_start", operator="thiago", mode="run", policy="stall"),
        row("book", tick=1400, book={"offers": [SELL, BUY], "bench_offers": [BENCH_S, BENCH_B]}),
        row("WOULD", tick=1400, sell=501, buy=502, price=43),
        row("matched", tick=1400, sell=501, buy=502, price=43, result={"id": 88, "status": "pending"}),
        "{not json",
        row("refused", tick=1401, sell="b3-1", buy="b3-2", price=33, code="taken", msg="", status=409),
        row("matched", tick=1401, sell="b3-1", buy="b3-2", price=33, result={}),
        row("read_error", error="BazaarError: network", in_a_row=1),
        row("dropped", tick=1401, match=["b3-1", "b9-2", 30], why="different_runs"),
    ]

    def test_matches_resolved_from_the_book(self):
        s = d.summarize_broker_log(self.LINES)
        self.assertEqual(s["count"], 2)
        bench, public = s["matches"]  # newest first
        self.assertEqual((public["tick"], public["card"], public["price"]), (1400, "LAV-09", 43))
        self.assertEqual((public["seller"], public["buyer"], public["status"]), ("t07", "t11", "pending"))
        self.assertEqual((bench["card"], bench["bench"], bench["bench_run"]), (None, True, "b3"))
        self.assertEqual((bench["seller"], bench["buyer"]), ("bench", "bench"))
        self.assertEqual((s["would"], s["refused"], s["dropped"], s["errors"]), (1, 1, 1, 1))
        self.assertEqual(s["last_error"]["event"], "read_error")
        self.assertEqual(s["run_start"]["policy"], "stall")
        self.assertNotIn("offers", s)

    def test_unknown_offers_and_keep(self):
        lines = [row("matched", tick=t, sell=1000 + t, buy=2000 + t, price=10) for t in range(25)]
        s = d.summarize_broker_log(lines, keep=10)
        self.assertEqual((s["count"], len(s["matches"])), (25, 10))
        self.assertEqual(s["matches"][0]["tick"], 24)
        self.assertEqual((s["matches"][0]["card"], s["matches"][0]["seller"]), (None, None))

    def test_empty(self):
        s = d.summarize_broker_log([])
        self.assertEqual((s["count"], s["matches"], s["errors"]), (0, [], 0))


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tail_reads_whole_lines_only(self):
        p = self.root / "b.jsonl"
        lines = LogTest.LINES
        p.write_text("\n".join(lines[:4]) + "\n" + lines[6][:20])  # last line still being written
        tail = d.BrokerLogTail()
        self.assertEqual(tail.read(p)["count"], 1)
        with p.open("a") as f:
            f.write(lines[6][20:] + "\n")
        out = tail.read(p)
        self.assertEqual((out["exists"], out["count"]), (True, 2))
        self.assertEqual(tail.read(p)["count"], 2)  # nothing new: nothing counted twice
        p.write_text(lines[3] + "\n")  # the file shrank (a new file under the same name): start over
        self.assertEqual(tail.read(p)["count"], 1)
        self.assertFalse(tail.read(self.root / "missing.jsonl")["exists"])

    def test_snapshot_reads_the_broker_root(self):
        now = time.time()
        (self.root / "logs" / "state").mkdir(parents=True)
        (self.root / "logs" / "broker").mkdir(parents=True)
        (self.root / "logs" / "state" / "desk-broker.json").write_text(json.dumps(dict(HeartbeatTest.HB, epoch=now - 5)))
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        (self.root / "logs" / "broker" / f"{day}.jsonl").write_text("\n".join(LogTest.LINES) + "\n")
        cel = d.Celestina("http://127.0.0.1:9", self.root)
        cel.venue_at = now  # skip the network: the venue was "just read"
        snap = cel.snapshot(now)
        self.assertEqual(snap["venue"]["id"], "v20")
        self.assertEqual((snap["broker"]["state"], snap["broker"]["tick"]), ("alive", 1311))
        self.assertEqual((snap["log"]["file"], snap["log"]["count"]), (f"{day}.jsonl", 2))
        json.dumps(snap)  # the page gets it as JSON

    def test_snapshot_empty_root(self):
        cel = d.Celestina("http://127.0.0.1:9", self.root)
        cel.venue_at = time.time()
        snap = cel.snapshot()
        self.assertEqual(snap["broker"], {"state": "missing"})
        self.assertEqual((snap["log"]["exists"], snap["log"]["count"], snap["offers"]), (False, 0, None))


if __name__ == "__main__":
    unittest.main()
