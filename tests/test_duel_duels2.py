"""agent/duel.py for Duels II: the accept-path review (four reported defects) and the F1-F3 flags.

Defects: (1) an offer replaced between our re-read and the accept POST, (2) the allocator letting the bigger surplus
expire, (3) a skipped re-read wasting the tick's one accept, (4) the duel length taken from DUEL_TICKS instead of the
duel. Flags (off by default): --hold-while-conceding (F1), --silent-last-margin (F2), --open-rung (F3).
No network, no key: the server is a fake. Run: python3 -m unittest discover tests
"""
import contextlib
import hashlib
import io
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import duel  # noqa: E402
import duel_arena as arena  # noqa: E402

FINAL = ROOT / "docs" / "duel-lab" / "duel-params-duels2-final.json"
T10 = ROOT / "docs" / "duel-lab" / "duel-params-duels2-tuned-plus10.json"


def cfg(*argv):
    return duel.make_cfg(["watch", *argv])


def msg(tick, price, days=None, frm="Rival X"):
    return {"tick": tick, "from": frm, "text": "", "price": price, "days": days}


def live(did=1, role="seller", limit=100, deadline=116, msgs=(), offer=None, two=False, weight=None):
    return {"duel": did, "session": 3, "status": "live", "role": role, "item": "Taxi",
            "issues": ["price", "days"] if two else ["price"], "your_days_weight": weight if two else None,
            "days_meaning": None, "your_limit": limit, "rival": "Rival X", "deadline_tick": deadline,
            "decay_per_round": 0.08, "rounds": 0, "your_offer": None, "rival_offer": offer, "messages": list(msgs),
            "result": None, "price": None, "days": None}


def acc(left, rs, dl=100, kind="window", did=1):
    st = duel.DuelState({"duel": did, "deadline_tick": dl}, dl - 16, 16)
    return ({"duel": did, "deadline_tick": dl}, st, {"action": "accept", "kind": kind, "left": left,
                                                     "rival_surplus": rs, "why": "test"})


