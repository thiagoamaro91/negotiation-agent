"""Open Bazaar · who needs which card: La Celestina's public board from tools/matchmaker.py's output
(tools/celestina.py missing_view, /api/missing, the first key of /api/match, the page). Offline, no key.
Run: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import unittest.mock as um
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import celestina as cel  # noqa: E402

NOW = 1_000_000.0


def m(team, card, tier=4, inferred=True, holders=(("t05", 890),), action=None, price=24, to=None, owner=None):
    out = {"tier": tier, "inferred": inferred, "team": team, "team_name": f"Team {int(team[1:])}", "card": card,
           "card_name": "Name", "rarity": "uncommon", "set_name": "Malasaña", "p_missing": 0.9 if inferred else None,
           "holders": [{"team": t, "name": f"Team {int(t[1:])}", "copies": 2, "asset": a, "spare": True}
                       for t, a in holders],
           "dealers": [{"name": "Abuela"}], "price": price, "prices": {"fair": 16.5, "team_range": {"low": 15, "high": 20}},
           "action": None}
    if action:
        side, oid, venue, p, maker = action
        out["action"] = {"side": side, "offer": oid, "venue": venue, "price": p, "fee": 2, "expires_tick": 1505,
                         "maker": maker, "maker_name": f"Team {int(maker[1:])}", "who": [t for t, _ in holders],
                         "gives": "SAL-02" if side == "swap" else None, "to": to, "venue_owner": owner}
    return out


DOC = {"generated_at": NOW - 60, "tick": 1445, "matches": [
    m("t09", "SAL-06", tier=1, inferred=False, holders=(("t05", 890),), action=("bid", 20259, "rastro", 20, "t09")),
    m("t13", "MAL-08"),
    m("t03", "LAV-09"),                                                              # Team 3 as buyer: never shown
    m("t14", "LAT-07", tier=3, holders=(("t06", 1133),), action=("ask", 20218, "rastro", 30, "t03")),  # our offer
]}


def row(oid, kind, ref, price, venue="rastro", to=None, want_ref=None, exp=1505):
    return {"offer": oid, "kind": kind, "ref": ref, "price": price, "venue": venue, "to": to, "want_ref": want_ref,
            "expires_tick": exp}


PUB = {"tick": 1446, "cards": {"SAL-06": {"offers": [row(20259, "bid", "SAL-06", 20)]}}}
BANNED = ("holders", "holdings", "copies", "net", "targets", "who", "spare")


def keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from keys(v)


class Board(unittest.TestCase):
    def test_the_board_keeps_live_wants_first_labels_inferences_and_never_shows_the_holder_map(self):
        v = cel.missing_view(DOC, now=NOW, pub=PUB)
        self.assertEqual(v["name"], "Open Bazaar · who needs which card")
        self.assertEqual([(e["team"], e["card"]) for e in v["matches"]], [("t09", "SAL-06"), ("t13", "MAL-08")])
        live, inferred = v["matches"]
        self.assertEqual((live["need"], live["action"]["live"], live["action"]["call"]),
                         ("live bid", True, "POST https://bazaar.causaprima.ai/api/offers/20259/accept"))
        self.assertEqual(inferred["need"], cel.INFERRED_NOTE)
        self.assertEqual(inferred["holder_count"], 1)
        self.assertEqual(inferred["orders"]["ask"]["give"], {"assets": ["<your MAL-08 asset id>"]})
        self.assertFalse(set(keys(v)) & set(BANNED))
        self.assertNotIn("890", json.dumps(v))                         # nobody's asset id
        self.assertNotIn("t03", json.dumps(v))

    def test_a_team_id_shows_only_that_teams_own_needs_never_what_it_holds(self):
        self.assertEqual(cel.missing_view(DOC, team="t05", now=NOW, pub=PUB)["matches"], [])   # t05 only holds
        v = cel.missing_view(DOC, team="t13", now=NOW, pub=PUB)
        self.assertEqual([(e["card"], e["yours"]) for e in v["matches"]], [("MAL-08", True)])
        self.assertNotIn("you_hold", json.dumps(v))
        self.assertNotIn("your_ask", json.dumps(v))

    def test_a_named_offer_is_served_live_only_while_the_current_book_shows_it_unchanged(self):
        def action(pub):
            return cel.missing_view(DOC, now=NOW, pub=pub)["matches"][0]["action"]
        self.assertTrue(action(PUB)["live"])
        for pub in (None, {"tick": 1446, "cards": {}},                                          # warming up, gone
                    {"tick": 1446, "cards": {"x": {"offers": [row(20259, "bid", "SAL-06", 18)]}}},   # price changed
                    {"tick": 1446, "cards": {"x": {"offers": [row(20259, "ask", "SAL-06", 20)]}}},   # another side
                    {"tick": 1446, "cards": {"x": {"offers": [row(20259, "bid", "SAL-07", 20)]}}},   # another card
                    {"tick": 1446, "cards": {"x": {"offers": [row(20259, "bid", "SAL-06", 20, to="t05")]}}},
                    {"tick": 1500, "cards": PUB["cards"]}):                                       # about to expire
            a = action(pub)
            self.assertEqual((a["live"], "call" in a), (False, False), pub)
            self.assertIn("history", a["history"])

    def test_an_addressed_offer_names_its_addressee_and_an_owner_is_told_it_cannot(self):
        doc = {"generated_at": NOW, "matches": [
            m("t09", "SAL-06", tier=1, inferred=False, action=("bid", 1, "v07", 20, "t09"), to="t05"),
            m("t08", "SAL-07", tier=2, inferred=False, action=("bid", 2, "v07", 20, "t08"), owner="t10")]}
        pub = {"tick": 1, "cards": {"a": {"offers": [row(1, "bid", "SAL-06", 20, "v07", to="t05"),
                                                     row(2, "bid", "SAL-07", 20, "v07")]}}}
        a, b = (e["action"] for e in cel.missing_view(doc, now=NOW, pub=pub)["matches"])
        self.assertIn("only Team 5 (it is addressed to that team) accepts it", a["how"])
        self.assertNotIn("a team with a copy", a["how"])
        self.assertIn("not Team 10 (a team cannot trade on its own venue)", b["how"])

    def test_the_broker_is_described_as_it_works(self):
        how = cel.missing_view(DOC, now=NOW, pub=PUB)["matches"][1]["orders"]["how"]
        self.assertIn("from two different teams when the bid covers the ask plus the fee", how)
        self.assertIn("as capacity allows", how)
        for oversold in ("same tick", "the tick they meet", "any ask"):
            self.assertNotIn(oversold, how)

    def test_a_stale_or_missing_file_is_an_empty_board(self):
        self.assertEqual(cel.missing_view(DOC, now=NOW + cel.MATCHES_MAX_AGE)["matches"], [])
        self.assertTrue(cel.missing_view({}, now=NOW)["stale"])
        self.assertEqual(cel.MissingBoard(Path("/nonexistent/latest.json")).load(), {})

    def test_text_lines_are_only_the_callers_own_needs(self):
        doc = dict(DOC, matches=DOC["matches"] + [
            m("t14", "LAT-07", tier=3, holders=(("t06", 1133),), action=("ask", 20218, "rastro", 30, "t06"))])
        pub = {"tick": 1446, "cards": {"x": {"offers": [row(20218, "ask", "LAT-07", 30)]}}}
        lines = cel.bazaar_lines(cel.missing_view(doc, team="t14", now=NOW, pub=pub)["matches"], cel.GAME)
        self.assertEqual(lines, ["OPEN BAZAAR: Team 6 sells LAT-07 for 30 P on El Rastro (offer 20218); you appear to "
                                 "be missing it (inferred) -> POST https://bazaar.causaprima.ai/api/offers/20218/accept {}"])
        self.assertEqual(cel.bazaar_lines(cel.missing_view(doc, team="t05", now=NOW, pub=pub)["matches"], cel.GAME), [])
        entries = cel.missing_view(doc, now=NOW, pub=pub)["matches"]
        theirs = [dict(e, yours=False) for e in entries]                    # someone else's needs: no line
        gone = [dict(e, yours=True) for e in cel.missing_view(doc, now=NOW, pub=None)["matches"] if e.get("action")]
        self.assertEqual(cel.bazaar_lines(theirs + gone, cel.GAME), [])     # an offer no longer standing: no line


class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "latest.json"
        path.write_text(json.dumps(dict(DOC, generated_at=time.time())))
        self.old = cel.MISSING.path
        cel.MISSING.path, cel.MISSING.key = path, None
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), cel.handler("public"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        cel.MISSING.path, cel.MISSING.key = self.old, None
        self.tmp.cleanup()

    def test_api_missing_answers_before_the_engine_warms_up_and_checks_the_team(self):
        with urllib.request.urlopen(self.base + "/api/missing") as r:
            body = json.loads(r.read())
        self.assertEqual([e["card"] for e in body["matches"]], ["SAL-06", "MAL-08"])
        self.assertFalse(body["matches"][0]["action"]["live"])                  # nothing to check it against yet
        with urllib.request.urlopen(self.base + "/api/missing?team=t05") as r:
            self.assertEqual(json.loads(r.read())["matches"], [])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/missing?team=<script>")
        self.assertEqual(cm.exception.code, 400)

    def test_the_page_opens_with_the_open_bazaar(self):
        with urllib.request.urlopen(self.base + "/") as r:
            page = r.read().decode()
        self.assertIn("Open Bazaar · who needs which card", page)
        self.assertLess(page.index('id="missing"'), page.index('id="agents-url"'))
        self.assertLess(page.index('id="missing"'), page.index('id="wanted"'))

    def _publish_live(self, age=0.0, err=None):
        """A snapshot whose book still shows the named bid #20259, published `age` seconds ago."""
        snap = {"scope": "private", "tick": 1446, "cards": {"SAL-06": {"ref": "SAL-06", "offers": [
            {"id": 20259, "offer": 20259, "kind": "bid", "ref": "SAL-06", "price": 20, "venue": "rastro", "to": None,
             "want_ref": None, "expires_tick": 1505, "venue_name": "El Rastro", "team": "t09", "maker": "m",
             "how": "", "source": "listing", "verdict": None, "summary": None}]}},
            "matches": [], "demand": [], "teams": [], "market": {}}
        cel.publish(snap)
        cel.STATE.update(updated=time.time() - age, error=err)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.loads(r.read())

    def tearDown_state(self):
        cel.STATE.update(private=None, public=None, private_bytes=None, public_bytes=None, error=None, updated=0.0)

    def test_the_published_json_and_match_open_with_the_board(self):
        self._publish_live()
        try:
            body = self.get("/api/celestina.json")
            self.assertEqual(next(iter(body)), "missing")
            self.assertEqual([e["card"] for e in body["missing"]["matches"]], ["SAL-06", "MAL-08"])
            self.assertIn("cards", body)                                    # the rest of the public view follows
            live = body["missing"]["matches"][0]["action"]
            self.assertEqual((live["live"], live["call"]), (True, "POST https://bazaar.causaprima.ai/api/offers/20259/accept"))
            self.assertTrue(self.get("/api/match?team=t09")["missing"][0]["action"]["live"])
        finally:
            self.tearDown_state()

    def test_no_live_claim_outlives_its_snapshot(self):
        """Sol round 2, blocker 3: refreshes fail for 1,000 s: the board says nothing is live and gives no call."""
        for age, err in ((1000.0, None), (0.0, "Traceback: refresh failed")):
            self._publish_live(age, err)
            try:
                for path in ("/api/celestina.json", "/api/missing"):
                    body = self.get(path)
                    board = body["missing"] if "missing" in body else body
                    a = board["matches"][0]["action"]
                    self.assertEqual((a["live"], "call" in a, board["live_checked"]), (False, False, False), (path, age))
                a = self.get("/api/match?team=t09")["missing"][0]["action"]          # the agent route too
                self.assertEqual((a["live"], "call" in a), (False, False), age)
            finally:
                self.tearDown_state()


