"""Sunday factory: schedule to wall time, gates, command rendering, staleness, the Market Test watch, double starts.

    python3 -m unittest discover tests
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import factory as f  # noqa: E402

MAD = f.MADRID
SAT_1400 = datetime(2026, 10, 3, 14, 0, tzinfo=MAD).timestamp()
SUN_0900 = datetime(2026, 10, 4, 9, 0, tzinfo=MAD).timestamp()
DAYS = [{"day": "sat", "opens": "2026-10-03T09:00:00+02:00", "closes": "2026-10-03T23:00:00+02:00", "tick_seconds": 30.0},
        {"day": "sun", "opens": "2026-10-04T09:00:00+02:00", "closes": "2026-10-04T15:00:00+02:00", "tick_seconds": 15.0}]


def clock(t_hours=16.0, tick_seconds=15.0, paused=False, doors="open", next_opens=None, closes=None):
    return {"tick": 100, "t_hours": t_hours, "tick_seconds": tick_seconds, "paused": paused, "doors": doors,
            "next_opens": next_opens, "closes": closes, "days": DAYS}


def ev(action, at, **params):
    return {"action": action, "at_hours": at, "note": params.pop("note", ""), "params": params}


DUELS3 = ev("duels", 18.65, name="Duels III", duel_ticks=12, rounds=2)
FINAL = ev("duels", 21.65, name="Final duels", duel_ticks=12, rounds=1)
GRANT = ev("grant_all", 16.7, cash=150)


class WallTime(unittest.TestCase):
    def test_same_wall_time_at_15_30_60_s_ticks_but_tick_count_scales(self):
        # measured: t_hours advances tick_seconds/3600 per tick, so a game hour is a wall hour at any tick length
        for tick_s, ticks in ((15, 240), (30, 120), (60, 60)):
            c = clock(t_hours=16.0, tick_seconds=tick_s)
            self.assertEqual(f.to_wall(17.0, c, [], SAT_1400), (SAT_1400 + 3600, False))
            self.assertEqual(f.ticks_until(17.0, 16.0, tick_s), ticks)

    def test_pause_marks_earliest_and_every_paused_minute_moves_the_event(self):
        c = clock(t_hours=16.0, paused=True)
        self.assertEqual(f.to_wall(17.0, c, [], SAT_1400), (SAT_1400 + 3600, True))
        # 30 minutes later, still paused at the same game hour: the event is 30 minutes later
        self.assertEqual(f.to_wall(17.0, c, [], SAT_1400 + 1800), (SAT_1400 + 5400, True))
        # resumed: the same arithmetic, no longer a lower bound
        self.assertEqual(f.to_wall(17.0, clock(t_hours=16.0), [], SAT_1400 + 1800)[1], False)

    def test_doors_closed_counts_from_the_next_opening(self):
        c = clock(t_hours=15.063, doors="closed", next_opens="2026-10-04T09:00:00+02:00")
        wall, early = f.to_wall(18.65, c, [], SUN_0900 - 300)
        self.assertAlmostEqual(wall, SUN_0900 + (18.65 - 15.063) * 3600, places=3)
        self.assertFalse(early)

    def test_overnight_gap_uses_the_day_opening_wall_time(self):
        opens = {"action": "day_opens", "at_hours": 15.063, "wall": "2026-10-04T09:00:00+02:00", "params": {}}
        c = clock(t_hours=6.575, tick_seconds=30.0)
        self.assertAlmostEqual(f.to_wall(18.65, c, [opens], SAT_1400)[0], SUN_0900 + 3.587 * 3600, places=3)
        self.assertAlmostEqual(f.to_wall(7.0, c, [opens], SAT_1400)[0], SAT_1400 + 0.425 * 3600, places=3)

    def test_until_is_the_closing_time_of_the_run_day_in_madrid(self):
        c = clock(closes="2026-10-03T23:00:00+02:00")
        self.assertEqual(f.until_for(c, SUN_0900 + 3600, 5), "15:05")
        self.assertEqual(f.until_for(c, SAT_1400, 5), "23:05")
        self.assertEqual(f.until_for(c, SUN_0900 + 10 * 3600, 5), "23:05")   # outside every day: the clock's close


class Gates(unittest.TestCase):
    DEALER = {"doors_open": True, "clock_running": True, "no_duel_lock": True, "duel_quiet_min": 12}

    def gate(self, c, events=(), lock=None, extra=None):
        return f.check_gates({**self.DEALER, **(extra or {})}, c, list(events), lock, SUN_0900)

    def test_paused_and_doors_closed_hold_dealer_runs(self):
        self.assertEqual(self.gate(clock(paused=True)), (False, "clock paused"))
        self.assertFalse(self.gate(clock(doors="closed"))[0])
        self.assertTrue(self.gate(clock())[0])

    def test_fresh_lock_holds_and_stale_lock_opens(self):
        self.assertFalse(self.gate(clock(), lock=SUN_0900 + 30)[0])
        self.assertTrue(self.gate(clock(), lock=SUN_0900 - 1)[0])
        self.assertTrue(self.gate(clock(), lock=None)[0])

    def test_no_dealer_start_just_before_a_duel_wave(self):
        self.assertFalse(self.gate(clock(t_hours=18.50), [DUELS3])[0])     # 9 min before Duels III
        self.assertFalse(self.gate(clock(t_hours=18.66), [DUELS3])[0])     # wave just started, lock not yet written
        self.assertTrue(self.gate(clock(t_hours=18.30), [DUELS3])[0])

    def test_after_event_waits_for_the_allowance(self):
        after = {"after_event": {"action": "grant_all", "delay_min": 1}}
        self.assertFalse(self.gate(clock(t_hours=16.69), [GRANT], extra=after)[0])
        self.assertFalse(self.gate(clock(t_hours=16.71), [GRANT], extra=after)[0])
        self.assertTrue(self.gate(clock(t_hours=16.72), [GRANT], extra=after)[0])
        self.assertIn("not in the schedule", self.gate(clock(t_hours=17.0), [], extra=after)[1])

    def test_duel_session_window_in_game_hours(self):
        sess = {"event": {"action": "duels"}, "lead_min": 10, "window_min": 120}
        ev3, events = DUELS3, [DUELS3, FINAL]
        self.assertEqual(f.session_pick(sess, events, 18.65 - 0.2), (ev3, False))
        self.assertEqual(f.session_pick(sess, events, 18.65 - 0.1), (ev3, True))
        self.assertEqual(f.session_pick(sess, events, 18.65 + 1.9), (ev3, True))
        self.assertEqual(f.session_pick(sess, events, 18.65 + 2.1), (FINAL, False))
        self.assertEqual(f.session_pick(sess, events, 21.65 + 2.1), (None, False))

    def test_fired_events_survive_in_the_cache_and_moved_ones_drop(self):
        moved = ev("bench", 19.0)
        merged = f.merge_events([FINAL], [DUELS3, moved, FINAL], now_hours=18.7)
        self.assertEqual(merged, [DUELS3, FINAL])
        self.assertEqual(f.merge_events([DUELS3], [DUELS3], now_hours=18.65), [DUELS3])   # firing now: listed once


class Rendering(unittest.TestCase):
    CFG = f.load_config(f.CONFIG)

    def ctx(self, p, c=None, events=(DUELS3, FINAL)):
        c = c or clock(t_hours=18.6, closes="2026-10-04T15:00:00+02:00")
        return f.context(self.CFG, f.CONFIG, p, c, list(events), SUN_0900 + 3 * 3600)

    def test_every_command_in_the_sunday_config_renders(self):
        for p in self.CFG["processes"]:
            self.assertIn(p["kind"], ("service", "session", "steps"), p["name"])
            for s in p.get("steps") or [p]:
                argv = f.render(s["cmd"], self.ctx(p))
                self.assertFalse([a for a in argv if "{" in a or "}" in a], (p["name"], argv))

    def test_duel_run_takes_ticks_from_the_schedule_and_covers_the_day(self):
        p = next(x for x in self.CFG["processes"] if x["name"] == "duel")
        argv = f.render(p["cmd"], self.ctx(p))
        self.assertEqual(argv[argv.index("--duel-ticks") + 1], "12")
        self.assertEqual(argv[argv.index("--late-poll") + 1], "4")
        self.assertEqual(argv[argv.index("--until") + 1], "15:05")
        self.assertEqual(argv[argv.index("--idle-ticks") + 1], "660")          # the 165 min window at 15 s

    def test_duel_window_outlasts_a_wave_on_a_game_clock_of_either_speed(self):
        """A crashed duel bot is relaunched only while its window is open (game minutes). Duels III is two rounds of
        34 duels, four at a time, 12 ticks each: 216 ticks, which is 108 game minutes if the clock runs two game
        hours per wall hour at 15 s ticks (30 game seconds a tick) and 54 if it runs one. The window must be well
        past the longer one (x1.5: gaps between rounds), yet closed before the Final opens its own, so that the two
        never overlap (inside an overlap the first wave would be picked and the Final's own checks skipped)."""
        sess = next(x for x in self.CFG["processes"] if x["name"] == "duel")["session"]
        ideal_ticks = 2 * -(-34 // 4) * 12
        for game_s_per_tick in (15, 30):
            wave_h = 1.5 * ideal_ticks * game_s_per_tick / 3600
            self.assertEqual(f.session_pick(sess, [DUELS3, FINAL], 18.65 + wave_h), (DUELS3, True), game_s_per_tick)
        self.assertLess(18.65 + sess["window_min"] / 60, 21.65 - sess["lead_min"] / 60)
        self.assertEqual(f.session_pick(sess, [DUELS3, FINAL], 21.65 - sess["lead_min"] / 60 + 0.01), (FINAL, True))
        self.assertEqual(f.session_pick(sess, [DUELS3, FINAL], 22.55), (FINAL, True))      # the freeze warning

    def test_dealer_flags_are_explicit(self):
        for p in self.CFG["processes"]:
            if p["kind"] != "steps":
                continue
            for s in p["steps"]:
                sells = any(str(a).startswith("sell:") for a in s["cmd"])
                strict = s.get("enabled", True)       # a step that is OFF by design (a by-hand line) needs the basics only
                for flag in ("--only", "--max-deals", *(("--floor" if sells else "--reserve",) if strict else ())):
                    self.assertIn(flag, s["cmd"], (p["name"], s["label"]))
                if "agent/chato.py" in s["cmd"]:
                    if strict:
                        self.assertIn("--max-rounds", s["cmd"], s["label"])
                    self.assertNotIn("--max-bid", s["cmd"], s["label"])

    def test_unknown_placeholder_is_an_error(self):
        with self.assertRaises(ValueError):
            f.render(["{python}", "{nope}"], {"python": "python3"})


class Staleness(unittest.TestCase):
    def test_threshold_scales_with_the_tick(self):
        self.assertTrue(f.is_stale(70, 4, 15.0))        # 4 ticks = 60 s
        self.assertFalse(f.is_stale(70, 4, 30.0))       # 4 ticks = 120 s
        self.assertTrue(f.is_stale(130, 4, 30.0))
        self.assertFalse(f.is_stale(25, 4, 5.0))        # never under the 30 s floor
        self.assertFalse(f.is_stale(10_000, None, 15.0))
        self.assertFalse(f.is_stale(None, 4, 15.0))


def book(tick, bench=True):
    offers = [{"id": "b36-17", "maker": "bench"}] if bench else []
    return {"event": "book", "tick": tick, "book": {"bench_offers": offers}}


class MarketTestWatch(unittest.TestCase):
    def test_saturday_b36_dropped_everything(self):
        rows = [book(t) for t in range(441, 456)]
        rows += [{"event": "dropped", "tick": t, "match": ["b36-17", "b36-4", 52]} for t in (442, 447, 447)]
        rows.append(book(460, bench=False))
        s = f.bench_summary(rows)
        self.assertEqual((s["bench"], s["first"], s["last"], s["matched"], s["dropped"], s["live"]),
                         ("b36", 441, 455, 0, 3, False))
        self.assertEqual(len(f.bench_alerts(s, 460)), 2)
        self.assertEqual(f.bench_alerts(s, 480), [])     # 25 ticks after the test: shown, no longer failing

    def test_live_test_with_a_match_is_clean_and_no_match_alerts_after_six_ticks(self):
        rows = [book(t) for t in range(100, 104)]
        self.assertEqual(f.bench_alerts(f.bench_summary(rows), 103), [])
        rows += [book(t) for t in range(104, 108)]
        self.assertIn("no match", f.bench_alerts(f.bench_summary(rows), 107)[0])
        rows.append({"event": "matched", "tick": 107, "sell": "b36-17", "buy": "b36-3"})
        self.assertEqual(f.bench_alerts(f.bench_summary(rows), 107), [])


class DoubleStart(unittest.TestCase):
    PS = ["  101 /opt/homebrew/bin/python3 -u agent/broker.py run --policy stall",
          "  102 /opt/homebrew/Cellar/python@3.13/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/"
          "Contents/MacOS/Python -u /Users/x/bazaar/agent/chato.py run --dealer pilar --only sell:44",
          "  103 python3 -u agent/chato.py run --only SAL-09",
          "  104 claude -p please run python3 agent/broker.py run --policy stall",
          "  105 /bin/bash -c python3 -u agent/duel.py run",
          "  106 python3 -u tools/factory.py keep broker --config tools/factory_sunday.json",
          "  107 python3 agent/abuela.py plan"]

    def test_ps_matching_finds_bots_and_shell_wrappers_and_ignores_agents_and_keepers(self):
        self.assertEqual(f.ps_pids(self.PS, ["agent/broker.py", "run"]), [101])
        self.assertEqual(f.ps_pids(self.PS, ["agent/chato.py", "pilar"]), [102])
        self.assertEqual(f.ps_pids(self.PS, ["agent/chato.py", "run"], ["pilar"]), [103])
        self.assertEqual(f.ps_pids(self.PS, ["agent/duel.py", "run"]), [105])      # a shell running the bot
        self.assertEqual(f.ps_pids(self.PS, ["agent/abuela.py", "run"]), [])

    def test_refuses_a_second_start(self):
        self.assertIn("window", f.refuse_reason("broker", {"broker"}, False, []))
        self.assertIn("keeper", f.refuse_reason("broker", set(), True, []))
        self.assertIn("pid 101", f.refuse_reason("broker", set(), False, [101]))
        self.assertIsNone(f.refuse_reason("broker", {"duel"}, False, []))

    def test_steps_already_done_or_disabled_are_not_rerun(self):
        p = {"steps": [{"label": "a", "cmd": []}, {"label": "b", "enabled": False, "cmd": []}, {"label": "c", "cmd": []}]}
        self.assertEqual([s["label"] for s in f.pending_steps(p, ["a"])], ["c"])


# --- review round: behaviour of up, keep, status and the schedule cache with the OS and network mocked ---------------

DEAD_PID = 4194311          # above the macOS pid limit: never alive
SERVICE = {"name": "broker", "kind": "service", "required": True, "gates": {"doors_open": True},
           "cmd": ["{python}", "-c", "pass"], "match": ["agent/broker.py", "run"], "log": "logs/broker/{date}.jsonl"}
DEALER = {"name": "abuela", "kind": "steps", "required": False, "gates": {"doors_open": True, "clock_running": True},
          "match": ["agent/abuela.py", "run"], "log": "logs/abuela/{date}.jsonl", "steps": [{"label": "a", "cmd": ["{python}", "-c", "pass"]},
                                                         {"label": "b", "cmd": ["{python}", "-c", "pass"]}]}


class Stop(Exception):
    pass


class FakeChild:
    def __init__(self, rc=0, polls=1, hang=False, log=None, writes=()):
        self.rc, self.polls, self.hang, self.pid, self.returncode = rc, polls, hang, DEAD_PID, None
        self.log, self.writes = log, list(writes)
        self.stdout = io.BytesIO(b"bot output\n")

    def poll(self):
        if self.polls > 0:
            self.polls -= 1
            return None
        if self.hang:            # a long run: end the test here, once
            self.hang = False
            raise Stop
        if self.writes and self.returncode is None:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log, "a") as fh:
                fh.write("".join(json.dumps(w) + "\n" for w in self.writes))
        self.returncode = self.rc
        return self.rc

    def wait(self, timeout=None):
        if self.poll() is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.rc

    def terminate(self):
        self.polls = 0

    kill = terminate


class Sandbox(unittest.TestCase):
    """factory.ROOT and STATE in a temp dir; ps, the bus, signals, the network, Popen and sleep are fakes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ps, self.bus_rc, self.bus_calls, self.board = [], 0, [], {}
        for target, value in (("ROOT", self.tmp), ("STATE", self.tmp / "results" / "factory"),
                              ("LOCK", self.tmp / "results" / "duel.lock"), ("ps_lines", lambda: list(self.ps)),
                              ("bus", self.fake_bus), ("bus_board", lambda cfg: self.board)):
            mock.patch.object(f, target, value, create=True).start()
        mock.patch.object(f.signal, "signal", lambda *a: None).start()
        mock.patch.object(f, "RECHECK_S", 0, create=True).start()
        self.addCleanup(mock.patch.stopall)

    def dealer_log(self):
        return self.tmp / "logs" / "abuela" / f"{f.today()}.jsonl"

    def hold(self, name):
        fd = f.acquire_singleton(name)
        self.assertIsNotNone(fd)
        self.addCleanup(os.close, fd)
        return fd

    def fake_bus(self, cfg, action, thing, *a, **k):
        self.bus_calls.append((action, thing))
        return self.bus_rc

    def config(self, *procs, env=None):
        path = self.tmp / "cfg.json"
        path.write_text(json.dumps({"processes": list(procs), "env": env or {}}))
        return path

    def keep(self, cfg_path, name, clocks, children=(), sleeps=6, schedule=(), environ=None):
        self.popen, kids, seq, n = [], iter(children), list(clocks), [0]

        def popen(argv, **kw):
            c = next(kids)
            c.argv, c.env = argv, kw.get("env")
            self.popen.append(c)
            return c

        def get(cfg, path):
            if path == "schedule":
                return {"upcoming": list(schedule)}
            return seq.pop(0) if len(seq) > 1 else seq[0]

        def sleep(_s):
            n[0] += 1
            if n[0] >= sleeps:
                raise Stop

        env_patch = mock.patch.dict(os.environ, environ or {}, clear=False)
        with mock.patch.object(f, "get", get), mock.patch.object(f.subprocess, "Popen", popen), env_patch, \
                mock.patch.object(f.time, "sleep", sleep), contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = f.cmd_keep(cfg_path, name)
            except Stop:
                rc = "looping"
        return rc, f.state_of(name)

    def up(self, cfg_path, **kw):
        calls, buf = [], io.StringIO()

        def run(argv, **k):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with mock.patch.object(f.shutil, "which", lambda n: "/usr/bin/tmux"), \
                mock.patch.object(f.subprocess, "run", run), contextlib.redirect_stdout(buf):
            rc = f.cmd_up(f.load_config(cfg_path), cfg_path, True, **kw)
        return rc, buf.getvalue(), [c for c in calls if c[:2] == ["tmux", "new-window"]]

    def status(self, cfg_path, clock_now, schedule=()):
        def get(cfg, path):
            return {"upcoming": list(schedule)} if path == "schedule" else clock_now
        with mock.patch.object(f, "get", get):
            return f.status_once(f.load_config(cfg_path))


class ReviewSingleton(Sandbox):
    """Item 1: one keeper per process (lock file held for its life) and outside copies seen in both forms."""

    def test_singleton_lock_blocks_a_second_keeper(self):
        cfg = self.config(SERVICE)
        self.hold("broker")
        rc, _ = self.keep(cfg, "broker", [clock()], [FakeChild()])
        self.assertNotEqual(rc, "looping")
        self.assertEqual(self.popen, [])
        self.assertTrue(f.singleton_held("broker"))

    def test_keeper_does_not_launch_while_an_outside_copy_runs(self):
        self.ps = ["  4242 /bin/bash -c while true; do python3 -m agent.broker run --policy stall; sleep 10; done"]
        rc, st = self.keep(self.config(SERVICE), "broker", [clock()], [FakeChild()])
        self.assertEqual(self.popen, [])
        self.assertIn("4242", st.get("why", ""))

    def test_ps_matches_module_form_and_shell_c_loops_but_never_reads_scripts(self):
        loop = self.tmp / "broker_loop.sh"
        loop.write_text("while true; do\n  python3 -u agent/broker.py run --policy stall\n  sleep 10\ndone\n")
        lines = ["  11 /opt/homebrew/bin/python3 -m agent.broker run --policy stall",
                 f"  12 /bin/bash {loop}",                     # inside a script file: seen only via its child
                 "  13 /bin/zsh -c python3 agent/broker.py plan --book x.json",
                 "  14 node /usr/local/bin/claude -p run agent/broker.py run",
                 "  15 /bin/bash -c while true; do python3 agent/broker.py run; sleep 10; done"]
        self.assertEqual(f.ps_pids(lines, ["agent/broker.py", "run"]), [11, 15])


class ReviewBus(Sandbox):
    """Item 2: no claim, no start; --no-bus is the operator's explicit override."""

    def test_up_fails_closed_when_the_bus_is_unreachable(self):
        self.bus_rc = 1
        rc, out, started = self.up(self.config(SERVICE))
        self.assertEqual(started, [])
        self.assertIn("REFUSE", out)
        self.assertNotEqual(rc, 0)

    def test_no_bus_override_starts_without_a_claim(self):
        self.bus_rc = 1
        rc, out, started = self.up(self.config(SERVICE), no_bus=True)
        self.assertEqual(len(started), 1)
        self.assertEqual(self.bus_calls, [])
        self.assertIn("--no-bus", started[0][-1])


class ReviewPauseGate(Sandbox):
    """Item 3: every game bot waits for a running clock, at launch and at every restart."""

    def test_every_game_bot_waits_for_a_running_clock(self):
        cfg = f.load_config(f.CONFIG)
        paused = clock(t_hours=18.6, paused=True)
        for p in cfg["processes"]:
            if p["name"] in ("feed", "watchdog"):
                continue
            self.assertFalse(f.check_gates(f.gates_for(p), paused, [], None, SUN_0900)[0], p["name"])

    def test_service_restart_waits_while_paused(self):
        clocks = [clock(), clock(paused=True)]
        rc, st = self.keep(self.config(SERVICE), "broker", clocks, [FakeChild(rc=1), FakeChild(rc=1)], sleeps=8)
        self.assertEqual(len(self.popen), 1)
        self.assertEqual(st["why"], "clock paused")


class ReviewDealerExit(Sandbox):
    """Item 4: a dealer run that exits non-zero is not relaunched; the keeper stops and status reports it."""

    def test_dealer_nonzero_exit_is_not_relaunched_and_is_reported(self):
        cfg = self.config(DEALER)
        rc, st = self.keep(cfg, "abuela", [clock()], [FakeChild(rc=3), FakeChild(rc=3), FakeChild(rc=3)])
        self.assertEqual(len(self.popen), 1)
        self.assertNotEqual(rc, "looping")
        self.assertEqual((st["state"], st["failed_steps"], st["last_rc"]), ("failed", ["a"], 3))
        _, problems = self.status(cfg, clock())
        self.assertTrue([x for x in problems if "abuela" in x and "rc=3" in x], problems)

    def test_next_dealer_step_waits_while_paused(self):
        deal = FakeChild(log=self.dealer_log(), writes=[{"event": "result", "status": "deal"}])
        rc, st = self.keep(self.config(DEALER), "abuela", [clock(), clock(paused=True)], [deal, FakeChild()])
        self.assertEqual(len(self.popen), 1)
        self.assertEqual((st["done_steps"], st["why"]), (["a"], "clock paused"))


class ReviewScheduleCache(Sandbox):
    """Item 5: keepers share one cache file; a race or a failed save never kills a keeper."""

    def test_concurrent_writers_do_not_crash(self):
        errors, path = [], self.tmp / "results" / "factory" / "schedule-x.json"

        def writer():
            for i in range(40):
                try:
                    f.write_json(path, [{"i": i}])
                except Exception as e:
                    errors.append(e)
        threads = [threading.Thread(target=writer) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])

    def test_events_now_survives_a_failed_save(self):
        def boom(*a):
            raise OSError("disk full")
        with mock.patch.object(f, "get", lambda cfg, path: {"upcoming": [DUELS3]}), \
                mock.patch.object(f, "write_json", boom):
            self.assertEqual(f.events_now({}, clock(t_hours=18.0), save=True), [DUELS3])


