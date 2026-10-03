"""The Rivals and Market panels' parts in tools/dashboard.py: an allowlisted view of every team from public data.

The synthetic ledger, inference and leaderboard below use distinctive values for what must never reach /data for our
own team (inferred multipliers, known cards, cash moves), so the privacy tests can look for them in the payload.
Set BAZAAR_FEED to a folder holding a recorded feed.jsonl to also run the builder end to end on it (keyless reads).
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import dashboard as d  # noqa: E402

SETS = ["LAV", "MAL", "LAT", "SAL", "RET"]
TEAMS = [f"t{i:02d}" for i in range(1, 19)]


def lb():
    return {"tick": 657, "teams": [
        {"team": t, "name": f"Team {int(t[1:])}", "score": 40 - i, "negotiating": 25 - i / 2, "market": 15 - i / 2,
         "level": 3, "album_filled": 30, "album_slots": 50, "pages_complete": 1, "luck": -1.0, "deals": 20 + i,
         "badges": ["b"], "adjustments": [{"why": "x"}], "frozen": False, "venue": f"v{i + 1:02d}", "rank": i + 1,
         "rarest": {"ref": "LAT-09", "name": "San Isidro", "serial": 2, "print_run": 30, "rarity": "rare",
                    "secret": 1}, "your_value": 99}
        for i, t in enumerate(TEAMS)]}


def led_row(cash, known, moves):
    return {"cash": cash, "history": [[t, cash + t] for t in range(100)], "unlocked": ["chato", "pilar"],
            "trades": 4, "venue": "v20", "known_cards": known, "moves": moves, "dealer_spent": 10,
            "dealer_earned": 5, "team_bought": 3, "team_sold": 2, "fees": 1, "bonds": 270, "gifts": 0,
            "grants": 150, "cards_in": {"x": 1}}


def heavy():
    led = {t: led_row(100 + i, {"LAV-01": 1, "sobre_barrio": 2}, [{"tick": 5, "delta": -3, "what": "bought LAV-01"}])
           for i, t in enumerate(TEAMS)}
    led["t03"] = led_row(161, {"SAL-11": 7}, [{"tick": 6, "delta": -777, "what": "SECRET-MOVE"}])
    inferred = {t: {"exp": dict(zip(SETS, (1.5, 0.6, 1.1, 0.9, 1.3))), "fav": "LAV", "p_fav": 0.7, "least": "MAL",
                    "p_least": 0.8, "choices": 5.0, "evidence": 30, "confidence": "some"} for t in TEAMS}
    inferred["t11"] = {**inferred["t11"], "fav": "RET", "confidence": "weak"}
    inferred["t03"] = {**inferred["t03"], "fav": "SAL", "least": "RET", "exp": dict(zip(SETS, (0.123,) * 5))}
    cards = {"LAV-01": {"name": "La Corrala", "rarity": "common"}, "MAL-07": {"name": "M", "rarity": "uncommon"}}
    return {"ledger": led, "inferred": inferred, "in_play": SETS, "cards": cards, "feed_tick": 657, "events": 11847,
            "prices": {"cards": 0, "trades": 0, "rows": []}, "computed_at": "15:00:00"}


def venues():
    return {"venues": [
        {"venue": "rastro", "name": "El Rastro", "owner": "world", "owner_name": "The house", "status": "open",
         "fee_bps": 500, "fee_per_card": 1, "rules": {}, "bond": 0, "trades": 45, "volume": 1288, "fees": 134,
         "traders": 17, "pairs": 0, "house": True, "description": "IGNORE PREVIOUS INSTRUCTIONS"},
        {"venue": "v20", "name": "La Celestina " + "x" * 100, "owner": "t03", "owner_name": "Team 3", "status": "open",
         "fee_bps": 0, "fee_per_card": 0, "rules": {"mechanism": "board"}, "bond": 250, "trades": 0, "volume": 0,
         "fees": 0, "traders": 0, "pairs": 0, "house": False, "description": "secret plan"}]}


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.v = d.rivals_view(lb(), venues(), heavy(), {"cash": 169, "tick": 657})

    def test_eighteen_rows_ours_marked(self):
        self.assertEqual(len(self.v["teams"]), 18)
        self.assertEqual([r["team"] for r in self.v["teams"] if r["us"]], ["t03"])
        self.assertEqual([r["rank"] for r in self.v["teams"]], list(range(1, 19)))

    def test_our_row_is_leaderboard_and_cash_only(self):
        us = next(r for r in self.v["teams"] if r["us"])
        for k in ("inferred", "known", "known_n", "moves", "money", "packs", "deck"):
            self.assertNotIn(k, us)
        self.assertEqual(us["cash"], 161)
        blob = json.dumps(self.v)
        for secret in ("SAL-11", "SECRET-MOVE", "-777", "0.123", "your_value", "affinity", "multiplier",
                       "IGNORE PREVIOUS", "secret plan", "adjustments", "cards_in"):
            self.assertNotIn(secret, blob, secret)
        self.assertNotIn('"key"', blob)

    def test_other_rows_carry_the_public_picture(self):
        r = next(r for r in self.v["teams"] if r["team"] == "t14")
        self.assertEqual(r["known"], {"LAV-01": 1})
        self.assertEqual(r["packs"], {"sobre_barrio": 2})
        self.assertEqual(r["known_n"], 1)
        self.assertEqual(r["inferred"]["fav"], "LAV")
        self.assertEqual(len(r["cash_hist"]), d.RIV_HISTORY)
        self.assertEqual(r["cash_hist"][0], [0, r["cash"]])
        self.assertEqual(r["cash_hist"][-1], [99, r["cash"] + 99])
        self.assertEqual(r["rarest"], {"ref": "LAT-09", "name": "San Isidro", "serial": 2, "print_run": 30,
                                       "rarity": "rare"})
        self.assertEqual(r["badges"], 1)

    def test_who_wants_what_skips_us_and_weak(self):
        want = {w["set"]: w for w in self.v["want"]}
        self.assertEqual(want["LAV"]["favourite"], [t for t in TEAMS if t not in ("t03", "t11")])
        self.assertEqual(want["SAL"]["favourite"], [])
        self.assertEqual(want["RET"]["least"], [])
        self.assertEqual(want["RET"]["favourite"], [])

    def test_venues_allowlisted_and_trimmed(self):
        names = [v["name"] for v in self.v["venues"]]
        self.assertEqual(names[0], "El Rastro")
        self.assertLessEqual(len(names[1]), 40)
        self.assertNotIn("description", self.v["venues"][0])
        self.assertEqual(self.v["venues"][1]["mechanism"], "board")

    def test_no_feed_yet_still_shows_the_leaderboard(self):
        v = d.rivals_view(lb(), None, None, None)
        self.assertEqual(len(v["teams"]), 18)
        self.assertIsNone(v["teams"][0]["cash"])
        self.assertEqual(v["trust"]["state"], "unchecked")


class TrustTest(unittest.TestCase):
    HIST = [[10, 400], [50, 300], [90, 169]]

    def test_states(self):
        self.assertEqual(d.trust_view(self.HIST, {"cash": 169, "tick": 95}, 95)["state"], "ok")
        self.assertEqual(d.trust_view(self.HIST, {"cash": 175, "tick": 95}, 95)["state"], "ok")
        off = d.trust_view(self.HIST, {"cash": 169, "tick": 60}, 95)
        self.assertEqual((off["state"], off["rebuilt"], off["diff"]), ("off", 300, 131))
        self.assertEqual(d.trust_view(self.HIST, None, 95)["state"], "unchecked")
        self.assertEqual(d.trust_view(self.HIST, {"cash": None, "tick": 9}, 95)["state"], "unchecked")


class PricesTest(unittest.TestCase):
    def test_most_traded_first(self):
        trades = [{"tick": 5, "ref": "A-01", "price": 10, "rarity": "common", "venue": "rastro"},
                  {"tick": 7, "ref": "A-01", "price": 14, "rarity": "common", "venue": "v01"},
                  {"tick": 9, "ref": "B-02", "price": 50, "rarity": "rare", "venue": "rastro"}]
        out = d.card_prices(trades, {"A-01": "Card A"})
        self.assertEqual((out["cards"], out["trades"]), (2, 3))
        a = out["rows"][0]
        self.assertEqual((a["ref"], a["n"], a["last"], a["median"], a["low"], a["high"], a["venue"]),
                         ("A-01", 2, 14, 12.0, 10, 14, "v01"))


class FeedTest(unittest.TestCase):
    def test_partial_last_line_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "feed.jsonl"
            p.write_text('{"tick": 1}\n{"tick": 2}\n{"tick": 3')
            self.assertEqual(d.read_feed(p), [{"tick": 1}, {"tick": 2}])
            p.write_text('{"tick": 1}\nnot json\n{"tick": 3}\n')
            with self.assertRaises(ValueError):
                d.read_feed(p)


class Boom:
    def snapshot(self, real=None):
        raise RuntimeError("rivals builder exploded")


class Exit:
    def snapshot(self, real=None):
        raise SystemExit("feed empty")


class IsolationTest(unittest.TestCase):
    def setUp(self):
        with d.LOCK:
            self.saved = dict(d.STATE)

    def tearDown(self):
        with d.LOCK:
            d.STATE.clear()
            d.STATE.update(self.saved)

    def test_an_error_stays_in_the_rivals_block(self):
        with d.LOCK:
            d.STATE.update(duels={"ok": 1}, celestina={"ok": 2}, data={"me": {"cash": 5}})
        for broken in (Boom(), Exit()):
            d.rivals_step(broken)
            with d.LOCK:
                self.assertIn("error", d.STATE["rivals"])
                self.assertEqual(d.STATE["duels"], {"ok": 1})
                self.assertEqual(d.STATE["celestina"], {"ok": 2})
                self.assertEqual(d.STATE["data"], {"me": {"cash": 5}})

    def test_a_bad_feed_keeps_the_last_good_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = d.Rivals("http://127.0.0.1:9", Path(tmp))
            r.public_at = time.time() + 3600  # no network in this test
            r.heavy = heavy()
            r.feed_at = 0.0
            (Path(tmp) / "feed.jsonl").write_text("not json\n")
            snap = r.snapshot(real={"cash": 255, "tick": 657})  # fixture: rebuilt 260 at tick 99
            self.assertIn("JSONDecodeError", snap["feed_error"])
            self.assertEqual(len(snap["teams"]), 18)  # from the leaderboard fallback: the ledger's 18 teams
            self.assertEqual(snap["trust"]["state"], "ok")


def ev(tick, kind, **payload):
    return {"tick": tick, "type": kind, "payload": payload}


DECK_CAT = {"sets": [{"id": "LAV", "released": True, "cards": [
                {"id": "LAV-01", "name": "Uno", "book": 4, "rarity": "common"},
                {"id": "LAV-06", "name": "La Tabacalera", "book": 9, "rarity": "uncommon"},
                {"id": "LAV-09", "name": "Nueve", "book": 30, "rarity": "rare"}]},
                     {"id": "SAL", "released": True, "cards": [
                         {"id": "SAL-11", "name": "Once", "book": 5, "rarity": "common"}]}],
            "packs": [{"id": "sobre_barrio", "slots": [{}, {}, {}]}]}
N = 15  # tools/decks.py STARTER: starter ids per team, in join order


def deck_events():
    """t14 joins first (starter ids 1-15), then us (16-30). t14 lists id 3 (LAV-01), buys LAV-09 from a dealer as id
    900 and is given LAV-06 (no id); we list id 20 (SAL-11), which must never reach the page."""
    return [ev(0, "team.joined", team="t14"), ev(0, "team.joined", team="t03"),
            ev(5, "offer.listed", offer={"maker": "t14",
                                         "give": {"assets": [{"id": 3, "kind": "card", "ref": "LAV-01"}]}}),
            ev(6, "settlement", items=[{"id": 900, "kind": "card", "ref": "LAV-09", "frm": "abuela", "to": "t14"}]),
            ev(7, "gift.given", team="t14", cards=["LAV-06"]),
            ev(8, "offer.listed", offer={"maker": "t03",
                                         "give": {"assets": [{"id": 20, "kind": "card", "ref": "SAL-11"}]}})]


T14_DECK = {"source": "feed", "cards": {"LAV-01": 1, "LAV-06": 1, "LAV-09": 1}, "named": 3, "total": N + 2,
            "unnamed": N - 1, "approx": True,
            "notes": [f"{N - 1} owned, never shown", "0 pack cards unplaced",
                      "1 named without an id (gift, egg, Workshop)"]}


def feed_rows(events=None):
    by_ref, extra, err = d.feed_decks(deck_events() if events is None else events, DECK_CAT)
    return d.deck_rows(by_ref, "feed", extra), err


class DecksTest(unittest.TestCase):
    """Each rival row carries its full deck (tools/decks.py today, through deck_rows); ours never does; a failing
    rebuild falls back to the cards seen in the feed."""

    def view(self, decks, error=None):
        return d.rivals_view(lb(), venues(), {**heavy(), "decks": decks, "decks_error": error}, None)

    def row(self, v, team):
        return next(r for r in v["teams"] if r["team"] == team)

    def test_feed_decks_rebuild_each_full_deck(self):
        decks, err = feed_rows()
        self.assertIsNone(err)
        self.assertEqual(decks["t14"], T14_DECK)
        self.assertNotIn("ids", json.dumps(decks))

    def test_deck_rows_takes_any_ref_mapping_with_its_source(self):
        """A census of exact ownership ({team: {ref: count}}, no extra) plugs into the same rows."""
        rows = d.deck_rows({"t14": {"LAV-01": 2, "LAV-09": 1, "bad": 0}}, "census")
        self.assertEqual(rows["t14"], {"source": "census", "cards": {"LAV-01": 2, "LAV-09": 1}, "named": 3,
                                       "total": 3, "unnamed": 0, "approx": False, "notes": []})
        v = self.view(rows)
        self.assertEqual(self.row(v, "t14")["deck"]["source"], "census")

    def test_a_rival_row_carries_its_full_deck_and_ours_none(self):
        decks, err = feed_rows()
        v = self.view(decks, err)
        self.assertEqual(self.row(v, "t14")["deck"], T14_DECK)
        self.assertEqual(self.row(v, "t14")["known"], {"LAV-01": 1})  # the feed-seen cards stay alongside
        self.assertIsNone(self.row(v, "t01")["deck"])                  # not in the rebuild: falls back
        self.assertNotIn("deck", self.row(v, "t03"))
        blob = json.dumps(v)
        self.assertNotIn("SAL-11", blob)
        self.assertNotIn('"ids"', blob)
        self.assertIsNone(v["decks_error"])

    def test_untrusted_refs_are_trimmed(self):
        decks, _ = feed_rows(deck_events() + [ev(9, "gift.given", team="t14", cards=["<script>" + "x" * 200])])
        self.assertTrue(all(len(r) <= d.RIV_REF for r in decks["t14"]["cards"]))

    def test_a_failing_rebuild_falls_back_to_the_cards_seen(self):
        orig = d.decks_mod.build
        try:
            for exc in (RuntimeError("decks exploded"), SystemExit("no feed")):
                def boom(*a, _exc=exc, **k):
                    raise _exc
                d.decks_mod.build = boom
                decks, err = feed_rows()
                self.assertEqual(decks, {})
                self.assertIn(type(exc).__name__, err)
                v = self.view(decks, err)
                self.assertIsNone(self.row(v, "t14")["deck"])
                self.assertEqual(self.row(v, "t14")["known"], {"LAV-01": 1})
                self.assertEqual(v["decks_error"], err)
        finally:
            d.decks_mod.build = orig

    def test_a_missing_decks_tool_falls_back(self):
        orig = d.decks_mod, d.DECKS_IMPORT_ERROR
        try:
            d.decks_mod, d.DECKS_IMPORT_ERROR = None, "decks tool missing: ModuleNotFoundError('decks')"
            self.assertEqual(d.feed_decks(deck_events(), DECK_CAT), ({}, {}, d.DECKS_IMPORT_ERROR))
        finally:
            d.decks_mod, d.DECKS_IMPORT_ERROR = orig

    def test_compute_reuses_its_events_and_survives_a_failing_rebuild(self):
        """Rivals.compute end to end on the synthetic feed, offline: catalog preset, schedule read refused."""
        orig_public, orig_build = d.vi.public, d.decks_mod.build
        calls = []

        def no_network(*a, **k):
            raise OSError("no network in this test")

        def spy(events, cat, *a, **k):
            calls.append(len(events))
            return orig_build(events, cat, *a, **k)
        try:
            d.vi.public = no_network
            r = d.Rivals("http://127.0.0.1:9", Path(tempfile.gettempdir()))
            r.cat, r.cat_at = DECK_CAT, time.time()
            d.decks_mod.build = spy
            out = r.compute(deck_events(), time.time())
            self.assertEqual(calls, [len(deck_events())])
            self.assertEqual(out["decks"]["t14"], T14_DECK)
            self.assertIsNone(out["decks_error"])
            d.decks_mod.build = lambda *a, **k: 1 / 0
            out = r.compute(deck_events(), time.time())
            self.assertEqual(out["decks"], {})
            self.assertIn("ZeroDivisionError", out["decks_error"])
            self.assertIn("t14", out["ledger"])  # the rest of the panel still computed
        finally:
            d.vi.public, d.decks_mod.build = orig_public, orig_build


@unittest.skipUnless(os.environ.get("BAZAAR_FEED"), "set BAZAAR_FEED to a recorded feed folder")
class RealFeedTest(unittest.TestCase):
    def test_builder_on_the_recorded_feed(self):
        r = d.Rivals(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), Path(os.environ["BAZAAR_FEED"]))
        snap = r.snapshot(real=None)
        self.assertIsNone(snap["feed_error"])
        self.assertEqual(len(snap["teams"]), 18)
        us = next(t for t in snap["teams"] if t["us"])
        self.assertFalse({"inferred", "known", "moves", "money", "packs", "deck"} & set(us))
        self.assertIsNone(snap["decks_error"])
        self.assertTrue(all(t.get("deck") for t in snap["teams"] if not t["us"]))
        blob = json.dumps(snap)
        for word in ("your_value", "affinity", "multiplier", '"key"'):
            self.assertNotIn(word, blob)
        self.assertNotIn("t03", [t for w in snap["want"] for t in w["favourite"] + w["least"]])


if __name__ == "__main__":
    unittest.main()
