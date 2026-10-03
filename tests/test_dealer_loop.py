"""The dealer bots' negotiation loop (agent/chato.py, agent/abuela.py) against the fake game server, through the real
kit SDK and the bots' real client (tests/dealer_fakes.py). Every test also checks that no write (accept, message,
close) was sent twice in one tick.

- D1: the --max-bid pin listens only while the dealer keeps improving (or we just moved), then takes his offer if it
  is inside our reservation or closes with max_bid_no_deal; the round budget never closes on a standing offer inside
  our reservation (chato and abuela, buys and sells).
- D2: the duel lock is re-checked before every accept; a fresh lock defers by a tick, free of rounds, bounded by
  --max-defer-ticks (then lock_timeout).
- D3: a refused accept, message or close never raises out of negotiate(), is never resent by the SDK, and comes
  back to a fresh read and decision; a close that keeps failing is reported as close_failed.
- D4: clock trouble during a pause spends no rounds.

    python3 -m unittest discover tests
"""
import unittest

from dealer_fakes import FakeServer, NullRun, abuela, buy_target, chato, lock_sequence, restore_globals, save_globals, \
    sell_target


class ServerCase(unittest.TestCase):
    mod = chato
    dealer = "chato"

    def setUp(self):
        self.saved = save_globals(self.mod)
        self.mod.RUN = NullRun()
        self.mod.duel_lock_fresh = lock_sequence()   # never fresh unless a test says so
        if self.mod is chato:
            chato.apply_dealer("chato")
            chato.ANCHOR_ABS, chato.STEP, chato.MAX_BID = None, 1, None
        self.mod.MAX_ROUNDS, self.mod.CASH_RESERVE, self.mod.MAX_DEFER_TICKS = 12, 280, 60

    def tearDown(self):
        restore_globals(self.mod, self.saved)

    def events(self, name):
        return self.mod.RUN.named(name)

    def run_thread(self, srv, target, first_deal=False, **kw):
        with srv.serving():
            r = self.mod.negotiate(srv.client(self.mod), target, first_deal, **kw)
        self.assertEqual(srv.same_tick_resends(), [], "a write was sent twice in one tick")
        return r

    def server(self, **kw):
        kw.setdefault("dealer", self.dealer)
        return FakeServer(**kw)


# ---------------------------------------------------------------- D1: bid-cap deadlock and the end of the budget

class TestThread335Replay(ServerCase):
    """Thread 335, Saturday 2026-10-03 (logs/chato/2026-10-03.jsonl, logs/threads/thread-00335.json): LAV-09 with
    --anchor 60 --step 4 --max-bid 84 --cap 93 --reserve 200 --max-rounds 16, cash 383. His asks answered our
    60..84 with 97, 97, 97, 97, 96, 94, 90 (never final), each a tick after our message, and each of his offers lapses
    4 ticks after it is posted. Old code pinned at 84, waited silently, and closed on max_rounds with his 90 inside
    our 93."""

    def setUp(self):
        super().setUp()
        chato.MAX_ROUNDS, chato.ANCHOR_ABS, chato.STEP, chato.MAX_BID, chato.CASH_RESERVE = 16, 60, 4, 84, 200

    def dealer335(self, replies=(97, 97, 97, 97, 96, 94, 90)):
        return self.server(side="buy", item="LAV-09", opening=97, replies=list(replies), cash=383)

    def test_takes_his_90_inside_our_93_instead_of_closing(self):
        srv = self.dealer335()
        r = self.run_thread(srv, buy_target("LAV-09", 93.0))
        self.assertEqual([p for _, p in srv.said], [60, 64, 68, 72, 76, 80, 84])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(len(srv.accepted), 1)
        self.assertLessEqual(srv.accepted[0][1], 90)             # a deal at 90 or better, not a close
        self.assertEqual(srv.closes, [])
        self.assertEqual(srv.status(), "deal")
        self.assertEqual(self.events("accept")[0]["why"], "max_bid_stall")

    def test_closes_at_once_when_his_stalled_ask_is_above_the_reservation(self):
        srv = self.dealer335()
        r = self.run_thread(srv, buy_target("LAV-09", 88.0))     # his 90 is above our 88
        self.assertEqual(r["result"], "max_bid_no_deal")
        self.assertEqual(srv.accepted, [])
        self.assertEqual(srv.status(), "closed")
        self.assertLess(srv.closes[0] - 100, 16)                 # long before the round budget
        self.assertTrue(self.events("max_bid_no_deal"))

    def test_max_bid_equal_to_the_reservation_closes_on_the_stall(self):
        # item 10: reservation 84 and --max-bid 84, his ask stalls at 90: close with max_bid_no_deal, not max_rounds
        srv = self.dealer335()
        r = self.run_thread(srv, buy_target("LAV-09", 84.0))
        self.assertEqual(r["result"], "max_bid_no_deal")
        self.assertLess(srv.closes[0] - 100, 16)

    def test_keeps_listening_while_he_still_improves(self):
        srv = self.dealer335()
        drops = [89, 88, 87]

        def drop(s, t):   # pinned at 84, he keeps dropping on his own a tick after his 90
            if s.said and s.said[-1][1] == 84 and drops and t > s.said[-1][0] + 1:
                s.post(drops.pop(0), t=t)
        srv.hooks.append(drop)
        r = self.run_thread(srv, buy_target("LAV-09", 93.0))
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 87)                 # took it only once it stopped improving

    def test_late_answer_to_our_capped_bid_is_still_heard(self):
        # he holds 97 through our 60..80, then answers our 84 two ticks later with 90: the 2-tick window starts at
        # our own move, so his earlier hold does not close the thread before his answer
        srv = self.dealer335(replies=[97] * 6 + [90])
        srv.reply_delay[84] = 2
        r = self.run_thread(srv, buy_target("LAV-09", 93.0))
        self.assertEqual([p for _, p in srv.said], [60, 64, 68, 72, 76, 80, 84])
        self.assertEqual(self.events("max_bid_no_deal"), [])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 90)


