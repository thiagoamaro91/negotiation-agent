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

    def test_the_venue_owner_gets_the_fee_even_when_its_payer_is_unknown(self):
        swap = two_way(0, 2, (5, "LAV-08", "t01", "t02"), (6, "SAL-01", "t02", "t01"))
        swap["venue"] = "v20"
        led = ledger.build(feed((1, "venue.opened", {"venue": "v20", "owner": "t03", "bond": 250, "name": "x"}),
                                (2, "settlement", swap)))
        self.assertEqual((led["t03"]["cash"], led["t03"]["cash_unsure"]), (400 - 270 + 2, 0))
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (2, 2))

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

    def test_without_a_matching_listing_the_cash_stays_put_and_the_whole_amount_is_unsure(self):
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t01", give_cash=10, give_ids=(5, 7), want_refs=("SAL-01",))),
            (2, "settlement", two_way(10, 2, (5, "LAV-01", "t01", "t02"), (6, "SAL-01", "t02", "t01")))))
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (400, 400))  # asset 7 never moved: not that listing
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (12, 12))

    def test_an_unmatched_package_bounds_every_balance_it_could_leave(self):
        led = ledger.build(feed((2, "settlement", two_way(38, 7, (960, "RET-01", "t03", "t02"),
                                                           (490, "LAV-10", "t02", "t03")))))
        for team in ("t02", "t03"):
            low, high = led[team]["cash"] - led[team]["cash_unsure"], led[team]["cash"] + led[team]["cash_unsure"]
            for real in (400 - 38 - 7, 400 - 38, 400 + 38 - 7, 400 + 38):  # who paid the cash, who took the listing
                self.assertTrue(low <= real <= high, (team, real, low, high))

    def test_a_later_cancelled_listing_that_does_not_fit_cannot_take_the_swap(self):
        # t02's listing (SAL-01 for LAV-08) was taken by t01; t01's own later listing (LAV-08 for MAL-09) was cancelled
        rep = {}
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t02", give_ids=(6,), want_refs=("LAV-08",))),
            (2, "offer.listed", listed(2, "t01", give_ids=(5,), want_refs=("MAL-09",))),
            (2, "offer.cancelled", {"offer": 2, "venue": "rastro"}),
            (3, "settlement", two_way(0, 2, (5, "LAV-08", "t01", "t02"), (6, "SAL-01", "t02", "t01")))), report=rep)
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (398, 400))
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (0, 0))

    def test_a_fitting_listing_that_was_cancelled_or_sits_on_another_venue_does_not_count(self):
        for other in ((2, "offer.cancelled", {"offer": 2, "venue": "rastro"}), None):
            rows = [(1, "offer.listed", listed(1, "t02", give_ids=(6,), want_refs=("LAV-08",))),
                    (2, "offer.listed", listed(2, "t01", give_ids=(5,), want_refs=("SAL-01",)))]
            if other:
                rows.append(other)  # t01's own listing fits the swap too, but was withdrawn first
            else:
                rows[1][2]["offer"]["venue"] = "v07"  # ... or was posted on another venue
            rows.append((3, "settlement", two_way(0, 2, (5, "LAV-08", "t01", "t02"), (6, "SAL-01", "t02", "t01"))))
            led = ledger.build(feed(*rows))
            self.assertEqual((led["t01"]["cash"], led["t02"]["cash"], led["t01"]["cash_unsure"]), (398, 400, 0), other)

    def test_two_listings_that_read_the_swap_differently_leave_it_unsure(self):
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t02", give_ids=(6,), want_refs=("LAV-08",))),
            (2, "offer.listed", listed(2, "t01", give_ids=(5,), want_refs=("SAL-01",))),
            (3, "settlement", two_way(0, 2, (5, "LAV-08", "t01", "t02"), (6, "SAL-01", "t02", "t01")))))
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (400, 400))
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (2, 2))


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


def listed_until(offer_id, maker, expires, **kw):
    out = listed(offer_id, maker, **kw)
    out["offer"]["expires_tick"] = expires
    return out


