"""The dealer bots' client (agent/chato.py, agent/abuela.py): built with wait_on_tick=False (D3), and a wait_tick that
holds through a paused clock or closed doors and tolerates a null next_tick_in (D4). kit/ stays unchanged.

    python3 -m unittest discover tests
"""
import unittest

from dealer_fakes import (BOTS, FakeAccount, NullRun, Thread, VirtualClock, lock_sequence, patched_sleep,
                          restore_globals, run_main, save_globals, sell_target)


def scripted(clocks):
    """A _call stand-in that serves /api/clock from a list and fails on anything else or past the end."""
    calls = []

    def _call(method, path, body=None, query=None):
        calls.append(path)
        if path != "/api/clock":
            raise AssertionError(f"unexpected {method} {path}")
        if not clocks:
            raise AssertionError("clock polled past the script")
        return clocks.pop(0)
    return _call, calls


def client(mod):
    return mod.Bazaar("http://test.invalid", "test-dummy")


class TestClientConstruction(unittest.TestCase):
    """D3: a refused accept or message must come back to the bot, not be resent by the SDK on the next tick."""

    def check(self, mod, argv):
        class Account(FakeAccount):
            made = []
        code, out, run, _ = run_main(mod, argv, Account)
        self.assertIsNone(code, out)
        self.assertEqual(len(Account.made), 1)
        self.assertIs(Account.made[0].get("wait_on_tick"), False)

    def test_chato_builds_client_without_wait_on_tick(self):
        self.check(BOTS[0], ["plan", "--only", "LAV-09"])

    def test_abuela_builds_client_without_wait_on_tick(self):
        self.check(BOTS[1], ["plan", "--only", "LAV-01"])

    def test_bot_client_defaults_to_no_wait_on_tick(self):
        for mod in BOTS:
            self.assertFalse(client(mod).wait_on_tick, mod.__name__)


class TestPauseSafeWait(unittest.TestCase):
    """D4: kit's wait_tick returns at once while the clock is paused and does float(None) on a null next_tick_in."""

    def wait(self, mod, clocks):
        b = client(mod)
        b._call, calls = scripted(list(clocks))
        vc = VirtualClock()
        with patched_sleep(vc):
            c = b.wait_tick()
        return c, calls, vc

    def test_holds_through_pause_with_null_next_tick_in(self):
        paused = {"tick": 100, "paused": True, "doors": "open", "next_tick_in": None}
        script = [paused, paused, paused,
                  {"tick": 100, "paused": False, "doors": "open", "next_tick_in": None, "tick_seconds": 15},
                  {"tick": 101, "paused": False, "doors": "open", "next_tick_in": 15}]
        for mod in BOTS:
            c, calls, vc = self.wait(mod, script)
            self.assertEqual((c["tick"], c["paused"]), (101, False), mod.__name__)
            self.assertEqual(len(calls), len(script), mod.__name__)

    def test_does_not_return_while_paused(self):
        script = [{"tick": 100, "paused": True, "next_tick_in": 4},
                  {"tick": 100, "paused": True, "next_tick_in": 4},
                  {"tick": 100, "paused": False, "next_tick_in": 2},
                  {"tick": 101, "paused": False, "next_tick_in": 15}]
        for mod in BOTS:
            c, calls, vc = self.wait(mod, script)
            self.assertFalse(c.get("paused"), mod.__name__)
            self.assertEqual(c["tick"], 101, mod.__name__)

    def test_waits_for_doors_to_open(self):
        closed = {"tick": 100, "paused": False, "doors": "closed", "next_tick_in": None}
        script = [closed, closed, {"tick": 100, "paused": False, "doors": "open", "next_tick_in": 1},
                  {"tick": 101, "paused": False, "doors": "open", "next_tick_in": 15}]
        for mod in BOTS:
            c, calls, vc = self.wait(mod, script)
            self.assertEqual((c["tick"], c["doors"]), (101, "open"), mod.__name__)

    def test_polls_every_few_seconds_while_paused(self):
        vc = VirtualClock(pause_from=0.0, pause_to=600.0)
        for mod in BOTS:
            vc.now, vc.reads = 0.0, 0
            b = client(mod)
            b._call = lambda method, path, body=None, query=None: vc.read()
            with patched_sleep(vc):
                c = b.wait_tick()
            self.assertFalse(c["paused"], mod.__name__)
            self.assertGreaterEqual(vc.now, 600.0, mod.__name__)
            self.assertGreater(vc.reads, 600 / 10, mod.__name__)       # polled at least every 10 s
            self.assertLess(vc.reads, 600 / 1, mod.__name__)           # but not spinning

    def test_stuck_running_clock_returns(self):
        """A running clock whose tick never moves must not hold the bot forever (bounded fallback)."""
        same = {"tick": 100, "paused": False, "doors": "open", "next_tick_in": 0}
        for mod in BOTS:
            b = client(mod)
            n = []
            b._call = lambda method, path, body=None, query=None: (n.append(1), dict(same))[1]
            vc = VirtualClock()
            with patched_sleep(vc):
                c = b.wait_tick()
            self.assertEqual(c["tick"], 100, mod.__name__)
            self.assertLess(len(n), 1000, mod.__name__)


class TestPauseCostsNoRounds(unittest.TestCase):
    """D4 end to end: a 3-minute pause in the middle of a negotiation does not eat the round budget. The dealer names
    her final at tick 104; with MAX_ROUNDS 5 we only see it if the paused minutes did not count as rounds."""

    def make(self, mod, vc):
        dealer = mod.DEALER

        class Sim(mod.Bazaar):
            def __init__(self):
                super().__init__("http://test.invalid", "test-dummy")
                self.offer_id, self.status, self.accepted = 500, "open", []

            def _call(self, method, path, body=None, query=None):
                if path == "/api/clock":
                    return vc.read()
                raise AssertionError(f"unexpected {method} {path}")

            def tick(self):
                return vc.read()["tick"]

            def open_thread(self, with_, topic=None, venue=None):
                return {"id": 9}

            def thread(self, tid):
                final = self.tick() >= 104
                price = 41 if final else 16
                o = {"id": self.offer_id + (1000 if final else 0), "maker": dealer, "status": "open", "final": final,
                     "give": {"cash": price}, "want": {"assets": [{"id": 42}]}}
                return {"id": tid, "status": self.status, "standing_offers": [o] if self.status == "open" else [],
                        "messages": []}

            def say(self, tid, text="", price=None, offer=None, topic=None):
                self.offer_id += 1
                return {}

            def accept(self, oid):
                self.accepted.append(oid)
                self.status = "deal"
                return {}

            def close_thread(self, tid):
                self.status = "walked"
                return {}

            def me(self):
                return {"cash": 1000}
        return Sim()

    def test_pause_does_not_spend_rounds(self):
        for mod in BOTS:
            saved = save_globals(mod)
            try:
                mod.RUN, mod.MAX_ROUNDS, mod.duel_lock_fresh = NullRun(), 5, lock_sequence()
                if hasattr(mod, "apply_dealer"):
                    mod.apply_dealer("chato")
                vc = VirtualClock(pause_from=20.0, pause_to=200.0)
                b = self.make(mod, vc)
                with patched_sleep(vc):
                    r = mod.negotiate(b, sell_target(42, "MAL-06", 40), False)
                self.assertEqual(r["result"], "deal", mod.__name__)
                self.assertEqual(r["price"], 41, mod.__name__)
                self.assertEqual(len(b.accepted), 1, mod.__name__)
            finally:
                restore_globals(mod, saved)


if __name__ == "__main__":
    unittest.main()
