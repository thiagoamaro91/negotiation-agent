"""tools/announce.py: the market read right (best sides with ids, v20's live offers from the feed, makers named from
the feed), the message variants, and that nothing posts without --yes. Offline: no key, no network.
Run: python3 -m unittest discover tests"""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import announce as an  # noqa: E402

_ids = iter(range(1000, 10**6))


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
                return {"tick": state["tick"]}
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
        for tick_s in (15.0, 30.0, 60.0):
            (w,) = an.quiet_windows(sched, {"t_hours": 10.0, "tick_seconds": tick_s}, 0.0)
            self.assertEqual(w, (3600 - an.QUIET_BEFORE_S, 3600 + an.QUIET_AFTER_S), tick_s)


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
                return {"tick": state["tick"]}
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
                return {"tick": state["tick"]}
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