class WhoPaysTheFee(unittest.TestCase):
    """The rules that tell the acceptor when the price alone is not enough (Saturday's whole feed: 105 fees told by
    price, 1 by the board, 9 packages or swaps, 2 unsure of which 1 settled by the consistency pass)."""

    def test_an_offer_taken_on_its_last_tick_still_counts(self):
        # t15's bid 1513 (21 P for MAL-06) expired at tick 102; t07 sold into it and it settled at 103
        led = ledger.build(feed(
            (1, "offer.listed", listed_until(1, "t02", 200, give_ids=(103,), want_cash=30)),
            (2, "offer.listed", listed_until(2, "t03", 102, give_cash=21, want_refs=("MAL-06",))),
            (103, "settlement", settlement("t02", "t03", "MAL-06", 21, "rastro", fee=3, asset=103))))
        self.assertEqual((led["t02"]["cash"], led["t03"]["cash"]), (400 + 21 - 3, 400 - 21))

    def test_with_both_at_the_price_the_offer_that_left_the_board_was_filled(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in (
                {"tick": 380, "what": "rastro", "body": {"offers": [{"id": 1}, {"id": 2}]}},
                {"tick": 381, "what": "rastro", "body": {"offers": [{"id": 1}]}})))
            posted = ledger.listings(feed(
                (370, "offer.listed", listed(1, "t02", give_ids=(77,), want_cash=8)),
                (378, "offer.listed", listed(2, "t03", give_cash=8, want_refs=("MAL-04",)))))
            first = {"id": 77, "ref": "MAL-04"}
            self.assertEqual(ledger.acceptor_of(posted, first, "t03", "t02", 8, 381, "rastro", ledger.Boards(path)),
                             ("t02", "board"))  # our bid 2 left the board: the seller took it
            self.assertEqual(ledger.acceptor_of(posted, first, "t03", "t02", 8, 381, "rastro",
                                                ledger.Boards(Path(d) / "none.jsonl")), ("t03", "unsure"))

    def test_an_unsure_fee_moves_to_the_other_side_when_it_would_overdraw(self):
        # no listing at 50: the old rule charges the seller (the buyer's 40 P bid stood); then the seller pays a dealer
        # all its cash, which it could not have done after a 5 P fee: the buyer paid it
        rep = {}
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t02", give_cash=40, want_refs=("SAL-09",))),
            (2, "settlement", settlement("t01", "t02", "SAL-09", 50, "rastro", fee=5, asset=60)),
            (3, "settlement", {"persona": "picaros", "price": 450, "items": [{"id": 9, "ref": "RET-09", "frm": "picaros", "to": "t01"}]})),
            report=rep)
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (0, 400 - 50 - 5))
        self.assertEqual([u["tick"] for u in rep["flipped"]], [2])
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (0, 0))

    def test_the_consistency_pass_checks_the_other_side_too(self):
        # t01 buys from t02 (tick 2) and from t03 (tick 3), 10 P + 2 P fee each, no listings: the old rule charges t01
        # both fees, and t01 then spends 378 P. Moving the later fee would sink t03 (it spent all its 410 P), so the
        # earlier one moves: balances (0, 408, 0), never (0, 410, -2)
        rep = {}
        led = ledger.build(feed(
            (2, "settlement", settlement("t02", "t01", "SAL-01", 10, "rastro", fee=2, asset=61)),
            (3, "settlement", settlement("t03", "t01", "SAL-02", 10, "rastro", fee=2, asset=62)),
            (4, "settlement", {"persona": "picaros", "price": 410, "items": [{"id": 91, "ref": "RET-09", "frm": "picaros", "to": "t03"}]}),
            (5, "settlement", {"persona": "picaros", "price": 378, "items": [{"id": 92, "ref": "RET-10", "frm": "picaros", "to": "t01"}]})),
            report=rep)
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"], led["t03"]["cash"]), (0, 408, 0))
        self.assertEqual(rep["overdrawn"], [])
        self.assertEqual([u["tick"] for u in rep["flipped"]], [2])
        self.assertEqual([led[t]["cash_unsure"] for t in ("t01", "t02", "t03")], [0, 0, 0])  # the only way that fits

    def test_when_several_ways_fit_the_fees_stay_unsure(self):
        # the same two trades, but t03 keeps its cash: t02, t03 or both could have paid a fee, so nothing is pinned
        # and t03 is 408 or 410, never "408 ±0"
        rep = {}
        led = ledger.build(feed(
            (2, "settlement", settlement("t02", "t01", "SAL-01", 10, "rastro", fee=2, asset=61)),
            (3, "settlement", settlement("t03", "t01", "SAL-02", 10, "rastro", fee=2, asset=62)),
            (5, "settlement", {"persona": "picaros", "price": 378, "items": [{"id": 92, "ref": "RET-10", "frm": "picaros", "to": "t01"}]})),
            report=rep)
        self.assertEqual(rep["overdrawn"], [])
        self.assertEqual([led[t]["cash_unsure"] for t in ("t01", "t02", "t03")], [4, 2, 2])
        for team, possible in (("t01", (0, 2)), ("t02", (408, 410)), ("t03", (408, 410))):
            for real in possible:
                self.assertLessEqual(abs(real - led[team]["cash"]), led[team]["cash_unsure"], (team, real))

    def test_a_settlement_of_unknown_direction_counts_as_an_unknown_in_the_consistency_pass(self):
        # t01 buys from t02 (10 P + an unsure 2 P fee), then an unmatched 10 P package with t03 whose cash may have
        # gone to t01, then t01 spends 390 P: t01 can afford it either way if t03 paid it, so the fee is not pinned
        rep = {}
        led = ledger.build(feed(
            (2, "settlement", settlement("t02", "t01", "SAL-01", 10, "rastro", fee=2, asset=61)),
            (3, "settlement", two_way(10, 0, (70, "RET-01", "t01", "t03"), (71, "LAV-10", "t03", "t01"))),
            (5, "settlement", {"persona": "picaros", "price": 390, "items": [{"id": 92, "ref": "RET-10", "frm": "picaros", "to": "t01"}]})),
            report=rep)
        self.assertEqual(rep["settled"], [])
        for team, possible in (("t01", (8, 10)), ("t02", (408, 410))):
            for real in possible:
                self.assertLessEqual(abs(real - led[team]["cash"]), led[team]["cash_unsure"], (team, real))

    def test_an_unknown_left_out_of_the_search_pins_nothing_it_touches(self):
        # two unsure fees of t01, either could have moved; with room for one unknown only, the kept one must not be
        # pinned just because the other was held at the old rule
        rows = ((2, "settlement", settlement("t02", "t01", "SAL-01", 10, "rastro", fee=2, asset=61)),
                (3, "settlement", settlement("t03", "t01", "SAL-02", 10, "rastro", fee=2, asset=62)),
                (5, "settlement", {"persona": "picaros", "price": 378, "items": [{"id": 92, "ref": "RET-10", "frm": "picaros", "to": "t01"}]}))
        saved = ledger.MAX_FLIP_COMBOS
        try:
            ledger.MAX_FLIP_COMBOS = 2
            led = ledger.build(feed(*rows))
        finally:
            ledger.MAX_FLIP_COMBOS = saved
        self.assertEqual((led["t02"]["cash_unsure"], led["t03"]["cash_unsure"]), (2, 2))

    def test_a_settlement_without_known_sides_pins_nothing(self):
        rep = {}
        ledger.build(feed(
            (2, "settlement", settlement("t02", "t01", "SAL-01", 10, "rastro", fee=2, asset=61)),
            (3, "settlement", settlement("t03", "t01", "SAL-02", 10, "rastro", fee=2, asset=62)),
            (4, "settlement", {"persona": "picaros", "price": 410, "items": [{"id": 91, "ref": "RET-09", "frm": "picaros", "to": "t03"}]}),
            (5, "settlement", {"persona": "picaros", "price": 378, "items": [{"id": 92, "ref": "RET-10", "frm": "picaros", "to": "t01"}]}),
            (6, "settlement", {"persona": None, "price": 50, "fee": 3, "items": []})), report=rep)
        self.assertEqual(rep["settled"], [])  # without it, both fees are pinned (test_the_consistency_pass_checks_...)

    def test_a_settlement_without_items_is_reported_not_fatal(self):
        rep = {}
        led = ledger.build(feed((2, "settlement", {"persona": None, "price": 38, "fee": 7, "parties": ["t01", "t02"],
                                                   "items": []}),
                                (3, "settlement", {"persona": None, "price": 5}),
                                (4, "settlement", {"persona": "abuela", "price": 9, "items": None})), report=rep)
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (400, 400))
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (45, 45))
        self.assertEqual(sum(1 for u in rep["unsure"] if u.get("incomplete")), 3)

    def test_an_offer_cancelled_between_snapshots_is_not_read_as_filled(self):
        # boards at ticks 1 and 4; our bid (on the board at 1) is cancelled at tick 4; t02's ask appears at tick 2 and
        # is what the tick-3 settlement filled. The board cannot tell: unsure, never "the seller took our bid"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in (
                {"tick": 1, "what": "rastro", "body": {"offers": [{"id": 1}]}},
                {"tick": 4, "what": "rastro", "body": {"offers": []}})))
            posted = ledger.listings(feed(
                (0, "offer.listed", listed(1, "t03", give_cash=8, want_refs=("MAL-04",))),
                (2, "offer.listed", listed(2, "t02", give_ids=(77,), want_cash=8)),
                (4, "offer.cancelled", {"offer": 1, "venue": "rastro"})))
            self.assertEqual(ledger.acceptor_of(posted, {"id": 77, "ref": "MAL-04"}, "t03", "t02", 8, 3, "rastro",
                                                ledger.Boards(path)), ("t03", "unsure"))

    def test_the_board_tells_only_a_clean_fill_against_an_offer_that_stayed(self):
        # ask 2 sits on the board before and after; bid 1 leaves it. A fill only if bid 1 was neither cancelled nor
        # expired in between, and only if the ask was on the board before too
        cases = (({}, {"tick": 0}, ("t02", "board")),                                 # clean: the seller took our bid
                 ({"cancel": 4}, {"tick": 0}, ("t03", "unsure")),                     # bid withdrawn in between
                 ({"expires": 2}, {"tick": 0}, ("t03", "unsure")),                    # bid ran out in between
                 ({}, {"tick": 2, "absent": True}, ("t03", "unsure")))                # ask was not on the board before
        for bid, ask, want in cases:
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "snapshots.jsonl"
                before = [{"id": 1}] + ([] if ask.get("absent") else [{"id": 2}])
                path.write_text("".join(json.dumps(r) + "\n" for r in (
                    {"tick": 1, "what": "rastro", "body": {"offers": before}},
                    {"tick": 4, "what": "rastro", "body": {"offers": [] if ask.get("absent") else [{"id": 2}]}})))
                rows = [(0, "offer.listed", listed_until(1, "t03", bid.get("expires"), give_cash=8, want_refs=("MAL-04",))),
                        (ask["tick"], "offer.listed", listed(2, "t02", give_ids=(77,), want_cash=8))]
                if bid.get("cancel"):
                    rows.append((bid["cancel"], "offer.cancelled", {"offer": 1, "venue": "rastro"}))
                posted = ledger.listings(feed(*rows))
                got = ledger.acceptor_of(posted, {"id": 77, "ref": "MAL-04"}, "t03", "t02", 8, 3, "rastro", ledger.Boards(path))
                self.assertEqual(got, want, (bid, ask))

    def test_the_board_is_read_next_to_the_feed_in_use(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "snapshots.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
                {"tick": 380, "what": "rastro", "body": {"offers": [{"id": 1}, {"id": 2}]}},
                {"tick": 381, "what": "rastro", "body": {"offers": [{"id": 1}]}})))
            posted = ledger.listings(feed(
                (370, "offer.listed", listed(1, "t02", give_ids=(77,), want_cash=8)),
                (378, "offer.listed", listed(2, "t03", give_cash=8, want_refs=("MAL-04",)))))
            saved = ledger.vi.FEED
            try:
                ledger.vi.FEED = Path(d)  # what tools/dashboard.py does for --feed
                got = ledger.acceptor_of(posted, {"id": 77, "ref": "MAL-04"}, "t03", "t02", 8, 381, "rastro")
            finally:
                ledger.vi.FEED = saved
            self.assertEqual(got, ("t02", "board"))

    def test_the_latest_snapshot_of_a_tick_is_the_one_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in (
                {"tick": 380, "what": "rastro", "body": {"offers": [{"id": 1}, {"id": 2}]}},
                {"tick": 381, "what": "rastro", "body": {"offers": [{"id": 1}, {"id": 2}]}},  # before the fill
                {"tick": 381, "what": "rastro", "body": {"offers": [{"id": 1}]}})))           # after it
            self.assertEqual(ledger.Boards(path).gone(381, "rastro"), {2})

    def test_an_unsure_fee_left_alone_is_reported_on_both_sides(self):
        rep = {}
        led = ledger.build(feed((2, "settlement", settlement("t01", "t02", "LAT-02", 18, "rastro", fee=3, asset=53))),
                           report=rep)
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (418, 400 - 18 - 3))  # the old rule: the buyer
        self.assertEqual((led["t01"]["cash_unsure"], led["t02"]["cash_unsure"]), (3, 3))
        self.assertEqual(rep["how"]["unsure"], 1)

    def test_a_card_for_card_swap_charges_its_fee_to_the_side_that_took_the_listing(self):
        led = ledger.build(feed(
            (1, "offer.listed", listed(1, "t01", give_ids=(5,), want_refs=("SAL-01",))),
            (2, "settlement", two_way(0, 2, (5, "LAV-08", "t01", "t02"), (6, "SAL-01", "t02", "t01")))))
        self.assertEqual((led["t01"]["cash"], led["t02"]["cash"]), (400, 398))
        self.assertEqual((led["t01"]["trades"], led["t02"]["trades"]), (1, 1))


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
