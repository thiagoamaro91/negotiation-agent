"""tools/sal10_fallback.py: the automatic 13:30 SAL-10 buy from Los Picaros (no network, no key)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
import sal10_fallback as s  # noqa: E402
from dealer_client import exact_offer  # noqa: E402


def ev(action, at, note="", **params):
    return {"action": action, "at_hours": at, "note": note, "params": params}


SCHED = [ev("duels", 18.65, name="Duels III"), ev("bench", 19.0), ev("bench", 21.0),
         ev("announce", 21.45, note="finale warning"), ev("duels", 21.65, name="Final duels")]


class Window(unittest.TestCase):
    def test_the_trigger_hour_is_clear(self):
        self.assertEqual(s.window(20.40, SCHED, 20), (True, "clear"))

    def test_a_run_that_would_reach_the_market_test_is_refused(self):
        ok, why = s.window(20.70, SCHED, 20)
        self.assertFalse(ok)
        self.assertIn("21.000", why)

    def test_inside_a_market_test_is_refused(self):
        self.assertFalse(s.window(21.05, SCHED, 20)[0])

    def test_after_the_test_the_final_quiet_window_still_refuses(self):
        ok, why = s.window(21.16, SCHED, 20)
        self.assertFalse(ok)
        self.assertRegex(why, "Final|finale")


class Ack(unittest.TestCase):
    def test_only_a_fresh_closed_bid_ack_counts(self):
        self.assertTrue(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": True}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-09", "tick": 2000, "open_bid": False}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 1990, "open_bid": False}, 2000))   # stale
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "open_bid": False}, 2000))
        self.assertFalse(s.ack_ok(None, 2000))

    def test_wait_returns_the_ack_when_it_lands(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ack"
            calls = []

            def sleep(_):
                calls.append(1)
                if len(calls) == 2:
                    path.write_text(json.dumps({"ref": "SAL-10", "tick": 2001, "open_bid": False}))
            a = s.wait_ack(2000, lambda: 2001, 3, 120, path=path, sleep=sleep, now=lambda: 0.0)
            self.assertEqual(a["tick"], 2001)

    def test_wait_gives_up_after_the_ticks(self):
        with tempfile.TemporaryDirectory() as d:
            ticks = iter([2000, 2002, 2004])
            a = s.wait_ack(2000, lambda: next(ticks), 3, 120, path=Path(d) / "ack", sleep=lambda _: None,
                           now=lambda: 0.0)
            self.assertIsNone(a)

    def test_a_paused_clock_ends_on_the_wall_bound(self):
        with tempfile.TemporaryDirectory() as d:
            t = iter(range(0, 1000, 50))
            a = s.wait_ack(2000, lambda: 2000, 3, 120, path=Path(d) / "ack", sleep=lambda _: None,
                           now=lambda: float(next(t)))
            self.assertIsNone(a)


class Outcome(unittest.TestCase):
    def test_outcomes(self):
        self.assertEqual(s.outcome(0, [{"event": "result", "status": "deal"}]), "deal")
        self.assertEqual(s.outcome(0, [{"event": "run_start", "plan": []}]), "nothing")
        self.assertEqual(s.outcome(0, [{"event": "stop", "code": "persona_quota"}]), "stop:persona_quota")
        self.assertEqual(s.outcome(0, [{"event": "result", "status": "closed"}]), "no_deal")
        self.assertEqual(s.outcome(6, []), "failed")

    def test_holds(self):
        self.assertTrue(s.holds({"assets": [{"kind": "card", "ref": "SAL-10"}]}))
        self.assertFalse(s.holds({"assets": [{"kind": "card", "ref": "SAL-09"}, {"kind": "pack", "ref": "SAL-10"}]}))

    def test_chato_command_is_one_picaros_sal10_deal_at_cap_88_reserve_40(self):
        a = s.parse_args(["run"])
        argv = s.chato_argv(a)
        for flag, want in (("--dealer", "picaros"), ("--only", "SAL-10"), ("--cap", "88"), ("--reserve", "40"),
                           ("--max-deals", "1")):
            self.assertEqual(argv[argv.index(flag) + 1], want)


class StructureCheck(unittest.TestCase):
    """Tick 1385, thread 2124: Los Picaros named SAL-09 inside a SAL-10 thread. Only the structured give binds."""

    def test_a_sal09_give_in_a_sal10_thread_is_refused(self):
        o = {"give": {"assets": [{"id": 9, "ref": "SAL-09"}]}, "want": {"cash": 56}}
        self.assertFalse(exact_offer(o, "buy", "SAL-10", None))
        self.assertFalse(exact_offer({"give": {"types": ["card:SAL-09"]}, "want": {"cash": 56}}, "buy", "SAL-10", None))

    def test_the_exact_sal10_give_is_taken(self):
        o = {"give": {"assets": [{"id": 10, "ref": "SAL-10"}]}, "want": {"cash": 56}}
        self.assertTrue(exact_offer(o, "buy", "SAL-10", None))


class Run(unittest.TestCase):
    """main('run') with the network and the subprocess faked: the yield/ack handshake and the factory markers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.rows = []
        log = mock.MagicMock()
        log.start.side_effect = lambda **k: self.rows.append({"event": "run_start", **k})
        log.event.side_effect = lambda e, **k: self.rows.append({"event": e, **k})
        self.patches = [mock.patch.object(s, "YIELD", d / "y"), mock.patch.object(s, "ACK", d / "y.ack"),
                        mock.patch.object(s, "STATE", d), mock.patch.object(s, "RunLog", return_value=log),
                        mock.patch.object(s, "load_env"), mock.patch.dict("os.environ", {"BAZAAR_KEY": "x"}),
                        mock.patch.object(s, "get_json", side_effect=self.api)]
        for p in self.patches:
            p.start()
        self.me = {"assets": [], "cash": 300}
        client = mock.MagicMock()
        client.return_value.me.side_effect = lambda: self.me
        self.patches.append(mock.patch("dealer_client.DealerBazaar", client))
        self.patches[-1].start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def api(self, path):
        return {"clock": {"t_hours": 20.40, "tick": 2000}, "schedule": {"upcoming": SCHED}}[path]

    def test_already_ours_is_a_nothing_to_do_marker_and_no_yield(self):
        self.me = {"assets": [{"kind": "card", "ref": "SAL-10"}]}
        self.assertEqual(s.main(["run"]), 0)
        self.assertEqual(self.rows[0]["plan"], [])
        self.assertFalse(s.YIELD.exists())

    def test_no_ack_buys_nothing_removes_the_yield_and_exits_nonzero(self):
        with mock.patch.object(s, "wait_ack", return_value=None), mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), s.EXIT_NO_ACK)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertNotEqual(self.rows[0]["plan"], [])      # never a done marker
        self.assertIn("no_ack", [r["event"] for r in self.rows])

    def test_ack_then_deal_keeps_the_yield_and_logs_the_done_marker(self):
        ack = {"ref": "SAL-10", "tick": 2001, "open_bid": False}
        with mock.patch.object(s, "wait_ack", return_value=ack), mock.patch.object(s, "other_picaros_runs", return_value=[]), \
                mock.patch.object(s.subprocess, "call", return_value=0) as call, \
                mock.patch.object(s, "read_rows", return_value=[{"event": "result", "status": "deal"}]):
            self.assertEqual(s.main(["run"]), 0)
            self.assertIn("SAL-10", call.call_args[0][0])
        self.assertTrue(s.YIELD.exists())
        self.assertIn({"event": "result", "status": "deal", "ref": "SAL-10", "dealer": "picaros"}, self.rows)

    def test_ack_then_no_deal_gives_the_bid_back_to_the_desk(self):
        ack = {"ref": "SAL-10", "tick": 2001, "open_bid": False}
        with mock.patch.object(s, "wait_ack", return_value=ack), mock.patch.object(s, "other_picaros_runs", return_value=[]), \
                mock.patch.object(s.subprocess, "call", return_value=0), mock.patch.object(s, "read_rows", return_value=[]):
            self.assertEqual(s.main(["run"]), 0)
        self.assertFalse(s.YIELD.exists())
        self.assertNotIn("result", [r["event"] for r in self.rows])

    def test_unsettled_keeps_the_yield(self):
        ack = {"ref": "SAL-10", "tick": 2001, "open_bid": False}
        with mock.patch.object(s, "wait_ack", return_value=ack), mock.patch.object(s, "other_picaros_runs", return_value=[]), \
                mock.patch.object(s.subprocess, "call", return_value=6), mock.patch.object(s, "read_rows", return_value=[]):
            self.assertEqual(s.main(["run"]), 6)
        self.assertTrue(s.YIELD.exists())

    def test_too_late_for_the_market_test_writes_no_yield(self):
        with mock.patch.object(s, "get_json", side_effect=lambda p: {"clock": {"t_hours": 20.8, "tick": 2000},
                                                                      "schedule": {"upcoming": SCHED}}[p]):
            self.assertEqual(s.main(["run"]), s.EXIT_WINDOW)
        self.assertFalse(s.YIELD.exists())


if __name__ == "__main__":
    unittest.main()
