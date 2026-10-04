"""agent/duel.py for Duels III and the Final: the F4 flag (--last-while-moving) and the params file the Sunday
factory starts the duel bot with (docs/duel-lab/duel-params-duels3.json).

No network, no key. Run: python3 -m unittest discover tests
"""
import json
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
