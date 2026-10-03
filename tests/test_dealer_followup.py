"""Post-merge audit of PR #35: five failure-recovery defects in the dealer bots (agent/chato.py, agent/abuela.py),
each reproduced against the fake game server through the real kit SDK and the bots' real client.

1. The printed resume command must carry every limit and override the operator passed (--cap above all).
2. A trade whose accept went out but whose settlement could not be confirmed stops the plan (exit 6).
3. No decision or write before a tick is confirmed; a clock that stays lost ends the thread (bounded).
4. The terminal status and its line never depend on the final account read.
5. --resume is not skipped by the new-conversation cash check; the resumed thread is resolved inside its limit.

    python3 -m unittest discover tests
"""
import shlex
import unittest

from dealer_fakes import (BazaarError, FakeAccount, FakeServer, NullRun, abuela, chato, lock_sequence,
                          restore_globals, run_main, save_globals, sell_target)

CARDS = [{"id": "LAV-09", "rarity": "rare", "name": "LAV-09", "book": 77},
         {"id": "LAV-08", "rarity": "rare", "name": "LAV-08", "book": 77},
         {"id": "LAV-01", "rarity": "common", "name": "LAV-01", "book": 10},
         {"id": "LAV-02", "rarity": "common", "name": "LAV-02", "book": 10}]
VALUES = {"LAV-09": 90, "LAV-08": 90, "LAV-01": 12, "LAV-02": 12}


def mal06():
    return {"id": 42, "ref": "MAL-06", "kind": "card", "rarity": "uncommon", "serial": 5, "your_value": 16,
            "name": "MAL-06"}


def buy_server(mod, ask, final=True, **kw):
    item = "LAV-09" if mod is chato else "LAV-01"
    kw.setdefault("cash", 1000)
    return FakeServer(dealer=mod.DEALER, side="buy", item=item, opening=ask, opening_final=final, expiry=100,
                      cards=CARDS, values=VALUES, max_requests=3000, **kw)


def resume_argv(out):
    """The argv of the command the bot printed for continuing a thread (everything after the script path)."""
    lines = [ln for ln in out.splitlines() if "Continue it with: " in ln]
    assert len(lines) == 1, out
    tokens = shlex.split(lines[0].split("Continue it with: ", 1)[1])
    assert tokens[0] == "python3" and tokens[1].startswith("agent/"), tokens
    return tokens[2:]


def fail_after(kind, count_writes, n=50, code=(503, "unavailable")):
    """A request hook: once the bot has sent `count_writes` writes of that kind, every `kind` request fails."""
    fired = []

    def hook(s, method, path):
        if not fired and len(s.writes(count_writes[0])) >= count_writes[1]:
            s.inject[kind] = [code] * n
            fired.append(1)
    return hook


# ---------------------------------------------------------------- 1: the resume command keeps the limits

class ResumeCommandCases:
    mod = chato
    cap, ask = "50", 80       # private value 90 (chato) / 12 (abuela); the operator capped it below the ask

    def test_following_the_printed_command_keeps_the_cap(self):
        item = "LAV-09" if self.mod is chato else "LAV-01"
        srv = buy_server(self.mod, self.ask)
        srv.inject["close"] = [(503, "unavailable")] * 3            # the first run cannot close: exit 4
        code, out, _, _ = run_main(self.mod, ["run", "--only", item, "--max-deals", "1", "--cap", self.cap],
                                   server=srv)
        self.assertEqual(code, self.mod.EXIT_CLOSE_FAILED, out)
        argv = resume_argv(out)
        code2, out2, _, _ = run_main(self.mod, argv, server=srv)  # the operator follows the printed line
        self.assertEqual(srv.accepted, [], f"the resumed run took {self.ask} above the --cap {self.cap}:\n{out2}")
        self.assertEqual(srv.status(), "closed")


