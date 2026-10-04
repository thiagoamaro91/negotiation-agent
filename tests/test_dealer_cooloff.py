"""A dealer that is cooling off is waited out, not given up on (agent/dealer_client.py wait_out_cooloff, used by
agent/chato.py and agent/abuela.py). No key, no network, the fake server under the bots' real client.

The Sunday Picaros steps buy one card each. If a card is bought and the next open is refused with `cooloff` (and its
until_tick), the bot used to stop with exit 0 and no completion marker: the factory counts that as an attempt, three of them
fail the keeper for good, and the second card never runs. Now the run waits, pause-safe, until the tick has passed
until_tick, retries the open once, and logs cooloff_wait; a cooloff longer than --max-wait-ticks (default 120), past --until,
without an until_tick, or met again on the retry ends with exit 8 and a line saying so.

Also here: a rate_limited read (the per-decision /api/me) is backed off and retried by the client, so several bots starting
together do not lose a decision to the key's 20-request burst.

    python3 -m unittest discover -s tests
"""
import time
import unittest

from dealer_fakes import FakeServer, abuela, chato, run_main

import dealer_client as dc

LAT = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7, "CHA": 0.5}
COOLOFF = (409, "cooloff", "cooling off after tricks")


def cooloff(until_tick):
    return COOLOFF + ({"until_tick": until_tick},)


def picaros(**kw):
    kw.setdefault("max_requests", 20000)
    return FakeServer(dealer="picaros", side="buy", item="RET-10", opening=59, opening_final=True, expiry=100, cash=1000,
                      cards=[{"id": "RET-10", "rarity": "rare", "name": "RET-10", "book": 70}], values={"RET-10": 63.0},
                      affinity=LAT, **kw)


ARGS = ["run", "--dealer", "picaros", "--only", "RET-10", "--cap", "62", "--anchor", "40", "--step", "2", "--max-deals", "1",
        "--max-rounds", "6"]


def open_ticks(srv):
    return [t for (t, m, p) in srv.requests if m == "POST" and p == "/api/threads"]


