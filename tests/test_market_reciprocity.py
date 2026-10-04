"""Market desk --reciprocity: partner venues for our own genuine buys.

    python3 -m unittest tests.test_market_reciprocity

A partner is a team that listed an offer on (or settled a trade on) our venue v20 since the day opened (the latest
day.opened event in the tape), or one named with --partners. With --reciprocity, a non-page listing on a partner's own
open board venue may be taken despite --no-team-venues, at the venue's real fee, and when two eligible listings of
the same card cost the same all-in (within --reciprocity-tie P) the partner venue wins. Off by default: the golden
file (tests/fixtures/market_reciprocity_golden.json, made by the desk before this flag existed) pins that.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "tests"))

import market_desk as md  # noqa: E402
import test_market_desk as base  # noqa: E402
from test_market_desk import AFFINITY, CAT, bid, card, listing, rec, snap  # noqa: E402
from test_market_pages import SAL9, pcfg  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "market_reciprocity_golden.json"

VENUES = {"rastro": {"fee": (500, 1), "owner": "world", "house": True, "mechanism": None},
          "v02": {"fee": (0, 0), "owner": "t12", "house": False, "mechanism": None},
          "v10": {"fee": (0, 0), "owner": "t10", "house": False, "mechanism": "board"},
          "v11": {"fee": (300, 2), "owner": "t11", "house": False, "mechanism": "board"},
          "v16": {"fee": (0, 0), "owner": "t16", "house": False, "mechanism": "auto"},
          "v20": {"fee": (0, 0), "owner": "t03", "house": False, "mechanism": "board"}}


def ev_day(eid, tick, day="sun"):
    return {"id": eid, "tick": tick, "type": "day.opened", "actor": "", "payload": {"day": day}}


def ev_listed(eid, tick, team, venue="v20", oid=None, ref="LAT-02"):
    oid = oid or 70000 + eid
    return {"id": eid, "tick": tick, "type": "offer.listed", "actor": team, "payload": {
        "venue": venue, "offer": {"id": oid, "maker": team, "venue": venue, "give": {"assets": [card(oid, ref)]},
                                  "want": {"cash": 20}}}}


def ev_settled(eid, tick, frm, to, venue="v20", ref="LAT-02"):
    return {"id": eid, "tick": tick, "type": "settlement", "payload": {
        "settlement": eid, "kind": "trade", "parties": [frm, to], "venue": venue, "fee": 0, "price": 20,
        "items": [{"id": 6000 + eid, "kind": "card", "ref": ref, "rarity": "common", "set": ref[:3], "frm": frm,
                   "to": to}]}}


def partner_tape():
    """Saturday: t13 on v20 (old news). Sunday: t10 lists twice on v20, t11 settles with t12 there; t16 lists on
    El Rastro only; we (t03) never count."""
    return md.Tape().ingest([
        ev_day(1, 0, "sat"), ev_listed(2, 5, "t13"),
        ev_day(10, 100, "sun"), ev_listed(11, 100, "t10"), ev_listed(12, 101, "t10"),
        ev_settled(13, 102, "t11", "t12"), ev_listed(14, 102, "t16", venue="rastro"), ev_listed(15, 103, "t03")])


# ---------------------------------------------------------------- scenarios for the flag-off golden file

def scenarios():
    """(name, cfg kwargs, boards, holdings, cash, bidbook) - built from the existing test helpers. Each runs through
    decide() with partner_tape(): partner evidence exists, and with the flag off it must change nothing."""
    boards = {
        "rastro": [listing(1, "SAL-05", 8), listing(2, "LAV-07", 30, maker="t07"), listing(3, "LAT-03", 5),
                   bid(4, "MAL-02", 30, maker="t09"), listing(5, "SAL-10", 103, maker="t14")],
        "v02": [listing(21, "LAT-04", 4, venue="v02", maker="t12")],
        "v10": [listing(31, "SAL-05", 10, venue="v10", maker="t10"), listing(32, "LAT-01", 5, venue="v10"),
                listing(33, "SAL-10", 106, venue="v10", maker="t10"), listing(34, "LAV-08", 20, venue="v10")],
        "v11": [listing(41, "LAV-08", 18, venue="v11", maker="t11"), listing(42, "MAL-01", 2, venue="v11")],
        "v16": [listing(51, "LAT-05", 3, venue="v16", maker="t16")],
        "v20": [listing(61, "MAL-03", 3, venue="v20", maker="t07")],
    }
    hold = {"MAL-02": [card(201, "MAL-02", 3), card(202, "MAL-02", 9)], "LAV-01": [card(203, "LAV-01")]}
    page_hold = {**SAL9, **hold}
    base_kw = {"bids": False, "min_cash": 40, "cap_hour": 150, "cap_day": 250}
    return [
        ("no_team_venues", {**base_kw, "team_venues": False}, boards, hold, 1000, {}),
        ("team_venues", {**base_kw, "team_venues": True}, boards, hold, 1000, {}),
        ("no_team_venues_bids", {**base_kw, "team_venues": False, "bids": True}, boards, hold, 1000, {}),
        ("page_no_team_venues", {**base_kw, "team_venues": False, "page_targets": {"SAL-10": {"cap": 110,
                                                                                               "floor": 80}},
                                 "page_bonus": True}, boards, page_hold, 1000, {}),
        ("low_cash", {**base_kw, "team_venues": False}, boards, hold, 60, {}),
    ]


def run_scenario(cfg_kw, boards, holdings, cash, bidbook, tape=None, **extra_cfg):
    s = snap(boards, holdings, cash=cash, venues=VENUES)
    valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in holdings.items()},
                       page_bonus=bool(cfg_kw.get("page_bonus")))
    cfg = md.Config(**{**cfg_kw, **extra_cfg})
    return md.decide(s, valuer, tape or partner_tape(), md.Ledger(), cfg, dict(bidbook), {})


def canon(res) -> str:
    return json.dumps({"records": res["records"], "accept": res["accept"], "bids": res["bids"],
                       "swaps": res["swaps"]}, sort_keys=True, default=str)


def rcfg(**kw):
    kw.setdefault("bids", False)
    kw.setdefault("min_cash", 40)
    kw.setdefault("cap_hour", 150)
    kw.setdefault("cap_day", 250)
    kw.setdefault("team_venues", False)
    kw.setdefault("reciprocity", True)
    return md.Config(**kw)


T10 = {"t10": {"listed": 2, "settled": 0, "evidence": 2, "static": False}}


def decide(boards, cfg=None, holdings=None, partners=None, cash=1000, ledger=None, **extra):
    h = holdings or {}
    s = snap(boards, h, cash=cash, venues=VENUES)
    s["partners"] = T10 if partners is None else partners
    s.update(extra)
    valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in h.items()})
    return md.decide(s, valuer, md.Tape(), ledger or md.Ledger(), cfg or rcfg(), {}, {})


class PartnerDetection(unittest.TestCase):
    def test_today_only_and_never_us(self):
        ps, since = md.reciprocity_partners(partner_tape(), md.Config(reciprocity=True), "t03", 104)
        self.assertEqual(sorted(ps), ["t10", "t11", "t12"])          # t13 was Saturday, t16 on El Rastro, t03 is us
        self.assertEqual((ps["t10"]["listed"], ps["t10"]["evidence"]), (2, 2))
        self.assertEqual((ps["t11"]["settled"], ps["t12"]["settled"]), (1, 1))
        self.assertIn("day.opened event 10", since)

    def test_lookback_ticks_and_static_partners(self):
        cfg = md.Config(reciprocity=True, partner_lookback=200, partners=("t05", "t03"))
        ps, _ = md.reciprocity_partners(partner_tape(), cfg, "t03", 104)
        self.assertEqual(sorted(ps), ["t05", "t10", "t11", "t12", "t13"])   # tick 5 is within 200; t03 never
        self.assertTrue(ps["t05"]["static"])
        self.assertEqual(ps["t05"]["evidence"], 0)
        ps, _ = md.reciprocity_partners(partner_tape(), md.Config(reciprocity=True, partner_lookback=3), "t03", 104)
        self.assertEqual(sorted(ps), ["t11", "t12"])                     # tick > 101: the tick-102 settlement only

    def test_no_day_opened_fails_closed(self):
        tape = md.Tape().ingest([ev_listed(11, 100, "t10")])
        ps, since = md.reciprocity_partners(tape, md.Config(reciprocity=True, partners=("t07",)), "t03", 104)
        self.assertEqual(sorted(ps), ["t07"])                            # static partners only
        self.assertIn("feed evidence off", since)

    def test_clock_day_binds_the_lookback(self):
        cfg = md.Config(reciprocity=True)
        ps, since = md.reciprocity_partners(partner_tape(), cfg, "t03", 104, today="sun")
        self.assertEqual(sorted(ps), ["t10", "t11", "t12"])
        ps, _ = md.reciprocity_partners(partner_tape(), cfg, "t03", 104, today="sat")
        self.assertEqual(sorted(ps), ["t10", "t11", "t12", "t13"])      # since Saturday's open
        # a recorded feed that stops before Sunday opened: Saturday's teams never count on Sunday
        stale = md.Tape().ingest([ev_day(1, 0, "sat"), ev_listed(2, 5, "t13")])
        ps, since = md.reciprocity_partners(stale, cfg, "t03", 104, today="sun")
        self.assertEqual(ps, {})
        self.assertIn("no day.opened for sun", since)

    def test_incremental_ingest(self):
        tape = partner_tape()
        tape.ingest([ev_listed(20, 110, "t14"), ev_listed(11, 100, "t10")])   # a new team; a repeated event ignored
        ps, _ = md.reciprocity_partners(tape, md.Config(reciprocity=True), "t03", 110)
        self.assertEqual(ps["t14"]["evidence"], 1)
        self.assertEqual(ps["t10"]["evidence"], 2)


class Eligibility(unittest.TestCase):
    # values to us (tests/test_market_desk.py catalog): LAT common 11 (need 3); LAV uncommon 40 (need 4)
    def test_partner_board_listing_taken_at_its_fee(self):
        r = decide({"v10": [listing(1, "LAT-03", 7, venue="v10", maker="t10")]})
        self.assertEqual((r["accept"] or {}).get("offer"), 1)            # 11 - 7 - 0 = 4 >= 3
        self.assertEqual(rec(r, 1)["recip_partner"], "t10")
        self.assertIn("reciprocity partner t10 (2 listed on v20)", rec(r, 1)["reciprocity"])

    def test_partner_venue_fee_counts_in_the_gain(self):
        ps = {"t11": {"listed": 1, "settled": 0, "evidence": 1, "static": False}}
        r = decide({"v11": [listing(1, "LAT-03", 6, venue="v11", maker="t11")]}, partners=ps)
        self.assertEqual(rec(r, 1)["fee"], 3)                            # ceil(3 % x 6) + 2
        self.assertIsNone(r["accept"])                                   # 11 - 6 - 3 = 2 < 3
        self.assertIn("below need", rec(r, 1)["reason"])
        r = decide({"v11": [listing(1, "LAT-03", 5, venue="v11", maker="t11")]}, partners=ps)
        self.assertEqual((r["accept"] or {}).get("offer"), 1)            # 11 - 5 - 3 = 3

    def test_caps_still_hold(self):
        lst = {"v10": [listing(1, "LAV-07", 30, venue="v10", maker="t10")]}   # 40 - 30 = 10 >= 4
        self.assertEqual((decide(lst)["accept"] or {}).get("offer"), 1)
        r = decide(lst, cash=69)                                          # 69 - 30 = 39 < min cash 40
        self.assertIsNone(r["accept"])
        self.assertIn("min 40", rec(r, 1)["reason"])
        r = decide(lst, cfg=rcfg(max_price=29))
        self.assertIn("cap: price 30 > max 29", rec(r, 1)["reason"])
        led = md.Ledger([{"side": "buy", "t_hours": 100 / 60, "cost": 130, "partner": "t09"}])
        self.assertIn("hour spend", rec(decide(lst, ledger=led), 1)["reason"])
        led = md.Ledger([{"side": "buy", "t_hours": 0.1, "cost": 230, "partner": "t09"}])
        self.assertIn("day spend", rec(decide(lst, ledger=led), 1)["reason"])

    def test_structure_check_still_applies(self):
        bad = listing(1, "LAT-03", 5, venue="v10", maker="t10")
        bad["give"]["assets"].append(card(9999, "LAT-04"))               # two cards for one price: not a listing
        r = decide({"v10": [bad]})
        self.assertIsNone(r["accept"])
        self.assertTrue(rec(r, 1)["reason"].startswith("structure:"))

    def test_duel_and_lock_still_defer(self):
        lst = {"v10": [listing(1, "LAT-03", 5, venue="v10", maker="t10")]}
        for extra in ({"duel_live": "duel_live: test"}, {"duel_lock": True}):
            r = decide(lst, **extra)
            self.assertIsNone(r["accept"])
            self.assertEqual(rec(r, 1)["action"], "defer")

    def test_non_partner_team_venue_still_rejected(self):
        r = decide({"v11": [listing(1, "LAT-03", 1, venue="v11", maker="t11")],
                    "v02": [listing(2, "LAT-04", 1, venue="v02", maker="t12")]})
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["reason"], "team venue (off by --no-team-venues); not via --reciprocity: "
                                              "t11 is not a reciprocity partner")
        self.assertNotIn("recip_partner", rec(r, 1))

    def test_partner_but_not_a_board_or_our_own_venue(self):
        ps = {t: {"listed": 1, "settled": 0, "evidence": 1, "static": False} for t in ("t16", "t03")}
        r = decide({"v16": [listing(1, "LAT-03", 1, venue="v16", maker="t16")],
                    "v20": [listing(2, "LAT-04", 1, venue="v20", maker="t07")]}, partners=ps)
        self.assertIsNone(r["accept"])
        self.assertIn("mechanism 'auto', board only", rec(r, 1)["reason"])
        self.assertIn("v20 is our own venue", rec(r, 2)["reason"])

    def test_listing_by_a_third_team_on_a_partner_board(self):
        # eligibility follows the venue's owner (whose market points it is), not the listing's maker
        r = decide({"v10": [listing(1, "LAT-03", 5, venue="v10", maker="t07")]})
        self.assertEqual((r["accept"] or {}).get("offer"), 1)

    def test_flag_off_partner_board_still_rejected(self):
        r = decide({"v10": [listing(1, "LAT-03", 5, venue="v10", maker="t10")]}, cfg=rcfg(reciprocity=False))
        self.assertIsNone(r["accept"])
        self.assertEqual(rec(r, 1)["reason"], "team venue (off by --no-team-venues)")
        self.assertNotIn("recip_partner", rec(r, 1))


class TieBreak(unittest.TestCase):
    # LAV-07 (40 to us): El Rastro 28 + fee 3 = 31 all-in; t10's 0-fee board 31 + 0 = 31.
    BOARDS = {"rastro": [listing(1, "LAV-07", 28)], "v10": [listing(2, "LAV-07", 31, venue="v10", maker="t10")]}

    def test_equal_all_in_prefers_the_partner_venue(self):
        self.assertEqual(decide(self.BOARDS, cfg=rcfg(reciprocity=False))["accept"]["offer"], 1)   # today: rastro
        r = decide(self.BOARDS)
        self.assertEqual(r["accept"]["offer"], 2)
        self.assertIn("reciprocity: partner t10's v10 (all-in 31 vs 31 on rastro)", rec(r, 2)["reason"])
        self.assertIn("reciprocity tie-break", rec(r, 1)["reason"])

    def test_tie_also_under_team_venues(self):
        # with team venues on both are eligible, and the old key (-gain, price) picks El Rastro's lower price
        self.assertEqual(decide(self.BOARDS, cfg=rcfg(reciprocity=False, team_venues=True))["accept"]["offer"], 1)
        self.assertEqual(decide(self.BOARDS, cfg=rcfg(team_venues=True))["accept"]["offer"], 2)

    def test_cheaper_alternative_wins_without_tolerance(self):
        boards = {"rastro": [listing(1, "LAV-07", 27)],                  # 27 + 3 = 30 < 31
                  "v10": [listing(2, "LAV-07", 31, venue="v10", maker="t10")]}
        self.assertEqual(decide(boards)["accept"]["offer"], 1)
        self.assertEqual(decide(boards, cfg=rcfg(reciprocity_tie=1))["accept"]["offer"], 2)   # within 1 P

    def test_tie_never_passes_a_cap(self):
        r = decide(self.BOARDS, cfg=rcfg(max_price=30))                  # 31 > max price: only El Rastro passes
        self.assertEqual(r["accept"]["offer"], 1)
        self.assertIn("cap: price 31 > max 30", rec(r, 2)["reason"])

    def test_order_helper_leaves_sells_alone(self):
        c = [{"card": "A", "side": "sell", "price": 5, "fee": 1, "offer": 1, "venue": "rastro"},
             {"card": "A", "side": "buy", "price": 4, "fee": 0, "offer": 2, "venue": "v10", "recip_partner": "t10"},
             {"card": "B", "side": "buy", "price": 9, "fee": 0, "offer": 3, "venue": "rastro"}]
        self.assertEqual([x["offer"] for x in md.reciprocity_order(c)], [1, 2, 3])


class FlagOffGolden(unittest.TestCase):
    """Flag off: the decisions of the desk before --reciprocity existed (golden file made by main a1e2924 on the same
    scenarios), with partner evidence in the tape."""

    def test_identical_to_main(self):
        golden = json.loads(GOLDEN.read_text())
        for name, kw, boards, holdings, cash, bidbook in scenarios():
            with self.subTest(name):
                got = json.loads(canon(run_scenario(kw, boards, holdings, cash, bidbook)))
                self.assertEqual(got, golden[name])

    def test_flag_on_without_partners_takes_the_same_trades(self):
        for name, kw, boards, holdings, cash, bidbook in scenarios():
            with self.subTest(name):
                off = run_scenario(kw, boards, holdings, cash, bidbook)
                on = run_scenario(kw, boards, holdings, cash, bidbook, reciprocity=True)   # snap carries no partners
                self.assertEqual([(r.get("offer"), r["action"]) for r in on["records"]],
                                 [(r.get("offer"), r["action"]) for r in off["records"]])
                self.assertEqual((on["accept"] or {}).get("offer"), (off["accept"] or {}).get("offer"))


class Pub(base.FakePublic):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.reads = []

    def venues(self):
        return {"venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1, "house": True, "status": "open"},
                           {"venue": "v10", "owner": "t10", "fee_bps": 0, "status": "open",
                            "rules": {"mechanism": "board"}},
                           {"venue": "v11", "owner": "t11", "fee_bps": 300, "fee_per_card": 2, "status": "open",
                            "rules": {"mechanism": "board"}},
                           {"venue": "v20", "owner": "t03", "fee_bps": 0, "status": "open",
                            "rules": {"mechanism": "board"}}]}

    def board(self, vid):
        self.reads.append(vid)
        return {"offers": [listing(1, "LAT-03", 5, venue="v10", maker="t10")] if vid == "v10" else []}

    def feed(self, limit=500):
        return {"events": [ev_day(10, 90), ev_listed(11, 95, "t10")]}


class DeskReads(unittest.TestCase):
    def desk(self, cfg, out):
        d = md.Desk("plan", cfg, Pub([]), keyed=None, out=out.append, heartbeat=None, seller_config=None)
        d.account = lambda tick: {"id": "t03", "cash": 1000, "assets": [], "affinity": AFFINITY, "offers": [],
                                  "source": "test"}
        return d

    def test_flag_off_reads_no_team_board(self):
        d = self.desk(md.Config(bids=False, min_cash=40, team_venues=False), [])
        res = d.tick(d.public.clock())
        self.assertEqual(d.public.reads, ["rastro"])
        self.assertNotIn("partners", d.last_snap)
        self.assertIsNone(res["accept"])

    def test_flag_on_reads_partner_boards_logs_once_and_buys(self):
        out = []
        d = self.desk(rcfg(), out)
        res = d.tick(d.public.clock())
        self.assertEqual(sorted(d.public.reads), ["rastro", "v10"])           # t11 is no partner: v11 unread
        self.assertEqual(sorted(d.last_snap["partners"]), ["t10"])
        self.assertEqual((res["accept"] or {}).get("offer"), 1)
        d.tick(d.public.clock())
        self.assertEqual(sum("reciprocity partners since" in str(x) for x in out), 1)   # logged on change only


class Cli(unittest.TestCase):
    def parse(self, *argv):
        import argparse
        ap = argparse.ArgumentParser()
        md.add_config_args(ap)
        return md.build_config(ap.parse_args(list(argv)))

    def test_defaults_off(self):
        cfg = self.parse()
        self.assertFalse(cfg.reciprocity)
        self.assertEqual((cfg.partners, cfg.partner_lookback, cfg.reciprocity_tie), ((), None, 0))

    def test_flags(self):
        cfg = self.parse("--reciprocity", "--partners", "t05, T12,t05", "--reciprocity-tie", "1")
        self.assertEqual((cfg.reciprocity, cfg.partners, cfg.reciprocity_tie), (True, ("t05", "t12"), 1))
        with self.assertRaises(ValueError):
            self.parse("--reciprocity", "--partners", "La Celestina")


if __name__ == "__main__":
    unittest.main()