class ReviewStatusTruth(Sandbox):
    """Item 6: status checks the child pid itself and fails a log that never appears."""

    def state(self, **kw):
        f.write_json(f.STATE / "broker.json", {"date": f.today(), "name": "broker", **kw})

    def test_status_flags_a_dead_child_under_a_live_keeper(self):
        cfg = self.config(SERVICE)
        self.hold("broker")
        self.state(keeper_pid=os.getpid(), child_pid=DEAD_PID, state="running", started=time.time() - 30)
        lines, problems = self.status(cfg, clock())
        self.assertNotIn("RUNNING", lines[1])
        self.assertTrue([x for x in problems if "broker" in x], problems)

    def test_status_fails_a_missing_log_after_grace(self):
        cfg = self.config(SERVICE)
        self.hold("broker")
        self.ps = [f"  {os.getpid()} python3 -u agent/broker.py run --policy stall"]
        self.state(keeper_pid=os.getpid(), child_pid=os.getpid(), state="running", started=time.time() - 600)
        _, problems = self.status(cfg, clock())
        self.assertTrue([x for x in problems if "no log" in x], problems)

    def test_status_does_not_trust_a_reused_pid(self):
        cfg = self.config(SERVICE)
        self.hold("broker")
        self.ps = [f"  {os.getpid()} /usr/bin/vim notes.txt"]          # alive, but not the broker
        self.state(keeper_pid=os.getpid(), child_pid=os.getpid(), state="running", started=time.time() - 30)
        lines, problems = self.status(cfg, clock())
        self.assertIn("NO CHILD", lines[1])
        self.assertTrue([x for x in problems if "gone" in x], problems)

    def test_status_alerts_a_scheduled_market_test_the_broker_never_saw(self):
        cfg = self.config(dict(SERVICE, bench_watch=True))
        self.hold("broker")
        self.ps = [f"  {os.getpid()} python3 -u agent/broker.py run --policy stall"]
        self.state(keeper_pid=os.getpid(), child_pid=os.getpid(), state="running", started=time.time() - 30)
        _, problems = self.status(cfg, dict(clock(t_hours=17.05), tick=1000), schedule=[ev("bench", 17.0, ticks=16)])
        self.assertTrue([x for x in problems if "not on our book" in x], problems)