class TestEndOfBudget(ServerCase):
    def test_sell_takes_her_bid_inside_the_floor_when_rounds_run_out(self):
        # Pilar concedes by time: our asks 27, 26, 25 ... her bids 16, 17, 17, 18, 19; budget 5 rounds, floor 18
        chato.apply_dealer("pilar", sell_anchor=27, sell_step=1)
        chato.MAX_ROUNDS = 5
        srv = self.server(dealer="pilar", opening=16, replies=[17, 17, 18, 19])
        r = self.run_thread(srv, sell_target(42, "MAL-06", 18))
        self.assertEqual([p for _, p in srv.said], [27, 26, 25, 24, 23])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 19)
        self.assertEqual(self.events("accept")[0]["why"], "budget_end")

    def test_buy_takes_his_ask_inside_the_reservation_when_rounds_run_out(self):
        chato.ANCHOR_ABS, chato.MAX_ROUNDS, chato.CASH_RESERVE = 20, 3, 0
        srv = self.server(side="buy", item="LAV-09", opening=30)
        r = self.run_thread(srv, buy_target("LAV-09", 40))
        self.assertEqual([p for _, p in srv.said], [20, 21, 22])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 30)

    def test_still_closes_when_his_ask_is_above_the_reservation(self):
        chato.ANCHOR_ABS, chato.MAX_ROUNDS, chato.CASH_RESERVE = 20, 3, 0
        srv = self.server(side="buy", item="LAV-09", opening=30)
        r = self.run_thread(srv, buy_target("LAV-09", 25))
        self.assertEqual(r["result"], "max_rounds")
        self.assertEqual(srv.accepted, [])
        self.assertEqual(srv.status(), "closed")


class TestEndOfBudgetAbuela(ServerCase):
    mod, dealer = abuela, "abuela"

    def test_abuela_takes_her_bid_inside_the_floor_when_rounds_run_out(self):
        # asks 35, 34, 33, 32, 31 (2.2 x 16, then 1 P); her bids 16, 17, 17, 18, 19; budget 5 rounds, floor 18
        abuela.MAX_ROUNDS = 5
        srv = self.server(opening=16, replies=[17, 17, 18, 19])
        r = self.run_thread(srv, sell_target(42, "MAL-06", 18))
        self.assertEqual([p for _, p in srv.said], [35, 34, 33, 32, 31])
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 19)


# ---------------------------------------------------------------- item 1: fractional sell floors

class FloorCases:
    def test_fractional_floor_is_never_undercut(self):
        # floor 19.5 (private 17.5 + 2), her opening bid 5: every binding ask must be at least 20
        self.mod.MAX_ROUNDS = 3
        srv = self.server(opening=5)
        self.run_thread(srv, sell_target(42, "MAL-06", 19.5))
        self.assertTrue(srv.said)
        self.assertTrue(all(p >= 20 for _, p in srv.said), srv.said)


class TestFloorAbuela(FloorCases, ServerCase):
    mod, dealer = abuela, "abuela"


class TestFloorChato(FloorCases, ServerCase):
    pass


# ---------------------------------------------------------------- D2: duel lock before every accept

