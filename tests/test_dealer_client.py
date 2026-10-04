"""The dealer bots' client (agent/chato.py, agent/abuela.py): built with wait_on_tick=False (D3), and a wait_tick that
holds through a paused clock or closed doors and tolerates a null next_tick_in (D4). kit/ stays unchanged.

    python3 -m unittest discover tests
"""
import unittest

from dealer_fakes import (BOTS, BazaarError, FakeAccount, FakeServer, KitBazaar, NullRun, VirtualClock, lock_sequence,
                          patched_sleep, restore_globals, run_main, save_globals, sell_target)


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
        """A running clock whose tick never moves must not hold the bot forever (bounded fallback), and the wait
        confirms no new tick (so no round is counted for it)."""
        same = {"tick": 100, "paused": False, "doors": "open", "next_tick_in": 0}
        for mod in BOTS:
            b = client(mod)
            n = []
            b._call = lambda method, path, body=None, query=None: (n.append(1), dict(same))[1]
            vc = VirtualClock()
            with patched_sleep(vc):
                c = b.wait_tick()
            self.assertIsNone(c.get("tick"), mod.__name__)
            self.assertLess(len(n), 1000, mod.__name__)

    def test_stuck_clock_is_reported_once_a_minute(self):
        """A running clock whose tick never moves (a frozen server, not flagged paused) is reported to the operator,
        once a minute across successive waits, while the bot spends no rounds on it."""
        same = {"tick": 100, "paused": False, "doors": "open", "next_tick_in": 0}
        for mod in BOTS:
            b = client(mod)
            b._call = lambda method, path, body=None, query=None: dict(same)
            seen = []
            b.on_wait = lambda kind, c, waited: seen.append((kind, waited))
            vc = VirtualClock()
            with patched_sleep(vc):
                for _ in range(6):                               # six waits of about 30 s each: about 3 minutes
                    self.assertIsNone(b.wait_tick().get("tick"), mod.__name__)
            kinds = [k for k, _ in seen]
            self.assertEqual(set(kinds), {"clock_stuck"}, (mod.__name__, seen))
            # waits end every ~30 s, so "once a minute" lands every 60 to 90 s: more than once, fewer than every wait
            self.assertTrue(2 <= len(kinds) <= 4, (mod.__name__, vc.now, seen))

    def test_pause_reports_once_a_minute(self):
        """item 6: a long pause is reported once a minute, not once per wait."""
        for mod in BOTS:
            vc = VirtualClock(pause_from=0.0, pause_to=300.0)
            b = client(mod)
            b._call = lambda method, path, body=None, query=None: vc.read()
            seen = []
            b.on_wait = lambda kind, c, waited: seen.append((kind, waited))
            with patched_sleep(vc):
                b.wait_tick()
            self.assertIn(len(seen), (5, 6), (mod.__name__, seen))
            self.assertEqual({k for k, _ in seen}, {"paused"}, mod.__name__)
            self.assertEqual(seen[0][1], 0.0, mod.__name__)

    def test_unreadable_clock_gives_up_within_about_a_minute(self):
        """item 8: a dead clock endpoint (every read times out) releases the bot within about a minute of real time,
        and reports it; no round can be counted for it."""
        for mod in BOTS:
            srv = FakeServer(clock_down=(0.0, 10.0 ** 9))
            seen = []
            with srv.serving():
                b = srv.client(mod)
                b.on_wait = lambda kind, c, waited: seen.append(kind)
                t0 = srv.vc.now
                c = b.wait_tick()
                elapsed = srv.vc.now - t0
            self.assertEqual(c, {}, mod.__name__)
            self.assertLess(elapsed, 90.0, (mod.__name__, elapsed))
            self.assertEqual(seen[:1], ["clock_unreadable"], mod.__name__)