class TestResumeCommandChato(ResumeCommandCases, unittest.TestCase):
    def roundtrip(self, argv, server):
        code, out, _, _ = run_main(chato, argv, server=server)
        self.assertEqual(code, chato.EXIT_CLOSE_FAILED, out)
        return chato.parse_args(argv), chato.parse_args(resume_argv(out))

    def assert_same(self, a, b, fields):
        for f in fields:
            self.assertEqual(getattr(b, f), getattr(a, f), f)

    def test_sell_overrides_survive_the_resume_command(self):
        srv = FakeServer(dealer="pilar", opening=16, final=15, expiry=100, assets=[mal06()], max_requests=3000)
        srv.inject["close"] = [(503, "unavailable")] * 3
        argv = ["run", "--dealer", "pilar", "--only", "sell:42", "--allow-single", "--floor", "18",
                "--sell-anchor", "27", "--sell-step", "1", "--reserve", "200", "--max-rounds", "20",
                "--max-defer-ticks", "9", "--cap", "50"]
        a, b = self.roundtrip(argv, srv)
        self.assert_same(a, b, ("dealer", "only", "allow_single", "floor", "sell_anchor", "sell_step", "reserve",
                                "max_rounds", "max_defer_ticks", "cap"))
        self.assertEqual(b.resume, 7)

    def test_buy_overrides_survive_the_resume_command(self):
        srv = buy_server(chato, 97)
        srv.inject["close"] = [(503, "unavailable")] * 3
        argv = ["run", "--only", "LAV-09", "--cap", "93", "--anchor", "60", "--step", "4", "--max-bid", "84",
                "--reserve", "200"]
        a, b = self.roundtrip(argv, srv)
        self.assert_same(a, b, ("dealer", "only", "cap", "anchor", "step", "max_bid", "reserve"))
        self.assertEqual(b.resume, 7)


class TestResumeCommandAbuela(ResumeCommandCases, unittest.TestCase):
    mod, cap, ask = abuela, "8", 10


# ---------------------------------------------------------------- 2: unresolved settlement stops the plan

class BotState:
    """Module globals set for a direct negotiate() call, and put back afterwards."""

    def setUp(self):
        self.saved = save_globals(self.mod)
        self.mod.RUN, self.mod.duel_lock_fresh = NullRun(), lock_sequence()
        if self.mod is chato:
            chato.apply_dealer("chato")
        self.mod.MAX_ROUNDS, self.mod.CASH_RESERVE, self.mod.MAX_DEFER_TICKS = 12, 280, 60

    def tearDown(self):
        restore_globals(self.mod, self.saved)

    def negotiate(self, srv):
        with srv.serving():
            return self.mod.negotiate(srv.client(self.mod), sell_target(42, "MAL-06", 20), False)


class SettleCases(BotState):
    def test_unreadable_thread_after_an_accept_is_unsettled(self):
        srv = FakeServer(dealer=self.mod.DEALER, opening=25, opening_final=True, expiry=100)
        srv.request_hooks.append(fail_after("thread", ("accept", 1)))
        r = self.negotiate(srv)
        self.assertEqual(srv.status(), "deal")                      # the server did the trade
        self.assertEqual(r["result"], "unsettled")

    def test_frozen_clock_after_an_accept_is_unsettled_not_open(self):
        srv = FakeServer(dealer=self.mod.DEALER, opening=25, opening_final=True, expiry=100, frozen=(1.0, 5000.0))
        r = self.negotiate(srv)
        self.assertEqual(len(srv.accepted), 1)
        self.assertEqual(r["result"], "unsettled")

    def test_run_stops_the_plan_on_an_unsettled_trade(self):
        items = "LAV-09,LAV-08" if self.mod is chato else "LAV-01,LAV-02"
        srv = buy_server(self.mod, 10 if self.mod is abuela else 80)
        srv.request_hooks.append(fail_after("thread", ("accept", 1)))
        code, out, _, _ = run_main(self.mod, ["run", "--only", items, "--max-deals", "1"], server=srv)
        opened = [r for r in srv.requests if r[1:] == ("POST", "/api/threads")]
        self.assertEqual(len(opened), 1, "a second trade was started while the first was unconfirmed")
        self.assertEqual(code, self.mod.EXIT_UNSETTLED, out)
        self.assertTrue(any("Thread 7" in ln and "settle" in ln for ln in out.splitlines()), out)

    def test_unsettled_line_names_the_side_and_the_card(self):
        item = "LAV-09" if self.mod is chato else "LAV-01"
        srv = buy_server(self.mod, 10 if self.mod is abuela else 80)
        srv.request_hooks.append(fail_after("thread", ("accept", 1)))
        code, out, _, _ = run_main(self.mod, ["run", "--only", item, "--max-deals", "1"], server=srv)
        self.assertEqual(code, self.mod.EXIT_UNSETTLED, out)
        lines = [ln for ln in out.splitlines() if "Thread 7" in ln and "settle" in ln]
        self.assertEqual(len(lines), 1, out)
        self.assertIn(f"buy {item}", lines[0])


