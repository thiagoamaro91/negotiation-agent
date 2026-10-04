"""tools/census.py: end of the id space, backoff and retry, resume, top-up merge, the per-team summary, the key
fallback that never shows the key, redaction of errors, and the Market Test start check. Offline: a fake transport
is injected, the real network and the machine's key are blocked. Run: python3 -m unittest discover tests"""
import datetime
import json
import sys
import tempfile
import time
import unittest
import unittest.mock as um
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import census  # noqa: E402

URL = "https://bazaar.test"
FAKE_KEY = "tk-fake-0000-test"        # clearly fake, credential-shaped
ODD_KEY = "plainfakekey987654"        # clearly fake, NOT credential-shaped: only the literal replacement hides it
T0 = time.mktime((2026, 10, 3, 23, 5, 30, 0, 0, -1))   # 23:05:30 local, after Saturday's close
_GUARDS = []
REAL_LOAD_KEY = census.load_key


def setUpModule():
    def no_network(*a, **k):
        raise AssertionError("a test tried to reach the network")
    for g in (um.patch.object(census.urllib.request, "urlopen", no_network),
              um.patch.object(census, "load_key", lambda *a, **k: None)):
        g.start()
        _GUARDS.append(g)


def tearDownModule():
    for g in _GUARDS:
        g.stop()


class Clock:
    def __init__(self, t=T0):
        self.t, self.sleeps = t, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


def card(i, owner, ref=None, kind="card"):
    ref = ref or f"LAV-{(i % 12) + 1:02d}"
    return {"id": i, "kind": kind, "ref": ref, "serial": i, "rarity": "common", "set": ref.split("-")[0],
            "name": f"Card {i}", "owner": owner, "history": [{"tick": 1, "to": owner}]}


def deck(ids, owners=("t01", "t02", "t03")):
    return {i: card(i, owners[i % len(owners)]) for i in ids}


class Server:
    """Answers like the Bazaar: /api/cards/{id} needs the key (401 bad_key keyless), clock/schedule/feed keyless.
    `script[id]` is a list of (status, headers, body) answered first, whatever the key."""

    def __init__(self, cards, clock=None, schedule=None, feed=None, key=FAKE_KEY, script=None, fail=(), boom=None,
                 timer=None, live=False):
        self.cards, self.key, self.script, self.fail, self.boom = cards, key, script or {}, set(fail), boom
        self.live = live   # the clock runs with the fake time: tick and t_hours advance (a game hour is a wall hour)
        self.clock = clock if clock is not None else {"tick": 1700, "doors": "closed", "t_hours": 13.4,
                                                       "tick_seconds": 30.0}
        self.schedule = schedule if schedule is not None else {"upcoming": []}
        self.feed = feed if feed is not None else {"events": []}
        self.calls, self.timer = [], timer

    def card_calls(self):
        return [(int(u.rsplit("/", 1)[1]), h) for u, h, _ in self.calls if "/api/cards/" in u]

    def keyed_ids(self):
        return [i for i, h in self.card_calls() if h.get("X-Team-Key")]

    def calls_between(self, a, b):
        """Every request of any kind sent in [a, b)."""
        return [(u, t) for u, _, t in self.calls if t is not None and a <= t < b]

    def clock_now(self):
        c = dict(self.clock)
        if self.live and self.timer is not None:
            dt = self.timer.now() - T0
            c["tick"] = int(self.clock["tick"] + dt // self.clock["tick_seconds"])
            c["t_hours"] = self.clock["t_hours"] + dt / 3600
        return c

    def __call__(self, url, headers, timeout=15.0):
        self.calls.append((url, dict(headers), self.timer.now() if self.timer else None))
        path = url[len(URL):]
        for p in self.fail:
            if path.startswith(p):
                return 500, {}, b'{"error": "boom"}'
        if path in self.script and self.script[path]:
            return self.script[path].pop(0)
        if path == "/api/clock":
            return 200, {}, json.dumps(self.clock_now()).encode()
        if path == "/api/schedule":
            sched = self.schedule(self.timer.now()) if callable(self.schedule) else self.schedule
            return 200, {}, json.dumps(sched).encode()
        if path.startswith("/api/feed"):
            feed = self.feed(self.timer.now()) if callable(self.feed) else self.feed
            return 200, {}, json.dumps(feed).encode()
        i = int(path.rsplit("/", 1)[1])
        if self.boom == i:
            raise KeyboardInterrupt
        if self.script.get(i):
            return self.script[i].pop(0)
        if headers.get("X-Team-Key") != self.key:
            return 401, {}, b'{"error":"bad_key","message":"unknown team key (header X-Team-Key)"}'
        if i in self.cards:
            return 200, {}, json.dumps(self.cards[i]).encode()
        return 404, {}, b'{"error":"not_found","message":"no such asset"}'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv, server, key=FAKE_KEY):
        lines = []
        if server.timer is None:
            server.timer = self.clock
        code = census.main(list(argv) + ["--url", URL] if argv[0] in ("run", "ids") else list(argv),
                           fetch=server, sleep=self.clock.sleep, now=self.clock.now,
                           key_loader=lambda: key, say=lines.append)
        return code, lines

    def walk(self, server, *extra, key=FAKE_KEY):
        return self.run_cli(["run", "--out", str(self.out), "--stop-after", "5", *extra], server, key)

    def snapshot(self):
        snaps = [p for p in self.out.glob("cards-*-t*.json") if not p.name.endswith("-history.json")]
        self.assertEqual(len(snaps), 1, [p.name for p in self.out.iterdir()])
        return json.loads(snaps[0].read_text())

    def all_text(self, lines=()):
        return "\n".join(lines) + "".join(p.read_text() for p in self.out.iterdir() if p.is_file())


