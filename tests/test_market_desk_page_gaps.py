"""Sunday page gaps: SAL-10 during duels, on other teams' board venues, and the page-yield handoff.

    python3 -m unittest tests.test_market_desk_page_gaps
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tests"))

import market_desk as md  # noqa: E402
import test_market_desk as base  # noqa: E402
import test_market_pages as pages  # noqa: E402
from test_market_desk import AFFINITY, CAT, card, listing, rec, snap  # noqa: E402
from test_market_pages import SAL9, pcfg, page, live, sal10_tape  # noqa: E402

BOARD_VENUES = {"rastro": {"fee": (500, 1), "owner": "world", "house": True, "mechanism": None},
                "v10": {"fee": (0, 0), "owner": "t10", "house": False, "mechanism": "board"},
                "v11": {"fee": (300, 0), "owner": "t11", "house": False, "mechanism": "board"},
                "v16": {"fee": (0, 0), "owner": "t16", "house": False, "mechanism": "auto"},
                "v20": {"fee": (0, 0), "owner": "t03", "house": False, "mechanism": "board"}}


def decide(boards, cfg=None, holdings=None, **extra):
    h = SAL9 if holdings is None else holdings
    s = snap(boards, h, venues=BOARD_VENUES)
    s.update(extra)
    valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in h.items()}, page_bonus=True)
    return md.decide(s, valuer, md.Tape(), md.Ledger(), cfg or pcfg(team_venues=False), {}, {})


class TeamVenuePage(unittest.TestCase):
    def test_board_venue_listing_taken_at_the_cap(self):
        r = decide({"v10": [listing(1, "SAL-10", 110, venue="v10", maker="t10")]})
        self.assertEqual((r["accept"] or {}).get("offer"), 1)               # 110 + 0 fee == cap 110
        self.assertEqual(rec(r, 1)["action"], "take")

    def test_fee_counts_against_the_cap(self):
        r = decide({"v11": [listing(1, "SAL-10", 107, venue="v11", maker="t11")]})   # 107 + ceil(3.21) = 111
        self.assertIsNone(r["accept"])
        self.assertIn("page cap", rec(r, 1)["reason"])
        r = decide({"v11": [listing(1, "SAL-10", 106, venue="v11", maker="t11")]})   # 106 + 4 = 110
        self.assertEqual((r["accept"] or {}).get("offer"), 1)

    def test_above_the_cap_rejected(self):
        r = decide({"v10": [listing(1, "SAL-10", 111, venue="v10", maker="t10")]})
        self.assertIsNone(r["accept"])
        self.assertIn("page cap", rec(r, 1)["reason"])

    def test_own_venue_rejected(self):
        r = decide({"v20": [listing(1, "SAL-10", 60, venue="v20", maker="t07")]})
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["reason"], "page card on v20: our own venue")

    def test_non_board_mechanism_rejected(self):
        r = decide({"v16": [listing(1, "SAL-10", 60, venue="v16", maker="t16")]})
        self.assertIsNone(r["accept"])
        self.assertIn("mechanism 'auto', board only", rec(r, 1)["reason"])

    def test_closed_or_unknown_venue_rejected(self):
        r = decide({"v99": [listing(1, "SAL-10", 60, venue="v99", maker="t09")]})
        self.assertIsNone(r["accept"])
        self.assertIn("venue not open", rec(r, 1)["reason"])

    def test_non_page_card_on_the_same_board_still_skipped(self):
        r = decide({"v10": [listing(1, "SAL-05", 5, venue="v10", maker="t10"),
                            listing(2, "LAV-07", 5, venue="v10", maker="t10")]})
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 2)["reason"], "team venue (off by --no-team-venues)")

    def test_venue_table_reads_the_mechanism(self):
        vt = md.venue_table({"venues": [
            {"venue": "v10", "owner": "t10", "fee_bps": 0, "status": "open", "rules": {"mechanism": "board"}},
            {"venue": "v13", "owner": "t13", "fee_bps": 0, "status": "closed", "rules": {"mechanism": "board"}},
            {"venue": "rastro", "owner": "world", "fee_bps": 500, "status": "open", "rules": {}}]}, 100)
        self.assertEqual(vt["v10"]["mechanism"], "board")
        self.assertNotIn("v13", vt)
        self.assertIsNone(md.page_venue_ok(vt, "v10", "t03"))
        self.assertIsNotNone(md.page_venue_ok(vt, "v13", "t03"))


class DuelPage(unittest.TestCase):
    def test_page_accept_waits_for_a_live_duel(self):
        # the lease refuses every MARKET accept while duel.lock is fresh (lease.py _accept_check): deferred, as before
        r = decide({"rastro": [listing(1, "SAL-10", 90)]}, duel_any="duel_live: duel 30 is live")
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["action"], "defer")

    def test_page_bid_posted_and_raised_during_a_seller_duel(self):
        b = page(pages.run(tape=sal10_tape(), duel_lock=True, duel_live="duel_live: duel 30 is live"))[0]
        self.assertEqual(b["action"], "post")
        b = page(pages.run(bidbook=live(72), tick=200, duel_lock=True, duel_live="duel_live: duel 30 is live"))[0]
        self.assertEqual(b["action"], "replace")
        self.assertGreater(b["price"], 72)


class DuelPageRun(unittest.TestCase):
    setUp = base.DeskLoop.setUp
    tearDown = base.DeskLoop.tearDown

    def desk(self, duels=(), **kw):
        d, k = pages.PageDeskRun.desk(self, **kw)
        d.yield_dir = self.dir
        k.duel_list = list(duels)
        return d, k

    def test_page_bid_raised_during_a_live_seller_duel_and_lock(self):
        (self.dir / "duel.lock").write_text(f"{self.now + 90:.1f}\n")
        d, k = self.desk(duels=[{"duel": 30, "status": "live", "role": "seller", "deadline_tick": 110}])
        ours = pages.our_bid(55, "SAL-10", 80)
        k.my_offers = lambda: {"offers": [dict(ours)] if ("cancel", 55) not in k.writes else []}
        d.bidbook = {"SAL-10": {"offer": 55, "price": 80, "to": None, "since": 0, "anchor": 80}}   # a step is due
        d.tick(d.public.clock())
        self.assertIn(("cancel", 55), k.writes)
        lists = [w for w in k.writes if w[0] == "list"]
        self.assertEqual(len(lists), 1)
        self.assertGreater(lists[0][1]["cash"], 80)

    def test_buyer_duel_holds_the_page_bid(self):
        d, k = self.desk(duels=[{"duel": 31, "status": "live", "role": "buyer", "deadline_tick": 110}])
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "list"], [])

    def test_no_page_accept_during_a_duel(self):
        d, k = self.desk(duels=[{"duel": 30, "status": "live", "role": "seller", "deadline_tick": 110}])
        d.public.board_offers = k.board_offers = [listing(1, "SAL-10", 90)]
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [])


class PageYield(unittest.TestCase):
    setUp = base.DeskLoop.setUp
    tearDown = base.DeskLoop.tearDown

    def desk(self, **kw):
        d, k = pages.PageDeskRun.desk(self, **kw)
        d.yield_dir = self.dir
        return d, k

    def test_yield_cancels_the_bid_then_acks(self):
        (self.dir / "page-yield-SAL-10").write_text("")
        d, k = self.desk()
        ours = pages.our_bid(55, "SAL-10", 80)
        k.my_offers = lambda: {"offers": [dict(ours)] if ("cancel", 55) not in k.writes else []}
        d.bidbook = {"SAL-10": {"offer": 55, "price": 80, "to": None, "since": 100, "anchor": 80}}
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [("cancel", 55)])                     # cancelled, nothing new posted
        ack = self.dir / "page-yield-SAL-10.ack"
        self.assertFalse(ack.exists())                                    # not before the account shows it gone
        d.public.tick = k.tick = 101
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [("cancel", 55)])
        body = json.loads(ack.read_text())
        self.assertEqual((body["ref"], body["tick"], body["open_bid"]), ("SAL-10", 101, False))

    def test_yield_without_a_bid_acks_at_once_and_takes_no_ask(self):
        (self.dir / "page-yield-SAL-10").write_text("")
        d, k = self.desk()
        d.public.board_offers = k.board_offers = [listing(1, "SAL-10", 60)]
        res = d.tick(d.public.clock())
        self.assertEqual(k.writes, [])
        self.assertIn("page-yield", rec(res, 1)["reason"])
        self.assertTrue((self.dir / "page-yield-SAL-10.ack").exists())

    def test_plan_mode_never_writes_the_ack(self):
        (self.dir / "page-yield-SAL-10").write_text("")
        d = md.Desk("plan", pcfg(), base.FakePublic([]), keyed=None, out=self.lines.append, heartbeat=None)
        d.yield_dir = self.dir
        res = d.tick(d.public.clock())
        self.assertFalse((self.dir / "page-yield-SAL-10.ack").exists())
        self.assertTrue(all(b["action"] in ("skip", "cancel") for b in page(res)))

    def test_owned_card_stops_page_buying(self):
        r = decide({"rastro": [listing(1, "SAL-10", 60)]}, holdings={**SAL9, "SAL-10": [card(5, "SAL-10")]})
        self.assertIsNone(r["accept"])
        self.assertEqual([b["action"] for b in page(r)], ["skip"])


class TeamBoardFetch(unittest.TestCase):
    def test_only_hinted_board_venues_between_sweeps(self):
        d = md.Desk("plan", pcfg(team_venues=False), base.FakePublic([]), keyed=None, out=lambda *_: None,
                    heartbeat=None)
        d.yield_dir = Path("/nonexistent")
        vt = BOARD_VENUES
        self.assertEqual(sorted(d.page_boards(vt, "t03")), ["v10", "v11"])      # tick 0: full sweep, boards only
        d.ticks = 1
        self.assertEqual(d.page_boards(vt, "t03"), [])
        d.tape.ingest([{"id": 1, "tick": 5, "type": "offer.listed", "actor": "t11", "payload": {
            "venue": "v11", "offer": {"id": 77, "venue": "v11", "give": {"assets": [card(9, "SAL-10")]},
                                      "want": {"cash": 90}}}}])
        self.assertEqual(d.page_boards(vt, "t03"), ["v11"])
        d.tape.ingest([{"id": 2, "tick": 6, "type": "offer.cancelled", "payload": {"offer": 77}}])
        self.assertEqual(d.page_boards(vt, "t03"), [])


if __name__ == "__main__":
    unittest.main()