class TestSettleChato(SettleCases, unittest.TestCase):
    mod = chato


class TestSettleAbuela(SettleCases, unittest.TestCase):
    mod = abuela


# ---------------------------------------------------------------- 3: no decision before a confirmed tick

class ClockLostCases(BotState):
    def test_negotiation_ends_when_the_clock_stays_unreadable(self):
        # the clock never answers: the thread must still end (closed, distinct result), not loop forever
        self.mod.MAX_ROUNDS = 2
        srv = FakeServer(dealer=self.mod.DEALER, opening=16, clock_down=(0.0, 1e9), max_requests=3000)
        r = self.negotiate(srv)
        self.assertEqual(r["result"], "clock_lost")
        self.assertEqual(srv.status(), "closed")
        self.assertLess(srv.vc.now, 3600.0)

    def test_clock_recovering_during_the_close_lets_the_bot_take_an_in_limit_final(self):
        # Codex timeline on #38: sell floor 40; the clock is unreadable from second 1 to 380, long enough for the
        # clock to count as lost; the first close is refused (503); the clock recovers and confirms tick 126, and
        # her final 41 (posted at tick 123, lapsing at 127) is still standing: take it, do not close on it.
        srv = FakeServer(dealer=self.mod.DEALER, opening=16, clock_down=(1.0, 380.0), max_requests=3000)
        srv.inject["close"] = [(503, "unavailable")]

        def final_at_123(s, t):
            if t == 123:
                s.post(41, final=True, t=t)
        srv.hooks.append(final_at_123)
        r = self.negotiate(srv)
        self.assertEqual(len(srv.writes("close")), 1)                # the refused one: no second close
        self.assertEqual(r["result"], "deal")
        self.assertEqual(srv.accepted[0][1:], (41, 126))

    def test_frozen_game_never_gets_a_resend_in_the_same_tick(self):
        # tick 100 frozen for 90 s: a refused message may only go out again once tick 101 is confirmed
        self.mod.MAX_ROUNDS = 3
        srv = FakeServer(dealer=self.mod.DEALER, opening=16, frozen=(0.0, 90.0))
        srv.inject["say"] = [(429, "rate_limited")]
        self.negotiate(srv)
        self.assertEqual(srv.same_tick_resends(), [])
        self.assertGreater(srv.said[0][0], 100)


class TestClockLostChato(ClockLostCases, unittest.TestCase):
    mod = chato

    def test_stall_counts_ticks_not_reads(self):
        # thread 335 shape with our limit 88 under his 90: the max-bid stall may close only after two real ticks.
        # The game freezes at tick 107 (his 90) for 90 s.
        chato.MAX_ROUNDS, chato.ANCHOR_ABS, chato.STEP, chato.MAX_BID, chato.CASH_RESERVE = 16, 60, 4, 84, 200
        srv = FakeServer(dealer="chato", side="buy", item="LAV-09", opening=97, replies=[97, 97, 97, 97, 96, 94, 90],
                         cash=383, frozen=(106.0, 196.0))
        with srv.serving():
            r = chato.negotiate(srv.client(chato), {"side": "buy", "item": "LAV-09", "value": 88.0}, False)
        self.assertEqual(r["result"], "max_bid_no_deal")
        self.assertGreaterEqual(srv.closes[0], 109)               # his 90 came at 107: two confirmed ticks later


