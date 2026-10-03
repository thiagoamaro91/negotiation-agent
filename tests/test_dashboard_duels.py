"""The Duels panel's pure parts in tools/dashboard.py: agent/duel.py's log folded into a view with no private number.

The fixture rows copy the shapes agent/duel.py writes through runlog (duel_new, rival, hold, say, would_say, accept,
result, error, refused, run_start, run_end, stop). Limits, paired limits, soft pies, surpluses and planned numbers
use distinctive values so the privacy test can look for them anywhere in the payload.
"""
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import dashboard as d  # noqa: E402

# private numbers that must never reach /data (limits, paired limits, soft pies, surpluses, planned next numbers)
PRIVATE = {137, 149, 143, 119, 173, 187, 103, 167, 47, 59, 63}
BUY_L, SELL_L, LOST_L, TWO_L = 137, 173, 149, 143


def row(ts, event, **kw):
    return json.dumps({"ts": f"2026-10-03T12:{ts}", "run": "20261003-120100-ab12", "agent": "duel", "event": event,
                       **kw})


def hold(ts, duel, role, limit, tick, left, rival, why, moving=False):
    return row(ts, "hold", duel=duel, role=role, limit=limit, tick=tick, left=left, step=None, rival=rival,
               rival_surplus=47.0, pair_l=119, soft_pie=59, moving=moving, next=103, next_days=None, why=why,
               window=None)


START = row("01:00", "run_start", operator="thiago", argv=["run"], mode="run", params_file="results/duel-params.json",
            once=False, lock="results/duel.lock", accept_any_ticks=3)
LINES = [
    START,
    # 501: we buy, still live; rival came down 152 -> 129, we anchored at 97
    row("02:00", "duel_new", duel=501, role="buyer", item="Taxi Blanco", limit=BUY_L, issues=["price"],
        days_weight=None, days_meaning=None, rival="Rival Luna", deadline=220, decay=0.06, total_ticks=16,
        pair_limit=119, mirror_used=False),
    row("02:00", "rival", duel=501, offer={"id": 9001, "price": 152, "tick": 205, "days": 0}, rounds=0,
        your_offer=None, text="Opening bid <b>from</b> Luna, 152"),
    hold("02:01", 501, "buyer", BUY_L, 205, 15, [152, 0], "rival moved toward us at tick 205: listening (free)",
         moving=True),
    # 502: we sell, deal at 81
    row("02:02", "duel_new", duel=502, role="seller", item="Bocadillo", limit=SELL_L, issues=["price"],
        days_weight=None, days_meaning=None, rival="Rival Sol", deadline=216, decay=0.06, total_ticks=16,
        pair_limit=187, mirror_used=False),
    row("02:03", "say", duel=502, role="seller", limit=SELL_L, tick=206, price=212, days=None, resp={"ok": True},
        left=10, step="anchor", rival=None, rival_surplus=None, pair_l=187, soft_pie=59, moving=False,
        why="anchor (rival stalled)", window=None),
    row("03:00", "rival", duel=501, offer={"id": 9002, "price": 129, "tick": 208, "days": 0}, rounds=1,
        your_offer=None, text="ok 129"),
    row("03:01", "say", duel=501, role="buyer", limit=BUY_L, tick=208, price=97, days=None, resp={"ok": True},
        left=12, step="anchor", rival=[129, 0], rival_surplus=8.0, pair_l=119, soft_pie=59, moving=False,
        why="anchor (rival stalled)", window=None),
    hold("04:00", 502, "seller", SELL_L, 213, 3, [181, 0], "rival surplus 8 >= our anchor 103 less a round (7)"),
    row("04:01", "accept", duel=502, role="seller", limit=SELL_L, tick=213, resp={"ok": True}, left=3, step=None,
        rival=[181, 0], rival_surplus=8.0, pair_l=187, soft_pie=59, moving=False, next=None, next_days=None,
        why="endgame (3 ticks left), inside limit", window=3),
    row("04:30", "result", duel=502, role="seller", limit=SELL_L, status="deal", result=0.42, price=181, days=None,
        rounds=1, rival="Rival Sol", our_surplus=8, mirror_rival_limit=187, rival_prices=[200, 181],
        rival_crossed_mirror=[]),
    # 503: we buy, no deal
    row("05:00", "duel_new", duel=503, role="buyer", item="Gafas", limit=LOST_L, issues=["price"], days_weight=None,
        days_meaning=None, rival="Rival Oro", deadline=214, decay=0.06, total_ticks=16, pair_limit=167,
        mirror_used=False),
    row("05:30", "result", duel=503, role="buyer", limit=LOST_L, status="no_deal", result=0.0, price=None, days=None,
        rounds=0, rival="Rival Oro"),
    # 504: Duels II shape (price + days), live
    row("06:00", "duel_new", duel=504, role="buyer", item="Sofa", limit=TWO_L, issues=["price", "days"],
        days_weight=1.5, days_meaning="primas lost per day of delivery", rival="Rival Noche", deadline=224,
        decay=0.06, total_ticks=16, pair_limit=167, mirror_used=False),
    row("06:01", "rival", duel=504, offer={"id": 9003, "price": 120, "tick": 209, "days": 2}, rounds=0,
        your_offer={"price": 99, "days": 8}, text="2 days, 120"),
    row("06:02", "error", where="duels", code="http_502", msg="bad gateway"),
    row("06:03", "refused", duel=504, action="say", code="wait_for_tick", msg="price 143 refused, retry at 210",
        extra=None),
    hold("06:30", 504, "buyer", TWO_L, 214, 10, [120, 2], "early: surplus 23 >= 0.9 x soft pie 59"),
    hold("07:00", 501, "buyer", BUY_L, 214, 6, [129, 0], "rival offer inside our limit and not thin: waiting"),
]


