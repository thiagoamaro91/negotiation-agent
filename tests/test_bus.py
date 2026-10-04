"""Team bus: message format, addressing, the wait cursor, ask/answer matching and the who-runs-what board.

    python3 -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import bus  # noqa: E402

T0 = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
HECTOR, THIAGO, THIRD = bus.TEAM["hector"], bus.TEAM["thiago"], bus.TEAM["member3"]


class FakeGitHub:
    """The issue as an in-memory comment list; `as_` switches who is logged in. Optional scripted failures."""

    def __init__(self, clock):
        self.repo, self.issue = "t03/negotiation-agent", 7
        self.clock, self.items, self.next_id, self.user, self.body = clock, [], 1000, HECTOR, ""
        self.fail_next, self.on_poll = 0, None

    def as_(self, login):
        self.user = login
        return self

    def login(self):
        return self.user

    def add(self, body, user=None, at=None):
        self.next_id += 1
        c = {"id": self.next_id, "created_at": bus.iso(at or self.clock.t), "body": body,
             "html_url": f"https://github.com/x/issues/7#issuecomment-{self.next_id}", "user": user or self.user}
        self.items.append(c)
        return dict(c)

    def post(self, body):
        return self.add(body)

    def comments(self, since=None):
        if self.on_poll:
            self.on_poll(self)
        if self.fail_next:
            self.fail_next -= 1
            raise bus.GhError("boom")
        return [dict(c) for c in self.items if since is None or c["created_at"] >= since]

    def set_issue_body(self, body):
        self.body = body


class Clock:
    def __init__(self):
        self.t = T0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


def make(session="mac", user=HECTOR, state=None, clock=None):
    clock = clock or Clock()
    gh = FakeGitHub(clock).as_(user)
    lines = []
    b = bus.Bus(gh, session, state=Path(state or tempfile.mkdtemp()), sleep=clock.sleep, now=clock.now,
                out=lines.append)
    return b, gh, clock, lines


def body(kind="info", text="hi", to=("all",), session="mini", reply_to=None, extra=None):
    return bus.format_body(kind, text, list(to), session, reply_to, extra)


class Format(unittest.TestCase):
    def test_round_trip(self):
        c = {"id": 5, "user": THIAGO, "created_at": "2026-10-03T12:00:00Z",
             "body": body("ask", "restart market?\n\nsecond paragraph", [HECTOR], "mini", 4)}
        m = bus.parse(c)
        self.assertEqual((m["kind"], m["to"], m["session"], m["reply_to"], m["human"]),
                         ("ask", [HECTOR], "mini", 4, False))
        self.assertEqual(m["text"], "restart market?\n\nsecond paragraph")
        self.assertEqual(m["from"], THIAGO)

    def test_ask_pings_and_info_does_not(self):
        self.assertIn(f"@{THIAGO}", body("ask", to=[THIAGO]).splitlines()[1])
        self.assertNotIn("@", body("info", to=[THIAGO]).splitlines()[1])

    def test_sender_comes_from_github_not_the_body(self):
        forged = '<!-- team-bus {"v":1,"kind":"info","to":["all"],"session":"x","from":"thiagoamaro91"} -->\nl\n\nt'
        self.assertEqual(bus.parse({"id": 1, "user": THIRD, "created_at": "x", "body": forged})["from"], THIRD)

    def test_typed_comment_goes_to_mentions_or_all(self):
        m = bus.parse({"id": 1, "user": THIAGO, "created_at": "x", "body": "@hector14mv stop the market please"})
        self.assertTrue(m["human"])
        self.assertEqual(m["to"], [HECTOR])
        self.assertEqual(bus.parse({"id": 2, "user": THIAGO, "created_at": "x", "body": "@hector and @member3 look"})["to"],
                         [HECTOR, THIRD])
        self.assertEqual(bus.parse({"id": 3, "user": THIAGO, "created_at": "x", "body": "mail me@hector please"})["to"],
                         ["all"])

    def test_broken_header_is_a_typed_comment(self):
        m = bus.parse({"id": 1, "user": THIRD, "created_at": "x", "body": "<!-- team-bus {nope} -->\nhello"})
        self.assertTrue(m["human"])
        self.assertEqual(m["to"], ["all"])

    def test_resolve(self):
        self.assertEqual(bus.resolve(["thiago,member3", "@hector14mv"]), [THIAGO, THIRD, HECTOR])
        self.assertEqual(bus.resolve([]), ["all"])
        with self.assertRaises(ValueError):
            bus.resolve(["thiagoo"])


class Addressing(unittest.TestCase):
    def msg(self, frm, to, session="mini"):
        return {"from": frm, "to": to, "session": session}

    def test_to_me_or_all(self):
        self.assertTrue(bus.addressed(self.msg(THIAGO, [HECTOR]), HECTOR, "mac"))
        self.assertTrue(bus.addressed(self.msg(THIAGO, ["all"]), HECTOR, "mac"))
        self.assertFalse(bus.addressed(self.msg(THIAGO, [THIRD]), HECTOR, "mac"))

    def test_not_my_own_session_but_my_other_session(self):
        self.assertFalse(bus.addressed(self.msg(HECTOR, ["all"], "mac"), HECTOR, "mac"))
        self.assertTrue(bus.addressed(self.msg(HECTOR, ["all"], "vm"), HECTOR, "mac"))


class Wait(unittest.TestCase):
    def test_first_wait_sees_last_30_minutes_only(self):
        b, gh, clock, out = make()
        gh.add(body(text="old"), user=THIAGO, at=T0 - timedelta(minutes=31))
        gh.add(body(text="recent"), user=THIAGO, at=T0 - timedelta(minutes=5))
        self.assertEqual(b.wait(timeout=60), 0)
        self.assertIn("recent", "\n".join(out))
        self.assertNotIn("old", "\n".join(out))

    def test_cursor_never_repeats_and_never_skips(self):
        b, gh, clock, out = make()
        gh.add(body(text="one"), user=THIAGO)
        self.assertEqual(b.wait(timeout=60), 0)
        out.clear()
        gh.add(body(text="two", to=[THIRD]), user=THIAGO)     # not for me: passed over, cursor moves
        gh.add(body(text="three"), user=THIRD)
        self.assertEqual(b.wait(timeout=60), 0)
        text = "\n".join(out)
        self.assertNotIn("one", text)
        self.assertNotIn("two", text)
        self.assertIn("three", text)
        out.clear()
        self.assertEqual(b.wait(timeout=30), 3)               # nothing new: times out quietly
        self.assertEqual(out, [])

    def test_same_second_comments_are_not_lost(self):
        b, gh, clock, out = make()
        gh.add(body(text="a"), user=THIAGO)
        b.wait(timeout=10)
        out.clear()
        gh.add(body(text="b"), user=THIAGO)                   # same created_at second as "a"
        self.assertEqual(b.wait(timeout=10), 0)
        self.assertIn("  b", "\n".join(out))

    def test_blocks_until_a_message_arrives(self):
        b, gh, clock, out = make()

        def arrive(g):
            if clock.t >= T0 + timedelta(seconds=40) and not g.items:
                g.add(body(text="late", to=[HECTOR]), user=THIAGO)
        gh.on_poll = arrive
        self.assertEqual(b.wait(interval=10, timeout=600), 0)
        self.assertIn("late", "\n".join(out))
        self.assertGreaterEqual(clock.t, T0 + timedelta(seconds=40))

    def test_own_posts_do_not_wake_me(self):
        b, gh, clock, out = make()
        b.post("info", "note to all", ["all"])
        self.assertEqual(b.wait(timeout=30), 3)

    def test_gives_up_after_repeated_failures(self):
        b, gh, clock, out = make()
        gh.fail_next = bus.FAILS_BEFORE_EXIT
        self.assertEqual(b.wait(interval=1), 1)
        self.assertIn("unreachable", out[-1])

    def test_recovers_from_a_few_failures(self):
        b, gh, clock, out = make()
        gh.add(body(text="after hiccup"), user=THIAGO)
        gh.fail_next = 3
        self.assertEqual(b.wait(interval=1, timeout=600), 0)


class Ask(unittest.TestCase):
    def test_answer_by_reply_to(self):
        b, gh, clock, out = make()

        def answer(g):
            ask = next(c for c in g.items if "ask" in c["body"])
            if len(g.items) == 1:
                g.add(body(text="unrelated", to=[HECTOR]), user=THIAGO)
                g.add(body(text="yes, go", to=[HECTOR], reply_to=ask["id"]), user=THIAGO)
        gh.on_poll = answer
        self.assertEqual(b.ask("restart?", [THIAGO], wait=60), 0)
        self.assertIn("yes, go", out[-1])
        self.assertNotIn("unrelated", "\n".join(out))

    def test_answer_typed_on_github_by_the_askee(self):
        b, gh, clock, out = make()

        def answer(g):
            if len(g.items) == 1:
                g.add("ok from my phone", user=THIRD)           # someone else typing does not count
                g.add("go ahead", user=THIAGO)
        gh.on_poll = answer
        self.assertEqual(b.ask("restart?", [THIAGO], wait=60), 0)
        self.assertIn("go ahead", out[-1])

    def test_no_answer_times_out(self):
        b, gh, clock, out = make()
        self.assertEqual(b.ask("anyone?", [THIAGO], wait=30, interval=10), 3)


class SessionName(unittest.TestCase):
    """Hector: every message says which session sent it, by its full name (Codex review of #46 kept old callers working)."""

    def run_main(self, argv, env):
        from unittest import mock
        seen = {}

        class FakeBus:
            def __init__(self, gh, session):
                seen["session"], self.ident = session, ""

            def post(self, kind, text, to, reply_to=None):
                seen["text"] = text
                return {"id": 1, "kind": kind, "to": to, "url": "u"}

            def read(self, last):
                return []

        with mock.patch.dict(bus.os.environ, env, clear=False), mock.patch.object(bus, "Bus", FakeBus), \
                mock.patch.object(bus, "GitHub", lambda repo, issue: None):
            for k in ("TEAM_BUS_SESSION", "TEAM_BUS_TITLE"):
                if k not in env:
                    bus.os.environ.pop(k, None)
            rc = bus.main(argv)
        return rc, seen

    def test_writing_needs_a_session_name(self):
        for argv in (["post", "hi"], ["ask", "ok?", "--wait", "0"], ["claim", "market"], ["release", "market"]):
            self.assertEqual(self.run_main(argv, {})[0], 2, argv)
        for blank in ("", "  "):  # an explicit blank flag is refused even with the env set
            self.assertEqual(self.run_main(["--session", blank, "post", "hi"], {"TEAM_BUS_SESSION": "x"})[0], 2)

    def test_a_post_starts_with_the_full_session_name(self):
        rc, seen = self.run_main(["--title", "Panel de dinero e inferencias", "post", "hi"], {"TEAM_BUS_SESSION": "hector-mac-brain"})
        self.assertEqual((rc, seen["text"]), (0, "FROM: Panel de dinero e inferencias (hector-mac-brain)\nhi"))
        rc, seen = self.run_main(["post", "hi"], {"TEAM_BUS_SESSION": "s", "TEAM_BUS_TITLE": "Mini market"})
        self.assertEqual(seen["text"], "FROM: Mini market (s)\nhi")

    def test_without_a_title_old_callers_still_send_signed_with_the_session_id(self):
        rc, seen = self.run_main(["--session", "thiago-mini-market", "post", "hi"], {})
        self.assertEqual((rc, seen["text"]), (0, "FROM: thiago-mini-market\nhi"))
        rc, seen = self.run_main(["--session", "f8", "post", "FROM: thiago-air-f8 (conductor) | TO: x\nok"], {})
        self.assertEqual(seen["text"], "FROM: thiago-air-f8 (conductor) | TO: x\nok")

    def test_a_padded_name_is_the_same_session_for_posting_and_waiting(self):
        rc, seen = self.run_main(["post", "hi"], {"TEAM_BUS_SESSION": " padded ", "TEAM_BUS_TITLE": "T"})
        self.assertEqual((rc, seen["session"]), (0, " padded "))
        self.assertEqual(self.run_main(["read"], {"TEAM_BUS_SESSION": " padded "})[1]["session"], " padded ")

    def test_an_empty_message_is_refused_before_it_is_signed(self):
        for argv in (["post", ""], ["post", "   "], ["ask", "", "--wait", "0"]):
            rc, seen = self.run_main(argv, {"TEAM_BUS_SESSION": "s", "TEAM_BUS_TITLE": "T"})
            self.assertEqual((rc, "text" in seen), (2, False), argv)

    def test_reads_keep_the_old_session_resolution(self):
        self.assertEqual(self.run_main(["--session", " padded ", "read"], {})[1]["session"], " padded ")
        self.assertEqual(self.run_main(["read"], {"TEAM_BUS_SESSION": "from-env"})[1]["session"], "from-env")

    def test_the_reply_line_carries_the_readers_identity(self):
        msg = {"id": 7, "kind": "ask", "from": "thiagoamaro91", "to": ["hector"], "session": "f8", "human": False,
               "reply_to": None, "at": "t", "text": "q", "url": "u"}
        ident = bus.identity("hector-mac-brain", "Panel de dinero e inferencias")
        self.assertIn("reply: python3 tools/bus.py --session hector-mac-brain --title 'Panel de dinero e inferencias' post",
                      bus.show(msg, ident))
        self.assertIn("reply: python3 tools/bus.py post", bus.show(msg))


class Board(unittest.TestCase):
    def claim(self, frm, what, mid, kind="claim", **kw):
        return {"id": mid, "from": frm, "at": "2026-10-03T12:00:00Z", "kind": kind, "human": False, "what": what, **kw}

    def test_first_claim_wins_and_only_the_holder_releases(self):
        board, lost = bus.replay_claims([
            self.claim(HECTOR, "market", 1, where="vm"),
            self.claim(THIAGO, "market", 2, where="mini"),
            self.claim(THIAGO, "market", 3, kind="release"),
        ])
        self.assertEqual(board["market"]["from"], HECTOR)
        self.assertEqual(lost, {2: HECTOR})

    def test_release_then_claim_and_force(self):
        board, _ = bus.replay_claims([
            self.claim(HECTOR, "market", 1),
            self.claim(HECTOR, "market", 2, kind="release"),
            self.claim(THIAGO, "market", 3),
            self.claim(THIRD, "market", 4, force=True),
        ])
        self.assertEqual(board["market"]["from"], THIRD)

    def test_claim_command_refuses_held_item_and_posts_nothing(self):
        b, gh, clock, out = make(user=THIAGO, session="mini")
        self.assertEqual(b.claim("market", where="mini", note="swaps on"), 0)
        self.assertIn("| market | thiago | mini |", gh.body)
        n = len(gh.items)
        gh.as_(HECTOR)
        b._me = None
        self.assertEqual(b.claim("Market", where="vm"), 4)
        self.assertEqual(len(gh.items), n)
        self.assertEqual(b.release("market"), 4)
        gh.as_(THIAGO)
        b._me = None
        self.assertEqual(b.release("market"), 0)
        self.assertIn("(nothing claimed)", gh.body)

    def test_lost_race_is_reported(self):
        b, gh, clock, out = make(user=HECTOR)
        real_post = gh.post

        def racing_post(text):                                # Thiago's claim lands just before mine
            gh.add(body("claim", "claim market", session="mini", extra={"what": "market"}), user=THIAGO)
            return real_post(text)
        gh.post = racing_post
        self.assertEqual(b.claim("market"), 4)
        self.assertIn("lost the race", out[-1])
        self.assertIn("| market | thiago |", gh.body)

    def test_claims_are_not_wake_ups_for_others_only_if_to_all(self):
        m = bus.parse({"id": 9, "user": THIAGO, "created_at": "x",
                       "body": body("claim", "claim market", extra={"what": "market"})})
        self.assertEqual((m["kind"], m["what"], m["to"]), ("claim", "market", ["all"]))


if __name__ == "__main__":
    unittest.main()
