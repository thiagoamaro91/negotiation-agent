"""The team relay (keyless, allowlisted) and what the brain makes of its bundle. Run: python3 -m unittest discover tests"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import brain  # noqa: E402
import team_relay  # noqa: E402

SECRET = "tk-team3-secret-0000"
ME = {"id": "t03", "cash": 169, "tick": 630, "level": 3, "affinity": {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1},
      "starter_broker_key": "bk-should-never-leave", "venue": {"broker_key": "x"},
      "assets": [{"id": 41, "kind": "card", "ref": "LAV-01", "set": "LAV", "rarity": "common", "your_value": 4.0},
                 {"id": 42, "kind": "card", "ref": "LAV-01", "set": "LAV", "rarity": "common", "your_value": 4.0},
                 {"id": 7, "kind": "card", "ref": "SAL-01", "set": "SAL", "rarity": "common", "your_value": 13.0}]}


def key_machine(d: Path) -> tuple:
    """A fake key machine: a clone with the team key in .env, its state files, and the live view folder."""
    repo, live = d / "repo", d / "live"
    (repo / "logs" / "state").mkdir(parents=True)
    live.mkdir()
    (repo / ".env").write_text(f"BAZAAR_KEY={SECRET}\n")
    (repo / "logs" / "state" / "me.json").write_text(json.dumps(ME))
    (repo / "logs" / "score.jsonl").write_text(json.dumps({"tick": 630, "cash": 169}) + "\n")
    (repo / "logs" / "state" / "desk-broker.json").write_text(json.dumps(
        {"agent": "broker", "mode": "run", "tick": 1036, "epoch": 1000.0, "what": "same_book",
         "last_decision": {"tick": 1036, "matches": []}, "api_key": SECRET}))
    os.symlink(repo / ".env", repo / "logs" / "state" / "desk-market.json")  # a symlink to the key is never followed
    (live / "score.state.json").write_text(json.dumps({"keyed": 1.0, "prev": {"cash": 60, "tick": 1031, "rank": 5}}))
    (live / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"ts": "a", "tick": 900, "lane": "ladder", "action": "sell", "card": "MAL-07", "price": 19, "why": f"used {SECRET}"},
        {"ts": "b", "tick": None, "lane": "conductor", "action": "cancel", "card": "SAL-10", "price": 73, "why": "w"},
    ]) + "not json\n")
    return repo, live


class Relay(unittest.TestCase):
    def test_the_key_never_leaves_and_only_the_allowlist_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            repo, live = key_machine(Path(d))
            b = team_relay.collect(repo, live, now=5.0)
            body = team_relay.encode(b).decode()
            self.assertNotIn("team3-secret", body)
            self.assertNotIn("should-never-leave", body)
            self.assertNotIn("broker_key", body)
            self.assertEqual([x["_file"] for x in b["desks"]], ["logs/state/desk-broker.json"])  # the symlink is skipped
            self.assertNotIn("logs/state/desk-market.json", b["files"])
            self.assertEqual(b["me"]["cash"], 169)
            self.assertEqual(set(b["me"]), {"id", "cash", "tick", "level", "affinity", "assets"})
            self.assertEqual(b["score_state"]["prev"]["cash"], 60)
            self.assertEqual(len(b["decisions"]), 2)  # the broken line is skipped
            self.assertIn("[redacted]", b["decisions"][0]["why"])

    def test_safe_path_refuses_env_key_symlinks_and_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            repo, _ = key_machine(Path(d))
            self.assertIsNotNone(team_relay.safe_path(repo, "logs/state/me.json"))
            for bad in (".env", "logs/state/desk-market.json", "logs/state/api_key.json", "../repo/.env", "logs/state/missing.json"):
                self.assertIsNone(team_relay.safe_path(repo, bad), bad)

    def test_a_big_bundle_drops_the_oldest_decisions_first(self):
        b = {"kind": "team", "decisions": [{"i": i, "why": "x" * 500} for i in range(4000)]}
        body = team_relay.encode(b)
        self.assertLessEqual(len(body), team_relay.MAX_BYTES)
        kept = json.loads(body)["decisions"]
        self.assertEqual(kept[-1]["i"], 3999)
        self.assertGreater(kept[0]["i"], 0)


class TeamBundle(unittest.TestCase):
    def bundle(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            repo, live = key_machine(Path(d))
            b = json.loads(team_relay.encode(team_relay.collect(repo, live)))
        b.update(kw)
        return b

    def test_valid_team_scrubs_again_and_turns_desk_files_into_heartbeats(self):
        raw = {**self.bundle(), "extra_key": SECRET, "me": {**ME, "assets": []},
               "decisions": [{"tick": 1, "lane": "x", "why": f"read with {SECRET}", "broker_key": "bk-y"}]}
        t = brain.valid_team(raw, received=50.0)
        self.assertNotIn("team3-secret", json.dumps(t))
        self.assertNotIn("should-never-leave", json.dumps(t))
        self.assertNotIn("broker_key", json.dumps(t))
        self.assertEqual(t["received"], 50.0)
        self.assertEqual(t["me"]["cash"], 169)
        desk = t["desks"][0]
        self.assertEqual((desk["name"], desk["mode"], desk["tick"], desk["at"]), ("mini-broker", "live", 1036, 1000.0))

    def test_rejects_what_is_not_a_bundle_and_drops_a_bad_account(self):
        for bad in ([], "x", {"kind": "me"}, {**self.bundle(), "kind": None}):
            self.assertIsNone(brain.valid_team(bad), bad)
        self.assertIsNone(brain.valid_team(self.bundle(me={"cash": "a lot"}))["me"])


class DecisionsOnTheTape(unittest.TestCase):
    def test_tickless_rows_take_the_previous_tick_and_test_lanes_are_dropped(self):
        rows = brain.decision_rows([
            {"ts": "1", "tick": 0, "lane": "liveview-test", "action": "skip"},
            {"ts": "2", "tick": 900, "lane": "ladder", "action": "sell", "card": "MAL-07", "price": 19, "dealer": "pilar",
             "surplus": 1.5, "why": "w", "result": "deal"},
            {"ts": "3", "tick": None, "lane": "conductor", "action": "cancel", "card": "SAL-10", "price": 73},
        ])
        self.assertEqual([(r["tick"], r["lane"]) for r in rows], [(900, "ladder"), (900, "conductor")])
        self.assertEqual(rows[0]["text"], "sell MAL-07 at 19 P · pilar")
        self.assertEqual(rows[0]["surplus"], 1.5)
        self.assertTrue(all(r["ours"] and r["kind"] == "decision" for r in rows))

    def test_merge_keeps_tick_order_and_the_latest_decisions_even_when_older_than_the_market(self):
        market = [{"tick": t, "kind": "ask", "id": f"m{t}"} for t in range(1050, 950, -1)]
        decisions = [{"tick": t, "kind": "decision", "id": f"d{t}"} for t in range(700, 1000, 5)]
        out = brain.merge_tape(market, decisions)
        ticks = [r["tick"] for r in out]
        self.assertEqual(ticks, sorted(ticks, reverse=True))
        kept = [r["id"] for r in out if r["kind"] == "decision"]
        self.assertEqual(len(kept), brain.DECISIONS_ON_TAPE)
        self.assertIn("d995", kept)
        self.assertNotIn("d795", kept)


class Workshop(unittest.TestCase):
    """Codex review of #43 (0766808): burns of copies bought after the snapshot, and conversions leaving the relay's
    decision window, must not bring burned cards back."""
    CONVERT = {"tick": 953, "lane": "ladder", "action": "convert", "card": "LAV-06",
               "why": "burned spares LAV-01 #41, LAV-05 #499 (values 4+4)", "result": "got LAV-06 #1001 (second copy)"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (brain.vi.CONVERSIONS, brain.vi.ME, brain.vi.ME_LIVE)
        brain.vi.CONVERSIONS = Path(self.tmp.name) / "conversions.json"
        brain.vi.ME, brain.vi.ME_LIVE = Path(self.tmp.name) / "me.json", Path(self.tmp.name) / "me_live.json"

    def tearDown(self):
        brain.vi.CONVERSIONS, brain.vi.ME, brain.vi.ME_LIVE = self.saved
        self.tmp.cleanup()

    def us(self, frm_or_to, tick, aid, ref):
        side = {"frm": brain.vi.US, "to": "t09"} if frm_or_to == "sell" else {"frm": "abuela", "to": brain.vi.US}
        return {"tick": tick, "type": "settlement", "payload": {"items": [{"kind": "card", "id": aid, "ref": ref, **side}]}}

    def test_parses_burned_ids_and_the_card_got(self):
        self.assertEqual(brain.conversions([self.CONVERT, {**self.CONVERT, "action": "sell"}]),
                         [{"tick": 953, "card": "LAV-06", "burned": [41, 499], "got": [{"id": 1001, "ref": "LAV-06"}]}])

    def test_a_copy_bought_after_the_snapshot_then_burned_stays_gone(self):
        convert = {"tick": 953, "burned": [41, 499], "got": [{"id": 1001, "ref": "LAV-06"}]}
        events = [self.us("buy", 900, 499, "LAV-05"), self.us("sell", 961, 1001, "LAV-06")]
        mine = brain.vi.our_cards({**ME, "conversions": [convert]}, events)
        self.assertEqual((mine["LAV-01"], mine["LAV-05"], mine["LAV-06"], mine["SAL-01"]), (1, 0, 0, 1))
        no_burn = brain.vi.our_cards(ME, events)
        self.assertEqual((no_burn["LAV-01"], no_burn["LAV-05"]), (2, 1))

    def test_a_conversion_is_remembered_after_it_leaves_the_relay_window(self):
        brain.remember_conversions(brain.conversions([self.CONVERT]))
        brain.remember_conversions(brain.conversions([]))   # the decision has scrolled out of the relay's window
        brain.remember_conversions(brain.conversions([self.CONVERT]))   # and a duplicate is not kept twice
        brain.vi.ME.write_text(json.dumps(ME))
        me = brain.vi.load_me()
        self.assertEqual([c["tick"] for c in me["conversions"]], [953])
        self.assertEqual(brain.vi.our_cards(me, [])["LAV-01"], 1)

    def test_a_snapshot_after_the_conversion_already_includes_it(self):
        brain.remember_conversions(brain.conversions([self.CONVERT]))
        brain.vi.ME.write_text(json.dumps({**ME, "tick": 960}))
        self.assertNotIn("conversions", brain.vi.load_me())


class OurAccount(unittest.TestCase):
    def test_cash_checks_pages_and_copy_values(self):
        import collections
        led = {"t03": {"cash": 92, "history": [(600, 169), (844, 131), (961, 92)]}}
        team = {"received": time.time() - 10, "files": {},
                "score_state": {"prev": {"cash": 60, "tick": 1000, "rank": 5, "set_LAV": 10}},
                "score_rows": [{"tick": 620, "cash": 169}]}
        mine = collections.Counter({"LAV-01": 2, "LAV-09": 1, "SAL-01": 0})
        u = brain.our_account(ME, mine, led, team, {"LAV-01": 10, "LAV-09": 70, "SAL-01": 10},
                              {"LAV-01": "common", "LAV-09": "rare"}, [1.0, 0.25], ["LAV", "SAL"], last_tick=1040)
        self.assertEqual((u["cash"], u["cash_source"], u["cash_stale"], u["ledger_cash"]), (60, "live score at t1000", 40, 92))
        checks = {c["tick"]: c for c in u["checks"]}
        self.assertTrue(checks[620]["ok"] and checks[630]["ok"])
        self.assertEqual((checks[1000]["rebuilt"], checks[1000]["ok"]), (92, False))
        lav01 = next(c for c in u["cards"] if c["ref"] == "LAV-01")
        self.assertEqual(lav01["values"], [16.0, 4.0])
        self.assertNotIn("SAL-01", [c["ref"] for c in u["cards"]])  # a copy we no longer hold
        lav = next(p for p in u["pages"] if p["set"] == "LAV")
        self.assertEqual((lav["held"], lav["live"], len(lav["missing"])), (2, 10, 8))
        self.assertLess(u["relay"]["age_s"], 60)

    def test_without_the_relay_cash_comes_from_the_ledger(self):
        import collections
        u = brain.our_account(ME, collections.Counter(), {"t03": {"cash": 92, "history": []}}, None, {}, {}, [1.0],
                              [], last_tick=700)
        self.assertEqual((u["cash"], u["cash_source"], u["relay"]["age_s"]), (169, "account at t630", None))

    def test_the_freshest_reading_wins_and_an_agreeing_ledger_carries_it_forward(self):
        hist = [(0, 400), (150, 20)]
        old_score = {"tick": 100, "cash": 100}
        # Codex's case: a stale live-score file (t100, 100 P) must not beat the newer account (t200, 20 P)
        c = brain.choose_cash({"tick": 200, "cash": 20}, old_score, hist, 20, last_tick=200)
        self.assertEqual((c["cash"], c["cash_source"], c["cash_stale"]), (20, "account at t200", 0))
        c = brain.choose_cash({"tick": 200, "cash": 20}, old_score, hist, 20, last_tick=260)
        self.assertEqual((c["cash"], c["cash_tick"], c["cash_stale"]), (20, 260, 0))
        self.assertIn("ledger", c["cash_source"])
        c = brain.choose_cash({"tick": 200, "cash": 25}, old_score, hist, 20, last_tick=260)  # ledger disagrees
        self.assertEqual((c["cash"], c["cash_source"], c["cash_stale"]), (25, "account at t200", 60))
        self.assertEqual(brain.choose_cash({}, {}, hist, 20, last_tick=5)["cash_source"], "ledger")


class OurCards(unittest.TestCase):
    def test_gifts_and_eggs_after_the_snapshot_count_and_earlier_ones_do_not(self):
        us = brain.vi.US
        events = [{"tick": 600, "type": "gift.given", "payload": {"team": us, "cards": ["LAV-01"]}},
                  {"tick": 700, "type": "gift.given", "payload": {"team": us, "cards": ["SAL-03"]}},
                  {"tick": 701, "type": "egg.given", "payload": {"team": us, "cards": ["LAT-13"]}},
                  {"tick": 702, "type": "gift.given", "payload": {"team": "t09", "cards": ["SAL-03"]}},
                  {"tick": 703, "type": "settlement", "payload": {"items": [
                      {"kind": "card", "ref": "LAV-01", "frm": us, "to": "t09"}]}}]
        mine = brain.vi.our_cards(ME, events)
        self.assertEqual((mine["LAV-01"], mine["SAL-03"], mine["LAT-13"], mine["SAL-01"]), (1, 1, 1, 1))


class InferenceVsTruth(unittest.TestCase):
    def model(self):
        sets = ["LAV", "MAL", "LAT", "SAL", "RET", "CHA"]
        return brain.vi.Model(sets, sets[:5], {"LAV-01": 10})

    def test_evidence_for_the_true_favourite_beats_the_prior(self):
        truth = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7, "CHA": 0.5}
        evs = [{"tick": t, "kind": "choose", "set": s, "ref": f"{s}-01"} for t, s in
               enumerate(["LAV", "LAV", "SAL", "LAV", "SAL", "LAT", "LAV"], start=10)]
        brain.TRUTH_CACHE.clear()
        out = brain.inference_vs_truth(self.model(), evs, truth)
        self.assertEqual(out["prior"]["pairs"], 0.5)  # a uniform prior orders nothing: every pair is a coin flip
        self.assertGreater(out["now"]["pairs"], 0.8)
        self.assertGreater(out["now"]["p_fav"], out["prior"]["p_fav"])
        self.assertLess(out["now"]["mae"], out["prior"]["mae"])
        self.assertTrue(out["now"]["fav_ok"])
        self.assertEqual(out["sets"][0], {**out["sets"][0], "set": "LAV", "true": 1.6, "rank_true": 1, "rank_inferred": 1})
        self.assertEqual([p["n"] for p in out["curve"]], list(range(1, 8)))
        self.assertNotIn("CHA", [r["set"] for r in out["sets"]])  # not in play

    def test_evidence_against_the_truth_shows_up_as_error(self):
        truth = {"LAV": 1.6, "SAL": 1.3, "LAT": 1.1, "RET": 0.9, "MAL": 0.7}
        evs = [{"tick": t, "kind": "choose", "set": "MAL", "ref": "MAL-01"} for t in range(10, 16)]
        brain.TRUTH_CACHE.clear()
        out = brain.inference_vs_truth(self.model(), evs, truth)
        self.assertFalse(out["now"]["fav_ok"])
        self.assertGreater(out["now"]["mae"], out["prior"]["mae"])

    def test_needs_two_known_sets(self):
        self.assertIsNone(brain.inference_vs_truth(self.model(), [], {"LAV": 1.6}))


class TeamEndpoint(unittest.TestCase):
    READ, WRITE = "read-team-test", "write-team-test"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (brain.OUT, brain.DESK_FILE, brain.vi.ME_LIVE, brain.TEAM_LIVE, dict(brain.DESKS))
        brain.OUT = Path(cls.tmp.name)
        brain.DESK_FILE = brain.OUT / "desks.json"
        brain.vi.ME_LIVE = brain.OUT / "me_live.json"
        brain.TEAM_LIVE = brain.OUT / "team_live.json"
        brain.DESKS.clear()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        threading.Thread(target=brain.serve, args=(cls.port, "127.0.0.1", cls.READ, cls.WRITE), daemon=True).start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        brain.OUT, brain.DESK_FILE, brain.vi.ME_LIVE, brain.TEAM_LIVE = cls.saved[:4]
        brain.DESKS.clear()
        brain.DESKS.update(cls.saved[4])
        cls.tmp.cleanup()

    def post(self, body: bytes, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/ingest/team", data=body, method="POST",
                                     headers={"X-Brain-Write": token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_needs_the_write_token_and_stores_a_scrubbed_bundle(self):
        brain.vi.ME_LIVE.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as d:
            repo, live = key_machine(Path(d))
            body = team_relay.encode(team_relay.collect(repo, live))
        self.assertEqual(self.post(body), 403)
        self.assertEqual(self.post(body, token=self.READ), 403)
        self.assertEqual(self.post(b"{not json", token=self.WRITE), 400)
        self.assertEqual(self.post(json.dumps({"kind": "other"}).encode(), token=self.WRITE), 400)
        self.assertEqual(self.post(body, token=self.WRITE), 200)
        stored = brain.TEAM_LIVE.read_text()
        self.assertNotIn("team3-secret", stored)
        self.assertEqual(json.loads(stored)["score_state"]["prev"]["cash"], 60)
        me = json.loads(brain.vi.ME_LIVE.read_text())
        self.assertEqual((me["tick"], me["source"]), (630, "team relay"))
        self.assertIn("mini-broker", brain.DESKS)

    def test_a_fresher_relayed_account_is_never_overwritten_by_an_older_bundle(self):
        brain.vi.ME_LIVE.write_text(json.dumps({**ME, "tick": 2000, "cash": 1}))
        with tempfile.TemporaryDirectory() as d:
            repo, live = key_machine(Path(d))
            self.assertEqual(self.post(team_relay.encode(team_relay.collect(repo, live)), token=self.WRITE), 200)
        self.assertEqual(json.loads(brain.vi.ME_LIVE.read_text())["tick"], 2000)

    def test_an_oversized_bundle_is_refused_before_its_body_is_read(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall((f"POST /ingest/team HTTP/1.1\r\nHost: x\r\nX-Brain-Write: {self.WRITE}\r\n"
                       f"Content-Length: {brain.TEAM_MAX_BYTES + 1}\r\n\r\n").encode())
            self.assertIn(b" 413 ", s.recv(200))


if __name__ == "__main__":
    unittest.main()
