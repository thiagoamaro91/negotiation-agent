"""Open Bazaar outreach (tools/outreach.py): who is told, what they are told, one thread at a time, closed at once.
Offline: no key, no network. Run: python3 -m unittest discover tests"""
import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
import unittest.mock as um
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "kit"))
import outreach as out  # noqa: E402
from bazaar_sdk import BazaarError  # noqa: E402


def m(team, card, tier, action=None, who=(), price=24):
    x = {"tier": tier, "inferred": tier >= 3, "p_missing": 0.9 if tier >= 3 else None, "team": team, "team_name": f"Team {int(team[1:])}", "card": card,
         "card_name": None, "set_name": "Malasaña", "action": None,
         "proposal": {"buyer": {"post": {"venue": "v20", "give": {"cash": price}, "want": {"cards": [card]},
                                         "expires_in_ticks": 240}}} if tier == 4 else None}
    if action:
        side, oid, venue, p, maker = action
        x["action"] = {"side": side, "offer": oid, "venue": venue, "price": p, "maker": maker,
                       "maker_name": f"Team {int(maker[1:])}", "expires_tick": 1505, "who": list(who),
                       "gives": "SAL-02" if side == "swap" else None}
    return x


DOC = {"generated_at": 0, "tick": 1445, "matches": [
    m("t09", "SAL-06", 1, ("bid", 20259, "rastro", 20, "t09"), who=("t05", "t07")),
    m("t06", "SAL-12", 2, ("bid", 20162, "rastro", 450, "t06")),
    m("t14", "LAT-07", 3, ("ask", 20218, "rastro", 30, "t06"), who=("t14",)),
    m("t13", "MAL-08", 4),
    m("t03", "LAV-09", 4),
    m("t05", "MAL-01", 4),
]}


class Who(unittest.TestCase):
    def test_the_one_team_that_can_act(self):
        r = [out.recipient(x) for x in DOC["matches"]]
        self.assertEqual(r, ["t05", None, "t14", "t13", None, "t05"])

    def test_one_message_per_team_never_twice_never_team_3_never_excluded(self):
        t = out.targets(DOC, {}, "d", 10)
        self.assertEqual([(to, x["card"]) for to, x, _ in t], [("t05", "SAL-06"), ("t14", "LAT-07"), ("t13", "MAL-08")])
        state = {"teams": {"d": ["t05"]}, "keys": ["t14:LAT-07:20218"]}
        self.assertEqual([to for to, _, _ in out.targets(DOC, state, "d", 10)], ["t13"])
        self.assertEqual([to for to, _, _ in out.targets(DOC, {}, "d", 10, exclude=("SAL-06",))], ["t14", "t13", "t05"])
        self.assertEqual(len(out.targets(DOC, {}, "d", 1)), 1)


class Words(unittest.TestCase):
    def test_a_live_bid_names_the_offer_and_the_call(self):
        text = out.message(DOC["matches"][0], "t05")
        self.assertIn("Team 9 bids 20 P for SAL-06 on El Rastro: offer #20259, open until tick 1505.", text)
        self.assertIn('POST /api/offers/20259/accept with {"assets": [<your SAL-06 asset id>]}', text)
        self.assertIn("Open Bazaar · who needs which card", text)

    def test_an_inferred_need_says_it_may_be_wrong(self):
        for x in (DOC["matches"][2], DOC["matches"][3]):
            self.assertIn("appear to be missing", out.message(x, x["team"]))
            self.assertIn("inferred from public trades, may be wrong", out.message(x, x["team"]))

    def test_a_swap_is_accepted_directly_never_crossed(self):
        x = m("t06", "RET-12", 1, ("swap", 20068, "rastro", 0, "t06"), who=("t05",))
        text = out.message(x, "t05")
        self.assertIn("a swap: accept it directly", text)
        self.assertNotIn("crosses", text)


class FakeClient:
    def __init__(self, open_threads=0, fail=None):
        self.calls, self.open_threads, self.fail = [], open_threads, fail or {}

    def _maybe(self, what):
        self.calls.append(what)
        if what[0] in self.fail:
            raise self.fail[what[0]]

    def my_threads(self, status=None):
        self._maybe(("my_threads", status))
        return {"threads": [{"id": i, "status": "open"} for i in range(self.open_threads)]}

    def open_thread(self, with_, topic=None, venue=None):
        self._maybe(("open", with_, venue))
        return {"id": 77}

    def say(self, tid, text=""):
        self._maybe(("say", tid))
        return {"ok": True}

    def close_thread(self, tid):
        self._maybe(("close", tid))
        return {"ok": True}


class Log:
    def __init__(self):
        self.events = []

    def event(self, e, **d):
        self.events.append((e, d))


