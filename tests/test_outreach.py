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
    x = {"tier": tier, "inferred": tier >= 3, "team": team, "team_name": f"Team {int(team[1:])}", "card": card,
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

    def test_the_last_free_slots_stay_for_the_dealer_bots(self):
        c = FakeClient(open_threads=out.MAX_THREADS - out.MIN_FREE_SLOTS)
        res = out.send_one(c, "t05", "hello", "rastro", Log())
        self.assertEqual([x[0] for x in c.calls], ["my_threads"])
        self.assertIn("slots free", res["error"])
        c = FakeClient(open_threads=out.MAX_THREADS - out.MIN_FREE_SLOTS - 1)
        self.assertTrue(out.send_one(c, "t05", "hello", "rastro", Log())["sent"])

    def test_nothing_is_called_inside_a_market_test_silence(self):
        sys.path.insert(0, str(ROOT / "agent"))
        import announce
        gate = announce.Gate(manual=[(0, 10 ** 12)])
        c = FakeClient()
        res = out.send_one(c, "t05", "hello", "rastro", Log(), gate)
        self.assertEqual((c.calls, res["sent"]), ([], False))


class Cli(unittest.TestCase):
    def run_main(self, argv, client=None, gate_ok=True):
        import announce
        buf = io.StringIO()
        logged = []

        class RL:
            def __init__(self, *_): pass
            def start(self, **k): logged.append(("start", k))
            def event(self, e, **d): logged.append((e, d))
            def end(self, **d): logged.append(("end", d))

        class G:
            def __init__(self, *a, **k): pass
            def refresh(self, get, *a): return gate_ok
            def quiet_end(self): return None
            def check(self): pass

        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            mpath.write_text(json.dumps(dict(DOC, generated_at=time.time())))
            spath = Path(d) / "s.json"
            with contextlib.redirect_stdout(buf), um.patch("runlog.RunLog", RL), \
                    um.patch.object(announce, "Gate", G), um.patch.object(out.time, "sleep", lambda s: None), \
                    um.patch.dict("os.environ", {"BAZAAR_KEY": "tk-AbCd-EfGh"}), \
                    um.patch("bazaar_sdk.Bazaar", lambda *a, **k: client):
                out.main(argv + ["--matches", str(mpath), "--state", str(spath), "--exclude", ""])
            state = json.loads(spath.read_text()) if spath.exists() else {}
        return buf.getvalue(), logged, state

    def test_plan_is_keyless_and_shows_the_slot_budget(self):
        with um.patch.object(out, "team_key", side_effect=AssertionError("plan read the key")):
            text, logged, state = self.run_main(["plan", "--max-teams", "2"])
        self.assertIn("slot budget: 6 threads per team", text)
        self.assertIn('{"with": "t05", "venue": "rastro"}', text)
        self.assertEqual((logged, state), ([], {}))

    def test_run_needs_yes(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            out.main(["run"])

    def test_run_sends_records_and_never_prints_or_logs_the_key(self):
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "2"], client=c)
        self.assertEqual([x for x in c.calls if x[0] == "open"], [("open", "t05", "rastro"), ("open", "t14", "rastro")])
        self.assertEqual(state["keys"], ["t09:SAL-06:20259", "t14:LAT-07:20218"])
        self.assertNotIn("tk-AbCd-EfGh", text + json.dumps(logged))

    def test_run_stops_at_the_first_refusal_and_records_nothing_unsent(self):
        c = FakeClient(fail={"open": BazaarError("forbidden", "", 403)})
        text, logged, state = self.run_main(["run", "--yes", "--max-teams", "3"], client=c)
        self.assertEqual(len([x for x in c.calls if x[0] == "open"]), 1)
        self.assertEqual(state, {})
        self.assertIn("stopped: 403 forbidden", text)

    def test_run_sends_nothing_when_the_market_test_status_is_unknown(self):
        c = FakeClient()
        text, logged, state = self.run_main(["run", "--yes"], client=c, gate_ok=False)
        self.assertEqual((c.calls, state), ([], {}))


if __name__ == "__main__":
    unittest.main()
