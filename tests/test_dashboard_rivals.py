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
        for k in ("inferred", "known", "known_n", "moves", "money", "packs"):
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


@unittest.skipUnless(os.environ.get("BAZAAR_FEED"), "set BAZAAR_FEED to a recorded feed folder")
class RealFeedTest(unittest.TestCase):
    def test_builder_on_the_recorded_feed(self):
        r = d.Rivals(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), Path(os.environ["BAZAAR_FEED"]))
        snap = r.snapshot(real=None)
        self.assertIsNone(snap["feed_error"])
        self.assertEqual(len(snap["teams"]), 18)
        us = next(t for t in snap["teams"] if t["us"])
        self.assertFalse({"inferred", "known", "moves", "money", "packs"} & set(us))
        blob = json.dumps(snap)
        for word in ("your_value", "affinity", "multiplier", '"key"'):
            self.assertNotIn(word, blob)
        self.assertNotIn("t03", [t for w in snap["want"] for t in w["favourite"] + w["least"]])


if __name__ == "__main__":
    unittest.main()