class Send(unittest.TestCase):
    def test_one_thread_one_message_closed_at_once(self):
        c = FakeClient()
        res = out.send_one(c, "t05", "hello", "rastro", Log())
        self.assertEqual([x[0] for x in c.calls], ["my_threads", "open", "say", "close"])
        self.assertEqual((res["sent"], res["closed"], res["error"]), (True, True, None))

    def test_a_refusal_stops_and_the_thread_is_still_closed(self):
        c = FakeClient(fail={"say": BazaarError("wait_for_tick", "", 429)})
        res = out.send_one(c, "t05", "hello", "rastro", Log())
        self.assertEqual([x[0] for x in c.calls], ["my_threads", "open", "say", "close"])
        self.assertEqual((res["sent"], res["closed"], res["error"]), (False, True, "429 wait_for_tick"))

    def test_three_slots_stay_free_for_the_dealer_bots_after_ours_opens(self):
        c = FakeClient(open_threads=out.MAX_THREADS - out.RESERVE_SLOTS)          # 3 open: ours would leave 2
        res = out.send_one(c, "t05", "hello", "rastro", Log())
        self.assertEqual([x[0] for x in c.calls], ["my_threads"])
        self.assertIn("kept for the dealer bots", res["error"])
        c = FakeClient(open_threads=out.MAX_THREADS - out.RESERVE_SLOTS - 1)      # 2 open: ours leaves 3
        self.assertTrue(out.send_one(c, "t05", "hello", "rastro", Log())["sent"])

    def test_a_failed_close_is_an_error(self):
        c = FakeClient(fail={"close": BazaarError("network", "", 0)})
        res = out.send_one(c, "t05", "hello", "rastro", Log())
        self.assertEqual((res["sent"], res["closed"], res["error"]), (True, False, "the thread could not be closed"))

    def test_nothing_is_called_inside_a_market_test_silence_not_even_a_close(self):
        sys.path.insert(0, str(ROOT / "agent"))
        import announce
        gate = announce.Gate(manual=[(0, 10 ** 12)])
        c = FakeClient()
        res = out.send_one(c, "t05", "hello", "rastro", Log(), gate)
        self.assertEqual((c.calls, res["sent"]), ([], False))
        self.assertFalse(out.close_thread_safely(c, 77, Log(), gate))
        self.assertEqual(c.calls, [])


class FakeGate:
    def __init__(self, known=True, windows=(), refresh_ok=True):
        self._known, self.windows, self.refresh_ok, self.refreshes = known, list(windows), refresh_ok, 0

    def refresh(self, get, *a):
        self.refreshes += 1
        self._known = self.refresh_ok
        return self.refresh_ok

    def known(self):
        return self._known

    def quiet_end(self):
        return next((e for s, e in self.windows if s <= time.time() < e), None)

    def check(self):
        if self.quiet_end() is not None:
            sys.path.insert(0, str(ROOT / "agent"))
            import announce
            raise announce.Silenced()