class Log:
    def __init__(self):
        self.events = []

    def event(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class FakeB:
    """GET /api/duels and POST accept. `script` maps a call number of duels() to a change applied before it answers;
    `before_accept` changes the standing offer between our re-read and the POST (the race the API cannot close)."""

    def __init__(self, duels, script=None, before_accept=None):
        self.views = {d["duel"]: json.loads(json.dumps(d)) for d in duels}   # the server's own copy
        self.script, self.before_accept = script or {}, before_accept
        self.reads, self.accepted = 0, []

    def duels(self, done=False):
        self.reads += 1
        if self.reads in self.script:
            self.script[self.reads](self.views)
        return {"duels": [json.loads(json.dumps(d)) for d in self.views.values()]}

    def duel_accept(self, did):
        if self.before_accept:
            self.before_accept(self.views)
        o = self.views[did]["rival_offer"]
        self.accepted.append((did, o["price"], o.get("days")))
        return {"queued": True, "price": o["price"], "days": o.get("days"), "settles_at_tick": 0}


# ---------------------------------------------------------------- defect 2: the allocator

class Allocator(unittest.TestCase):
    def actions(self, decs, c=None):
        return [x[2]["action"] for x in duel.allocate(decs, c or cfg(), late=True)]

    def test_two_duels_on_their_last_tick_the_bigger_surplus_takes_the_slot(self):
        # reported: surpluses 50 and 5 sharing the last tick took the 5 and let the 50 expire
        self.assertEqual(self.actions([acc(1, 50, did=1), acc(1, 5, did=3)]), ["accept", "hold"])
        self.assertEqual(self.actions([acc(1, 5, did=3), acc(1, 50, did=1)]), ["hold", "accept"])

    def test_the_urgent_one_still_goes_first_when_both_can_be_saved(self):
        self.assertEqual(self.actions([acc(3, 50, did=1), acc(1, 5, did=3)]), ["hold", "accept"])
        self.assertEqual(self.actions([acc(5, 30), acc(5, 20, did=3), acc(1, 5, 96, did=5)]),
                         ["hold", "hold", "accept"])
        self.assertEqual(self.actions([acc(3, 10), acc(3, 30, did=3), acc(3, 20, did=5)]), ["hold", "accept", "hold"])

    def test_three_on_two_ticks_keep_the_two_biggest(self):
        decs = [acc(2, 50, did=1), acc(2, 40, did=3), acc(1, 5, did=5)]
        self.assertEqual(self.actions(decs), ["accept", "hold", "hold"])
        self.assertEqual([x[2].get("slot_rank") for x in decs], [None, 1, 2])   # the 5 is last in line


# ---------------------------------------------------------------- defects 1 and 3: the accept itself

def two_issue_duel(did=1, offer=(90, 0), oid=7):
    """We buy (value 100), 3 P per day away from day 0."""
    return live(did, role="buyer", limit=100, two=True, weight=3, msgs=[msg(105, offer[0], offer[1])],
                offer={"id": oid, "price": offer[0], "tick": 105, "days": offer[1]})


def replace(did, price, days, oid):
    def f(views):
        views[did]["rival_offer"] = {"id": oid, "price": price, "tick": 110, "days": days}
        views[did]["messages"].append(msg(110, price, days))
    return f


class AcceptRace(unittest.TestCase):
    def go(self, b, duels_, c=None):
        c = c or cfg()
        pairs = [(d, duel.DuelState(d, 100, 16)) for d in duels_]
        decs = duel.allocate([(d, st, duel.decide(d, st, 114, c)) for d, st in pairs], c, late=True)
        run = Log()
        sent = duel.try_accepts(b, run, duel.accept_candidates(decs), 114, c)
        return sent, run

    def test_a_worse_offer_seen_by_the_reread_is_never_accepted(self):
        d = two_issue_duel()
        b = FakeB([d], script={1: replace(1, 99, 10, 8)})          # replaced before our re-read
        sent, run = self.go(b, [d])
        self.assertFalse(sent)
        self.assertEqual(b.accepted, [])
        self.assertIn("accept_skipped", run.kinds())

    def test_reproduced_a_replacement_after_the_reread_is_accepted_as_it_stands_and_logged(self):
        # reported defect 1: POST /api/duels/{id}/accept names no offer (kit/RULES.md, bazaar_sdk.duel_accept), so a
        # replacement between the re-read and the POST cannot be refused client-side. It is detected and logged.
        d = two_issue_duel()
        b = FakeB([d], before_accept=replace(1, 99, 10, 8))
        sent, run = self.go(b, [d])
        self.assertTrue(sent)
        self.assertEqual(b.accepted, [(1, 99, 10)])                # the residual risk, as reported
        mism = [kw for k, kw in run.events if k == "accept_mismatch"]
        self.assertEqual(len(mism), 1)
        self.assertEqual(mism[0]["approved"], [90, 0])
        self.assertEqual(mism[0]["surplus"], -29.0)

    def test_terms_are_compared_not_only_the_offer_id(self):
        d = two_issue_duel()
        b = FakeB([d], script={1: replace(1, 90, 10, 7)})          # same id, the day moved: 10 - 30 < 0
        sent, _ = self.go(b, [d])
        self.assertFalse(sent)
        self.assertEqual(b.accepted, [])


class AcceptFallback(unittest.TestCase):
    """Reported defect 3: the chosen duel's offer changes before the re-read; the tick's one accept was wasted."""

    def duels_(self):
        a = live(1, limit=100, msgs=[msg(110, 140)], offer={"id": 1, "price": 140, "tick": 110, "days": 0})
        b = live(3, limit=100, msgs=[msg(110, 120)], offer={"id": 2, "price": 120, "tick": 110, "days": 0})
        return a, b

    def go(self, script):
        a, b_ = self.duels_()
        b = FakeB([a, b_], script=script)
        c = cfg()
        pairs = [(d, duel.DuelState(d, 100, 16)) for d in (a, b_)]
        decs = duel.allocate([(d, st, duel.decide(d, st, 114, c)) for d, st in pairs], c, late=True)
        self.assertEqual([x[2]["action"] for x in decs], ["accept", "hold"])   # 40 first, 20 held
        run = Log()
        duel.try_accepts(b, run, duel.accept_candidates(decs), 114, c)
        return b, run

    def test_a_worse_offer_on_the_chosen_duel_passes_the_accept_to_the_next_one(self):
        b, run = self.go({1: replace(1, 105, None, 9)})
        self.assertEqual([x[:2] for x in b.accepted], [(3, 120)])
        self.assertEqual(run.kinds().count("accept_skipped"), 1)

    def test_a_better_offer_on_the_chosen_duel_is_taken(self):
        b, run = self.go({1: replace(1, 150, None, 9)})
        self.assertEqual([x[:2] for x in b.accepted], [(1, 150)])
        self.assertEqual(next(kw for k, kw in run.events if k == "accept")["taken"], "better")

    def test_late_pass_uses_the_same_fallback(self):
        a, b_ = self.duels_()
        b = FakeB([a, b_], script={2: replace(1, 105, None, 9)})   # read 1: the late read, read 2: the re-read
        b.clock = lambda: {"tick": 114, "paused": False, "next_tick_in": 0, "tick_seconds": 30}
        states = {1: duel.DuelState(a, 100, 16), 3: duel.DuelState(b_, 100, 16)}
        run = Log()
        self.assertTrue(duel.late_pass(b, run, cfg("--late-poll", "8"), states, 114, True, 0.0))
        self.assertEqual([x[:2] for x in b.accepted], [(3, 120)])


# ---------------------------------------------------------------- defect 4: the duel's own length

class DuelLength(unittest.TestCase):
    def test_a_12_tick_duel_seen_on_its_first_tick_is_12_ticks_long(self):
        d = live(deadline=212)                        # Duels III: 12 ticks, first seen at tick 200
        st = duel.DuelState(d, 200, 16)
        self.assertEqual((st.total, st.start), (12, 200))
        c = cfg("--absent-at", "0.2")
        self.assertEqual(duel.decide(d, st, 200, c)["action"], "hold")    # reported: conceded on its first tick
        self.assertEqual(duel.decide(d, st, 203, c)["action"], "say")     # ceil(0.2 x 12) = 3 ticks in

    def test_joining_mid_way_never_assumes_a_shorter_duel(self):
        d = live(deadline=212, msgs=[msg(203, 150)], offer={"id": 1, "price": 150, "tick": 203, "days": 0})
        self.assertEqual(duel.DuelState(d, 206, 16).total, 16)


# ---------------------------------------------------------------- the two-issue path (audit items 1-4, 6)

def days_duel(role, weight, meaning):
    d = live(role=role, two=True, weight=weight)
    d["days_meaning"] = meaning
    return d


class DaysProfile(unittest.TestCase):
    def test_a_named_direction_is_not_flipped_again_by_a_negative_weight(self):
        # item 1: the server both names the direction and signs the weight
        self.assertEqual(duel.days_profile(days_duel("buyer", -2.0, "each day later costs you this much")), (0, 2.0))
        self.assertEqual(duel.days_profile(days_duel("seller", -2.0, "each day earlier costs you this much")),
                         (10, 2.0))
        self.assertEqual(duel.days_profile(days_duel("buyer", 2.0, "each day later costs you this much")), (0, 2.0))

    def test_without_a_named_direction_the_sign_still_flips_the_role_default(self):
        self.assertEqual(duel.days_profile(days_duel("buyer", -2.0, None)), (10, 2.0))
        self.assertEqual(duel.days_profile(days_duel("buyer", 2.0, "")), (0, 2.0))
        self.assertEqual(duel.days_profile(days_duel("seller", -1.5, "delivery day")), (0, 1.5))

    def test_days_best_per_role_and_the_old_global_form(self):
        b, s = days_duel("buyer", 2.0, None), days_duel("seller", 2.0, None)
        self.assertEqual([duel.days_profile(x, "buyer:10,seller:0")[0] for x in (b, s)], [10, 0])
        self.assertEqual([duel.days_profile(x, "seller:0")[0] for x in (b, s)], [0, 0])     # buyer left on auto
        self.assertEqual([duel.days_profile(x, "10")[0] for x in (b, s)], [10, 10])
        self.assertEqual(cfg("--days-best", "buyer:0,seller:10").days_best, "buyer:0,seller:10")
        for bad in ("5", "buyer:3", "trader:0", "buyer0"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                cfg("--days-best", bad)


class TwoIssuePayload(unittest.TestCase):
    def test_a_two_issue_message_carries_a_top_level_days_and_the_offer(self):
        self.assertEqual(duel.say_body("hi", 120, 3),
                         {"text": "hi", "price": 120, "days": 3, "offer": {"price": 120, "days": 3}})

    def test_post_say_uses_that_body_and_the_kit_for_price_only(self):
        calls = []

        class B:
            def _call(self, method, path, body=None, **kw):
                calls.append((method, path, body))
                return {"ok": True}

            def duel_say(self, did, text, price=None, days=None):
                calls.append(("kit", did, price, days))
                return {"ok": True}
        duel.post_say(B(), 7, "hi", 120, 0)
        duel.post_say(B(), 7, "hi", 120, None)
        self.assertEqual(calls, [("POST", "/api/duels/7/messages",
                                  {"text": "hi", "price": 120, "days": 0, "offer": {"price": 120, "days": 0}}),
                                 ("kit", 7, 120, None)])


class RivalNamesOurBestDay(unittest.TestCase):
    def test_we_offer_our_best_day_with_no_premium(self):
        d = live(role="seller", limit=100, two=True, weight=0.5)               # cheap days, our best day is 10
        c = cfg()
        p, days = duel.planned_offer(d, 0, c, (150, 10), False)
        self.assertEqual((p, days), (155, 10))                                  # not day 0 plus a premium
        self.assertEqual(duel.planned_offer(d, 0, c, (150, 0), False)[1], 0)    # the rival wants day 0: give it


class WindowRetry(unittest.TestCase):
    def test_default_keeps_deadline_minus_one_as_retry_and_zero_waits_for_it(self):
        def run(*argv):
            c = cfg("--accept-any-ticks", "2", "--near-ticks", "0", *argv)
            d = conceding()
            st = duel.DuelState(d, 100, 16)
            duel.set_windows([(d, st)], c)
            return duel.allocate([(d, st, duel.decide(d, st, 114, c))], c, late=True)[0][2]["action"]
        self.assertEqual(run(), "accept")                       # lone duel at deadline-2: taken (retry at D-1)
        self.assertEqual(run("--window-retry", "0"), "hold")    # waits for deadline-1


class EarlyAcceptOff(unittest.TestCase):
    def test_early_share_99_disables_the_early_accept_even_with_a_paired_limit(self):
        d = live(limit=100, msgs=[msg(103, 190)], offer={"id": 1, "price": 190, "tick": 103, "days": 0})
        st = duel.DuelState(d, 100, 16)
        st.pair_l = 200                                          # soft pie 100, offer worth 90
        self.assertEqual(duel.decide(d, st, 104, cfg())["kind"], "early")
        self.assertEqual(duel.decide(d, st, 104, cfg("--params", str(FINAL)))["action"], "hold")
        self.assertEqual(json.loads(FINAL.read_text())["early_share"], 99)


# ---------------------------------------------------------------- F1: hold while the rival is conceding

def conceding(did=1, deadline=116, last=(113, 130), prev=(112, 125)):
    return live(did, limit=100, deadline=deadline, msgs=[msg(*prev), msg(*last)],
                offer={"id": did, "price": last[1], "tick": last[0], "days": 0})


class HoldWhileConceding(unittest.TestCase):
    F1 = ("--hold-while-conceding", "--accept-any-ticks", "2", "--near-ticks", "0")

    def step(self, d, tick, *argv, others=()):
        c = cfg(*argv)
        pairs = [(x, duel.DuelState(x, x["deadline_tick"] - 16, 16)) for x in (d, *others)]
        duel.set_windows(pairs, c)
        return duel.allocate([(x, st, duel.decide(x, st, tick, c)) for x, st in pairs], c, late=True)[0][2]

    def test_off_by_default_it_accepts_at_deadline_minus_two(self):
        self.assertEqual(self.step(conceding(), 114, "--accept-any-ticks", "2", "--near-ticks", "0")["action"],
                         "accept")

    def test_on_it_waits_at_deadline_minus_two_and_accepts_at_deadline_minus_one(self):
        dec = self.step(conceding(), 114, *self.F1, "--no-hold-counter")
        self.assertEqual(dec["action"], "hold")
        self.assertIn("still conceding", dec["why"])
        self.assertEqual(self.step(conceding(), 115, *self.F1, "--no-hold-counter")["action"], "accept")

    def test_a_repeated_number_ends_the_wait(self):
        self.assertEqual(self.step(conceding(prev=(112, 130)), 114, *self.F1)["action"], "accept")

    def test_no_wait_when_the_slots_would_not_fit(self):
        other = conceding(did=3, last=(113, 125), prev=(112, 120))
        decs = [self.step(conceding(), 114, *self.F1, "--no-hold-counter", others=(other,))]
        self.assertEqual(decs[0]["action"], "accept")          # two duels, two ticks: the bigger goes now

    def test_the_counter_is_one_rung_up_and_only_when_it_beats_the_offer_by_a_round(self):
        dec = self.step(conceding(last=(113, 112), prev=(112, 106)), 114, *self.F1)
        self.assertEqual((dec["action"], dec["step"], dec["price"]), ("say", "counter", 155))   # nothing sent: rung 0
        d = conceding()
        st = duel.DuelState(d, 100, 16)
        st.sent, st.last_sent = 1, (155, None)
        self.assertEqual(duel.our_number(d, st, cfg(*self.F1), None, "counter")[0], 122)       # then 100 x 1.22
        st.sent = 2
        self.assertEqual(duel.our_number(d, st, cfg(*self.F1), None, "counter")[0], 108)       # then LAST_R
        dec = self.step(conceding(last=(113, 152), prev=(112, 140)), 114, *self.F1)
        self.assertEqual(dec["action"], "hold")                # 52 beats 55 x 0.92 = 50.6: silent wait


# ---------------------------------------------------------------- F2 and F3: our numbers

class SilentLastMargin(unittest.TestCase):
    def last(self, d, *argv):
        return duel.our_number(d, duel.DuelState(d, 100, 16), cfg(*argv), None, "last")

    def test_a_silent_rival_gets_limit_plus_minus_the_margin(self):
        self.assertEqual(self.last(live(), "--silent-last-margin", "0.05")[0], 105)
        self.assertEqual(self.last(live(role="buyer", limit=120), "--silent-last-margin", "0.05")[0], 114)
        self.assertEqual(self.last(live())[0], 108)                                      # off: LAST_R 1.08

    def test_a_rival_that_spoke_keeps_the_last_ratio(self):
        d = live(msgs=[msg(105, 80)], offer={"id": 1, "price": 80, "tick": 105, "days": 0})
        self.assertEqual(self.last(d, "--silent-last-margin", "0.05")[0], 108)


class OpenRung(unittest.TestCase):
    def anchor(self, d, *argv):
        return duel.our_number(d, duel.DuelState(d, 100, 16), cfg(*argv), None, "anchor")

    def test_the_anchor_opens_at_the_chosen_rung(self):
        self.assertEqual(self.anchor(live())[0], 155)
        self.assertEqual(self.anchor(live(), "--open-rung", "1")[0], 122)
        self.assertEqual(self.anchor(live(), "--open-rung", "9")[0], 122)       # clamped to the last rung

    def test_two_issues_the_first_message_names_both(self):
        d = live(role="seller", limit=100, two=True, weight=0.5)                # days cheap: 5 <= 0.1 x 100
        p, days = self.anchor(d, "--open-rung", "1")
        self.assertEqual(days, 0)                       # the day a buyer wants, not our best (10)
        self.assertGreater(p, 122)                      # and our days cost asked back in price


# ---------------------------------------------------------------- flags off: unchanged decisions

def random_states(n=1500, seed=11):
    """Random duel states for decide() and our_number(), price-only and two-issue (as in duel.py's rule fuzz)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        role = rng.choice(["seller", "buyer"])
        L = rng.randint(20, 200)
        dl = 500 + rng.randint(1, 16)
        tick = dl - rng.randint(-1, 16)
        two = rng.random() < 0.3
        d = {"duel": rng.randint(1, 300), "role": role, "your_limit": L, "deadline_tick": dl, "rival": "Rival X",
             "issues": ["price", "days"] if two else ["price"],
             "your_days_weight": round(rng.uniform(-3, 3), 2) if two else None, "decay_per_round": 0.08,
             "messages": [], "rival_offer": None}
        best = (0 if role == "buyer" else 10) if not two or d["your_days_weight"] >= 0 else \
            (10 if role == "buyer" else 0)
        days_pool = [x for x in range(11) if x != best]   # the rival naming our best day is item 4's fix (on)
        for t in sorted(rng.sample(range(dl - 16, dl), rng.randint(0, 8))):
            d["messages"].append({"tick": t, "from": "Rival X", "text": "", "price": int(L * rng.uniform(0.4, 2.2)),
                                  "days": rng.choice(days_pool) if two else None})
        if d["messages"] and rng.random() < 0.9:
            m = d["messages"][-1]
            d["rival_offer"] = {"id": rng.randint(1, 9999), "price": m["price"], "tick": m["tick"],
                                "days": m["days"] if two else 0}
        pair = rng.choice([None, int(L * rng.uniform(0.5, 2.5))])
        sent = rng.randint(0, 2)
        last = (int(L * rng.uniform(1.01, 1.8)) if role == "seller" else int(L / rng.uniform(1.01, 1.8)),
                rng.randint(0, 10) if two else None) if sent else None
        out.append((d, tick, pair, sent, last))
    return out


def decisions_digest(mod, params: dict) -> str:
    """sha256 of every decide() and our_number() output over random_states(), for one params set."""
    c = mod.make_cfg(["watch"] + [x for k, v in params.items() for x in (f"--{k.replace('_', '-')}", str(v))])
    rows = []
    for d, tick, pair, sent, last in random_states():
        st = mod.DuelState(d, d["deadline_tick"] - 16, 16)
        st.pair_l, st.sent, st.last_sent = pair, sent, last
        dec = mod.decide(d, st, tick, c)
        nums = [mod.our_number(d, st, c, mod.parse_offer(d["rival_offer"]), k) for k in ("anchor", "absent", "last")]
        rows.append([dec, nums])
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


# computed with agent/duel.py at origin/main e59d10d (before this change), same generator
DIGEST_DEFAULTS = "55f4ea52c284bd516669463b0218da2416b544620212d7aa0ec2bd6018c36147"
DIGEST_T10 = "b0d746679702fea55627f3430ef870d90b2957db68dcceecb04d0457f61669cd"
T10_FLAGS = {"ratios": "1.55,1.277", "last_r": 1.103, "last_chance_ticks": 4, "accept_any_ticks": 2, "near_ticks": 0,
             "stall_ticks": 4, "early_share": 0.85, "early_min_pie": 5.373, "pair_sell": 0.965, "pair_buy": 1.07,
             "absent_at": 0.552, "absent_share": 0.371, "days_cheap": 0.153, "days_premium": "0.629,0.087",
             "last_share": 0.3}


class FlagsOff(unittest.TestCase):
    def test_decide_and_our_numbers_are_unchanged_with_the_new_flags_off(self):
        self.assertEqual(decisions_digest(duel, {}), DIGEST_DEFAULTS)
        self.assertEqual(decisions_digest(duel, T10_FLAGS), DIGEST_T10)

    def test_the_final_params_load_and_pass_the_simulation(self):
        c = duel.make_cfg(["selftest", "--params", str(FINAL)])
        res = duel.simulate(duel, c, n_duels=600, seed=5)
        self.assertEqual(res["violations"], [])
        self.assertLessEqual(res["max_sends"], c.max_msgs)

    def test_the_final_params_use_only_keys_an_older_duel_py_knows(self):
        # the Mini may run the file before pulling this branch: no new key may crash load_params there
        self.assertLessEqual(set(json.loads(FINAL.read_text())), set(json.loads(T10.read_text())))


# ---------------------------------------------------------------- the arena's replays

class Replays(unittest.TestCase):
    def test_the_friday_replay_reads_only_friday(self):
        self.assertTrue(all(d["session"] == 1 for d in arena.friday_duels()))
        self.assertTrue(all(d["session"] == 2 for d in arena.duels1_duels()))

    def test_the_duels1_replay_never_crosses_our_limit_and_counts_real_results(self):
        rr = arena.duels1_replay(json.loads(T10.read_text()))
        self.assertGreater(len(rr), 20)
        for r in rr:
            if r["deal"]:
                self.assertGreaterEqual(r["result"], 0)
        self.assertGreater(sum(r["real_result"] for r in rr), 0)

    def test_hiding_the_paired_limit_changes_play(self):
        p = json.loads(T10.read_text())
        seen = arena.summary(arena.evaluate(p, range(10), 2))["all"]["mean"]
        saved = arena.PAIR_SEEN
        arena.PAIR_SEEN = 0.0
        try:
            rr = arena.evaluate(p, range(10), 2)
        finally:
            arena.PAIR_SEEN = saved
        self.assertTrue(all(r["pair_limit"] is None for r in rr))
        self.assertNotEqual(arena.summary(rr)["all"]["mean"], seen)


if __name__ == "__main__":
    unittest.main()