class TestEndOfSpace(Base):
    def test_stops_after_a_run_of_404s_past_the_last_card(self):
        server = Server(deck(range(1, 41)))
        code, _ = self.walk(server)
        self.assertEqual(code, 0)
        self.assertEqual(max(i for i, _ in server.card_calls()), 45)
        m = self.snapshot()["meta"]
        self.assertEqual((m["end"], m["ids_walked"], m["found"], m["not_found"]), ("404_run", 45, 40, 5))
        self.assertEqual(m["tick_start"], 1700)

    def test_a_gap_below_expect_max_does_not_end_the_walk(self):
        cards = deck(list(range(1, 21)) + list(range(31, 41)))
        code, _ = self.walk(Server(cards))
        self.assertEqual(self.snapshot()["meta"]["found"], 20)          # without the anchor the gap ends it at 25
        for p in self.out.iterdir():
            p.unlink()
        code, _ = self.walk(Server(cards), "--expect-max", "31")
        self.assertEqual(code, 0)
        m = self.snapshot()["meta"]
        self.assertEqual((m["found"], m["ids_walked"]), (30, 45))

    def test_max_id_without_the_run_exits_4(self):
        code, lines = self.walk(Server(deck(range(1, 31))), "--max-id", "30")
        self.assertEqual(code, 4)
        self.assertEqual(self.snapshot()["meta"]["end"], "max_id")
        self.assertTrue(any("--max-id" in x for x in lines))