class Cli(unittest.TestCase):
    BOOK = {"rastro": [{"id": 20259, "status": "open", "expires_tick": 1505,
                        "give": {"cash": 20, "assets": [], "types": []}, "want": {"cash": 0, "assets": [],
                                                                                  "types": ["card:SAL-06"]}},
                       {"id": 20218, "status": "open", "expires_tick": 1505,
                        "give": {"cash": 0, "assets": [{"id": 1, "kind": "card", "ref": "LAT-07"}], "types": []},
                        "want": {"cash": 30, "assets": [], "types": []}}]}

    def run_main(self, argv, client=None, gate=None, state=None, book=None, doc=None, trace=None):
        import announce
        buf, logged = io.StringIO(), []
        book = self.BOOK if book is None else book
        doc = DOC if doc is None else doc

        class RL:
            def __init__(self, *_): pass
            def start(self, **k): logged.append(("start", k))
            def event(self, e, **d): logged.append((e, d))
            def end(self, **d): logged.append(("end", d))

        def get_json(url):
            if trace is not None:
                trace.append("get " + url.rsplit("/api/", 1)[1])
            if url.endswith("/api/clock"):
                return {"tick": 1440, "tick_seconds": 15.0}
            venue = url.split("/api/venues/")[1].split("/")[0] if "/api/venues/" in url else None
            return {"offers": book.get(venue, [])}

        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            if doc != "missing":
                mpath.write_text(json.dumps(dict(doc, generated_at=time.time())))
            spath = Path(d) / "s.json"
            if state is not None:
                spath.write_text(json.dumps(state))
            with contextlib.redirect_stdout(buf), um.patch("runlog.RunLog", RL), \
                    um.patch.object(announce, "Gate", lambda *a, **k: gate or FakeGate()), \
                    um.patch.object(announce, "get_json", get_json), um.patch.object(out.time, "sleep", lambda s: None), \
                    um.patch.dict("os.environ", {"BAZAAR_KEY": "tk-AbCd-EfGh"}), \
                    um.patch("bazaar_sdk.Bazaar", lambda *a, **k: client):
                out.main(argv + ["--matches", str(mpath), "--state", str(spath), "--exclude", ""])
            state = json.loads(spath.read_text()) if spath.exists() else {}
        return buf.getvalue(), logged, state

    def test_plan_is_keyless_and_shows_the_slot_budget(self):
        with um.patch.object(out, "team_key", side_effect=AssertionError("plan read the key")):
            text, logged, state = self.run_main(["plan", "--max-teams", "2"])
        self.assertIn("run opens only while 3 stay free for the dealer bots", text)
        self.assertIn('{"with": "t05", "venue": "rastro"}', text)
        self.assertEqual((logged, state), ([], {}))

    def test_max_teams_zero_sends_nothing(self):
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "0"], client=c)
        self.assertEqual((c.calls, state), ([], {}))
        self.assertEqual(out.targets(DOC, {}, "d", 0), [])

    def test_run_needs_yes(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            out.main(["run"])

    def test_run_sends_records_and_never_prints_or_logs_the_key(self):
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "2"], client=c)
        self.assertEqual([x for x in c.calls if x[0] == "open"], [("open", "t05", "rastro"), ("open", "t14", "rastro")])
        self.assertEqual(state["keys"], ["t09:SAL-06:20259", "t14:LAT-07:20218"])
        self.assertNotIn("tk-AbCd-EfGh", text + json.dumps(logged))

    def test_an_offer_that_no_longer_stands_is_not_sent(self):
        c = FakeClient()
        book = {"rastro": [dict(self.BOOK["rastro"][0], give={"cash": 12, "assets": [], "types": []})]}
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "1"], client=c, book=book)
        self.assertEqual(c.calls, [])
        self.assertIn("skipped", [e for e, _ in logged])

    def test_run_stops_at_the_first_refusal_and_records_nothing_unsent(self):
        c = FakeClient(fail={"open": BazaarError("forbidden", "", 403)})
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "3"], client=c)
        self.assertEqual(len([x for x in c.calls if x[0] == "open"]), 1)
        self.assertEqual(state, {})
        self.assertIn("stopped: 403 forbidden", text)

    def test_a_thread_that_could_not_be_closed_stops_the_run_and_is_closed_first_next_time(self):
        c = FakeClient(fail={"close": BazaarError("network", "", 0)})
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "3"], client=c)
        self.assertEqual(len([x for x in c.calls if x[0] == "open"]), 1)
        self.assertEqual(state["unclosed"], [77])
        c2 = FakeClient(fail={"close": BazaarError("network", "", 0)})
        text, logged, state2 = self.run_main(["run", "--yes", "--max-teams", "3"], client=c2, state=state)
        self.assertEqual([x[0] for x in c2.calls], ["close"])              # nothing else until it closes
        c3 = FakeClient()
        text, logged, state3 = self.run_main(["run", "--yes", "--max-teams", "1"], client=c3, state=state)
        self.assertEqual([x[0] for x in c3.calls][:1], ["close"])
        self.assertEqual(state3["unclosed"], [])

    def test_every_request_is_right_after_a_silence_check(self):
        """Sol round 2, blocker 1: no read or write without the gate asked just before it (cleanup reads, the clock
        read, both freshness reads included)."""
        import announce
        trace = []

        class Traced(FakeGate):
            def check(self):
                trace.append("check")
                super().check()

            def quiet_end(self):
                trace.append("check")
                return super().quiet_end()

        class TracedClient(FakeClient):
            def _maybe(self, what):
                trace.append("client " + what[0])
                super()._maybe(what)
        self.run_main(["run", "--yes", "--max-teams", "2"], client=TracedClient(), gate=Traced(), trace=trace,
                      state={"unclosed": [5]})
        requests = [i for i, x in enumerate(trace) if x != "check"]
        self.assertTrue(len(requests) > 6, trace)
        for i in requests:
            self.assertEqual(trace[i - 1], "check", (i, trace[max(0, i - 3):i + 1]))

    def test_a_silence_that_starts_during_the_cleanup_stops_every_later_read(self):
        """Sol round 2, blocker 1: the silence starts at t+100; the old thread's close answers at t+101; nothing after."""
        import announce
        clock = {"now": 1000.0}
        trace = []

        class SlowClose(FakeClient):
            def close_thread(self, tid):
                r = super().close_thread(tid)
                clock["now"] = 1101.0                                       # the answer lands inside the silence
                return r

        class Gate(FakeGate):
            def quiet_end(self):
                return 1900.0 if 1100.0 <= clock["now"] < 1900.0 else None

            def check(self):
                if self.quiet_end() is not None:
                    raise announce.Silenced()
        c = SlowClose()
        with um.patch.object(out.time, "time", lambda: clock["now"]):
            text, logged, state = self.run_main(["run", "--yes"], client=c, gate=Gate(), trace=trace,
                                                state={"unclosed": [5]})
        self.assertEqual([x[0] for x in c.calls], ["close"])
        self.assertEqual(trace, [])                                         # no read at all after the close
        self.assertEqual(state["unclosed"], [])

    def test_a_silence_found_while_rechecking_the_offer_stops_the_run(self):
        import announce

        class Late(FakeGate):
            n = 0

            def check(self):
                self.n += 1
                if self.n >= 2:                                             # the second read of offer_stands
                    raise announce.Silenced()
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "2"], client=c, gate=Late())
        self.assertEqual((c.calls, state), ([], {}))
        self.assertIn(("stopped", {"reason": "Market Test silence"}), logged)

    def test_a_thread_left_open_is_closed_even_with_nothing_left_to_send(self):
        """Sol round 2, blocker 2: one match, sent, its close fails; the next run has nothing to send (deduplicated)
        and must still close the thread; so must a run whose match file is stale or missing."""
        one = dict(DOC, matches=[DOC["matches"][0]])
        c = FakeClient(fail={"close": BazaarError("network", "", 0)})
        _, _, state = self.run_main(["run", "--yes"], client=c, doc=one)
        self.assertEqual((state["keys"], state["unclosed"]), (["t09:SAL-06:20259"], [77]))
        c2 = FakeClient()
        _, _, state2 = self.run_main(["run", "--yes"], client=c2, doc=one, state=state)
        self.assertEqual(([x[0] for x in c2.calls], state2["unclosed"]), (["close"], []))
        c3 = FakeClient()
        _, _, state3 = self.run_main(["run", "--yes"], client=c3, doc="missing", state=state)
        self.assertEqual(([x[0] for x in c3.calls], state3["unclosed"]), (["close"], []))
        c4 = FakeClient()
        _, _, state4 = self.run_main(["run", "--yes", "--max-teams", "0"], client=c4, state=state)
        self.assertEqual((c4.calls, state4["unclosed"]), ([], [77]))      # an explicit 0 touches nothing

    def test_run_sends_nothing_when_the_market_test_status_is_unknown_or_stale(self):
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes"], client=c, gate=FakeGate(known=False, refresh_ok=False))
        self.assertEqual((c.calls, state), ([], {}))
        text, logged, state = self.run_main(["run", "--yes"], client=c, gate=FakeGate(known=False, refresh_ok=False),
                                            state={"unclosed": [77]})
        self.assertEqual((c.calls, state["unclosed"]), ([], [77]))          # not even the close of an old thread

    def test_the_status_is_rechecked_before_every_send(self):
        class Stale(FakeGate):              # fresh for the start and the first send, stale after, and the read fails
            n = 0

            def known(self):                # two reads at the start, two before the first send
                self.n += 1
                return self.n <= 4
        c = FakeClient()
        gate = Stale(refresh_ok=False)
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "2"], client=c, gate=gate)
        self.assertEqual(len([x for x in c.calls if x[0] == "open"]), 1)
        self.assertIn("status unknown or stale", text)

    def test_no_thread_is_opened_within_two_ticks_of_a_silence(self):
        c = FakeClient()
        soon = FakeGate(windows=[(time.time() + 20, time.time() + 900)])         # starts in 20 s, ticks of 15 s
        text, logged, state = self.run_main(["run", "--yes"], client=c, gate=soon)
        self.assertEqual(c.calls, [])
        self.assertIn("starts within 2 ticks", text)
        later = FakeGate(windows=[(time.time() + 300, time.time() + 900)])
        self.assertEqual(self.run_main(["run", "--yes"], client=FakeClient(), gate=later)[2]["keys"],
                         ["t09:SAL-06:20259"])


