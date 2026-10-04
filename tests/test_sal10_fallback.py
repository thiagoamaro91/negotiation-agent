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
        self.assertTrue(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False, "held": 0}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": True, "held": 0}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-09", "tick": 2000, "open_bid": False, "held": 0}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 1990, "open_bid": False, "held": 0}, 2000))   # stale
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "open_bid": False, "held": 0}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False}, 2000))   # no held count
        self.assertFalse(s.ack_ok(None, 2000))

    def test_held_must_be_an_int(self):
        self.assertTrue(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False, "held": 1}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False, "held": None}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False, "held": True}, 2000))
        self.assertFalse(s.ack_ok({"ref": "SAL-10", "tick": 2000, "open_bid": False, "held": -1}, 2000))


class WaitFor(unittest.TestCase):
    def test_returns_the_value_when_it_is_ready(self):
        vals = iter([None, None, "x"])
        self.assertEqual(s.wait_for(lambda: next(vals), lambda: 20.40, SCHED, 20, 120, 3, sleep=lambda _: None,
                                    now=lambda: 0.0), ("ready", "x"))

    def test_the_window_closing_ends_the_wait(self):
        hours = iter([20.40, 20.50, 20.70])
        state, why = s.wait_for(lambda: None, lambda: next(hours), SCHED, 20, 10_000, 3, sleep=lambda _: None,
                                now=lambda: 0.0)
        self.assertEqual(state, "window")
        self.assertIn("21.000", why)

    def test_a_paused_clock_ends_on_the_wall_bound(self):
        t = iter(range(0, 10_000, 50))
        self.assertEqual(s.wait_for(lambda: None, lambda: 20.40, SCHED, 20, 120, 3, sleep=lambda _: None,
                                    now=lambda: float(next(t))), ("wall", None))

    def test_a_failed_clock_read_falls_back_to_the_wall_bound(self):
        def boom():
            raise OSError("timeout")
        t = iter(range(0, 10_000, 50))
        self.assertEqual(s.wait_for(lambda: None, boom, SCHED, 20, 120, 3, sleep=lambda _: None,
                                    now=lambda: float(next(t))), ("wall", None))


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
    """main('run') with the network, the process table, the clock and the subprocess faked: the yield/ack handshake,
    the waits and the factory markers."""

    ACK0 = {"ref": "SAL-10", "tick": 2001, "open_bid": False, "held": 0}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.rows = []
        self.t = 0.0                  # fake monotonic seconds; every sleep advances it
        self.hours = 20.40            # what /api/clock says now
        self.acks = [self.ACK0]       # successive fresh_ack() answers (the last repeats); None = no ack yet
        self.busy = [[]]              # successive other_picaros_runs() answers (the last repeats)
        log = mock.MagicMock()
        log.start.side_effect = lambda **k: self.rows.append({"event": "run_start", **k})
        log.event.side_effect = lambda e, **k: self.rows.append({"event": e, **k})

        def sleep(sec):
            self.t += sec

        def pop(seq):
            return seq.pop(0) if len(seq) > 1 else seq[0]
        self.patches = [mock.patch.object(s, "YIELD", d / "y"), mock.patch.object(s, "ACK", d / "y.ack"),
                        mock.patch.object(s, "STATE", d), mock.patch.object(s, "RunLog", return_value=log),
                        mock.patch.object(s, "load_env"), mock.patch.dict("os.environ", {"BAZAAR_KEY": "x"}),
                        mock.patch.object(s, "get_json", side_effect=self.api),
                        mock.patch.object(s.time, "sleep", side_effect=sleep),
                        mock.patch.object(s.time, "monotonic", side_effect=lambda: self.t),
                        mock.patch.object(s, "fresh_ack", side_effect=lambda tick, path=None: pop(self.acks)),
                        mock.patch.object(s, "other_picaros_runs", side_effect=lambda: pop(self.busy))]
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
        return {"clock": {"t_hours": self.hours, "tick": 2000}, "schedule": {"upcoming": SCHED}}[path]

    def events(self):
        return [r["event"] for r in self.rows]

    def done_marker(self):
        return any(r["event"] == "run_start" and r.get("plan") == [] for r in self.rows) or \
            any(r["event"] == "result" and r.get("status") == "deal" for r in self.rows)

    def test_already_ours_is_a_nothing_to_do_marker_and_no_yield(self):
        self.me = {"assets": [{"kind": "card", "ref": "SAL-10"}]}
        self.assertEqual(s.main(["run"]), 0)
        self.assertEqual(self.rows[0]["plan"], [])
        self.assertFalse(s.YIELD.exists())

    def test_ack_with_held_buys_nothing_and_logs_the_done_marker(self):
        self.acks = [None, dict(self.ACK0, held=1)]
        with mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), 0)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertTrue(self.done_marker())

    def test_a_desk_fill_while_waiting_for_picaros_buys_nothing(self):
        self.busy = [[], [4242], [4242]]                    # free before the yield, busy right after the ack
        self.acks = [self.ACK0, self.ACK0, dict(self.ACK0, tick=2003, held=1)]
        with mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), 0)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertTrue(self.done_marker())

    def test_no_ack_until_the_window_closes_removes_the_yield_and_exits_2(self):
        self.acks = [None]

        def api(path):
            if path == "clock":
                self.hours = round(self.hours + 0.05, 3)     # the game clock runs while we wait
            return {"clock": {"t_hours": self.hours, "tick": 2000}, "schedule": {"upcoming": SCHED}}[path]
        self.hours = 20.35
        with mock.patch.object(s, "get_json", side_effect=api), mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), s.EXIT_NO_ACK)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertFalse(self.done_marker())
        self.assertIn("no_ack", self.events())

    def test_no_ack_on_a_paused_clock_is_a_retry_later_without_a_marker(self):
        self.acks = [None]
        with mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), s.EXIT_RETRY)
            call.assert_not_called()
        self.assertEqual(s.EXIT_RETRY, 0)              # rc 0 without a marker: tools/factory.py relaunches the step
        self.assertFalse(s.YIELD.exists())
        self.assertFalse(self.done_marker())
        self.assertIn("retry_later", self.events())

    def test_a_picaros_run_longer_than_300_s_is_waited_out_inside_the_window(self):
        self.busy = [[4242]] * 60 + [[]]                   # busy for 60 polls of 10 s: 600 s
        with mock.patch.object(s.subprocess, "call", return_value=0) as call, \
                mock.patch.object(s, "read_rows", return_value=[{"event": "result", "status": "deal"}]):
            self.assertEqual(s.main(["run"]), 0)
            call.assert_called_once()
        self.assertGreater(self.t, 300)
        self.assertIn("busy_wait", self.events())
        self.assertTrue(s.YIELD.exists())                  # a deal keeps the yield
        self.assertIn({"event": "result", "status": "deal", "ref": "SAL-10", "dealer": "picaros"}, self.rows)

    def test_the_busy_wait_writes_no_yield_until_picaros_is_free(self):
        seen = []

        def busy():
            seen.append(s.YIELD.exists())
            return [4242] if len(seen) < 5 else []
        with mock.patch.object(s, "other_picaros_runs", side_effect=busy), \
                mock.patch.object(s.subprocess, "call", return_value=0), mock.patch.object(s, "read_rows", return_value=[]):
            self.assertEqual(s.main(["run"]), 0)
        self.assertEqual(seen[:5], [False] * 5)

    def test_window_expiry_while_picaros_is_busy_is_a_clean_exit_6(self):
        self.busy = [[4242]]

        def api(path):
            if path == "clock":
                self.hours = round(self.hours + 0.05, 3)
            return {"clock": {"t_hours": self.hours, "tick": 2000}, "schedule": {"upcoming": SCHED}}[path]
        self.hours = 20.35
        with mock.patch.object(s, "get_json", side_effect=api), mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), s.EXIT_WINDOW)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertFalse(self.done_marker())

    def test_window_expiry_after_the_ack_removes_the_yield(self):
        self.busy = [[], [4242]]                           # free before the yield, then a keeper run starts

        def api(path):
            if path == "clock":
                self.hours = round(self.hours + 0.05, 3)
            return {"clock": {"t_hours": self.hours, "tick": 2000}, "schedule": {"upcoming": SCHED}}[path]
        self.hours = 20.35
        with mock.patch.object(s, "get_json", side_effect=api), mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), s.EXIT_WINDOW)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertIn("yield_written", self.events())

    def test_a_busy_picaros_on_a_paused_clock_is_a_retry_later(self):
        self.busy = [[4242]]
        with mock.patch.object(s.subprocess, "call") as call:
            self.assertEqual(s.main(["run"]), s.EXIT_RETRY)
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())
        self.assertFalse(self.done_marker())
        self.assertIn("retry_later", self.events())

    def test_a_run_that_starts_at_the_last_look_is_waited_out_too(self):
        self.busy = [[], [], [4242], [4242], []]            # free, free (ready), BUSY at the last look, then free
        with mock.patch.object(s.subprocess, "call", return_value=0) as call, \
                mock.patch.object(s, "read_rows", return_value=[]):
            self.assertEqual(s.main(["run"]), 0)
            call.assert_called_once()
        self.assertIn("busy_wait", self.events())

    def test_ack_then_deal_keeps_the_yield_and_logs_the_done_marker(self):
        with mock.patch.object(s.subprocess, "call", return_value=0) as call, \
                mock.patch.object(s, "read_rows", return_value=[{"event": "result", "status": "deal"}]):
            self.assertEqual(s.main(["run"]), 0)
            self.assertIn("SAL-10", call.call_args[0][0])
        self.assertTrue(s.YIELD.exists())
        self.assertIn({"event": "result", "status": "deal", "ref": "SAL-10", "dealer": "picaros"}, self.rows)

    def test_ack_then_no_deal_gives_the_bid_back_to_the_desk(self):
        with mock.patch.object(s.subprocess, "call", return_value=0), mock.patch.object(s, "read_rows", return_value=[]):
            self.assertEqual(s.main(["run"]), 0)
        self.assertFalse(s.YIELD.exists())
        self.assertNotIn("result", self.events())

    def test_unsettled_keeps_the_yield(self):
        with mock.patch.object(s.subprocess, "call", return_value=6), mock.patch.object(s, "read_rows", return_value=[]):
            self.assertEqual(s.main(["run"]), 6)
        self.assertTrue(s.YIELD.exists())

    def test_a_failed_clock_read_after_the_ack_gives_the_bid_back(self):
        reads = iter([{"t_hours": 20.40, "tick": 2000}, {"upcoming": SCHED}])

        def api(path):
            try:
                return next(reads)
            except StopIteration:
                raise OSError("timeout") from None
        with mock.patch.object(s, "get_json", side_effect=api), mock.patch.object(s.subprocess, "call") as call:
            with self.assertRaises(OSError):
                s.main(["run"])
            call.assert_not_called()
        self.assertFalse(s.YIELD.exists())

    def test_too_late_for_the_market_test_writes_no_yield(self):
        self.hours = 20.8
        self.assertEqual(s.main(["run"]), s.EXIT_WINDOW)
        self.assertFalse(s.YIELD.exists())


if __name__ == "__main__":
    unittest.main()
