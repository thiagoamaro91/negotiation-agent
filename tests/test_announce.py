"""tools/announce.py: the market read right (best sides with ids, v20's live offers from the feed, makers named from
the feed), the message variants, and that nothing posts without --yes. Offline: no key, no network.
Run: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import announce as an  # noqa: E402

_ids = iter(range(1000, 10**6))
REAL_TEAM_CLIENT = an.team_client
_GUARDS = []
_TMP = []


def setUpModule():
    """No test may use the machine's team key or the network (on the Mini both exist): team_client() answers None and
    any real HTTP request fails, unless a test patches them on purpose."""
    import unittest.mock as um

    def no_network(*a, **k):
        raise AssertionError("a test tried to reach the network")
    import tempfile
    _TMP.append(tempfile.TemporaryDirectory())
    for g in (um.patch.object(an, "team_client", lambda: None), um.patch.object(an.urllib.request, "urlopen", no_network),
              um.patch.object(an, "STATE", Path(_TMP[0].name) / "announce.json"),    # never the real state files
              um.patch.object(an, "SESSIONS", None)):   # no session memory shared between tests (tests set their own)
        g.start()
        _GUARDS.append(g)


def tearDownModule():
    for g in _GUARDS:
        g.stop()
    for d in _TMP:
        d.cleanup()


def ask(ref, cash, status="open", venue="rastro", maker=None, to=None, oid=None, asset=None):
    return {"id": oid or next(_ids), "maker": maker, "to": to, "venue": venue, "status": status,
            "give": {"cash": 0, "assets": [{"id": asset, "kind": "card", "ref": ref}], "types": []},
            "want": {"cash": cash, "assets": [], "types": []}}


def bid(ref, cash, status="open", venue="rastro", maker=None, to=None, oid=None):
    return {"id": oid or next(_ids), "maker": maker, "to": to, "venue": venue, "status": status,
            "give": {"cash": cash, "assets": [], "types": []},
            "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


def swap(give_ref, want_ref, **kw):
    o = ask(give_ref, 0, **kw)
    o["want"] = {"cash": 0, "assets": [], "types": [f"card:{want_ref}"]}
    return o


def listed(o, tick=100, actor=None):
    return {"type": "offer.listed", "tick": tick, "actor": actor or o.get("maker") or "",
            "payload": {"venue": o["venue"], "offer": dict(o, expires_tick=o.get("expires_tick", tick + 60))}}


BOOK = [ask("MAL-04", 8, oid=1), ask("MAL-04", 9), bid("MAL-04", 7, oid=2), bid("MAL-04", 6),
        ask("LAV-09", 120), bid("LAV-09", 99), bid("SAL-09", 68), bid("RET-01", 2),
        swap("LAT-02", "LAV-07"), ask("SAL-03", 5, status="cancelled")]
NAMES = {1: "t09", 2: "t16"}


class TestBook(unittest.TestCase):
    def test_only_plain_card_asks_bids_and_swaps_have_a_shape(self):
        self.assertEqual(an.shape(ask("LAT-07", 26)), ("ask", "LAT-07", 26))
        self.assertEqual(an.shape(bid("LAT-06", 14)), ("bid", "LAT-06", 14))
        self.assertEqual(an.shape(swap("SAL-03", "LAV-07")), ("swap", "SAL-03", "LAV-07"))
        pack = ask("x", 20)
        pack["give"]["assets"] = [{"id": 5, "kind": "pack", "ref": "sobre_barrio"}]
        plus_asset = ask("LAT-07", 26)
        plus_asset["want"]["assets"] = [123]                     # 26 P AND asset 123: not a cash-only ask
        two_types = bid("A", 5)
        two_types["want"]["types"] = ["card:A", "card:B"]
        both_cash = ask("A", 5)
        both_cash["give"]["cash"] = 3
        typed_give = bid("A", 5)
        typed_give["give"]["types"] = ["card:Z"]
        for o in (pack, plus_asset, two_types, both_cash, typed_give, {"give": None}, "x"):
            self.assertIsNone(an.shape(o), o)
            self.assertIsNone(an.describe(o) if isinstance(o, dict) else None)
            self.assertIsNone(an.take_order(o) if isinstance(o, dict) else None)
        t = an.build_text([], 0, exclude=(), venue_offers=[dict(pack, venue="v20", id=40),
                                                           dict(plus_asset, venue="v20", id=41)])
        self.assertNotIn("sobre_barrio", t)
        self.assertNotIn("offer 41", t)

    def test_market_sides_keep_ids_and_venues_and_skip_our_venue(self):
        bids, asks = an.market_sides(BOOK + [bid("MAL-04", 50, venue="v20"), ask("MAL-04", 7, venue="v07", oid=3)])
        self.assertEqual(bids["MAL-04"], (7, 2, "rastro"))       # the v20 bid of 50 is ours to cross, not to quote
        self.assertEqual(asks["MAL-04"], (7, 3, "v07"))

    def test_near_pairs_within_gap_closest_first_and_never_one_team_with_itself(self):
        self.assertEqual([p[0] for p in an.near_market_pairs(BOOK, NAMES)], ["MAL-04"])
        self.assertEqual(an.near_market_pairs(BOOK, {1: "t09", 2: "t09"}), [])
        self.assertEqual(an.near_market_pairs([ask("A", 10), bid("A", 6)], {}), [])  # 4 P apart > NEAR_GAP


class TestFeed(unittest.TestCase):
    def test_makers_come_from_the_feed(self):
        ev = [listed(ask("X", 5, maker="t15", oid=7)), listed(bid("Y", 3, maker="t06", oid=8)),
              {"type": "thread.message", "payload": {}}]
        self.assertEqual(an.offer_makers(ev), {7: "t15", 8: "t06"})

    def test_books_come_from_each_venue_and_an_unreadable_one_is_skipped(self):
        served = {"rastro": [ask("A", 5)], "v07": [bid("A", 4)], "v20": [ask("B", 9)]}

        def get(url):
            v = url.rsplit("/", 2)[-2]
            if v == "v99":
                raise OSError("down")
            return {"offers": served[v]}
        books = an.market_books(get, ["v07", "v99", "v20"])
        self.assertEqual(sorted(books), ["rastro", "v07", "v20"])
        self.assertEqual(books["v07"][0]["venue"], "v07")

    def test_describe_names_the_team_and_skips_ours_and_directed(self):
        self.assertEqual(an.describe(ask("LAT-07", 26, oid=9), {9: "t15"}), "t15 sells LAT-07 for 26 P (offer 9)")
        self.assertEqual(an.describe(bid("LAT-06", 14, maker="t06", oid=5)), "t06 buys LAT-06 for 14 P (offer 5)")
        self.assertEqual(an.describe(swap("SAL-03", "LAV-07", maker="t13", oid=4)),
                         "t13 swaps SAL-03 for any LAV-07 (offer 4), taken by accepting it")
        self.assertEqual(an.describe(ask("A", 5, maker="m8812", oid=3)), "a team sells A for 5 P (offer 3)")
        self.assertIsNone(an.describe(ask("A", 5, maker="t03")))
        self.assertIsNone(an.describe(ask("A", 5, maker="t13", to="t16")))


class TestText(unittest.TestCase):
    V20 = [ask("LAT-07", 26, venue="v20", oid=21), bid("MAL-08", 9, venue="v20", maker="t06", oid=22)]

    def test_book_variant_lists_v20_with_teams_and_the_order_that_takes_it(self):
        t = an.build_text([], 0, exclude=(), venue_offers=self.V20, names={21: "t15"})
        self.assertTrue(t.startswith("Live on La Celestina (v20) now: t15 sells LAT-07 for 26 P (offer 21); "
                                     "t06 buys MAL-08 for 9 P (offer 22)."))
        self.assertIn('{"venue": "v20", "give": {"cash": 26}, "want": {"cards": ["LAT-07"]}}', t)
        self.assertIn("POST /api/offers/21/accept", t)
        self.assertNotIn("http", t)                             # no web link: agents read the feed
        self.assertNotIn("Open bids on El Rastro", t)           # never send sellers to El Rastro

    def test_our_own_offers_never_make_a_pair(self):
        ours_ask = [ask("MAL-04", 7, oid=50, maker="t03"), bid("MAL-04", 7, oid=51)]
        self.assertEqual(an.near_market_pairs(ours_ask, {}), [])                 # maker shown as t03
        self.assertEqual(an.near_market_pairs([ask("MAL-04", 7, oid=52), bid("MAL-04", 7, oid=53)],
                                              {52: "t03", 53: "t16"}), [])        # named t03 by the feed
        both = [ask("MAL-04", 6, oid=54), ask("MAL-04", 7, oid=55), bid("MAL-04", 7, oid=56)]
        (p,) = an.near_market_pairs(both, {54: "t03", 55: "t09", 56: "t16"})   # ours skipped, the next ask pairs
        self.assertEqual(p[2][1], 55)

    def test_our_old_offers_are_known_by_their_pseudonym_or_our_offer_list(self):
        old = ask("MAL-04", 7, oid=100, maker="mOURS")            # ours, listed before the feed window
        recent = ask("LAT-01", 9, oid=101, maker="mOURS")         # ours, the feed names it
        theirs = bid("MAL-04", 7, oid=102, maker="mT16")
        books = {"rastro": [old, recent, theirs], "v07": [ask("SAL-01", 5, venue="v07", oid=103, maker="mOURS")]}
        names = an.learn_pseudonyms(books, {101: "t03", 102: "t16"})
        self.assertEqual(names[100], "t03")                       # same pseudonym on the same venue: ours
        self.assertNotIn(103, names)                              # pseudonyms are per venue: not linked
        self.assertEqual(an.near_market_pairs([old, theirs], names), [])
        self.assertEqual(len(an.near_market_pairs([old, theirs], {102: "t16"})), 1)  # without it, it would pair
        me = {"offers": [dict(old, maker="t03"), dict(bid("X", 1, oid=104), maker="t13", to="t03")]}
        self.assertEqual(an.our_offer_ids(me), {100})             # offers addressed to us are not ours

    def test_recorded_feed_keeps_only_listings_and_survives_bad_lines(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "feed.jsonl"
            f.write_text('{"type": "offer.listed", "actor": "t03", "payload": {"offer": {"id": 7, "maker": "t03"}}}\n'
                         'not json "offer.listed"\n{"type": "settlement", "payload": {}}\n')
            self.assertEqual(an.offer_makers(an.recorded_events(f)), {7: "t03"})
            self.assertEqual(an.recorded_events(Path(d) / "missing.jsonl"), [])

    def test_crossing_claims_and_orders_count_v20s_fee(self):
        book = [ask("MAL-04", 10, oid=60), bid("MAL-04", 11, oid=61)]
        names = {60: "t09", 61: "t16"}
        self.assertIn("they already cross on v20's terms", an.build_text(book, 1, names=names, exclude=()))
        t = an.build_text(book, 1, names=names, exclude=(), fee=(500, 1))       # 10 + 1 + 1 = 12 > 11
        self.assertIn("1 P apart on v20's terms", t)
        self.assertIn("5 % fee, 1 P per card", t)
        self.assertNotIn("0 % fee", t)
        order = an.take_order(ask("LAT-07", 26, oid=62), fee=(500, 1))           # 26 + ceil(1.3) + 1 = 29
        self.assertIn('"give": {"cash": 29}', order)
        order = an.take_order(bid("LAT-07", 26, oid=63), fee=(500, 1))           # 24 + 2 + 1 = 27 > 26; 23 + 2 + 1 = 26
        self.assertIn('"want": {"cash": 23}', order)
        self.assertIsNone(an.take_order(bid("LAT-07", 1, oid=64), fee=(0, 1)))  # no whole price leaves room

    def test_a_swap_is_never_promised_to_the_broker(self):
        t = an.build_text([], 0, venue_offers=[swap("LAT-07", "LAT-01", venue="v20", maker="t15", oid=31)])
        self.assertIn("t15 swaps LAT-07 for any LAT-01 (offer 31), taken by accepting it", t)
        self.assertIn("POST /api/offers/31/accept", t)
        self.assertNotIn("broker crosses", t)

    def test_pairs_variant_names_both_sides_and_falls_back_to_the_book(self):
        t = an.build_text(BOOK, 1, names=NAMES)
        self.assertTrue(t.startswith("Buyer and seller close, nobody crossing them"))
        self.assertIn("MAL-04: t09 asks 8 P on El Rastro (offer 1), t16 bids 7 P on El Rastro (offer 2), "
                      "1 P apart on v20's terms", t)
        self.assertNotIn("matches them at the midpoint the tick they meet", t)   # no promise for a gap
        none = [ask("LAT-06", 30), bid("LAT-06", 6)]
        self.assertEqual(an.build_text(none, 1, venue_offers=self.V20), an.build_text(none, 0, venue_offers=self.V20))

    def test_excluded_cards_never_appear_in_any_variant(self):
        book = BOOK + [ask("LAV-10", 70), bid("LAV-10", 69), ask("LAT-09", 60), bid("LAT-09", 60)]
        v20 = [ask("LAV-09", 100, venue="v20"), bid("LAT-09", 40, venue="v20")]
        for v in range(3):
            t = an.build_text(book, v, venue_offers=v20)       # default: the cards we lack
            for ref in ("LAV-09", "LAV-10", "LAT-09", "SAL-09"):
                self.assertNotIn(ref, t)
            self.assertNotIn("LAV-04", an.build_text([bid("LAV-04", 50), ask("LAV-04", 50)], v, exclude=("LAV-04",)))
        self.assertTrue({"LAV-09", "LAV-10", "LAT-09"} <= set(an.MISSING))

    def test_missing_card_variant_is_bilingual_and_carries_the_book(self):
        t = an.build_text([], 2, venue_offers=self.V20, names={21: "t15"})
        self.assertIn("Missing one card", t)
        self.assertIn("¿Te falta una carta?", t)
        self.assertIn("t15 sells LAT-07", t)

    def test_variants_rotate_and_fit_the_limit_and_link_is_optional(self):
        self.assertEqual(an.build_text(BOOK, 3), an.build_text(BOOK, 0))
        big = [bid(f"LAV-{i:02d}", 50 + i) for i in range(400)] + [ask(f"LAV-{i:02d}", 50 + i) for i in range(400)]
        v20 = [ask(f"MAL-{i:02d}", 9, venue="v20") for i in range(50)]
        for v in range(3):
            self.assertLessEqual(len(an.build_text(big, v, venue_offers=v20)), an.MAX_CHARS)
            self.assertNotIn("http", an.build_text(BOOK, v))
            self.assertEqual(len(an.build_text(BOOK, v, link="x" * 2000)), an.MAX_CHARS)
        self.assertIn("Selling a spare", an.build_text([], 0))  # nothing concrete: the plain pitch


class TestAnnouncer(unittest.TestCase):
    def test_the_first_read_learns_the_book_then_only_new_eligible_offers_are_fresh(self):
        a = an.Announcer(4, 1800, on_event=True, eligible=lambda o: o.get("maker") != "t03")
        self.assertEqual(a.fresh([ask("A", 5, venue="v20", oid=1)]), [])
        new = [ask("A", 5, venue="v20", oid=1), ask("B", 6, venue="v20", oid=2, maker="t15"),
               ask("C", 7, venue="v20", oid=3, maker="t03")]
        self.assertEqual([o["id"] for o in a.fresh(new)], [2])
        self.assertEqual([o["id"] for o in a.fresh(new)], [2])   # still queued (not posted yet), never twice
        a.mark_posted(0, 100, "event", [2])
        self.assertEqual(a.fresh(new), [])                       # posted: the queue is empty, and 2 is not new

    def test_an_offer_that_lands_during_the_cooldown_is_posted_when_it_ends(self):
        a = an.Announcer(4, 1800, on_event=True, min_gap_s=600)
        a.fresh([])
        a.mark_posted(0, 100, "slot")
        q = a.fresh([ask("A", 5, venue="v20", oid=7)])
        self.assertIsNone(a.due(300, q))                         # inside the cooldown: waits, but keeps it
        q = a.fresh([ask("A", 5, venue="v20", oid=7)])
        self.assertEqual(a.due(650, q), "event")                 # the cooldown is over: posted
        self.assertEqual([o["id"] for o in q], [7])
        b = an.Announcer(4, 1800, on_event=True, min_gap_s=600)
        b.fresh([])
        b.mark_posted(0, 100, "slot")
        b.fresh([ask("A", 5, venue="v20", oid=8)])
        self.assertEqual(b.fresh([]), [])                        # it left the book before the cooldown ended

    def test_a_scheduled_slot_never_comes_closer_than_the_min_gap(self):
        a = an.Announcer(4, 600, on_event=True, min_gap_s=600)
        a.mark_posted(0, 100, "slot")
        a.mark_posted(500, 110, "event")                         # an event post at 500 s ...
        self.assertIsNone(a.due(700, []))                       # ... so the 600 s slot waits for 500 + 600
        self.assertEqual(a.due(1100, []), "slot")

    def test_only_the_offers_a_post_advertised_leave_the_queue(self):
        a = an.Announcer(4, 1800, on_event=True)
        a.fresh([])
        q = a.fresh([ask("A", 5, venue="v20", oid=1), ask("B", 6, venue="v20", oid=2)])
        self.assertEqual([o["id"] for o in q], [1, 2])
        a.mark_posted(0, 100, "event", [1])                      # the text named only offer 1
        self.assertEqual([o["id"] for o in a.queue], [2])

    def test_slots_events_gap_and_cap(self):
        a = an.Announcer(3, 1800, on_event=True, min_gap_s=600)
        self.assertEqual(a.due(0, []), "slot")                    # the first slot is at once
        a.mark_posted(0, 100, "slot")
        self.assertIsNone(a.due(300, []))
        self.assertIsNone(a.due(300, [{"id": 9}]))               # an event inside the gap waits
        self.assertEqual(a.due(700, [{"id": 9}]), "event")        # ... and goes once the gap has passed
        a.mark_posted(700, 120, "event", [9])
        self.assertIsNone(a.due(1800, []))                       # the next slot counts from the event post
        self.assertEqual(a.due(2500, []), "slot")
        a.mark_posted(2500, 150, "slot")
        self.assertIsNone(a.due(10**6, [{"id": 10}]))            # count reached
        off = an.Announcer(3, 1800)                              # without on_event, offers never trigger
        off.mark_posted(0, 100, "slot")
        self.assertIsNone(off.due(700, [{"id": 9}]))

    def test_responses_count_the_window_after_and_before_from_the_feed(self):
        def lst(t, maker, venue="v20"):
            return {"type": "offer.listed", "tick": t, "actor": maker,
                    "payload": {"offer": {"id": t, "maker": maker, "venue": venue}}}
        ev = [lst(95, "t15"), lst(105, "t08"), lst(110, "t08"), lst(112, "t03"), lst(108, "t04", "v07"),
              {"type": "settlement", "tick": 111, "payload": {"venue": "v20"}},
              {"type": "settlement", "tick": 111, "payload": {"venue": "v07"}}, lst(125, "t13")]
        a = an.Announcer(2, 1800, measure_ticks=20)
        a.mark_posted(0, 100, "event", [7])
        self.assertEqual(a.responses(119, ev), [])               # the window is still open
        (r,) = a.responses(120, ev)
        self.assertEqual((r["listed_after"], r["teams_after"], r["trades_after"]), (2, ["t08"], 1))
        self.assertEqual((r["listed_before"], r["teams_before"], r["trades_before"]), (1, ["t15"], 0))
        self.assertEqual((r["why"], r["fresh"], r["post"]), ("event", [7], 1))
        self.assertEqual(a.pending, [])


class TestExactOrder(unittest.TestCase):
    """f9's design (Thiago's data review): an event post names the exact order, until when it stands and who holds
    the other side elsewhere; a post is judged by whether the order left v20's book and v20 settled."""

    def test_fillers_are_the_other_side_of_that_card_elsewhere_best_first_never_the_maker_or_us(self):
        order = ask("LAT-07", 26, venue="v20", maker="t15", oid=70)
        market = [bid("LAT-07", 20, venue="v01", oid=71), bid("LAT-07", 24, oid=72), bid("LAT-07", 30, oid=73),
                  bid("LAT-08", 50, oid=74), bid("LAT-07", 99, venue="v20", oid=75), ask("LAT-07", 5, oid=76)]
        names = {71: "t12", 72: "t08", 73: "t03", 74: "t09"}
        self.assertEqual(an.fillers(order, market, names), [("t08", 24, "rastro"), ("t12", 20, "v01")])
        self.assertEqual(an.fillers(order, market + [bid("LAT-07", 40, maker="t15", oid=77)], names),
                         [("t08", 24, "rastro"), ("t12", 20, "v01")])          # the maker's own bid is not a filler
        bid_order = bid("MAL-08", 9, venue="v20", maker="t06", oid=78)
        asks = [ask("MAL-08", 12, oid=79), ask("MAL-08", 10, venue="v07", oid=80)]
        self.assertEqual(an.fillers(bid_order, asks, {79: "t09", 80: "t04"}), [("t04", 10, "v07"), ("t09", 12, "rastro")])
        self.assertEqual(an.fillers(swap("A", "B", venue="v20"), market), [])

    def test_the_event_post_details_only_the_order_it_leads_with(self):
        order = dict(ask("LAT-07", 26, venue="v20", maker="t15", oid=70), expires_tick=1240)
        other = ask("MAL-01", 6, venue="v20", maker="t13", oid=81)
        market = [bid("LAT-07", 24, oid=72)]
        t = an.build_text(market, 0, exclude=(), venue_offers=[order, other], names={72: "t08"}, lead=[70])
        self.assertIn("t15 sells LAT-07 for 26 P (offer 70) [open until tick 1240; open bids for it elsewhere: "
                      "t08 24 P on El Rastro]", t)
        self.assertIn("; t13 sells MAL-01 for 6 P (offer 81). ", t)             # no detail for the others
        self.assertNotIn("open until tick", an.build_text(market, 0, exclude=(), venue_offers=[order], names={72: "t08"}))

    def test_a_response_says_whether_the_announced_order_left_v20(self):
        a = an.Announcer(2, 1800, measure_ticks=20)
        a.mark_posted(0, 100, "event", [70, 71])
        (r,) = a.responses(120, [], v20_ids={71})
        self.assertEqual(r["fresh_left_book"], [70])
        b = an.Announcer(2, 1800, measure_ticks=20)
        b.mark_posted(0, 100, "slot")
        self.assertNotIn("fresh_left_book", b.responses(120, [])[0])