class ReviewBench(unittest.TestCase):
    """Items 7 and 8: only our bench run's offers count, and a scheduled test we never saw alerts."""

    def test_public_fill_does_not_hide_a_zero_match_test(self):
        rows = [book(t) for t in range(100, 108)]
        rows.append({"event": "matched", "tick": 103, "sell": 5012, "buy": 5013})
        alerts = f.bench_alerts(f.bench_summary(rows), 107)
        self.assertTrue([a for a in alerts if "no match" in a], alerts)
        rows.append({"event": "matched", "tick": 106, "sell": "b36-17", "buy": "b36-4"})
        self.assertEqual(f.bench_alerts(f.bench_summary(rows), 107), [])

    def test_scheduled_test_never_seen_on_our_book_alerts(self):
        bench = ev("bench", 17.0, ticks=16)
        c = dict(clock(t_hours=17.05), tick=1000)          # 12 ticks into the test at 15 s
        self.assertEqual(len(f.missed_tests([bench], [], c)), 1)
        seen = [{"bench": "b40", "first": 989, "last": 999, "matched": 2, "dropped": 0}]
        self.assertEqual(f.missed_tests([bench], seen, c), [])
        self.assertEqual(f.missed_tests([bench], [], dict(clock(t_hours=17.01), tick=1000)), [])   # 2 ticks in