if __name__ == "__main__":
    unittest.main()


class Guards(unittest.TestCase):
    """The same two guards as the announcer: never a card we lack, never an unconfident inference."""

    def test_an_unconfident_or_inconsistent_inference_is_never_messaged(self):
        low = m("t13", "MAL-08", 4)
        low["p_missing"] = 0.6
        self.assertEqual(out.targets({"matches": [low]}, {}, "d", 3), [])
        self.assertEqual(len(out.targets({"matches": [low]}, {}, "d", 3, min_p=0.5)), 1)
        ok = m("t13", "MAL-08", 4)
        self.assertEqual(len(out.targets({"matches": [ok]}, {}, "d", 3)), 1)
        self.assertEqual(out.targets({"matches": [ok], "teams": {"t13": {"consistent": False}}}, {}, "d", 3), [])

    def test_a_swap_giving_a_card_we_lack_is_never_messaged(self):
        sw = m("t06", "RET-12", 1, action=("swap", 9, "rastro", 0, "t06"), who=("t05",))   # gives SAL-02
        self.assertEqual(out.targets({"matches": [sw]}, {}, "d", 3, exclude=("SAL-02",)), [])

    def test_the_default_reads_our_account_and_fails_closed_without_it(self):
        import argparse
        import value_inference
        fallback = ("NOT-01",)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "me.json").write_text(json.dumps({"id": "t03", "tick": 1500, "tick_seconds": 15, "assets": [
                {"id": 1, "kind": "card", "ref": "MAL-08"}]}))
            with um.patch("builtins.print"):
                got = out.lacking(argparse.Namespace(exclude_from=d, exclude_max_age_min=60), {"tick": 1500}, fallback)
                none = out.lacking(argparse.Namespace(exclude_from=d + "/nope", exclude_max_age_min=60),
                                   {"tick": 1500}, fallback)
                off = out.lacking(argparse.Namespace(exclude_from="", exclude_max_age_min=60), {"tick": 1500}, fallback)
        self.assertIn("MAL-07", got)                               # a page card we do not hold
        self.assertNotIn("MAL-08", got)                            # one we hold
        self.assertNotIn("NOT-01", got.cards)                      # a trusted file needs no built-in list
        self.assertTrue(got.trusted)
        every = {c["id"] for c in value_inference.catalog()["sets"][0]["cards"] if c.get("page")}
        for closed in (none, off):                                 # no trusted file: every page card, not MISSING alone
            self.assertTrue(all(r in closed for r in every))
            self.assertFalse(closed.trusted)
            self.assertIn("MAL-08", closed)
        src = (ROOT / "tools" / "outreach.py").read_text(encoding="utf-8")
        self.assertIn('ap.add_argument("--exclude-from", default=str(ACCOUNT_DIR),', src)
        self.assertEqual(out.ACCOUNT_DIR, ROOT / "logs" / "state")


class SolRound1(unittest.TestCase):
    def test_only_a_real_probability_is_messaged(self):
        for bad in (float("nan"), True, 1.5, -0.1):
            x = m("t13", "MAL-08", 4)
            x["p_missing"] = bad
            with self.subTest(bad=bad):
                self.assertEqual(out.targets({"matches": [x]}, {}, "d", 3, min_p=0.0), [])

    def test_no_catalog_means_nothing_is_sent(self):
        import argparse
        import value_inference
        with um.patch.object(value_inference, "catalog", um.MagicMock(side_effect=OSError("down"))), \
                self.assertRaises(LookupError):
            out.lacking(argparse.Namespace(exclude_from="", exclude_max_age_min=60), {"tick": 1}, ())


