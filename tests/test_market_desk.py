"""Market desk: fees, the gain rule, held cards, protected pages, caps, structure checks, bids.

    python3 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "tools"))

import market_desk as md  # noqa: E402
import rastro_seller  # noqa: E402

# Every distinct (price, cards, fee) of Friday's 46 team-to-team settlements on El Rastro (logs/feed-vm/feed.jsonl).
FRIDAY_FEES = [(5, 1, 2), (6, 1, 2), (7, 1, 2), (8, 1, 2), (9, 1, 2), (10, 1, 2), (12, 1, 2), (18, 1, 2), (18, 2, 3),
               (21, 1, 3), (22, 1, 3), (23, 1, 3), (26, 1, 3), (27, 1, 3), (28, 1, 3), (35, 1, 3), (40, 2, 4),
               (53, 1, 4), (60, 1, 4), (65, 1, 5), (70, 1, 5), (74, 1, 5), (75, 1, 5), (80, 1, 5)]

AFFINITY = {"LAV": 1.6, "MAL": 0.7, "LAT": 1.1, "SAL": 1.3}


def catalog():
    sets = []
    for sid in ("LAV", "MAL", "LAT", "SAL"):
        cards = []
        for n in range(1, 13):
            rarity = ["common"] * 5 + ["uncommon"] * 3 + ["rare"] * 2 + ["epic", "legendary"]
            r = rarity[n - 1]
            cards.append({"id": f"{sid}-{n:02d}", "rarity": r,
                          "book": {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}[r],
                          "page": n <= 10, "hidden": False})
        sets.append({"id": sid, "released": True, "cards": cards})
    return {"sets": sets, "values": {"copy_marginals": [1.0, 0.25, 0.1], "page_bonus": 0.25}}


CAT = catalog()


def card(aid, ref, serial=1):
    return {"id": aid, "kind": "card", "ref": ref, "serial": serial, "set": ref[:3]}


def listing(oid, ref, price, *, aid=None, maker="m1", venue="rastro", **extra):
    o = {"id": oid, "maker": maker, "to": None, "venue": venue, "thread": None, "status": "open",
         "give": {"cash": 0, "assets": [card(aid or 9000 + oid, ref, 5)], "types": []},
         "want": {"cash": price, "assets": [], "types": []}, "expires_tick": 200, "created_tick": 90}
    o.update(extra)
    return o


def bid(oid, ref, price, *, maker="m2", venue="rastro", **extra):
    o = {"id": oid, "maker": maker, "to": None, "venue": venue, "thread": None, "status": "open",
         "give": {"cash": price, "assets": [], "types": []},
         "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}, "expires_tick": 200, "created_tick": 90}
    o.update(extra)
    return o


def snap(boards, holdings=None, cash=1000, mine=None, tick=100, venues=None):
    return {"tick": tick, "t_hours": tick / 60, "me_id": "t03", "cash": cash, "holdings": holdings or {},
            "venues": venues or {"rastro": {"fee": (500, 1), "owner": "world", "house": True},
                                 "v02": {"fee": (0, 0), "owner": "t12", "house": False}},
            "boards": boards, "mine": mine or [], "released": {"LAV", "MAL", "LAT", "SAL"}}


def run(boards, holdings=None, cfg=None, ledger=None, **kw):
    h = holdings or {}
    cfg = cfg or md.Config(bids=False, min_cash=0)
    valuer = md.Valuer(CAT, AFFINITY, {r: len(a) for r, a in h.items()})
    return md.decide(snap(boards, h, **kw), valuer, md.Tape(), ledger or md.Ledger(), cfg, {})


def rec(res, oid):
    return next(r for r in res["records"] if r.get("offer") == oid)


class Fees(unittest.TestCase):
    def test_friday_table(self):
        for price, n, fee in FRIDAY_FEES:
            self.assertEqual(md.fee_for(price, md.DEFAULT_FEE, n), fee, (price, n))
            if n == 1:  # the seller's single-card formula agrees
                self.assertEqual(rastro_seller.fee_for(price, rastro_seller.DEFAULT_FEE), fee, price)

    def test_team_venue_fee(self):
        self.assertEqual(md.fee_for(50, (0, 0)), 0)
        self.assertEqual(md.fee_for(50, (100, 0)), 1)       # 1 % of 50 = 0.5 -> 1
        self.assertEqual(md.fee_for(50, md.WORST_FEE), 10)  # 10 % + 5


class GainRule(unittest.TestCase):
    # SAL common: value 13 to us. need = max(3, 1.3) = 3.
    def test_boundary(self):
        r = run({"rastro": [listing(1, "SAL-05", 8)]})        # 13 - 8 - 2 = 3 >= 3
        self.assertEqual(rec(r, 1)["action"], "take")
        self.assertEqual(rec(r, 1)["gain"], 3.0)
        r = run({"rastro": [listing(1, "SAL-05", 9)]})        # 13 - 9 - 2 = 2 < 3
        self.assertEqual(rec(r, 1)["action"], "skip")
        self.assertIsNone(r["accept"])

    def test_ten_percent_of_value(self):
        # LAV rare: value 112, need 11.2. 94 + fee 6 -> 12 (take); 95 + 6 -> 11 (skip)
        cfg = md.Config(bids=False, min_cash=0, max_price_rare=100)
        self.assertEqual(rec(run({"rastro": [listing(1, "LAV-09", 94)]}, cfg=cfg), 1)["action"], "take")
        self.assertEqual(rec(run({"rastro": [listing(1, "LAV-09", 95)]}, cfg=cfg), 1)["action"], "skip")

    def test_venue_fee_counts(self):
        # on a 0 % team venue the same 9 P listing passes (13 - 9 - 0 = 4)
        r = run({"v02": [listing(1, "SAL-05", 9, venue="v02")]})
        self.assertEqual(rec(r, 1)["action"], "take")
        self.assertEqual(rec(r, 1)["venue_owner"], "t12")
        cfg = md.Config(bids=False, min_cash=0, team_venues=False)
        self.assertEqual(rec(run({"v02": [listing(1, "SAL-05", 9, venue="v02")]}, cfg=cfg), 1)["action"], "skip")


class HeldCards(unittest.TestCase):
    def test_never_buy_a_held_card(self):
        h = {"LAV-09": [card(1, "LAV-09")]}
        r = run({"rastro": [listing(1, "LAV-09", 1)]}, holdings=h)   # 1 P for a 112 card, but we hold one
        self.assertEqual(rec(r, 1)["action"], "skip")
        self.assertIn("we hold", rec(r, 1)["reason"])
        self.assertIsNone(r["accept"])

    def test_settling_offer_blocks(self):
        mine = [{"id": 77, "maker": "t03", "status": "queued", "give": {"cash": 9}, "want": {"types": ["card:SAL-05"]}}]
        r = run({"rastro": [listing(1, "SAL-05", 5)]}, mine=mine)
        self.assertEqual(rec(r, 1)["action"], "skip")
        self.assertIn("settling", rec(r, 1)["reason"])


class ServerValues(unittest.TestCase):
    def test_server_value_wins_cached_and_compared(self):
        calls = []

        def online(ref):
            calls.append(ref)
            return 218.0   # 112 + a page bonus the offline model leaves out

        h = {f"LAV-{i:02d}": [card(i, f"LAV-{i:02d}")] for i in range(1, 10)}   # LAV-10 completes the page
        valuer = md.Valuer(CAT, AFFINITY, {r: 1 for r in h}, online=online)
        cfg = md.Config(bids=False, min_cash=0, max_price_rare=150, cap_hour=500, cap_day=500)
        board = {"rastro": [listing(1, "LAV-10", 130), listing(2, "SAL-05", 40)]}
        res = md.decide(snap(board, h), valuer, md.Tape(), md.Ledger(), cfg, {})
        self.assertEqual(res["accept"]["offer"], 1)
        self.assertEqual((res["accept"]["value"], res["accept"]["value_src"]), (218.0, "server"))
        self.assertEqual(valuer.mismatches, [{"card": "LAV-10", "server": 218.0, "offline": 112.0}])
        md.decide(snap(board, h), valuer, md.Tape(), md.Ledger(), cfg, {})
        self.assertEqual(calls, ["LAV-10"])     # cached; SAL-05 at 40 is clearly short and never asked


class Selling(unittest.TestCase):
    def test_protected_page_only_copy(self):
        h = {"LAV-07": [card(5, "LAV-07")]}
        r = run({"rastro": [bid(1, "LAV-07", 200)]}, holdings=h)     # huge bid, still our only LAV copy
        self.assertEqual(rec(r, 1)["action"], "skip")
        self.assertIn("protected", rec(r, 1)["reason"])

    def test_spare_sells_and_keeps_lowest_serial(self):
        h = {"LAV-07": [card(5, "LAV-07", serial=3), card(6, "LAV-07", serial=9)]}
        r = run({"rastro": [bid(1, "LAV-07", 20)]}, holdings=h)      # copy worth 10; 20 - 2 = 18 >= 10 + 3
        self.assertEqual(rec(r, 1)["action"], "take")
        self.assertEqual(r["accept"]["asset"], 6)

    def test_sell_threshold(self):
        h = {"LAV-07": [card(5, "LAV-07", 3), card(6, "LAV-07", 9)]}
        # copy 10, need 3: net must be >= 13. 15 - 2 = 13 takes, 14 - 2 = 12 does not
        self.assertEqual(rec(run({"rastro": [bid(1, "LAV-07", 15)]}, holdings=h), 1)["action"], "take")
        self.assertEqual(rec(run({"rastro": [bid(1, "LAV-07", 14)]}, holdings=h), 1)["action"], "skip")

    def test_first_copy_only_for_listed_sets(self):
        h = {"MAL-08": [card(44, "MAL-08")]}
        self.assertEqual(rec(run({"rastro": [bid(1, "MAL-08", 40)]}, holdings=h), 1)["action"], "skip")
        cfg = md.Config(bids=False, min_cash=0, sell_first_copies=("MAL",))
        self.assertEqual(rec(run({"rastro": [bid(1, "MAL-08", 40)]}, holdings=h, cfg=cfg), 1)["action"], "take")

    def test_bid_for_our_keeper_asset(self):
        h = {"LAV-07": [card(5, "LAV-07", 3), card(6, "LAV-07", 9)]}
        o = bid(1, "LAV-07", 40)
        o["want"] = {"cash": 0, "assets": [5], "types": []}
        self.assertIn("keep", rec(run({"rastro": [o]}, holdings=h), 1)["reason"])

    def test_listed_spare_left_to_the_seller(self):
        h = {"LAV-07": [card(5, "LAV-07", 3), card(6, "LAV-07", 9)]}
        mine = [{"id": 50, "maker": "t03", "status": "open", "venue": "rastro", "give": {"assets": [card(6, "LAV-07", 9)]},
                 "want": {"cash": 30}}]
        r = run({"rastro": [bid(1, "LAV-07", 40)]}, holdings=h, mine=mine)
        self.assertIn("listed by rastro_seller", rec(r, 1)["reason"])


class Caps(unittest.TestCase):
    def test_price_caps(self):
        cfg = md.Config(bids=False, min_cash=0, max_price=40, max_price_rare=100)
        # SAL rare (91): 60 + 4 -> gain 27, but over the 40 cap
        self.assertIn("cap: price", rec(run({"rastro": [listing(1, "SAL-09", 60)]}, cfg=cfg), 1)["reason"])
        # LAV rare (112): 60 is under its own 100 cap
        self.assertEqual(rec(run({"rastro": [listing(1, "LAV-09", 60)]}, cfg=cfg), 1)["action"], "take")
        cfg = md.Config(bids=False, min_cash=0, max_price=40, max_price_rare=50)
        self.assertIn("cap: price", rec(run({"rastro": [listing(1, "LAV-09", 60)]}, cfg=cfg), 1)["reason"])

    def test_min_cash(self):
        cfg = md.Config(bids=False, min_cash=280)
        self.assertIn("cash after", rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, cash=289), 1)["reason"])
        self.assertEqual(rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, cash=290), 1)["action"], "take")

    def test_spend_per_hour_and_day(self):
        cfg = md.Config(bids=False, min_cash=0, cap_hour=20, cap_day=30)
        led = md.Ledger([{"side": "buy", "t_hours": 100 / 60 - 0.5, "cost": 11, "partner": "x"}])
        self.assertIn("hour spend", rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, ledger=led), 1)["reason"])
        led = md.Ledger([{"side": "buy", "t_hours": 100 / 60 - 1.5, "cost": 21, "partner": "x"}])  # last hour: free
        self.assertIn("day spend", rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, ledger=led), 1)["reason"])
        led = md.Ledger([{"side": "buy", "t_hours": 100 / 60 - 1.5, "cost": 10, "partner": "x"}])
        self.assertEqual(rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, ledger=led), 1)["action"], "take")

    def test_partner_per_hour(self):
        cfg = md.Config(bids=False, min_cash=0, partner_hour=2)
        led = md.Ledger([{"side": "sell", "t_hours": 1.5, "partner": "m1"}, {"side": "buy", "t_hours": 1.6,
                                                                               "partner": "m1", "cost": 0}])
        self.assertIn("trades with m1", rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, ledger=led), 1)["reason"])
        led = md.Ledger([{"side": "sell", "t_hours": 0.5, "partner": "m1"}, {"side": "buy", "t_hours": 1.6,
                                                                               "partner": "m1", "cost": 0}])
        self.assertEqual(rec(run({"rastro": [listing(1, "SAL-05", 8)]}, cfg=cfg, ledger=led), 1)["action"], "take")

    def test_one_accept_per_tick(self):
        r = run({"rastro": [listing(1, "SAL-05", 8), listing(2, "SAL-04", 5), listing(3, "SAL-04", 6)]})
        self.assertEqual(r["accept"]["offer"], 2)               # best gain: 13 - 5 - 2 = 6
        self.assertEqual(rec(r, 1)["action"], "defer")
        self.assertEqual(rec(r, 3)["action"], "skip")           # same card, worse price
        self.assertEqual(sum(1 for x in r["records"] if x["action"] == "take"), 1)


class Structure(unittest.TestCase):
    def test_listing_mismatches(self):
        cases = {
            "two cards": lambda o: o["give"].update(assets=[card(1, "SAL-05"), card(2, "SAL-04")]),
            "card plus cash": lambda o: o["give"].update(cash=5),
            "card plus type": lambda o: o["give"].update(types=["pack:sobre_barrio"]),
            "wants a card back": lambda o: o["want"].update(types=["card:LAV-09"]),
            "unknown key": lambda o: o["want"].update(cards=["LAV-09"]),
            "bool price": lambda o: o["want"].update(cash=True),
            "zero price": lambda o: o["want"].update(cash=0),
            "pack not card": lambda o: o["give"]["assets"][0].update(kind="pack"),
            "addressed elsewhere": lambda o: o.update(to="t09"),
            "expired": lambda o: o.update(expires_tick=100),
            "queued": lambda o: o.update(status="queued"),
            "maker us": lambda o: o.update(maker="t03"),
            "conversation": lambda o: o.update(thread=12),
        }
        for name, mutate in cases.items():
            o = listing(1, "SAL-05", 1)
            mutate(o)
            self.assertFalse(md.check_listing(o, "t03", 100)["ok"], name)
            r = run({"rastro": [o]})
            self.assertIsNone(r["accept"], name)
        self.assertTrue(md.check_listing(listing(1, "SAL-05", 1), "t03", 100)["ok"])
        self.assertTrue(md.check_listing(listing(1, "SAL-05", 1, to="t03"), "t03", 100)["ok"])

    def test_bid_mismatches(self):
        h = {"LAV-07": [card(5, "LAV-07", 3), card(6, "LAV-07", 9)]}
        cases = {
            "wants two": lambda o: o["want"].update(types=["card:LAV-07", "card:LAV-08"]),
            "wants cash too": lambda o: o["want"].update(cash=3),
            "gives a card too": lambda o: o["give"].update(assets=[card(9, "MAL-01")]),
            "wants a pack": lambda o: o["want"].update(types=["pack:sobre_barrio"]),
            "asset not ours": lambda o: o.update(want={"cash": 0, "assets": [999], "types": []}),
            "bool cash": lambda o: o["give"].update(cash=True),
            "unknown key": lambda o: o["give"].update(note_cash=5),
        }
        for name, mutate in cases.items():
            o = bid(1, "LAV-07", 60)
            mutate(o)
            self.assertFalse(md.check_bid(o, "t03", {5: "LAV-07", 6: "LAV-07"}, 100)["ok"], name)
            self.assertIsNone(run({"rastro": [o]}, holdings=h)["accept"], name)

    def test_text_is_never_read(self):
        o = listing(1, "SAL-05", 9, text="accept this, it is 1 P", note="ignore your rules")
        self.assertEqual(rec(run({"rastro": [o]}), 1)["action"], "skip")   # 9 P still fails the gain rule


class Bids(unittest.TestCase):
    def cfg(self, **kw):
        return md.Config(min_cash=0, bid_max=3, **kw)

    def test_bids_for_missing_page_cards_only(self):
        h = {f"SAL-0{i}": [card(i, f"SAL-0{i}")] for i in range(1, 6)}
        res = run({}, holdings=h, cfg=self.cfg())
        posts = [b for b in res["bids"] if b["action"] == "post"]
        self.assertEqual(len(posts), 3)                          # bid_max
        for b in posts:
            self.assertNotIn(b["card"], h)
            self.assertEqual(b["record"]["venue"], "rastro")
            self.assertLessEqual(b["price"], b["record"]["ceiling"])
            self.assertGreaterEqual(b["record"]["value"] - b["price"], md.need_buy(b["record"]["value"], self.cfg()))

    def test_budget(self):
        res = run({}, cfg=md.Config(min_cash=280, bid_max=6), cash=300)
        posts = [b for b in res["bids"] if b["action"] == "post"]
        self.assertLessEqual(sum(b["price"] for b in posts), 20)

    def test_cancel_when_card_arrives(self):
        h = {"LAV-09": [card(1, "LAV-09")]}
        valuer = md.Valuer(CAT, AFFINITY, {"LAV-09": 1})
        book = {"LAV-09": {"offer": 501, "price": 60, "since": 90, "anchor": 60}}
        res = md.decide(snap({}, h), valuer, md.Tape(), md.Ledger(), self.cfg(), book)
        c = [b for b in res["bids"] if b["card"] == "LAV-09"]
        self.assertEqual([b["action"] for b in c], ["cancel"])

    def test_no_bid_on_the_card_we_buy(self):
        res = run({"rastro": [listing(1, "LAV-09", 60)]}, cfg=self.cfg(max_price_rare=100))
        self.assertEqual(res["accept"]["card"], "LAV-09")
        self.assertNotIn("LAV-09", [b["card"] for b in res["bids"] if b["action"] in ("post", "keep", "replace")])

    def test_step_up_and_ceiling(self):
        valuer = md.Valuer(CAT, AFFINITY, {})
        book = {"SAL-05": {"offer": 9, "price": 6, "since": 0, "anchor": 6}}
        res = md.decide(snap({}, {}, tick=100), valuer, md.Tape(), md.Ledger(),
                        md.Config(min_cash=0, bid_max=60, bid_step=1, bid_step_ticks=20,
                                  cap_hour=10 ** 4, cap_day=10 ** 4), book)
        b = next(x for x in res["bids"] if x["card"] == "SAL-05")
        self.assertEqual(b["action"], "replace")
        self.assertEqual(b["price"], 10)                         # 6 + 5 steps = 11, ceiling 13 - 3 = 10


# ---------------------------------------------------------------- the desk loop against fakes (no network)

class MemLog:
    def __init__(self):
        self.rows = []

    def event(self, event, **data):
        self.rows.append({"event": event, **data})


class FakePublic:
    def __init__(self, board, tick=100):
        self.board_offers, self.tick = board, tick

    def clock(self):
        return {"tick": self.tick, "t_hours": self.tick / 60, "tick_seconds": 30.0, "next_tick_in": 5.0,
                "doors": "open", "paused": False, "limits": {"accepts_per_team_per_tick": 1,
                                                             "offers_per_team_per_tick": 12}}

    def catalog(self):
        return CAT

    def venues(self):
        return {"venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1, "house": True, "status": "open"}]}

    def board(self, vid):
        return {"offers": list(self.board_offers)}

    def feed(self, limit=500):
        return {"events": []}


class FakeKeyed(FakePublic):
    def __init__(self, board, assets, tick=100):
        super().__init__(board, tick)
        self.assets, self.writes, self.reads = assets, [], 0
        self.duel_list, self.duel_reads = [], 0     # GET /api/duels: our live duels (a list, or an exception to raise)

    def duels(self, done=False):
        self.duel_reads += 1
        if isinstance(self.duel_list, Exception):
            raise self.duel_list
        return {"duels": list(self.duel_list)}

    def me(self):
        self.reads += 1
        return {"id": "t03", "cash": 1000, "assets": self.assets, "affinity": AFFINITY}

    def my_offers(self):
        return {"offers": []}

    def value(self, ref):
        v = md.Valuer(CAT, AFFINITY, {})
        return {"card": ref, "your_value": v.offline_more(ref)}

    def accept(self, oid, assets=None):
        self.writes.append(("accept", oid, assets))
        return {"ok": True}

    def list_offer(self, give, want, venue=None, to=None, expires_in_ticks=40):
        self.writes.append(("list", give, want, venue, to, expires_in_ticks))
        return {"offer": {"id": 7000 + len(self.writes)}}

    def cancel(self, oid):
        self.writes.append(("cancel", oid))
        return {"ok": True}


class DeskLoop(unittest.TestCase):
    def setUp(self):
        import tempfile
        from lease import Lease
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lines = []
        clock = FakePublic([]).clock()
        self.now = 1_000_000.0 + clock["tick"] * 30 + 25          # 25 s into the tick: second half
        self.lease = Lease("market", state_dir=self.dir, now=lambda: self.now, log=MemLog(),
                           duel_lock=self.dir / "duel.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def desk(self, mode, board, assets):
        keyed = FakeKeyed(board, assets)
        d = md.Desk(mode, md.Config(min_cash=0, bid_max=3), FakePublic(board), keyed=keyed, lease=self.lease,
                    log=MemLog(), heartbeat=self.dir / "desk-market.json", out=self.lines.append)
        return d, keyed

    def test_watch_sends_nothing_and_beats(self):
        d, k = self.desk("watch", [listing(1, "SAL-05", 5)], [card(1, "LAV-07")])
        res = d.tick(d.public.clock())
        self.assertEqual(res["accept"]["offer"], 1)
        self.assertEqual(k.writes, [])
        hb = __import__("json").loads((self.dir / "desk-market.json").read_text())
        self.assertEqual((hb["mode"], hb["tick"], hb["last_decision"]["offer"]), ("watch", 100, 1))
        self.assertTrue(any("TAKE" in ln for ln in self.lines))
        d.tick(d.public.clock())                                  # shadow: the would-be buy now counts as held
        self.assertTrue(any("we hold 1" in ln for ln in self.lines))

    def test_run_goes_through_the_lease(self):
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [card(1, "LAV-07")])
        d.tick(d.public.clock())
        accepts = [w for w in k.writes if w[0] == "accept"]
        lists = [w for w in k.writes if w[0] == "list"]
        self.assertEqual(accepts, [("accept", 1, None)])
        self.assertEqual(len(lists), 3)                           # bid_max
        for _, give, want, venue, to, exp in lists:
            self.assertEqual(set(give), {"cash"})
            self.assertEqual(list(want), ["cards"])
            self.assertEqual((venue, to, exp), ("rastro", None, 30))
        self.assertEqual(self.lease.snapshot()["accept"]["desk"], "market")

    def test_run_leaves_dealer_thread_offers_alone_and_cancels_duplicate_bids(self):
        # live 2026-10-03: chato.py's offer in its El Chato thread (venue None) was read as our LAV-09 bid and cancelled
        def ours(oid, cash, **kw):
            return {"id": oid, "maker": "t03", "status": "open", "to": "t04", "thread": None, "venue": "rastro",
                    "give": {"cash": cash, "assets": [], "types": []},
                    "want": {"cash": 0, "assets": [], "types": ["card:LAV-09"]}, **kw}
        d, k = self.desk("run", [], [card(1, "LAV-07")])
        k.my_offers = lambda: {"offers": [ours(2954, 65), ours(2972, 65),
                                          ours(2987, 64, thread=335, venue=None, to="chato")]}
        snap = d.snapshot(d.public.clock())
        d.sync_bids(snap)
        self.assertEqual(d.bidbook["LAV-09"]["offer"], 2954)
        self.assertEqual(d.bid_dupes, [{"card": "LAV-09", "offer": 2972}])
        d.tick(d.public.clock())
        cancels = [w[1] for w in k.writes if w[0] == "cancel"]
        self.assertNotIn(2987, cancels)                           # the dealer bot's offer is never ours to touch
        self.assertIn(2972, cancels)                              # the duplicate bid goes

    def test_run_respects_stop(self):
        (self.dir / "STOP").touch()
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [])
        d.tick(d.public.clock())
        self.assertEqual(k.writes, [])

    def test_run_decides_again_on_fresh_reads(self):
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [])
        calls = {"n": 0}
        first = d.public.board

        def board(vid):   # the listing is gone by the time the desk re-reads before accepting
            calls["n"] += 1
            return first(vid) if calls["n"] == 1 else {"offers": []}
        d.public.board = board
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [])

    def test_filled_bids_count_toward_the_caps(self):
        d, k = self.desk("watch", [], [])
        d.tick(d.public.clock())                                  # start tick 100
        d.public.feed = lambda limit=500: {"events": [
            {"id": 1, "tick": 101, "type": "settlement", "payload": {
                "settlement": 9, "kind": "trade", "parties": ["t03", "t07"], "venue": "rastro", "fee": 2, "price": 60,
                "items": [{"id": 5, "kind": "card", "ref": "LAV-09", "frm": "t07", "to": "t03"}]}},
            {"id": 2, "tick": 99, "type": "settlement", "payload": {   # before the desk started: not counted
                "settlement": 8, "kind": "trade", "parties": ["t03", "t05"], "venue": "rastro", "fee": 2, "price": 30,
                "items": [{"id": 6, "kind": "card", "ref": "LAV-10", "frm": "t05", "to": "t03"}]}},
            {"id": 3, "tick": 101, "type": "settlement", "payload": {  # we accepted: take() logs those itself
                "settlement": 10, "kind": "trade", "parties": ["t08", "t03"], "venue": "rastro", "fee": 2, "price": 9,
                "items": [{"id": 7, "kind": "card", "ref": "SAL-05", "frm": "t08", "to": "t03"}]}}]}
        d.public.tick = 102
        d.tick(d.public.clock())
        d.tick(d.public.clock())
        rows = [r for r in d.ledger.rows if r.get("settlement") is not None]
        self.assertEqual([(r["settlement"], r["side"], r["cost"], r["partner"]) for r in rows], [(9, "buy", 60, "t07")])
        self.assertEqual(d.ledger.spent(102 / 60, 1.0), 60)

    def test_read_only_clients_refuse_writes_before_the_network(self):
        ro = md.ReadOnlyBazaar("http://127.0.0.1:9", "tk-test-only", wait_on_tick=False, retries=0)
        for call in (lambda: ro.accept(1), lambda: ro.cancel(1), lambda: ro.list_offer({"cash": 1}, {"cards": ["LAV-09"]})):
            with self.assertRaises(md.BazaarError) as e:
                call()
            self.assertEqual(e.exception.code, "read_only")
        with self.assertRaises(md.BazaarError) as e:
            md.PublicClient("http://127.0.0.1:9").get("/api/me")
        self.assertEqual(e.exception.code, "not_public")

    def test_never_accepts_while_duel_lock_is_fresh(self):
        (self.dir / "duel.lock").write_text(f"{self.now + 90:.1f}\n")
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [])
        res = d.tick(d.public.clock())
        self.assertIsNone(res["accept"])
        self.assertIn("duel.lock", rec(res, 1)["reason"])
        self.assertEqual(rec(res, 1)["action"], "defer")
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [])
        self.assertTrue([w for w in k.writes if w[0] == "list"])   # bids go on: a filled bid is the seller's accept

    def test_run_yields_a_taken_accept(self):
        from lease import Lease
        other = Lease("chato", state_dir=self.dir, now=lambda: self.now, log=MemLog(), duel_lock=None)
        self.assertTrue(other.claim_accept(FakePublic([]).clock(), Lease.DEALER_FINAL))
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [])
        d.tick(d.public.clock())
        self.assertEqual([w for w in k.writes if w[0] == "accept"], [])


def duel(did, status="live", deadline=110):
    return {"duel": did, "session": 2, "status": status, "role": "seller", "deadline_tick": deadline}


class DuelGuard(unittest.TestCase):
    """GET /api/duels: duel.py may run on another machine, where results/duel.lock is invisible to the desk."""
    setUp = DeskLoop.setUp                # a temp lease 25 s into tick 100 (no inherited tests)
    tearDown = DeskLoop.tearDown

    def desk(self, mode, board, assets, duels=(), **kw):
        d, k = DeskLoop.desk(self, mode, board, assets)
        for f, v in kw.items():
            setattr(d.cfg, f, v)
        k.duel_list = duels if isinstance(duels, Exception) else list(duels)
        return d, k

    def accepts(self, k):
        return [w for w in k.writes if w[0] == "accept"]

    def test_live_duel_defers_every_accept_bids_go_on(self):
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=[duel(30, deadline=116)])
        res = d.tick(d.public.clock())
        self.assertIsNone(res["accept"])
        self.assertEqual(rec(res, 1)["action"], "defer")
        self.assertIn("duel_live", rec(res, 1)["reason"])
        self.assertIn("duel 30", rec(res, 1)["reason"])
        self.assertEqual(self.accepts(k), [])
        self.assertTrue([w for w in k.writes if w[0] == "list"])   # bids still posted
        hb = __import__("json").loads((self.dir / "desk-market.json").read_text())
        self.assertIn("duel_live", hb["duel_guard"])
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=[duel(30, deadline=116), duel(32, deadline=104)])
        self.assertIn("duel 32 is live, deadline tick 104 (4 ticks left) (+1 more)",
                      rec(d.tick(d.public.clock()), 1)["reason"])            # the most urgent one is named

    def test_finished_duels_do_not_block(self):
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=[duel(30, "deal"), duel(31, "no_deal")])
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [("accept", 1, None)])

    def test_failed_read_defers(self):
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=md.BazaarError("network", "down", 0))
        res = d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])
        self.assertIn("/api/duels unread (network)", rec(res, 1)["reason"])
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [])
        k.duel_list = None                                         # a body without a duels list
        k.duels = lambda done=False: {"error": "?"}
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])

    def test_guard_ticks_window(self):
        # tick 100: a duel ending at 120 is 20 ticks away; with --duel-guard-ticks 3 the desk may accept
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=[duel(30, deadline=120)], duel_guard_ticks=3)
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [("accept", 1, None)])
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=[duel(30, deadline=120), duel(31, deadline=103)],
                         duel_guard_ticks=3)
        res = d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])
        self.assertIn("duel 31", rec(res, 1)["reason"])

    def test_read_once_per_tick(self):
        # the accept path re-reads the account and boards before accepting; /api/duels is read once per tick
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [])
        d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [("accept", 1, None)])
        self.assertEqual(k.duel_reads, 1)
        d.public.tick = 101
        d.tick(d.public.clock())
        self.assertEqual(k.duel_reads, 2)

    def test_watch_defers_too_and_sends_nothing(self):
        d, k = self.desk("watch", [listing(1, "SAL-05", 5)], [], duels=[duel(30)])
        res = d.tick(d.public.clock())
        self.assertIsNone(res["accept"])
        self.assertEqual(k.writes, [])

    def test_keyless_has_no_server_guard(self):
        d = md.Desk("plan", md.Config(min_cash=0, bids=False), FakePublic([]), keyed=None, out=self.lines.append,
                    heartbeat=None)
        self.assertIsNone(d.duel_guard(100))

    def test_local_lock_still_honoured(self):
        (self.dir / "duel.lock").write_text(f"{self.now + 90:.1f}\n")
        d, k = self.desk("run", [listing(1, "SAL-05", 5)], [], duels=[])
        res = d.tick(d.public.clock())
        self.assertEqual(self.accepts(k), [])
        self.assertIn("duel.lock", rec(res, 1)["reason"])


if __name__ == "__main__":
    unittest.main()
