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
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import celestina as cel  # noqa: E402

NOW = 1_000_000.0


def m(team, card, tier=4, inferred=True, holders=(("t05", 890),), action=None, price=24):
    out = {"tier": tier, "inferred": inferred, "team": team, "team_name": f"Team {int(team[1:])}", "card": card,
           "card_name": "Name", "rarity": "uncommon", "set_name": "Malasaña", "p_missing": 0.77 if inferred else None,
           "holders": [{"team": t, "name": f"Team {int(t[1:])}", "copies": 2, "asset": a, "spare": True}
                       for t, a in holders],
           "dealers": [{"name": "Abuela"}], "price": price, "prices": {"fair": 16.5, "team_range": {"low": 15, "high": 20}},
           "action": None}
    if action:
        side, oid, venue, p, maker = action
        out["action"] = {"side": side, "offer": oid, "venue": venue, "price": p, "fee": 2, "expires_tick": 1505,
                         "maker": maker, "maker_name": f"Team {int(maker[1:])}", "who": [t for t, _ in holders],
                         "gives": "SAL-02" if side == "swap" else None}
    return out


DOC = {"generated_at": NOW - 60, "tick": 1445, "matches": [
    m("t09", "SAL-06", tier=1, inferred=False, holders=(("t05", 890),), action=("bid", 20259, "rastro", 20, "t09")),
    m("t13", "MAL-08"),
    m("t03", "LAV-09"),                                                              # Team 3 as buyer: never shown
    m("t14", "LAT-07", tier=3, holders=(("t06", 1133),), action=("ask", 20218, "rastro", 30, "t03")),  # our offer
]}
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
        v = cel.missing_view(DOC, now=NOW)
        self.assertEqual(v["name"], "Open Bazaar · who needs which card")
        self.assertEqual([(e["team"], e["card"]) for e in v["matches"]], [("t09", "SAL-06"), ("t13", "MAL-08")])
        live, inferred = v["matches"]
        self.assertEqual((live["need"], live["action"]["call"]),
                         ("live bid", "POST https://bazaar.causaprima.ai/api/offers/20259/accept"))
        self.assertEqual(inferred["need"], cel.INFERRED_NOTE)
        self.assertEqual(inferred["holder_count"], 1)
        self.assertEqual(inferred["orders"]["ask"]["give"], {"assets": ["<your MAL-08 asset id>"]})
        self.assertFalse(set(keys(v)) & set(BANNED))
        self.assertNotIn("890", json.dumps(v))                         # nobody else's asset id
        self.assertNotIn("t03", json.dumps(v))

    def test_a_team_sees_its_own_needs_and_what_it_holds_with_its_own_asset_id_only(self):
        v = cel.missing_view(DOC, team="t05", now=NOW)
        self.assertEqual([(e["card"], e["yours"], e["you_hold"]) for e in v["matches"]],
                         [("SAL-06", False, True), ("MAL-08", False, True)])
        self.assertEqual(v["matches"][1]["orders"]["your_ask"]["give"], {"assets": [890]})
        self.assertEqual(cel.missing_view(DOC, team="t13", now=NOW)["matches"][0]["yours"], True)
        self.assertNotIn("your_ask", cel.missing_view(DOC, team="t13", now=NOW)["matches"][0]["orders"])

    def test_a_stale_or_missing_file_is_an_empty_board(self):
        self.assertEqual(cel.missing_view(DOC, now=NOW + cel.MATCHES_MAX_AGE)["matches"], [])
        self.assertTrue(cel.missing_view({}, now=NOW)["stale"])
        self.assertEqual(cel.MissingBoard(Path("/nonexistent/latest.json")).load(), {})

    def test_text_lines_give_the_caller_the_one_call(self):
        v = {"missing": cel.missing_view(DOC, team="t05", now=NOW)["matches"]}
        lines = cel.bazaar_lines(v["missing"], cel.GAME)
        self.assertEqual(lines[0], 'OPEN BAZAAR: Team 9 bids 20 P for SAL-06 on El Rastro (offer 20259) and you hold a '
                                   'copy -> POST https://bazaar.causaprima.ai/api/offers/20259/accept '
                                   '{"assets":["<your SAL-06 asset id>"]}')
        self.assertIn("Team 13 appears to be missing MAL-08 (inferred) and you hold a copy; SELL MAL-08", lines[1])


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
        with urllib.request.urlopen(self.base + "/api/missing?team=t05") as r:
            body = json.loads(r.read())
        self.assertEqual([e["card"] for e in body["matches"]], ["SAL-06", "MAL-08"])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/missing?team=<script>")
        self.assertEqual(cm.exception.code, 400)

    def test_the_page_opens_with_the_open_bazaar(self):
        with urllib.request.urlopen(self.base + "/") as r:
            page = r.read().decode()
        self.assertIn("Open Bazaar · who needs which card", page)
        self.assertLess(page.index('id="missing"'), page.index('id="agents-url"'))
        self.assertLess(page.index('id="missing"'), page.index('id="wanted"'))

    def test_the_published_json_and_match_open_with_the_board(self):
        snap = {"scope": "private", "cards": {}, "matches": [], "demand": [], "teams": [], "market": {}}
        cel.publish(snap)
        try:
            self.assertEqual(next(iter(cel.STATE["public"])), "missing")
            self.assertEqual([e["card"] for e in cel.STATE["public"]["missing"]["matches"]], ["SAL-06", "MAL-08"])
        finally:
            cel.STATE.update(private=None, public=None, private_bytes=None, public_bytes=None)


if __name__ == "__main__":
    unittest.main()
