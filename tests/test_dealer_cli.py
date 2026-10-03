"""The dealer bots' command line (agent/chato.py, agent/abuela.py), against a fake account, no key, no network:

- D5: when the 280 P team reserve blocks every buy, say so on one line (how to pass --reserve), log it, and exit with
  its own status instead of finishing silently. The 280 default stays.
- D6: Doña Pilar's slow defaults (first ask about floor + 9, 1 P steps, 40 rounds); explicit flags still win.

    python3 -m unittest discover tests
"""
import unittest

from dealer_fakes import FakeAccount, FakeServer, abuela, chato, run_main


class Poor(FakeAccount):
    made = []
    cash = 169   # the team's cash at lunch on Saturday


class Rich(FakeAccount):
    made = []
    cash = 1000


def mal06():
    return {"id": 42, "ref": "MAL-06", "kind": "card", "rarity": "uncommon", "serial": 5, "your_value": 16,
            "name": "MAL-06"}


class WithMal06(FakeAccount):
    made = []
    assets = [mal06()]


# ---------------------------------------------------------------- D5

class ReserveCases:
    mod = chato
    item = "LAV-09"

    def test_every_buy_blocked_by_the_reserve_exits_with_its_own_status(self):
        code, out, run, _ = run_main(self.mod, ["run", "--only", self.item], Poor)
        self.assertIsNotNone(code, "main() finished silently with every buy skipped:\n" + out)
        self.assertNotIn(code, (0, 1, 2))                        # distinct from success, crashes and usage errors
        self.assertEqual(code, self.mod.EXIT_RESERVE)
        lines = [ln for ln in out.splitlines() if "--reserve" in ln]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("280", lines[0])
        self.assertEqual(len(run.named("reserve_blocks_buys")), 1)
        self.assertEqual(run.named("reserve_blocks_buys")[0]["reserve"], 280)

    def test_default_reserve_is_still_280(self):
        self.assertEqual(self.mod.CASH_RESERVE, 280)
        _, out, _, after = run_main(self.mod, ["plan", "--only", self.item], Poor)
        self.assertIn("reserve=280", out)

    def test_plan_mode_never_exits_on_the_reserve(self):
        code, out, run, _ = run_main(self.mod, ["plan", "--only", self.item], Poor)
        self.assertIsNone(code)


class TestReserveChato(ReserveCases, unittest.TestCase):
    mod = chato
    item = "LAV-09"


class TestReserveAbuela(ReserveCases, unittest.TestCase):
    mod = abuela
    item = "LAV-01"


# ---------------------------------------------------------------- D6

class TestPilarDefaults(unittest.TestCase):
    def test_pilar_defaults_are_slow(self):
        code, out, _, after = run_main(chato, ["plan", "--dealer", "pilar", "--only", "sell:42", "--allow-single"],
                                       WithMal06)
        self.assertIsNone(code, out)
        self.assertEqual(after["MAX_ROUNDS"], 40)
        self.assertEqual(after["SELL_STEP"], 1)
        self.assertEqual(after["SELL_ANCHOR_OVER_FLOOR"], 9)

    def test_first_ask_is_floor_plus_9(self):
        saved = (chato.SELL_ANCHOR_MULT, chato.SELL_ANCHOR_OVER_FLOOR, chato.SELL_ANCHOR_ABS, chato.SELL_STEP)
        try:
            chato.apply_dealer("pilar")
            self.assertEqual(chato.sell_anchor(16, 18), 27)          # the measured pattern: floor 18 -> ask 27
            self.assertEqual(chato.sell_ladder(16, 18), list(range(27, 17, -1)))
        finally:
            chato.apply_dealer("chato")
            (chato.SELL_ANCHOR_MULT, chato.SELL_ANCHOR_OVER_FLOOR, chato.SELL_ANCHOR_ABS, chato.SELL_STEP) = saved

    def test_explicit_flags_win(self):
        argv = ["plan", "--dealer", "pilar", "--only", "sell:42", "--allow-single",
                "--max-rounds", "20", "--sell-step", "3", "--sell-anchor", "30"]
        code, out, _, after = run_main(chato, argv, WithMal06)
        self.assertIsNone(code, out)
        self.assertEqual((after["MAX_ROUNDS"], after["SELL_STEP"], after["SELL_ANCHOR_ABS"]), (20, 3, 30))

    def test_chato_defaults_unchanged(self):
        code, out, _, after = run_main(chato, ["plan", "--only", "LAV-09"], Rich)
        self.assertIsNone(code, out)
        self.assertEqual((after["MAX_ROUNDS"], after["SELL_STEP"], after["SELL_ANCHOR_MULT"],
                          after["SELL_ANCHOR_OVER_FLOOR"]), (12, 2, 1.6, 0))

    def test_max_rounds_flag_wins_for_chato_too(self):
        _, _, _, after = run_main(chato, ["plan", "--only", "LAV-09", "--max-rounds", "7"], Rich)
        self.assertEqual(after["MAX_ROUNDS"], 7)