class LockCases:
    def test_fresh_lock_defers_the_accept_without_spending_a_round(self):
        self.mod.duel_lock_fresh = lock_sequence(True, True)
        self.mod.MAX_ROUNDS = 1        # had a deferral cost a round, the budget would be gone before the accept
        srv = self.server(opening=25, opening_final=True)
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(r["result"], "deal")
        self.assertEqual(len(srv.accepted), 1)
        self.assertEqual(srv.accepted[0][2], 102)                # accepted on the third tick, after two deferrals
        self.assertEqual(len(srv.writes("accept")), 1)           # nothing was sent while the lock was fresh
        deferred = self.events("accept_deferred_lock")
        self.assertEqual(len(deferred), 2)
        self.assertEqual({d["round"] for d in deferred}, {0})
        self.assertEqual(self.events("accept")[0]["round"], 0)

    def test_crossed_accept_also_checks_the_lock(self):
        self.mod.duel_lock_fresh = lock_sequence(True)
        srv = self.server(opening=16, replies=[60])              # she jumps above our first ask: crossed
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(r["result"], "deal")
        self.assertEqual(len(self.events("accept_deferred_lock")), 1)
        self.assertEqual(srv.accepted[0][1], 60)

    def test_rate_limited_accept_is_not_resent_into_a_fresh_lock(self):
        # item 2: the first accept is rate_limited; the duel lock turns fresh right after it, for 40 s (under 3
        # ticks). No accept may reach the server while the lock is fresh: the SDK must not resend it.
        srv = self.server(opening=25, opening_final=True, expiry=100)
        srv.inject["accept"] = [(429, "rate_limited")]

        def lock(*_a):
            return srv.first_accept_at is not None and srv.vc.now < srv.first_accept_at + 40
        srv.lock_probe = lock
        self.mod.duel_lock_fresh = lock
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(srv.lock_violations, [])
        self.assertEqual(r["result"], "deal")
        self.assertTrue(self.events("accept_deferred_lock"))
        self.assertEqual(self.events("accept_refused")[0]["code"], "rate_limited")

    def test_lock_that_stays_fresh_times_out(self):
        # item 6: the lock never clears; after --max-defer-ticks the thread is closed through the safe path
        self.mod.duel_lock_fresh = lambda *a: True
        self.mod.MAX_DEFER_TICKS = 5
        srv = self.server(opening=25, opening_final=True, expiry=100, max_requests=600)
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(r["result"], "lock_timeout")
        self.assertEqual(srv.accepted, [])
        self.assertEqual(srv.writes("accept"), [])
        self.assertEqual(srv.status(), "closed")
        self.assertEqual(len(self.events("accept_deferred_lock")), 6)   # 5 deferred ticks, then the timeout check


class TestLockChato(LockCases, ServerCase):
    pass


class TestLockAbuela(LockCases, ServerCase):
    mod, dealer = abuela, "abuela"


# ---------------------------------------------------------------- D3: refused writes