class TestBackoff(Base):
    def test_429_then_503_are_retried_on_the_same_id(self):
        script = {3: [(429, {"Retry-After": "7"}, b'{"error":"rate_limited"}'), (503, {}, b"")]}
        server = Server(deck(range(1, 11)), script=script)
        code, _ = self.walk(server)
        self.assertEqual(code, 0)
        self.assertIn(7.0, self.clock.sleeps)                            # Retry-After honoured
        self.assertIn(4.0, self.clock.sleeps)                            # then exponential (2 ** 2)
        self.assertEqual([i for i, _ in server.card_calls()].count(3), 3)
        self.assertIn(3, [c["id"] for c in self.snapshot()["cards"]])
        self.assertEqual(self.snapshot()["meta"]["errors"], [])

    def test_pace_is_one_request_per_second(self):
        server = Server(deck(range(1, 11)))
        self.walk(server)
        times = [t for u, _, t in server.calls if "/api/cards/" in u]
        self.assertTrue(all(b - a >= 0.999 for a, b in zip(times, times[1:])))

    def test_an_id_that_keeps_failing_is_recorded_not_skipped_and_resume_retries_it(self):
        server = Server(deck(range(1, 11)), script={3: [(500, {}, b'{"error":"boom"}')] * 3})
        code, _ = self.walk(server, "--max-retries", "3")
        self.assertEqual(code, 1)
        snap = self.snapshot()
        self.assertEqual([(e["id"], e["attempts"], e["code"]) for e in snap["meta"]["errors"]], [(3, 3, "boom")])
        self.assertIn(4, [c["id"] for c in snap["cards"]])               # the walk went on
        healthy = Server(deck(range(1, 11)))
        code, _ = self.walk(healthy, "--resume")
        self.assertEqual(code, 0)
        self.assertEqual(healthy.keyed_ids(), [3])                       # only the failed id is read again
        self.assertEqual(self.snapshot()["meta"]["found"], 10)

    def test_many_ids_failing_in_a_row_stop_the_run(self):
        server = Server({}, script={i: [(502, {}, b"")] * 9 for i in range(1, 50)})
        code, lines = self.walk(server, "--max-retries", "2", "--max-consecutive-errors", "3")
        self.assertEqual(code, 5)
        self.assertEqual(len(server.card_calls()), 6)
        self.assertEqual(list(self.out.glob("cards-*-t*.json")), [])
        self.assertTrue(any("--resume" in x for x in lines))


class TestResume(Base):
    def test_resume_skips_done_ids_even_after_midnight(self):
        cards = deck(range(1, 41))
        code, _ = self.walk(Server(cards, boom=25))
        self.assertEqual(code, 130)
        [partial] = list(self.out.glob("cards-*-partial.jsonl"))
        self.assertEqual(len(partial.read_text().splitlines()), 24)
        partial.rename(self.out / "cards-2026-10-02-partial.jsonl")      # started yesterday, resumed today
        server = Server(cards)
        code, lines = self.walk(server, "--resume")
        self.assertEqual(code, 0)
        self.assertEqual(min(i for i, _ in server.card_calls()), 25)
        self.assertTrue(any("resuming from cards-2026-10-02-partial.jsonl" in x for x in lines))
        m = self.snapshot()["meta"]
        self.assertEqual((m["found"], m["resumed_ids"]), (40, 24))

    def test_without_resume_an_old_partial_is_moved_aside(self):
        self.walk(Server(deck(range(1, 6)), boom=3))
        server = Server(deck(range(1, 6)))
        self.walk(server)
        self.assertEqual(min(i for i, _ in server.card_calls()), 1)
        self.assertEqual(len(list(self.out.glob("*.old"))), 1)

    def test_a_finished_partial_refinalizes_without_card_requests(self):
        self.walk(Server(deck(range(1, 11))))
        first = self.snapshot()
        for p in self.out.glob("cards-*-t*.json"):
            p.unlink()
        server = Server(deck(range(1, 11)))
        self.walk(server, "--resume")
        self.assertEqual(server.card_calls(), [])
        self.assertEqual(self.snapshot()["teams"], first["teams"])


