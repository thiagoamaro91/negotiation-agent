"""The dealer bots' negotiation loop (agent/chato.py, agent/abuela.py) against a scripted dealer, no key, no network:

- D1 (chato): the --max-bid pin listens only while the dealer keeps improving, then takes his standing offer if it is
  inside our reservation or closes with max_bid_no_deal; the round budget never closes a thread while the dealer's
  standing offer is inside our reservation (buys and sells).
- D2 (both): the duel lock is re-checked before every accept; a fresh lock defers the accept by a tick, free of rounds.
- D3 (both): a refused accept, message or close never raises out of negotiate() and is never resent blindly.

    python3 -m unittest discover tests
"""
import unittest

from dealer_fakes import (NullRun, Thread, abuela, buy_target, chato, lock_sequence, restore_globals, save_globals,
                          sell_target)


class BotCase(unittest.TestCase):
    mod = chato

    def setUp(self):
        self.saved = save_globals(self.mod)
        self.mod.RUN = NullRun()
        self.mod.duel_lock_fresh = lock_sequence()   # never fresh unless a test says so
        if self.mod is chato:
            chato.apply_dealer("chato")
            chato.MAX_ROUNDS, chato.ANCHOR_ABS, chato.STEP, chato.MAX_BID = 12, None, 1, None
        self.mod.CASH_RESERVE = 280

    def tearDown(self):
        restore_globals(self.mod, self.saved)

    def events(self, name):
        return self.mod.RUN.named(name)


# ---------------------------------------------------------------- D1: bid-cap deadlock and the end of the budget

class TestThread335Replay(BotCase):
    """Thread 335, Saturday 2026-10-03 (logs/chato/2026-10-03.jsonl, logs/threads/thread-00335.json): LAV-09 with
    --anchor 60 --step 4 --max-bid 84 --cap 93 --reserve 200 --max-rounds 16, cash 383. His asks answered our
    60..84 with 97, 97, 97, 97, 96, 94, 90 (never final), and each of his offers lapses 4 ticks after it is posted.
    Old code pinned at 84, waited silently, and closed on max_rounds with his 90 inside our 93."""

    def setUp(self):
        super().setUp()
        chato.MAX_ROUNDS, chato.ANCHOR_ABS, chato.STEP, chato.MAX_BID, chato.CASH_RESERVE = 16, 60, 4, 84, 200

    def dealer(self):
        return Thread("chato", side="buy", item="LAV-09", opening=97, replies=[97, 97, 97, 97, 96, 94, 90],
                      expiry=4, cash=383)

    def test_takes_his_90_inside_our_93_instead_of_closing(self):
        b = self.dealer()
        r = chato.negotiate(b, buy_target("LAV-09", 93.0), False)
        self.assertEqual(b.says, [60, 64, 68, 72, 76, 80, 84])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(len(b.accepts), 1)
        self.assertLessEqual(b.accepts[0][1], 90)               # a deal at 90 or better, not a close
        self.assertNotIn("close", b.kinds())
        self.assertEqual(self.events("accept")[0]["why"], "max_bid_stall")

    def test_closes_at_once_when_his_stalled_ask_is_above_the_reservation(self):
        b = self.dealer()
        r = chato.negotiate(b, buy_target("LAV-09", 88.0), False)   # his 90 is above our 88
        self.assertEqual(r["result"], "max_bid_no_deal")
        self.assertEqual(b.accepts, [])
        self.assertIn("close", b.kinds())
        self.assertLess(b.tick, 16)                              # long before the round budget
        self.assertTrue(self.events("max_bid_no_deal"))

    def test_keeps_listening_while_he_still_improves(self):
        # pinned at 84 he keeps dropping on his own: 90, 89, 88 ... we must not accept while he improves
        b = self.dealer()
        drops = [89, 88, 87]
        real_wait = b.wait_tick

        def wait():
            c = real_wait()
            if b.status == "open" and b.says and b.says[-1] == 84 and drops and b.price() <= 90:
                b.post(drops.pop(0))
            return c
        b.wait_tick = wait
        r = chato.negotiate(b, buy_target("LAV-09", 93.0), False)
        self.assertEqual(r["result"], "deal")
        self.assertEqual(b.accepts[0][1], 87)                    # took it only once it stopped improving


class TestEndOfBudget(BotCase):
    def test_sell_takes_her_bid_inside_the_floor_when_rounds_run_out(self):
        # Pilar concedes by time: our asks 27, 26, 25 ... her bids 16, 17, 17, 18, 19; budget 5 rounds, floor 18
        chato.apply_dealer("pilar", sell_anchor=27, sell_step=1)
        chato.MAX_ROUNDS = 5
        b = Thread("pilar", opening=16, replies=[17, 17, 18, 19])
        r = chato.negotiate(b, sell_target(42, "MAL-06", 18), False)
        self.assertEqual(b.says, [27, 26, 25, 24, 23])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(b.accepts[0][1], 19)
        self.assertEqual(self.events("accept")[0]["why"], "budget_end")

    def test_buy_takes_his_ask_inside_the_reservation_when_rounds_run_out(self):
        chato.ANCHOR_ABS, chato.MAX_ROUNDS, chato.CASH_RESERVE = 20, 3, 0
        b = Thread("chato", side="buy", item="LAV-09", opening=30)
        r = chato.negotiate(b, buy_target("LAV-09", 40), False)
        self.assertEqual(b.says, [20, 21, 22])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(b.accepts[0][1], 30)

    def test_still_closes_when_his_ask_is_above_the_reservation(self):
        chato.ANCHOR_ABS, chato.MAX_ROUNDS, chato.CASH_RESERVE = 20, 3, 0
        b = Thread("chato", side="buy", item="LAV-09", opening=30)
        r = chato.negotiate(b, buy_target("LAV-09", 25), False)
        self.assertEqual(r["result"], "max_rounds")
        self.assertEqual(b.accepts, [])
        self.assertIn("close", b.kinds())


