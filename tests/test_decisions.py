"""Tests for tools/decisions.py: the shared decision-log normaliser (H2)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import decisions as D


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Normalise(unittest.TestCase):
    def test_market_decision_row_is_kept_only_for_an_actionable_kind_and_action(self):
        taken = {"ts": "t", "tick": 266, "event": "decision", "kind": "bid", "card": "LAV-10", "price": 71,
                  "value": 112.0, "gain": 41.0, "reason": "live bid 4142 at 71", "action": "post"}
        row = D.normalise("market", taken)
        self.assertEqual(row, {"ts": "t", "tick": 266, "lane": "market", "action": "bid:post", "card": "LAV-10",
                                "price": 71, "our_value": 112.0, "surplus": 41.0, "why": "live bid 4142 at 71",
                                "result": "proposed"})

    def test_market_skip_and_keep_and_note_are_dropped(self):
        for action in ("skip", "keep", "note"):
            self.assertIsNone(D.normalise("market", {"event": "decision", "kind": "buy", "action": action}))
        self.assertIsNone(D.normalise("market", {"event": "decision", "kind": "value", "action": "note"}))

    def test_market_terminal_events_map_their_result(self):
        self.assertEqual(D.normalise("market", {"ts": "t", "tick": 1, "event": "accepted", "side": "buy",
                                                  "card": "LAV-10", "price": 70, "value": 112, "gain": 42})["result"],
                          "accepted")
        self.assertEqual(D.normalise("market", {"event": "sent", "op": "post", "card": "X"})["result"], "sent")
        self.assertEqual(D.normalise("market", {"event": "refused", "card": "X"})["result"], "refused")
        self.assertEqual(D.normalise("market", {"event": "skip_accept", "offer": 1})["result"], "skipped")

    def test_market_unrelated_events_are_dropped(self):
        for event in ("maker_trade", "offer_cap", "heartbeat", "value"):
            self.assertIsNone(D.normalise("market", {"event": event}))

    def test_dealer_accept_and_result_rows(self):
        row = D.normalise("abuela", {"ts": "t", "tick": 40, "event": "accept", "thread": 49, "price": 22,
                                      "value": 40.0, "why": "crossed", "item": "LAV-07"})
        self.assertEqual(row, {"ts": "t", "tick": 40, "lane": "abuela", "action": "accept", "card": "LAV-07",
                                "price": 22, "our_value": 40.0, "surplus": None, "why": "crossed", "result": "accepted"})
        res = D.normalise("chato", {"ts": "t", "tick": 50, "event": "result", "thread": 49, "price": 22,
                                     "status": "deal", "item": "LAV-07", "reason": None})
        self.assertEqual((res["action"], res["result"]), ("settle", "deal"))

    def test_dealer_chatter_is_dropped(self):
        for event in ("open", "her", "say", "clock_wait", "resume", "save_thread_failed"):
            self.assertIsNone(D.normalise("abuela", {"event": event}))

    def test_pilar_runs_through_chato_py_use_the_same_mapping(self):
        row = D.normalise("chato", {"ts": "t", "tick": 60, "event": "accept", "item": "MAL-08", "price": 18, "value": 17.5})
        self.assertEqual(row["lane"], "chato")
        self.assertEqual(row["result"], "accepted")

    def test_duel_rows(self):
        row = D.normalise("duel", {"ts": "t", "tick": 700, "event": "accept", "duel": 2314, "role": "seller",
                                    "limit": 64, "taken": {"price": 68, "days": 0}})
        self.assertEqual(row, {"ts": "t", "tick": 700, "lane": "duel", "action": "accept", "card": 2314,
                                "price": 68, "our_value": 64, "surplus": None, "why": None, "result": "accepted"})

    def test_duel_chatter_is_dropped(self):
        for event in ("rival", "pass", "error", "late_skipped", "run_start", "run_end"):
            self.assertIsNone(D.normalise("duel", {"event": event}))

    def test_unknown_agent_drops_everything(self):
        self.assertIsNone(D.normalise("some_new_agent", {"event": "accept", "price": 1}))


class PassOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.logs = self.tmp / "logs"
        self.out = self.tmp / "decisions.jsonl"
        self.offsets = self.tmp / "decisions.offsets.json"

    def test_merges_two_lanes_into_one_canonical_file(self):
        write(self.logs / "abuela" / "2026-10-03.jsonl",
              [{"ts": "a", "tick": 1, "event": "open", "thread": 1},
               {"ts": "b", "tick": 2, "event": "accept", "item": "LAV-07", "price": 22, "value": 40, "why": "crossed"}])
        write(self.logs / "market" / "2026-10-03.jsonl",
              [{"ts": "c", "tick": 3, "event": "decision", "kind": "buy", "action": "post", "card": "LAV-09",
                "price": 88, "value": 112, "gain": 24, "reason": "under ceiling"}])
        rows = D.pass_once(self.logs, self.out, self.offsets)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["lane"] for r in rows}, {"abuela", "market"})
        on_disk = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual(on_disk, rows)

    def test_is_idempotent_across_repeated_passes(self):
        write(self.logs / "abuela" / "2026-10-03.jsonl",
              [{"ts": "a", "tick": 1, "event": "accept", "item": "LAV-07", "price": 22, "value": 40}])
        first = D.pass_once(self.logs, self.out, self.offsets)
        second = D.pass_once(self.logs, self.out, self.offsets)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(self.out.read_text().splitlines()), 1)

    def test_picks_up_only_lines_appended_since_the_last_pass(self):
        f = self.logs / "chato" / "2026-10-03.jsonl"
        write(f, [{"ts": "a", "tick": 1, "event": "accept", "item": "MAL-08", "price": 18, "value": 17.5}])
        D.pass_once(self.logs, self.out, self.offsets)
        with f.open("a") as fh:
            fh.write(json.dumps({"ts": "b", "tick": 2, "event": "accept", "item": "MAL-07", "price": 19, "value": 17.5}) + "\n")
        second = D.pass_once(self.logs, self.out, self.offsets)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["card"], "MAL-07")
        self.assertEqual(len(self.out.read_text().splitlines()), 2)

    def test_malformed_json_line_is_skipped_not_fatal(self):
        f = self.logs / "duel" / "2026-10-03.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text('{"ts": "a", "tick": 1, "event": "accept", "duel": 1, "limit": 10, "taken": {"price": 9}}\n'
                      'not json at all\n'
                      '{"ts": "b", "tick": 2, "event": "accept", "duel": 2, "limit": 20, "taken": {"price": 19}}\n')
        rows = D.pass_once(self.logs, self.out, self.offsets)
        self.assertEqual(len(rows), 2)

    def test_a_shrunk_rotated_file_is_read_from_the_start_again(self):
        f = self.logs / "market" / "2026-10-03.jsonl"
        write(f, [{"event": "decision", "kind": "buy", "action": "post", "card": "A", "price": 1},
                   {"event": "decision", "kind": "buy", "action": "post", "card": "B", "price": 2}])
        D.pass_once(self.logs, self.out, self.offsets)
        write(f, [{"event": "decision", "kind": "sell", "action": "post", "card": "C", "price": 3}])   # rotated, shorter
        rows = D.pass_once(self.logs, self.out, self.offsets)
        self.assertEqual([r["card"] for r in rows], ["C"])

    def test_no_logs_directory_yet_is_not_fatal(self):
        rows = D.pass_once(self.logs / "nope", self.out, self.offsets)
        self.assertEqual(rows, [])

    def test_offsets_file_survives_being_absent_or_corrupt(self):
        self.assertEqual(D.load_offsets(self.tmp / "missing.json"), {})
        bad = self.tmp / "bad.json"
        bad.write_text("{not json")
        self.assertEqual(D.load_offsets(bad), {})


if __name__ == "__main__":
    unittest.main()
