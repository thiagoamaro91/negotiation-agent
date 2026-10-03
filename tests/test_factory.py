"""Sunday factory: schedule to wall time, gates, command rendering, staleness, the Market Test watch, double starts.

    python3 -m unittest discover tests
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

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
        self.assertEqual(argv[argv.index("--idle-ticks") + 1], "480")          # 120 min at 15 s

    def test_dealer_flags_are_explicit(self):
        for p in self.CFG["processes"]:
            if p["kind"] != "steps":
                continue
            for s in p["steps"]:
                for flag in ("--only", "--reserve" if "pilar" not in s["cmd"] else "--floor", "--max-deals"):
                    self.assertIn(flag, s["cmd"], (p["name"], s["label"]))
                if "agent/chato.py" in s["cmd"]:
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
        rows = [book(t) for t in range(441, 456)] + [{"event": "dropped", "tick": t} for t in (442, 447, 447)]
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
        rows.append({"event": "matched", "tick": 107})
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

    def test_ps_matching_finds_bots_and_ignores_shells_agents_and_keepers(self):
        self.assertEqual(f.ps_pids(self.PS, ["agent/broker.py", "run"]), [101])
        self.assertEqual(f.ps_pids(self.PS, ["agent/chato.py", "pilar"]), [102])
        self.assertEqual(f.ps_pids(self.PS, ["agent/chato.py", "run"], ["pilar"]), [103])
        self.assertEqual(f.ps_pids(self.PS, ["agent/duel.py", "run"]), [])
        self.assertEqual(f.ps_pids(self.PS, ["agent/abuela.py", "run"]), [])

    def test_refuses_a_second_start(self):
        self.assertIn("window", f.refuse_reason("broker", {"broker"}, False, []))
        self.assertIn("keeper", f.refuse_reason("broker", set(), True, []))
        self.assertIn("pid 101", f.refuse_reason("broker", set(), False, [101]))
        self.assertIsNone(f.refuse_reason("broker", {"duel"}, False, []))

    def test_steps_already_done_or_disabled_are_not_rerun(self):
        p = {"steps": [{"label": "a", "cmd": []}, {"label": "b", "enabled": False, "cmd": []}, {"label": "c", "cmd": []}]}
        self.assertEqual([s["label"] for s in f.pending_steps(p, ["a"])], ["c"])


if __name__ == "__main__":
    unittest.main()