class TestTopUp(Base):
    def test_merge_moves_adds_and_removes(self):
        cards = deck(range(1, 11))
        self.walk(Server(cards))
        [base] = list(self.out.glob("cards-*-t*.json"))
        before = json.loads(base.read_text())
        moved = dict(cards)
        moved[3] = card(3, "t02", ref=cards[3]["ref"])
        del moved[5]
        moved[12] = card(12, "t03", ref="LAT-04")
        (self.out / "ids.txt").write_text("12\n")
        server = Server(moved, clock={"tick": 1800, "doors": "closed", "t_hours": 14.0, "tick_seconds": 15.0})
        code, _ = self.run_cli(["ids", "3,5", "--ids-file", str(self.out / "ids.txt"), "--base", str(base),
                                "--out", str(self.out)], server)
        self.assertEqual(code, 0)
        self.assertEqual(server.keyed_ids(), [3, 5, 12])
        snap = json.loads((self.out / base.name.replace(f"-t{before['meta']['tick_end']}", "-t1800")).read_text())
        m = snap["meta"]
        self.assertEqual((m["mode"], m["removed"], m["added"]), ("topup", [5], [12]))
        self.assertEqual(m["moved"], [{"id": 3, "ref": cards[3]["ref"], "from": cards[3]["owner"], "to": "t02"}])
        owners = {c["id"]: c["owner"] for c in snap["cards"]}
        self.assertEqual((owners[3], owners[12], 5 in owners, len(owners)), ("t02", "t03", False, 10))
        self.assertEqual(sum(t["cards"] for t in snap["teams"].values()), 10)
        self.assertEqual(snap["teams"]["t03"]["by_ref"].get("LAT-04"), 1)
        self.assertEqual(json.loads(base.read_text()), before)           # the base is never rewritten

    def test_bad_base_exits_2(self):
        (self.out / "nope.json").write_text("{}")
        code, _ = self.run_cli(["ids", "1", "--base", str(self.out / "nope.json"), "--out", str(self.out)],
                               Server({}))
        self.assertEqual(code, 2)


class TestSummary(Base):
    def test_teams_add_up_and_print_per_team(self):
        cards = deck(range(1, 13))
        cards[1] = card(1, "t03", ref="LAV-01")
        cards[4] = card(4, "t03", ref="LAV-01")
        cards[5] = card(5, "abuela")                                      # a dealer's card
        cards[6] = card(6, None)                                          # burned, no owner
        cards[7] = {"id": 7, "kind": "pack", "ref": "sobre_barrio", "owner": "t02"}
        self.walk(Server(cards))
        snap = self.snapshot()
        owned = [c for c in snap["cards"] if (c["owner"] or "").startswith("t")]
        self.assertEqual(sum(t["cards"] for t in snap["teams"].values()), len(owned))
        self.assertEqual(snap["meta"]["cards_team_owned"], len(owned))
        self.assertEqual(set(snap["other_owners"]), {"abuela", "none"})
        self.assertEqual([p["id"] for p in snap["packs"]], [7])
        self.assertNotIn(7, [c["id"] for c in snap["cards"]])
        self.assertNotIn("history", json.dumps(snap["cards"]))
        self.assertEqual(snap["cards"][0]["set"], "LAV")
        [path] = [p for p in self.out.glob("cards-*-t*.json")]
        code, lines = self.run_cli(["summary", str(path), "--team", "t03"], Server({}))
        self.assertEqual(code, 0)
        self.assertIn(f"t03  {snap['teams']['t03']['cards']} cards", lines)
        self.assertTrue(any(x.strip().startswith("LAV") and "LAV-01 x2" in x for x in lines))
        self.assertFalse(any(x.startswith("t01") for x in lines))

    def test_set_from_ref_and_nested_shapes(self):
        e, ok = census.normalize(9, {"asset": {"ref": "LAT-05", "name": "n"}, "owner": {"id": "t03"}})
        self.assertTrue(ok)
        self.assertEqual((e["ref"], e["set"], e["owner"]), ("LAT-05", "LAT", "t03"))
        e, ok = census.normalize(9, {"card": {"id": 9, "ref": "LAV-11"}, "owner": "t03"})
        self.assertEqual((e["ref"], ok), ("LAV-11", True))
        e, ok = census.normalize(9, {"name": "no ref, no owner"})
        self.assertFalse(ok)

    def test_with_history_goes_to_its_own_file(self):
        self.walk(Server(deck(range(1, 4))), "--with-history")
        [hist] = list(self.out.glob("cards-*-history.json"))
        self.assertEqual(json.loads(hist.read_text())["2"], [{"tick": 1, "to": "t03"}])
        self.assertNotIn("history", json.dumps(self.snapshot()))


