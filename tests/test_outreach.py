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