if __name__ == "__main__":
    unittest.main()


class PublicGuards(unittest.TestCase):
    """The public side never names a page card we lack and shows an inferred need only when confident (the same two
    guards as tools/announce.py). Mutation-first: each test fails without its guard in tools/celestina.py."""

    def test_the_default_threshold_is_the_announcers(self):
        import announce
        self.assertEqual(cel.MIN_P, announce.MIN_P_ANNOUNCE)

    def test_a_card_we_lack_never_appears_on_the_board(self):
        v = cel.missing_view(DOC, now=NOW, pub=PUB, exclude=frozenset({"MAL-08"}))
        self.assertEqual([e["card"] for e in v["matches"]], ["SAL-06"])
        swap = {"generated_at": NOW - 60, "matches": [
            m("t09", "SAL-06", tier=2, inferred=False, action=("swap", 9, "rastro", 0, "t09"))]}   # gives SAL-02
        self.assertEqual(cel.missing_view(swap, now=NOW, exclude=frozenset({"SAL-02"}))["matches"], [])
        self.assertEqual(len(cel.missing_view(swap, now=NOW)["matches"]), 1)

    def test_an_inferred_need_is_shown_only_when_confident(self):
        def board(p, consistent=None, **kw):
            x = m("t13", "MAL-08")
            x["p_missing"] = p
            doc = {"generated_at": NOW - 60, "matches": [x]}
            if consistent is not None:
                doc["teams"] = {"t13": {"consistent": consistent}}
            return [e["card"] for e in cel.missing_view(doc, now=NOW, **kw)["matches"]]
        self.assertEqual(board(0.77), [])
        self.assertEqual(board(0.77, min_p=0.7), ["MAL-08"])
        self.assertEqual(board(0.9), ["MAL-08"])
        self.assertEqual(board(None, min_p=0.0), [])
        self.assertEqual(board(0.95, consistent=False), [])
        self.assertEqual(board(0.95, consistent=True), ["MAL-08"])

    def test_live_wants_need_no_probability(self):
        v = cel.missing_view(DOC, now=NOW, pub=PUB, min_p=1.0)
        self.assertEqual([e["card"] for e in v["matches"]], ["SAL-06"])

    def test_the_public_view_drops_cards_we_lack_from_every_suggestion_but_keeps_the_books(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import test_celestina as tc
        snap = tc.snapshot()
        base = cel.public_view(snap)
        self.assertIn("LAV-09", [x["ref"] for x in base["matches"]])
        self.assertIn("LAV-05", [x["ref"] for x in base["our_book"]] + [x["ref"] for x in base["invitations"]])
        pub = cel.public_view(snap, exclude=frozenset({"LAV-09", "LAV-05", "LAV-02"}))
        self.assertEqual([x["ref"] for x in pub["matches"]], ["LAV-04"])        # LAV-01 swap wants LAV-02: gone too
        self.assertEqual((pub["our_book"], pub["invitations"]), ([], []))
        self.assertEqual([d["ref"] for d in pub["demand"]], ["LAV-04", "LAV-01"])
        self.assertEqual(sorted(pub["cards"]), sorted(base["cards"]))          # every venue's public book stays
        self.assertEqual(sorted(pub), sorted(base))                            # same keys for every reader


class PublicViewFailClosed(unittest.TestCase):
    def test_1_an_untrusted_exclusion_keeps_its_rule_in_the_public_view(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import matchmaker
        import test_celestina as tc
        pub = cel.public_view(tc.snapshot(), matchmaker.Exclusion((), allow=()))   # nothing positively non-page
        self.assertEqual((pub["matches"], pub["our_book"], pub["invitations"], pub["demand"]), ([], [], [], []))


class PublicExcludeFile(unittest.TestCase):
    CAT = {"sets": [{"id": "MAL", "released": True, "cards": [
        {"id": f"MAL-0{i}", "rarity": "common", "page": True} for i in range(1, 5)]}]}
    ALL = frozenset({"MAL-01", "MAL-02", "MAL-03", "MAL-04", "RET-01"})

    def account(self, d, tick=100, **extra):
        body = {"id": "t03", "tick": tick, "tick_seconds": 15, "assets": [{"id": 1, "kind": "card", "ref": "MAL-01"}]}
        body.update(extra)
        (Path(d) / "me.json").write_text(json.dumps(body))

    def test_a_trusted_snapshot_hides_exactly_the_cards_we_lack(self):
        ex = cel.PublicExclude()
        self.assertEqual((ex.refresh(self.CAT, 100), ex.suppress), (frozenset(), False))   # unconfigured: nothing
        with tempfile.TemporaryDirectory() as d:
            self.account(d)
            ex.configure([d], 60, ("RET-01",))
            self.assertTrue(ex.suppress)                                 # before the first refresh: closed
            with um.patch("sys.stderr"):
                self.assertEqual(ex.refresh(self.CAT, 110), frozenset({"MAL-02", "MAL-03", "MAL-04"}))
                self.assertFalse(ex.suppress)
                ex.refresh({"sets": []}, 120)                            # an incomplete catalog: closed again
                self.assertTrue(ex.suppress)

    def test_no_trusted_snapshot_fails_closed_never_to_the_built_in_list_alone(self):
        with tempfile.TemporaryDirectory() as d:
            self.account(d, tick_seconds="bad")
            cases = {"no flag": [], "no file": ["/nonexistent"], "malformed": [d]}
            for why, paths in cases.items():
                with self.subTest(why), um.patch("sys.stderr"):
                    ex = cel.PublicExclude()
                    ex.configure(paths, 60, ("RET-01",))
                    self.assertEqual(ex.refresh(self.CAT, 110), self.ALL)   # every page card, not RET-01 alone
                    self.assertTrue(ex.suppress)
            self.account(d)
            ex = cel.PublicExclude()
            ex.configure([d], 60, ("RET-01",))
            with um.patch("sys.stderr"):
                self.assertEqual(ex.refresh(self.CAT, 100 + 241), self.ALL)  # stale: 60.25 min of play
                self.assertTrue(ex.suppress)
                ex.refresh(None, 110)                     # an older tick never makes the snapshot young again
            self.assertTrue(ex.suppress)

    def test_4_the_served_exclusion_follows_a_newer_snapshot_without_an_engine_refresh(self):
        cat_ = {"sets": [{"id": "LAV", "released": True, "cards": [
            {"id": f"LAV-0{i}", "rarity": "common", "page": True} for i in range(1, 5)]}]}
        with tempfile.TemporaryDirectory() as d, um.patch("sys.stderr"):
            hold = lambda tick, refs: (Path(d) / "me.json").write_text(json.dumps(
                {"id": "t03", "tick": tick, "tick_seconds": 15,
                 "assets": [{"id": i, "kind": "card", "ref": r} for i, r in enumerate(refs, 1)]}))
            hold(100, ["LAV-01", "LAV-02"])
            ex = cel.PublicExclude()
            ex.configure([d], 60, ())
            ex.refresh(cat_, 100)
            self.assertNotIn("LAV-02", ex.current()[0])
            hold(101, ["LAV-01"])                                      # we sold LAV-02; the engine has not refreshed
            ex.checked = 0.0                                           # RECHECK_S elapsed
            cards, sup = ex.current()
            self.assertIn("LAV-02", cards)
            self.assertFalse(sup)

    def test_a_suppressed_board_lists_only_epic_and_legendary_wants_and_says_so(self):
        epic = m("t06", "SAL-12", tier=2, inferred=False, holders=())
        epic["rarity"] = "legendary"
        swap = m("t06", "LAV-12", tier=2, inferred=False, action=("swap", 9, "rastro", 0, "t06"))
        swap["rarity"] = "legendary"
        unknown = m("t06", "RET-12", tier=2, inferred=False, holders=())
        unknown["rarity"] = None
        doc = {"generated_at": NOW - 60, "matches": DOC["matches"] + [epic, swap, unknown]}
        open_ = cel.missing_view(doc, now=NOW, pub=PUB)
        self.assertNotIn("paused", open_["about"])
        closed = cel.missing_view(doc, now=NOW, pub=PUB, suppress_pages=True)
        self.assertEqual([e["card"] for e in closed["matches"]], ["SAL-12"])   # no page card, no swap, no unknown
        self.assertIn("Page-card matches (commons, uncommons, rares) are paused", closed["about"])
        self.assertEqual(sorted(closed), sorted(open_))                        # same keys

    def test_only_a_real_probability_passes(self):
        for bad in (float("nan"), True, 1.5, -0.1, "0.9"):
            x = m("t13", "MAL-08")
            x["p_missing"] = bad
            with self.subTest(bad=bad):
                self.assertEqual(cel.missing_view({"generated_at": NOW - 60, "matches": [x]}, now=NOW,
                                                  min_p=0.0)["matches"], [])
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            cel.min_p_arg("nan")


class GuardedRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "latest.json"
        path.write_text(json.dumps(dict(DOC, generated_at=time.time())))
        self.old = (cel.MISSING.path, cel.EXCLUDE.cards, cel.PUBLIC_MIN_P[0])
        cel.MISSING.path, cel.MISSING.key = path, None
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), cel.handler("public"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        cel.MISSING.path, cel.EXCLUDE.cards, cel.PUBLIC_MIN_P[0] = self.old
        cel.MISSING.key = None
        self.tmp.cleanup()

    def get(self):
        with urllib.request.urlopen(self.base + "/api/missing") as r:
            return [e["card"] for e in json.loads(r.read())["matches"]]

    def test_4_the_served_board_drops_a_card_we_no_longer_hold_at_once(self):
        cat_ = {"sets": [{"id": "MAL", "released": True, "cards": [
            {"id": f"MAL-0{i}", "rarity": "uncommon", "page": True} for i in range(1, 10)]},
            {"id": "SAL", "released": True, "cards": [
            {"id": f"SAL-0{i}", "rarity": "uncommon", "page": True} for i in range(1, 10)]}]}
        old = (cel.EXCLUDE.paths, cel.EXCLUDE.catalog, cel.EXCLUDE.tick, cel.EXCLUDE.checked, cel.EXCLUDE.suppress)
        with tempfile.TemporaryDirectory() as d, um.patch("sys.stderr"):
            hold = lambda tick, refs: (Path(d) / "me.json").write_text(json.dumps(
                {"id": "t03", "tick": tick, "tick_seconds": 15,
                 "assets": [{"id": i, "kind": "card", "ref": r} for i, r in enumerate(refs, 1)]}))
            try:
                hold(1445, ["MAL-08", "SAL-06"])
                cel.EXCLUDE.configure([d], 60, ())
                cel.EXCLUDE.refresh(cat_, 1445)
                self.assertEqual(self.get(), ["SAL-06", "MAL-08"])
                hold(1446, ["SAL-06"])                                 # a newer snapshot: MAL-08 is gone
                cel.EXCLUDE.checked = 0.0
                self.assertEqual(self.get(), ["SAL-06"])
            finally:
                cel.EXCLUDE.paths, cel.EXCLUDE.catalog, cel.EXCLUDE.tick, cel.EXCLUDE.checked, cel.EXCLUDE.suppress = old
                cel.EXCLUDE.cards = frozenset()

    def test_4_the_served_public_view_is_recut_when_holdings_change(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import test_celestina as tc
        private = tc.snapshot()
        saved = dict(cel.STATE)
        old = (cel.EXCLUDE.paths, cel.EXCLUDE.cards, cel.EXCLUDE.suppress)
        try:
            pub = cel.public_view(private, frozenset())
            cel.STATE.update(private=private, public=pub, public_bytes=json.dumps(pub).encode(),
                             pub_exclude=frozenset(), error=None, updated=time.time())
            with urllib.request.urlopen(self.base + "/api/celestina.json") as r:
                self.assertIn("LAV-09", [x["ref"] for x in json.loads(r.read())["matches"]])
            cel.EXCLUDE.cards = frozenset({"LAV-09"})          # holdings changed since the last engine refresh
            with urllib.request.urlopen(self.base + "/api/celestina.json") as r:
                self.assertNotIn("LAV-09", [x["ref"] for x in json.loads(r.read())["matches"]])
        finally:
            cel.STATE.clear()
            cel.STATE.update(saved)
            cel.EXCLUDE.paths, cel.EXCLUDE.cards, cel.EXCLUDE.suppress = old

    def test_the_served_board_is_paused_for_page_cards_while_untrusted(self):
        cel.EXCLUDE.suppress = True
        try:
            with urllib.request.urlopen(self.base + "/api/missing") as r:
                body = json.loads(r.read())
        finally:
            cel.EXCLUDE.suppress = False
        self.assertEqual(body["matches"], [])                  # SAL-06 and MAL-08 are uncommons: page cards
        self.assertIn("paused", body["about"])

    def test_the_served_board_applies_the_configured_exclusion_and_threshold(self):
        self.assertEqual(self.get(), ["SAL-06", "MAL-08"])
        cel.EXCLUDE.cards = frozenset({"SAL-06"})
        self.assertEqual(self.get(), ["MAL-08"])
        cel.PUBLIC_MIN_P[0] = 0.95
        self.assertEqual(self.get(), [])