class TestVariantTwoOnEvents(unittest.TestCase):
    def test_on_event_with_variant_2_never_renders_near_pairs(self):
        """f9 runs --on-event --variant 2 tonight: every post, event ones included, is pitch + v20's book."""
        import tempfile
        import unittest.mock as um
        state = {"tick": 100, "now": 0.0, "v20": []}
        posts, logged = [], []
        near = [ask("MAL-04", 8, oid=90), bid("MAL-04", 7, oid=91)]               # a near pair on El Rastro

        def get_json(url):
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
            if url.endswith("/api/venues/v20/offers"):
                return {"offers": state["v20"]}
            if url.endswith("/api/venues/rastro/offers"):
                return {"offers": near}
            if "/api/feed" in url:
                return {"events": [{"type": "offer.listed", "tick": 100, "actor": t,
                                    "payload": {"offer": {"id": i, "maker": t, "venue": "rastro"}}}
                                   for i, t in ((90, "t09"), (91, "t16"))]}
            if url.endswith("/api/venues"):
                return {"venues": [{"venue": "v20", "status": "open"}]}
            return {"offers": []}

        def sleep(_):
            state["now"] += an.POLL_S
            state["tick"] += 1
            if state["tick"] == 103:
                state["v20"] = [dict(ask("MAL-04", 9, venue="v20", maker="t15", oid=5), expires_tick=160)]
            if state["tick"] > 2000:
                raise AssertionError("the run loop did not end")

        class Log:
            def __init__(self, *_): pass
            def start(self, **k): pass
            def event(self, e, **d): logged.append((e, d))
            def end(self): pass

        with tempfile.TemporaryDirectory() as d, \
                um.patch.object(an, "get_json", get_json), um.patch.object(an.time, "sleep", sleep), \
                um.patch.object(an.time, "time", lambda: state["now"]), um.patch.object(an, "STATE", Path(d) / "s"), \
                um.patch.object(an, "post_announce", lambda text, key: posts.append(text) or {"ok": True}), \
                um.patch("runlog.RunLog", Log), um.patch("broker.load_broker_key", lambda *_: "bk_fake"):
            an.main(["run", "--yes", "--on-event", "--variant", "2", "--count", "2", "--every-min", "30",
                     "--min-gap-min", "0", "--exclude", ""])
        self.assertEqual([d["why"] for e, d in logged if e == "announce"], ["slot", "event"])
        self.assertEqual({d["variant"] for e, d in logged if e == "announce"}, {2})
        for t in posts:
            self.assertNotIn("Buyer and seller", t)                              # no near-pair block, ever
            self.assertNotIn("MAL-04: t09 asks", t)
        self.assertIn("t15 sells MAL-04 for 9 P (offer 5) [open until tick 160; open bids for it elsewhere: "
                      "t16 7 P on El Rastro]", posts[1])

    def test_unnamed_fillers_are_never_named(self):
        order = ask("LAT-07", 26, venue="v20", maker="t15", oid=70)
        market = [bid("LAT-07", 24, oid=72, maker="m1234abcd"), bid("LAT-07", 20, oid=73)]
        self.assertEqual(an.fillers(order, market, {73: "t12"}), [("t12", 20, "rastro")])  # 72 could be us