class TestKey(Base):
    def test_one_keyless_try_then_the_key_and_never_shown(self):
        server = Server(deck(range(1, 11)))
        code, lines = self.walk(server)
        self.assertEqual(code, 0)
        calls = server.card_calls()
        self.assertEqual(calls[0][1], {})                                 # keyless first
        self.assertTrue(all(h.get("X-Team-Key") == FAKE_KEY for _, h in calls[1:]))
        self.assertEqual(sum(1 for _, h in calls if not h), 1)            # one keyless try per run, not per id
        self.assertTrue(self.snapshot()["meta"]["keyed"])
        self.assertNotIn(FAKE_KEY, self.all_text(lines))
        self.assertTrue(any("key not shown" in x for x in lines))

    def test_a_key_echoed_in_errors_is_hidden_whatever_its_shape(self):
        body = json.dumps({"error": "boom", "message": f"header was {ODD_KEY}"}).encode()
        server = Server(deck(range(1, 6)), key=ODD_KEY, script={2: [(500, {}, body)]})
        code, lines = self.walk(server, "--max-retries", "1", key=ODD_KEY)
        self.assertEqual(code, 1)
        self.assertNotIn(ODD_KEY, self.all_text(lines))
        self.assertIn("[redacted]", self.snapshot()["meta"]["errors"][0]["message"])

    def test_key_refused_stops_without_showing_it(self):
        server = Server(deck(range(1, 6)), key="tk-other-1111-team")
        code, lines = self.walk(server)
        self.assertEqual(code, 5)
        self.assertEqual(len(server.card_calls()), 2)                    # keyless, then keyed, then stop
        self.assertNotIn(FAKE_KEY, self.all_text(lines))

    def test_no_key_found_stops_at_once(self):
        server = Server(deck(range(1, 6)))
        code, lines = self.walk(server, key=None)
        self.assertEqual(code, 5)
        self.assertEqual(len(server.card_calls()), 1)
        self.assertTrue(any("no team key found" in x for x in lines))

    def test_load_key_reads_the_env_file(self):
        env = self.out / ".env"
        env.write_text(f'# team\nexport BAZAAR_KEY="{FAKE_KEY}"\n')
        with um.patch.dict(census.os.environ, {"BAZAAR_KEY": ""}):
            self.assertEqual(REAL_LOAD_KEY(env), FAKE_KEY)
            self.assertIsNone(REAL_LOAD_KEY(self.out / "missing.env"))


class TestRedaction(Base):
    def test_credential_shaped_text_in_an_error_is_redacted(self):
        msg = "upstream echoed tk-abcd-1234-wxyz and bk_fake_abcdef123456"
        server = Server(deck(range(1, 6)), script={2: [(500, {}, json.dumps({"error": "boom", "message": msg}).encode())]})
        code, lines = self.walk(server, "--max-retries", "1")
        self.assertEqual(code, 1)
        err = self.snapshot()["meta"]["errors"][0]
        self.assertEqual(err["id"], 2)
        self.assertIn("[redacted]", err["message"])
        text = self.all_text(lines)
        self.assertNotIn("tk-abcd-1234-wxyz", text)
        self.assertNotIn("bk_fake_abcdef123456", text)

    def test_credential_shaped_text_in_a_card_payload_is_redacted(self):
        cards = deck(range(1, 4))
        cards[2]["history"] = [{"tick": 5, "note": "pasted tk-qqqq-7777-rrrr by mistake"}]
        self.walk(Server(cards), "--with-history")
        text = self.all_text()
        self.assertNotIn("tk-qqqq-7777-rrrr", text)
        self.assertIn("[redacted]", text)

    def test_network_exception_text_is_redacted(self):
        server = Server(deck(range(1, 4)))
        real = server.__call__

        def flaky(url, headers, timeout=15.0):
            if url.endswith("/api/cards/2") and headers:
                raise OSError("connect failed for tk-zzzz-9999-yyyy")
            return real(url, headers, timeout)
        lines = []
        code = census.main(["run", "--out", str(self.out), "--stop-after", "3", "--max-retries", "2", "--url", URL],
                           fetch=flaky, sleep=self.clock.sleep, now=self.clock.now, key_loader=lambda: FAKE_KEY,
                           say=lines.append)
        self.assertEqual(code, 1)
        self.assertNotIn("tk-zzzz-9999-yyyy", self.all_text(lines))
        self.assertEqual(self.snapshot()["meta"]["errors"][0]["code"], "network")


