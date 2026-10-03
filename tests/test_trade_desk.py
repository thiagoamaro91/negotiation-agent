"""Tests for agent/trade_desk.py (H2): the pure gain rules, and one_pass against a fake server that records every write."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kit"))
import trade_desk as T
from bazaar_sdk import BazaarError

T.VALUE_CALL_GAP = 0
CFG = T.Config()
TICK = 500


def card(i, ref, serial=5, value=None):
    a = {"id": i, "kind": "card", "ref": ref, "rarity": "uncommon", "set": ref[:3], "serial": serial}
    if value is not None:
        a["your_value"] = value
    return a


def listing(oid, ref, price, asset_id=900, maker="t05", venue="rastro", to=None):
    return {"id": oid, "maker": maker, "to": to, "venue": venue, "thread": None, "status": "open", "expires_tick": TICK + 20,
            "give": {"cash": 0, "assets": [card(asset_id, ref)], "types": []},
            "want": {"cash": price, "assets": [], "types": []}}


def bid(oid, ref, price, maker="t06", venue="rastro", to=None):
    return {"id": oid, "maker": maker, "to": to, "venue": venue, "thread": None, "status": "open", "expires_tick": TICK + 20,
            "give": {"cash": price, "assets": [], "types": []}, "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


class FakeB:
    """Records every write. Reads are scripted; values by ref."""

    def __init__(self, cash=300, assets=None, album=None, board=None, inbox=None, mine=None, values=None, duels=None,
                 schedule=None, clock=None, accept_error=None):
        self.cash, self.assets, self.album = cash, assets or [], album or []
        self._board, self._inbox, self._mine = board or [], inbox or [], mine or []
        self.values, self._duels, self._schedule = values or {}, duels or [], schedule or []
        self.clock_ = clock or {"tick": TICK, "t_hours": 5.0, "tick_seconds": 30, "paused": False}
        self.accept_error, self.writes, self.reads = accept_error, [], []

    def clock(self): return self.clock_
    def schedule(self): self.reads.append("schedule"); return {"upcoming": self._schedule}
    def me(self): self.reads.append("me"); return {"id": "t03", "cash": self.cash, "assets": self.assets, "album": {"pages": self.album}}
    def my_offers(self): return {"offers": self._inbox + self._mine}
    def board(self, v): return {"offers": self._board}
    def duels(self): return {"duels": self._duels}
    def value(self, ref):
        if ref not in self.values:
            raise BazaarError("not_found", ref, 404)
        return {"card": ref, "your_value": self.values[ref]}

    def accept(self, oid, assets=None):
        if self.accept_error:
            raise self.accept_error
        self.writes.append(("accept", oid, assets))

    def list_offer(self, give, want, venue=None, **kw):
        self.writes.append(("list", give, want, venue))


def run_pass(b, cfg=CFG, live=False, said=None, vcache=None, tmp=None):
    tmp = tmp or Path(tempfile.mkdtemp())
    out = T.one_pass(b, T.Config(**{**cfg.__dict__, "stop_file": str(tmp / "stop")}), live, b.clock(), said if said is not None else {},
                     vcache if vcache is not None else {}, tmp / "decisions.jsonl")
    rows = [json.loads(l) for l in (tmp / "decisions.jsonl").read_text().splitlines()] if (tmp / "decisions.jsonl").exists() else []
    return out, rows, tmp


class Venues(unittest.TestCase):
    def test_allowed_and_blocked(self):
        self.assertTrue(T.venue_allowed("rastro", CFG))
        self.assertTrue(T.venue_allowed(None, CFG))
        for v in ("v02", "v07", "v20", "v99"):
            self.assertFalse(T.venue_allowed(v, CFG))
        self.assertTrue(T.venue_allowed("v06", T.Config(pact_venue=("v06",))))
        self.assertFalse(T.venue_allowed("v02", T.Config(pact_venue=("v02",))))   # the block wins over the pact list

    def test_fee_is_known_for_rastro_only(self):
        self.assertEqual(T.venue_fee("rastro"), (500, 1))
        self.assertEqual(T.venue_fee("v06"), (1000, 5))


class PageCard(unittest.TestCase):
    def test_only_when_the_rest_of_the_page_is_held(self):
        held = {"LAV-09": [card(1, "LAV-09")]}
        self.assertEqual(T.page_card_ok([{"set": "LAV", "have": 9, "of": 10}], held, CFG)[0], True)
        self.assertEqual(T.page_card_ok([{"set": "LAV", "have": 8, "of": 10}], {}, CFG)[0], False)
        self.assertEqual(T.page_card_ok([{"set": "LAV", "have": 9, "of": 10}], {"LAV-10": [card(2, "LAV-10")]}, CFG)[0], False)
        self.assertEqual(T.page_card_ok(None, {}, CFG)[0], False)
        self.assertEqual(T.page_card_ok([{"set": "MAL", "have": 9, "of": 10}], {}, CFG)[0], False)   # no LAV album row


class Scan(unittest.TestCase):
    def scan(self, offers, holdings=None, values=None, venue="rastro", page_ok=False, cfg=CFG):
        vals = values or {}
        h = holdings or {}
        mine = {a["id"]: ref for ref, cs in h.items() for a in cs}
        return T.scan_offers(offers, venue, "t03", mine, h, cfg, TICK, vals.get, page_ok)

    def test_buy_candidate_needs_surplus_of_the_margin_after_the_fee(self):
        # price 20, rastro fee ceil(20*5%)+1 = 2, value 25 -> gain 3: exactly the margin
        r = self.scan([listing(1, "MAL-03", 20)], values={"MAL-03": 25})[0]
        self.assertEqual((r["result"], r["surplus"], r["fee"]), ("candidate", 3.0, 2))
        r = self.scan([listing(1, "MAL-03", 21)], values={"MAL-03": 25})[0]      # fee 3 -> gain 1
        self.assertEqual(r["result"], "skipped")

    def test_wrong_side_of_value_is_never_a_candidate(self):
        r = self.scan([listing(1, "MAL-03", 30)], values={"MAL-03": 25})[0]
        self.assertEqual(r["result"], "skipped")
        self.assertLess(r["surplus"], 0)

    def test_held_card_unknown_value_and_padded_offers(self):
        h = {"MAL-03": [card(7, "MAL-03")]}
        self.assertEqual(self.scan([listing(1, "MAL-03", 5)], holdings=h, values={"MAL-03": 99})[0]["result"], "skipped")
        self.assertEqual(self.scan([listing(2, "MAL-04", 5)], values={})[0]["why"], "live value unreadable")
        padded = listing(3, "MAL-05", 5)
        padded["give"]["assets"].append(card(901, "MAL-06"))
        self.assertEqual(self.scan([padded], values={"MAL-05": 99})[0]["result"], "not_a_match")
        wants_card_too = listing(4, "MAL-05", 5)
        wants_card_too["want"]["types"] = ["card:LAV-01"]
        self.assertEqual(self.scan([wants_card_too], values={"MAL-05": 99})[0]["result"], "not_a_match")

    def test_blocked_venue_skips_everything_on_it(self):
        rows = self.scan([listing(1, "MAL-03", 1, venue="v07")], values={"MAL-03": 99}, venue="v07")
        self.assertEqual((rows[0]["result"], rows[0]["why"]), ("skipped", "venue v07 is not allowed"))

    def test_page_card_is_skipped_until_the_page_is_ready(self):
        o = [listing(1, "LAV-10", 100)]
        self.assertEqual(self.scan(o, values={"LAV-10": 218}, page_ok=False)[0]["result"], "skipped")
        self.assertEqual(self.scan(o, values={"LAV-10": 218}, page_ok=True)[0]["result"], "candidate")

    def test_sell_into_a_bid_uses_the_spare_copys_own_value_and_gives_the_highest_serial(self):
        h = {"MAL-06": [card(10, "MAL-06", serial=2, value=17.5), card(11, "MAL-06", serial=9, value=4.4)]}
        r = self.scan([bid(1, "MAL-06", 24)], holdings=h)[0]          # fee ceil(1.2)+1 = 3, value 4.4 -> gain 16.6
        self.assertEqual((r["result"], r["asset"], r["our_value"], r["surplus"]), ("candidate", 11, 4.4, 16.6))

    def test_never_sell_our_only_copy_of_a_protected_set_card(self):
        for ref in ("LAV-08", "LAT-06", "SAL-07"):
            h = {ref: [card(10, ref, value=40)]}
            r = self.scan([bid(1, ref, 90)], holdings=h)[0]
            self.assertEqual(r["result"], "skipped", ref)
            self.assertIn("only copy", r["why"])

    def test_a_single_copy_outside_the_protected_sets_may_be_sold_above_its_value(self):
        h = {"MAL-07": [card(10, "MAL-07", value=17.5)]}
        r = self.scan([bid(1, "MAL-07", 25)], holdings=h)[0]            # fee 3 -> gain 4.5
        self.assertEqual((r["result"], r["surplus"], r["asset"]), ("candidate", 4.5, 10))
        r = self.scan([bid(2, "MAL-07", 21)], holdings=h)[0]            # gain 0.5: below the margin
        self.assertEqual(r["result"], "skipped")

    def test_a_protected_set_card_is_sellable_when_we_hold_a_spare(self):
        h = {"LAV-08": [card(10, "LAV-08", 2, 40), card(11, "LAV-08", 9, 10)]}
        r = self.scan([bid(1, "LAV-08", 24)], holdings=h)[0]
        self.assertEqual((r["result"], r["asset"], r["our_value"]), ("candidate", 11, 10))

    def test_a_bid_for_a_card_we_do_not_hold_is_skipped(self):
        self.assertEqual(self.scan([bid(1, "MAL-07", 25)], holdings={})[0]["why"], "we do not hold that card")

    def test_a_bid_for_one_specific_asset_must_be_that_spare(self):
        h = {"MAL-06": [card(10, "MAL-06", value=17.5), card(11, "MAL-06", value=4.4)]}
        o = bid(1, "MAL-06", 24)
        o["want"] = {"cash": 0, "assets": [card(10, "MAL-06")], "types": []}
        r = self.scan([o], holdings=h)[0]
        self.assertEqual((r["asset"], r["our_value"]), (10, 17.5))      # that asset's own value, not the cheaper copy's


class Pick(unittest.TestCase):
    def row(self, action, card, price, surplus, fee=2):
        return {"action": action, "card": card, "price": price, "surplus": surplus, "fee": fee, "result": "candidate", "offer": 1}

    def test_highest_surplus_wins_and_buys_respect_the_reserve(self):
        rows = [self.row("buy", "A-01", 50, 5), self.row("buy", "B-01", 20, 9), self.row("sell", "C-01", 10, 7)]
        self.assertEqual(T.best_accept(rows, 100, CFG, False)["card"], "B-01")
        self.assertEqual(T.best_accept(rows, 60, CFG, False)["card"], "C-01")     # the buys would leave < 40
        self.assertIsNone(T.best_accept([], 100, CFG, False))

    def test_a_sell_is_never_blocked_by_the_reserve(self):
        self.assertEqual(T.best_accept([self.row("sell", "C-01", 10, 7)], 0, CFG, False)["card"], "C-01")

    def test_the_page_card_may_dip_to_the_looser_reserve_only_when_the_page_is_ready(self):
        r = self.row("buy", "LAV-10", 100, 20, fee=6)
        self.assertIsNone(T.best_accept([r], 140, CFG, False))                    # 140-106 = 34 < 40
        self.assertEqual(T.best_accept([r], 120, CFG, True)["card"], "LAV-10")    # 120-106 = 14 >= 10
        self.assertIsNone(T.best_accept([r], 115, CFG, True))                     # 115-106 = 9 < 10


class PageBidRow(unittest.TestCase):
    def row(self, **kw):
        args = dict(cfg=CFG, page_ok=True, page_why="ready", has_live_bid=False, value=218.0)
        args.update(kw)
        return T.page_bid_row(**args)

    def test_never_posts_without_a_human_named_price(self):
        r = self.row()
        self.assertEqual((r["result"], r["price"]), ("skipped", None))
        self.assertIn("ceiling 215", r["why"])
        self.assertIn("no --page-bid-price", r["why"])

    def test_posts_at_the_named_price_and_never_above_the_ceiling(self):
        cfg = T.Config(page_bid_price=90)
        r = self.row(cfg=cfg)
        self.assertEqual((r["result"], r["price"], r["surplus"]), ("candidate", 90, 128.0))
        r = self.row(cfg=T.Config(page_bid_price=500))
        self.assertEqual(r["price"], 215)

    def test_skipped_when_the_page_is_not_ready_a_bid_is_live_or_value_unknown(self):
        self.assertEqual(self.row(cfg=T.Config(page_bid_price=90), page_ok=False)["result"], "skipped")
        self.assertEqual(self.row(cfg=T.Config(page_bid_price=90), has_live_bid=True)["result"], "skipped")
        self.assertEqual(self.row(cfg=T.Config(page_bid_price=90), value=None)["result"], "skipped")


class LiveBid(unittest.TestCase):
    def test_detects_only_our_own_open_bid_for_that_card(self):
        mine = [{"maker": "t03", "status": "open", "give": {"cash": 100}, "want": {"types": ["card:LAV-10"]}},
                {"maker": "t03", "status": "cancelled", "give": {"cash": 100}, "want": {"types": ["card:LAV-09"]}},
                {"maker": "t09", "status": "open", "give": {"cash": 100}, "want": {"types": ["card:LAV-08"]}}]
        self.assertTrue(T.live_bid_for(mine, "t03", "LAV-10"))
        self.assertFalse(T.live_bid_for(mine, "t03", "LAV-09"))
        self.assertFalse(T.live_bid_for(mine, "t03", "LAV-08"))


class Bench(unittest.TestCase):
    EV = [{"action": "bench", "at_hours": 10.0, "params": {"ticks": 16}}, {"action": "duels", "at_hours": 5.0}]

    def test_window_start_run_margin_and_clear(self):
        self.assertTrue(T.in_bench_window(self.EV, 10.0, 30, CFG))
        self.assertTrue(T.in_bench_window(self.EV, 9.95, 30, CFG))             # inside the 0.10 h margin before
        self.assertTrue(T.in_bench_window(self.EV, 10.1, 30, CFG))             # 16 x 30 s = 0.133 h running
        self.assertFalse(T.in_bench_window(self.EV, 9.8, 30, CFG))
        self.assertFalse(T.in_bench_window(self.EV, 10.5, 30, CFG))
        self.assertFalse(T.in_bench_window([], 10.0, 30, CFG))

    def test_a_slower_tick_makes_the_window_longer(self):
        self.assertFalse(T.in_bench_window(self.EV, 10.3, 30, CFG))
        self.assertTrue(T.in_bench_window(self.EV, 10.3, 60, CFG))


class OnePass(unittest.TestCase):
    def setUp(self):
        self.lock = T.DUEL_LOCK
        T.DUEL_LOCK = Path(tempfile.mkdtemp()) / "duel.lock"     # never read the real one

    def tearDown(self):
        T.DUEL_LOCK = self.lock

    def buyable(self, **kw):
        return FakeB(board=[listing(10, "MAL-03", 20)], values={"MAL-03": 30}, **kw)

    def test_shadow_mode_sends_nothing_but_logs_the_candidate(self):
        b = self.buyable()
        out, rows, _ = run_pass(b, live=False)
        self.assertEqual(b.writes, [])
        self.assertIsNone(out["sent"])
        self.assertIn(("buy", "MAL-03", "candidate"), [(r["action"], r["card"], r["result"]) for r in rows])
        self.assertTrue(all(r["lane"] == "trade_desk" for r in rows))
        self.assertEqual(set(rows[0]), {"ts", "tick", "lane", "action", "card", "price", "our_value", "surplus", "why", "result"})

    def test_trivial_skips_collapse_into_one_summary_line_instead_of_one_row_each(self):
        held = [card(7, "MAL-03")]
        board = [listing(i, "MAL-03", 9, asset_id=900 + i) for i in range(1, 31)] + [listing(99, "MAL-04", 20)]
        b = FakeB(assets=held, board=board, values={"MAL-04": 30})
        _, rows, _ = run_pass(b, live=False)
        self.assertEqual(len([r for r in rows if r["card"] == "MAL-03"]), 0)           # 30 "we already hold it" rows
        scans = [r for r in rows if r["result"] == "scan"]
        self.assertEqual(len(scans), 1)
        self.assertIn("scanned 31 offers: 30 not actionable", scans[0]["why"])
        self.assertIn("1 candidate(s)", scans[0]["why"])
        self.assertEqual(len([r for r in rows if r["card"] == "MAL-04"]), 1)             # the real candidate is still logged

    def test_a_judged_skip_with_a_value_is_still_logged_because_it_says_why_not(self):
        b = FakeB(board=[listing(10, "MAL-03", 28)], values={"MAL-03": 30})              # gain 30-28-3 = -1
        _, rows, _ = run_pass(b, live=False)
        r = next(r for r in rows if r["card"] == "MAL-03")
        self.assertEqual((r["result"], r["our_value"]), ("skipped", 30))
        self.assertIn("< margin", r["why"])

    def test_live_accepts_a_buy_without_assets(self):
        b = self.buyable()
        out, rows, _ = run_pass(b, live=True)
        self.assertEqual(b.writes, [("accept", 10, None)])
        self.assertEqual(rows[-1]["result"], "sent")

    def test_live_sell_passes_the_asset_to_give(self):
        h = [card(10, "MAL-06", 2, 17.5), card(11, "MAL-06", 9, 4.4)]
        b = FakeB(assets=h, board=[bid(20, "MAL-06", 24)])
        run_pass(b, live=True)
        self.assertEqual(b.writes, [("accept", 20, [11])])

    def test_only_one_write_per_pass(self):
        b = FakeB(board=[listing(10, "MAL-03", 20), listing(11, "MAL-04", 20)], values={"MAL-03": 30, "MAL-04": 40})
        run_pass(b, live=True)
        self.assertEqual(len(b.writes), 1)
        self.assertEqual(b.writes[0][1], 11)                    # the bigger surplus

    def test_stop_file_means_no_reads_and_no_writes(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "stop").write_text("x")
        b = self.buyable()
        out, rows, _ = run_pass(b, live=True, tmp=tmp)
        self.assertTrue(out["stopped"])
        self.assertEqual((b.writes, b.reads), ([], []))
        self.assertEqual(rows[0]["result"], "stopped")

    def test_a_live_duel_defers_the_whole_pass_even_when_live(self):
        b = self.buyable(duels=[{"duel": 1}])
        out, rows, _ = run_pass(b, live=True)
        self.assertEqual(b.writes, [])
        self.assertTrue(any(r["result"] == "deferred_duel_live" for r in rows))

    def test_a_fresh_duel_lock_defers(self):
        T.DUEL_LOCK.parent.mkdir(parents=True, exist_ok=True)
        T.DUEL_LOCK.write_text(str(time.time() + 60))
        b = self.buyable()
        run_pass(b, live=True)
        self.assertEqual(b.writes, [])

    def test_a_stale_lock_does_not_defer_but_a_garbled_one_does(self):
        T.DUEL_LOCK.parent.mkdir(parents=True, exist_ok=True)
        T.DUEL_LOCK.write_text(str(time.time() - 60))
        b = self.buyable()
        run_pass(b, live=True)
        self.assertEqual(len(b.writes), 1)
        T.DUEL_LOCK.write_text("garbage")
        b2 = self.buyable()
        run_pass(b2, live=True)
        self.assertEqual(b2.writes, [])

    def test_a_failed_duels_read_defers(self):
        b = self.buyable()
        b.duels = lambda: (_ for _ in ()).throw(BazaarError("network", "x", 0))
        run_pass(b, live=True)
        self.assertEqual(b.writes, [])

    def test_market_test_window_is_quiet_and_reads_nothing_of_ours(self):
        b = self.buyable(schedule=[{"action": "bench", "at_hours": 5.0, "params": {"ticks": 16}}])
        out, rows, _ = run_pass(b, live=True)
        self.assertTrue(out["quiet"])
        self.assertEqual(b.writes, [])
        self.assertNotIn("me", b.reads)

    def test_inbox_offer_on_a_rival_venue_is_skipped_but_on_rastro_is_taken(self):
        rival = listing(30, "MAL-03", 20, venue="v07", to="t03")
        b = FakeB(inbox=[rival], values={"MAL-03": 30})
        run_pass(b, live=True)
        self.assertEqual(b.writes, [])
        home = listing(31, "MAL-03", 20, venue="rastro", to="t03")
        b = FakeB(inbox=[home], values={"MAL-03": 30})
        run_pass(b, live=True)
        self.assertEqual(b.writes, [("accept", 31, None)])

    def test_the_same_offer_on_the_board_and_in_the_inbox_is_one_row(self):
        o = listing(31, "MAL-03", 20, to="t03")
        b = FakeB(inbox=[o], board=[o], values={"MAL-03": 30})
        _, rows, _ = run_pass(b, live=False)
        self.assertEqual(len([r for r in rows if r["card"] == "MAL-03"]), 1)

    def test_a_row_is_logged_once_until_it_changes(self):
        b = self.buyable()
        said, vcache, tmp = {}, {}, Path(tempfile.mkdtemp())
        run_pass(b, said=said, vcache=vcache, tmp=tmp)
        n = len((tmp / "decisions.jsonl").read_text().splitlines())
        run_pass(b, said=said, vcache=vcache, tmp=tmp)
        self.assertEqual(len((tmp / "decisions.jsonl").read_text().splitlines()), n)
        b._board = [listing(10, "MAL-03", 19)]                 # a new price is a new row (values are cached)
        run_pass(b, said=said, vcache=vcache, tmp=tmp)
        self.assertGreater(len((tmp / "decisions.jsonl").read_text().splitlines()), n)

    def test_values_are_cached_across_passes(self):
        b = self.buyable()
        calls = []
        orig = b.value
        b.value = lambda ref: (calls.append(ref), orig(ref))[1]
        vcache = {}
        run_pass(b, vcache=vcache)
        run_pass(b, vcache=vcache)
        self.assertEqual(calls, ["MAL-03"])

    PAGE = [{"set": "LAV", "have": 9, "of": 10}]

    def test_page_card_bid_is_posted_only_with_a_named_price_and_not_twice(self):
        cfg = T.Config(page_bid_price=90)
        b = FakeB(cash=300, assets=[card(1, "LAV-09")], album=self.PAGE, values={"LAV-10": 218})
        run_pass(b, cfg=cfg, live=True)
        self.assertEqual(b.writes, [("list", {"cash": 90}, {"cards": ["LAV-10"]}, "rastro")])
        live_bid = {"maker": "t03", "status": "open", "give": {"cash": 90}, "want": {"types": ["card:LAV-10"]}}
        b2 = FakeB(cash=300, assets=[card(1, "LAV-09")], album=self.PAGE, values={"LAV-10": 218}, mine=[live_bid])
        run_pass(b2, cfg=cfg, live=True)
        self.assertEqual(b2.writes, [])

    def test_no_page_bid_without_a_named_price_even_when_the_page_is_ready_and_live(self):
        b = FakeB(cash=300, assets=[card(1, "LAV-09")], album=self.PAGE, values={"LAV-10": 218})
        _, rows, _ = run_pass(b, live=True)
        self.assertEqual(b.writes, [])
        self.assertTrue(any("no --page-bid-price" in (r["why"] or "") for r in rows))

    def test_no_page_bid_while_the_page_is_incomplete_or_cash_is_short(self):
        cfg = T.Config(page_bid_price=90)
        b = FakeB(cash=300, assets=[], album=[{"set": "LAV", "have": 8, "of": 10}], values={"LAV-10": 218})
        run_pass(b, cfg=cfg, live=True)
        self.assertEqual(b.writes, [])
        b = FakeB(cash=95, assets=[card(1, "LAV-09")], album=self.PAGE, values={"LAV-10": 218})   # 95-90 = 5 < 10
        run_pass(b, cfg=cfg, live=True)
        self.assertEqual(b.writes, [])

    def test_the_page_card_is_not_accepted_from_a_team_before_its_page_is_ready(self):
        b = FakeB(cash=500, board=[listing(10, "LAV-10", 100)], album=[{"set": "LAV", "have": 8, "of": 10}], values={"LAV-10": 218})
        run_pass(b, live=True)
        self.assertEqual(b.writes, [])
        b = FakeB(cash=500, assets=[card(1, "LAV-09")], board=[listing(10, "LAV-10", 100)], album=self.PAGE, values={"LAV-10": 218})
        run_pass(b, live=True)
        self.assertEqual(b.writes, [("accept", 10, None)])

    def test_shadow_mode_never_writes_even_with_a_page_bid_price_and_a_buyable_card(self):
        cfg = T.Config(page_bid_price=90)
        b = FakeB(cash=500, assets=[card(1, "LAV-09")], board=[listing(10, "MAL-03", 20)], album=self.PAGE,
                  values={"LAV-10": 218, "MAL-03": 30})
        run_pass(b, cfg=cfg, live=False)
        self.assertEqual(b.writes, [])

    def test_a_refused_write_is_logged_and_a_429_is_raised_for_the_backoff(self):
        b = self.buyable(accept_error=BazaarError("insufficient_cash", "no", 400))
        _, rows, _ = run_pass(b, live=True)
        self.assertEqual(rows[-1]["result"], "refused")
        b = self.buyable(accept_error=BazaarError("rate_limited", "slow", 429))
        with self.assertRaises(BazaarError):
            run_pass(b, live=True)

    def test_cash_reserve_blocks_a_buy_that_would_dip_below_it(self):
        b = FakeB(cash=55, board=[listing(10, "MAL-03", 20)], values={"MAL-03": 30})      # 55-22 = 33 < 40
        run_pass(b, live=True)
        self.assertEqual(b.writes, [])


if __name__ == "__main__":
    unittest.main()
