"""agent/duel.py for Duels III and the Final: the F4 flag (--last-while-moving) and the params file the Sunday
factory starts the duel bot with (docs/duel-lab/duel-params-duels3.json).

No network, no key. Run: python3 -m unittest discover tests
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import duel  # noqa: E402


def cfg(*argv):
    return duel.make_cfg(["watch", "--last-chance-ticks", "4", *argv])


def conceding(role="buyer", limit=96, deadline=116, prices=(105, 103, 101, 99, 97, 96, 94, 92, 90, 88, 86, 84, 83),
              day=None):
    """Duels II 5905: a rival that conceded every tick and ended 3 P outside our limit; we never spoke."""
    two = day is not None
    msgs = [{"tick": deadline - 16 + i, "from": "Rival X", "text": "", "price": p, "days": day}
            for i, p in enumerate(prices)]
    last = msgs[-1]
    return {"duel": 1, "session": 4, "status": "live", "role": role, "item": "Taxi",
            "issues": ["price", "days"] if two else ["price"], "your_days_weight": 3.23 if two else None,
            "days_meaning": "each delivery day costs you this much cash" if two else None, "your_limit": limit,
            "rival": "Rival X", "deadline_tick": deadline, "decay_per_round": 0.1, "rounds": 0, "your_offer": None,
            "rival_offer": {"id": len(msgs), "price": last["price"], "tick": last["tick"], "days": day or 0},
            "messages": msgs, "result": None, "price": None, "days": None}


class LastWhileMoving(unittest.TestCase):
    def test_off_a_conceding_rival_outside_our_limit_never_hears_from_us(self):
        d = conceding(prices=tuple(range(110, 98, -1)))                 # still moving at tick 111, 99 > 96
        dec = duel.decide(d, duel.DuelState(d, 100, 16), 113, cfg())
        self.assertEqual(dec["action"], "hold")
        self.assertIn("rival moved toward us", dec["why"])

    def test_on_it_gets_our_last_chance(self):
        d = conceding(prices=tuple(range(110, 98, -1)))
        dec = duel.decide(d, duel.DuelState(d, 100, 16), 113, cfg("--last-while-moving"))
        self.assertEqual((dec["action"], dec["step"]), ("say", "last"))
        self.assertEqual(dec["price"], 88)                               # 96 / 1.08 (LAST_R), floored

    def test_on_the_last_chance_waits_for_the_last_ticks(self):
        d = conceding(prices=tuple(range(110, 98, -1)))
        dec = duel.decide(d, duel.DuelState(d, 100, 16), 111, cfg("--last-while-moving"))   # 5 ticks left
        self.assertEqual(dec["action"], "hold")

    def test_on_an_acceptable_offer_is_still_accepted_not_answered(self):
        d = conceding(prices=tuple(range(110, 98, -1)) + (90,))        # 90 < 96: inside our limit
        dec = duel.decide(d, duel.DuelState(d, 100, 16), 114, cfg("--last-while-moving"))
        self.assertEqual(dec["action"], "accept")

    def test_on_two_issues_the_last_chance_names_our_best_day(self):
        d = conceding(prices=(105, 103, 101, 99, 97, 96, 94, 92, 90, 88, 86, 84, 83), day=5)   # 83 at day 5: -3.15
        st = duel.DuelState(d, 100, 16)
        dec = duel.decide(d, st, 114, cfg("--last-while-moving", "--days-best", "buyer:0,seller:10"))
        self.assertEqual((dec["action"], dec["step"], dec["days"]), ("say", "last", 0))
        self.assertGreaterEqual(duel.surplus(d, dec["price"], dec["days"], "buyer:0"), 1)


DUELS3 = ROOT / "docs" / "duel-lab" / "duel-params-duels3.json"
BLEND = ROOT / "docs" / "duel-lab" / "duel-params-duels2-blend.json"
# the factory's command (tools/factory_sunday.json, process "duel"): flags win over the JSON, and it passes no
# --days-best and no --days-confirmed
FACTORY = ["--params", str(DUELS3), "--duel-ticks", "12", "--late-poll", "4"]


class ParamsFile(unittest.TestCase):
    def test_what_changed_from_the_file_that_played_duels2(self):
        new, old = json.loads(DUELS3.read_text()), json.loads(BLEND.read_text())
        changed = {k: (old.get(k), v) for k, v in new.items() if old.get(k) != v}
        self.assertEqual(changed, {"late_poll": (8, 4), "duel_ticks": (16, 12),
                                   "days_best": (None, "buyer:0,seller:10"), "last_while_moving": (None, True)})
        self.assertLessEqual(set(old), set(new))

    def test_the_factory_command_runs_it_with_the_days_confirmed_for_both_roles(self):
        c = duel.make_cfg(["run", *FACTORY])
        self.assertEqual((c.duel_ticks, c.late_poll, c.last_while_moving), (12, 4, True))
        for role, best in (("buyer", 0), ("seller", 10)):
            d = conceding(role=role, day=5)
            self.assertFalse(duel.days_unconfirmed(d, c.days_best), role)    # no robust mode: it costs 0.047 a duel
            self.assertEqual(duel.days_profile(d, c.days_best)[0], best)
        seller = conceding(role="seller", limit=100, day=5)
        self.assertEqual(duel.surplus(seller, 100, 10, c.days_best), 32.3)   # the server pays a seller w per day

    def test_it_passes_the_selftest_simulation(self):
        c = duel.make_cfg(["selftest", *FACTORY])
        res = duel.simulate(duel, c, n_duels=600, seed=5, ticks=12)
        self.assertEqual(res["violations"], [])
        self.assertLessEqual(res["max_sends"], c.max_msgs)


class SlowServer:
    """Five price-only buyer duels on 15 s ticks (virtual time). Duels 1-4: the rival concedes every tick but stays
    outside our limit (96), so F4 sends each a last chance at deadline-4 (tick 112). Duel 5 (limit 120, deadline 117):
    the rival holds 130, offers 100 at tick 108 (stalled, so acceptable at tick 112) and goes back to 125 at tick 113.
    Every message takes 10 s."""
    TS = 15.0

    def __init__(self, vt):
        self.vt, self.timeout, self.retries = vt, 15.0, 3
        self.calls, self.says, self.accepts, self.deal = [], {}, [], {}
        self.posts = {i: [(t, 0.1, max(99, 112 - (t - 100))) for t in range(100, 116)] for i in (1, 2, 3, 4)}
        self.posts[5] = [(t, 0.1, 130) for t in range(100, 108)] + [(108, 0.1, 100), (113, 0.1, 125)]
        self.D = {1: 116, 2: 116, 3: 116, 4: 116, 5: 117}
        self.L = {1: 96, 2: 96, 3: 96, 4: 96, 5: 120}

    def _now(self):
        return int(self.vt.now // self.TS), self.vt.now % self.TS

    def clock(self):
        t, sec = self._now()
        return {"tick": t, "paused": False, "next_tick_in": self.TS - sec, "tick_seconds": self.TS}

    def _view(self, did):
        t, sec = self._now()
        theirs = [(pt, p) for pt, ps, p in self.posts[did] if (pt, ps) <= (t, sec)]
        msgs = [{"tick": pt, "from": "Rival X", "price": p, "days": None, "text": ""} for pt, p in theirs]
        msgs += [{"tick": st, "from": "you", "price": p, "days": None, "text": ""} for st, p in self.says.get(did, [])]
        d = {"duel": did, "session": 4, "status": "live", "role": "buyer", "item": f"item-{did}", "issues": ["price"],
             "your_days_weight": None, "days_meaning": None, "your_limit": self.L[did], "rival": "Rival X",
             "deadline_tick": self.D[did], "decay_per_round": 0.1, "rounds": 0, "your_offer": None,
             "rival_offer": ({"id": len(theirs), "price": theirs[-1][1], "tick": theirs[-1][0], "days": 0}
                             if theirs else None), "messages": sorted(msgs, key=lambda m: m["tick"]),
             "result": None, "price": None, "days": None}
        if did in self.deal and t > self.deal[did]:
            d["status"] = "deal"
        elif t >= self.D[did]:
            d["status"] = "no_deal"
        return d

    def duels(self, done=False):
        return {"duels": [self._view(i) for i in self.D]}

    def duel_accept(self, did):
        t, sec = self._now()
        self.accepts.append((did, t, self._view(did)["rival_offer"]["price"]))
        self.deal[did] = t
        return {"ok": True}

    def duel_say(self, did, text, price=None, days=None):
        t, sec = self._now()
        self.calls.append((did, t, round(sec, 2), self.timeout, self.retries))
        if self.timeout < 10.0:
            self.vt.now += self.timeout
            raise duel.BazaarError("network", "timed out", 0)
        self.vt.now += 10.0
        self.says.setdefault(did, []).append((t, price))
        return {"ok": True}


class SlowMessages(unittest.TestCase):
    """Review of #72 (blocker): F4 can send several messages in one tick; with a slow server they must never eat the
    tick, push a message into the next tick on a stale decision, or hold back the tick's accept."""

    def play(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import test_duel_improve as ti
        vt = ti.VirtualTime(100 * SlowServer.TS + 0.4)
        srv = SlowServer(vt)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(duel, "time", vt), \
                mock.patch.object(duel, "Bazaar", lambda *a, **k: srv), \
                mock.patch.object(duel, "load_env", lambda: None), \
                mock.patch.object(duel, "ROOT", Path(tmp)), \
                mock.patch.object(duel, "LOCK_PATH", Path(tmp) / "duel.lock"), \
                mock.patch.object(duel, "RunLog", ti._tmp_runlog(Path(tmp))), \
                mock.patch.dict(os.environ, {"BAZAAR_KEY": "test-not-a-key"}), \
                mock.patch.object(sys, "argv", ["duel.py", "run", *FACTORY[:-4], "--duel-ticks", "16",
                                                "--late-poll", "4", "--idle-ticks", "2", "--log-dir", tmp]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            duel.main()
        return srv, out.getvalue()

    def test_the_accept_is_not_held_back_and_no_message_starts_late(self):
        srv, out = self.play()
        self.assertEqual(srv.accepts, [(5, 112, 100)])           # in the tick of the four messages, before them
        f4 = [c for c in srv.calls if c[0] != 5]
        self.assertEqual({t for _, t, *_ in f4}, {112, 113, 114, 115})
        for did, t, sec, timeout, retries in f4:                  # 113-115 have a late read (4 s): end 5 s early
            end = SlowServer.TS - (1.0 if t == 112 else 5.0)
            self.assertLessEqual(sec + timeout, end + 1e-6, (did, t, sec, timeout))
            self.assertEqual(retries, 0)
        self.assertIn("say_budget", out)
        self.assertEqual((srv.timeout, srv.retries), (15.0, 3))   # the client's own settings are restored


class PostSayBudget(unittest.TestCase):
    def test_no_call_after_the_deadline_and_the_timeout_is_capped(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import test_duel_improve as ti
        vt = ti.VirtualTime(1000.0)
        srv = SlowServer(vt)
        with mock.patch.object(duel, "time", vt):
            duel.post_say(srv, 1, "x", 90, None, deadline=1012.0)    # 12 s left: the 10 s call fits
            with self.assertRaises(duel.BazaarError):
                duel.post_say(srv, 2, "x", 90, None, deadline=1012.0)   # 2 s left: capped, times out
            with self.assertRaises(duel.BazaarError) as e:
                duel.post_say(srv, 3, "x", 90, None, deadline=1012.0)   # past the deadline: no call at all
        self.assertEqual(e.exception.code, "say_budget")
        self.assertEqual([(c[0], c[3], c[4]) for c in srv.calls], [(1, 12.0, 0), (2, 2.0, 0)])
        self.assertLessEqual(vt.now, 1012.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