class TestMarketCheck(Base):
    OPEN = {"tick": 1351, "doors": "open", "t_hours": 12.5833, "tick_seconds": 30.0}

    def test_refuses_when_a_market_test_starts_soon(self):
        sched = {"upcoming": [{"at_hours": 12.6, "action": "bench", "params": {"ticks": 16}}]}
        server = Server(deck(range(1, 4)), clock=self.OPEN, schedule=sched)
        code, lines = self.walk(server)
        self.assertEqual(code, 3)
        self.assertEqual(server.card_calls(), [])

    def test_refuses_during_a_running_market_test(self):
        feed = {"events": [{"type": "bench.started", "tick": 1349, "payload": {"start_tick": 1349, "ticks": 16}}]}
        server = Server(deck(range(1, 4)), clock=self.OPEN, feed=feed)
        self.assertEqual(self.walk(server)[0], 3)
        self.assertEqual(server.card_calls(), [])

    def test_fails_closed_when_the_schedule_is_unreadable(self):
        server = Server(deck(range(1, 4)), clock=self.OPEN, fail=("/api/schedule",))
        code, lines = self.walk(server, "--max-retries", "1")
        self.assertEqual(code, 3)
        self.assertEqual(server.card_calls(), [])
        server = Server(deck(range(1, 4)), clock=self.OPEN, fail=("/api/schedule",))
        self.assertEqual(self.walk(server, "--max-retries", "1", "--skip-market-check")[0], 0)

    def test_open_doors_with_no_test_near_runs_and_pauses_for_a_later_one(self):
        sched = {"upcoming": [{"at_hours": 12.5833 + 6 / 3600 + 120 / 3600, "action": "bench",
                               "params": {"ticks": 16}}]}                # quiet window opens ~6 s into the walk
        server = Server(deck(range(1, 11)), clock=self.OPEN, schedule=sched, live=True)
        code, lines = self.walk(server)
        self.assertEqual(code, 0)
        self.assertTrue(any("quiet window" in x for x in lines))
        self.assertTrue(any(s >= 600 for s in self.clock.sleeps))
        bench = T0 + 126
        self.assertEqual(server.calls_between(bench - 120, bench + 600), [])   # no request of any kind

    def test_closed_doors_skip_the_feed(self):
        server = Server(deck(range(1, 4)))
        self.walk(server)
        public = [u for u, _, _ in server.calls if "/api/cards/" not in u]
        self.assertEqual(public, [URL + "/api/clock", URL + "/api/schedule", URL + "/api/clock"])  # start, end

    def test_manual_quiet_window_holds_even_the_first_request(self):
        start = time.strftime("%H:%M", time.localtime(T0 - 60))
        end = time.strftime("%H:%M", time.localtime(T0 + 600))
        server = Server(deck(range(1, 4)))
        code, _ = self.walk(server, "--quiet", f"{start}-{end}")
        self.assertEqual(code, 0)
        self.assertGreaterEqual(server.calls[0][2], T0 + 540)
        self.assertEqual(server.calls_between(T0 - 600, T0 + 570), [])        # zero calls of any kind

    def test_parse_quiet_runs_past_midnight(self):
        [(a, b)] = census.parse_quiet("23:50-00:10", T0)
        self.assertEqual(b - a, 20 * 60)
        with self.assertRaises(ValueError):
            census.parse_quiet("25:00-26:00", T0)