# ---------------------------------------------------------------- items 3 and 6: stop with a distinct status

CARDS = [{"id": "LAV-09", "rarity": "rare", "name": "LAV-09", "book": 77},
         {"id": "LAV-01", "rarity": "common", "name": "LAV-01", "book": 10}]
VALUES = {"LAV-09": 90, "LAV-01": 12}


class StopCases:
    """Run main() end to end against the fake server with the bot's real client (one buy, max 1 deal)."""
    mod, item = chato, "LAV-09"
    too_high, good = 97, 80        # final asks above and inside our limit (chato: 90; abuela below)

    def server(self, ask):
        return FakeServer(dealer=self.mod.DEALER, side="buy", item=self.item, opening=ask, opening_final=True,
                          expiry=100, cash=1000, cards=CARDS, values=VALUES, max_requests=2000)

    def test_close_failed_exits_with_its_own_status_and_names_the_resume_command(self):
        srv = self.server(self.too_high)                         # final above our limit: we walk
        srv.inject["close"] = [(503, "unavailable")] * 50
        code, out, run, _ = run_main(self.mod, ["run", "--only", self.item, "--max-deals", "1"], server=srv)
        self.assertIsNotNone(code, "main() finished as if the thread were closed:\n" + out)
        self.assertNotIn(code, (0, 1, 2, 3))
        self.assertEqual(code, self.mod.EXIT_CLOSE_FAILED)
        lines = [ln for ln in out.splitlines() if "--resume 7" in ln]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("Thread 7", lines[0])
        self.assertIn(f"--only {self.item}", lines[0])
        self.assertEqual(srv.status(), "open")

    def test_lock_timeout_exits_with_its_own_status(self):
        srv = self.server(self.good)
        calls = []

        def lock(*_a):                                           # clear when run starts, fresh from then on
            calls.append(1)
            return len(calls) > 1
        code, out, run, _ = run_main(self.mod, ["run", "--only", self.item, "--max-deals", "1",
                                                "--max-defer-ticks", "3"], server=srv, lock=lock)
        self.assertNotIn(code, (None, 0, 1, 2, 3, 4), out)
        self.assertEqual(code, self.mod.EXIT_LOCK_TIMEOUT)
        self.assertEqual(srv.accepted, [])
        self.assertEqual(srv.status(), "closed")
        self.assertEqual(len([ln for ln in out.splitlines() if "duel lock" in ln]), 1, out)

    def test_max_defer_ticks_defaults_to_60(self):
        class Rich2(FakeAccount):
            made = []
            cash = 1000
        _, _, _, after = run_main(self.mod, ["plan", "--only", self.item], Rich2)
        self.assertEqual(after.get("MAX_DEFER_TICKS"), 60)


class TestStopChato(StopCases, unittest.TestCase):
    pass


class TestStopAbuela(StopCases, unittest.TestCase):
    mod, item = abuela, "LAV-01"
    too_high, good = 30, 10


if __name__ == "__main__":
    unittest.main()
