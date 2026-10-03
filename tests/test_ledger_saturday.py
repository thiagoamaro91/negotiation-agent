"""tools/ledger.py on Saturday's feed: starter stalls, the allowance grant, bond refunds, fees earned on a team venue,
and the Friday recording hole filled from logs/feed-vm. Run: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ledger  # noqa: E402

TEAMS = ("t01", "t02", "t03")


def load(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def feed(*rows) -> list:
    """Synthetic events: three teams join at tick 0, then `rows` as (tick, type, payload), one tick apart at most."""
    out = [{"id": n + 1, "tick": 0, "type": "team.joined", "payload": {"team": t}} for n, t in enumerate(TEAMS)]
    for tick, kind, payload in rows:
        out.append({"id": len(out) + 1, "tick": tick, "type": kind, "payload": payload})
    return out


def settlement(frm, to, ref, price, venue, fee=0, asset=900):
    return {"venue": venue, "persona": None, "fee": fee, "price": price, "parties": [frm, to],
            "items": [{"id": asset, "kind": "card", "ref": ref, "frm": frm, "to": to}]}


class Venues(unittest.TestCase):
    def test_a_starter_stall_costs_nothing(self):
        led = ledger.build(feed((1, "venue.opened", {"venue": "v09", "owner": "t03", "bond": 0, "starter": True,
                                                    "name": "Puesto de Team 3"})))
        self.assertEqual(led["t03"]["cash"], 400)
        self.assertEqual(led["t03"]["bonds"], 0)
        self.assertEqual(led["t03"]["venue"], "v09")

    def test_an_own_venue_costs_its_bond_plus_20(self):
        led = ledger.build(feed((1, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250, "name": "x"})))
        self.assertEqual(led["t03"]["cash"], 400 - 270)
        no_bond_field = ledger.build(feed((1, "venue.opened", {"venue": "v20", "owner": "t03", "name": "x"})))
        self.assertEqual(no_bond_field["t03"]["cash"], 400 - 270)

    def test_replacing_the_stall_costs_only_the_new_venue(self):
        led = ledger.build(feed(
            (1, "venue.opened", {"venue": "v09", "owner": "t03", "bond": 0, "starter": True}),
            (2, "venue.closed", {"venue": "v09", "refund": 0, "replaced": True}),
            (2, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250})))
        self.assertEqual(led["t03"]["cash"], 130)
        self.assertEqual(led["t03"]["venue"], "v20")

    def test_a_closed_venue_pays_its_refund_to_the_owner(self):
        led = ledger.build(feed(
            (1, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250}),
            (2, "venue.closed", {"venue": "v20", "refund": 250})))
        self.assertEqual(led["t03"]["cash"], 400 - 270 + 250)
        self.assertEqual(led["t03"]["refunds"], 250)
        self.assertIsNone(led["t03"]["venue"])

    def test_a_fee_on_a_team_venue_goes_to_its_owner_and_el_rastro_keeps_its_own(self):
        led = ledger.build(feed(
            (1, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250}),
            (2, "settlement", settlement("t01", "t02", "LAV-01", 10, "v20", fee=1, asset=901)),
            (3, "settlement", settlement("t01", "t02", "LAV-02", 10, "rastro", fee=2, asset=902))))
        self.assertEqual(led["t03"]["cash"], 400 - 270 + 1)
        self.assertEqual(led["t03"]["fees_earned"], 1)
        self.assertEqual(led["t02"]["cash"], 400 - 10 - 1 - 10 - 2)  # the buyer accepted both (no listing seen)
        self.assertEqual(led["t01"]["cash"], 420)


def listed(offer_id, maker, give_cash=0, give_ids=(), want_cash=0, want_refs=(), to=None):
    return {"offer": {"id": offer_id, "maker": maker, "to": to, "venue": "rastro", "status": "open",
                      "give": {"cash": give_cash, "assets": [{"id": i, "kind": "card"} for i in give_ids], "types": []},
                      "want": {"cash": want_cash, "assets": [], "types": [f"card:{r}" for r in want_refs]}}}


def two_way(price, fee, *moves):
    """A settlement with cards going both ways: moves are (asset id, ref, frm, to)."""
    return {"venue": "rastro", "persona": None, "fee": fee, "price": price, "parties": sorted({m[2] for m in moves}),
            "items": [{"id": i, "kind": "card", "ref": r, "frm": f, "to": t} for i, r, f, t in moves]}


class Packages(unittest.TestCase):
    """Cards both ways plus cash: the accepted listing says who paid (tick 844: our 38 P + four cards for LAV-10)."""

    def test_the_maker_who_gives_cash_pays_it_and_the_acceptor_pays_the_fee(self):
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t03", give_cash=38, give_ids=(960, 581), want_refs=("LAV-10",))),
            (2, "settlement", two_way(38, 7, (960, "RET-01", "t03", "t02"), (581, "RET-02", "t03", "t02"),
                                      (490, "LAV-10", "t02", "t03")))))
        self.assertEqual(led["t03"]["cash"], 400 - 38)
        self.assertEqual(led["t02"]["cash"], 400 + 38 - 7)
        self.assertEqual((led["t03"]["fees"], led["t02"]["fees"]), (0, 7))
        self.assertEqual((led["t03"]["trades"], led["t02"]["trades"]), (1, 1))
        self.assertEqual(led["t03"]["known_cards"], {"LAV-10": 1})

    def test_the_maker_who_wants_cash_is_paid(self):
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t01", give_ids=(5,), want_cash=10, want_refs=("SAL-01",))),
            (2, "settlement", two_way(10, 2, (5, "LAV-01", "t01", "t02"), (6, "SAL-01", "t02", "t01")))))
        self.assertEqual(led["t01"]["cash"], 410)
        self.assertEqual(led["t02"]["cash"], 400 - 10 - 2)

    def test_without_a_matching_listing_the_cash_stays_put(self):
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t01", give_cash=10, give_ids=(5, 7), want_refs=("SAL-01",))),
            (2, "settlement", two_way(10, 2, (5, "LAV-01", "t01", "t02"), (6, "SAL-01", "t02", "t01")))))
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (400, 400))  # asset 7 never moved: not that listing


class Acceptor(unittest.TestCase):
    """An ask and a bid both standing: the settled price tells which one was taken, and so who pays the fee."""

    def board(self, price):
        return ledger.build(feed(
            (1, "offer.listed", listed(1, "t03", give_cash=88, want_refs=("LAT-09",))),
            (2, "offer.listed", listed(2, "t02", give_ids=(15,), want_cash=135)),
            (3, "settlement", settlement("t02", "t03", "LAT-09", price, "rastro", fee=6, asset=15))))

    def test_settled_at_the_bid_the_seller_accepted(self):
        led = self.board(88)
        self.assertEqual((led["t03"]["cash"], led["t02"]["cash"]), (400 - 88, 400 + 88 - 6))

    def test_settled_at_the_ask_the_buyer_accepted(self):
        led = self.board(135)
        self.assertEqual((led["t03"]["cash"], led["t02"]["cash"]), (400 - 135 - 6, 400 + 135))


class Grants(unittest.TestCase):
    SATURDAY = "El Retiro has arrived: a pack and the Saturday allowance (150 primas) for everyone"
    SUNDAY = "The Sunday allowance: 150 primas for everyone"

    def test_a_fired_grant_without_cash_reads_it_from_its_note(self):
        led = ledger.build(feed((1, "schedule.fired", {"action": "grant_all", "note": self.SATURDAY})))
        self.assertEqual({t: r["cash"] for t, r in led.items()}, {t: 550 for t in TEAMS})
        self.assertEqual(led["t01"]["grants"], 150)

    def test_a_scheduled_grant_reads_its_params(self):
        schedule = {"upcoming": [{"action": "grant_all", "note": "Sunday money", "params": {"cash": 120}}]}
        self.assertEqual(ledger.grant_cash(schedule, {"action": "grant_all", "note": "Sunday money"}), 120)
        self.assertEqual(ledger.grant_cash(None, {"action": "grant_all", "note": self.SUNDAY}), 150)
        self.assertEqual(ledger.grant_cash(None, {"action": "grant_all", "note": "a pack for everyone"}), 0)
        self.assertEqual(ledger.grant_cash(None, {"cash": 75, "note": self.SUNDAY}), 75)


class Holes(unittest.TestCase):
    def test_a_contiguous_feed_is_left_alone(self):
        events = feed((1, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250}),
                      (2, "schedule.fired", {"action": "grant_all", "note": "x"}))
        self.assertEqual(ledger.gaps(events), [])
        self.assertIs(ledger.fill_gaps(events), events)

    def test_a_hole_is_filled_by_id_from_a_source(self):
        events = feed((1, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250}))
        events.append({"id": 50, "tick": 9, "type": "announcement", "payload": {}})
        missing = {"id": 20, "tick": 4, "type": "settlement",
                   "payload": {**settlement("t01", "t02", "LAV-03", 30, "rastro", fee=3), "persona": None}}
        outside = {"id": 60, "tick": 10, "type": "settlement", "payload": settlement("t01", "t02", "LAV-04", 30, "rastro")}
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "feed.jsonl"
            src.write_text("\n".join(json.dumps(e) for e in (events[0], missing, outside)) + "\n", encoding="utf-8")
            filled = ledger.fill_gaps(events, (src,))
        self.assertEqual([e["id"] for e in filled], [1, 2, 3, 4, 20, 50])
        self.assertEqual(ledger.build(filled, fill=False)["t02"]["cash"], 400 - 30 - 3)


class RealFeed(unittest.TestCase):
    """The committed feed (logs/feed, with the Friday hole at ticks 49-118) against our real cash in logs/score.jsonl."""

    LAST = 630  # checked by hand on Saturday 3 Oct: every snapshot up to here matches

    @classmethod
    def setUpClass(cls):
        events = [e for e in load(ROOT / "logs" / "feed" / "feed.jsonl") if e["tick"] <= cls.LAST]
        cls.holes = ledger.gaps(events)
        cls.led = ledger.build(events)
        cls.score = [r for r in load(ROOT / "logs" / "score.jsonl") if r["tick"] <= cls.LAST]

    def test_the_friday_hole_is_there_and_gets_filled(self):
        self.assertEqual([(lo, hi) for _, lo, _, hi in self.holes], [(48, 119)])

    def test_our_rebuilt_cash_matches_every_snapshot(self):
        hist = self.led["t03"]["history"]
        got = [(r["tick"], ledger.cash_at(hist, r["tick"])) for r in self.score]
        self.assertEqual(got, [(r["tick"], r["cash"]) for r in self.score])
        self.assertGreaterEqual(len(got), 10)

    def test_no_team_goes_below_zero(self):
        for team, r in self.led.items():
            self.assertGreaterEqual(min(c for _, c in r["history"]), 0, team)

    def test_our_cash_after_lat09_matches_the_live_reading(self):
        # /api/me read by the Mini's live score at 16:38:00 (score.view.log) = tick 767 in the feed: 154 P. t16 sold
        # LAT-09 into our 88 P bid at tick 724 while its own ask stood at 135, so the 6 P fee was t16's, not ours.
        events = [e for e in load(ROOT / "logs" / "feed" / "feed.jsonl") if e["tick"] <= 767]
        self.assertEqual(ledger.cash_at(ledger.build(events)["t03"]["history"], 767), 154)


if __name__ == "__main__":
    unittest.main()