def fold(lines=LINES):
    return d.fold_duel_log(d.new_duel_state(), lines)


def numbers(obj) -> set:
    """Every number in the payload, also inside strings."""
    return {float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", json.dumps(obj))}


def keys(obj) -> list:
    """Every key in the payload, at any depth."""
    if isinstance(obj, dict):
        return [k for k in obj] + [x for v in obj.values() for x in keys(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in keys(v)]
    return []


def at(ts: str) -> float:
    return time.mktime(time.strptime(f"2026-10-03T12:{ts}", "%Y-%m-%dT%H:%M:%S"))


class FoldTest(unittest.TestCase):
    def setUp(self):
        self.view = d.duel_view(fold(), at("07:30"), {"state": "on", "expires_in": 70})

    def test_counts_and_bot(self):
        v = self.view
        self.assertEqual(v["counts"], {"live": 2, "unknown": 0, "finished": 2, "total": 4, "deals": 1})
        self.assertEqual((v["bot"]["state"], v["bot"]["mode"], v["bot"]["age"], v["bot"]["started"]),
                         ("alive", "run", 30.0, "12:01:00"))
        self.assertEqual(v["tick"], 214)
        self.assertEqual((v["errors"], v["refused"]), (1, 1))

    def test_live_rows(self):
        live = {r["duel"]: r for r in self.view["live"]}
        self.assertEqual([r["duel"] for r in self.view["live"]], [501, 504])  # fewest ticks left first
        a = live[501]
        self.assertEqual((a["rival"], a["role"], a["round"], a["left"]), ("Rival Luna", "buyer", 1, 6))
        self.assertEqual((a["our_price"], a["rival_price"], a["our_days"], a["rival_days"]), (97, 129, None, None))
        self.assertEqual((a["our_zone"], a["rival_zone"]), ("far", "near"))   # 29 % and 5.8 % inside 137
        self.assertFalse(a["our_would"])
        self.assertEqual(a["note"], "acceptable offer, waiting for the endgame")
        b = live[504]
        self.assertTrue(b["two_issues"])
        self.assertEqual((b["our_price"], b["our_days"], b["rival_price"], b["rival_days"]), (99, 8, 120, 2))
        self.assertEqual((b["our_zone"], b["rival_zone"]), ("far", "far"))  # 31 % and 16 % inside 143
        self.assertEqual(b["note"], "early accept: rival offer is good enough")

    def test_finished_rows_and_average(self):
        f = self.view["finished"]
        self.assertEqual([r["duel"] for r in f], [503, 502])  # newest first
        self.assertEqual((f[1]["status"], f[1]["deal"], f[1]["price"], f[1]["result"], f[1]["round"]),
                         ("deal", True, 181, 0.42, 1))
        self.assertEqual((f[0]["status"], f[0]["deal"], f[0]["price"], f[0]["result"]), ("no_deal", False, None, 0.0))
        self.assertEqual((self.view["avg_result"], self.view["scored"], self.view["avg_result_deals"]),
                         (0.21, 2, 0.42))

    def test_no_private_number_anywhere(self):
        v = self.view
        leaked = numbers(v) & {float(x) for x in PRIVATE}
        self.assertFalse(leaked, f"private numbers in the payload: {leaked}")
        text = json.dumps(v)
        for key in ("limit", "pair_l", "pair_limit", "soft_pie", "surplus", "mirror", "next", "rival_prices", "resp",
                    "thin_ref", "bar\""):
            self.assertNotIn(key, text)

    def test_no_gap_number_only_coarse_zones(self):
        # a price plus an exact gap backs out our limit: only a few wide zones may leave the server
        names = d.DUEL_ZONE_NAMES
        self.assertLessEqual(len(names), 5)
        tops = [0.0] + [top for top, _ in d.DUEL_ZONES]
        self.assertTrue(all(b - a >= 0.05 for a, b in zip(tops, tops[1:])), f"zones finer than 5 %: {tops}")
        self.assertEqual(set(names), {"outside", "far"} | {name for _, name in d.DUEL_ZONES})
        self.assertFalse([k for k in keys(self.view) if "gap" in k.lower() or "pct" in k.lower()])
        numeric_ok = {"duel", "round", "left", "deadline", "our_price", "our_days", "rival_price", "rival_days"}
        seen = set()
        for r in self.view["live"]:
            for k in ("our_zone", "rival_zone"):
                self.assertIn(r[k], names + (None,))
                seen.add(r[k])
            self.assertFalse({k for k, x in r.items() if isinstance(x, (int, float)) and not isinstance(x, bool)}
                             - numeric_ok)
            self.assertNotIn("%", json.dumps(r))
        self.assertEqual(seen, {"far", "near"})

    def test_notes_carry_no_digits(self):
        for r in self.view["live"]:
            self.assertIsNone(re.search(r"\d", r["note"] or ""), r["note"])
        self.assertIsNone(re.search(r"\d", self.view["last_error"]["msg"]))
        for why in ("early: surplus 23 >= 0.9 x soft pie 59", "our number 103 stands (anchor; resending...)",
                    "rival silent: listening until mid-clock (elapsed 3/8)", "something new 137 vs 119"):
            self.assertIsNone(re.search(r"\d", d.duel_why(why)), why)

    def test_untrusted_text_is_kept_as_data(self):
        # the page escapes it; the server only trims it
        self.assertEqual(self.view["live"][0]["text"], "ok 129")
        long = fold(LINES + [row("07:01", "rival", duel=501, offer={"price": 128}, rounds=1, text="x" * 500)])
        self.assertEqual(len(d.duel_view(long, at("07:30"))["live"][0]["text"]), d.DUEL_TEXT)


class StateTest(unittest.TestCase):
    def test_empty_and_missing(self):
        v = d.duel_view(d.new_duel_state(), time.time(), exists=False)
        self.assertEqual(v["bot"]["state"], "missing")
        self.assertEqual((v["live"], v["finished"], v["avg_result"]), ([], [], None))
        self.assertEqual(v["lock"], {"state": "off"})

    def test_waiting_before_duels(self):
        v = d.duel_view(fold([START]), at("59:00"))
        self.assertEqual((v["bot"]["state"], v["counts"]["total"]), ("waiting", 0))

    def test_stale_when_live_and_quiet(self):
        v = d.duel_view(fold(), at("07:00") + d.DUEL_STALE_AFTER + 5)
        self.assertEqual(v["bot"]["state"], "stale")

    def test_stop_marks_unknown_and_restart_revives(self):
        stopped = fold(LINES + [row("08:00", "stop", why="until"), row("08:00", "run_end", duels_seen=4, finished=2)])
        v = d.duel_view(stopped, at("08:10"))
        self.assertEqual((v["bot"]["state"], v["bot"]["stop_why"]), ("stopped", "until"))
        self.assertEqual((v["counts"]["live"], v["counts"]["unknown"]), (0, 2))
        self.assertEqual({r["status"] for r in v["live"]}, {"unknown"})
        again = fold(LINES + [row("08:00", "run_end"), START,
                              hold("09:00", 501, "buyer", BUY_L, 216, 4, [128, 0], "deadline")])
        v = d.duel_view(again, at("09:10"))
        self.assertEqual((v["counts"]["live"], v["counts"]["unknown"], v["bot"]["runs"]), (1, 1, 2))
        self.assertEqual(v["live"][0]["duel"], 501)
        self.assertEqual(v["live"][0]["our_price"], 97)  # a restart keeps what we already said

    def test_watch_mode_marks_would(self):
        lines = [row("01:00", "run_start", mode="watch"), LINES[1],
                 row("02:00", "would_say", duel=501, role="buyer", limit=BUY_L, tick=206, price=95, days=None,
                     text="Hola", left=14, why="absent rival: one offer")]
        r = d.duel_view(fold(lines), at("02:10"))["live"][0]
        self.assertEqual((r["our_price"], r["our_would"], r["action"]), (95, True, "would_say"))

    def test_restart_picks_up_standing_offer(self):
        lines = [START, LINES[1], row("02:00", "rival", duel=501, offer=None, rounds=0,
                                      your_offer={"price": 96, "days": 0})]
        r = d.duel_view(fold(lines), at("02:10"))["live"][0]
        self.assertEqual((r["our_price"], r["rival_price"], r["rival_zone"]), (96, None, None))

    def test_bad_lines_are_skipped(self):
        st = fold(["", "not json", "[1,2]", json.dumps({"event": "hold", "duel": {"x": 1}}), START])
        self.assertEqual(d.duel_view(st, time.time())["counts"]["total"], 0)

    def test_zone(self):
        for role, limit, price, zone in (("seller", 80, 100, "far"), ("seller", 80, 88, "near"), ("seller", 80, 82, "at"),
                                         ("seller", 80, 80, "at"), ("seller", 80, 79, "outside"),
                                         ("buyer", 100, 96, "at"), ("buyer", 100, 95, "near"), ("buyer", 100, 90, "near"),
                                         ("buyer", 100, 85, "far"), ("buyer", 100, 110, "outside")):
            self.assertEqual(d.gap_zone(role, limit, price), zone, (role, limit, price))
        for args in (("buyer", None, 90), ("buyer", 100, None), ("buyer", 0, 5), ("judge", 100, 90)):
            self.assertIsNone(d.gap_zone(*args))


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = time.time()
        self.log = self.root / "logs" / "duel" / (time.strftime("%Y-%m-%d", time.localtime(self.now)) + ".jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_lock_states(self):
        p = self.root / "duel.lock"
        self.assertEqual(d.lock_view(p, self.now), {"state": "off"})
        p.write_text(f"{self.now + 90:.1f}\n")
        self.assertEqual(d.lock_view(p, self.now), {"state": "on", "expires_in": 90})
        p.write_text(f"{self.now - 5:.1f}\n")
        self.assertEqual(d.lock_view(p, self.now), {"state": "expired"})
        p.write_text("garbage\n")
        self.assertEqual(d.lock_view(p, self.now), {"state": "expired"})

    def test_tail_reads_whole_lines_only(self):
        self.log.parent.mkdir(parents=True)
        self.log.write_text("\n".join(LINES[:3]) + "\n" + LINES[3][:20])
        tail = d.DuelLogTail()
        self.assertTrue(tail.read(self.log))
        self.assertEqual(tail.state["duels"][501]["rival_price"], 152)
        self.assertIsNone(tail.state["duels"][501]["action"])
        self.log.write_text("\n".join(LINES) + "\n")
        tail.read(self.log)
        self.assertEqual(tail.state["duels"][502]["status"], "deal")
        self.log.write_text(START + "\n")  # shrank: start over
        tail.read(self.log)
        self.assertEqual(tail.state["duels"], {})

    def test_snapshot_reads_the_bots_root(self):
        self.log.parent.mkdir(parents=True)
        self.log.write_text("\n".join(LINES) + "\n")
        (self.root / "results").mkdir()
        (self.root / "results" / "duel.lock").write_text(f"{self.now + 60:.1f}\n")
        snap = d.Duels(self.root).snapshot(self.now)
        self.assertEqual((snap["exists"], snap["file"], snap["lock"]["state"]), (True, self.log.name, "on"))
        self.assertEqual(snap["counts"]["finished"], 2)
        self.assertFalse(numbers({k: v for k, v in snap.items() if k != "bot"}) & {float(x) for x in PRIVATE})

    def test_snapshot_empty_root(self):
        snap = d.Duels(self.root).snapshot(self.now)
        self.assertEqual((snap["exists"], snap["bot"]["state"], snap["lock"]["state"]), (False, "missing", "off"))


if __name__ == "__main__":
    unittest.main()
