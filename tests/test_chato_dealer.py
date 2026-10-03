"""agent/chato.py with --dealer: Chato's selling path unchanged by default, Pilar's big-step schedule above the floor,
and last copies sold only when named by asset id with --allow-single. A fake dealer, no key, no network.

    python3 -m unittest discover -s tests
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))

import chato  # noqa: E402


class NullRun:
    """Stands in for RunLog so tests never append to the committed logs/chato/<date>.jsonl."""

    def __init__(self):
        self.events = []

    def event(self, event, **data):
        self.events.append((event, data))

    def start(self, **data):
        self.events.append(("run_start", data))

    def end(self, **data):
        self.events.append(("run_end", data))


class FakeDealer:
    """One dealer thread. She bids `opening`, answers each of our messages with the next number in `script` (or holds
    her last bid), and names `final` once we stop moving for a tick. accept/close end the thread."""

    def __init__(self, dealer, asset_id, opening, script=(), final=None):
        self.dealer, self.asset_id = dealer, asset_id
        self.script, self.final = list(script), final
        self.calls, self.says = [], []
        self.status, self.next_id, self.moved = "open", 100, False
        self.offer = None
        self._post(opening)

    def _post(self, price, final=False):
        self.next_id += 1
        self.offer = {"id": self.next_id, "maker": self.dealer, "status": "open", "final": final,
                      "give": {"cash": price}, "want": {"assets": [{"id": self.asset_id}]}}

    def open_thread(self, with_, topic=None, venue=None):
        self.calls.append(("open_thread", with_, topic))
        return {"id": 7}

    def thread(self, tid):
        return {"id": tid, "status": self.status, "standing_offers": [self.offer] if self.status == "open" else [],
                "messages": []}

    def say(self, tid, text="", price=None, offer=None, topic=None):
        self.calls.append(("say", price))
        self.says.append(price)
        self.moved = True
        self._post(self.script.pop(0) if self.script else self.offer["give"]["cash"])
        return {}

    def wait_tick(self):
        if self.status == "open" and not self.moved and self.final is not None and not self.offer["final"]:
            self._post(self.final, final=True)  # we stopped moving: her patience runs out
        self.moved = False
        return {}

    def accept(self, oid):
        self.calls.append(("accept", oid, self.offer["give"]["cash"]))
        self.status = "deal"
        return {}

    def close_thread(self, tid):
        self.calls.append(("close", tid))
        self.status = "walked"
        return {}

    def me(self):
        return {"cash": 1000}


def sell_target(asset_id, ref, your_value):
    return {"side": "sell", "item": ref, "asset_id": asset_id, "value": your_value + 2, "private": your_value}


class DealerCase(unittest.TestCase):
    def setUp(self):
        self._run = chato.RUN
        chato.RUN = NullRun()
        chato.apply_dealer("chato")
        chato.MAX_ROUNDS = 12

    def tearDown(self):
        chato.apply_dealer("chato")
        chato.RUN = self._run
        chato.MAX_ROUNDS = 12


class TestChatoUnchanged(DealerCase):
    def test_defaults_match_old_constants(self):
        self.assertEqual(chato.DEALER, "chato")
        self.assertEqual(chato.DEALER_NAME, "El Chato")
        self.assertEqual(chato.SELL_ANCHOR_MULT, 1.6)
        self.assertEqual(chato.SELL_STEP, 2)
        self.assertEqual(chato.SELL_ANCHOR_OVER_FLOOR, 0)
        self.assertIsNone(chato.SELL_ANCHOR_ABS)
        self.assertEqual(chato.SELL_RARITIES, ("uncommon", "rare"))
        args = chato.parse_args(["run", "--only", "sell:51"])
        self.assertEqual((args.dealer, args.allow_single, args.sell_anchor, args.sell_step), ("chato", False, None, None))

    def test_old_ask_sequence_and_crossed_accept(self):
        # old code: first ask round(13 x 1.6) = 21, then -2 per round; at 13 his bid crosses our ask (floor 12)
        b = FakeDealer("chato", 51, opening=13)
        r = chato.negotiate(b, sell_target(51, "SAL-03", 10), False)
        self.assertEqual(b.calls[0], ("open_thread", "chato", {"sell": {"assets": [51]}}))
        self.assertEqual(b.says, [21, 19, 17, 15])
        self.assertEqual(b.calls[-1][0], "accept")
        self.assertEqual(b.calls[-1][2], 13)
        self.assertEqual(r["result"], "deal")
        self.assertEqual(chato.sell_ladder(13, 12), [21, 19, 17, 15, 13, 12])

    def test_old_floor_then_walk_on_low_final(self):
        # floor 22: 21 -> clamped to 22 at once, pinned, his final 15 is below the floor: we walk
        b = FakeDealer("chato", 51, opening=13, final=15)
        r = chato.negotiate(b, sell_target(51, "SAL-03", 20), False)
        self.assertEqual(b.says, [22])
        self.assertEqual(b.calls[-1][0], "close")
        self.assertEqual(r["result"], "walked_by_us")


class TestPilar(DealerCase):
    def setUp(self):
        super().setUp()
        chato.apply_dealer("pilar")

    def test_thread_goes_to_pilar_with_big_steps_and_walks_below_floor(self):
        # MAL-06 single, private 17.5 -> floor ceil(19.5) = 20; she holds 16 and names 19 as her final
        b = FakeDealer("pilar", 42, opening=16, final=19)
        r = chato.negotiate(b, sell_target(42, "MAL-06", 17.5), False)
        self.assertEqual(b.calls[0], ("open_thread", "pilar", {"sell": {"assets": [42]}}))
        self.assertEqual(b.says, [48, 44, 40, 36, 32, 28, 24, 20])   # max(3 x 16, 20 + 20) = 48, then -4
        self.assertTrue(all(p >= 20 for p in b.says))
        self.assertNotIn("accept", [c[0] for c in b.calls])
        self.assertEqual(r["result"], "walked_by_us")
        self.assertEqual(chato.sell_ladder(16, 20), [48, 44, 40, 36, 32, 28, 24, 20])

    def test_final_at_or_above_floor_is_taken(self):
        b = FakeDealer("pilar", 42, opening=16, final=21)
        r = chato.negotiate(b, sell_target(42, "MAL-06", 17.5), False)
        self.assertEqual(b.calls[-1][0], "accept")
        self.assertEqual(b.calls[-1][2], 21)
        self.assertEqual(r["result"], "deal")

    def test_anchor_floor_plus_20_when_her_bid_is_low(self):
        # floor 51 (private 49): max(3 x 16 = 48, 51 + 20 = 71) = 71
        self.assertEqual(chato.sell_anchor(16, 51), 71)
        ladder = chato.sell_ladder(16, 51)
        self.assertEqual(ladder[:3], [71, 67, 63])
        self.assertEqual(ladder[-1], 51)
        self.assertTrue(all(p >= 51 for p in ladder))

    def test_overrides_never_go_below_floor(self):
        chato.apply_dealer("pilar", sell_anchor=30, sell_step=7)
        b = FakeDealer("pilar", 42, opening=16, final=19)
        chato.negotiate(b, sell_target(42, "MAL-06", 17.5), False)
        self.assertEqual(b.says, [30, 23, 20])
        chato.apply_dealer("pilar", sell_anchor=5)   # an anchor below the floor is clamped to it
        b = FakeDealer("pilar", 42, opening=16, final=19)
        chato.negotiate(b, sell_target(42, "MAL-06", 17.5), False)
        self.assertEqual(b.says, [20])

    def test_she_crosses_our_ask(self):
        b = FakeDealer("pilar", 42, opening=16, script=[45])
        r = chato.negotiate(b, sell_target(42, "MAL-06", 17.5), False)
        self.assertEqual(b.says, [48])
        self.assertEqual(b.calls[-1], ("accept", 102, 45))   # 45 >= our next ask 44
        self.assertEqual(r["result"], "deal")

    def test_offers_from_another_maker_are_ignored(self):
        b = FakeDealer("chato", 42, opening=40, final=40)   # wrong maker: never accepted, never answered
        chato.MAX_ROUNDS = 3
        r = chato.negotiate(b, sell_target(42, "MAL-06", 17.5), False)
        self.assertEqual(b.says, [])
        self.assertNotIn("accept", [c[0] for c in b.calls])
        self.assertEqual(r["result"], "max_rounds")

    def test_buy_targets_refused(self):
        b = FakeDealer("pilar", 42, opening=16)
        r = chato.negotiate(b, {"side": "buy", "item": "LAV-09", "value": 90}, False)
        self.assertEqual(r["result"], "refused")
        self.assertEqual(b.calls, [])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                chato.parse_args(["plan", "--dealer", "pilar", "--only", "LAV-09,sell:42"])
        args = chato.parse_args(["plan", "--dealer", "pilar", "--only", "sell:42,sell:44", "--allow-single"])
        self.assertEqual((args.dealer, args.allow_single), ("pilar", True))


# ---------------------------------------------------------------- what gets sold

def asset(aid, ref, rarity, serial, your_value, kind="card"):
    return {"id": aid, "ref": ref, "kind": kind, "rarity": rarity, "serial": serial, "your_value": your_value,
            "name": ref}


ME = {"cash": 400, "assets": [
    asset(42, "MAL-06", "uncommon", 5, 17.5),        # single
    asset(44, "MAL-08", "rare", 3, 49),              # single
    asset(50, "SAL-03", "uncommon", 3, 32.5),        # kept (lowest serial)
    asset(51, "SAL-03", "uncommon", 9, 8.1),         # spare
    asset(60, "LAV-01", "common", 2, 16),            # single common: no dealer here buys it
    asset(70, "RET-02", "epic", 1, 120),             # epic duplicate
    asset(71, "RET-02", "epic", 4, 30),
    asset(80, "SAL-07", "rare", 2, 91),              # single SAL: never auto-selected
    asset(90, "gold", "pack", 1, 0, kind="pack"),
]}


class FakeCatalog:
    def __init__(self):
        self.catalog_calls = 0

    def catalog(self):
        self.catalog_calls += 1
        return {"sets": [{"id": "LAV", "released": True, "cards": [
            {"id": "LAV-09", "rarity": "rare", "name": "LAV-09", "book": 77}]}]}

    def value(self, ref):
        return {"card": ref, "your_value": 90}


class TestPlan(DealerCase):
    def ids(self, plan, side="sell"):
        return [p["asset_id"] for p in plan if p["side"] == side]

    def test_chato_plan_unchanged(self):
        b = FakeCatalog()
        plan = chato.build_plan(b, ME, None, None)
        self.assertEqual(self.ids(plan), [51])                          # spare uncommon only, no epic, no singles
        self.assertEqual([p["item"] for p in plan if p["side"] == "buy"], ["LAV-09"])
        self.assertEqual(plan[0]["value"], 8.1 + 2)
        self.assertEqual(chato.build_plan(b, ME, ["sell:42"], None), [])  # last copy refused without the flag

    def test_last_copy_refused_without_flag_allowed_only_when_listed(self):
        chato.apply_dealer("pilar")
        b = FakeCatalog()
        self.assertEqual(chato.build_plan(b, ME, ["sell:42", "sell:44"], None), [])
        skips = chato.sell_skips(ME, ["sell:42", "sell:44"], [], False)
        self.assertTrue(all("--allow-single" in s for s in skips) and len(skips) == 2)
        plan = chato.build_plan(b, ME, ["sell:42", "sell:44"], None, allow_single=True)
        self.assertEqual(self.ids(plan), [42, 44])
        self.assertEqual([p["value"] for p in plan], [19.5, 51])        # floor = that copy's private value + 2
        self.assertTrue(all(p["single"] for p in plan))
        self.assertEqual(b.catalog_calls, 0)                             # Pilar: no buy targets at all

    def test_flag_never_auto_selects(self):
        chato.apply_dealer("pilar")
        plan = chato.build_plan(FakeCatalog(), ME, None, None, allow_single=True)
        self.assertEqual(sorted(self.ids(plan)), [51, 71])              # spares only (Pilar also buys epics)
        self.assertNotIn(80, self.ids(plan))
        plan = chato.build_plan(FakeCatalog(), ME, ["sell:42"], None, allow_single=True)
        self.assertEqual(self.ids(plan), [42])                          # only the listed one, not SAL-07 or others

    def test_flag_respects_what_the_dealer_buys(self):
        chato.apply_dealer("pilar")
        plan = chato.build_plan(FakeCatalog(), ME, ["sell:60", "sell:90", "sell:999"], None, allow_single=True)
        self.assertEqual(plan, [])
        skips = chato.sell_skips(ME, ["sell:60", "sell:90", "sell:999"], plan, True)
        self.assertIn("does not buy common", skips[0])
        self.assertIn("not a card", skips[1])
        self.assertIn("not one of our assets", skips[2])
        chato.apply_dealer("chato")
        self.assertEqual(chato.build_plan(FakeCatalog(), ME, ["sell:71"], None, allow_single=True), [])

    def test_allow_single_needs_listed_ids(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                chato.parse_args(["plan", "--allow-single"])
            with self.assertRaises(SystemExit):
                chato.parse_args(["plan", "--allow-single", "--only", "SAL-08"])
            with self.assertRaises(SystemExit):
                chato.parse_args(["plan", "--dealer", "pilar", "--only", "sell:42", "--sell-step", "0"])


if __name__ == "__main__":
    unittest.main()
