"""tools/analyst.py (the Sunday analyst on duty) and the two duel_matrix.py flags it needs (--mix, --d1-stress): the
pure reads (expiries, latency, the bench verdict, duel loss causes, levers, candidates, the 2 SE pick, ladder values,
v20 activity, score deltas), plus the Saturday logs end to end. Offline: no key, no network.
Run: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
import unittest.mock as um
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
import analyst as an  # noqa: E402
import duel_matrix as dm  # noqa: E402


def setUpModule():
    def no_network(*a, **k):
        raise AssertionError("a test tried to reach the network")
    p = um.patch("urllib.request.urlopen", no_network)
    p.start()
    unittest.addModuleCleanup(p.stop)


# ---------------------------------------------------------------- bench

class Expiries(unittest.TestCase):
    def tr(self, *exps):
        return {f"b1-{i}": {"expires": e} for i, e in enumerate(exps)}

    def test_all_at_the_session_end_carry_nothing(self):
        r = an.expiry_read(self.tr(457, 457, 457), 457)
        self.assertFalse(r["differs"])
        self.assertEqual(r["early"], 0)

    def test_distinct_expiries_make_ours_a_candidate(self):
        self.assertTrue(an.expiry_read(self.tr(450, 457, 457), 457)["differs"])

    def test_two_expiries_one_off_the_end_still_differ(self):
        r = an.expiry_read(self.tr(456, 457), 457)
        self.assertEqual(r["early"], 0)
        self.assertTrue(r["differs"])

    def test_one_shared_early_expiry_also_differs(self):
        r = an.expiry_read(self.tr(450, 450), 457)
        self.assertTrue(r["differs"])
        self.assertEqual(r["early"], 2)

    def test_no_expiry_shown(self):
        r = an.expiry_read(self.tr(None, None), 457)
        self.assertFalse(r["differs"])
        self.assertEqual(r["shown"], 0)

    def test_session_end_unknown_uses_the_latest_expiry(self):
        self.assertFalse(an.expiry_read(self.tr(457, 457), None)["differs"])


class Windows(unittest.TestCase):
    def test_the_session_that_contains_the_first_tick(self):
        starts = [(201, 16, 1, ""), (441, 16, 2, ""), (681, 16, 3, "")]
        self.assertEqual(an.session_window(442, starts), (441, 457, 2))
        self.assertEqual(an.session_window(600, starts), (None, None, None))


class Latency(unittest.TestCase):
    def test_ticks_from_first_cross_to_the_match(self):
        states = [(10, "a"), (11, "b"), (12, "c")]
        cross = {"a": set(), "b": {("s1", "b1")}, "c": {("s1", "b1"), ("s2", "b2")}}
        first = an.first_cross(states, lambda book: cross[book])
        self.assertEqual(first[("s1", "b1")], (11, 1))
        self.assertEqual(an.latency([(13, "s1", "b1", 50), (12, "s2", "b2", 40), (12, "s9", "b9", 1)], first), [2, 0])


class PickSession(unittest.TestCase):
    S = {"b53": {"states": [(681, {})]}, "b104": {"states": [(1401, {})]}}

    def test_latest_is_the_newest_finished_run(self):
        self.assertEqual(an.pick_session("latest", self.S, {}, {"b53": 695, "b104": 1415}, [(1401, 16, 6, "")]),
                         ("b104", ""))

    def test_an_unfinished_newest_run_is_pending_not_the_previous_verdict(self):
        name, why = an.pick_session("latest", self.S, {"b999": "in progress"}, {"b104": 1415, "b999": 1500}, [])
        self.assertIsNone(name)
        self.assertIn("b999", why)

    def test_a_test_the_feed_started_but_the_log_lacks_is_pending(self):
        name, why = an.pick_session(None, self.S, {}, {"b104": 1415}, [(1401, 16, 6, ""), (1641, 16, 7, "")])
        self.assertIsNone(name)
        self.assertIn("1641", why)

    def test_explicit_sessions(self):
        self.assertEqual(an.pick_session("b53", self.S, {}, {}, [])[0], "b53")
        self.assertIsNone(an.pick_session("b999", self.S, {"b999": "in progress"}, {}, [])[0])
        self.assertIsNone(an.pick_session("b7", self.S, {}, {}, [])[0])
        self.assertIsNone(an.pick_session("latest", {}, {}, {}, [])[0])


class OursPath(unittest.TestCase):
    def test_bench_run_end_expiries(self):
        rows = [{"event": "bench_run_end", "traders": [{"id": "b9-1", "expires": 450}, {"id": "b8-1", "expires": 1}]},
                {"event": "book"}]
        self.assertEqual(an.run_end_expiries(rows, {"b9-1"}), {"b9-1": {"expires": 450}})

    def test_risk_note_and_switch_commands(self):
        note = an.ours_risk_note()
        self.assertIn("fitted_expiry_exact", note)
        self.assertIn("0 → 3", note)
        cmds = " ".join(an.OURS_SWITCH)
        for part in ("tmux kill-window -t factory:broker", "tools/factory_sunday.json", "factory.py up --yes"):
            self.assertIn(part, cmds)


class BenchVerdict(unittest.TestCase):
    def ok(self, **kw):
        r = {"dropped_live": 0, "dropped_why": [], "refused": 0, "read_errors": 0, "best": 100.0, "live_gain": 90.0,
             "replay_gain": 90.0, "lat": [0, 1], "live_n": 3, "replay_n": 3}
        r.update(kw)
        return an.bench_verdict(r)

    def test_clean_session(self):
        self.assertEqual(self.ok()[0], "stall behaved")

    def test_each_problem_is_named(self):
        for kw, word in [({"dropped_live": 2, "dropped_why": ["same_maker"]}, "dropped"), ({"refused": 1}, "refused"),
                         ({"read_errors": 1}, "read errors"), ({"live_gain": 50.0}, "below the stall replay"),
                         ({"lat": [2, 3, 0]}, "slow"), ({"live_n": 0, "live_gain": 90.0}, "no match sent")]:
            v, probs = self.ok(**kw)
            self.assertTrue(v.startswith("something is wrong"), kw)
            self.assertTrue(any(word in p for p in probs), (kw, probs))

    def test_one_late_pair_is_not_slow(self):
        self.assertEqual(self.ok(lat=[0, 0, 5])[0], "stall behaved")

    def test_a_small_shortfall_is_tolerated(self):
        self.assertEqual(self.ok(live_gain=86.0)[0], "stall behaved")


# ---------------------------------------------------------------- duels

def duel(status="no_deal", role="seller", limit=50, rival=(), ours=(), deadline=100, two=False, **kw):
    d = {"duel": kw.pop("duel", 1), "session": 4, "status": status, "role": role, "your_limit": limit,
         "issues": ["price", "days"] if two else ["price"], "your_days_weight": kw.pop("w", None),
         "days_meaning": kw.pop("meaning", None), "rival": "Rival Azul", "deadline_tick": deadline, "messages": []}
    for t, p, *dd in rival:
        d["messages"].append({"tick": t, "from": "Rival Azul", "price": p, "days": dd[0] if dd else None})
    for t, p, *dd in ours:
        d["messages"].append({"tick": t, "from": "you", "price": p, "days": dd[0] if dd else None})
    d["messages"].sort(key=lambda m: m["tick"])
    d.update(kw)
    return d


class Classify(unittest.TestCase):
    def test_mute(self):
        self.assertEqual(an.classify_duel(duel(ours=[(90, 70)]))["loss"], "mute")

    def test_an_offer_inside_our_limit_left_untaken(self):
        r = an.classify_duel(duel(rival=[(85, 40), (97, 52)], ours=[(90, 70)]))
        self.assertEqual(r["loss"], "inside_not_taken")
        self.assertEqual((r["best_rival"], r["inside_left"]), (2, 3))

    def test_an_early_rich_offer_left_untaken_is_its_own_cause(self):
        r = an.classify_duel(duel(rival=[(85, 40), (96, 52), (97, 45)], ours=[(90, 70)]))
        self.assertEqual((r["loss"], r["inside_left"]), ("early_inside_not_taken", 4))
        hits = an.lever_hits([dict(r, status="no_deal", conceding_at_accept=False)])
        self.assertEqual((hits[0][1], hits[0][3]), (None, 1))
        self.assertEqual(an.candidates_from({}, hits, {}), {})      # no knob: needs code, never a params candidate

    def test_one_primas_short_of_min_surplus_is_not_inside(self):
        r = an.classify_duel(duel(rival=[(85, 50), (98, 50)], ours=[(90, 70)]))
        self.assertNotIn(r["loss"], ("inside_not_taken", "early_inside_not_taken"))
        self.assertIsNone(r["inside_left"])

    def test_buyer_side_mirrors(self):
        self.assertEqual(an.classify_duel(duel(role="buyer", rival=[(97, 48)], ours=[(90, 30)]))["loss"],
                         "inside_not_taken")

    def test_deadline(self):
        self.assertEqual(an.classify_duel(duel(rival=[(99, 45)], ours=[(90, 70)]))["loss"], "deadline")

    def test_short_of_limit(self):
        # our last offer leaves us 10; the rival came within 5 of our limit: a last chance at the limit might close
        self.assertEqual(an.classify_duel(duel(rival=[(85, 40), (90, 45)], ours=[(91, 60)]))["loss"], "short_of_limit")

    def test_no_zone(self):
        self.assertEqual(an.classify_duel(duel(rival=[(85, 20), (90, 25)], ours=[(91, 52)]))["loss"], "no_zone")

    def test_anchor_elicited(self):
        self.assertTrue(an.classify_duel(duel(rival=[(92, 30)], ours=[(90, 70)]))["anchor_elicited"])
        self.assertFalse(an.classify_duel(duel(rival=[(85, 30)], ours=[(90, 70)]))["anchor_elicited"])

    def test_deal_with_days_and_a_still_conceding_rival(self):
        r = an.classify_duel(duel(status="deal", rival=[(90, 60, 10), (95, 62, 10)], ours=[(91, 70, 10)], two=True,
                                  w=2.0, meaning="each delivery day adds this much cash to your side", price=62,
                                  days=10, result=32))
        self.assertIsNone(r["loss"])
        self.assertTrue(r["conceding_at_accept"])
        self.assertAlmostEqual(r["days_value"], 20.0)

    def test_a_rival_that_stopped_moving_long_ago_is_not_conceding(self):
        r = an.classify_duel(duel(status="deal", rival=[(85, 60), (86, 62), (90, 62), (95, 62)], ours=[(91, 70)],
                                  price=62, result=12))
        self.assertFalse(r["conceding_at_accept"])
        r = an.classify_duel(duel(status="deal", rival=[(85, 60), (93, 62), (95, 62)], ours=[(91, 70)],
                                  price=62, result=12))
        self.assertTrue(r["conceding_at_accept"])


class Levers(unittest.TestCase):
    def rows(self):
        return [{"duel": 1, "status": "no_deal", "loss": "mute", "conceding_at_accept": False},
                {"duel": 2, "status": "no_deal", "loss": "short_of_limit", "conceding_at_accept": False},
                {"duel": 3, "status": "no_deal", "loss": "deadline", "conceding_at_accept": False},
                {"duel": 4, "status": "deal", "loss": None, "conceding_at_accept": True},
                {"duel": 5, "status": "deal", "loss": None, "conceding_at_accept": False}]

    def test_hits_per_knob_most_first(self):
        hits = an.lever_hits(self.rows())
        self.assertEqual(hits[0][1], "last_chance_ticks")
        self.assertEqual(hits[0][3], 2)
        knobs = {h[1]: h[3] for h in hits}
        self.assertEqual(knobs["silent_last_margin"], 1)
        self.assertEqual(knobs["hold_while_conceding"], 1)      # 1 of 2 deals: at the 50% threshold

    def test_session_wide_reads_need_their_share(self):
        rows = self.rows()
        rows[3]["conceding_at_accept"] = False
        rows.append({"duel": 6, "status": "deal", "loss": None, "conceding_at_accept": True})
        self.assertNotIn("hold_while_conceding", {h[1] for h in an.lever_hits(rows)})   # 1 of 3 deals
        rows[0]["anchor_elicited"] = True
        self.assertNotIn("stall_ticks", {h[1] for h in an.lever_hits(rows)})           # 1 of 6 duels
        rows[1]["anchor_elicited"] = True
        self.assertIn("stall_ticks", {h[1] for h in an.lever_hits(rows)})               # 2 of 6

    def test_doc_mention_flag(self):
        hits = an.lever_hits(self.rows(), "We tune the last-chance ticks tonight.")
        self.assertTrue(dict((h[1], h[5]) for h in hits)["last_chance_ticks"])
        self.assertFalse(dict((h[1], h[5]) for h in hits)["silent_last_margin"])


class Candidates(unittest.TestCase):
    def test_one_knob_each_bounded(self):
        base = {"last_chance_ticks": 6, "accept_any_ticks": 2, "silent_last_margin": 0.12, "stall_ticks": 1}
        hits = [("l", "last_chance_ticks", 1, 3, []), ("a", "accept_any_ticks", 1, 1, []),
                ("s", "silent_last_margin", 0.05, 2, []), ("t", "stall_ticks", -1, 4, []),
                ("h", "hold_while_conceding", True, 9, [])]
        c = an.candidates_from(base, hits, {})
        self.assertNotIn("last_chance_ticks@7", c)            # 6 is the cap: no move, no candidate
        self.assertEqual(c["accept_any_ticks@3"]["accept_any_ticks"], 3)
        self.assertEqual(c["silent_last_margin@0.15"]["silent_last_margin"], 0.15)
        self.assertNotIn("stall_ticks@0", c)                  # 1 is the floor
        self.assertIs(c["hold_while_conceding@True"]["hold_while_conceding"], True)
        for p in c.values():                                  # every candidate differs from the base in one knob only
            self.assertEqual(len(an.params_delta(base, p)), 1)

    def test_zero_hits_and_the_budget(self):
        self.assertEqual(an.candidates_from({}, [("l", "last_chance_ticks", 1, 0, [])], {}), {})
        extra = {f"x{i}": {"k": i} for i in range(9)}
        self.assertEqual(len(an.candidates_from({}, [], extra)), an.MAX_CANDIDATES)


class PickWinner(unittest.TestCase):
    FOCUS = "mix: Duels III field"
    GUARDS = [FOCUS, "mix: Duels I field", "d1: Duels III field"]

    def cells(self, focus=(0.02, 0.005), conf=(0.02, 0.005), d1=(0.0, 0.005), drop=()):
        out = []
        for pol in ("base", "c"):
            for w, m, (d, se) in [(self.FOCUS, "robust", focus), (self.FOCUS, "confirmed", conf),
                                  ("d1: Duels III field", "robust", d1), ("mix: Duels I field", "robust", (0.0, 0.01)),
                                  ("mix: Duels I field", "confirmed", (0.0, 0.01))]:
                if pol == "c" and (w, m) in drop:
                    continue
                out.append({"world": w, "mode": m, "policy": pol, "delta": 0.0 if pol == "base" else d,
                            "se": 0.0 if pol == "base" else se})
        return out

    def test_more_than_two_se_in_both_modes_wins(self):
        self.assertEqual(an.pick_winner(self.cells(), "base", self.FOCUS, self.GUARDS)[0], "c")

    def test_exactly_two_se_does_not_win(self):
        self.assertIsNone(an.pick_winner(self.cells(focus=(0.01, 0.005)), "base", self.FOCUS, self.GUARDS)[0])

    def test_full_precision_decides(self):
        # 0.01006 - 2 x 0.005049 < 0: fails; rounded to 4 places (0.0101, 0.0050) it would pass
        cells = self.cells(focus=(0.01006, 0.005049), conf=(0.01006, 0.005049))
        self.assertIsNone(an.pick_winner(cells, "base", self.FOCUS, self.GUARDS)[0])
        rounded = self.cells(focus=(0.0101, 0.0050), conf=(0.0101, 0.0050))
        self.assertEqual(an.pick_winner(rounded, "base", self.FOCUS, self.GUARDS)[0], "c")

    def test_confirmed_mode_must_also_win(self):
        self.assertIsNone(an.pick_winner(self.cells(conf=(0.0, 0.005)), "base", self.FOCUS, self.GUARDS)[0])

    def test_two_se_worse_on_the_d1_stress_vetoes(self):
        win, why = an.pick_winner(self.cells(d1=(-0.02, 0.005)), "base", self.FOCUS, self.GUARDS)
        self.assertIsNone(win)
        self.assertIn("d1", " ".join(why))

    def test_a_missing_cell_means_no_winner(self):
        for cell in [("d1: Duels III field", "robust"), ("mix: Duels I field", "confirmed"), (self.FOCUS, "confirmed")]:
            win, why = an.pick_winner(self.cells(drop=[cell]), "base", self.FOCUS, self.GUARDS)
            self.assertIsNone(win, cell)
            self.assertIn("incomplete", " ".join(why))

    def test_a_non_finite_cell_means_no_winner(self):
        for bad in [(float("nan"), 0.005), (0.02, float("inf")), (0.02, None)]:
            self.assertIsNone(an.pick_winner(self.cells(d1=bad), "base", self.FOCUS, self.GUARDS)[0], bad)

    def test_matrix_json_keeps_full_precision(self):
        c = dm.json_cell("mix: x", "robust", "c", {"mean": 0.3, "deal_rate": 0.5, "rounds": 1}, 0.01006, 0.005049)
        self.assertEqual((c["delta"], c["se"]), (0.01006, 0.005049))


class Baseline(unittest.TestCase):
    def test_the_deployed_params_are_required(self):
        a = an.build_parser().parse_args(["duels"])
        with um.patch.object(an, "DEPLOYED_PARAMS", Path("/nonexistent/duel-params-duels3.json")):
            with self.assertRaises(SystemExit) as e:
                an.base_params_path(a)
        self.assertIn("missing", str(e.exception))

    def test_an_explicit_baseline_is_used(self):
        f = ROOT / "docs/duel-lab/duel-params-duels2-final.json"
        a = an.build_parser().parse_args(["duels", "--base-params", str(f)])
        with um.patch.object(an, "DEPLOYED_PARAMS", Path("/nonexistent/x.json")):
            self.assertEqual(an.base_params_path(a), f)


class Completeness(unittest.TestCase):
    def rows(self, n, live=0):
        return [{"duel": i, "status": "deal" if i % 2 else "no_deal"} for i in range(n)] + \
            [{"duel": 1000 + i, "status": "live"} for i in range(live)]

    def test_all_expected_duels_finished_and_logged(self):
        self.assertTrue(an.completeness(self.rows(68), set(range(68)), 68)[0])

    def test_too_few_finished(self):
        ok, why = an.completeness(self.rows(4, live=4), set(range(4)), 68)
        self.assertFalse(ok)
        self.assertIn("4/68", why)

    def test_log_must_cover_every_duel(self):
        ok, why = an.completeness(self.rows(68), set(range(67)), 68)
        self.assertFalse(ok)
        self.assertIn("67/68", why)

    def test_a_partial_wave_gives_no_params_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp)
            (logs / "duels").mkdir()
            wave = [f for f in sorted((ROOT / "logs" / "duels").glob("duel-*.json"))
                    if not f.stem.endswith("-first") and json.loads(f.read_text()).get("session") == 3]
            for f in wave[:4]:                                   # four finished duels of Duels II, the rest missing
                (logs / "duels" / f.name).write_text(f.read_text())
            (logs / "duel").mkdir()
            (logs / "duel" / "2026-10-03.jsonl").write_text((ROOT / "logs/duel/2026-10-03.jsonl").read_text())
            a = an.build_parser().parse_args(["duels", "--session", "2", "--date", "2026-10-03", "--matrix",
                                              "--logs", tmp, "--out", tmp + "/out"])
            a.session = 2
            with um.patch.object(an, "run_matrix", side_effect=AssertionError("matrix on a partial wave")), \
                    um.patch.object(an, "predicted_per_duel", side_effect=AssertionError("prediction on a partial")):
                verdict, lines, _t, extra = an.cmd_duels(a, [])
            self.assertIn("PARTIAL", verdict)
            self.assertIn("no params recommendation", verdict)
            self.assertFalse(extra["complete"])
            self.assertFalse((Path(tmp) / "out").exists())


class PitchNumbers(unittest.TestCase):
    ROWS = [{"tick": 227, "score": {"duel_points": 0.0}}, {"tick": 630, "score": {"duel_points": 16.24}},
            {"tick": 1428, "score": {"duel_points": 43.37}}]

    def test_realised_per_duel_from_duel_points(self):
        v, why = an.realised_per_duel(self.ROWS, 1239, 1415, 68)
        self.assertAlmostEqual(v, (43.37 - 16.24) / 68)
        self.assertIn("tick 630", why)
        self.assertAlmostEqual(an.realised_per_duel(self.ROWS, 1239, 1415, 34)[0], (43.37 - 16.24) / 34)

    def test_a_snapshot_long_after_the_wave_is_not_used(self):
        self.assertIsNone(an.realised_per_duel(self.ROWS, 459, 640, 34)[0])     # 1428 also holds Duels II
        self.assertIsNone(an.realised_per_duel(self.ROWS, 100, 1415, 0)[0])

    def test_matrix_md_value(self):
        md = "| world | mode | base | c |\n|---|---|---|---|\n| mix: Duels I field | robust | 0.348 | 0.3 |\n" \
             "| mix: likely field | robust | 0.356 | 0.305 (_-0.051_ ±0.008) |\n"
        self.assertEqual(an.matrix_md_value(md), 0.356)
        self.assertIsNone(an.matrix_md_value(md, "mix: nope"))


class FieldRefit(unittest.TestCase):
    def test_shapes_map_to_arena_kinds(self):
        rows = {1: {"rival": [], "ours": []}, 2: {"rival": [], "ours": []},
                3: {"rival": [(t, 100 - t, None, "") for t in range(1, 8)], "ours": []}}
        w = an.field_weights(rows, {1: "deal", 2: "no_deal", 3: "deal"})
        self.assertEqual(w, {"silent": 1, "absent": 1, "linear": 1})
        for k in w:
            self.assertIn(k, dm.arena.KINDS)
        for k in an.SHAPE_TO_KIND.values():
            self.assertIn(k, dm.arena.KINDS)


# ---------------------------------------------------------------- ladder, market, score

class Values(unittest.TestCase):
    V = {"bot": {"LAV-06": [("2026-10-02T20:45:54", "buy", 40.0)],
                 "MAL-06": [("2026-10-03T10:00:00", "sell", 6.0), ("2026-10-03T19:00:00", "sell", 9.0)]},
         "held": {"LAV-06": 146.0}}

    def test_a_buy_value_is_never_used_for_a_sale(self):
        self.assertEqual(an.value_at(self.V, "LAV-06", "sell", "2026-10-03T18:14:59"), (146.0, "held"))
        self.assertEqual(an.value_at(self.V, "LAV-06", "buy", "2026-10-03T18:14:59"), (40.0, "bot"))

    def test_the_value_logged_before_the_deal(self):
        self.assertEqual(an.value_at(self.V, "MAL-06", "sell", "2026-10-03T12:00:00"), (6.0, "bot"))
        self.assertEqual(an.value_at(self.V, "MAL-06", "sell", "2026-10-03T20:00:00"), (9.0, "bot"))
        self.assertEqual(an.value_at(self.V, "XX-01", "sell", ""), (None, None))

    def test_only_settlement_time_values_fill_slots(self):
        deals = [{"tick": 1, "dealer": "chato", "level": 2, "side": "sell", "ref": "MAL-06", "price": 5,
                  "ts": "2026-10-03T12:00:00"},
                 {"tick": 2, "dealer": "picaros", "level": 4, "side": "sell", "ref": "LAV-06", "price": 11,
                  "ts": "2026-10-03T18:00:00"},
                 {"tick": 3, "dealer": "picaros", "level": 4, "side": "buy", "ref": "LAV-06", "price": 1,
                  "ts": "2026-10-01T18:00:00"},
                 {"tick": 4, "dealer": "banco", "level": 5, "side": "sell", "ref": "ZZ-01", "price": 50, "ts": ""}]
        deals += [{"tick": 3 + i, "dealer": "abuela", "level": 1, "side": "buy", "ref": "LAV-06", "price": 30 + i,
                   "ts": "2026-10-03T09:00:00"} for i in range(4)]
        s = an.ladder_slots(deals, self.V)
        self.assertEqual([d["ref"] for d in s[2]["zero"]], ["MAL-06"])      # below the value the bot sold on
        self.assertEqual(s[2]["best"], [])
        # valued only by the copy we hold (sale), or before any bot value (buy): unverified, not a slot
        self.assertEqual([d["tick"] for d in s[4]["unverified"]], [2, 3])
        self.assertEqual(s[4]["best"], [])
        self.assertEqual([d["ref"] for d in s[5]["unverified"]], ["ZZ-01"])  # no value at all
        self.assertEqual(s[5]["best"], [])
        self.assertEqual([d["price"] for d in s[1]["best"]], [30, 31, 32])  # best 3 of 4 by gain

    def test_dealer_deals_only_ours_since_the_round(self):
        ev = [{"id": 1, "tick": 5, "type": "settlement", "payload": {"persona": "chato", "parties": ["chato", "t03"],
                                                                      "items": [{"ref": "A", "to": "t03"}], "price": 9}},
              {"id": 2, "tick": 50, "type": "settlement", "payload": {"persona": "chato", "parties": ["chato", "t03"],
                                                                       "items": [{"ref": "B", "to": "chato"}],
                                                                       "price": 9}},
              {"id": 3, "tick": 60, "type": "settlement", "payload": {"persona": "chato", "parties": ["chato", "t09"],
                                                                       "items": [{"ref": "C", "to": "t09"}],
                                                                       "price": 9}},
              {"id": 4, "tick": 70, "type": "settlement", "payload": {"venue": "v20", "parties": ["t01", "t03"],
                                                                       "items": [{"ref": "D", "to": "t03"}],
                                                                       "price": 9}}]
        d = an.dealer_deals(ev, 10)
        self.assertEqual([(x["ref"], x["side"], x["level"]) for x in d], [("B", "sell", 2)])


class Market(unittest.TestCase):
    def test_v20_activity_and_what_preceded_it(self):
        ev = [{"id": 1, "tick": 10, "type": "venue.announcement", "actor": "v20", "payload": {"venue": "v20"}},
              {"id": 2, "tick": 30, "type": "offer.listed", "payload": {"venue": "v20", "offer": {
                  "id": 7, "maker": "t13", "give": {"assets": [{"ref": "SAL-03"}]}, "want": {"types": ["card:X"]}}}},
              {"id": 3, "tick": 31, "type": "offer.listed", "payload": {"venue": "v03", "offer": {"maker": "t13"}}},
              {"id": 4, "tick": 90, "type": "settlement", "payload": {"venue": "v20", "parties": ["t13", "t15"],
                                                                       "items": [{"ref": "SAL-03"}], "price": 0}},
              {"id": 5, "tick": 95, "type": "settlement", "payload": {"venue": "v20", "parties": ["t13", "t03"],
                                                                       "items": [{"ref": "LAV-01"}], "price": 5}}]
        v = an.venue_activity(ev)
        self.assertEqual(len(v["listed"]), 1)
        self.assertEqual(v["listed"][0]["give"], "SAL-03")
        self.assertEqual((len(v["trades"]), len(v["others"])), (2, 1))
        self.assertEqual(an.preceded(30, v["announcements"], 40), 20)
        self.assertIsNone(an.preceded(90, v["announcements"], 40))
        self.assertIsNone(an.preceded(5, v["announcements"], 40))


class Score(unittest.TestCase):
    def test_delta_and_board(self):
        self.assertEqual(an.score_delta({"score": 31.0, "rank": 4}, {"score": 29.5, "rank": 5}),
                         {"score": 1.5, "rank": -1})
        self.assertEqual(an.score_delta({"score": 31.0}, None), {})
        body = {"teams": [{"team": "t10", "rank": 1, "score": 37}, {"team": "t03", "rank": 3, "score": 29},
                          {"team": "t12", "rank": 2, "score": 30}]}
        me, lead, above = an.board_row(body)
        self.assertEqual((me["team"], lead["team"], above["team"]), ("t03", "t10", "t12"))


class Reports(unittest.TestCase):
    def test_latest_keeps_the_newest_verdict_per_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            an.write_report(out, "bench-b53", 683, "bench b53: stall behaved", ["x"])
            an.write_report(out, "score", 700, "score: 30 rank 5", ["y"])
            f = an.write_report(out, "score", 710, "score: 31 rank 4", ["z"])
            latest = (out / "LATEST.md").read_text()
            self.assertIn("| score | score-710.md | score: 31 rank 4 |", latest)
            self.assertIn("| bench-b53 | bench-b53-683.md |", latest)
            self.assertNotIn("score-700.md", latest)
            self.assertTrue(latest.endswith(f.read_text() + "\n"))
            (out / "HANDOFF.md").write_text("TRIGGER 12:35\nVERDICT keep\n")
            (out / "notes-draft.md").write_text("**not a report**")
            with um.patch("sys.stdout"):
                an.main(["latest", "--out", tmp])
            latest = (out / "LATEST.md").read_text()
            self.assertTrue(latest.startswith("# Analyst on duty: latest\n\n```\nTRIGGER 12:35\nVERDICT keep\n```"))
            self.assertIn("| score | score-710.md |", latest)
            self.assertNotIn("notes", latest)


# ---------------------------------------------------------------- duel_matrix flags

class NoWrite(unittest.TestCase):
    def test_latest_no_write_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            an.write_report(Path(tmp), "score", 700, "score: 30", ["y"])
            (Path(tmp) / "LATEST.md").unlink()
            with um.patch("sys.stdout"):
                an.main(["latest", "--out", tmp, "--no-write"])
            self.assertFalse((Path(tmp) / "LATEST.md").exists())

    def test_matrix_no_write_keeps_artifacts_out_of_the_reports(self):
        seen = {}

        def fake_matrix(a, base_path, cands, mix_file, mix_name, out_dir):
            seen["out"] = out_dir
            return []
        with tempfile.TemporaryDirectory() as tmp:
            a = an.build_parser().parse_args(["duels", "--session", "2", "--date", "2026-10-03", "--matrix",
                                              "--no-write", "--out", tmp + "/out", "--predict-sessions", "0",
                                              "--base-params", str(ROOT / "docs/duel-lab/duel-params-duels2-final.json")])
            a.session = 2
            with um.patch.object(an, "run_matrix", fake_matrix), um.patch("sys.stdout"):
                an.cmd_duels(a, [])
            self.assertFalse((Path(tmp) / "out").exists())
            self.assertFalse(str(seen["out"]).startswith(tmp))


class MatrixFlags(unittest.TestCase):
    def test_mix_file_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            good, bad, empty = (Path(tmp) / n for n in ("g.json", "b.json", "e.json"))
            good.write_text(json.dumps({"linear": 3, "absent": 1}))
            bad.write_text(json.dumps({"linear": 3, "wizard": 1}))
            empty.write_text(json.dumps({"linear": 0}))
            w = dm.load_mix(good)
            self.assertEqual((w["linear"], w["absent"], w["steady"]), (3, 1, 0))
            for f in (bad, empty):
                with self.assertRaises(SystemExit):
                    dm.load_mix(f)

    def test_extra_mix_and_d1_rows(self):
        mix = {k: 0 for k in dm.arena.KINDS}
        mix["linear"] = 1
        jobs = dm.jobs_for({"base": {}}, [1], 4, {"Duels III field": mix}, d1=True)
        rows = {(j[0], j[1]) for j in jobs}
        self.assertIn(("mix: Duels III field", "robust"), rows)
        self.assertIn(("mix: Duels III field", "confirmed"), rows)
        self.assertIn(("d1: Duels III field", "robust"), rows)
        self.assertIn(("d1: Duels I field", "robust"), rows)
        d1 = next(j for j in jobs if j[0] == "d1: Duels III field")
        self.assertEqual(d1[6]["kw"], {"d1_settles": False})
        self.assertEqual(d1[6]["kinds"], ["linear"])
        self.assertNotIn("kw", next(j for j in jobs if j[0] == "mix: Duels III field")[6])
        self.assertFalse(any(j[0].startswith("d1:") for j in dm.jobs_for({"base": {}}, [1], 4)))

    def test_cell_passes_the_d1_switch_to_the_arena(self):
        seen = {}

        def fake(params, seeds, session, **kw):
            seen.update(kw)
            return [{"seed": 1, "score": 0.5, "deal": True, "share": 0.5, "rounds": 1, "sent": 1, "kind": "linear"}]
        # cell() sets the arena's PAIR_SEEN and ARENA_DAYS for its worker process: restore them for the other tests
        with um.patch.object(dm.arena, "evaluate", fake), um.patch.object(dm.arena, "PAIR_SEEN", dm.arena.PAIR_SEEN), \
                um.patch.object(dm.arena, "ARENA_DAYS", dm.arena.ARENA_DAYS):
            dm.cell(("d1: x", "robust", "base", {}, [1], 4, {"mods": {}, "days_mode": "", "weights": {"linear": 1},
                                                             "kinds": ["linear"], "kw": {"d1_settles": False}}))
        self.assertIs(seen.get("d1_settles"), False)


# ---------------------------------------------------------------- Saturday logs, end to end (committed data)

class SaturdayLogs(unittest.TestCase):
    def run_cmd(self, *argv):
        with tempfile.TemporaryDirectory() as tmp, um.patch("sys.stdout"):
            a = an.build_parser().parse_args(list(argv) + ["--out", tmp])
            events, _boards = an.load_feed([str(ROOT / "logs" / "feed")])
            if a.cmd == "duels":
                a.session = int(a.session)
            return {"bench": an.cmd_bench, "duels": an.cmd_duels, "ladder": an.cmd_ladder,
                    "market": an.cmd_market}[a.cmd](a, events)

    def test_bench_b36_flags_the_same_maker_drops(self):
        verdict, lines, tick, extra = self.run_cmd("bench", "--session", "b36", "--date", "2026-10-03")
        self.assertIn("something is wrong", verdict)
        self.assertIn("same_maker", verdict)
        self.assertEqual(extra["live_n"], 0)

    def test_an_active_newer_session_is_pending_not_b104(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broker").mkdir()
            log = (ROOT / "logs/broker/2026-10-03.jsonl").read_text()
            last = max(json.loads(l).get("tick") or 0 for l in log.splitlines() if l.strip())
            active = {"ts": "2026-10-03T23:00:00", "event": "book", "tick": last, "book": {   # on the book right now
                "fee_bps": 0, "fee_per_card": 0, "offers": [], "bench_offers": [
                    {"id": "b999-1", "give": {"cash": 0}, "want": {"cash": 30}},
                    {"id": "b999-2", "give": {"cash": 40}, "want": {"cash": 0}}]}}
            (Path(tmp) / "broker" / "2026-10-03.jsonl").write_text(log + json.dumps(active) + "\n")
            verdict, *_ = self.run_cmd("bench", "--session", "latest", "--date", "2026-10-03", "--logs", tmp)
        self.assertIn("pending", verdict)
        self.assertIn("b999", verdict)
        self.assertNotIn("stall behaved", verdict)

    def test_bench_b104_behaved(self):
        verdict, lines, tick, extra = self.run_cmd("bench", "--session", "b104", "--date", "2026-10-03")
        self.assertEqual(verdict, "bench b104: stall behaved")
        self.assertEqual(extra["live_n"], 4)

    def test_duels_ii_read(self):
        verdict, lines, tick, extra = self.run_cmd("duels", "--session", "2", "--date", "2026-10-03")
        s = extra["summary"]
        self.assertEqual((s["n"], s["deals"]), (68, 57))
        self.assertEqual(sum(s["losses"].values()), 11)
        self.assertEqual(sum(extra["weights"].values()), 68)

    def test_duels_i_refit_is_close_to_the_hand_read(self):
        verdict, lines, tick, extra = self.run_cmd("duels", "--session", "1", "--date", "2026-10-03")
        self.assertEqual(extra["weights"]["absent"], dm.arena.DUELS1_WEIGHTS["absent"])
        self.assertEqual(extra["weights"]["silent"], dm.arena.DUELS1_WEIGHTS["silent"])


if __name__ == "__main__":
    unittest.main()