class WriteCases:
    def test_refused_accept_rereads_and_takes_the_replaced_offer(self):
        srv = self.server(opening=25, opening_final=True)
        srv.teammate_accepts.add(100)                            # a teammate used the team's accept this tick

        def replace(s, t):
            if t == 101:
                s.post(24, final=True, t=t)                      # the dealer replaced her offer meanwhile
        srv.hooks.append(replace)
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(r["result"], "deal")
        ids = srv.accept_ids()
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])                      # the second accept names the new offer
        self.assertEqual(srv.accepted[0][1:], (24, 101))
        self.assertEqual(self.events("accept_refused")[0]["code"], "wait_for_tick")

    def test_refused_message_is_not_counted_as_said(self):
        srv = self.server(opening=16)
        srv.inject["say"] = [(429, "wait_for_tick")]
        self.mod.MAX_ROUNDS = 3
        self.run_thread(srv, sell_target(42, "MAL-06", 20))
        sent = srv.writes("messages")
        self.assertEqual([t for t, _, _ in sent[:2]], [100, 101])   # refused at 100, sent again at 101
        self.assertEqual(srv.said[0][0], 101)
        self.assertEqual(srv.said[0][1], self.events("say_refused")[0]["price"])   # same number, not skipped

    def test_rate_limited_message_is_not_resent_in_the_same_tick(self):
        # item 11: the SDK must not resend a rate_limited message 0.25 s later (run_thread checks every tick)
        srv = self.server(opening=16)
        srv.inject["say"] = [(429, "rate_limited")]
        self.mod.MAX_ROUNDS = 3
        self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(self.events("say_refused")[0]["code"], "rate_limited")
        self.assertEqual(srv.said[0][0], 101)

    def test_accept_refused_every_time_never_raises_and_closes(self):
        srv = self.server(opening=25, opening_final=True, expiry=100)
        srv.inject["accept"] = [(409, "insufficient_cash")] * 50
        self.mod.MAX_ROUNDS = 3
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(r["result"], "max_rounds")
        self.assertEqual(srv.status(), "closed")                 # closed, not left open
        self.assertLessEqual(len(srv.writes("accept")), 3 + 2)   # the budget, then at most 2 fresh attempts

    def test_refused_close_on_a_walk_is_retried(self):
        srv = self.server(opening=16, final=15, expiry=100)      # final below the floor: we walk
        srv.inject["close"] = [(429, "wait_for_tick")]
        r = self.run_thread(srv, sell_target(42, "MAL-06", 40))
        self.assertEqual(r["result"], "walked_by_us")
        self.assertEqual(srv.status(), "closed")
        self.assertEqual(len(srv.writes("close")), 2)

    def test_close_refused_every_time_reports_close_failed(self):
        # item 3: the dealer's only conversation slot stays occupied: say so, do not report a walk
        srv = self.server(opening=16, final=15, expiry=100)
        srv.inject["close"] = [(503, "unavailable")] * 20
        r = self.run_thread(srv, sell_target(42, "MAL-06", 40))
        self.assertEqual(r["result"], "close_failed")
        self.assertEqual(r["thread"], 7)
        self.assertEqual(srv.status(), "open")
        self.assertTrue(self.events("close_failed"))

    def test_refused_close_rereads_and_takes_the_improved_final(self):
        # item 5: reservation 80, his final ask 90, close refused; next tick his final is 70: take it, do not close
        self.mod.CASH_RESERVE = 0
        srv = self.server(side="buy", item="LAV-09", opening=90, opening_final=True, expiry=100)
        srv.inject["close"] = [(429, "wait_for_tick")]

        def soften(s, t):
            if t == 101:
                s.post(70, final=True, t=t)
        srv.hooks.append(soften)
        r = self.run_thread(srv, buy_target("LAV-09", 80))
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 70)
        self.assertEqual(srv.closes, [])

    def test_refusal_on_the_last_round_keeps_a_valid_final(self):
        # item 4: the final arrives with one round left and a teammate holds this tick's accept
        self.mod.MAX_ROUNDS = 1
        srv = self.server(opening=25, opening_final=True, expiry=100)
        srv.teammate_accepts.add(100)
        r = self.run_thread(srv, sell_target(42, "MAL-06", 20))
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1:], (25, 101))

    def test_resume_survives_a_failing_first_read(self):
        # item 9: the first read of a resumed thread fails; the bot recovers and continues from our last number
        srv = self.server(opening=16)
        srv.preopen(ours=30, theirs=17)
        srv.inject["thread"] = [(503, "unavailable")]
        self.mod.MAX_ROUNDS = 2
        self.run_thread(srv, sell_target(42, "MAL-06", 20), resume=7)
        self.assertEqual(self.events("resume")[0]["ours"], 30)
        self.assertTrue(srv.said)
        self.assertLess(srv.said[0][1], 30)                      # continues down from 30, never steps back up
        self.assertTrue(self.events("read_refused"))


class TestWritesChato(WriteCases, ServerCase):
    pass


class TestWritesAbuela(WriteCases, ServerCase):
    mod, dealer = abuela, "abuela"

    def test_refusal_on_the_last_round_keeps_the_welcome_deal(self):
        # item 4: the first deal's welcome price (<= 0.75 x book) with one round left, accept slot taken this tick
        abuela.MAX_ROUNDS = 1
        srv = self.server(side="buy", item="LAV-01", opening=7, expiry=100)
        srv.teammate_accepts.add(100)
        r = self.run_thread(srv, buy_target("LAV-01", 12, book=10), first_deal=True)
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1:], (7, 101))


# ---------------------------------------------------------------- D4: clock trouble during a pause

class PauseCases:
    def test_clock_errors_during_a_pause_spend_no_rounds(self):
        # item 7: 75-minute pause; for 70 minutes of it the clock endpoint times out. Her final (41, above our floor
        # 40) comes at tick 104; with a 5-round budget we only see it if the failing minutes cost no rounds.
        srv = self.server(opening=16, pause=(20.0, 20.0 + 75 * 60), clock_down=(30.0, 30.0 + 70 * 60), expiry=10 ** 6)

        def final_at_104(s, t):
            if t == 104:
                s.post(41, final=True, t=t)
        srv.hooks.append(final_at_104)
        self.mod.MAX_ROUNDS = 5
        r = self.run_thread(srv, sell_target(42, "MAL-06", 40))
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1], 41)


class TestPauseChato(PauseCases, ServerCase):
    pass


class TestPauseAbuela(PauseCases, ServerCase):
    mod, dealer = abuela, "abuela"


if __name__ == "__main__":
    unittest.main()