class SolRound2(unittest.TestCase):
    def test_1_without_trusted_holdings_only_epic_and_legendary_cards_are_messaged(self):
        import argparse
        import value_inference
        cat_ = {"sets": [{"id": "MAL", "cards": [{"id": "MAL-08", "rarity": "uncommon", "page": True},
                                                 {"id": "MAL-11", "rarity": "epic", "page": False}]}]}
        page = m("t13", "MAL-08", 1, action=("bid", 7, "rastro", 20, "t13"), who=("t05",))
        epic = m("t14", "MAL-11", 1, action=("bid", 8, "rastro", 150, "t14"), who=("t05",))
        unknown = m("t15", "ZZZ-01", 1, action=("bid", 9, "rastro", 20, "t15"), who=("t05",))
        for catalog, allowed in ((cat_, ["MAL-11"]), ({"sets": []}, [])):
            with self.subTest(complete=bool(catalog["sets"])), \
                    um.patch.object(value_inference, "catalog", lambda *a, **k: catalog), um.patch("builtins.print"):
                ex = out.lacking(argparse.Namespace(exclude_from="/nonexistent", exclude_max_age_min=60), {"tick": 1}, ())
                got = out.targets({"matches": [page, epic, unknown]}, {}, "d", 5, exclude=ex | {"NOT-01"})
                self.assertEqual([x[1]["card"] for x in got], allowed)


TEAMS = {"t03": {"active": True, "last_move_tick": 1550}, "t05": {"active": True, "last_move_tick": 1500},
         "t07": {"active": True, "last_move_tick": 1540}, "t08": {"active": False, "last_move_tick": 1549},
         "t11": {"active": True, "last_move_tick": None}}


class SteerToV20(unittest.TestCase):
    """Matches on El Rastro keep their action and get the v20 line while it fits; the pitch is opt-in, once per team."""

    def test_an_offer_off_our_venue_keeps_its_call_and_adds_the_v20_line(self):
        for x, to in ((DOC["matches"][0], "t05"), (DOC["matches"][2], "t14")):
            text = out.message(x, to)
            self.assertIn(f"POST /api/offers/{x['action']['offer']}/accept", text)
            self.assertIn(out.V20_LINE.strip(), text)
            self.assertIn("5 % + 1 P a card", text)
            self.assertLessEqual(len(text), out.MAX_CHARS)
            self.assertTrue(text.endswith("We will not message you again today."))

    def test_an_offer_on_v20_or_a_swap_gets_no_v20_line(self):
        on_v20 = m("t09", "SAL-06", 1, ("bid", 20259, "v20", 20, "t09"), who=("t05",))
        swap = m("t06", "RET-12", 1, ("swap", 20068, "rastro", 0, "t06"), who=("t05",))
        for x in (on_v20, swap):
            self.assertNotIn("Next time", out.message(x, "t05"))

    def test_an_inferred_need_without_an_offer_proposes_the_v20_bid(self):
        text = out.message(DOC["matches"][3], "t13")
        self.assertIn('La Celestina (v20, 0 % fee; El Rastro charges the taker 5 % + 1 P a card): POST /api/offers '
                      '{"venue": "v20", "give": {"cash": 24}, "want": {"cards": ["MAL-08"]}}', text)
        self.assertLessEqual(len(text), out.MAX_CHARS)

    def test_the_v20_line_is_dropped_whole_never_the_call_when_it_would_not_fit(self):
        x = m("t09", "SAL-06", 1, ("bid", 20259, "rastro", 20, "t09"), who=("t05",))
        x["card_name"], x["action"]["maker_name"] = "N" * 500, "M" * 400
        text = out.message(x, "t05")
        self.assertNotIn("Next time", text)
        self.assertIn('POST /api/offers/20259/accept with {"assets": [<your SAL-06 asset id>]}.', text)
        self.assertTrue(text.endswith("We will not message you again today."))

    def test_the_pitch_names_no_card_fits_and_claims_nothing_about_our_buying_by_default(self):
        text = out.pitch_message()
        self.assertLessEqual(len(text), out.MAX_CHARS)
        self.assertIn('POST /api/offers {"venue": "v20", "give": {"cash": <your price>}, "want": {"cards": '
                      '["<card ref>"]}}', text)
        self.assertIn('{"venue": "v20", "give": {"assets": [<your asset id>]}, "want": {"cash": <your price>}}', text)
        self.assertNotIn("buying desk", text)
        self.assertNotRegex(text, r"[A-Z]{3}-\d\d")       # no card named
        self.assertIn("buying desk", out.pitch_message(reciprocity=True))
        self.assertLessEqual(len(out.pitch_message(reciprocity=True)), out.MAX_CHARS)
        for t in (text, out.pitch_message(True)):
            self.assertNotIn("trade on ours", t.lower())

    def test_pitch_targets_active_teams_once_per_game_never_us_never_messaged_today(self):
        doc = {"teams": TEAMS}
        self.assertEqual([t for t, _, _ in out.pitch_targets(doc, {}, "d", 10)], ["t07", "t05", "t11"])
        state = {"teams": {"d": ["t07"]}, "keys": ["pitch:t05"]}
        self.assertEqual([t for t, _, _ in out.pitch_targets(doc, state, "d", 10)], ["t11"])
        self.assertEqual([t for t, _, _ in out.pitch_targets(doc, {}, "d", 10, taken=["t07"])], ["t05", "t11"])
        self.assertEqual(out.pitch_targets(doc, {}, "d", 0), [])
        self.assertEqual(out.key_of(out.pitch_targets(doc, {}, "d", 1)[0][1]), "pitch:t07")