class ReviewOutOfHours(Sandbox):
    """Item 9: a duel wave projected outside opening hours never launches, recomputed on every loop."""

    SESSION = {"name": "duel", "kind": "session", "required": True, "gates": {},
               "session": {"event": {"action": "duels"}, "lead_min": 10, "window_min": 120},
               "cmd": ["{python}", "-c", "pass"], "match": ["agent/duel.py", "run"]}

    def test_duel_projected_after_close_does_not_launch(self):
        # Sunday 14:58 at game 21.55: the Final (21.65) projects to 15:04, after the 15:00 close
        c = clock(t_hours=21.55, closes="2026-10-04T15:00:00+02:00")
        with mock.patch.object(f.time, "time", lambda: SUN_0900 + 5 * 3600 + 58 * 60):
            rc, st = self.keep(self.config(self.SESSION), "duel", [c], [FakeChild()], schedule=[FINAL])
        self.assertEqual(self.popen, [])
        self.assertIn("outside opening hours", st["why"])

    def test_duel_inside_hours_launches_in_its_lead_window(self):
        c = clock(t_hours=18.55, closes="2026-10-04T15:00:00+02:00")
        with mock.patch.object(f.time, "time", lambda: SUN_0900 + 2 * 3600 + 50 * 60):
            self.keep(self.config(self.SESSION), "duel", [c], [FakeChild(polls=3, hang=True)], schedule=[DUELS3], sleeps=2)
        self.assertEqual(len(self.popen), 1)


