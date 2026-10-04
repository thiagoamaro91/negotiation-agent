"""The 14:50 pitch numbers (tools/pitch_numbers.py). Run: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pitch_numbers as pn  # noqa: E402


def settle(eid, parties, venue="v20", price=30, ref="SAL-10"):
    return {"id": eid, "tick": eid, "type": "settlement",
            "payload": {"kind": "trade", "parties": parties, "venue": venue, "price": price, "fee": 0,
                        "items": [{"kind": "card", "ref": ref, "frm": parties[0], "to": parties[1]}]}}


def listed(eid, maker, venue="v20"):
    return {"id": eid, "tick": eid, "type": "offer.listed", "actor": maker,
            "payload": {"venue": venue, "offer": {"id": 1000 + eid, "maker": maker, "venue": venue}}}


BOARD_ONE = {"trades": 1, "pairs": 1}


BOARD_ONE = {"trades": 1, "pairs": 1}
BOARD_ZERO = {"trades": 0, "pairs": 0}


class VersionFact(unittest.TestCase):
    def test_a_trade_between_two_other_teams_confirmed_by_the_leaderboard_is_version_a(self):
        trades = pn.others_trades([settle(1, ["t05", "t07"])])
        self.assertEqual(pn.version(trades, BOARD_ONE)[0], "A")
        self.assertEqual(trades[0]["cards"], ["SAL-10"])

    def test_feed_trade_the_leaderboard_denies_is_unconfirmed_never_plain_b(self):
        self.assertEqual(pn.version(pn.others_trades([settle(1, ["t05", "t07"])]), BOARD_ZERO)[0], "B-UNCONFIRMED")

    def test_feed_trade_without_a_leaderboard_read_is_unconfirmed(self):
        self.assertEqual(pn.version(pn.others_trades([settle(1, ["t05", "t07"])]), None)[0], "B-UNCONFIRMED")

    def test_leaderboard_trade_the_feed_lacks_is_unconfirmed(self):
        self.assertEqual(pn.version([], BOARD_ONE)[0], "B-UNCONFIRMED")

    def test_nothing_in_feed_or_leaderboard_is_b(self):
        self.assertEqual(pn.version([], BOARD_ZERO)[0], "B")
        self.assertEqual(pn.version([], None)[0], "B")

    def test_a_trade_we_were_part_of_is_not_the_network_working(self):
        trades = pn.others_trades([settle(1, ["t03", "t07"]), settle(2, ["t05", "t03"])])
        self.assertEqual(trades, [])

    def test_one_team_on_both_sides_is_not_two_teams(self):
        self.assertEqual(pn.others_trades([settle(1, ["t05", "t05"])]), [])

    def test_market_test_bench_and_dealer_parties_do_not_count(self):
        self.assertEqual(pn.others_trades([settle(1, ["bench", "t07"]), settle(2, ["pilar", "t05"])]), [])

    def test_other_venues_do_not_count(self):
        self.assertEqual(pn.others_trades([settle(1, ["t05", "t07"], venue="v01"),
                                           settle(2, ["t05", "t07"], venue=None)]), [])


class Deadline(unittest.TestCase):
    def test_a_slow_figure_is_unavailable_and_does_not_hold_the_rest(self):
        import time
        t0 = time.monotonic()
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = pn.gather({"fast": lambda t: 7, "slow": lambda t: time.sleep(3) or 9, "boom": lambda t: 1 / 0}, 0.3)
        self.assertEqual(err.getvalue(), "")  # no traceback reaches the screen
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(got, {"fast": 7, "slow": None, "boom": None})

    def test_without_a_deadline_every_figure_is_waited_for(self):
        self.assertEqual(pn.gather({"a": lambda t: 1, "b": lambda t: 2}, None), {"a": 1, "b": 2})


class Makers(unittest.TestCase):
    def test_counts_other_teams_on_v20_only(self):
        c = pn.venue_makers([listed(1, "t15"), listed(2, "t15"), listed(3, "t13"), listed(4, "t03"),
                             listed(5, "bench"), listed(6, "t09", venue="v01")])
        self.assertEqual(dict(c), {"t15": 2, "t13": 1})


class Stage(unittest.TestCase):
    OUT = {"version": "A", "why": "agree", "v20_other_team_trades": pn.others_trades([settle(1, ["t05", "t07"])]),
           "v20_other_makers": {"t15": 2}, "v20_other_offers": 2, "events": 3, "last_tick": 1,
           "ledger": {"ok": 1, "readings": 1, "last_tick": 1}, "merged_prs": 1, "leaderboard_v20": BOARD_ONE}

    def test_stage_names_no_team(self):
        text = "\n".join(pn.report(self.OUT, True, True))
        self.assertNotRegex(text, r"\bt\d\d\b")
        self.assertIn("SAL-10 for 30 P", text)

    def test_without_stage_the_parties_are_shown(self):
        self.assertIn("t05 and t07", "\n".join(pn.report(self.OUT, True, False)))


class Load(unittest.TestCase):
    def test_dedupes_by_id_and_skips_bad_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "feed.jsonl"
            p.write_text("\n".join([json.dumps(settle(2, ["t05", "t07"])), "not json",
                                    json.dumps(settle(1, ["t05", "t07"])), json.dumps(settle(2, ["t05", "t07"]))]))
            self.assertEqual([e["id"] for e in pn.load(p)], [1, 2])

    def test_merges_a_second_copy_and_skips_a_missing_one(self):
        with tempfile.TemporaryDirectory() as d:
            main, gap = Path(d) / "feed.jsonl", Path(d) / "gap.jsonl"
            main.write_text(json.dumps(settle(1, ["t05", "t07"])) + "\n" + json.dumps(settle(4, ["t05", "t07"])))
            gap.write_text(json.dumps(settle(2, ["t05", "t07"])) + "\n" + json.dumps(settle(4, ["t05", "t07"])))
            self.assertEqual([e["id"] for e in pn.load(main, (gap, Path(d) / "missing.jsonl"))], [1, 2, 4])


if __name__ == "__main__":
    unittest.main()
