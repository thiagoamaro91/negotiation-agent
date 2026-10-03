"""agent/broker.py: the stall's rule, the guard, the policy's invariants, the fallback and the live loop's manners.
Offline: no key, no network. Run: python3 -m unittest discover tests"""
import json
import math
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))
import broker as brk  # noqa: E402
import bench_sim as bs  # noqa: E402
from bazaar_sdk import BazaarError  # noqa: E402
from starter_broker import bench_plan, public_plan  # noqa: E402

FAKE_KEY = "bk_TESTKEY_do_not_log_123"


def seller(oid, ask, maker=None, **extra):
    o = {"id": oid, "give": {"cash": 0, "assets": [{"kind": "card", "ref": "BEN-01"}], "types": []},
         "want": {"cash": ask, "assets": [], "types": []}, **extra}
    if maker:
        o["maker"] = maker
    return o


def buyer(oid, bid, maker=None, **extra):
    o = {"id": oid, "give": {"cash": bid, "assets": [], "types": []},
         "want": {"cash": 0, "assets": [], "types": ["card:BEN-01"]}, **extra}
    if maker:
        o["maker"] = maker
    return o


def book_of(bench, offers=(), fee_bps=0, fee_card=0, tick=None):
    b = {"venue": "v99", "fee_bps": fee_bps, "fee_per_card": fee_card, "offers": list(offers),
         "bench_offers": list(bench)}
    if tick is not None:
        b["tick"] = tick
    return b


def random_book(rng):
    """Several runs interleaved, many equal quotes (the tie order is the hard part of 'exactly')."""
    bench = []
    for r in range(rng.randint(1, 3)):
        for i in range(rng.randint(0, 8)):
            q = rng.choice((rng.randint(20, 30), rng.randint(10, 60)))
            oid = f"b{r + 7}-{i + 1}"
            bench.append(seller(oid, q) if rng.random() < 0.5 else buyer(oid, q))
    rng.shuffle(bench)
    return book_of(bench)


class StallRule(unittest.TestCase):
    def test_stall_plan_is_exactly_kit_bench_plan(self):
        rng = random.Random(7)
        for _ in range(3000):
            book = random_book(rng)
            self.assertEqual(brk.stall_plan(book), bench_plan(book))

    def test_ties_keep_the_books_order(self):
        book = book_of([seller("b1-1", 20), seller("b1-2", 20), buyer("b1-3", 30), buyer("b1-4", 30)])
        self.assertEqual(brk.stall_plan(book), [("b1-1", "b1-3", 25), ("b1-2", "b1-4", 25)])

    def test_policy_without_history_is_the_stall(self):
        rng = random.Random(11)
        for _ in range(300):
            book = random_book(rng)
            self.assertEqual(sorted(brk.BenchPolicy().plan(book, 5)), sorted(bench_plan(book)))


class Guard(unittest.TestCase):
    def setUp(self):
        self.book = book_of([seller("b1-1", 20, "mA"), buyer("b1-2", 30, "mB"), seller("b2-1", 10),
                             buyer("b2-2", 40, "mA"), buyer("b1-3", 25, "mA")], fee_bps=1000, fee_card=1)

    def check(self, m, why):
        ok, bad = brk.guard([m], self.book)
        self.assertEqual(ok, [])
        self.assertEqual(bad[0][1], why)

    def test_a_good_match_passes(self):
        ok, bad = brk.guard([("b1-1", "b1-2", 25)], self.book)  # 25 + ceil(2.5) + 1 = 29 <= 30
        self.assertEqual((ok, bad), ([("b1-1", "b1-2", 25)], []))

    def test_price_must_cover_the_ask(self):
        self.check(("b1-1", "b1-2", 19), "price_outside_quotes")

    def test_price_plus_fee_must_fit_the_bid(self):
        self.check(("b1-1", "b1-2", 27), "price_outside_quotes")  # 27 + 3 + 1 = 31 > 30

    def test_different_runs_never_pair(self):
        self.check(("b2-1", "b1-2", 25), "different_runs")

    def test_same_maker_never_pairs(self):
        self.check(("b1-1", "b1-3", 22), "same_maker")

    def test_an_offer_is_used_once(self):
        ok, bad = brk.guard([("b1-1", "b1-2", 25), ("b1-1", "b1-2", 25)], self.book)
        self.assertEqual(len(ok), 1)
        self.assertEqual(bad[0][1], "offer_reused")

    def test_a_buyer_cannot_sell(self):
        self.check(("b1-2", "b1-1", 25), "not_a_seller_and_a_buyer")

    def test_unknown_offer_and_bad_price(self):
        self.check(("b1-1", "b1-9", 25), "unknown_offer")
        self.check(("b1-1", "b1-2", 24.5), "price_not_whole")
        self.check(("b1-1", "b1-2", True), "price_not_whole")