class PitchCli(unittest.TestCase):
    BOOK = Cli.BOOK
    run_main = Cli.run_main
    DOC2 = dict(DOC, teams=TEAMS)

    def test_the_pitch_is_off_by_default(self):
        text, _, _ = self.run_main(["plan", "--max-teams", "10"], doc=self.DOC2)
        self.assertNotIn("is a board venue", text)

    def test_the_pitch_fills_only_the_slots_left_and_is_recorded_once(self):
        text, _, _ = self.run_main(["plan", "--max-teams", "2", "--pitch"], doc=self.DOC2)
        self.assertNotIn("is a board venue", text)                       # 2 matches fill the 2 slots
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "6", "--pitch"], client=c, doc=self.DOC2)
        opened = [x[1] for x in c.calls if x[0] == "open"]
        self.assertEqual(opened[:2], ["t05", "t14"])                    # the matches first
        self.assertEqual(opened[-2:], ["t07", "t11"])                   # then the pitch; t05 got a match: no pitch
        self.assertEqual(opened.count("t05"), 1)
        self.assertEqual([k for k in state["keys"] if k.startswith("pitch:")], ["pitch:t07", "pitch:t11"])
        c2 = FakeClient()
        self.run_main(["run", "--yes", "--max-teams", "5", "--pitch"], client=c2, doc=self.DOC2, state=state)
        self.assertEqual([x for x in c2.calls if x[0] == "open"], [])

    def test_reciprocity_needs_the_pitch(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            out.main(["plan", "--pitch-reciprocity"])


def want(team, card, price, venue, oid, holders, set_=None):
    x = m(team, card, 2, ("bid", oid, venue, price, team))
    x["set"] = set_ or card.split("-")[0]
    x["holders"] = [dict({"team": t, "name": f"Team {int(t[1:])}", "active": True, "as_of": 1660}, copies=c, asset=a)
                    for t, c, a in holders]
    return x


PDOC = {"generated_at": 0, "tick": 1660, "matches": [
    want("t05", "LAT-06", 9, "v15", 21791, [("t16", 2, 613)]),                    # a spare, a high bid
    want("t12", "LAV-07", 5, "rastro", 21800, [("t07", 2, 700)]),                 # a spare, the last card of t12's page
    want("t04", "SAL-03", 4, "rastro", 21486, [("t01", 1, 934)]),                 # one copy, t01 is filling SAL
    m("t06", "CHA-12", 2, ("swap", 21645, "v02", 0, "t06")),                      # a swap: never paired
    want("t09", "RET-02", 30, "v20", 21900, [("t08", 3, 800)]),                   # already on v20: never paired
], "teams": {
    "t12": {"active": True, "consistent": True, "near_pages": [
        {"set": "LAV", "have": 9, "size": 10, "appears_missing": ["LAV-07"]}]},
    "t01": {"active": True, "consistent": True, "near_pages": [
        {"set": "SAL", "have": 8, "size": 10, "appears_missing": ["SAL-04", "SAL-06"]}]},
    "t05": {"active": True, "last_move_tick": 1650}, "t16": {"active": True, "last_move_tick": 1640},
    "t07": {"active": True, "last_move_tick": 1630}, "t02": {"active": True, "last_move_tick": 1620},
}}
PDOC["matches"][3]["holders"] = [{"team": "t10", "copies": 2, "active": True}]


class Pair(unittest.TestCase):
    """--pair: a tier-2 cash bid and a holder the decks name both get one message; the trade happens on v20."""

    def test_a_pair_is_found_and_both_texts_carry_the_post_shapes(self):
        got = out.pair_targets(PDOC, {}, "d", 6)
        self.assertEqual([to for to, _, _ in got], ["t12", "t07", "t05", "t16"])
        (w, mw, tw), (h, mh, th) = got[2], got[3]
        self.assertEqual((mw["role"], mh["role"], mw["want"], mw["holder"], mw["card"]),
                         ("want", "holder", "t05", "t16", "LAT-06"))
        self.assertIn('POST /api/offers {"venue": "v20", "give": {"cash": 9}, "want": {"cards": ["LAT-06"]}}', tw)
        self.assertIn("Team 16 holding 2 copies", tw)
        self.assertIn("appears to have a spare", tw)
        self.assertIn("Team 5 bids 9 P for LAT-06 on venue v15: offer #21791", th)
        self.assertIn('POST /api/offers {"venue": "v20", "give": {"assets": [613]}, "want": {"cash": <your price>}}', th)
        for t in (tw, th):
            self.assertIn("0 % fee", t)
            self.assertIn("5 % + 1 P a card", t)
            self.assertIn("at the midpoint", t)
            self.assertLessEqual(len(t), out.MAX_CHARS)
            self.assertTrue(t.endswith("We will not message you again today."))
            self.assertNotIn(chr(0x2014), t)
        self.assertNotIn('"cash": 9', th)                         # the holder's ask never carries the bidder's price
        self.assertEqual(len({out.key_of(x[1]) for x in got}), 4)
        self.assertEqual(out.key_of(mw), "pair:t05:LAT-06:t16:want")
        self.assertEqual(out.key_of(mh), "pair:t05:LAT-06:t16:holder")

    def test_last_card_of_a_page_ranks_first_then_the_bid(self):
        got = out.pair_targets(PDOC, {}, "d", 6)
        self.assertEqual(got[0][1]["card"], "LAV-07")              # 5 P, the last card of t12's page
        self.assertIn("last card of the", got[0][1]["reason"])
        self.assertEqual(got[2][1]["card"], "LAT-06")              # 9 P, no near page
        self.assertEqual(out.page_gap(PDOC, "t12", "LAV-07", "LAV"), 1)
        self.assertEqual(out.page_gap(PDOC, "t05", "LAT-06", "LAT"), out.FAR)

    def test_skipped_when_either_side_was_messaged_today_or_taken_by_this_run(self):
        for state in ({"teams": {"d": ["t07"]}}, {"teams": {"d": ["t12"]}}):
            with self.subTest(state=state):
                self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, state, "d", 6)], ["t05", "t16"])
        self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, {}, "d", 6, taken=["t16"])], ["t12", "t07"])
        sent = {"keys": ["pair:t12:LAV-07:t07:want"]}             # a want sent before is never sent again
        self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, sent, "d", 6)], ["t05", "t16"])
        self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, {}, "d", 6, exclude=("LAV-07",))], ["t05", "t16"])

    def test_skipped_when_the_holder_has_no_spare(self):
        cards = [x[1]["card"] for x in out.pair_targets(PDOC, {}, "d", 10)]
        self.assertNotIn("SAL-03", cards)                          # one copy of a set t01 is filling
        self.assertNotIn("CHA-12", cards)                          # a swap
        self.assertNotIn("RET-02", cards)                          # a bid already on v20
        free = json.loads(json.dumps(PDOC))
        free["teams"]["t01"]["near_pages"] = []                   # one copy of a set its consistent deck is not filling
        got = [x for x in out.pair_targets(free, {}, "d", 10) if x[1]["card"] == "SAL-03"]
        self.assertEqual([to for to, _, _ in got], ["t04", "t01"])
        self.assertIn("holding a copy of it", got[0][2])
        self.assertNotIn("spare", got[0][2])
        free["teams"]["t01"]["consistent"] = False                 # an inconsistent deck proves nothing
        self.assertFalse([x for x in out.pair_targets(free, {}, "d", 10) if x[1]["card"] == "SAL-03"])
        idle = json.loads(json.dumps(PDOC))
        idle["matches"][0]["holders"][0]["active"] = False         # an idle holder would never list it
        self.assertNotIn("LAT-06", [x[1]["card"] for x in out.pair_targets(idle, {}, "d", 10)])

    def test_a_pair_takes_two_slots_never_one(self):
        self.assertEqual(len(out.pair_targets(PDOC, {}, "d", 3)), 2)
        self.assertEqual(out.pair_targets(PDOC, {}, "d", 1), [])

    def test_long_names_are_capped_and_the_post_shapes_always_fit(self):
        x = json.loads(json.dumps(PDOC["matches"][0]))
        x["card_name"], x["action"]["maker_name"] = "N" * 3000, "M" * 2000
        x["holders"][0]["name"] = "H" * 2000
        tw, th = out.pair_messages(x, x["holders"][0], 2)
        for t in (tw, th):
            self.assertLessEqual(len(t), out.MAX_CHARS)
            self.assertIn('POST /api/offers {"venue": "v20"', t)
            self.assertTrue(t.endswith("We will not message you again today."))
            self.assertNotIn("N" * (out.NAME_CAP + 1), t)


