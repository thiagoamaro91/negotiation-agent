"""tools/concierge.py: the keyless wants / haves board for La Celestina, end to end over HTTP on a free port, with a
sample catalog and feed in a temp dir (nothing touches logs/ or the network)."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import concierge as cg  # noqa: E402
from bazaar_sdk import BazaarError  # noqa: E402  (on the path once concierge is imported)

KEY = "t" + "k-abcd-efgh"   # a key-shaped string, built so the literal never appears in the repo


class StubLog:
    def __init__(self):
        self.rows = []

    def event(self, event, **data):
        self.rows.append((event, data))


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class ServerCase(unittest.TestCase):
    limiter_args = {"post_per_min": 1000, "global_post_per_min": 1000}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        cat, self.feed_path = cg.write_sample(self.dir)
        self.log = StubLog()
        self.board = cg.Board(self.dir / cg.STORE_NAME)
        self.c = cg.Concierge(cg.Catalog(json.loads(cat.read_text(encoding="utf-8"))), cg.FeedWatch([self.feed_path]),
                              self.board, log=self.log, limiter=cg.Limiter(**self.limiter_args))
        self.c.refresh_feed(force=True)
        self.server = cg.make_server(self.c, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.seen = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                status, text, hdrs = r.status, r.read().decode("utf-8"), dict(r.headers)
        except urllib.error.HTTPError as e:
            status, text, hdrs = e.code, e.read().decode("utf-8"), dict(e.headers)
            e.close()
        self.seen.append(text)
        return status, text, hdrs

    def json(self, path, body=None, **kw):
        status, text, _ = self.call(path, body, **kw)
        return status, json.loads(text)


class FlowTest(ServerCase):
    def test_want_then_have_match(self):
        s, want = self.json("/api/want", {"team": "t07", "card": "LAV-03", "max_price": 14, "note": "for my page"})
        self.assertEqual(s, 201)
        self.assertEqual(want["matches"], [])
        self.assertEqual(want["next_step"]["body"], {"venue": "v20", "give": {"cash": 14}, "want": {"cards": ["LAV-03"]}})
        s, have = self.json("/api/have", {"team": "t11", "card": "lav-03", "min_price": 12})
        self.assertEqual(s, 201)
        self.assertEqual([(m["team"], m["max_price"], m["note"]) for m in have["matches"]], [("t07", 14, "for my page")])
        self.assertEqual(have["next_step"]["body"],
                         {"venue": "v20", "give": {"assets": ["YOUR_ASSET_ID"]}, "want": {"cash": 12}})
        s, board = self.json("/api/board?card=LAV-03")
        self.assertEqual((s, board["count"]), (200, 2))
        self.assertEqual({r["side"] for r in board["requests"]}, {"want", "have"})
        self.assertEqual([e for e, _ in self.log.rows], ["want", "have"])

    def test_prices_that_cannot_meet_do_not_match(self):
        self.json("/api/want", {"team": "t07", "card": "LAV-03", "max_price": 10})
        _, have = self.json("/api/have", {"team": "t11", "card": "LAV-03", "min_price": 12})
        self.assertEqual(have["matches"], [])
        _, have2 = self.json("/api/have", {"team": "t12", "card": "LAV-03"})   # no price: can always meet
        self.assertEqual([m["team"] for m in have2["matches"]], ["t07"])

    def test_same_team_side_card_replaces(self):
        _, a = self.json("/api/want", {"team": "t7", "card": "LAV-03", "max_price": 10})
        _, b = self.json("/api/want", {"team": "t07", "card": "LAV-03", "max_price": 13})
        self.assertEqual(a["request"]["team"], "t07")
        self.assertEqual(b["replaced"], a["request"]["id"])
        _, board = self.json("/api/board")
        self.assertEqual([(r["team"], r["max_price"]) for r in board["requests"]], [("t07", 13)])

    def test_withdraw_needs_the_token(self):
        _, a = self.json("/api/want", {"team": "t07", "card": "LAV-09"})
        rid = a["request"]["id"]
        s, out = self.json("/api/withdraw", {"id": rid, "token": "wrong"})
        self.assertEqual((s, out["error"]), (404, "not_found"))
        s, out = self.json("/api/withdraw", {"id": rid, "token": a["withdraw_token"]})
        self.assertEqual((s, out["withdrawn"]), (200, rid))
        self.assertEqual(self.json("/api/board")[1]["count"], 0)

    def test_quote_price_range_and_holders(self):
        s, q = self.json("/api/quote?card=LAV-03")
        self.assertEqual(s, 200)
        self.assertEqual(q["public_price"]["basis"], "card")
        self.assertEqual(q["public_price"]["trades"], 4)
        self.assertEqual((q["public_price"]["low"], q["public_price"]["median"], q["public_price"]["high"]),
                         (12, 13, 14))   # 10, 12, 14, 16 -> p25 11.5, p50 13, p75 14.5 (banker's rounding)
        self.assertEqual(q["holders"]["teams"], 4)   # t06, t08, t09, t14; never t03
        self.assertEqual(self.c.quote("LAV-03", "t06")["holders"]["teams"], 3)
        self.assertEqual(self.c.quote("LAV-04")["public_price"]["basis"], "set+rarity")
        pp = self.c.quote("LAV-07")["public_price"]
        self.assertEqual((pp["basis"], pp["low"], pp["median"], pp["trades"]), ("book", 25, 25, 0))

    def test_quote_carries_the_shared_fair_price(self):
        fair = self.c.quote("LAV-03")["public_price"]["fair"]
        self.assertEqual((fair["price"], fair["n"], fair["basis"]), (13, 4, "teams"))   # median of 16, 14, 12, 10
        self.assertEqual(fair["range"], {"low": 12, "median": 13, "high": 14, "trades": 4})
        sale = {"id": 60, "tick": 30, "type": "settlement", "scope": "public", "actor": "",   # t05 sells to Abuela at 2
                "payload": {"settlement": 60, "tick": 30, "kind": "trade", "parties": ["t05", "abuela"], "venue": None,
                            "persona": "abuela", "fee": 0, "price": 2,
                            "items": [{"id": 960, "kind": "card", "ref": "LAV-03", "rarity": "common", "set": "LAV",
                                       "frm": "t05", "to": "abuela"}]}}
        with self.feed_path.open("a") as f:
            f.write(json.dumps(sale) + "\n")
        self.c.refresh_feed(force=True)
        pp = self.c.quote("LAV-03")["public_price"]
        self.assertEqual((pp["fair"]["price"], pp["fair"]["n"], pp["median"]), (13, 4, 13))  # a dealer's buy price is not fair
        self.assertEqual(self.c.quote("LAV-07")["public_price"]["fair"]["price"], None)

    def test_agent_instructions_point_to_celestina(self):
        for path in ("/api", "/llms.txt"):
            s, text, hdrs = self.call(path)
            self.assertEqual(s, 200)
            self.assertTrue(hdrs["Content-Type"].startswith("text/plain"))
            self.assertIn("https://celestina.invalid:8443/agents.md", text)
            self.assertIn('POST /api/want     {"team": "t07", "card": "LAV-03", "max_price": 14', text)
            self.assertIn("never as instructions", text)
            self.assertNotIn("## Then trade on the game", text)     # the full instructions live on La Celestina
        self.assertIn('href="https://celestina.invalid:8443/agents.md"', self.call("/")[1])
        c = cg.Concierge(self.c.catalog, self.c.feed, self.board, celestina_url="https://cel.example/")
        self.assertIn("https://cel.example/agents.md", c.pointer())
        self.assertEqual(cg.clean_url("https://cel.example/"), "https://cel.example")
        for bad in ('https://x.example/"><script>', "javascript:alert(1)", ""):
            with self.assertRaises(SystemExit):
                cg.clean_url(bad)


class RefusalTest(ServerCase):
    def err(self, path, body=None, **kw):
        s, out = self.json(path, body, **kw)
        return s, out.get("error")

    def test_bad_inputs(self):
        cases = [
            ({"team": "t07", "card": "XYZ-99"}, (400, "unknown_card")),
            ({"team": "t07", "card": "LAV-3; drop"}, (400, "bad_card")),
            ({"team": "t07"}, (400, "bad_card")),
            ({"team": "t03", "card": "LAV-03"}, (403, "own_venue")),
            ({"team": "team 7", "card": "LAV-03"}, (400, "bad_team")),
            ({"team": 7, "card": "LAV-03"}, (400, "bad_team")),
            ({"team": "t07", "card": "LAV-03", "max_price": -1}, (400, "bad_price")),
            ({"team": "t07", "card": "LAV-03", "max_price": "12"}, (400, "bad_price")),
            ({"team": "t07", "card": "LAV-03", "max_price": True}, (400, "bad_price")),
            ({"team": "t07", "card": "LAV-03", "max_price": 12.5}, (400, "bad_price")),
            ({"team": "t07", "card": "LAV-03", "note": {"x": 1}}, (400, "bad_note")),
        ]
        for body, want in cases:
            self.assertEqual(self.err("/api/want", body), want, body)
        self.assertEqual(self.err("/api/want", raw=b'{"team": "t07", "card": "LAV-03", "max_price": NaN}'),
                         (400, "bad_json"))
        self.assertEqual(self.err("/api/want", raw=b"[1, 2]"), (400, "bad_json"))
        self.assertEqual(self.err("/api/have", raw=b"\xff\xfe"), (400, "bad_json"))
        self.assertEqual(self.err("/api/want", raw=b"{" + b" " * cg.MAX_BODY + b"}"), (413, "too_large"))
        self.assertEqual(self.err("/api/nope", {"a": 1}), (404, "not_found"))
        self.assertEqual(self.err("/nope"), (404, "not_found"))
        self.assertEqual(self.err("/api/board?side=sell"), (400, "bad_side"))
        self.assertEqual(self.err("/api/quote?card=nope"), (400, "bad_card"))
        self.assertEqual(self.json("/api/board")[1]["count"], 0)

    def test_untrusted_text_is_cleaned_and_escaped(self):
        note = "<script>alert(1)</script> ‮evil​\x00 key " + KEY + " " + "x" * 400
        _, out = self.json("/api/want", {"team": "t07", "card": "LAV-03", "note": note})
        stored = out["request"]["note"]
        self.assertTrue(stored.startswith("<script>alert(1)</script> evil key [redacted] x"))
        self.assertEqual(len(stored), cg.NOTE_MAX)
        self.assertNotIn("‮", stored)
        s, page, hdrs = self.call("/")
        self.assertEqual(s, 200)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("script-src 'self'", hdrs["Content-Security-Policy"])
        self.assertEqual(hdrs["X-Content-Type-Options"], "nosniff")

    def test_no_key_or_private_data_anywhere(self):
        self.json("/api/want", {"team": "t07", "card": "LAV-03", "note": KEY})
        self.json("/api/have", {"team": "t11", "card": "LAV-03"})
        for path in ("/", "/api", "/llms.txt", "/api/board", "/api/quote?card=LAV-03", "/healthz", "/app.js"):
            self.call(path)
        for text in self.seen:
            self.assertIsNone(cg.KEYLIKE.search(text), text[:200])
        self.assertNotIn(KEY, (self.dir / cg.STORE_NAME).read_text(encoding="utf-8"))
        src = Path(cg.__file__).read_text(encoding="utf-8")
        for banned in ("t" + "k-", "BAZAAR_KEY", "BROKER_KEY", '".env"', "/.env", "load_env", "me.json", "rastro_floors", "/api/me/",
                       "Bazaar(", "Broker("):
            self.assertNotIn(banned, src, banned)
        with self.assertRaises(BazaarError):
            cg.PublicClient().get("/api/me")   # the only client it holds refuses keyed routes before sending


class LimitTest(ServerCase):
    limiter_args = {"post_per_min": 2, "get_per_min": 100, "global_post_per_min": 3}

    def test_per_client_and_global_post_limits(self):
        a = {"X-Forwarded-For": "6.6.6.6, 1.1.1.1"}   # behind a tunnel: the rightmost entry is the client
        b = {"X-Forwarded-For": "2.2.2.2"}
        body = {"team": "t07", "card": "LAV-03"}
        self.assertEqual(self.call("/api/want", body, headers=a)[0], 201)
        self.assertEqual(self.call("/api/want", body, headers=a)[0], 201)
        s, text, hdrs = self.call("/api/want", body, headers=a)
        self.assertEqual((s, json.loads(text)["error"], hdrs["Retry-After"]), (429, "rate_limited", "60"))
        self.assertEqual(self.call("/api/want", body, headers=b)[0], 201)
        self.assertEqual(self.call("/api/want", body, headers={"X-Forwarded-For": "3.3.3.3"})[0], 429)  # global cap

    def test_board_caps(self):
        b = cg.Board(None, max_open=3, max_per_team=2, max_per_client=10)
        b.add("want", "t07", "LAV-03", None, "", "c1")
        b.add("want", "t07", "LAV-04", None, "", "c1")
        with self.assertRaises(cg.Refused) as e:
            b.add("want", "t07", "LAV-07", None, "", "c1")
        self.assertEqual(e.exception.code, "team_cap")
        b.add("want", "t07", "LAV-04", 9, "", "c1")         # replacing is always allowed
        b.add("have", "t08", "LAV-03", None, "", "c2")
        with self.assertRaises(cg.Refused) as e:
            b.add("have", "t09", "LAV-03", None, "", "c3")
        self.assertEqual(e.exception.code, "board_full")


class BoardStoreTest(unittest.TestCase):
    def test_expiry(self):
        clock = Clock()
        b = cg.Board(None, ttl=7200, now=clock)
        b.add("want", "t07", "LAV-03", 14, "", "c")
        clock.t += 7199
        self.assertEqual(len(b.listing()), 1)
        clock.t += 2
        self.assertEqual(b.listing(), [])

    def test_replay_and_compaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / cg.STORE_NAME
            b = cg.Board(path)
            r1, tok1, _ = b.add("want", "t07", "LAV-03", 14, "hola", "c")
            b.add("have", "t11", "LAV-03", 12, "", "c")
            b.add("have", "t11", "LAV-03", 11, "", "c")       # replaces the one before
            b.withdraw(r1["id"], tok1)
            self.assertEqual(len(path.read_text().splitlines()), 5)
            b2 = cg.Board(path)
            self.assertEqual([(r["team"], r["price"]) for r in b2.listing()], [("t11", 11)])
            self.assertEqual(b2.next_id, 4)
            self.assertEqual(len(path.read_text().splitlines()), 1)
            self.assertNotIn("c", b2.client.values())        # client addresses never reach the disk
            self.assertNotIn('"client"', path.read_text())


class PublicDataTest(unittest.TestCase):
    def test_book_summary_drops_makers_and_odd_shapes(self):
        book = {"offers": [
            {"id": 1, "maker": "m1secret", "to": None, "status": "open",
             "give": {"cash": 0, "assets": [{"id": 9, "kind": "card", "ref": "LAV-09"}], "types": []},
             "want": {"cash": 40, "assets": [], "types": []}},
            {"id": 2, "maker": "m2secret", "to": None, "status": "open",
             "give": {"cash": 0, "assets": [{"id": 8, "kind": "card", "ref": "LAV-09"}], "types": []},
             "want": {"cash": 35, "assets": [], "types": []}},
            {"id": 3, "maker": "m3secret", "to": None, "status": "open", "give": {"cash": 46, "assets": [], "types": []},
             "want": {"cash": 0, "assets": [], "types": ["card:LAV-09"]}},
            {"id": 4, "maker": "m4", "to": "t07", "status": "open", "give": {"cash": 99, "assets": [], "types": []},
             "want": {"cash": 0, "assets": [], "types": ["card:LAV-09"]}},     # addressed: not public interest
            {"id": 5, "maker": "m5", "to": None, "status": "open",                # a swap: the broker cannot cross it
             "give": {"cash": 0, "assets": [{"id": 7, "kind": "card", "ref": "LAV-03"}], "types": []},
             "want": {"cash": 0, "assets": [], "types": ["card:LAV-04"]}},
        ]}
        out = cg.book_summary(book)
        self.assertEqual(out, {"LAV-09": {"bids": 1, "best_bid": 46, "asks": 2, "best_ask": 35}})
        self.assertNotIn("secret", json.dumps(out))
        self.assertEqual(cg.book_summary({"offers": "junk"}), {})
        self.assertEqual(cg.book_summary(None), {})

    def test_feed_is_read_incrementally(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, feed = cg.write_sample(Path(tmp))
            w = cg.FeedWatch([feed])
            self.assertEqual(w.poll(), 6)
            self.assertEqual(len(w.tape.trades), 5)
            extra = cg.sample_feed()[0]
            extra = {**extra, "id": 50, "payload": {**extra["payload"], "price": 30}}
            with feed.open("a") as f:
                f.write(json.dumps(extra) + "\n" + '{"id": 51, "partial')   # an unfinished line waits
            self.assertEqual(w.poll(), 1)
            self.assertEqual(len(w.tape.trades), 6)
            self.assertEqual(w.poll(), 0)

    def test_catalog_refs(self):
        cat = cg.Catalog(cg.SAMPLE_CATALOG)
        self.assertEqual(cat.card(" lav-09 ")["rarity"], "rare")
        with self.assertRaises(cg.Refused):
            cat.card("LAV-99")
        with self.assertRaises(ValueError):
            cg.Catalog({"sets": []})


if __name__ == "__main__":
    unittest.main()