# ---------------------------------------------------------------- D2: duel lock before every accept

class LockCases:
    dealer = "chato"

    def test_fresh_lock_defers_the_accept_without_spending_a_round(self):
        self.mod.duel_lock_fresh = lock_sequence(True, True)
        self.mod.MAX_ROUNDS = 1        # had a deferral cost a round, the budget would be gone before the accept
        b = Thread(self.dealer, opening=25, opening_final=True)
        r = self.mod.negotiate(b, sell_target(42, "MAL-06", 20), False)
        self.assertEqual(r["result"], "deal")
        self.assertEqual(len(b.accepts), 1)
        self.assertEqual(b.accepts[0][2], 2)                     # accepted on the third tick, after two deferrals
        self.assertEqual(b.kinds().count("accept_attempt"), 1)   # nothing was sent while the lock was fresh
        deferred = self.events("accept_deferred_lock")
        self.assertEqual(len(deferred), 2)
        self.assertEqual({d["round"] for d in deferred}, {0})
        self.assertEqual(self.events("accept")[0]["round"], 0)

    def test_crossed_accept_also_checks_the_lock(self):
        self.mod.duel_lock_fresh = lock_sequence(True)
        b = Thread(self.dealer, opening=16, replies=[60])        # she jumps above our first ask: crossed
        r = self.mod.negotiate(b, sell_target(42, "MAL-06", 20), False)
        self.assertEqual(r["result"], "deal")
        self.assertEqual(len(self.events("accept_deferred_lock")), 1)
        self.assertEqual(b.accepts[0][1], 60)


class TestLockChato(LockCases, BotCase):
    mod = chato


class TestLockAbuela(LockCases, BotCase):
    mod = abuela
    dealer = "abuela"


# ---------------------------------------------------------------- D3: refused writes

class WriteCases:
    dealer = "chato"

    def test_refused_accept_rereads_and_takes_the_replaced_offer(self):
        b = Thread(self.dealer, opening=25, opening_final=True)
        b.refuse["accept"] = ["wait_for_tick"]
        first = b.offer["id"]
        real_wait = b.wait_tick

        def wait():
            c = real_wait()
            if not b.accepts and b.offer["id"] == first:
                b.post(24, final=True)           # the dealer replaced her offer during the refused tick
            return c
        b.wait_tick = wait
        r = self.mod.negotiate(b, sell_target(42, "MAL-06", 20), False)
        self.assertEqual(r["result"], "deal")
        attempts = [c for c in b.calls if c[0] == "accept_attempt"]
        self.assertEqual([a[1] for a in attempts], [first, first + 1])   # the second accept names the new offer
        self.assertEqual(b.accepts[0][1], 24)
        k = b.kinds()
        i, j = k.index("accept_attempt"), len(k) - 1 - k[::-1].index("accept_attempt")
        self.assertIn("wait", k[i:j])
        self.assertIn("read", k[i:j])                            # re-read before deciding again
        self.assertEqual(self.events("accept_refused")[0]["code"], "wait_for_tick")

    def test_refused_message_is_not_counted_as_said(self):
        b = Thread(self.dealer, opening=16, final=None)
        b.refuse["say"] = ["wait_for_tick"]
        self.mod.MAX_ROUNDS = 3
        self.mod.negotiate(b, sell_target(42, "MAL-06", 20), False)
        attempts = [c[1] for c in b.calls if c[0] == "say_attempt"]
        self.assertEqual(attempts[0], attempts[1])               # the refused number is sent again, not skipped
        self.assertEqual(b.says[0], attempts[0])
        self.assertTrue(self.events("say_refused"))

    def test_accept_refused_every_time_never_raises_and_closes(self):
        b = Thread(self.dealer, opening=25, opening_final=True)
        b.refuse["accept"] = ["insufficient_cash"] * 50
        self.mod.MAX_ROUNDS = 3
        r = self.mod.negotiate(b, sell_target(42, "MAL-06", 20), False)
        self.assertNotEqual(r["result"], "deal")
        self.assertEqual(b.status, "walked")                     # closed, not left open
        self.assertIn("close", b.kinds())

    def test_refused_close_on_a_walk_is_retried(self):
        b = Thread(self.dealer, opening=16, final=15)            # final below the floor: we walk
        b.refuse["close"] = ["wait_for_tick"]
        r = self.mod.negotiate(b, sell_target(42, "MAL-06", 40), False)
        self.assertEqual(r["result"], "walked_by_us")
        self.assertEqual(b.status, "walked")
        self.assertEqual(b.kinds().count("close_attempt"), 2)


class TestWritesChato(WriteCases, BotCase):
    mod = chato


class TestWritesAbuela(WriteCases, BotCase):
    mod = abuela
    dealer = "abuela"


if __name__ == "__main__":
    unittest.main()
