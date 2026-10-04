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
    extra = {k: kw.pop(k) for k in ("duel_lock", "duel_live") if k in kw}
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

    def test_never_on_a_team_venue(self):
        r = run({"v02": [listing(1, "SAL-10", 60, venue="v02")]}, config=pcfg(team_venues=True))
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["reason"], "page card: bought on rastro only")

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

    def test_duel_lock_holds_every_post_and_step(self):
        r = run(tape=sal10_tape(), duel_lock=True)
        self.assertEqual([b["action"] for b in page(r)], ["skip"])
        self.assertIn("hold: results/duel.lock is fresh", page(r)[0]["record"]["reason"])
        b = page(run(bidbook=live(72), tick=200, duel_lock=True))[0]
        self.assertEqual((b["action"], b["price"]), ("keep", 72))         # due a step, but not while a duel runs
        b = page(run(bidbook=live(72), tick=200, duel_live="duel_live: duel 30 is live"))[0]
        self.assertEqual((b["action"], b["price"]), ("keep", 72))
        self.assertIn("duel 30", b["record"]["reason"])
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
        cfg = md.Config(min_cash=200, bid_max=6, max_price_rare=100)
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
        keyed.value = lambda ref: {"card": ref, "your_value": 177.1 if ref == "SAL-10" else 0}
        cfg = pcfg(page_targets={"SAL-10": {"cap": 110, "floor": 72}}, **kw)
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

    def test_nothing_posted_while_the_duel_lock_is_fresh(self):
        (self.dir / "duel.lock").write_text(f"{self.now + 90:.1f}\n")
        d, k = self.desk()
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [])


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


if __name__ == "__main__":
    unittest.main()