class TestChatoCooloff(unittest.TestCase):
    def test_the_open_is_retried_once_the_until_tick_has_passed_and_the_deal_is_made(self):
        srv = picaros()
        srv.inject["open"] = [cooloff(112)]
        code, out, run, _ = run_main(chato, ARGS, server=srv)
        self.assertIsNone(code, out)                                   # exit 0, a deal
        self.assertEqual([p for _, p, _ in srv.accepted], [59], out)
        (w,) = run.named("cooloff_wait")
        self.assertEqual((w["until_tick"], w["result"], w["tick"]), (112, "waited", 100))
        self.assertEqual(w["waited"], 13)                              # ticks 101 to 113
        first, second = open_ticks(srv)
        self.assertEqual(first, 100)
        self.assertGreater(second, 112)                                # never before the cooloff is over

    def test_the_wait_is_pause_safe(self):
        srv = picaros(pause=(20.0, 400.0))                             # the game pauses while we wait: no tick, no round
        srv.inject["open"] = [cooloff(106)]
        code, out, run, _ = run_main(chato, ARGS, server=srv)
        self.assertIsNone(code, out)
        (w,) = run.named("cooloff_wait")
        self.assertEqual(w["waited"], 7)                               # only confirmed ticks count (101 to 107)
        self.assertGreater(open_ticks(srv)[1], 106)

    def test_a_cooloff_longer_than_the_bound_ends_with_its_own_status(self):
        srv = picaros()
        srv.inject["open"] = [cooloff(600)]
        code, out, run, _ = run_main(chato, ARGS + ["--max-wait-ticks", "20"], server=srv)
        self.assertEqual(code, dc.EXIT_COOLOFF, out)
        self.assertEqual(code, 8)
        self.assertEqual(open_ticks(srv), [100])                       # no second open, no waiting out 500 ticks
        (w,) = run.named("cooloff_wait")
        self.assertEqual((w["result"], w["waited"], w["max_wait_ticks"]), ("too_long", 0, 20))
        self.assertEqual(run.named("stop")[0]["code"], "cooloff_timeout")
        self.assertIn("cooling off until tick 600", out)
        self.assertIn("--max-wait-ticks 20", out)

    def test_a_second_cooloff_on_the_retry_is_the_operators_call_not_a_loop(self):
        srv = picaros()
        srv.inject["open"] = [cooloff(105), cooloff(130)]
        code, out, run, _ = run_main(chato, ARGS, server=srv)
        self.assertEqual(code, dc.EXIT_COOLOFF, out)
        self.assertEqual(len(open_ticks(srv)), 2)                      # one retry, never a third open
        self.assertEqual([w["result"] for w in run.named("cooloff_wait")], ["waited", "cooloff_again"])

    def test_a_cooloff_without_an_until_tick_cannot_be_waited_out(self):
        srv = picaros()
        srv.inject["open"] = [COOLOFF]
        code, out, run, _ = run_main(chato, ARGS, server=srv)
        self.assertEqual(code, dc.EXIT_COOLOFF, out)
        self.assertEqual(run.named("cooloff_wait")[0]["result"], "until_tick_unknown")
        self.assertEqual(open_ticks(srv), [100])

    def test_until_tick_inside_a_details_object_is_read_too(self):
        srv = picaros()
        srv.inject["open"] = [COOLOFF + ({"details": {"until_tick": 104}},)]
        code, out, run, _ = run_main(chato, ARGS, server=srv)
        self.assertIsNone(code, out)
        self.assertEqual(run.named("cooloff_wait")[0]["until_tick"], 104)

    def test_other_refusals_still_stop_quietly_as_before(self):
        srv = picaros()
        srv.inject["open"] = [(409, "persona_quota", "hourly limit")]
        code, out, run, _ = run_main(chato, ARGS, server=srv)
        self.assertIsNone(code, out)
        self.assertEqual(run.named("cooloff_wait"), [])
        self.assertEqual(run.named("stop")[0]["code"], "persona_quota")

    def test_the_flags_are_validated(self):
        import contextlib
        import io
        for bad in (["--max-wait-ticks", "0"], ["--until", "25:00"], ["--until", "noon"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    chato.parse_args(["run", "--only", "RET-10", "--dealer", "picaros"] + bad)
        args = chato.parse_args(["run", "--only", "RET-10", "--dealer", "picaros"])
        self.assertEqual((args.max_wait_ticks, args.until), (120, ""))


class TestAbuelaCooloff(unittest.TestCase):
    def test_abuela_waits_and_retries_too(self):
        srv = FakeServer(dealer="abuela", side="buy", item="RET-06", opening=22, opening_final=True, expiry=100, cash=1000,
                         cards=[{"id": "RET-06", "rarity": "uncommon", "name": "RET-06", "book": 25}],
                         values={"RET-06": 22.5}, affinity=LAT, max_requests=20000)
        srv.inject["open"] = [cooloff(110)]
        code, out, run, _ = run_main(abuela, ["run", "--only", "RET-06", "--cap", "22", "--reserve", "20", "--max-deals", "1"],
                                     server=srv)
        self.assertIsNone(code, out)
        self.assertEqual([p for _, p, _ in srv.accepted], [22], out)
        self.assertEqual(run.named("cooloff_wait")[0]["result"], "waited")
        self.assertGreater(open_ticks(srv)[1], 110)

    def test_abuela_ends_with_exit_8_when_the_wait_is_too_long(self):
        srv = FakeServer(dealer="abuela", side="buy", item="RET-06", opening=22, opening_final=True, expiry=100, cash=1000,
                         cards=[{"id": "RET-06", "rarity": "uncommon", "name": "RET-06", "book": 25}],
                         values={"RET-06": 22.5}, affinity=LAT, max_requests=20000)
        srv.inject["open"] = [cooloff(900)]
        code, out, run, _ = run_main(abuela, ["run", "--only", "RET-06", "--cap", "22", "--reserve", "20", "--max-deals", "1"],
                                     server=srv)
        self.assertEqual(code, 8, out)
        self.assertEqual(open_ticks(srv), [100])


class Clockwork:
    """A client stub: read_clock and wait_tick walk a tick counter; nothing sleeps."""

    def __init__(self, tick=100):
        self.tick = tick
        self.waits = 0

    def read_clock(self):
        return {"tick": self.tick}

    def wait_tick(self):
        self.waits += 1
        self.tick += 1
        return {"tick": self.tick}


class TestWaitOutCooloff(unittest.TestCase):
    def go(self, until_tick, b=None, retry=None, until_wall=None, max_wait=120):
        events = []
        b = b or Clockwork()
        retry = retry or (lambda: {"result": "deal"})
        res, stop = dc.wait_out_cooloff(b, {"result": "refused", "code": "cooloff", "until_tick": until_tick}, retry,
                                        lambda e, **d: events.append((e, d)), max_wait, until_wall, item="RET-10")
        return b, res, stop, events

    def test_it_waits_until_the_tick_has_passed_then_retries_once(self):
        b, res, stop, events = self.go(105)
        self.assertEqual((res, stop, b.waits, b.tick), ({"result": "deal"}, None, 6, 106))
        self.assertEqual(events[-1][1]["result"], "waited")

    def test_the_bound_counts_ticks_left_not_the_calendar(self):
        b, res, stop, events = self.go(219, max_wait=120)               # 120 ticks left: allowed
        self.assertIsNone(stop)
        b, res, stop, events = self.go(220, max_wait=120)               # 121: refused before waiting
        self.assertEqual((stop[0], b.waits), (dc.EXIT_COOLOFF, 0))

    def test_until_a_wall_time_in_the_past_stops_without_waiting(self):
        retried = []
        b, res, stop, events = self.go(105, until_wall=time.time() - 1, retry=lambda: retried.append(1) or {"result": "deal"})
        self.assertEqual((stop[0], b.waits, retried), (dc.EXIT_COOLOFF, 0, []))
        self.assertEqual(events[-1][1]["result"], "past_until")

    def test_a_lost_clock_ends_the_wait(self):
        class Lost(Clockwork):
            def wait_tick(self):
                self.waits += 1
                return {}
        b, res, stop, events = self.go(105, b=Lost())
        self.assertEqual((stop[0], b.waits), (dc.EXIT_COOLOFF, dc.MAX_FAILED_WAITS))
        self.assertEqual(events[-1][1]["result"], "clock_lost")

    def test_until_epoch(self):
        self.assertIsNone(dc.until_epoch(None))
        self.assertIsNone(dc.until_epoch(""))
        now = time.mktime((2026, 10, 4, 10, 0, 0, 0, 0, -1))
        self.assertEqual(dc.until_epoch("10:45", now) - now, 45 * 60)
        self.assertEqual(dc.until_epoch("09:00", now) - now, -3600)


class TestReadBackoff(unittest.TestCase):
    """The per-decision /api/me is a GET: the kit client backs off on rate_limited (0.25 s, 0.5 s, 0.75 s) and retries up to
    three times, so a burst from several bots starting together costs a short pause, not a decision."""

    def test_a_rate_limited_me_is_retried_after_a_pause(self):
        srv = FakeServer(dealer="chato", opening=25)
        srv.inject["me"] = [(429, "rate_limited"), (429, "rate_limited")]
        with srv.serving():
            me = srv.client(chato).me()
        self.assertIn("cash", me)
        self.assertEqual(len([r for r in srv.requests if r[2] == "/api/me"]), 3)
        self.assertGreaterEqual(srv.vc.now, 0.25 + 0.5)               # virtual seconds slept between the tries


if __name__ == "__main__":
    unittest.main()