class PairCli(unittest.TestCase):
    run_main = Cli.run_main
    BOOK = {"rastro": [{"id": 21800, "status": "open", "expires_tick": 1900,
                        "give": {"cash": 5, "assets": [], "types": []},
                        "want": {"cash": 0, "assets": [], "types": ["card:LAV-07"]}}],
            "v15": [{"id": 21791, "status": "open", "expires_tick": 1900, "give": {"cash": 9, "assets": [], "types": []},
                     "want": {"cash": 0, "assets": [], "types": ["card:LAT-06"]}}]}

    def go(self, argv, **k):
        with um.patch.object(out, "lacking", lambda *a, **kw: set()):
            return self.run_main(argv, doc=PDOC, book=k.pop("book", self.BOOK), **k)

    def test_flag_off_is_the_old_behaviour(self):
        with um.patch.object(out, "lacking", lambda *a, **kw: set()):
            self.assertNotIn("tier pair", self.run_main(["plan", "--max-teams", "6"], doc=PDOC)[0])
            self.assertEqual(self.run_main(["plan", "--max-teams", "6"], doc=DOC)[0],
                             self.run_main(["plan", "--max-teams", "6", "--pair"], doc=DOC)[0])  # no holder: no pair

    def test_plan_prints_each_pair_and_both_texts(self):
        text = self.go(["plan", "--max-teams", "4", "--pair"])[0]
        self.assertIn("pair: W t12 wants LAV-07, H t07 holds it; reason: last card of the", text)
        self.assertIn("pair: W t05 wants LAT-06, H t16 holds it", text)
        self.assertEqual(text.count("/messages "), 4)

    def test_run_sends_both_sides_records_both_keys_and_the_pitch_takes_what_is_left(self):
        c = FakeClient()
        text, logged, state = self.go(["run", "--yes", "--max-teams", "5", "--pair", "--pitch"], client=c)
        opened = [x[1] for x in c.calls if x[0] == "open"]
        self.assertEqual(opened, ["t12", "t07", "t05", "t16", "t02"])
        self.assertEqual(state["keys"][:4], ["pair:t12:LAV-07:t07:want", "pair:t12:LAV-07:t07:holder",
                                             "pair:t05:LAT-06:t16:want", "pair:t05:LAT-06:t16:holder"])
        self.assertEqual(state["keys"][4:], ["pitch:t02"])

    def test_the_holder_is_not_told_when_the_bidder_was_not(self):
        c = FakeClient()
        book = {"rastro": [], "v15": self.BOOK["v15"]}            # t12's bid is gone: neither side of that pair
        text, logged, state = self.go(["run", "--yes", "--max-teams", "4", "--pair"], client=c, book=book)
        self.assertEqual([x[1] for x in c.calls if x[0] == "open"], ["t05", "t16"])
        self.assertIn(("skipped", {"to": "t07", "key": "pair:t12:LAV-07:t07:holder",
                                   "reason": "the bidder of this pair was not told"}), logged)