class ReviewChildEnv(Sandbox):
    """Item 10: children get an allowlisted environment, never a key exported in the launching shell."""

    def test_children_get_a_secret_free_environment(self):
        secrets = {"BAZAAR_KEY": "k1", "BROKER_KEY": "bk_2", "GH_TOKEN": "t3", "AWS_SECRET_ACCESS_KEY": "s4"}
        self.keep(self.config(SERVICE, env={"BAZAAR_OPERATOR": "claude-mini"}), "broker", [clock()],
                  [FakeChild(polls=3, hang=True)], sleeps=2, environ=secrets)
        env = self.popen[0].env
        self.assertFalse(set(secrets) & set(env), sorted(env))
        self.assertEqual(env.get("BAZAAR_OPERATOR"), "claude-mini")
        self.assertIn("PATH", env)


class ReviewMissingInput(Sandbox):
    """Item 11: up refuses a process whose input file is missing and names the file."""

    def test_up_refuses_a_missing_input_file(self):
        p = dict(SERVICE, name="duel", params="docs/duel-lab/missing.json")
        rc, out, started = self.up(self.config(p))
        self.assertEqual(started, [])
        self.assertIn("docs/duel-lab/missing.json", out)



# --- third round: fewer capabilities, each fail-closed -----------------------------------------------------------------