class TestSilenceReview(Base):
    """The three Market Test findings of the #57 review, each with a fake clock, and the --until hard stop."""
    OPEN = {"tick": 100, "doors": "open", "t_hours": 12.0, "tick_seconds": 30.0}

    def test_1_a_retried_feed_cannot_leave_a_stale_tick(self):
        # the feed answers 503 Retry-After 180; meanwhile a Market Test starts at tick 106 (T0 + 180). The old code
        # placed it with the clock read before the retry (tick 100), dropped it and sent card requests during it.
        def feed(t):
            return {"events": [{"type": "bench.started", "tick": 106, "payload": {"start_tick": 106, "ticks": 16}}]
                    if t >= T0 + 180 else []}
        server = Server(deck(range(1, 11)), clock=self.OPEN, live=True, feed=feed,
                        script={"/api/feed?limit=1000": [(503, {"Retry-After": "180"}, b"")]})
        code, lines = self.walk(server)
        self.assertEqual(code, 3)
        self.assertEqual(server.card_calls(), [])
        urls = [u for u, _, _ in server.calls]
        self.assertEqual(urls[-1], URL + "/api/clock")                      # the anchor clock comes after the feed
        self.assertLess(max(i for i, u in enumerate(urls) if "/api/feed" in u), len(urls) - 1)

    def test_1_the_feed_tick_above_a_clock_tick_is_kept_not_dropped(self):
        clock = {"tick": 100, "tick_seconds": 30.0}
        events = [{"type": "bench.started", "payload": {"start_tick": 106, "ticks": 16}}]
        [(a, b)] = census.running_windows(events, clock, T0)
        self.assertLessEqual(a, T0)
        self.assertGreaterEqual(b, T0 + 600)

    def test_2_closed_doors_stop_before_the_opening(self):
        # doors closed, opening at T0 + 600: a slow scan must not run into the opening; the status is re-read
        # every 2 min meanwhile, and nothing is sent from 2 min before the opening
        opens = T0 + 600
        clock = {"tick": 1445, "doors": "closed", "t_hours": 13.363, "tick_seconds": 30.0,
                 "next_opens": datetime.datetime.fromtimestamp(opens).astimezone().isoformat()}
        server = Server(deck(range(1, 2000)), clock=clock)
        code, lines = self.walk(server)
        self.assertEqual(code, 3)
        self.assertTrue(any("doors open at" in x for x in lines))
        self.assertEqual(server.calls_between(opens - 120, opens + 86400), [])
        clocks = [t for u, _, t in server.calls if u.endswith("/api/clock")]
        self.assertGreaterEqual(len(clocks), 4)                             # T0, +120, +240, +360
        self.assertTrue(all(b - a <= 125 for a, b in zip(clocks, clocks[1:])))
        [partial] = list(self.out.glob("cards-*-partial.jsonl"))
        self.assertGreater(len(partial.read_text().splitlines()), 400)      # progress kept for --resume

    def test_2_open_doors_refresh_and_catch_a_newly_scheduled_test(self):
        # the schedule announces a Market Test only at T0 + 150 (for T0 + 400): a status read once at start would miss
        # it; the 2 min refresh places it and the walk is silent from T0 + 280 to T0 + 1000
        def sched(t):
            return {"upcoming": [{"at_hours": 12.0 + 400 / 3600, "action": "bench", "params": {"ticks": 16}}]
                    if t >= T0 + 150 else []}
        server = Server(deck(range(1, 900)), clock=self.OPEN, live=True, schedule=sched)
        code, _ = self.walk(server)
        self.assertEqual(code, 0)
        self.assertEqual(server.calls_between(T0 + 280, T0 + 1000), [])
        self.assertGreater(max(t for _, _, t in server.calls), T0 + 1000)   # the walk went on after it

    def test_2_a_retried_card_reads_the_status_again_first(self):
        # a 429 with Retry-After 200 on id 3: the status (2 min old by then) is read again before the retry
        server = Server(deck(range(1, 6)), script={3: [(429, {"Retry-After": "200"}, b"")]})
        self.assertEqual(self.walk(server)[0], 0)
        urls = [u for u, _, _ in server.calls]
        first, retry = [k for k, u in enumerate(urls) if u.endswith("/api/cards/3")]
        self.assertIn(URL + "/api/clock", urls[first + 1:retry])

    def test_3_cached_window_refuses_with_zero_requests(self):
        (self.out / census.STATUS_FILE).write_text(json.dumps({"windows": [[T0 - 60, T0 + 600]]}))
        server = Server(deck(range(1, 4)))
        code, lines = self.walk(server)
        self.assertEqual(code, 3)
        self.assertEqual(server.calls, [])                                  # zero transport calls of any kind
        self.assertTrue(any("no request sent" in x for x in lines))

    def test_3_the_previous_run_caches_tomorrows_windows(self):
        # Saturday night (closed): the schedule places Sunday's 10:17 Market Test from day_opens; a top-up started
        # inside it on Sunday is refused with no request
        sun9 = time.mktime((2026, 10, 4, 9, 0, 0, 0, 0, -1))
        sched = {"upcoming": [
            {"at_hours": 13.363, "action": "day_closes", "wall": "x"},
            {"at_hours": 13.363, "action": "day_opens", "params": {"tick_seconds": 15.0},
             "wall": datetime.datetime.fromtimestamp(sun9).astimezone().isoformat()},
            {"at_hours": 14.65, "action": "bench", "params": {"ticks": 16}}]}
        self.walk(Server(deck(range(1, 6)), schedule=sched))
        [base] = list(self.out.glob("cards-*-t*.json"))
        sunday = Clock(sun9 + 1.287 * 3600 + 60)                          # 10:18:13, a minute into the session
        server = Server(deck(range(1, 6)), timer=sunday)
        code = census.main(["ids", "1,2", "--base", str(base), "--out", str(self.out), "--url", URL], fetch=server,
                           sleep=sunday.sleep, now=sunday.now, key_loader=lambda: FAKE_KEY, say=[].append)
        self.assertEqual(code, 3)
        self.assertEqual(server.calls, [])

    def test_until_stops_cleanly_and_resume_finishes(self):
        until = time.strftime("%H:%M", time.localtime(T0 + 90))           # 23:07, 90 s after the start
        server = Server(deck(range(1, 300)))
        code, lines = self.walk(server, "--until", until)
        self.assertEqual(code, 6)
        stop = T0 + 90
        self.assertEqual(server.calls_between(stop, stop + 86400), [])
        [partial] = list(self.out.glob("cards-*-partial.jsonl"))
        n = len(partial.read_text().splitlines())
        self.assertTrue(80 <= n <= 90, n)
        self.assertEqual(list(self.out.glob("cards-*-t*.json")), [])
        self.assertTrue(any("--resume" in x for x in lines))
        server = Server(deck(range(1, 300)))
        self.assertEqual(self.walk(server, "--resume")[0], 0)
        self.assertEqual(min(server.keyed_ids()), n + 1)
        self.assertEqual(self.snapshot()["meta"]["found"], 299)


class TestSelftest(unittest.TestCase):
    def test_selftest_passes_offline(self):
        lines = []
        self.assertEqual(census.main(["selftest"], say=lines.append), 0)
        self.assertFalse(any("FAIL" in x for x in lines))


if __name__ == "__main__":
    unittest.main()
