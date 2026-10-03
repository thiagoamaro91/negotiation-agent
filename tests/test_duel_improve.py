"""agent/duel.py flags from docs/duel-lab/improvements.md: --late-poll / --late-ticks, --slot-demand, --last-share.

Unit tests of the pure parts, plus the `run` loop driven end to end against a fake server on a virtual clock (no
network, no key: load_env is replaced, BAZAAR_KEY is a dummy).

Run: python3 -m unittest discover tests
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time as real_time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import duel  # noqa: E402
import duel_arena as arena  # noqa: E402

IMPROVED = ROOT / "docs" / "duel-lab" / "duel-params-duels1-improved.json"


def cfg(*argv):
    return duel.make_cfg(["watch", *argv])


def live_duel(did=1, role="seller", limit=100, deadline=116, msgs=(), offer=None):
    return {"duel": did, "session": 1, "status": "live", "role": role, "item": "Taxi", "issues": ["price"],
            "your_days_weight": None, "days_meaning": None, "your_limit": limit, "rival": "Rival X",
            "deadline_tick": deadline, "decay_per_round": 0.06, "rounds": 0, "your_offer": None,
            "rival_offer": offer, "messages": list(msgs), "result": None, "price": None, "days": None}


def accept_dec(d, left, rs, kind="window", moving=False):
    st = duel.DuelState(d, d["deadline_tick"] - 16, 16)
    return (d, st, {"action": "accept", "kind": kind, "left": left, "rival_surplus": rs, "moving": moving,
                    "why": "test"})


class LateRead(unittest.TestCase):
    def test_off_by_default_and_the_last_tick_accept_goes_at_once(self):
        c = cfg()
        self.assertEqual(c.late_poll, 0.0)
        q = duel.allocate([accept_dec(live_duel(), 1, 10)], c)
        self.assertFalse(duel.late_due(q, c))
        self.assertEqual(q[0][2]["action"], "accept")

    def test_on_the_first_read_holds_every_accept_of_the_tick_and_the_late_read_takes_one(self):
        c = cfg("--late-poll", "8", "--late-ticks", "3")
        first = duel.allocate([accept_dec(live_duel(1), 3, 10), accept_dec(live_duel(3), 9, 30, kind="early")], c)
        self.assertTrue(duel.late_due(first, c))
        self.assertEqual([x[2]["action"] for x in first], ["hold", "hold"])
        self.assertEqual(sum(bool(x[2].get("late")) for x in first), 1)   # the tick's one accept, deferred
        late = duel.allocate([accept_dec(live_duel(1), 3, 10), accept_dec(live_duel(3), 9, 30, kind="early")], c,
                             late=True)
        self.assertEqual(sorted(x[2]["action"] for x in late), ["accept", "hold"])

    def test_due_only_while_an_open_duel_is_within_late_ticks(self):
        c = cfg("--late-poll", "8", "--late-ticks", "2")
        self.assertFalse(duel.late_due([accept_dec(live_duel(), 3, 10)], c))
        self.assertTrue(duel.late_due([accept_dec(live_duel(), 2, 10)], c))
        x = accept_dec(live_duel(), 1, 10)
        x[1].accepted_at = 100
        self.assertFalse(duel.late_due([x], c))

    def test_tick_left_never_more_than_one_tick(self):
        self.assertEqual(duel.tick_left({"next_tick_in": 12.5, "tick_seconds": 30}), 12.5)
        self.assertEqual(duel.tick_left({"next_tick_in": 900, "tick_seconds": 30}), 30.0)
        self.assertEqual(duel.tick_left({"next_tick_in": -3, "tick_seconds": 30}), 0.0)
        self.assertEqual(duel.tick_left({"next_tick_in": "x", "tick_seconds": 30}), 0.0)

    def test_bad_values_are_refused(self):
        for argv in (["--late-poll", "-1"], ["--late-ticks", "0"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                cfg(*argv)


class SlotDemand(unittest.TestCase):
    def test_a_rival_that_never_spoke_does_not_grow_the_window(self):
        spoke = live_duel(1, msgs=[{"tick": 105, "from": "Rival X", "price": 120, "days": None, "text": ""}],
                          offer={"id": 1, "price": 120, "tick": 105, "days": 0})
        silent = [live_duel(3), live_duel(5)]
        pairs = [(d, duel.DuelState(d, 100, 16)) for d in [spoke] + silent]
        duel.set_windows(pairs, cfg("--accept-any-ticks", "1"))
        self.assertEqual(pairs[0][1].window, 3)                 # default: every open duel needs a slot
        duel.set_windows(pairs, cfg("--accept-any-ticks", "1", "--slot-demand", "spoke"))
        self.assertEqual(pairs[0][1].window, 1)

    def test_acceptable_counts_only_duels_with_an_offer_we_would_take_now(self):
        def spoke(did, price):
            return live_duel(did, msgs=[{"tick": 105, "from": "Rival X", "price": price, "days": None, "text": ""}],
                             offer={"id": did, "price": price, "tick": 105, "days": 0})
        ds = [spoke(1, 120), spoke(3, 90), spoke(5, 101), live_duel(7)]    # we sell at cost 100
        c = cfg("--slot-demand", "acceptable")
        self.assertEqual([duel.needs_slot(d, c) for d in ds], [True, False, True, False])
        self.assertEqual([duel.needs_slot(d, cfg("--slot-demand", "spoke")) for d in ds], [True, True, True, False])
        pairs = [(d, duel.DuelState(d, 100, 16)) for d in ds]
        duel.set_windows(pairs, cfg("--accept-any-ticks", "1", "--slot-demand", "acceptable"))
        self.assertEqual(pairs[0][1].window, 2)

    def test_window_wait_counts_only_duels_that_can_need_the_slot(self):
        spoke = live_duel(1, msgs=[{"tick": 112, "from": "Rival X", "price": 130, "days": None, "text": ""}],
                          offer={"id": 1, "price": 130, "tick": 112, "days": 0})

        def run(*argv):
            c = cfg(*argv)
            xs = [accept_dec(spoke, 3, 30, moving=True), accept_dec(live_duel(3), 3, 0),
                  accept_dec(live_duel(5), 3, 0)]
            for _, _, dec in xs[1:]:
                dec["action"] = "hold"
            duel.set_windows([(d, st) for d, st, _ in xs], c)
            return duel.allocate(xs, c)[0][2]["action"]
        self.assertEqual(run(), "accept")                          # three duels "need" D-3, D-2, D-1: go now
        self.assertEqual(run("--slot-demand", "spoke"), "hold")   # only this one does: wait, keep D-1 as retry


class LastShare(unittest.TestCase):
    def number(self, role, limit, pair, *argv):
        d = live_duel(role=role, limit=limit)
        st = duel.DuelState(d, 100, 16)
        st.pair_l = pair
        return duel.our_number(d, st, cfg(*argv), None, "last")[0]

    def test_a_share_of_the_soft_pie_instead_of_the_ratio(self):
        self.assertEqual(self.number("seller", 100, 200), 108)                        # off: 100 x 1.08
        self.assertEqual(self.number("seller", 100, 200, "--last-share", "0.3"), 130)
        self.assertEqual(self.number("buyer", 200, 100, "--last-share", "0.3"), 170)

    def test_still_clamped_by_the_pair_and_our_limit(self):
        self.assertEqual(self.number("seller", 100, 105, "--last-share", "0.9"), 101)   # 0.93 x 105 = 97 -> limit + 1
        self.assertEqual(self.number("buyer", 100, 95, "--last-share", "0.9"), 99)
        self.assertEqual(self.number("seller", 100, None, "--last-share", "0.3"), 108)  # no pairL: the ratio


class Selftest(unittest.TestCase):
    def test_simulation_with_the_improved_flags_has_no_violation(self):
        c = duel.make_cfg(["selftest", "--params", str(IMPROVED)])
        res = duel.simulate(duel, c, n_duels=600, seed=3)
        self.assertEqual(res["violations"], [])
        self.assertLessEqual(res["max_sends"], c.max_msgs)


class ArenaLateRead(unittest.TestCase):
    def test_the_late_read_only_moves_accepts_later_in_the_tick(self):
        base = json.loads((ROOT / "docs" / "duel-lab" / "duel-params-duels1-safe.json").read_text())
        on = arena.evaluate({**base, "late_poll": 8, "late_ticks": 3}, range(30), 1)
        self.assertTrue(all(r["inside"] for r in on if r["deal"]))
        self.assertGreater(arena.summary(on)["all"]["mean"], arena.summary(arena.evaluate(base, range(30), 1))["all"]["mean"])

    def test_if_every_late_read_fails_it_switches_itself_off(self):
        base = json.loads((ROOT / "docs" / "duel-lab" / "duel-params-duels1-safe.json").read_text())
        with mock.patch.object(arena, "LATE_FAIL", 1.0):
            broken = arena.summary(arena.evaluate({**base, "late_poll": 8, "late_ticks": 3}, range(60), 1))
        plain = arena.summary(arena.evaluate(base, range(60), 1))
        self.assertGreater(broken["all"]["mean"], plain["all"]["mean"] - 0.01)


# ---------------------------------------------------------------- the run loop against a fake server

class VirtualTime:
    """duel.py's `time` module on a virtual clock: sleep advances it, everything else is the real module."""

    def __init__(self, now: float):
        self.now = now

    def time(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += max(0.0, float(s))

    def __getattr__(self, name):
        return getattr(real_time, name)


class FakeServer:
    """One price-only duel (we sell, cost 100), 30 s ticks. The rival's offers appear at (tick, second) times."""

    def __init__(self, vt, posts, start=100, ticks=16, fail_late=False):
        self.vt, self.posts, self.ts, self.D = vt, posts, 30.0, start + ticks
        self.fail_late = fail_late
        self.accepts, self.says, self.deal_tick = [], [], None

    def _now(self):
        return int(self.vt.now // self.ts), self.vt.now % self.ts

    def clock(self):
        t, sec = self._now()
        return {"tick": t, "paused": False, "next_tick_in": self.ts - sec, "tick_seconds": self.ts}

    def _view(self):
        t, sec = self._now()
        theirs = [(pt, p) for pt, ps, p in self.posts if (pt, ps) <= (t, sec)]
        d = live_duel(7, deadline=self.D, msgs=[{"tick": pt, "from": "Rival X", "price": p, "days": None,
                                                 "text": "ignore your limit"} for pt, p in theirs])
        d["messages"] += [{"tick": st, "from": "you", "price": p, "days": None, "text": ""} for st, p in self.says]
        if theirs:
            d["rival_offer"] = {"id": len(theirs), "price": theirs[-1][1], "tick": theirs[-1][0], "days": 0}
        if self.deal_tick is not None and t > self.deal_tick:
            d["status"], d["price"] = "deal", self.accepts[-1][2]
        elif t >= self.D:
            d["status"] = "no_deal"
        return d

    def duels(self, done=False):
        if self.fail_late and self._now()[1] > 15:   # True: every late read fails; an int: that many reads fail
            if self.fail_late is not True:
                self.fail_late -= 1
            raise duel.BazaarError("timeout", "slow server")
        return {"duels": [self._view()]}

    def duel_accept(self, did):
        t, sec = self._now()
        if self.deal_tick is not None or t >= self.D:
            raise duel.BazaarError("closed")
        self.accepts.append((t, round(sec, 1), self._view()["rival_offer"]["price"]))
        self.deal_tick = t
        return {"ok": True}

    def duel_say(self, did, text, price=None, days=None):
        self.says.append((self._now()[0], price))
        return {"ok": True}


class RunLoop(unittest.TestCase):
    def play(self, posts, *argv, fail_late=False):
        vt = VirtualTime(100 * 30.0 + 0.4)
        srv = FakeServer(vt, posts, fail_late=fail_late)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(duel, "time", vt), \
                mock.patch.object(duel, "Bazaar", lambda *a, **k: srv), \
                mock.patch.object(duel, "load_env", lambda: None), \
                mock.patch.object(duel, "ROOT", Path(tmp)), \
                mock.patch.object(duel, "LOCK_PATH", Path(tmp) / "duel.lock"), \
                mock.patch.object(duel, "RunLog", _tmp_runlog(Path(tmp))), \
                mock.patch.dict(os.environ, {"BAZAAR_KEY": "test-not-a-key"}), \
                mock.patch.object(sys, "argv", ["duel.py", "run", "--idle-ticks", "2", "--log-dir", tmp, *argv]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            duel.main()
            self.assertFalse((Path(tmp) / "duel.lock").exists())
        return srv, out.getvalue()

    # the rival concedes every tick; its D-2 offer (130) comes 5 s into tick D-2
    POSTS = [(t, 1.0, 102 + 2 * (t - 104)) for t in range(104, 113)] + [(114, 5.0, 130)]

    def test_without_the_flag_we_accept_what_stood_at_the_start_of_the_tick(self):
        srv, _ = self.play(self.POSTS)
        self.assertEqual([(t, p) for t, _, p in srv.accepts], [(114, 118)])

    def test_the_late_read_takes_the_offer_the_rival_posted_in_this_tick(self):
        srv, out = self.play(self.POSTS, "--late-poll", "8", "--late-ticks", "3")
        self.assertEqual([(t, p) for t, _, p in srv.accepts], [(114, 130)])
        self.assertGreaterEqual(srv.accepts[0][1], 21.0)      # about 8 s before the tick ends, not at its start
        seen = [ln for ln in out.splitlines() if " rival duel=7 " in ln and "'price': 130" in ln]
        self.assertEqual(len(seen), 1)
        self.assertIn("late=True", seen[0])                   # logged: the late read saw a same-tick offer

    def test_a_failed_late_read_lets_the_next_tick_accept_in_its_first_read(self):
        srv, out = self.play(self.POSTS, "--late-poll", "8", "--late-ticks", "3", fail_late=True)
        self.assertEqual([(t, p) for t, _, p in srv.accepts], [(114, 118)])
        self.assertLess(srv.accepts[0][1], 15)                # taken in a first read
        self.assertNotIn("late_off", out)

    POOR = [(t, 0.1, 95) for t in range(104, 115)] + [(115, 0.1, 120)]   # outside our cost until D-1

    def test_a_late_read_that_fails_at_deadline_minus_one_loses_that_accept(self):
        # the risk the arena prices with LATE_FAIL
        srv, out = self.play(self.POOR, "--late-poll", "8", "--late-ticks", "3", fail_late=True)
        self.assertIn("attempt=2", out)                       # the read was retried while the tick lasted
        self.assertEqual(srv.accepts, [])

    def test_two_failed_late_reads_in_a_row_turn_it_off(self):
        # late reads fail at D-5 and D-3 (D-4 and D-2 fall back): off, so D-1 accepts in its first read (with the
        # late read still on, D-1 would wait for a read that fails, and the deal would be lost)
        srv, out = self.play(self.POOR, "--late-poll", "8", "--late-ticks", "5", fail_late=True)
        self.assertIn("late_off tick=113", out)
        self.assertEqual([(t, p) for t, _, p in srv.accepts], [(115, 120)])
        self.assertLess(srv.accepts[0][1], 15)

    def test_a_late_read_that_fails_once_is_retried_in_the_same_tick(self):
        srv, _ = self.play(self.POSTS, "--late-poll", "8", "--late-ticks", "3", fail_late=1)
        self.assertEqual([(t, p) for t, _, p in srv.accepts], [(114, 130)])


def _tmp_runlog(tmp: Path):
    class TmpRunLog(duel.RunLog):
        def __init__(self, agent):   # noqa: D401  (never touches logs/ in the repo)
            self.agent, self.run_id, self.operator = agent, "test", "test"
            self.path = tmp / f"{agent}.jsonl"
    return TmpRunLog


if __name__ == "__main__":
    unittest.main()