class Round3Dealers(Sandbox):
    def test_the_sunday_dealers_are_on_and_up_starts_each_one_that_has_a_step(self):
        """PR #35 and #38 are merged: no dealer is switched off, and none still says it waits for #35."""
        cfg = f.load_config(f.CONFIG)
        dealers = [p for p in cfg["processes"] if p["kind"] == "steps"]
        self.assertEqual({p["name"] for p in dealers}, {"abuela", "chato", "pilar", "picaros"})
        for p in dealers:
            self.assertIsNot(p.get("enabled"), False, p["name"])
            self.assertNotIn("Off:", p.get("note", ""), p["name"])
            # a run is at most 40 ticks = 10 wall min = 20 game min if the clock runs two game hours per wall hour
            self.assertGreaterEqual(p["gates"]["duel_quiet_min"], 20, p["name"])
        _, out, started = self.up(f.CONFIG)
        for p in dealers:
            keeper = [c for c in started if f" keep {p['name']} " in c[-1]]
            if f.pending_steps(p, []):
                self.assertEqual(len(keeper), 1, (p["name"], out))
            else:                                       # every step off: up says so instead of starting an idle keeper
                self.assertRegex(out, rf"skip +{p['name']}: no enabled step")
                self.assertEqual(keeper, [])

    def test_chato_does_not_count_the_other_dealers_runs_as_its_own(self):
        """agent/chato.py runs three dealers (--dealer pilar, --dealer picaros, and Chato itself): Chato's match must
        exclude the other two, or its keeper refuses to start beside their runs and `status` mixes their pids up."""
        procs = {p["name"]: p for p in f.load_config(f.CONFIG)["processes"]}
        lines = ["  51 python3 -u agent/chato.py run --dealer pilar --only sell:RET-09",
                 "  52 python3 -u agent/chato.py run --dealer picaros --only RET-09,RET-10 --cap 62",
                 "  53 python3 -u agent/chato.py run --only SAL-10 --cap 88"]
        chato = procs["chato"]
        self.assertEqual(f.ps_pids(lines, chato["match"], chato["exclude"]), [53])
        self.assertEqual(f.ps_pids(lines, procs["pilar"]["match"], procs["pilar"].get("exclude", [])), [51])
        self.assertEqual(f.ps_pids(lines, procs["picaros"]["match"], procs["picaros"].get("exclude", [])), [52])

    def test_the_sunday_config_has_nothing_open(self):
        """The 08:40 pre-flight greps `plan` for TODO: a `todo` key anywhere in the config prints one."""
        def todos(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.lower().startswith("todo"):
                        yield f"{path}/{k}"
                    yield from todos(v, f"{path}/{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    yield from todos(v, f"{path}[{i}]")
        self.assertEqual(list(todos(f.load_config(f.CONFIG))), [])

    FRAGMENT = Path(__file__).resolve().parent.parent / "docs" / "plans" / "factory-dealer-steps-sunday.json"

    @unittest.skipUnless(FRAGMENT.exists(), "docs/plans/factory-dealer-steps-sunday.json comes with the ladder PR (#69)")
    def test_the_dealer_steps_are_the_ladder_fragment(self):
        """The ladder lane's value-gated steps are pasted into the config as they are (its own test checks the
        fragment against our account; this one checks nobody edited the paste)."""
        frag = json.loads(self.FRAGMENT.read_text())
        procs = {p["name"]: p for p in f.load_config(f.CONFIG)["processes"]}
        for name in ("abuela", "chato", "pilar", "picaros"):
            ours = [(s["label"], s.get("enabled", True), s.get("after_event"), s["cmd"]) for s in procs[name]["steps"]]
            theirs = [(s["label"], s.get("enabled", True), s.get("after_event"), s["cmd"]) for s in frag[name]["steps"]]
            self.assertEqual(ours, theirs, name)
        self.assertEqual(procs["chato"]["exclude"], frag["chato"]["exclude"])
        self.assertEqual(procs["picaros"]["match"], frag["picaros"]["match"])

    def test_exit_zero_without_a_marker_is_retried_then_reported(self):
        cfg = self.config(dict(DEALER, max_attempts=2))
        kids = [FakeChild(), FakeChild(), FakeChild()]          # exit 0, nothing in the log: the duel-lock refusal
        rc, st = self.keep(cfg, "abuela", [clock()], kids, sleeps=10)
        self.assertEqual(len(self.popen), 2)
        self.assertEqual((st["state"], st["done_steps"], st["failed_steps"]), ("failed", [], ["a"]))
        _, problems = self.status(cfg, clock())
        self.assertTrue([x for x in problems if "abuela" in x and "marker" in x], problems)

    def test_a_deal_or_nothing_to_do_marks_the_step_done(self):
        log = self.dealer_log()
        kids = [FakeChild(log=log, writes=[{"event": "run_start", "plan": [{"item": "RET-07"}]},
                                           {"event": "result", "status": "deal"}]),
                FakeChild(log=log, writes=[{"event": "run_start", "plan": []}, {"event": "run_end"}])]
        rc, st = self.keep(self.config(DEALER), "abuela", [clock()], kids, sleeps=10)
        self.assertEqual((rc, st["state"], st["done_steps"]), (0, "done", ["a", "b"]))


class Round3Matching(unittest.TestCase):
    def test_basename_and_mode_whatever_the_path_form(self):
        lines = ["  31 /usr/bin/python3 broker.py run --policy stall",
                 "  32 /bin/bash -c cd agent; while true; do python3 broker.py run; sleep 10; done",
                 "  33 python3 -m broker run",
                 "  34 python3 /Users/x/bazaar/agent/broker.py plan --book b.json",
                 "  35 python3 -u agent/chato.py run --dealer=pilar --only sell:44"]
        self.assertEqual(f.ps_pids(lines, ["agent/broker.py", "run"]), [31, 32, 33])
        self.assertEqual(f.ps_pids(lines, ["agent/chato.py", "pilar"]), [35])
        self.assertEqual(f.ps_pids(lines, ["agent/chato.py", "run"], ["pilar"]), [])

    def test_the_scanner_never_opens_a_file(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "run.sh").write_text("#!/bin/bash\npython3 agent/broker.py run\n")
        (tmp / ".env").write_text("BAZAAR_KEY=never-read\n")
        lines = [f"  41 /bin/bash {tmp / 'run.sh'}", f"  42 /bin/bash -c source {tmp / '.env'}; python3 x.py",
                 f"  43 /bin/zsh {tmp / '.env'}"]

        def opened(*a, **k):
            raise AssertionError(f"the scanner opened a file: {a[:1]}")
        with mock.patch("builtins.open", opened), mock.patch("io.open", opened), mock.patch("os.open", opened), \
                mock.patch.object(Path, "read_text", opened), mock.patch.object(Path, "read_bytes", opened):
            f.ps_pids(lines, ["agent/broker.py", "run"])


class Round3Bus(Sandbox):
    def test_a_claim_held_on_another_machine_refuses(self):
        self.board = {"broker": ("thiago", "vm")}
        rc, out, started = self.up(self.config(SERVICE))
        self.assertEqual(started, [])
        self.assertIn("vm", out)
        self.assertNotIn(("claim", "broker"), self.bus_calls)

    def test_a_claim_held_on_this_machine_is_ours(self):
        self.board = {"broker": ("thiago", "mini")}
        cfg = self.config(SERVICE)
        data = json.loads(cfg.read_text())
        cfg.write_text(json.dumps({**data, "bus": {"session": "s", "where": "mini"}}))
        rc, out, started = self.up(cfg)
        self.assertEqual(len(started), 1, out)

    def test_an_unreadable_board_fails_closed(self):
        self.board = None
        rc, out, started = self.up(self.config(SERVICE))
        self.assertEqual(started, [])


class Round3Keeper(Sandbox):
    def test_a_missing_input_stops_the_keeper_and_is_reported(self):
        cfg = self.config(dict(SERVICE, params="docs/gone.json"))
        rc, st = self.keep(cfg, "broker", [clock()], [FakeChild()])
        self.assertNotEqual(rc, "looping")
        self.assertEqual((st["state"], self.popen), ("failed", []))
        _, problems = self.status(cfg, clock())
        self.assertTrue([x for x in problems if "docs/gone.json" in x], problems)

    def test_disabled_on_reload_stops_before_any_launch(self):
        rc, st = self.keep(self.config(dict(SERVICE, enabled=False)), "broker", [clock()], [FakeChild()])
        self.assertEqual(self.popen, [])
        self.assertNotEqual(rc, "looping")

    def test_status_reports_a_disabled_entry_that_still_runs(self):
        cfg = self.config(dict(SERVICE, enabled=False))
        self.hold("broker")
        self.ps = [f"  {os.getpid()} python3 -u agent/broker.py run --policy stall"]
        f.write_json(f.STATE / "broker.json", {"date": f.today(), "child_pid": os.getpid(), "state": "running"})
        _, problems = self.status(cfg, clock())
        self.assertTrue([x for x in problems if "disabled" in x], problems)


class Round3DuelFreshness(Sandbox):
    DUEL = {k: v for k, v in next(p for p in f.load_config(f.CONFIG)["processes"] if p["name"] == "duel").items()
            if k != "params"}                                   # the real Sunday entry

    def setup_duel(self, log_age_s, lock):
        cfg = self.config(self.DUEL)
        self.hold("duel")
        self.ps = [f"  {os.getpid()} python3 -u agent/duel.py run --params p.json"]
        f.write_json(f.STATE / "duel.json", {"date": f.today(), "child_pid": os.getpid(), "state": "running",
                                              "started": time.time() - 3600})
        log = self.tmp / "logs" / "duel" / f"{f.today()}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("{}\n")
        os.utime(log, (time.time() - log_age_s, time.time() - log_age_s))
        if lock:
            f.LOCK.parent.mkdir(parents=True, exist_ok=True)
            f.LOCK.write_text(f"{time.time() + 30}\n")
        return cfg

    def test_nothing_logged_since_the_wave_began_is_stale(self):
        cfg = self.setup_duel(log_age_s=600, lock=False)        # last line 10 min ago, wave began 3 min ago
        _, problems = self.status(cfg, clock(t_hours=18.70), schedule=[DUELS3])
        self.assertTrue([x for x in problems if x.startswith("duel") and "down" not in x], problems)

    def test_a_live_lock_with_a_silent_log_is_stale(self):
        cfg = self.setup_duel(log_age_s=150, lock=True)         # 150 s > 8 ticks of 15 s
        _, problems = self.status(cfg, clock(t_hours=19.5), schedule=[DUELS3])
        self.assertTrue([x for x in problems if x.startswith("duel") and "down" not in x], problems)

    def test_quiet_after_our_duels_end_is_fine(self):
        cfg = self.setup_duel(log_age_s=900, lock=False)        # wave began 51 min ago, our duels done
        _, problems = self.status(cfg, clock(t_hours=19.5), schedule=[DUELS3])
        self.assertEqual([x for x in problems if "duel" in x], [])


class Round3ClockAndNotify(Sandbox):
    def test_gates_fail_closed_on_an_incomplete_clock(self):
        self.assertFalse(f.check_gates({}, {}, [], None, SUN_0900)[0])
        self.assertFalse(f.check_gates({}, {"doors": "open"}, [], None, SUN_0900)[0])
        self.assertFalse(f.check_gates({}, {"paused": False}, [], None, SUN_0900)[0])
        self.assertTrue(f.check_gates({}, {"doors": "open", "paused": False}, [], None, SUN_0900)[0])

    def test_one_incident_notifies_once_while_its_numbers_change(self):
        polls = [["broker log silent for 70 s (4 ticks at 15 s)"], ["broker log silent for 130 s (4 ticks at 15 s)"],
                 ["broker log silent for 190 s (4 ticks at 15 s)"], ["broker log silent for 250 s (4 ticks at 15 s)",
                                                                     "duel is down"]]
        sent, n = [], [0]

        def status_once(cfg):
            n[0] += 1
            if n[0] > len(polls):
                raise Stop
            return [], polls[n[0] - 1]
        with mock.patch.object(f, "status_once", status_once), mock.patch.object(f, "notify", lambda c, t: sent.append(t)), \
                mock.patch.object(f.time, "sleep", lambda s: None), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(Stop):
                f.cmd_status(self.config(SERVICE), True, 60)
        self.assertEqual(len(sent), 2, sent)          # the incident, then the new one (duel down)


if __name__ == "__main__":
    unittest.main()
