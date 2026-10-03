"""Market desk eval (tools/eval_market.py): the grader's arithmetic and the harness checks on a tiny synthetic day.

Values to us (affinity LAV 1.6, MAL 0.7; book common 10, uncommon 25, rare 70; copies 1, 0.25, 0.1):
LAV-09 (rare) first copy 112; LAV-06 (uncommon) 40; MAL-06 (uncommon) 17.5, our second copy 4.375.

    python3 -m unittest tests.test_eval_market
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))

import eval_market as em  # noqa: E402
import market_desk as md  # noqa: E402

ME = "t03"


def catalog():
    sets = []
    for sid in ("LAV", "MAL"):
        cards = []
        for n in range(1, 13):
            r = (["common"] * 5 + ["uncommon"] * 3 + ["rare"] * 2 + ["epic", "legendary"])[n - 1]
            cards.append({"id": f"{sid}-{n:02d}", "rarity": r, "page": n <= 10, "hidden": False,
                          "book": {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}[r]})
        sets.append({"id": sid, "released": True, "cards": cards})
    return {"sets": sets, "values": {"copy_marginals": [1.0, 0.25, 0.1], "page_bonus": 0.25}}


def asset(aid, ref, serial=5):
    return {"id": aid, "kind": "card", "ref": ref, "serial": serial, "set": ref[:3], "rarity": "x"}


def listing(eid, tick, oid, maker, aid, ref, price, venue="rastro"):
    return {"id": eid, "tick": tick, "t": tick / 60, "type": "offer.listed", "actor": maker,
            "payload": {"venue": venue, "offer": {
                "id": oid, "maker": maker, "to": None, "venue": venue, "thread": None, "status": "open",
                "give": {"cash": 0, "assets": [asset(aid, ref)], "types": []},
                "want": {"cash": price, "assets": [], "types": []}, "expires_tick": tick + 30, "created_tick": tick}}}


def bid(eid, tick, oid, maker, ref, price, venue="rastro"):
    return {"id": eid, "tick": tick, "t": tick / 60, "type": "offer.listed", "actor": maker,
            "payload": {"venue": venue, "offer": {
                "id": oid, "maker": maker, "to": None, "venue": venue, "thread": None, "status": "open",
                "give": {"cash": price, "assets": [], "types": []},
                "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}, "expires_tick": tick + 30,
                "created_tick": tick}}}


def swap(eid, tick, oid, maker, aid, ref, want_ref):
    e = listing(eid, tick, oid, maker, aid, ref, 0)
    e["payload"]["offer"]["want"] = {"cash": 0, "assets": [], "types": [f"card:{want_ref}"]}
    return e


def day():
    """Tick 1: LAV-09 listed at 60 (in the money: 112 - 60 - 4 = +48) and LAV-06 at 50 (40 - 50 - 4 = -14).
    Tick 2: a bid of 20 for MAL-06, of which we hold two (20 - 2 - 4.375 = +13.6). Also a swap and an offer of
    ours, which are never cases."""
    return [
        {"id": 1, "tick": 0, "t": 0.0, "type": "day.opened", "actor": "", "payload": {"day": "fri"}},
        listing(2, 1, 501, "t05", 101, "LAV-09", 60),
        listing(3, 1, 502, "t06", 102, "LAV-06", 50),
        bid(4, 2, 503, "t07", "MAL-06", 20),
        swap(5, 2, 504, "t08", 103, "MAL-02", "LAV-01"),
        listing(6, 2, 505, ME, 3, "LAV-01", 9),
        {"id": 7, "tick": 5, "t": 5 / 60, "type": "day.closed", "actor": "", "payload": {"day": "fri"}},
    ]


def me():
    return {"id": ME, "tick": 0, "cash": 355, "affinity": {"LAV": 1.6, "MAL": 0.7},
            "assets": [asset(1, "MAL-06", 3), asset(2, "MAL-06", 9), asset(3, "LAV-01", 4)]}


def run(policy, cfg=None, events=None):
    return em.evaluate(events or day(), me(), catalog(), cfg or md.Config(team_venues=False), policy=policy)


class GraderArithmetic(unittest.TestCase):
    def test_fee_matches_the_server_rule_on_fridays_settlements(self):
        for price, fee in [(5, 2), (12, 2), (21, 3), (35, 3), (53, 4), (80, 5)]:
            self.assertEqual(em.venue_fee(price, md.DEFAULT_FEE), fee)
        self.assertEqual(em.venue_fee(70, (100, 0)), 1)

    def test_a_swap_listing_is_not_evidence_of_a_fill_but_a_cash_ask_is(self):
        ctx = em.Context(day(), catalog(), me())
        self.assertIsNone(em.verify_evidence(ctx, 2, "MAL-02", 30))
        self.assertIsNotNone(em.verify_evidence(ctx, 1, "LAV-09", 70))   # ask 60 <= 70 - 5 = 65
        self.assertIsNone(em.verify_evidence(ctx, 1, "LAV-09", 64))      # ask 60 > 64 - 5 = 59

    def test_a_free_or_cash_plus_card_listing_is_not_an_ask(self):
        free = listing(8, 3, 506, "t09", 104, "MAL-03", 0)                # gives a card, wants nothing: not an ask
        sweet = swap(9, 3, 507, "t12", 105, "MAL-07", "LAV-01")           # Saturday's shape: card + 19 P for a card
        sweet["payload"]["offer"]["give"]["cash"] = 19
        ctx = em.Context(day() + [free, sweet], catalog(), me())
        self.assertIsNone(em.verify_evidence(ctx, 3, "MAL-03", 30))
        self.assertIsNone(em.verify_evidence(ctx, 3, "MAL-07", 30))

    def test_a_listing_addressed_to_a_team_or_in_a_thread_is_not_evidence_of_a_fill(self):
        # Same cash ask as the open one at tick 1 (LAV-09 at 60, bid 70 nets 65), but not open to our bid.
        addressed = listing(8, 3, 506, "t09", 104, "MAL-03", 8)
        addressed["payload"]["offer"]["to"] = "t16"
        threaded = listing(9, 3, 507, "t12", 105, "MAL-07", 8)
        threaded["payload"]["offer"]["thread"] = 77
        open_ask = listing(10, 3, 508, "t13", 106, "MAL-04", 8)
        ctx = em.Context(day() + [addressed, threaded, open_ask], catalog(), me())
        self.assertIsNone(em.verify_evidence(ctx, 3, "MAL-03", 30))
        self.assertIsNone(em.verify_evidence(ctx, 3, "MAL-07", 30))
        self.assertIsNotNone(em.verify_evidence(ctx, 3, "MAL-04", 30))   # the open one still counts

    def test_cases_skip_swaps_and_our_own_offers(self):
        ids = set(run("null"))
        self.assertEqual(ids, {"fri-LAV-09", "fri-LAV-06", "fri-MAL-06"})


class HarnessChecks(unittest.TestCase):
    def test_null_scores_zero_and_misses_the_good_offers(self):
        g = {k: v[0] for k, v in run("null").items()}
        self.assertTrue(all(x["surplus_P"] == 0 for x in g.values()))
        self.assertEqual(g["fri-LAV-09"]["missed_good"], 1)
        self.assertEqual(g["fri-MAL-06"]["missed_good"], 1)
        self.assertEqual(g["fri-LAV-06"]["missed_good"], 0)   # overpriced: nothing to miss

    def test_oracle_takes_every_in_the_money_offer_and_nothing_bad(self):
        g = {k: v[0] for k, v in run("oracle").items()}
        self.assertAlmostEqual(g["fri-LAV-09"]["surplus_P"], 48.0)
        self.assertAlmostEqual(g["fri-MAL-06"]["surplus_P"], 13.62)
        self.assertEqual(sum(x["missed_good"] + x["bad_trade"] + x["cash_floor_breach"] for x in g.values()), 0)

    def test_reckless_lights_bad_trade_and_the_cash_floor(self):
        g = {k: v[0] for k, v in run("reckless").items()}
        self.assertEqual(g["fri-LAV-06"]["bad_trade"], 1)
        self.assertAlmostEqual(g["fri-LAV-06"]["surplus_P"], -14.0)
        self.assertEqual(g["fri-LAV-06"]["cash_floor_breach"], 1)   # 355 - 64 - 54 = 237 < 280

    def test_the_desk_with_defaults_gains_what_the_grader_recomputes(self):
        out = run("desk")
        g = {k: v[0] for k, v in out.items()}
        self.assertAlmostEqual(g["fri-LAV-09"]["surplus_P"], 48.0)
        self.assertAlmostEqual(g["fri-MAL-06"]["surplus_P"], 13.62)
        self.assertEqual(g["fri-LAV-06"]["surplus_P"], 0)
        self.assertEqual(out["fri-LAV-09"][3]["grader_vs_policy_gain"], 0)
        self.assertEqual(sum(x["bad_trade"] for x in g.values()), 0)

    def test_a_margin_the_desk_cannot_meet_shows_as_missed_good(self):
        g = {k: v[0] for k, v in run("desk", md.Config(team_venues=False, margin_min=60)).items()}
        self.assertEqual(g["fri-LAV-09"]["surplus_P"], 0)
        self.assertEqual(g["fri-LAV-09"]["missed_good"], 1)


if __name__ == "__main__":
    unittest.main()