class TestWritesNotRetried(unittest.TestCase):
    """item 2: the SDK must never resend a write (a retried accept can land after the duel lock turned fresh, a
    retried message after the dealer replaced her offer). Reads keep the SDK's retries."""

    def test_rate_limited_message_raises_once(self):
        for mod in BOTS:
            srv = FakeServer(dealer=mod.DEALER)
            srv.inject["say"] = [(429, "rate_limited")]
            with srv.serving():
                b = srv.client(mod)
                b.open_thread(mod.DEALER, topic={"sell": {"assets": [42]}})
                with self.assertRaises(BazaarError) as e:
                    b.say(7, "x", price=30)
            self.assertEqual(e.exception.code, "rate_limited", mod.__name__)
            self.assertEqual(len(srv.writes("messages")), 1, mod.__name__)

    def test_rate_limited_accept_raises_once(self):
        for mod in BOTS:
            srv = FakeServer(dealer=mod.DEALER, opening=25)
            srv.inject["accept"] = [(429, "rate_limited")]
            with srv.serving():
                b = srv.client(mod)
                b.open_thread(mod.DEALER, topic={"sell": {"assets": [42]}})
                oid = srv.dealer_offer()["id"]
                with self.assertRaises(BazaarError):
                    b.accept(oid)
            self.assertEqual(len(srv.writes("accept")), 1, mod.__name__)
            self.assertEqual(srv.accepted, [], mod.__name__)

    def test_reads_keep_the_sdk_retries(self):
        for mod in BOTS:
            srv = FakeServer(dealer=mod.DEALER)
            with srv.serving():
                b = srv.client(mod)
                b.open_thread(mod.DEALER, topic={"sell": {"assets": [42]}})
                srv.inject["thread"] = [(429, "rate_limited")]
                self.assertEqual(b.thread(7)["status"], "open", mod.__name__)


class TestFakeServer(unittest.TestCase):
    """The fake behaves like the server on the three points the bots depend on (kit SDK client, no retries)."""

    def setUp(self):
        self.srv = FakeServer(dealer="chato", opening=25)
        self.cm = self.srv.serving()
        self.cm.__enter__()
        self.b = KitBazaar("http://fake.invalid", "test-dummy", wait_on_tick=False, retries=0)
        self.b.open_thread("chato", topic={"sell": {"assets": [42]}})

    def tearDown(self):
        self.cm.__exit__(None, None, None)

    def next_tick(self):
        self.srv.vc.sleep(15.0)

    def test_accept_of_an_unknown_or_replaced_offer_is_refused(self):
        old = self.srv.dealer_offer()["id"]
        with self.assertRaises(BazaarError) as e:
            self.b.accept(old + 999)
        self.assertEqual(e.exception.code, "offer_not_open")
        self.srv.post(24)
        with self.assertRaises(BazaarError):
            self.b.accept(old)                                   # replaced: no longer open

    def test_accept_settles_on_the_next_tick(self):
        self.b.accept(self.srv.dealer_offer()["id"])
        self.assertEqual(self.b.thread(7)["status"], "open")
        self.next_tick()
        self.assertEqual(self.b.thread(7)["status"], "deal")

    def test_one_accept_per_team_and_one_message_per_thread_per_tick(self):
        self.b.say(7, "x", price=40)
        with self.assertRaises(BazaarError) as e:
            self.b.say(7, "y", price=39)
        self.assertEqual(e.exception.code, "wait_for_tick")
        self.srv.teammate_accepts.add(self.srv.tick())
        with self.assertRaises(BazaarError) as e:
            self.b.accept(self.srv.dealer_offer()["id"])
        self.assertEqual(e.exception.code, "wait_for_tick")

    def test_dealer_answers_on_the_next_tick_and_offers_lapse(self):
        first = self.srv.dealer_offer()["id"]
        self.b.say(7, "x", price=40)
        self.assertEqual(self.srv.dealer_offer()["id"], first)   # no answer in the same tick
        self.next_tick()
        self.b.thread(7)
        self.assertNotEqual(self.srv.dealer_offer()["id"], first)
        for _ in range(4):
            self.next_tick()
        self.assertEqual(self.b.thread(7)["standing_offers"], [])   # lapsed 4 ticks after it was posted

    def test_sdk_retry_shows_as_a_same_tick_resend(self):
        self.srv.inject["say"] = [(429, "rate_limited")]
        retrying = KitBazaar("http://fake.invalid", "test-dummy", wait_on_tick=False, retries=3)
        retrying.say(7, "x", price=40)
        self.assertEqual(len(self.srv.same_tick_resends()), 1)


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
                base = {"kind": "card", "ref": "MAL-06", "rarity": "uncommon", "set": "MAL", "name": "MAL-06"}
                return {"cash": 1000, "affinity": {"MAL": 0.7},
                        "assets": [dict(base, id=42, serial=9, your_value=40), dict(base, id=43, serial=1, your_value=40)]}
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