class TestSilence(unittest.TestCase):
    SCHED = {"upcoming": [{"at_hours": 11.0, "action": "bench"}, {"at_hours": 11.65, "action": "duels"},
                          {"at_hours": 13.0, "action": "bench"}, {"at_hours": 14.077, "action": "day_closes"},
                          {"at_hours": 14.65, "action": "bench"}]}

    def test_market_test_windows_come_from_the_schedule_and_stop_at_the_day_close(self):
        clock = {"t_hours": 10.5, "tick_seconds": 30.0, "paused": False}
        w = an.quiet_windows(self.SCHED, clock, 1000.0, horizon_h=6)
        start = 1000.0 + 0.5 * 120 * 30                           # 0.5 game hours = 60 ticks of 30 s
        self.assertEqual(w[0], (start - an.QUIET_BEFORE_S, start + an.QUIET_AFTER_S))  # whole seconds here
        self.assertEqual(len(w), 2)                              # 14.65 is after the day closes: not placed
        self.assertEqual(an.quiet_windows(self.SCHED, dict(clock, paused=True), 1000.0), w)  # earliest start
        self.assertEqual(an.quiet_windows(self.SCHED, {}, 1000.0), [])
        self.assertEqual(an.quiet_until(w, start), start + an.QUIET_AFTER_S)
        self.assertIsNone(an.quiet_until(w, start + an.QUIET_AFTER_S))

    def test_manual_windows_parse(self):
        day = time.strptime("2026-10-03", "%Y-%m-%d")
        (a, b), = an.parse_quiet("21:53-22:05", day)
        self.assertEqual(b - a, 12 * 60)
        self.assertEqual(an.parse_quiet("", day), [])

    def test_the_run_loop_makes_no_api_call_inside_a_market_test_silence(self):
        import tempfile
        import unittest.mock as um
        state = {"now": 0.0, "tick": 100}
        calls, posts = [], []
        bench_in_s = 900.0                                     # a Market Test 15 minutes in

        def get_json(url):
            calls.append((state["now"], url))
            if url.endswith("/api/schedule"):
                return {"upcoming": [{"at_hours": 10.0 + bench_in_s / 3600, "action": "bench"}]}
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
            return {"offers": [], "events": [], "venues": []}

        def sleep(sec):
            state["now"] += sec
            state["tick"] = 100 + int(state["now"] // 30)
            if state["now"] > 10 ** 5:
                raise AssertionError("the run loop did not end")

        class Log:
            def __init__(self, *_): pass
            def start(self, **k): pass
            def event(self, e, **d): pass
            def end(self): pass

        with tempfile.TemporaryDirectory() as d, \
                um.patch.object(an, "get_json", get_json), um.patch.object(an.time, "sleep", sleep), \
                um.patch.object(an.time, "time", lambda: state["now"]), um.patch.object(an, "STATE", Path(d) / "s"), \
                um.patch.object(an, "post_announce", lambda text, key: posts.append(state["now"]) or {"ok": True}), \
                um.patch("runlog.RunLog", Log), um.patch("broker.load_broker_key", lambda *_: "bk_fake"):
            an.main(["run", "--yes", "--count", "3", "--every-min", "10", "--min-gap-min", "1", "--exclude", ""])
        lo, hi = bench_in_s - an.QUIET_BEFORE_S, bench_in_s + an.QUIET_AFTER_S
        self.assertEqual([t for t, _ in calls if lo <= t < hi], [])     # not one request inside the silence
        self.assertEqual([t for t in posts if lo <= t < hi], [])
        self.assertEqual(len(posts), 3)


def run_loop(argv, get_json, state, posts, logged=None, slow=None):
    """Drive an.main(run) offline: a fake clock that only moves when the loop sleeps or a slow request runs."""
    import tempfile
    import unittest.mock as um

    def sleep(sec):
        state["now"] += sec
        state["tick"] = 100 + int(state["now"] // 30)
        if state["now"] > 10 ** 5:
            raise AssertionError("the run loop did not end")

    def get(url):
        state.setdefault("calls", []).append((state["now"], url))
        if slow:
            state["now"] += slow(url, state["now"])
        return get_json(url)

    class Log:
        def __init__(self, *_): pass
        def start(self, **k): pass
        def event(self, e, **d): (logged if logged is not None else []).append((e, d))
        def end(self): pass

    with tempfile.TemporaryDirectory() as d, \
            um.patch.object(an, "get_json", get), um.patch.object(an.time, "sleep", sleep), \
            um.patch.object(an.time, "time", lambda: state["now"]), um.patch.object(an, "STATE", Path(d) / "s"), \
            um.patch.object(an, "recorded_events", lambda *a, **k: []), \
            um.patch.object(an, "post_announce", lambda text, key: posts.append((state["now"], text)) or {"ok": True}), \
            um.patch("runlog.RunLog", Log), um.patch("broker.load_broker_key", lambda *_: "bk_fake"):
        an.main(argv)


def market(state, bench_at_s=None, v20=None, fail=()):
    """A fake API: a Market Test bench_at_s seconds after t=0 (game hour 10.0), v20's book from state."""
    def get_json(url):
        for f in fail:
            if f(url, state):
                raise TimeoutError("down")
        if url.endswith("/api/schedule"):
            up = [{"at_hours": 10.0 + bench_at_s / 3600, "action": "bench"}] if bench_at_s is not None else []
            return {"upcoming": up}
        if url.endswith("/api/clock"):
            return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
        if url.endswith("/api/venues/v20/offers"):
            return {"offers": state.get("v20", [])}
        if "/api/feed" in url:
            return {"events": state.get("events", [])}
        if url.endswith("/api/venues"):
            return {"venues": [{"venue": "v20", "status": "open"}]}
        return {"offers": []}
    return get_json


class TestSilenceGate(unittest.TestCase):
    """Codex BLOCKERs on #45: silence checked right before every request and the post; unknown status = no post."""

    def test_a_slow_read_that_crosses_into_the_silence_never_posts_inside_it(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        lo, hi = 900 - an.QUIET_BEFORE_S, 900 + an.QUIET_AFTER_S          # silence 780-1500
        slow = lambda url, now: 25.0 if "/api/feed" in url and 740 <= now < 780 else 0.0   # 15-25 s timeouts
        run_loop(["run", "--yes", "--count", "3", "--every-min", str(760 / 60), "--min-gap-min", "1",
                  "--exclude", ""], market(state, bench_at_s=900), state, posts, slow=slow)
        self.assertEqual([t for t, _ in posts if lo <= t < hi], [])
        self.assertEqual([u for t, u in state["calls"] if lo <= t < hi], [])     # not one request inside it
        self.assertEqual(len(posts), 3)

    def test_the_last_read_of_a_post_crossing_into_the_silence_stops_the_post(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        n = {"v20": 0}

        def slow(url, now):                      # the poll's v20 read is quick; the composing one takes 25 s
            if url.endswith("/api/venues/v20/offers") and 760 <= now < 780:   # the 760 s slot: poll, then compose
                n["v20"] += 1
                return 25.0 if n["v20"] == 2 else 0.0
            return 0.0
        run_loop(["run", "--yes", "--count", "3", "--every-min", str(760 / 60), "--min-gap-min", "1",
                  "--exclude", ""], market(state, bench_at_s=900), state, posts, slow=slow)
        self.assertEqual([t for t, _ in posts if 780 <= t < 1500], [])
        self.assertEqual(len(posts), 3)

    def test_no_post_while_the_market_test_status_is_unknown(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        down = lambda url, st: url.endswith("/api/schedule") and st["now"] < 500
        run_loop(["run", "--yes", "--count", "1", "--every-min", "1", "--exclude", ""],
                 market(state, fail=[down]), state, posts)
        self.assertEqual(len(posts), 1)
        self.assertGreaterEqual(posts[0][0], 500)                       # only once the schedule could be read
        self.assertEqual([u for t, u in state["calls"] if t < 500 and "/api/venues" in u], [])  # nor any polling

    def test_a_status_that_goes_stale_while_composing_defers_the_post(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        down = lambda url, st: url.endswith("/api/schedule") and 230 <= st["now"] < 400   # no fresh status 230-400
        slow = lambda url, now: 60.0 if "/api/feed" in url and 260 <= now < 280 else 0.0   # composing takes 60 s
        run_loop(["run", "--yes", "--count", "2", "--every-min", str(260 / 60), "--min-gap-min", "1",
                  "--exclude", ""], market(state, fail=[down]), state, posts, slow=slow)
        self.assertEqual([t for t, _ in posts if 300 < t < 400], [])    # the status read at 0 is stale by then
        self.assertEqual(len(posts), 2)

    def test_a_restart_in_the_middle_of_a_market_test_waits_for_its_end(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        state["events"] = [{"type": "bench.started", "tick": 90, "payload": {"start_tick": 90, "ticks": 16}}]
        run_loop(["run", "--yes", "--count", "1", "--every-min", "1", "--exclude", ""],
                 market(state), state, posts)                         # the schedule no longer lists it
        started = -10 * 30                                             # 10 ticks of 30 s before t = 0
        self.assertGreaterEqual(posts[0][0], started + an.QUIET_AFTER_S)

    def test_a_feed_failure_during_an_active_market_test_never_posts(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        state["events"] = [{"type": "bench.started", "tick": 90, "payload": {"start_tick": 90, "ticks": 16}}]
        down = lambda url, st: "/api/feed" in url and st["now"] < 400        # the feed is down while it runs
        run_loop(["run", "--yes", "--count", "1", "--every-min", "1", "--exclude", ""],
                 market(state, fail=[down]), state, posts)
        self.assertEqual(len(posts), 1)
        self.assertGreaterEqual(posts[0][0], 400)                         # never while the status was unknown
        self.assertEqual([u for t, u in state["calls"] if t < 400 and "/api/venues" in u], [])

    def test_game_hours_are_wall_hours_at_any_tick_length(self):
        sched = {"upcoming": [{"at_hours": 11.0, "action": "bench"}]}
        for tick_s, end in ((15.0, 3600 + 600), (30.0, 3600 + 600), (60.0, 3600 + 16 * 60 + an.QUIET_TAIL_S)):
            (w,) = an.quiet_windows(sched, {"t_hours": 10.0, "tick_seconds": tick_s}, 0.0)
            self.assertEqual(w, (3600 - an.QUIET_BEFORE_S, end), tick_s)   # same start; a slow session lasts longer

    def test_an_active_session_is_silent_until_its_last_tick_at_the_clocks_pace(self):
        ev = [{"type": "bench.started", "tick": 100, "payload": {"start_tick": 100, "ticks": 16}}]
        (w,) = an.active_windows(ev, {"tick": 105, "tick_seconds": 60.0}, 1000.0)   # 11 ticks of 60 s still to run
        self.assertEqual(w[1], 1000 + 11 * 60 + an.QUIET_TAIL_S)
        (w,) = an.active_windows(ev, {"tick": 105, "tick_seconds": 15.0}, 1000.0)   # fast ticks: the 10-minute rule
        self.assertEqual(w[1], 1000 - 5 * 15 + an.QUIET_AFTER_S)
        self.assertEqual(an.active_windows(ev, {"tick": 140, "tick_seconds": 30.0}, 1000.0), [])  # long over

    def test_windows_are_placed_from_the_clock_read_not_after_a_slow_feed(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        g = an.Gate(clock=lambda: state["now"])

        def get(url):
            if url.endswith("/api/schedule"):
                return {"upcoming": [{"at_hours": 10.25, "action": "bench"}]}   # 900 s after the clock read
            if url.endswith("/api/clock"):
                return {"tick": 100, "t_hours": 10.0, "tick_seconds": 30.0}
            state["now"] += 200                                                  # the feed takes 200 s
            return {"events": []}
        self.assertTrue(g.refresh(get))
        self.assertEqual(g.windows, [(900 - an.QUIET_BEFORE_S, 900 + an.QUIET_AFTER_S)])
        self.assertEqual(g.status_at, 0.0)


class TestGateMemory(unittest.TestCase):
    """Codex at ab39a6a: the silence must not end early on a tick pause or when bench.started scrolls out of the feed;
    the schedule's windows are installed before the feed read; any bad shape leaves the status unknown."""

    @staticmethod
    def api(state, schedule=None, feed=None, calls=None):
        def get(url):
            (calls if calls is not None else []).append(url)
            if url.endswith("/api/schedule"):
                return schedule(state) if callable(schedule) else (schedule or {"upcoming": []})
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": state["t"], "tick_seconds": 30.0, "paused": state.get("paused")}
            return feed(state) if callable(feed) else (feed or {"events": []})
        return get

    def test_a_paused_clock_keeps_a_running_session_silent(self):
        state = {"now": 0.0, "tick": 105, "t": 10.0, "paused": True}
        g = an.Gate(clock=lambda: state["now"])
        feed = {"events": [{"type": "bench.started", "tick": 100, "payload": {"start_tick": 100, "ticks": 16}}]}
        self.assertTrue(g.refresh(self.api(state, feed=feed)))
        self.assertIsNotNone(g.quiet_end())
        state["now"] = 2000.0                                    # 33 minutes later, the clock still at tick 105
        g.expire()
        self.assertFalse(g.refresh(self.api(state, feed=feed)))  # inside the silence: no read at all
        self.assertIsNotNone(g.quiet_end())                      # the old window was not cut short ...
        g.windows = [w for w in g.windows if w[1] > 2000.0]      # ... and a fresh placement keeps it running:
        self.assertEqual(an.active_windows([{"type": "bench.started", "payload": {"start_tick": 100, "ticks": 16}}],
                                           {"tick": 105, "tick_seconds": 30.0}, 2000.0)[0][1], 2000 + 11 * 30 + an.QUIET_TAIL_S)

    def test_a_session_whose_bench_started_scrolled_out_is_still_known(self):
        state = {"now": 0.0, "tick": 100, "t": 10.0}
        g = an.Gate(clock=lambda: state["now"])
        with_start = {"events": [{"type": "bench.started", "tick": 98, "payload": {"start_tick": 98, "ticks": 16}}]}
        self.assertTrue(g.refresh(self.api(state, feed=with_start)))    # status known: a session is running
        self.assertIsNotNone(g.quiet_end())                              # silent at once
        state["now"], state["tick"] = 400.0, 100                         # paused; the event has scrolled out
        g.windows = []                                                   # even with every window forgotten
        g.expire()
        g.refresh(self.api(state, feed={"events": []}))
        self.assertIsNotNone(g.quiet_end())                              # the remembered session places it again

    def test_a_fired_session_is_placed_from_its_start_event_never_from_elapsed_hours(self):
        """Codex BLOCK 2 on #64: 60 s ticks, then 15 s ticks and a pause; elapsed hours would put the start at tick 70
        for a session that started at 100. Without a start event the status is unknown; with one, its tick is used."""
        state = {"now": 0.0, "tick": 90, "t": 10.0}
        g = an.Gate(clock=lambda: state["now"])
        sched = lambda st: {"upcoming": [{"at_hours": 10.5, "action": "bench", "params": {"ticks": 16}}]} \
            if st["t"] < 10.5 else {"upcoming": []}
        self.assertTrue(g.refresh(self.api(state, schedule=sched)))
        state.update(now=2400.0, tick=110, t=10.5 + 600 / 3600)       # fired; the pace changed on the way
        g.windows, g.status_at = [], None
        self.assertFalse(g.refresh(self.api(state, schedule=sched)))   # nothing says when it started: unknown
        self.assertEqual(g.sessions, {})
        fired = {"events": [{"type": "schedule.fired", "tick": 100, "t": 10.5, "payload": {"action": "bench"}}]}
        self.assertTrue(g.refresh(self.api(state, schedule=sched, feed=fired)))
        self.assertEqual(g.sessions, {100: 16})
        self.assertIsNotNone(g.quiet_end())

    def test_a_longer_report_of_the_same_session_wins(self):
        """Codex BLOCK 1 on #64: scheduled as 16 ticks, bench.started says 32: the window runs 32 ticks."""
        state = {"now": 0.0, "tick": 100, "t": 10.0}
        g = an.Gate(clock=lambda: state["now"])
        feed = {"events": [{"type": "schedule.fired", "tick": 100, "t": 10.0, "payload": {"action": "bench"}},
                           {"type": "bench.started", "tick": 100, "t": 10.0, "payload": {"start_tick": 100, "ticks": 32}}]}
        self.assertTrue(g.refresh(self.api(state, feed=feed)))
        self.assertEqual(g.sessions, {100: 32})
        g._add(100, 16)
        self.assertEqual(g.sessions, {100: 32})

    def test_a_malformed_feed_or_session_leaves_the_status_unknown(self):
        """Codex BLOCK 3 on #64: "unavailable" is not an empty feed; a start tick must be a whole number."""
        for feed in ({"events": "unavailable"}, ["x"], {"events": [{"type": "x"}]},
                     {"events": [{"type": "bench.started", "tick": 100, "payload": {"start_tick": "100"}}]},
                     {"events": [{"type": "bench.started", "tick": 100, "payload": {"start_tick": 100, "ticks": "16"}}]},
                     {"events": [{"type": "bench.started", "tick": 100, "payload": "x"}]}):
            state = {"now": 0.0, "tick": 105, "t": 10.0}
            g = an.Gate(clock=lambda: state["now"])
            self.assertFalse(g.refresh(self.api(state, feed=feed)), feed)
            self.assertFalse(g.known())

    def test_a_restart_inside_a_test_whose_start_left_the_window_is_unknown_unless_saved(self):
        """Codex MAJOR on #64: the session began at 100; at 105 the API's full window starts at 103 and the recorded
        feed is not there. Without saved sessions: unknown (no post). With the file a previous run wrote: silent."""
        window = {"events": [{"type": "offer.listed", "tick": 103 + i // 500, "payload": {}}
                             for i in range(an.FEED_LIMIT)]}
        state = {"now": 0.0, "tick": 105, "t": 10.0}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sessions.json"
            g = an.Gate(clock=lambda: state["now"], state_path=path)
            self.assertFalse(g.refresh(self.api(state, feed=window)))           # no file, window too short
            self.assertIsNone(g.quiet_end())                                    # unknown: the loop never posts
            self.assertFalse(g.known())
            state["tick"] = 101
            first = an.Gate(clock=lambda: state["now"], state_path=path)
            started = {"events": [{"type": "bench.started", "tick": 100, "t": 10.0,
                                   "payload": {"start_tick": 100, "ticks": 16}}]}
            self.assertTrue(first.refresh(self.api(state, feed=started)))      # the run before the restart saw it
            state["tick"] = 105
            again = an.Gate(clock=lambda: state["now"], state_path=path)       # the restart
            again.refresh(self.api(state, feed=window))
            self.assertEqual(again.sessions, {100: 16})
            self.assertIsNotNone(again.quiet_end())                             # silent until the session's end

    def test_saved_coverage_lets_a_restart_after_the_test_post_again(self):
        window = {"events": [{"type": "offer.listed", "tick": 203 + i // 500, "payload": {}}
                             for i in range(an.FEED_LIMIT)]}
        state = {"now": 0.0, "tick": 202, "t": 10.0}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sessions.json"
            self.assertTrue(an.Gate(clock=lambda: 0.0, state_path=path).refresh(self.api(state)))   # covered to 202
            state["tick"] = 205
            self.assertTrue(an.Gate(clock=lambda: 0.0, state_path=path).refresh(self.api(state, feed=window)))
            state["tick"] = 240                                             # the saved coverage no longer reaches
            self.assertFalse(an.Gate(clock=lambda: 0.0, state_path=path).refresh(
                self.api(state, feed={"events": [{"type": "x", "tick": 239, "payload": {}}] * an.FEED_LIMIT})))

    def test_the_recorded_feed_never_proves_coverage(self):
        """Round 2, finding 2: the recorder saved to tick 90, missed the test that began at 100, resumed at 103. Its
        endpoints (0, 104) prove nothing; with the API window starting at 103 the status stays unknown."""
        window = {"events": [{"type": "offer.listed", "tick": 103, "payload": {}} for _ in range(an.FEED_LIMIT)]}
        recorded = [{"type": "offer.listed", "tick": t, "payload": {}} for t in (0, 50, 90, 103, 104)]
        state = {"now": 0.0, "tick": 105, "t": 10.0}
        g = an.Gate(clock=lambda: state["now"])
        self.assertFalse(g.refresh(self.api(state, feed=window), recorded))
        self.assertFalse(g.known())
        recorded.append({"type": "bench.started", "tick": 100, "payload": {"start_tick": 100, "ticks": 16}})
        g = an.Gate(clock=lambda: state["now"])
        g.refresh(self.api(state, feed=window), recorded)
        self.assertEqual(g.sessions, {100: 16})                       # it still adds the sessions it does carry

    def test_coverage_comes_from_this_gates_own_overlapping_windows(self):
        state = {"now": 0.0, "tick": 100, "t": 10.0}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            self.assertTrue(an.Gate(clock=lambda: 0.0, state_path=path).refresh(self.api(state)))   # covered to 100
            state["tick"] = 130
            full = lambda lo: {"events": [{"type": "x", "tick": lo, "payload": {}}] * an.FEED_LIMIT}
            self.assertTrue(an.Gate(clock=lambda: 0.0, state_path=path).refresh(self.api(state, feed=full(101))))
            state["tick"] = 160                                          # covered to 130 now; a window from 132
            self.assertFalse(an.Gate(clock=lambda: 0.0, state_path=path).refresh(self.api(state, feed=full(132))))

    def test_a_failed_refresh_takes_back_the_permission_to_post(self):
        """Round 2, finding 1: a known status, then a refresh whose feed says "unavailable": unknown at once, not
        when the old status ages out."""
        state = {"now": 0.0, "tick": 100, "t": 10.0}
        g = an.Gate(clock=lambda: state["now"])
        self.assertTrue(g.refresh(self.api(state)))
        state.update(now=60.0, tick=102)
        self.assertTrue(g.known())
        self.assertFalse(g.refresh(self.api(state, feed={"events": "unavailable"})))
        self.assertFalse(g.known())

    def test_a_saved_state_is_trusted_only_whole(self):
        """Round 2, finding 3: {"covered_to": 104} without a sessions mapping is ignored, as is a bad mapping."""
        window = {"events": [{"type": "x", "tick": 103, "payload": {}}] * an.FEED_LIMIT}
        state = {"now": 0.0, "tick": 105, "t": 10.0}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            for bad in ({"covered_to": 104}, {"covered_to": 104, "sessions": []},
                        {"covered_to": 104, "sessions": {"100": "16"}}, {"covered_to": 104, "sessions": {"x": 16}},
                        {"covered_to": "104", "sessions": {}}, {"sessions": {"100": 16}},
                        {"covered_to": 104, "sessions": {}, "longest": 0}):
                path.write_text(json.dumps(bad))
                g = an.Gate(clock=lambda: 0.0, state_path=path)
                self.assertEqual((g.covered_to, g.sessions), (None, {}), bad)
                self.assertFalse(g.refresh(self.api(state, feed=window)), bad)
            path.write_text(json.dumps({"covered_to": 104, "sessions": {"100": 16}}))
            g = an.Gate(clock=lambda: 0.0, state_path=path)
            self.assertEqual((g.covered_to, g.sessions), (104, {100: 16}))

    def test_the_lookback_is_the_longest_test_seen_plus_a_margin(self):
        """Round 2, finding 4: once a 64-tick test has been seen, 32 ticks of feed no longer rule out a running one."""
        window = {"events": [{"type": "x", "tick": 55, "payload": {}}] * an.FEED_LIMIT}
        state = {"now": 0.0, "tick": 90, "t": 10.0}
        sched16 = {"upcoming": [{"at_hours": 12.0, "action": "bench", "params": {"ticks": 16}}]}
        sched64 = {"upcoming": [{"at_hours": 12.0, "action": "bench", "params": {"ticks": 64}}]}
        self.assertTrue(an.Gate(clock=lambda: 0.0).refresh(self.api(state, schedule=sched16, feed=window)))
        g = an.Gate(clock=lambda: 0.0)
        self.assertFalse(g.refresh(self.api(state, schedule=sched64, feed=window)))
        self.assertEqual(g.longest, 64)
        g = an.Gate(clock=lambda: 0.0)
        long_one = {"events": [{"type": "bench.started", "tick": 2, "payload": {"start_tick": 2, "ticks": 64}}]}
        g.refresh(self.api(state, feed=long_one))                   # a 64-tick test seen in the feed (long over)
        self.assertEqual(g.longest, 64)
        with tempfile.TemporaryDirectory() as d:                    # and remembered across a restart
            path = Path(d) / "s.json"
            path.write_text(json.dumps({"covered_to": 10, "sessions": {}, "longest": 64}))
            self.assertFalse(an.Gate(clock=lambda: 0.0, state_path=path).refresh(self.api(state, feed=window)))
            saved = Path(d) / "saved.json"
            first = an.Gate(clock=lambda: 0.0, state_path=saved)
            first.refresh(self.api(dict(state, tick=20), schedule=sched64))   # it saw the 64-tick test, then a restart
            self.assertEqual(json.loads(saved.read_text())["longest"], 64)
            self.assertEqual(an.Gate(clock=lambda: 0.0, state_path=saved).longest, 64)

    def test_a_feed_shorter_than_the_api_window_is_the_whole_feed(self):
        state = {"now": 0.0, "tick": 105, "t": 10.0}
        short = {"events": [{"type": "x", "tick": 103, "payload": {}}] * (an.FEED_LIMIT - 1)}
        self.assertTrue(an.Gate(clock=lambda: 0.0).refresh(self.api(state, feed=short)))
        full = {"events": [{"type": "x", "tick": 103, "payload": {}}] * an.FEED_LIMIT}
        self.assertFalse(an.Gate(clock=lambda: 0.0).refresh(self.api(state, feed=full)))

    def test_the_feed_is_not_read_when_the_schedule_already_says_silence(self):
        state, calls = {"now": 0.0, "tick": 100, "t": 10.0}, []
        g = an.Gate(clock=lambda: state["now"])
        soon = {"upcoming": [{"at_hours": 10.0 + 60 / 3600, "action": "bench"}]}   # starts in 60 s: silent now
        self.assertFalse(g.refresh(self.api(state, schedule=soon, calls=calls)))
        self.assertFalse(any("/api/feed" in u for u in calls))

    def test_bad_shapes_leave_the_status_unknown(self):
        for schedule, clock_ok, feed in (([1, 2], True, None), ({"upcoming": "x"}, True, None),
                                         (None, False, None), (None, True, {"events": [{"type": "bench.started",
                                                                                         "payload": ["x"]}]})):
            state = {"now": 0.0, "tick": 100, "t": 10.0}
            g = an.Gate(clock=lambda: state["now"])
            get = self.api(state, schedule=schedule, feed=feed)
            if not clock_ok:
                get = lambda url, _g=get: {"tick": "?"} if url.endswith("/api/clock") else _g(url)
            self.assertFalse(g.refresh(get), (schedule, clock_ok, feed))
            self.assertFalse(g.known())


    def test_a_later_read_never_shortens_a_window_already_placed(self):
        """The schedule stops listing a session that has not fired yet (it moved, or the API's list is cut short): the
        window the gate already placed for it stays; only its own end retires it."""
        state = {"now": 0.0, "tick": 100, "t": 10.0}
        g = an.Gate(clock=lambda: state["now"])
        sched = lambda st: {"upcoming": [{"at_hours": 10.0 + 600 / 3600, "action": "bench"}]} if st["now"] < 60 \
            else {"upcoming": []}
        self.assertTrue(g.refresh(self.api(state, schedule=sched)))
        state.update(now=60.0, tick=102, t=10.0 + 60 / 3600)
        self.assertTrue(g.refresh(self.api(state, schedule=sched)))      # the session is gone from the schedule
        state["now"] = 600.0                                             # its start, no read in between
        self.assertIsNotNone(g.quiet_end())
        state["now"] = 600.0 + an.QUIET_AFTER_S                          # and the window still ends on time
        self.assertIsNone(g.quiet_end())


class TestFailClosedLoop(unittest.TestCase):
    """Codex BLOCKs 1 and 3 on #64, at the level of the run loop."""

    def test_a_session_reported_longer_than_scheduled_keeps_the_loop_silent_to_its_real_end(self):
        state, posts = {"now": 0.0, "tick": 100}, []
        at = 10.0 + 1000 / 3600                                          # starts at t=1000 s, tick 133

        def get_json(url):
            if url.endswith("/api/schedule"):
                return {"upcoming": [{"at_hours": at, "action": "bench", "params": {"ticks": 16}}]
                        if state["now"] < 1000 else []}
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
            if "/api/feed" in url:
                return {"events": [{"type": "schedule.fired", "tick": 133, "t": at, "payload": {"action": "bench"}},
                                   {"type": "bench.started", "tick": 133, "t": at,
                                    "payload": {"start_tick": 133, "ticks": 32}}] if state["now"] >= 1000 else []}
            if url.endswith("/api/venues"):
                return {"venues": [{"venue": "v20", "status": "open"}]}
            return {"offers": []}
        run_loop(["run", "--yes", "--count", "4", "--every-min", "5", "--min-gap-min", "1", "--exclude", ""],
                 get_json, state, posts)
        lo, hi = 1000 - an.QUIET_BEFORE_S, 1000 + 32 * 30 + an.QUIET_TAIL_S         # 880 to 2080, not to 1600
        self.assertEqual([t for t, _ in posts if lo <= t < hi], [])
        # inside it, only the one status read when the scheduled 16 ticks end (it learns the 32 and goes quiet again)
        inside = [(t, u.rsplit("/api/", 1)[1]) for t, u in state["calls"] if lo <= t < hi]
        self.assertEqual(inside, [(1601.0, "schedule"), (1601.0, "clock"), (1601.0, "feed?limit=1000")])
        self.assertEqual(len(posts), 4)

    def test_a_malformed_feed_with_the_clock_paused_inside_a_test_never_posts(self):
        state, posts = {"now": 0.0, "tick": 105}, []

        def get_json(url):
            if url.endswith("/api/clock"):
                return {"tick": 105, "t_hours": 10.0, "tick_seconds": 30.0, "paused": True}
            if "/api/feed" in url:
                return {"events": "unavailable"}
            if url.endswith("/api/schedule"):
                return {"upcoming": []}
            return {"offers": [], "venues": []}
        run_loop(["run", "--yes", "--count", "1", "--deadline-min", "15", "--exclude", ""], get_json, state, posts)
        self.assertEqual(posts, [])


class TestRound2Loop(unittest.TestCase):
    def test_after_a_failed_refresh_the_loop_never_posts_on_the_old_status(self):
        """Round 2, finding 1, in the run loop: a test starts unlisted at t=200 and the feed turns "unavailable"; the
        refresh at 240 fails; the old status (read at 0) must not let a post through before it ages out at 300."""
        state, posts = {"now": 0.0, "tick": 100}, []

        def get_json(url):
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
            if "/api/feed" in url:
                return {"events": "unavailable"} if state["now"] >= 200 else {"events": []}
            if url.endswith("/api/schedule"):
                return {"upcoming": []}
            if url.endswith("/api/venues"):
                return {"venues": [{"venue": "v20", "status": "open"}]}
            return {"offers": []}
        run_loop(["run", "--yes", "--count", "20", "--every-min", "1", "--min-gap-min", "1", "--deadline-min", "8",
                  "--exclude", ""], get_json, state, posts)
        failed = min(t for t, u in state["calls"] if u.endswith("/api/schedule") and t >= 200)
        self.assertEqual([t for t, _ in posts if t >= failed], [])
        self.assertTrue([t for t, _ in posts if t < failed])


class TestStatusAfterSilence(unittest.TestCase):
    def test_the_first_request_after_a_silence_is_a_fresh_status_read(self):
        """A pause can move a Market Test while the loop sleeps through a silence: after it, nothing is read or posted
        on the status from before it (Gate.expire), even when that status is younger than STATUS_MAX_AGE_S."""
        import unittest.mock as um
        state, posts = {"now": 0.0, "tick": 100}, []

        def get_json(url):
            if url.endswith("/api/schedule"):
                return {"upcoming": [{"at_hours": 10.0 + 100 / 3600, "action": "bench", "params": {"ticks": 4}}]
                        if state["now"] < 100 else []}
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 1.0}
            if url.endswith("/api/venues"):
                return {"venues": [{"venue": "v20", "status": "open"}]}
            return {"offers": [], "events": []}
        with um.patch.object(an, "QUIET_BEFORE_S", 10), um.patch.object(an, "QUIET_AFTER_S", 30), \
                um.patch.object(an, "QUIET_TAIL_S", 5):
            run_loop(["run", "--yes", "--count", "3", "--every-min", "2", "--min-gap-min", "1", "--exclude", ""],
                     get_json, state, posts)
        lo, hi = 90, 130                                                 # the silence: 10 s before to 30 s after
        self.assertTrue(any(t < lo for t, _ in state["calls"]) and any(t >= hi for t, _ in state["calls"]))
        self.assertEqual([u for t, u in state["calls"] if lo <= t < hi], [])
        first_after = next(u for t, u in state["calls"] if t >= hi)
        self.assertTrue(first_after.endswith("/api/schedule"), first_after)
        self.assertEqual([t for t, _ in posts if lo <= t < hi], [])


class TestStateFile(unittest.TestCase):
    def test_the_variant_state_follows_a_patched_state_path(self):
        import tempfile
        import unittest.mock as um
        with tempfile.TemporaryDirectory() as d, um.patch.object(an, "STATE", Path(d) / "s.json"):
            an.save_variant(3)
            self.assertEqual(an.next_variant(), 3)
            self.assertTrue((Path(d) / "s.json").exists())


class TestDeadline(unittest.TestCase):
    def test_a_persistent_feed_outage_after_the_posts_still_ends_the_run(self):
        state, posts, logged = {"now": 0.0, "tick": 100}, [], []
        down = lambda url, st: "/api/feed" in url and st["now"] >= 30            # the feed dies after the post
        run_loop(["run", "--yes", "--count", "1", "--every-min", "1", "--deadline-min", "30", "--exclude", ""],
                 market(state, fail=[down]), state, posts, logged)
        self.assertEqual(len(posts), 1)
        self.assertLessEqual(state["now"], 30 * 60 + an.POLL_S)                  # ended at the deadline
        self.assertIn("response_unavailable", [e for e, _ in logged])


class TestTeamKey(unittest.TestCase):
    def test_the_team_client_makes_one_attempt_only(self):
        import unittest.mock as um
        with um.patch.dict(an.os.environ, {"BAZAAR_KEY": "tk-Fake-Test"}):
            c = an.team_client.__wrapped__() if hasattr(an.team_client, "__wrapped__") else REAL_TEAM_CLIENT()
        self.assertEqual(c.retries, 0)
        self.assertFalse(c.wait_on_tick)


class TestDeferredEvents(unittest.TestCase):
    def test_an_event_whose_offer_cannot_be_verified_is_deferred_not_consumed(self):
        state, posts, logged = {"now": 0.0, "tick": 100}, [], []
        offer = ask("LAT-07", 26, venue="v20", maker="t15", oid=5)
        reads = {"n": 0}

        def flaky(url, st):                       # v20 shows the offer to the poll, then fails once in compose
            if st["now"] >= 200 and url.endswith("/api/venues/v20/offers"):
                st["v20"] = [offer]
                reads["n"] += 1
                return reads["n"] == 2
            return False
        run_loop(["run", "--yes", "--on-event", "--count", "2", "--every-min", "60", "--min-gap-min", "0",
                  "--exclude", ""], market(state, fail=[flaky]), state, posts, logged)
        whys = [(e, d.get("why")) for e, d in logged if e in ("announce", "deferred")]
        self.assertEqual(whys, [("announce", "slot"), ("deferred", "event"), ("announce", "event")])
        self.assertIn("t15 sells LAT-07 for 26 P (offer 5)", posts[1][1])  # posted once verified


class TestCleaning(unittest.TestCase):
    def test_a_key_in_an_http_error_body_never_reaches_stdout_or_the_log(self):
        import io
        import unittest.mock as um
        import urllib.error

        def boom(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(b'bad key bk_SYNTH_KEY_123 tk-AbCd-EfGh'))
        with um.patch.object(an.urllib.request, "urlopen", boom):
            res = an.post_announce("hi", "bk_real")
        self.assertNotIn("bk_SYNTH_KEY_123", json.dumps(res))
        self.assertNotIn("tk-AbCd-EfGh", json.dumps(res))
        glued = an.clean({"body": "keyXbk_GLUED_1 and Ztk-AbCd-EfGh9", "list": ["abk_IN_LIST"]})
        self.assertNotIn("bk_GLUED_1", json.dumps(glued))                 # \b-based redaction misses these
        self.assertNotIn("tk-AbCd-EfGh", json.dumps(glued))
        self.assertNotIn("bk_IN_LIST", json.dumps(glued))
        state, posts, logged, out = {"now": 0.0, "tick": 100}, [], [], io.StringIO()
        with um.patch("sys.stdout", out), um.patch.object(an, "post_announce",
                                                          lambda t, k: {"http_error": 500, "body": "echo bk_LEAK_9"}):
            import tempfile
            with tempfile.TemporaryDirectory() as d, \
                    um.patch.object(an, "get_json", market(state)), um.patch.object(an, "STATE", Path(d) / "s"), \
                    um.patch.object(an.time, "time", lambda: state["now"]), \
                    um.patch.object(an, "recorded_events", lambda *a, **k: []), \
                    um.patch("runlog.RunLog", type("L", (), {"__init__": lambda s, *a: None, "start": lambda s, **k: None,
                                                            "event": lambda s, e, **d: logged.append((e, d)),
                                                            "end": lambda s: None})), \
                    um.patch("broker.load_broker_key", lambda *_: "bk_fake"):
                an.main(["run", "--yes", "--count", "1", "--exclude", ""])
        self.assertNotIn("bk_LEAK_9", out.getvalue())
        self.assertNotIn("bk_LEAK_9", json.dumps([d for _, d in logged]))


class TestCli(unittest.TestCase):
    def test_run_without_yes_refuses_before_any_key_or_network(self):
        with self.assertRaises(SystemExit) as cm:
            an.main(["run"])
        self.assertEqual(cm.exception.code, 2)          # argparse refused it; no key was read

    def test_run_loop_posts_on_a_new_v20_offer_then_measures_and_stops(self):
        import tempfile
        import unittest.mock as um
        older = ask("MAL-01", 6, venue="v20", maker="t13", oid=4)
        state = {"tick": 100, "now": 0.0, "v20": [older]}
        posts, logged = [], []

        def get_json(url):
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
            if url.endswith("/api/venues/v20/offers"):
                return {"offers": state["v20"]}
            if "/api/feed" in url:
                return {"events": [{"type": "offer.listed", "tick": 104, "actor": "t15",
                                    "payload": {"offer": {"id": 5, "maker": "t15", "venue": "v20"}}}]}
            if url.endswith("/api/venues"):
                return {"venues": [{"venue": "v20", "status": "open"}]}
            return {"offers": []}

        def sleep(_):
            state["now"] += an.POLL_S
            state["tick"] += 1
            if state["tick"] == 103:                  # an explorer lists on v20
                state["v20"] = [older, ask("LAT-07", 26, venue="v20", maker="t15", oid=5)]

        class Log:
            def __init__(self, *_): pass
            def start(self, **k): pass
            def event(self, e, **d): logged.append((e, d))
            def end(self): pass

        with tempfile.TemporaryDirectory() as d, \
                um.patch.object(an, "get_json", get_json), um.patch.object(an.time, "sleep", sleep), \
                um.patch.object(an.time, "time", lambda: state["now"]), um.patch.object(an, "STATE", Path(d) / "s"), \
                um.patch.object(an, "post_announce", lambda text, key: posts.append(text) or {"ok": True}), \
                um.patch("runlog.RunLog", Log), um.patch("broker.load_broker_key", lambda *_: "bk_fake"):
            an.main(["run", "--yes", "--count", "2", "--every-min", "30", "--on-event", "--min-gap-min", "0",
                     "--exclude", ""])
        self.assertEqual(len(posts), 2)
        self.assertIn("now: t15 sells LAT-07 for 26 P (offer 5); t13 sells MAL-01", posts[1])  # the new one leads
        self.assertIn("POST /api/offers/5/accept", posts[1])
        whys = [d["why"] for e, d in logged if e == "announce"]
        self.assertEqual(whys, ["slot", "event"])
        self.assertEqual(sum(e == "response" for e, _ in logged), 2)          # both measured before it stops

    def test_a_failed_feed_or_venue_index_read_never_cancels_the_run(self):
        import tempfile
        import unittest.mock as um
        state = {"tick": 100, "now": 0.0, "prev": []}
        posts = []

        def get_json(url):
            status_read = state["prev"][-2:] == ["schedule", "clock"]   # the gate's own feed read: it answers
            state["prev"].append("schedule" if url.endswith("/api/schedule") else
                                 "clock" if url.endswith("/api/clock") else "other")
            if url.endswith("/api/clock"):
                return {"tick": state["tick"], "t_hours": 10.0 + state["now"] / 3600, "tick_seconds": 30.0}
            if ("/api/feed" in url and not status_read) or url.endswith("/api/venues"):
                raise TimeoutError("slow")                              # the composing reads fail
            if url.endswith("/api/venues/v20/offers"):
                return {"offers": [ask("LAT-07", 26, venue="v20", maker="t15", oid=5)]}
            return {"offers": [], "events": [], "upcoming": []}

        def sleep(_):
            state["now"] += an.POLL_S
            state["tick"] += 1
            if state["tick"] > 2000:                  # fail, never hang, if the loop cannot end
                raise AssertionError("the run loop did not end")

        class Log:
            def __init__(self, *_): pass
            def start(self, **k): pass
            def event(self, e, **d): pass
            def end(self): pass

        with tempfile.TemporaryDirectory() as d, \
                um.patch.object(an, "get_json", get_json), um.patch.object(an.time, "sleep", sleep), \
                um.patch.object(an.time, "time", lambda: state["now"]), um.patch.object(an, "STATE", Path(d) / "s"), \
                um.patch.object(an, "post_announce", lambda text, key: posts.append(text) or {"ok": True}), \
                um.patch("runlog.RunLog", Log), um.patch("broker.load_broker_key", lambda *_: "bk_fake"):
            an.main(["run", "--yes", "--count", "2", "--every-min", "1", "--exclude", ""])
        self.assertEqual(len(posts), 2)                                # both posts went out
        self.assertIn("t15 sells LAT-07 for 26 P (offer 5)", posts[0])    # v20's book still read; maker from the book
        # (and the run ended although no response could be measured: the feed never answered)

    def test_unmeasurable_posts_are_given_up_so_the_run_ends(self):
        a = an.Announcer(1, 60, measure_ticks=20)
        a.mark_posted(0, 100, "slot")
        self.assertEqual(a.give_up(100 + 20 + an.GIVE_UP_TICKS - 1), [])
        self.assertEqual([p["post"] for p in a.give_up(100 + 20 + an.GIVE_UP_TICKS)], [1])
        self.assertEqual(a.pending, [])

    def test_variant_state_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            self.assertEqual(an.next_variant(p), 0)
            an.save_variant(2, p)
            self.assertEqual(an.next_variant(p), 2)


if __name__ == "__main__":
    unittest.main()



def match(team, card, set_="MAL", tier=4, holders=(("t05", "Team 5"),), dealers=("Abuela",), price=24, action=None):
    """One entry of tools/matchmaker.py's output, as announce reads it. action: (side, offer, venue, price, maker,
    expires, gives)."""
    m = {"tier": tier, "inferred": tier >= 3, "p_missing": 0.9 if tier >= 3 else None, "team": team,
         "team_name": f"Team {int(team[1:])}", "set": set_,
         "set_name": {"MAL": "Malasaña", "SAL": "Salamanca"}.get(set_, set_), "card": card, "card_name": None,
         "holders": [{"team": t, "name": n, "as_of": 1445} for t, n in holders], "dealers": [{"name": d} for d in dealers],
         "price": price, "action": None, "proposal": None}
    if action:
        side, oid, venue, p, maker, exp, gives = action
        m["action"] = {"side": side, "offer": oid, "venue": venue, "price": p, "maker": maker,
                       "maker_name": f"Team {int(maker[1:])}", "expires_tick": exp, "gives": gives}
    else:
        m["proposal"] = {"price": price, "buyer": {"team": team, "post": {"venue": "v20", "give": {"cash": price},
                                                                         "want": {"cards": [card]},
                                                                         "expires_in_ticks": 240}}}
    return m


class TestMissingVariant(unittest.TestCase):
    BID = {"rastro": [dict(bid("SAL-06", 20, oid=20259), expires_tick=1505)]}

    def test_a_live_bid_is_named_with_its_offer_expiry_and_the_one_action(self):
        doc = {"matches": [match("t09", "SAL-06", "SAL", tier=1, action=("bid", 20259, "rastro", 20, "t09", 1505, None))]}
        text, key = an.missing_text(doc, self.BID, tick=1400)
        self.assertIn("Team 9 bids 20 P for SAL-06 on El Rastro: offer #20259, open until tick 1505.", text)
        self.assertIn('POST /api/offers/20259/accept with {"assets": [<your SAL-06 asset id>]}', text)
        self.assertIn("Team 5 held a copy at tick 1445 (reconstructed from public trades, may have changed).", text)
        self.assertNotIn("Abuela", text)                                # a dealer cannot accept a team's offer
        self.assertNotIn("appears", text)                               # an explicit want is no inference
        self.assertEqual(key, "t09:SAL-06:20259")

    def test_an_inferred_need_is_always_said_as_one_and_the_broker_is_not_oversold(self):
        text, _ = an.missing_text({"matches": [match("t13", "MAL-08")]}, {})
        self.assertIn("Team 13 appears to be missing MAL-08 for the Malasaña page (inferred from public trades, not "
                      "confirmed).", text)
        self.assertIn('A bid on La Celestina (v20, 0 % fee, 0 P per card): {"venue": "v20", "give": {"cash": 24}, '
                      '"want": {"cards": ["MAL-08"]}}', text)
        self.assertIn("Abuela sells it.", text)
        self.assertIn("from two different teams when the bid covers the ask plus the fee, at the midpoint, as capacity "
                      "allows.", text)
        for oversold in ("any ask", "same tick", "the tick they meet"):
            self.assertNotIn(oversold, text)
        ask_book = {"rastro": [dict(ask("LAT-07", 30, oid=20218), expires_tick=1455)]}
        doc = {"matches": [match("t14", "LAT-07", tier=3, action=("ask", 20218, "rastro", 30, "t06", 1455, None))]}
        text, _ = an.missing_text(doc, ask_book, tick=1440)
        self.assertIn("Team 6 sells LAT-07 for 30 P on El Rastro: offer #20218, open until tick 1455. Team 14 appears "
                      "to be missing LAT-07", text)

    def test_a_swap_is_accepted_directly_and_never_said_to_be_crossed(self):
        doc = {"matches": [match("t06", "RET-12", tier=2, holders=(),
                                 action=("swap", 20068, "rastro", 0, "t06", 1481, "SAL-02"))]}
        text, _ = an.missing_text(doc, {"rastro": [swap("SAL-02", "RET-12", oid=20068)]})
        self.assertIn("Team 6 gives SAL-02 for any RET-12 on El Rastro: offer #20068", text)
        self.assertIn("accepting it directly (a swap is accepted, never crossed by a broker)", text)
        self.assertNotIn("broker crosses", text)

    def test_team_3_never_appears_as_buyer_holder_or_maker(self):
        doc = {"matches": [match("t03", "MAL-08"),
                           match("t09", "SAL-06", tier=1, action=("bid", 20259, "rastro", 20, "t03", 1505, None)),
                           match("t13", "LAT-06", holders=(("t03", "Team 3"), ("t06", "Team 6")))]}
        text, key = an.missing_text(doc, self.BID)
        self.assertNotIn("Team 3 ", text)
        self.assertNotIn("t03", text)
        self.assertEqual(key, "t13:LAT-06:v20")
        self.assertIn("Team 6 held a copy", text)

    def test_an_excluded_card_never_appears_not_even_as_what_a_swap_gives(self):
        doc = {"matches": [match("t13", "MAL-05"), match("t13", "MAL-08")]}
        text, _ = an.missing_text(doc, {}, exclude=("MAL-05",))
        self.assertNotIn("MAL-05", text)
        with self.assertRaises(LookupError):                       # nothing left to say: no post
            an.missing_text({"matches": [match("t13", "MAL-05")]}, {}, exclude=("MAL-05",))
        sw = {"matches": [match("t06", "RET-12", tier=2, action=("swap", 9, "rastro", 0, "t06", 1481, "LAV-09"))]}
        with self.assertRaises(LookupError):
            an.missing_text(sw, {"rastro": [swap("LAV-09", "RET-12", oid=9)]}, exclude=("LAV-09",))

    def test_the_named_offer_is_rechecked_in_its_current_book(self):
        doc = {"matches": [match("t09", "SAL-06", tier=1, action=("bid", 20259, "rastro", 20, "t09", 1505, None)),
                           match("t13", "MAL-08")]}
        ok = dict(bid("SAL-06", 20, oid=20259), expires_tick=1505)
        self.assertEqual(an.missing_text(doc, {"rastro": [ok]}, tick=1400)[1], "t09:SAL-06:20259")
        for book, tick in (([], 1400),                                                     # gone
                           ([dict(ok, status="accepted")], 1400),                          # taken
                           ([ok], 1500),                                                   # about to expire
                           ([dict(ok, give={"cash": 12, "assets": [], "types": []})], 1400),  # price changed
                           ([dict(bid("SAL-07", 20, oid=20259), expires_tick=1505)], 1400),   # another card
                           ([dict(ok, to="t05")], 1400)):                                  # now for one team only
            self.assertEqual(an.missing_text(doc, {"rastro": book}, tick=tick)[1], "t13:MAL-08:v20", (book, tick))

    def test_a_swap_that_now_gives_another_card_is_not_named(self):
        doc = {"matches": [match("t06", "RET-12", tier=2, holders=(),
                                 action=("swap", 20068, "rastro", 0, "t06", 1481, "SAL-02")), match("t13", "MAL-08")]}
        self.assertEqual(an.missing_text(doc, {"rastro": [swap("SAL-03", "RET-12", oid=20068)]})[1], "t13:MAL-08:v20")

    def test_an_offer_on_a_rival_venue_or_for_one_team_is_skipped(self):
        doc = {"matches": [match("t06", "SAL-12", tier=2, action=("bid", 8, "v21", 450, "t06", 1488, None)),
                           match("t09", "SAL-06", tier=1, action=("bid", 20259, "rastro", 20, "t09", 1505, None)),
                           match("t13", "MAL-08")]}
        books = {"v21": [bid("SAL-12", 450, oid=8, venue="v21")], "rastro": [dict(bid("SAL-06", 20, oid=20259), to="t05")]}
        self.assertEqual(an.missing_text(doc, books)[1], "t13:MAL-08:v20")
        self.assertEqual(an.missing_text(doc, books, rival_venues=True)[1], "t06:SAL-12:8")

    def test_the_venue_owner_is_told_it_cannot_take_it(self):
        m = match("t06", "SAL-12", tier=2, holders=(("t21", "Team 21"), ("t09", "Team 9")),
                  action=("bid", 8, "v21", 450, "t06", 1488, None))
        m["action"]["venue_owner"] = "t09"
        text = an.missing_line(m)
        self.assertIn("A team with a copy (not t09: a team cannot trade on its own venue)", text)
        self.assertIn("Team 21 held a copy", text)
        self.assertNotIn("Team 9 held", text)

    def test_a_match_named_lately_is_not_named_again(self):
        doc = {"matches": [match("t13", "MAL-08"), match("t14", "LAT-06", set_="LAT")]}
        self.assertEqual(an.missing_text(doc, {}, recent=["t13:MAL-08:v20"])[1], "t14:LAT-06:v20")
        with self.assertRaises(LookupError):
            an.missing_text(doc, {}, recent=["t13:MAL-08:v20", "t14:LAT-06:v20"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            for i in range(an.MISSING_REPEAT + 2):
                an.remember_match(f"k{i}", path)
            self.assertEqual(an.recent_matches(path), [f"k{i}" for i in range(2, an.MISSING_REPEAT + 2)])

    def test_the_response_names_a_candidate_settlement_with_the_offers_whole_structure(self):
        bid_named = {"card": "SAL-06", "offer": 20259, "venue": "rastro", "maker": "t09", "side": "bid", "price": 20}
        ask_named = {"card": "LAT-07", "offer": 20218, "venue": "rastro", "maker": "t06", "side": "ask", "price": 30,
                     "asset": 1133}
        swap_named = {"card": "RET-12", "offer": 20068, "venue": "rastro", "maker": "t06", "side": "swap",
                      "asset": 501, "gives": "SAL-02"}

        def settle(tick, items, venue="rastro", price=20):
            return {"type": "settlement", "tick": tick, "payload": {"venue": venue, "price": price, "items": [
                {"kind": "card", "ref": r, "id": i, "frm": f, "to": to} for r, i, f, to in items]}}
        ok = settle(105, [("SAL-06", 1, "t05", "t09")])
        res = an.named_outcome([ok], 100, 20, bid_named)
        self.assertEqual((res["candidate"], res["candidate_tick"]), (True, 105))
        self.assertIn("no offer id", res["attribution"])
        self.assertNotIn("settled", res)                                     # never presented as proof
        for ev in (settle(99, [("SAL-06", 1, "t05", "t09")]),                           # before the post
                   settle(105, [("SAL-06", 1, "t09", "t05")]),                          # t09 SELLS it: wrong way
                   settle(105, [("SAL-07", 1, "t05", "t09")]),                          # another card
                   settle(105, [("SAL-06", 1, "t05", "t09")], price=18),                # another price
                   settle(105, [("SAL-06", 1, "t05", "t09")], venue="v02"),             # another venue
                   settle(105, [("SAL-06", 1, "t05", "t09"), ("SAL-06", 2, "t05", "t09")])):   # two copies
            self.assertFalse(an.named_outcome([ev], 100, 20, bid_named)["candidate"], ev)
        self.assertTrue(an.named_outcome([settle(105, [("LAT-07", 1133, "t06", "t14")], price=30)], 100, 20,
                                         ask_named)["candidate"])
        for ev in (settle(105, [("LAT-07", 999, "t06", "t14")], price=30),              # another copy
                   settle(105, [("LAT-07", 1133, "t14", "t06")], price=30)):            # the other way
            self.assertFalse(an.named_outcome([ev], 100, 20, ask_named)["candidate"], ev)
        self.assertTrue(an.named_outcome([settle(105, [("SAL-02", 501, "t06", "t05"), ("RET-12", 7, "t05", "t06")],
                                                 price=0)], 100, 20, swap_named)["candidate"])
        for items in ([("SAL-03", 501, "t06", "t05"), ("RET-12", 7, "t05", "t06")],     # the wrong card given
                      [("SAL-02", 501, "t06", "t05"), ("RET-11", 7, "t05", "t06")],     # the wrong card got
                      [("SAL-02", 501, "t06", "t05"), ("RET-12", 7, "t07", "t06")],     # two counterparties
                      [("SAL-02", 501, "t06", "t05")]):                                 # one leg only
            self.assertFalse(an.named_outcome([settle(105, items, price=0)], 100, 20, swap_named)["candidate"], items)
        self.assertTrue(an.named_outcome([settle(110, [("SAL-06", 1, "t05", "t07")], venue="v20")], 100, 20,
                                         bid_named)["v20_trade"])
        fits = lambda items, price=0: an.outcome_fits(settle(105, items, price=price)["payload"], swap_named)
        self.assertTrue(fits([("SAL-02", 501, "t06", "t05"), ("RET-12", 7, "t05", "t06")]))
        self.assertFalse(fits([("SAL-02", 501, "t06", "t05"), ("RET-11", 7, "t05", "t06")]))      # wanted card
        self.assertFalse(fits([("SAL-02", 501, "t06", "t05"), ("RET-12", 7, "t05", "t06"),
                               ("LAV-01", 8, "t05", "t06")]))                                    # a third card
        self.assertFalse(fits([("SAL-02", 501, "t06", "t05"), ("RET-12", 7, "t05", "t06")], price=5))  # cash too

    def test_a_missing_or_stale_matchmaker_file_is_never_posted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "latest.json"
            with self.assertRaises(LookupError):
                an.load_matches(path, now=100)
            path.write_text(json.dumps({"generated_at": 100, "matches": []}))
            self.assertEqual(an.load_matches(path, now=100 + an.MATCHES_MAX_AGE_S)["generated_at"], 100)
            with self.assertRaises(LookupError):
                an.load_matches(path, now=101 + an.MATCHES_MAX_AGE_S)

    def test_run_names_one_match_per_post_never_twice_never_in_a_silence_never_from_a_stale_file(self):
        import tempfile
        import unittest.mock as um
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "latest.json"
            path.write_text(json.dumps({"generated_at": 0, "matches": [match("t13", "MAL-08"),
                                                                       match("t14", "LAT-06", set_="LAT")]}))
            state, posts, logged = {"now": 0.0, "tick": 100}, [], []
            with um.patch.object(an, "MISSING_STATE", Path(d) / "recent.json"):
                run_loop(["run", "--yes", "--variant", "missing", "--matches", str(path), "--count", "4",
                          "--every-min", "5", "--min-gap-min", "1", "--exclude", ""],
                         market(state, bench_at_s=1200), state, posts, logged)
        lo, hi = 1200 - an.QUIET_BEFORE_S, 1200 + an.QUIET_AFTER_S
        self.assertEqual([t for t, _ in state["calls"] if lo <= t < hi], [])  # no request inside the Market Test
        self.assertEqual([t for t, _ in posts if t > an.MATCHES_MAX_AGE_S], [])  # never from a stale file
        self.assertEqual(len(posts), 2)                                      # two matches, each named once
        self.assertIn("Team 13 appears to be missing MAL-08", posts[0][1])
        self.assertIn("Team 14 appears to be missing LAT-06", posts[1][1])
        self.assertEqual([d["key"] for e, d in logged if e == "named"], ["t13:MAL-08:v20", "t14:LAT-06:v20"])

    def test_variant_takes_only_numbers_or_missing(self):
        with self.assertRaises(SystemExit):
            an.main(["plan", "--variant", "pairs"])


class InferredThreshold(unittest.TestCase):
    """--variant missing names an inferred need only at p_missing >= MIN_P_ANNOUNCE and never for a team whose deck
    contradicts the leaderboard (docs/plans/matchmaker-validation.md). Mutation-first: each fails without its guard."""

    def doc(self, p, consistent=None):
        m = match("t13", "MAL-08")
        m["p_missing"] = p
        d = {"matches": [m]}
        if consistent is not None:
            d["teams"] = {"t13": {"consistent": consistent}}
        return d

    def test_the_default_threshold_is_the_validated_one(self):
        self.assertEqual(an.MIN_P_ANNOUNCE, 0.8)

    def test_an_inferred_need_below_the_threshold_is_never_named(self):
        self.assertIsNone(an.pick_match(self.doc(0.62), {}))
        self.assertIsNotNone(an.pick_match(self.doc(0.62), {}, min_p=0.6))
        self.assertIsNotNone(an.pick_match(self.doc(0.91), {}))

    def test_an_inferred_need_without_a_probability_is_never_named(self):
        self.assertIsNone(an.pick_match(self.doc(None), {}, min_p=0.0))
        m = match("t13", "MAL-08")
        m["inferred"] = None    # a malformed entry is treated as an inference
        m["p_missing"] = None
        self.assertIsNone(an.pick_match({"matches": [m]}, {}, min_p=0.0))

    def test_a_team_whose_deck_contradicts_the_leaderboard_is_never_named(self):
        self.assertIsNone(an.pick_match(self.doc(0.95, consistent=False), {}))
        self.assertIsNotNone(an.pick_match(self.doc(0.95, consistent=True), {}))

    def test_a_live_want_needs_no_probability(self):
        doc = {"matches": [match("t09", "SAL-06", "SAL", tier=1,
                                 action=("bid", 20259, "rastro", 20, "t09", 1505, None))]}
        books = {"rastro": [dict(bid("SAL-06", 20, oid=20259), expires_tick=1505)]}
        self.assertIsNotNone(an.pick_match(doc, books, tick=1445))


import unittest.mock as um  # noqa: E402


class ProbabilityAndExclusion(unittest.TestCase):
    """Sol's round 1 on #73: p_missing must be a real probability; a bad holdings snapshot never stops the announcer
    and never lets a page card through (fails closed)."""

    def doc(self, p):
        m = match("t13", "MAL-08")
        m["p_missing"] = p
        return {"matches": [m]}

    def test_only_a_real_probability_passes(self):
        for bad in (float("nan"), True, 1.5, -0.1, "0.9", float("inf")):
            with self.subTest(bad=bad):
                self.assertIsNone(an.pick_match(self.doc(bad), {}, min_p=0.0))
        self.assertIsNotNone(an.pick_match(self.doc(1), {}))
        self.assertIsNotNone(an.pick_match(self.doc(0.85), {}))

    def test_min_p_is_validated(self):
        import argparse
        for bad in ("nan", "1.5", "-0.1", "x", "inf"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                an.min_p_arg(bad)
        self.assertEqual(an.min_p_arg("0.8"), 0.8)
        with um.patch("sys.stderr"), self.assertRaises(SystemExit):
            an.main(["plan", "--variant", "missing", "--min-p", "nan"])

    def run_plan(self, me_body, catalog_error=None):
        """plan --variant missing with every read faked: no network. Returns what it printed."""
        import io
        import value_inference
        with tempfile.TemporaryDirectory() as d:
            mp = Path(d) / "latest.json"
            mp.write_text(json.dumps({"generated_at": time.time(), "tick": 1500, "matches": [match("t13", "MAL-08")]}))
            me = Path(d) / "me.json"
            me.write_text(json.dumps(me_body))
            out = io.StringIO()
            cat = {"sets": [{"id": "MAL", "released": True, "cards": [
                {"id": f"MAL-0{i}", "rarity": "common", "page": True} for i in range(1, 9)]}]}
            catalog = um.MagicMock(side_effect=catalog_error) if catalog_error else um.MagicMock(return_value=cat)
            with um.patch.object(an, "get_json", lambda url: {"events": [{"id": 1, "tick": 1500}], "tick": 1500}), \
                    um.patch.object(value_inference, "catalog", catalog), um.patch("sys.stdout", out), \
                    um.patch.object(an, "recorded_events", lambda *a, **k: []):
                an.main(["plan", "--variant", "missing", "--matches", str(mp), "--exclude-from", str(me)])
        return out.getvalue()

    GOOD = {"id": "t03", "tick": 1500, "tick_seconds": 15, "assets": []}

    def test_a_trusted_snapshot_lets_a_card_we_lack_be_hidden_and_others_through(self):
        self.assertIn("nothing to post", self.run_plan(self.GOOD))                     # we lack MAL-08: hidden
        holds = dict(self.GOOD, assets=[{"id": 1, "kind": "card", "ref": "MAL-08"}])
        self.assertIn("MAL-08", self.run_plan(holds).split("chars:")[-1])              # we hold it: shown

    def test_a_bad_snapshot_suppresses_page_cards_and_never_raises(self):
        holds = dict(self.GOOD, assets=[{"id": 1, "kind": "card", "ref": "MAL-08"}])
        for bad in (dict(holds, tick_seconds="bad"), dict(holds, id=None), dict(holds, tick=1000)):
            with self.subTest(bad=bad):
                text = self.run_plan(bad)
                self.assertIn("nothing to post", text)
                self.assertIn("page cards suppressed", text)

    def test_a_catalog_failure_is_no_post_not_a_crash(self):
        text = self.run_plan(self.GOOD, catalog_error=OSError("down"))
        self.assertIn("nothing to post (exclude: OSError", text)