class PolicyInvariants(unittest.TestCase):
    """The raw plan of our policy (before the guard), over simulated sessions where every path of it runs."""

    def assert_valid(self, plan, book):
        offers = {o["id"]: o for o in book["bench_offers"]}
        used = set()
        for sell, buy, price in plan:
            s, b = offers[sell], offers[buy]
            ask, bid = s["want"]["cash"], b["give"]["cash"]
            self.assertTrue(ask > 0 and not s["give"]["cash"], (sell, "is not a seller"))
            self.assertTrue(bid > 0 and not b["want"]["cash"], (buy, "is not a buyer"))
            self.assertEqual(brk.run_of(sell), brk.run_of(buy))
            self.assertIsInstance(price, int)
            self.assertGreaterEqual(price, ask)
            self.assertLessEqual(price + brk.fee_of(book, price), bid)
            if s.get("maker") is not None:
                self.assertNotEqual(s.get("maker"), b.get("maker"))
            self.assertNotIn(sell, used)
            self.assertNotIn(buy, used)
            used.update((sell, buy))

    def test_every_plan_respects_quotes_runs_makers_and_reuse(self):
        n = 0
        for name, params in (("standard", {"blind": "policy"}), ("hard", {"blind": "policy"}),
                             ("expiry_exact", {}), ("makers", {"blind": "policy"})):
            sc = {**bs.scenario(name), "fee_bps": 150, "fee_card": 1}
            for seed in range(60):
                rng = random.Random(f"inv:{name}:{seed}")
                day = [bs.make_session(rng, sc, run=f"b{k + 1}") for k in range(3)]
                if name == "makers":  # two offers of one maker in a run: they must never be paired
                    for traders in day:
                        traders[1]["maker"] = traders[0]["maker"]
                pol = brk.BenchPolicy(params)

                def fn(book, t):
                    nonlocal n
                    plan = pol.plan(book, t)
                    self.assert_valid(plan, book)
                    n += len(plan)
                    for sell, buy, _ in plan:
                        pol.sent(sell, buy, t)
                    return plan
                for k, traders in enumerate(day):
                    r = bs.simulate(traders, sc, fn, t0=100 * k)
                    self.assertEqual(r["refused"], 0)
        self.assertGreater(n, 500)  # the check ran on real plans

    def test_plans_across_two_runs_stay_inside_each_run(self):
        book = book_of([seller("b1-1", 20), buyer("b2-1", 40), seller("b2-2", 30), buyer("b1-2", 25)])
        pol = brk.BenchPolicy({"blind": "policy"})
        pol.plan(book, 1)
        plan = pol.plan(book, 2)  # second sight: the policy path, not the no-history fallback
        self.assertEqual(sorted(plan), [("b1-1", "b1-2", 22), ("b2-2", "b2-1", 35)])

    def test_a_better_pair_across_runs_is_never_taken(self):
        # one match b1-1 x b2-2 (20 against 60) would be worth more than both in-run pairs together
        book = book_of([seller("b1-1", 20), buyer("b1-2", 21), seller("b2-1", 39), buyer("b2-2", 60)])
        for params in ({"blind": "policy"}, {}):
            pol = brk.BenchPolicy(params)
            pol.plan(book, 1)
            self.assertEqual(sorted(pol.plan(book, 2)), [("b1-1", "b1-2", 20), ("b2-1", "b2-2", 49)])