class TestClockLostAbuela(ClockLostCases, unittest.TestCase):
    mod = abuela


# ---------------------------------------------------------------- 4: terminal status before the account read

class FinalReadCases:
    mod = chato

    def test_close_failed_status_survives_a_failing_account_read(self):
        item = "LAV-09" if self.mod is chato else "LAV-01"
        srv = buy_server(self.mod, 97 if self.mod is chato else 30)
        srv.inject["close"] = [(503, "unavailable")] * 3
        srv.request_hooks.append(fail_after("me", ("close", 3)))
        code, out, _, _ = run_main(self.mod, ["run", "--only", item, "--max-deals", "1"], server=srv)
        self.assertEqual(code, self.mod.EXIT_CLOSE_FAILED, out)
        self.assertTrue(resume_argv(out))

    def test_reserve_status_survives_a_failing_account_read(self):
        class Flaky(FakeAccount):
            made, cash, calls = [], 169, []

            def me(self):
                Flaky.calls.append(1)
                if len(Flaky.calls) >= 3:                           # start, the cash check, then the summary
                    raise BazaarError("unavailable", "fake", 503)
                return super().me()
        item = "LAV-09" if self.mod is chato else "LAV-01"
        code, out, _, _ = run_main(self.mod, ["run", "--only", item], Flaky)
        self.assertEqual(code, self.mod.EXIT_RESERVE, out)
        self.assertEqual(len([ln for ln in out.splitlines() if "--reserve" in ln]), 1, out)


class TestFinalReadChato(FinalReadCases, unittest.TestCase):
    mod = chato


class TestFinalReadAbuela(FinalReadCases, unittest.TestCase):
    mod = abuela


# ---------------------------------------------------------------- 5: --resume is not skipped for cash

class ResumeCashCases:
    mod = chato

    def test_resume_reads_and_resolves_the_thread_despite_low_cash(self):
        # buy thread 7 left open with our last bid; cash 282 against the 280 reserve: the cash check for a NEW
        # conversation must not skip the resume. We may spend 2 P at most, under our own bid: close it.
        item = "LAV-09" if self.mod is chato else "LAV-01"
        srv = buy_server(self.mod, 97 if self.mod is chato else 30, final=False, cash=282)
        srv.preopen(ours=60 if self.mod is chato else 6, theirs=97 if self.mod is chato else 30)
        code, out, _, _ = run_main(self.mod, ["run", "--only", item, "--resume", "7", "--max-deals", "1"],
                                   server=srv)
        self.assertTrue(any(r[1:] == ("GET", "/api/threads/7") for r in srv.requests), "thread 7 was never read")
        self.assertNotEqual(code, self.mod.EXIT_RESERVE, out)
        self.assertEqual(srv.status(), "closed")
        self.assertEqual(srv.accepted, [])
        self.assertEqual(srv.said, [])                              # never a new number above what we may spend


    def test_resume_with_no_number_of_ours_and_no_spendable_cash_closes(self):
        # the earlier run opened the thread and died before saying a number; cash 270 is under the 280 reserve:
        # nothing may be bid at all, so the resumed thread is closed (never a zero or negative bid)
        item = "LAV-09" if self.mod is chato else "LAV-01"
        srv = buy_server(self.mod, 97 if self.mod is chato else 30, final=False, cash=270)
        srv.thread = {"id": 7, "status": "open", "closed_reason": None, "opened": srv.tick()}
        srv.post(srv.opening)
        code, out, _, _ = run_main(self.mod, ["run", "--only", item, "--resume", "7", "--max-deals", "1"],
                                   server=srv)
        self.assertEqual(srv.said, [], out)
        self.assertEqual(srv.status(), "closed")
        self.assertNotEqual(code, self.mod.EXIT_RESERVE, out)


class TestResumeCashChato(ResumeCashCases, unittest.TestCase):
    mod = chato


class TestResumeCashAbuela(ResumeCashCases, unittest.TestCase):
    mod = abuela


if __name__ == "__main__":
    unittest.main()
