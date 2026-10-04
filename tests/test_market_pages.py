"""Market desk page mode (--page REF:CAP[:FLOOR]) and the bid-churn fixes.

    python3 -m unittest discover -s tests

Values to us (tests/test_market_desk.py catalog, SAL x1.3): commons 13, uncommons 32.5, rares 91. Holding SAL-01..09,
SAL-10 completes the page: 91 + 25 % x (5 x 13 + 3 x 32.5 + 2 x 91) = 177.125 (need 17.71). El Rastro's fee on a
price p is ceil(5 % x p) + 1: 103 -> 7 (cost 110), 104 -> 7 (cost 111).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "tests"))

import market_desk as md  # noqa: E402
import test_market_desk as base  # noqa: E402
from test_market_desk import AFFINITY, CAT, card, listing, bid, snap, rec  # noqa: E402

SAL9 = {f"SAL-0{i}": [card(100 + i, f"SAL-0{i}")] for i in range(1, 10)}
TARGET = {"SAL-10": {"cap": 110, "floor": None}}


def pcfg(**kw):
    kw.setdefault("bids", False)
    kw.setdefault("min_cash", 40)
    kw.setdefault("page_targets", dict(TARGET))
    kw.setdefault("page_bonus", True)
    kw.setdefault("cap_hour", 150)       # the defaults (100 / 250) would block a 110 page buy: main() refuses that
    kw.setdefault("cap_day", 300)
    return md.Config(**kw)


def settlement(eid, tick, ref, price, frm="t07", to="t12", venue="rastro"):
    return {"id": eid, "tick": tick, "type": "settlement", "payload": {
        "settlement": eid, "kind": "trade", "parties": [frm, to], "venue": venue, "fee": 5, "price": price,
        "items": [{"id": 5000 + eid, "kind": "card", "ref": ref, "rarity": "rare", "set": ref[:3], "frm": frm,
                   "to": to}]}}


def sal10_tape():
    # Friday-Saturday team trades of SAL-10 (feed ticks 72, 98, 163, 376, 556): 80 70 72 76 76, p25 = 72
    return md.Tape().ingest([settlement(i, t, "SAL-10", p) for i, (t, p) in
                             enumerate([(72, 80), (98, 70), (163, 72), (376, 76), (556, 76)], 1)])


def run(boards=None, config=None, bidbook=None, tape=None, holdings=None, ledger=None, page_bonus=True, **kw):
    h = SAL9 if holdings is None else holdings
    extra = {k: kw.pop(k) for k in ("duel_lock", "duel_live", "duels_unread", "page_yield") if k in kw}
    s = snap(boards or {}, h, **kw)
    s.update(extra)
    valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in h.items()}, page_bonus=page_bonus)
    return md.decide(s, valuer, tape or md.Tape(), ledger or md.Ledger(), config or pcfg(), bidbook or {}, {})


def page(res):
    return [b for b in res["bids"] if b.get("page")]


def live(price, since=100, anchor=None, offer=55, to=None):
    return {"SAL-10": {"offer": offer, "price": price, "to": to, "since": since, "anchor": anchor or price}}


class PageAsks(unittest.TestCase):
    def test_takes_an_ask_up_to_the_cap_fee_included(self):
        r = run({"rastro": [listing(1, "SAL-10", 103)]})                 # 103 + 7 = 110 <= 110
        self.assertEqual(r["accept"]["offer"], 1)
        self.assertEqual((rec(r, 1)["page"], rec(r, 1)["cap"], rec(r, 1)["fee"]), (True, 110, 7))
        r = run({"rastro": [listing(1, "SAL-10", 104)]})                 # 104 + 7 = 111 > 110
        self.assertIsNone(r["accept"])
        self.assertIn("page cap: price 104 + fee 7 = 111 > cap 110", rec(r, 1)["reason"])

    def test_the_page_cap_replaces_the_price_cap(self):
        r = run({"rastro": [listing(1, "SAL-10", 103)]}, config=pcfg(page_targets={}))
        self.assertIn("cap: price 103 > max 80", rec(r, 1)["reason"])  # without page mode the 80 P cap blocks it
        r = run({"rastro": [listing(1, "SAL-10", 81)]})
        self.assertEqual(r["accept"]["offer"], 1)                       # with it, the page cap governs

    def test_team_venue_only_when_board_mechanism(self):
        # the snap() helper's v02 has no mechanism: not a plain board, so skipped (board venues: page_gaps tests)
        r = run({"v02": [listing(1, "SAL-10", 60, venue="v02")]}, config=pcfg(team_venues=True))
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["reason"], "page card on v02: mechanism None, board only")

    def test_min_cash(self):
        self.assertEqual(run({"rastro": [listing(1, "SAL-10", 103)]}, cash=150)["accept"]["offer"], 1)   # 40 left
        r = run({"rastro": [listing(1, "SAL-10", 103)]}, cash=149)
        self.assertIsNone(r["accept"])
        self.assertIn("cash after 39 < min 40", rec(r, 1)["reason"])

    def test_the_gain_rule_still_holds(self):
        # without the page bonus SAL-10 is 91 to us: 80 + 5 = 85 leaves 6 < need 9.1, cap or no cap
        r = run({"rastro": [listing(1, "SAL-10", 80)]}, page_bonus=False)
        self.assertIsNone(r["accept"])
        self.assertIn("below need", rec(r, 1)["reason"])

    def test_buying_it_cancels_our_page_bid_first(self):
        r = run({"rastro": [listing(1, "SAL-10", 90)]}, bidbook=live(80))
        self.assertIn("cancel our bid 55 first", rec(r, 1)["reason"])
        self.assertEqual([(b["action"], b["offer"]) for b in page(r)], [("cancel", 55)])


class PageBids(unittest.TestCase):
    def test_one_bid_to_nobody_at_the_team_price_floor(self):
        r = run(tape=sal10_tape())
        self.assertEqual(len(page(r)), 1)
        b = page(r)[0]
        self.assertEqual((b["action"], b["card"], b["price"], b["to"]), ("post", "SAL-10", 72, None))
        rr = b["record"]
        self.assertEqual((rr["kind"], rr["venue"], rr["cap"], rr["ceiling"], rr["value"]),
                         ("bid", "rastro", 110, 110, 177.12))
        self.assertIn("p25 of 5 card team trades 70-80", rr["price_basis"])
        self.assertEqual(rr["gain"], round(177.125 - 72, 2))

    def test_explicit_floor_and_a_rival_bid(self):
        cfg = pcfg(page_targets={"SAL-10": {"cap": 110, "floor": 60}})
        self.assertEqual(page(run(config=cfg, tape=sal10_tape()))[0]["price"], 60)
        r = run({"rastro": [bid(9, "SAL-10", 68, maker="m9")]}, config=cfg)
        self.assertEqual(page(r)[0]["price"], 69)                        # one above the other team's bid

    def test_steps_up_every_n_ticks_to_the_cap(self):
        cfg = pcfg(page_step=4, page_step_ticks=8)
        b = page(run(config=cfg, bidbook=live(72), tick=115))[0]
        self.assertEqual((b["action"], b["price"]), ("replace", 76))      # one step at tick 108
        b = page(run(config=cfg, bidbook=live(72), tick=116))[0]
        self.assertEqual((b["action"], b["price"], b["since"], b["anchor"]), ("replace", 80, 100, 72))
        b = page(run(config=cfg, bidbook=live(72), tick=900))[0]
        self.assertEqual(b["price"], 110)                                 # never above the cap

    def test_our_own_bid_on_the_board_is_not_a_rival(self):
        ours = bid(55, "SAL-10", 72, maker="m-ours")                     # the board shows our bid under a pseudonym
        b = page(run({"rastro": [ours]}, bidbook=live(72), tape=sal10_tape(), tick=101))[0]
        self.assertEqual((b["action"], b["price"]), ("keep", 72))          # not 73: we never outbid ourselves

    def test_a_live_bid_never_steps_down(self):
        b = page(run(bidbook=live(90, anchor=60), tape=sal10_tape()))[0]
        self.assertEqual((b["action"], b["price"]), ("keep", 90))

    def test_a_cheaper_live_ask_caps_the_bid(self):
        # the ask (80 + 5 = 85) cannot be taken (2 trades with its maker this hour): the bid stays below its cost
        led = md.Ledger([{"side": "buy", "t_hours": 1.6, "cost": 9, "partner": "m1"}] * 2)
        r = run({"rastro": [listing(1, "SAL-10", 80)]}, bidbook=live(72, since=0), ledger=led)
        self.assertIsNone(r["accept"])
        b = page(r)[0]
        self.assertEqual((b["action"], b["price"]), ("replace", 84))
        self.assertEqual(b["record"]["ceiling"], 84)

    def test_address_flag(self):
        tape = md.Tape().ingest([settlement(1, 50, "SAL-10", 75, frm="t07", to="t12")])
        self.assertIsNone(page(run(tape=tape))[0]["to"])
        b = page(run(tape=tape, config=pcfg(page_address=True)))[0]
        self.assertEqual((b["action"], b["to"]), ("post", "t12"))


class PageGuards(unittest.TestCase):
    def test_never_two_bids_for_one_card(self):
        # other bids on (every other page missing); the page card belongs to the page planner alone
        cfg = pcfg(bids=True, bid_max=6)
        r = run(config=cfg, bidbook=live(72), tape=sal10_tape(), tick=101)
        sal10 = [b for b in r["bids"] if b["card"] == "SAL-10"]
        self.assertEqual([(b["action"], b.get("page")) for b in sal10], [("keep", True)])
        self.assertTrue([b for b in r["bids"] if b["action"] == "post" and not b.get("page")])
        r = run(config=cfg, tape=sal10_tape())                            # no live bid: one post
        self.assertEqual([b["action"] for b in r["bids"] if b["card"] == "SAL-10"], ["post"])

    def test_page_bids_take_the_cash_first(self):
        r = run(config=pcfg(bids=True, bid_max=6), tape=sal10_tape(), cash=150)
        self.assertEqual(page(r)[0]["price"], 72)
        others = [b for b in r["bids"] if not b.get("page") and b["action"] in ("post", "keep", "replace")]
        self.assertLessEqual(sum(b["price"] for b in others), 150 - 40 - 72)

    def test_duels_no_longer_hold_page_posts_and_steps_only_an_unread_duel_list(self):
        # a fill of our page bid is the seller's accept, not ours: duel.lock / a live duel no longer hold it
        r = run(tape=sal10_tape(), duel_lock=True)
        self.assertEqual([b["action"] for b in page(r)], ["post"])
        b = page(run(bidbook=live(72), tick=200, duel_lock=True))[0]
        self.assertEqual(b["action"], "replace")                           # the due step goes during a duel
        b = page(run(bidbook=live(72), tick=200, duel_live="duel_live: duel 30 is live"))[0]
        self.assertEqual(b["action"], "replace")
        b = page(run(bidbook=live(72), tick=200, duels_unread="duel_live: /api/duels unread (network)"))[0]
        self.assertEqual((b["action"], b["price"]), ("keep", 72))         # an unread duel list holds it
        self.assertIn("/api/duels unread", b["record"]["reason"])
        r = run(holdings={**SAL9, "SAL-10": [card(5, "SAL-10")]}, bidbook=live(72), duel_lock=True)
        self.assertEqual([b["action"] for b in page(r)], ["cancel"])      # cancels still go

    def test_min_cash(self):
        r = run(tape=sal10_tape(), cash=100)                              # room 60 < 72
        self.assertEqual([b["action"] for b in page(r)], ["skip"])
        self.assertIn("cash: bid 72 > room 60", page(r)[0]["record"]["reason"])
        b = page(run(bidbook=live(50), cash=100, tick=300))[0]            # the step does not fit, 50 does
        self.assertEqual((b["action"], b["price"]), ("keep", 50))
        b = page(run(bidbook=live(50), cash=85))[0]                       # room 45 < 50: cancelled
        self.assertEqual(b["action"], "cancel")

    def test_spend_caps(self):
        led = md.Ledger([{"side": "buy", "t_hours": 1.6, "cost": 110, "partner": "t09"}])
        r = run(tape=sal10_tape(), ledger=led)                            # room 150 - 110 = 40 this hour
        self.assertEqual(page(r)[0]["action"], "skip")
        self.assertIn("spend caps 40", page(r)[0]["record"]["reason"])

    def test_card_arrived(self):
        r = run(holdings={**SAL9, "SAL-10": [card(5, "SAL-10")]}, bidbook=live(72))
        self.assertEqual([(b["action"], b["record"]["reason"]) for b in page(r)], [("cancel", "page card arrived")])
        self.assertEqual(page(run(holdings={**SAL9, "SAL-10": [card(5, "SAL-10")]}))[0]["action"], "skip")

    def test_a_live_bid_above_a_lower_ceiling_goes(self):
        # value without the bonus: 91 - 9.1 -> ceiling 81; a live bid at 90 is above it
        r = run(bidbook=live(90), page_bonus=False)
        self.assertEqual(page(r)[0]["action"], "cancel")


class BidChurn(unittest.TestCase):
    """Saturday 2026-10-03 (logs/market): LAV-10 posted 71 at tick 243, replaced 71 -> 70 at 244, 70 -> 71 at 249;
    LAV-09 (live at 64) cancelled at 216 when another bid pushed its anchor to 84, and SAL-09 posted in its place."""

    def held_except(self, *missing):
        h = {}
        for s in CAT["sets"]:
            for c in s["cards"]:
                if c["page"] and c["id"] not in missing:
                    h[c["id"]] = [card(len(h) + 1, c["id"])]
        return h

    def decide(self, book, tick, boards=None, cash=1000):
        h = self.held_except("LAV-09", "LAV-10")
        valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in h.items()})
        cfg = md.Config(min_cash=200, bid_max=6, max_price_rare=100, cap_hour=1000, cap_day=1000)
        return md.decide(snap(boards or {}, h, tick=tick, cash=cash), valuer, md.Tape(), md.Ledger(), cfg, book)

    def test_a_reposted_bid_keeps_its_step_base(self):
        # tick 243: the live bid expired (offer None); its base was 71, the tape anchor is 56 (80 % of book)
        book = {"LAV-10": {"offer": None, "price": 71, "since": 229, "anchor": 71},
                "LAV-09": {"offer": 60, "price": 56, "since": 243, "anchor": 56}}
        b = next(x for x in self.decide(book, 243)["bids"] if x["card"] == "LAV-10")
        self.assertEqual((b["action"], b["price"], b["anchor"]), ("post", 71, 71))
        # what Desk.send stores after the post, then the next tick: same price, no replace
        book["LAV-10"] = {"offer": 3906, "price": b["price"], "to": b["to"], "since": b["since"], "anchor": b["anchor"]}
        b = next(x for x in self.decide(book, 244)["bids"] if x["card"] == "LAV-10")
        self.assertEqual((b["action"], b["price"]), ("keep", 71))

    def test_a_live_bid_whose_step_does_not_fit_stays(self):
        book = {"LAV-09": {"offer": 3502, "price": 64, "since": 208, "anchor": 64},
                "LAV-10": {"offer": 3503, "price": 70, "since": 208, "anchor": 70}}
        rival = bid(9, "LAV-09", 83, maker="m9")                          # pushes LAV-09's anchor to 84
        res = self.decide(book, 216, boards={"rastro": [rival]}, cash=353)   # room 153: 70 + 84 does not fit
        acts = {(b["card"], b["action"], b["price"]) for b in res["bids"]}
        self.assertIn(("LAV-10", "keep", 70), acts)
        self.assertIn(("LAV-09", "keep", 64), acts)
        self.assertFalse([b for b in res["bids"] if b["action"] == "cancel"])


class PageDeskRun(unittest.TestCase):
    setUp = base.DeskLoop.setUp
    tearDown = base.DeskLoop.tearDown

    def desk(self, **kw):
        assets = [a for lst in SAL9.values() for a in lst]
        keyed = base.FakeKeyed([], assets)
        off = md.Valuer(CAT, AFFINITY, {})
        keyed.value = lambda ref: {"card": ref, "your_value": 177.1 if ref == "SAL-10" else off.offline_more(ref)}
        kw.setdefault("page_targets", {"SAL-10": {"cap": 110, "floor": 72}})
        cfg = pcfg(**kw)
        d = md.Desk("run", cfg, base.FakePublic([]), keyed=keyed, lease=self.lease, log=base.MemLog(),
                    heartbeat=self.dir / "desk-market.json", out=self.lines.append)
        return d, keyed

    def test_posts_one_bid_then_keeps_it(self):
        d, k = self.desk()
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [("list", {"cash": 72}, {"cards": ["SAL-10"]}, "rastro", None, 30)])
        oid = 7000 + len(k.writes)
        ours = {"id": oid, "maker": "t03", "status": "open", "to": None, "thread": None, "venue": "rastro",
                "give": {"cash": 72, "assets": [], "types": []}, "want": {"cash": 0, "assets": [], "types": ["card:SAL-10"]}}
        k.my_offers = lambda: {"offers": [ours]}
        d.public.tick = k.tick = 101
        d.tick(d.public.clock())
        self.assertEqual(len(k.writes), 1)                                # kept: nothing sent
        self.assertEqual(d.bidbook["SAL-10"], {"offer": oid, "price": 72, "to": None, "since": 100, "anchor": 72})
        logged = [r for r in d.log.rows if r["event"] == "decision" and r.get("page")]
        self.assertTrue(logged and all("value" in r and "ceiling" in r for r in logged))

    def test_page_bid_posted_while_the_duel_lock_is_fresh(self):
        # a real Lease and a fresh lock file: claim_listings is not refused under the lock, the bid goes up
        (self.dir / "duel.lock").write_text(f"{self.now + 90:.1f}\n")
        d, k = self.desk()
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [("list", {"cash": 72}, {"cards": ["SAL-10"]}, "rastro", None, 30)])


class Cli(unittest.TestCase):
    def test_parse_pages(self):
        self.assertEqual(md.parse_pages(["SAL-10:110", "lav-11:50:30,LAT-12:9"]),
                         {"SAL-10": {"cap": 110, "floor": None}, "LAV-11": {"cap": 50, "floor": 30},
                          "LAT-12": {"cap": 9, "floor": None}})
        for bad in ("SAL-10", "SAL-10:x", "SAL10:110", "SAL-10:110:120", "SAL-10:0", "SAL-10:110:5:6"):
            with self.assertRaises(ValueError, msg=bad):
                md.parse_pages([bad])

    def test_flags(self):
        import argparse
        ap = argparse.ArgumentParser()
        md.add_config_args(ap)
        cfg = md.build_config(ap.parse_args(["--page", "SAL-10:110", "--page-step", "5", "--page-step-ticks", "6",
                                             "--page-address"]))
        self.assertEqual((cfg.page_targets, cfg.page_step, cfg.page_step_ticks, cfg.page_address, cfg.page_bonus),
                         ({"SAL-10": {"cap": 110, "floor": None}}, 5, 6, True, True))
        cfg = md.build_config(ap.parse_args([]))
        self.assertEqual((cfg.page_targets, cfg.page_bonus), ({}, False))

    def test_a_page_cap_above_the_spend_caps_is_refused(self):
        import subprocess
        cmd = [sys.executable, str(ROOT / "agent" / "market_desk.py"), "plan", "--keyless", "--page", "SAL-10:110"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)  # refused before any network read
        self.assertEqual(r.returncode, 2)
        self.assertIn("above --cap-hour 100", r.stderr)

    def test_default_feeds_read_every_recorded_file(self):
        with tempfile.TemporaryDirectory() as t:
            a, b, c = Path(t) / "a.jsonl", Path(t) / "b.jsonl", Path(t) / "missing.jsonl"
            a.write_text("")
            b.write_text("")
            self.assertEqual(md.default_feeds([a, c, b]), [a, b])

    def test_recorded_board(self):
        with tempfile.TemporaryDirectory() as t:
            snaps, cat = Path(t) / "s.jsonl", Path(t) / "cat.json"
            rows = [{"what": "rastro", "tick": 10, "body": {"offers": [listing(1, "SAL-10", 50)]}},
                    {"what": "venues", "tick": 9, "body": {"venues": [{"venue": "rastro", "fee_bps": 500}]}},
                    {"what": "rastro", "tick": 12, "body": {"offers": [listing(2, "SAL-10", 60)]}}]
            snaps.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            cat.write_text(json.dumps({"sets": [{"id": "CHA", "released": False, "cards": []}]}))
            pub = md.RecordedPublic(snaps, cat, release="cha")
            self.assertEqual(pub.clock()["tick"], 12)
            self.assertEqual([o["id"] for o in pub.board("rastro")["offers"]], [2])
            self.assertTrue(pub.catalog()["sets"][0]["released"])
            self.assertEqual(pub.venues()["venues"][0]["fee_bps"], 500)
            with self.assertRaises(md.BazaarError):
                pub.board("v02")


# ---------------------------------------------------------------- review of PR #70 (head 361be93)

def our_bid(oid, ref, cash, status="open"):
    return {"id": oid, "maker": "t03", "status": status, "to": None, "thread": None, "venue": "rastro",
            "give": {"cash": cash, "assets": [], "types": []}, "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


class ReviewRun(unittest.TestCase):
    setUp = base.DeskLoop.setUp
    tearDown = base.DeskLoop.tearDown

    def desk(self, board=(), offers=(), **kw):
        d, k = PageDeskRun.desk(self, **kw)
        d.public.board_offers = k.board_offers = list(board)
        # /api/me/offers as the server keeps it: an offer we cancelled is gone
        k.my_offers = lambda: {"offers": [dict(o) for o in offers if ("cancel", o["id"]) not in k.writes]}
        return d, k

    def quota(self, n):
        left = [n]

        def claim(clock, want=1):
            got = min(want, left[0])
            left[0] -= got
            return got
        self.lease.claim_listings = claim

    def accepts(self, k):
        return [w for w in k.writes if w[0] == "accept"]

    def test_blocker1_no_accept_while_a_duplicate_bid_stays_live(self):
        # bids #55 and #56 on SAL-10, an ask at 90, quota for one cancel: #55 goes, #56 cannot, so no accept
        # room for the ask (96) and both bids (160), which stay held until their cancels show
        d, k = self.desk([listing(1, "SAL-10", 90)], [our_bid(55, "SAL-10", 80), our_bid(56, "SAL-10", 80)],
                         cap_hour=300, cap_day=300)
        self.quota(1)
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])
        self.assertEqual([w[1] for w in k.writes if w[0] == "cancel"], [55])
        self.assertTrue([r for r in d.log.rows if r["event"] == "skip_accept"])

    def test_blocker1_every_bid_on_the_card_is_cancelled_before_the_accept(self):
        # room for the ask (96) and both bids (160), which stay held until their cancels show
        d, k = self.desk([listing(1, "SAL-10", 90)], [our_bid(55, "SAL-10", 80), our_bid(56, "SAL-10", 80)],
                         cap_hour=300, cap_day=300)
        d.tick(d.public.clock())
        self.assertEqual(k.writes[-1], ("accept", 1, None))
        self.assertEqual(sorted(w[1] for w in k.writes if w[0] == "cancel"), [55, 56])

    def test_blocker1_a_failed_cancel_aborts_the_accept(self):
        d, k = self.desk([listing(1, "SAL-10", 90)], [our_bid(56, "SAL-10", 80)])
        d.bidbook = {}                                                    # the duplicate only the fresh read shows

        def cancel(oid):
            raise md.BazaarError("rate_limited", "slow down", 429)
        k.cancel = cancel
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])
        self.assertTrue([r for r in d.log.rows if r["event"] == "skip_accept" and "failed" in r["why"]])

    def test_blocker1_a_settling_bid_of_ours_blocks_the_accept(self):
        d, k = self.desk([listing(1, "SAL-10", 90)], [our_bid(57, "SAL-10", 80, status="queued")])
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])

    def test_blocker3_lock_fresh_after_planning_still_posts(self):
        # reversed on Sunday: the lock guards our accept only; a page bid post spends no accept of ours
        d, k = self.desk()
        d.duel_lock_fresh = lambda: True
        d.tick(d.public.clock())
        self.assertEqual(len([w for w in k.writes if w[0] == "list"]), 1)

    def test_blocker3_server_duel_live_after_planning_still_posts(self):
        d, k = self.desk()
        calls = {"n": 0}

        def duels(done=False):
            calls["n"] += 1
            return {"duels": [] if calls["n"] == 1 else [{"duel": 30, "status": "live", "deadline_tick": 110}]}
        k.duels = duels
        d.tick(d.public.clock())
        self.assertEqual(len([w for w in k.writes if w[0] == "list"]), 1)

    def test_blocker3_a_replace_under_an_unread_duel_list_neither_cancels_nor_posts(self):
        d, k = self.desk(offers=[our_bid(55, "SAL-10", 80)])
        d.bidbook = {"SAL-10": {"offer": 55, "price": 80, "to": None, "since": 0, "anchor": 80}}   # a step is due
        calls = {"n": 0}

        def duels(done=False):   # read when planned, unreadable by the time the replacement goes out
            calls["n"] += 1
            if calls["n"] > 1:
                raise md.BazaarError("network", "down", 0)
            return {"duels": []}
        k.duels = duels
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [])

    def test_major4_a_failed_replacement_keeps_the_step_clock(self):
        d, k = self.desk(offers=[our_bid(55, "SAL-10", 108)])
        d.bidbook = {"SAL-10": {"offer": 55, "price": 108, "to": None, "since": 36, "anchor": 80}}
        d.public.tick = k.tick = 100                                      # (100 - 36) // 8 = 8 steps: 112 -> 110

        def refused(*a, **kw):
            raise md.BazaarError("rate_limited", "slow down", 429)
        k.list_offer = refused
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "cancel"], [("cancel", 55)])
        self.assertEqual(d.bidbook["SAL-10"], {"offer": None, "price": 108, "to": None, "since": 36, "anchor": 80})
        k.list_offer = base.FakeKeyed.list_offer.__get__(k)
        k.my_offers = lambda: {"offers": []}
        d.public.tick = k.tick = 101
        d.tick(d.public.clock())
        self.assertEqual([w[1] for w in k.writes if w[0] == "list"], [{"cash": 110}])   # not 80 on a new clock


class ReviewDecide(unittest.TestCase):
    def test_blocker2_other_buys_leave_spend_room_for_the_page_card(self):
        # MAL-09 at 30 (+3 fee) passes the buy rule; 30 already spent this hour + 33 + the 110 held > 150
        led = md.Ledger([{"side": "buy", "t_hours": 1.6, "cost": 30, "partner": "t09"}])
        r = run({"rastro": [listing(1, "MAL-09", 30)]}, ledger=led, bidbook=live(108, since=36, anchor=80))
        self.assertIsNone(r["accept"])
        self.assertIn("held for page bids", rec(r, 1)["reason"])
        self.assertEqual((page(r)[0]["action"], page(r)[0]["price"]), ("replace", 110))
        r = run({"rastro": [listing(1, "MAL-09", 30)]}, ledger=led, config=pcfg(page_targets={}))
        self.assertEqual(r["accept"]["offer"], 1)                         # without page mode it is taken

    def test_blocker2_page_room_counts_this_ticks_accept(self):
        h = SAL9
        valuer = md.Valuer(CAT, AFFINITY, {r: 1 for r in h}, page_bonus=True)
        acc = {"side": "buy", "card": "MAL-09", "price": 60, "fee": 4}
        out = md.plan_page_bids(snap({}, h, tick=100), valuer, md.Tape(), md.Ledger(), pcfg(), live(108, since=36,
                                anchor=80), {r: 1 for r in h}, set(), acc, 1000)
        self.assertEqual(out[0]["action"], "cancel")                      # room 150 - 64 = 86 < 108
        self.assertIn("room 86", out[0]["record"]["reason"])

    def test_blocker2_page_targets_share_the_room(self):
        cfg = pcfg(cap_hour=140, page_targets={"SAL-10": {"cap": 110, "floor": 80},
                                               "LAV-10": {"cap": 100, "floor": 70}})
        acts = {b["card"]: b["action"] for b in page(run(config=cfg))}
        self.assertEqual(acts, {"LAV-10": "post", "SAL-10": "skip"})     # 70 + 80 > 140

    def test_blocker2_other_bids_share_the_room_with_the_accept(self):
        cfg = md.Config(min_cash=0, bid_max=6, cap_hour=100, cap_day=1000)
        r = md.decide(snap({"rastro": [listing(1, "MAL-09", 30)]}, {}), md.Valuer(CAT, AFFINITY, {}), md.Tape(),
                      md.Ledger(), cfg, {})
        self.assertEqual(r["accept"]["card"], "MAL-09")                   # 33 this tick
        posts = [b for b in r["bids"] if b["action"] in ("post", "keep", "replace")]
        self.assertTrue(posts)
        self.assertLessEqual(sum(b["price"] for b in posts), 100 - 33)

    def test_major5_a_malformed_rival_bid_never_moves_our_price(self):
        bad = bid(9, "SAL-10", 100, maker="m9")
        bad["want"]["cash"] = 99                                          # wants cash back: not a bid
        cfg = pcfg(page_targets={"SAL-10": {"cap": 110, "floor": 80}})
        self.assertEqual(page(run({"rastro": [bad]}, config=cfg))[0]["price"], 80)
        two = bid(10, "SAL-10", 100, maker="m9")
        two["want"]["types"].append("card:SAL-09")                        # two cards: not a single-card bid
        self.assertEqual(page(run({"rastro": [two]}, config=cfg))[0]["price"], 80)
        self.assertEqual(md.rival_bid(bid(11, "SAL-10", 100)), ("SAL-10", 100))
        # the ordinary bid planner reads rivals the same way
        bad_lav = bid(12, "LAV-09", 90, maker="m9")
        bad_lav["want"]["cash"] = 89
        res = md.decide(snap({"rastro": [bad_lav]}, {}), md.Valuer(CAT, AFFINITY, {}), md.Tape(), md.Ledger(),
                        md.Config(min_cash=0, bid_max=6, cap_hour=10 ** 4, cap_day=10 ** 4), {})
        self.assertEqual(next(b for b in res["bids"] if b["card"] == "LAV-09")["price"], 56)   # 80 % of book

    def test_minor8_completed_card_records_carry_the_numbers(self):
        r = run(holdings={**SAL9, "SAL-10": [card(5, "SAL-10")]}, bidbook=live(72))
        rr = page(r)[0]["record"]
        self.assertEqual(rr["action"], "cancel")
        for k in ("value", "ceiling", "anchor", "gain"):
            self.assertIsNotNone(rr.get(k), k)


# ---------------------------------------------------------------- review round 2 of PR #70 (head 3360ad3)

class Review2Run(unittest.TestCase):
    """The reviewer's fixtures against the desk loop, with the Sunday flags (--no-bids, page SAL-10:110:80, min cash
    40, caps 150 / 250)."""
    setUp = base.DeskLoop.setUp
    tearDown = base.DeskLoop.tearDown

    def desk(self, board=(), offers=(), **kw):
        kw.setdefault("page_targets", {"SAL-10": {"cap": 110, "floor": 80}})
        kw.setdefault("cap_day", 250)
        return ReviewRun.desk(self, board, offers, **kw)

    def lists(self, k):
        return [w for w in k.writes if w[0] == "list"]

    def accepts(self, k):
        return [w for w in k.writes if w[0] == "accept"]

    def test_b1_a_snapshot_that_spans_ticks_writes_nothing(self):
        # /api/me at tick 100 says SAL-10 is missing; our bid settles at 101 before /api/me/offers answers
        for board in ([], [listing(1, "SAL-10", 90)]):
            d, k = self.desk(board)

            def offers():
                d.public.tick = k.tick = 101
                return {"offers": []}
            k.my_offers = offers
            d.tick(d.public.clock())
            self.assertEqual((self.lists(k), self.accepts(k)), ([], []), board)
            self.assertTrue([r for r in d.log.rows if r["event"] == "snapshot_spans_ticks"])

    def test_b1_inventory_rechecked_right_before_the_accept(self):
        d, k = self.desk([listing(1, "SAL-10", 90)])
        me, calls = k.me, {"n": 0}

        def me_then_owned():   # 1: the tick's snapshot, 2: take()'s fresh one, 3: the check before the accept
            calls["n"] += 1
            body = me()
            if calls["n"] >= 3:
                body = {**body, "assets": body["assets"] + [card(999, "SAL-10")]}
            return body
        k.me = me_then_owned
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])
        self.assertTrue([r for r in d.log.rows if r["event"] == "skip_accept" and "SAL-10 count" in r["why"]])

    def test_b1_cash_rechecked_right_before_a_bid_post(self):
        d, k = self.desk()
        me, calls = k.me, {"n": 0}

        def me_then_spent():   # 1: the snapshot, 2: the check before the post (a bid of ours filled meanwhile)
            calls["n"] += 1
            return me() if calls["n"] == 1 else {**me(), "cash": 920}
        k.me = me_then_spent
        d.tick(d.public.clock())
        self.assertEqual(self.lists(k), [])
        self.assertTrue([r for r in d.log.rows if r["event"] == "posts_deferred" and "cash" in r["why"]])

    def test_b3_no_bid_planned_before_the_accept_is_posted(self):
        # plan: MAL-09 at 30 (+3) and the SAL-10 bid at 80; take()'s fresh read shows an 80 P maker fill
        d, k = self.desk([listing(1, "MAL-09", 30)], cap_hour=300, cap_day=300)
        fill = {"id": 1, "tick": 100, "type": "settlement", "payload": {
            "settlement": 9, "kind": "trade", "parties": ["t03", "t07"], "venue": "rastro", "fee": 5, "price": 80,
            "items": [{"id": 5, "kind": "card", "ref": "LAV-10", "frm": "t07", "to": "t03"}]}}
        calls = {"n": 0}

        def feed(limit=500):
            calls["n"] += 1
            return {"events": [] if calls["n"] == 1 else [fill]}
        d.public.feed = feed
        d.tick(d.public.clock())
        self.assertEqual(self.lists(k), [])
        self.assertTrue([r for r in d.log.rows if r["event"] == "posts_deferred"])

    def test_b4_page_accepts_wait_for_every_live_duel(self):
        # tick 100, a live duel ending at 110, --duel-guard-ticks 1, no local lock
        d, k = self.desk([listing(1, "SAL-10", 90)], duel_guard_ticks=1)
        k.duel_list = [{"duel": 30, "status": "live", "deadline_tick": 110}]
        res = d.tick(d.public.clock())
        self.assertEqual((len(self.lists(k)), self.accepts(k)), (1, []))   # the page bid goes up, the accept waits
        self.assertEqual(rec(res, 1)["action"], "defer")
        self.assertIn("duel 30", rec(res, 1)["reason"])
        d, k = self.desk([listing(1, "MAL-09", 30)], duel_guard_ticks=1)   # an ordinary accept: the window applies
        k.duel_list = [{"duel": 30, "status": "live", "deadline_tick": 110}]
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [("accept", 1, None)])

    def test_b4_a_duel_at_the_post_time_recheck_no_longer_holds(self):
        d, k = self.desk(duel_guard_ticks=1)
        calls = {"n": 0}

        def duels(done=False):   # quiet at planning, a duel 10 ticks from its end at the post
            calls["n"] += 1
            return {"duels": [] if calls["n"] == 1 else [{"duel": 31, "status": "live", "deadline_tick": 110}]}
        k.duels = duels
        d.tick(d.public.clock())
        self.assertEqual(len(self.lists(k)), 1)   # reversed on Sunday: a live duel no longer holds the page bid

    def test_b3_unread_duel_list_only_at_the_post(self):
        d, k = self.desk()
        calls = {"n": 0}

        def duels(done=False):   # 1: the snapshot, 2: before the cancels, 3: right before the post
            calls["n"] += 1
            if calls["n"] >= 3:
                raise md.BazaarError("network", "down", 0)
            return {"duels": []}
        k.duels = duels
        d.tick(d.public.clock())
        self.assertEqual(self.lists(k), [])
        self.assertTrue([r for r in d.log.rows if r["event"] == "page_hold" and r["when"] == "at the post"])

    def test_m5_feed_down_no_cash_write(self):
        for board in ([], [listing(1, "SAL-10", 90)]):
            d, k = self.desk(board)

            def down(limit=500):
                raise md.BazaarError("network", "down", 0)
            d.public.feed = down
            d.tick(d.public.clock())
            self.assertEqual((self.lists(k), self.accepts(k)), ([], []), board)
            self.assertTrue([r for r in d.log.rows if r["event"] == "feed_down"])

    def test_b2_a_failed_cancel_blocks_every_post(self):
        # ordinary bids on: the cancel of a LAV-09 bid fails; no other bid (SAL-10 or any card) goes up this tick
        d, k = self.desk(offers=[our_bid(70, "LAV-09", 999)], bids=True, bid_max=3, cap_hour=10 ** 4,
                         cap_day=10 ** 4)

        def cancel(oid):
            raise md.BazaarError("rate_limited", "slow down", 429)
        k.cancel = cancel
        d.tick(d.public.clock())
        self.assertEqual(self.lists(k), [])


class Review2Decide(unittest.TestCase):
    def test_b2_other_open_bids_hold_spend_room_under_no_bids(self):
        # --no-bids: an 80 P LAV-10 bid of ours is open; SAL-10 at 80 would make 160 P in the hour (cap 150)
        cfg = pcfg(page_targets={"SAL-10": {"cap": 110, "floor": 80}})
        r = run(config=cfg, mine=[our_bid(70, "LAV-10", 80)])
        self.assertEqual(page(r)[0]["action"], "skip")
        self.assertIn("room 70", page(r)[0]["record"]["reason"])
        r = run(config=cfg, mine=[our_bid(70, "LAV-10", 80, status="queued")])   # settling: still held
        self.assertEqual(page(r)[0]["action"], "skip")
        self.assertEqual(page(run(config=cfg))[0]["action"], "post")

    def test_b2_daily_exposure(self):
        # 100 P spent earlier today (outside the hour) + an open 80 P bid + 80 P = 260 > 250
        led = md.Ledger([{"side": "buy", "t_hours": 0.2, "cost": 100, "partner": "t09"}])
        cfg = pcfg(page_targets={"SAL-10": {"cap": 110, "floor": 80}}, cap_day=250)
        r = run(config=cfg, ledger=led, mine=[our_bid(70, "LAV-10", 80)])
        self.assertEqual(page(r)[0]["action"], "skip")
        self.assertIn("room 70", page(r)[0]["record"]["reason"])

    def test_b2_other_buys_count_our_open_bids(self):
        # MAL-09 at 30 (+3) with the 110 page reserve and an open 20 P bid: 33 + 110 + 20 > 150
        r = run({"rastro": [listing(1, "MAL-09", 30)]}, mine=[our_bid(70, "LAV-05", 20)])
        self.assertIsNone(r["accept"])
        r = run({"rastro": [listing(1, "MAL-09", 30)]})
        self.assertEqual(r["accept"]["card"], "MAL-09")

    def test_b2_cash_reservations(self):
        cfg = pcfg(page_targets={"SAL-10": {"cap": 110, "floor": 80}}, cap_hour=10 ** 4, cap_day=10 ** 4)
        # page bid: cash 190 - min 40 - an open 80 P bid = 70 < 80
        self.assertEqual(page(run(config=cfg, cash=190, mine=[our_bid(70, "LAV-10", 80)]))[0]["action"], "skip")
        self.assertEqual(page(run(config=cfg, cash=190))[0]["action"], "post")
        # other buys: cash 200 - the 110 page reserve - an open 20 P bid - 33 = 37 < 40
        r = run({"rastro": [listing(1, "MAL-09", 30)]}, config=cfg, cash=200, mine=[our_bid(70, "LAV-05", 20)])
        self.assertIsNone(r["accept"])
        self.assertIn("cash after 37 < min 40", rec(r, 1)["reason"])
        r = run({"rastro": [listing(1, "MAL-09", 30)]}, config=cfg, cash=180)      # 180 - 110 - 33 = 37
        self.assertIsNone(r["accept"])
        self.assertEqual(run({"rastro": [listing(1, "MAL-09", 30)]}, config=cfg, cash=200)["accept"]["card"], "MAL-09")

    def test_b4_planning_holds_page_bids_only_for_an_unread_duel_list(self):
        r = run(tape=sal10_tape(), duel_live=None)
        self.assertEqual(page(r)[0]["action"], "post")
        valuer = md.Valuer(CAT, AFFINITY, {r: 1 for r in SAL9}, page_bonus=True)
        s = snap({}, SAL9)
        s.update(duel_live=None, duel_any="duel_live: duel 30 is live, deadline tick 110")
        self.assertEqual(page(md.decide(s, valuer, sal10_tape(), md.Ledger(), pcfg(), {}, {}))[0]["action"], "post")
        s.update(duels_unread="duel_live: /api/duels unread (network)")
        r = md.decide(s, valuer, sal10_tape(), md.Ledger(), pcfg(), {}, {})
        self.assertEqual(page(r)[0]["action"], "skip")
        self.assertIn("/api/duels unread", page(r)[0]["record"]["reason"])

    def test_m6_held_page_card_ask_records_carry_the_page_numbers(self):
        r = run({"rastro": [listing(1, "SAL-10", 90)]}, holdings={**SAL9, "SAL-10": [card(5, "SAL-10")]},
                bidbook=live(80))
        rr = rec(r, 1)
        self.assertIn("we hold", rr["reason"])
        self.assertEqual((rr.get("page"), rr.get("cap"), rr.get("ceiling"), rr.get("anchor")), (True, 110, 110, 80))


if __name__ == "__main__":
    unittest.main()