class Fallback(unittest.TestCase):
    def test_bad_offers_do_not_break_the_plan(self):
        good = [seller("b1-1", 20), buyer("b1-2", 30)]
        junk = [{"id": "b1-3"}, {"id": "b1-4", "want": None, "give": {"cash": 5}}, "not an offer", None,
                {"id": "b1-5", "want": {"cash": "12"}, "give": {"cash": 0}},
                {"id": "b1-6", "want": {"cash": float("nan")}, "give": {"cash": 0}}]
        book = book_of(good + junk)
        pol = brk.BenchPolicy({"blind": "policy"})
        for t in (1, 2, 3):
            ok, bad, notes = brk.plan_book(book, t, pol)
            self.assertEqual(ok, [("b1-1", "b1-2", 25)])
        for broken in (None, [], "x", {"bench_offers": "zzz"}, {"bench_offers": [None, 3]}):
            ok, bad, notes = brk.plan_book(broken if isinstance(broken, dict) else {"bench_offers": broken}, 1,
                                           brk.BenchPolicy())
            self.assertEqual(ok, [])

    def test_an_exception_in_the_estimator_falls_back_to_the_stall(self):
        book = book_of([seller("b1-1", 20), seller("b1-2", 24), buyer("b1-3", 30), buyer("b1-4", 26)])
        pol = brk.BenchPolicy({"blind": "policy"})
        pol.plan(book, 1)

        def boom(*a, **k):
            raise ZeroDivisionError("estimator bug")
        pol.estimate = boom
        plan = pol.plan(book, 2)
        self.assertEqual(sorted(plan), sorted(bench_plan(book)))
        self.assertTrue(pol.notes["b1"].startswith("fallback:"))

    def test_a_broken_policy_object_falls_back_for_the_whole_book(self):
        class Broken(brk.BenchPolicy):
            def plan(self, book, tick):
                raise RuntimeError("bug")
        book = book_of([seller("b1-1", 20), buyer("b1-2", 30)])
        ok, bad, notes = brk.plan_book(book, 1, Broken())
        self.assertEqual(ok, [("b1-1", "b1-2", 25)])
        self.assertTrue(notes["*"].startswith("fallback:"))


class FakeBroker:
    def __init__(self, book, refuse=True):
        self.book_now, self.refuse, self.calls, self.tick = book, refuse, [], 1

    def clock(self):
        return {"tick": self.tick}

    def book(self):
        return json.loads(json.dumps(self.book_now))

    def match(self, sell, buy, price):
        self.calls.append((self.tick, sell, buy, price))
        if self.refuse:
            raise BazaarError("not_crossing", "refused by the fake", 409)
        return {"id": 1, "status": "queued"}


class MemLog:
    def __init__(self, path):
        self.path, self.rows, self.run_id = path, [], "test"

    def event(self, event, **data):
        self.rows.append({"event": event, **data})


class LiveLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = [1000.0]

    def tearDown(self):
        self.tmp.cleanup()

    def desk(self, fake, policy="ours", send=True):
        log = MemLog(self.dir / "broker.jsonl")
        return brk.Desk(fake, log, policy, now=lambda: self.clock[0], heartbeat=self.dir / "hb.json", send=send), log

    def loop(self, desk, n):
        for _ in range(n):
            desk.step()
            self.clock[0] += 0.5

    def test_a_refused_match_is_not_sent_again_every_half_second(self):
        for policy in ("ours", "stall"):
            fake = FakeBroker(book_of([seller("b1-1", 20), buyer("b1-2", 30)]))
            desk, log = self.desk(fake, policy)
            self.loop(desk, 40)  # 20 seconds of the same book in the same tick
            self.assertEqual(len(fake.calls), 1, policy)
            fake.book_now["bench_offers"].append(buyer("b1-3", 18))  # the book changes, the tick does not
            self.loop(desk, 10)
            self.assertEqual(len(fake.calls), 1, policy)
            fake.tick = 2  # a new tick: one more try
            self.loop(desk, 10)
            self.assertEqual(len(fake.calls), 2, policy)
            self.assertEqual(sum(r["event"] == "refused" for r in log.rows), 2)

    def test_the_book_is_planned_and_logged_once_per_state(self):
        fake = FakeBroker(book_of([seller("b1-1", 20), buyer("b1-2", 18)]))  # nothing crosses
        desk, log = self.desk(fake)
        self.loop(desk, 40)
        rows = (self.dir / "broker.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1)
        fake.book_now["bench_offers"][1]["give"]["cash"] = 19  # a quote moved: a new state
        self.loop(desk, 2)
        rows = [json.loads(r) for r in (self.dir / "broker.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["same_reads_before"], 39)  # the identical reads are counted, not stored

    def test_a_run_is_summarised_once_it_is_quiet_with_every_trader(self):
        for policy in ("ours", "stall"):
            fake = FakeBroker(book_of([]))
            desk, log = self.desk(fake, policy)
            timeline = {1: [buyer("b5-1", 30)], 2: [buyer("b5-1", 31)], 3: [], 4: [seller("b5-2", 50)],
                        5: [seller("b5-2", 48)]}
            for t in range(1, 12):
                fake.tick, fake.book_now = t, book_of(timeline.get(t, []))
                self.loop(desk, 3)
            ends = [r for r in log.rows if r["event"] == "bench_run_end"]
            self.assertEqual(len(ends), 1, policy)  # not at tick 3, when the book was empty for a moment
            self.assertEqual(ends[0]["tick"], 9)    # three quiet ticks after b5-2 left at tick 6
            self.assertEqual(sorted(t["id"] for t in ends[0]["traders"]), ["b5-1", "b5-2"])
            self.assertEqual([q for _, q in ends[0]["traders"][0]["quotes"]], [30, 31])

    def test_a_restart_keeps_what_was_learned_about_expiries_today(self):
        fake = FakeBroker(book_of([buyer("b1-1", 30, expires_tick=3), seller("b1-2", 40, expires_tick=5)]))
        desk, _ = self.desk(fake)
        self.loop(desk, 3)
        fake.tick, fake.book_now = 2, book_of([seller("b1-2", 40, expires_tick=5)])  # b1-1 left before tick 3
        self.loop(desk, 3)
        self.assertEqual((desk.tracker.departed, desk.tracker.early), (1, 1))
        again, _ = self.desk(fake)  # a new process, same heartbeat file
        self.assertEqual((again.tracker.departed, again.tracker.early), (1, 1))

    def test_an_accepted_match_is_not_sent_twice_while_it_settles(self):
        fake = FakeBroker(book_of([seller("b1-1", 20), buyer("b1-2", 30)]), refuse=False)
        desk, _ = self.desk(fake, "stall")
        self.loop(desk, 4)
        fake.tick = 2  # still on the book one tick later (settling)
        self.loop(desk, 4)
        self.assertEqual(len(fake.calls), 1)

    def test_read_errors_keep_the_loop_alive_and_the_heartbeat_fresh(self):
        class Down(FakeBroker):
            def book(self):
                raise BazaarError("network", "down", 0)
        desk, log = self.desk(Down(book_of([])))
        waits = [desk.step() for _ in range(6)]
        self.assertEqual(waits[-1], brk.ERROR_SLEEP[-1])
        hb = json.loads((self.dir / "hb.json").read_text())
        self.assertEqual((hb["what"], hb["read_errors_in_a_row"], hb["mode"]), ("read_error", 6, "run"))

    def test_watch_mode_sends_nothing(self):
        fake = FakeBroker(book_of([seller("b1-1", 20), buyer("b1-2", 30)]), refuse=False)
        desk, log = self.desk(fake, send=False)
        self.loop(desk, 4)
        self.assertEqual(fake.calls, [])
        self.assertTrue(any(r["event"] == "WOULD" for r in log.rows))

    def test_read_only_broker_refuses_writes_before_the_network(self):
        b = brk.ReadOnlyBroker("http://127.0.0.1:9", FAKE_KEY)
        with self.assertRaises(BazaarError) as e:
            b.match("b1-1", "b1-2", 25)
        self.assertEqual(e.exception.code, "read_only")

    def test_the_key_never_reaches_the_logs_or_the_heartbeat(self):
        os.environ["BROKER_KEY"] = FAKE_KEY
        try:
            key = brk.load_broker_key(self.dir / "missing.env")
        finally:
            del os.environ["BROKER_KEY"]
        self.assertEqual(key, FAKE_KEY)
        fake = FakeBroker(book_of([seller("b1-1", 20), buyer("b1-2", 30, note=f"key {FAKE_KEY}")]))
        desk, log = self.desk(fake)
        self.loop(desk, 4)
        text = (self.dir / "broker.jsonl").read_text() + (self.dir / "hb.json").read_text() + json.dumps(log.rows)
        self.assertNotIn(FAKE_KEY, text)
        self.assertIn("book", (self.dir / "broker.jsonl").read_text())

    def test_key_file_is_read_when_the_environment_has_none(self):
        f = self.dir / "broker.env"
        f.write_text(f"# broker\nBROKER_KEY={FAKE_KEY}\n")
        old = os.environ.pop("BROKER_KEY", None)
        try:
            self.assertEqual(brk.load_broker_key(f), FAKE_KEY)
        finally:
            if old is not None:
                os.environ["BROKER_KEY"] = old


class Public(unittest.TestCase):
    def test_public_offers_are_crossed_as_the_starter_does(self):
        offers = [
            {"id": 11, "maker": "pA", "give": {"cash": 0, "assets": [{"kind": "card", "ref": "LAV-03", "id": 5}],
                                              "types": []}, "want": {"cash": 10, "assets": [], "types": []}},
            {"id": 12, "maker": "pB", "give": {"cash": 14, "assets": [], "types": []},
             "want": {"cash": 0, "assets": [], "types": ["card:LAV-03"]}},
            {"id": 13, "maker": "pA", "give": {"cash": 30, "assets": [], "types": []},
             "want": {"cash": 0, "assets": [], "types": ["card:LAV-03"]}},
        ]
        book = book_of([], offers)
        ok, bad, _ = brk.plan_book(book, 1, brk.BenchPolicy())
        self.assertEqual(ok, public_plan(book))
        self.assertEqual(ok, [(11, 12, 12)])  # the 30 P bid is the seller's own maker


class Estimates(unittest.TestCase):
    prior = brk.patience_prior()

    def test_limits_sit_beyond_the_quotes(self):
        for side, path in (("buy", [(1, 40), (2, 43), (3, 46)]), ("sell", [(1, 60), (2, 57), (3, 55)]),
                           ("buy", [(1, 40), (2, 40)]), ("sell", [(1, 60)])):
            e = brk.estimate(side, path, path[-1][0], self.prior)
            q = path[-1][1]
            self.assertTrue(e["limit"] >= q if side == "buy" else e["limit"] <= q, (side, path, e))
            self.assertTrue(0.0 <= e["leave"] <= 1.0)

    def test_a_shown_expiry_that_is_due_means_leaving(self):
        pol = brk.BenchPolicy()
        tr = {"side": "buy", "quotes": [(5, 40), (6, 41)], "expires": 7}
        self.assertEqual(pol.estimate(tr, 6)["leave"], 1.0)
        tr["expires"] = 15
        self.assertLess(pol.estimate(tr, 6)["leave"], 1.0)
        self.assertEqual(pol.estimate(tr, 6, known=True)["leave"], 0.0)

    def test_hazard_and_clearing_price(self):
        self.assertEqual(brk.hazard(self.prior, 1), 0.0)
        self.assertEqual(brk.hazard(self.prior, 16), 1.0)
        self.assertEqual(brk.hazard(self.prior, 40), 1.0)
        self.assertTrue(math.isclose(sum(self.prior), 1.0))
        self.assertEqual(brk.clearing_price([50, 40], [30, 45]), 42.5)

    def test_best_matching_is_exact(self):
        w = {(0, 0): 5, (0, 1): 4, (1, 0): 4}
        self.assertEqual(sorted(brk.best_matching(2, 2, lambda i, j: w.get((i, j)))), [(0, 1), (1, 0)])


class Offline(unittest.TestCase):
    def test_plan_mode_replays_a_recorded_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rec.jsonl"
            rows = [{"event": "book", "tick": t, "book": book_of([seller("b1-1", 30 - t), buyer("b1-2", 20 + t)])}
                    for t in range(1, 8)]
            f.write_text("\n".join(json.dumps(r) for r in rows) + "\n{not json\n")
            books = brk.read_books(f)
            self.assertEqual([t for t, _ in books], list(range(1, 8)))

    def test_open_venue_plan_body(self):
        import open_venue
        body = open_venue.BODY
        self.assertLessEqual(len(body["name"]), 40)
        self.assertEqual((body["fee_bps"], body["fee_per_card"], body["rules"]), (0, 0, {"mechanism": "board"}))
        self.assertEqual(set(body), {"name", "fee_bps", "fee_per_card", "rules", "description"})

    def test_open_venue_key_file_is_private_and_never_overwritten(self):
        import open_venue  # the helpers only: `run` itself is never executed here
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sub" / "broker.env"
            open_venue.write_key(f, FAKE_KEY)
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
            self.assertEqual(f.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(brk.load_broker_key(f), FAKE_KEY)
            with self.assertRaises(FileExistsError):
                open_venue.write_key(f, "bk_other")
            self.assertEqual(brk.load_broker_key(f), FAKE_KEY)

    def test_open_venue_save_key_falls_back_when_the_reserved_file_fails(self):
        import contextlib
        import io
        import open_venue
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "broker.env"
            ok = open_venue.reserve_key_file(f)
            self.assertEqual(open_venue.save_key(ok, f, FAKE_KEY), f)
            self.assertEqual(brk.load_broker_key(f), FAKE_KEY)
            g = Path(d) / "other" / "broker.env"
            open_venue.reserve_key_file(g)
            bad = os.open(str(g), os.O_RDONLY)  # writing through it fails like a full disk would
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                where = open_venue.save_key(bad, g, FAKE_KEY)
            self.assertNotEqual(where, g)
            self.assertEqual(where.parent, g.parent)
            self.assertEqual(where.stat().st_mode & 0o777, 0o600)
            self.assertEqual(brk.load_broker_key(where), FAKE_KEY)
            self.assertIn(str(g), err.getvalue())
            self.assertIn("RECOVERY", err.getvalue())
            self.assertNotIn(FAKE_KEY, err.getvalue())

    def test_open_venue_finds_the_venue_id(self):
        import open_venue
        self.assertEqual(open_venue.venue_id({"venue": "v05", "broker_key": "x"}), "v05")
        self.assertEqual(open_venue.venue_id({"venue": {"venue": "v06", "name": "n"}}), "v06")
        self.assertEqual(open_venue.venue_id({"id": "v07"}), "v07")


if __name__ == "__main__":
    unittest.main()