class PairAfterPitch(unittest.TestCase):
    """A team whose only message today was the venue pitch may still get ONE pair message; nobody else messaged today."""
    TODAY = {"teams": {"d": ["t12", "t07", "t05", "t16"]}}

    def test_a_pitch_only_team_is_eligible(self):
        got = {t: {"pitch"} for t in self.TODAY["teams"]["d"]}
        self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, self.TODAY, "d", 6, got=got)],
                         ["t12", "t07", "t05", "t16"])
        self.assertEqual(out.pair_targets(PDOC, self.TODAY, "d", 6), [])          # nothing known: fail closed

    def test_a_team_matched_today_is_still_excluded(self):
        for t07 in ({"match"}, {"pitch", "match"}, None):                        # None: not accounted for
            got = {t: {"pitch"} for t in ("t12", "t05", "t16")}
            if t07 is not None:
                got["t07"] = t07
            with self.subTest(t07=t07):
                self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, self.TODAY, "d", 6, got=got)],
                                 ["t05", "t16"])

    def test_a_second_pair_message_to_the_same_team_the_same_day_is_refused(self):
        got = {"t12": {"pitch"}, "t07": {"pitch", "pair"}, "t05": {"pitch"}, "t16": {"pitch"}}
        self.assertEqual([to for to, _, _ in out.pair_targets(PDOC, self.TODAY, "d", 6, got=got)], ["t05", "t16"])
        state = {"teams": {"d": ["t12"]}, "kinds": {"d": {"t12": ["pair"]}}}       # a pair only, no pitch before
        self.assertNotIn("t12", [to for to, _, _ in out.pair_targets(PDOC, state, "d", 6,
                                                                      got=out.received(state, "d"))])

    def test_an_inactive_bidder_is_never_paired(self):
        idle = json.loads(json.dumps(PDOC))
        idle["teams"]["t12"]["active"] = False
        self.assertEqual([to for to, _, _ in out.pair_targets(idle, {}, "d", 6)], ["t05", "t16"])

    def test_received_reads_state_kinds_and_the_run_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text("\n".join([json.dumps({"event": "sent", "to": "t12", "tier": "pitch", "key": "[redacted]"}),
                                    json.dumps({"event": "sent", "to": "t18", "tier": 1, "card": "SAL-11"}),
                                    json.dumps({"event": "sent", "to": "t07", "tier": "pair"}),
                                    json.dumps({"event": "open", "to": "t05"}), "not json"]))
            got = out.received({"kinds": {"d": {"t16": ["pitch"]}}}, "d", p)
            self.assertEqual(got, {"t12": {"pitch"}, "t18": {"match"}, "t07": {"pair"}, "t16": {"pitch"}})
            self.assertEqual(out.received({}, "d", Path(d) / "missing.jsonl"), {})
        self.assertEqual(out.pair_eligible({"teams": {"d": ["t12", "t18", "t07", "t09"]}}, "d", got), {"t12"})


class PairAfterPitchCli(unittest.TestCase):
    run_main = Cli.run_main
    BOOK = PairCli.BOOK

    def test_run_sends_to_pitch_only_teams_once_and_records_the_kind(self):
        day = time.strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "sent.jsonl"
            log.write_text("\n".join(json.dumps({"event": "sent", "to": t, "tier": "pitch"})
                                     for t in ("t12", "t07", "t05", "t16")))
            state = {"teams": {day: ["t12", "t07", "t05", "t16"]},
                     "keys": ["pitch:t12", "pitch:t07", "pitch:t05", "pitch:t16"]}
            c = FakeClient()
            with um.patch.object(out, "lacking", lambda *a, **kw: set()):
                _, _, s2 = self.run_main(["run", "--yes", "--max-teams", "6", "--pair", "--sent-log", str(log)],
                                         client=c, doc=PDOC, book=self.BOOK, state=state)
                self.assertEqual([x[1] for x in c.calls if x[0] == "open"], ["t12", "t07", "t05", "t16"])
                self.assertEqual(s2["kinds"][day], {t: ["pair"] for t in ("t12", "t07", "t05", "t16")})
                s2["keys"] = [k for k in s2["keys"] if not k.startswith("pair:")]   # even with the pair keys gone
                c2 = FakeClient()
                self.run_main(["run", "--yes", "--max-teams", "6", "--pair", "--sent-log", str(log)],
                              client=c2, doc=PDOC, book=self.BOOK, state=s2)
                self.assertEqual([x for x in c2.calls if x[0] == "open"], [])    # one pair message per team a day
