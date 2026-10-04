"""docs/plans/factory-dealer-steps-sunday.json: every dealer step obeys the ladder value gate before it ever runs.

The bots refuse a run whose --cap is above floor(book x our set multiplier) or whose --floor is below
ceil(book x multiplier) of the copy sold (exit 2, before any thread): in the factory that is a step that fails at 10:41
and holds the dealer's keeper. This test finds it at commit time instead, from a frozen copy of our account at the
Saturday close (tests/fixtures/me_tick1445.json) and the public catalog (logs/public/catalog.json):

  - a buy names cards we do not hold, has a --cap, and the cap is at or under the ceiling of every card it names
  - a Picaros step buys one card (a cooloff on the second card of a two-card step would leave it marked done)
  - a sell names a card by ref (an asset id is not known before the buy lands), with --allow-single and a --floor at or
    over the card's whole value; Los Picaros never gets a sell
  - the flags are the ones the bot has (agent/chato.py parses them with its own parser; abuela.py takes five)
  - steps keep the order of their delays, the process-level gates stay, picaros is excluded from chato's match

    python3 -m unittest discover -s tests
"""
import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))

import chato  # noqa: E402

FRAGMENT = ROOT / "docs" / "plans" / "factory-dealer-steps-sunday.json"
ME = json.loads((ROOT / "tests" / "fixtures" / "me_tick1445.json").read_text())
CATALOG = json.loads((ROOT / "logs" / "public" / "catalog.json").read_text())
BOOK = {c["id"]: c["book"] for s in CATALOG["sets"] for c in s["cards"]}
HELD = {a["ref"] for a in ME["assets"] if a["kind"] == "card"}
ABUELA_FLAGS = {"--only", "--cap", "--reserve", "--max-deals", "--resume", "--max-defer-ticks"}


def ceiling(ref):
    return int(math.floor(round(BOOK[ref] * ME["affinity"][ref.split("-")[0]], 6)))


def whole_value_floor(ref):
    return int(math.ceil(round(BOOK[ref] * ME["affinity"][ref.split("-")[0]], 6)))


def flags_of(tokens):
    """{flag: value} for the `--flag value` pairs after the mode; a bare flag maps to True."""
    out, i = {}, 0
    while i < len(tokens):
        if tokens[i].startswith("--"):
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                out[tokens[i]] = tokens[i + 1]
                i += 1
            else:
                out[tokens[i]] = True
        i += 1
    return out


def step_violations(dealer, step):
    """Everything wrong with one step's command line, as strings (empty = fine)."""
    label, cmd = step["label"], step["cmd"]
    bad = []
    script = cmd[2]
    argv = cmd[3:]                        # run --only ...
    f = flags_of(argv)
    if argv[0] != "run":
        bad.append(f"{label}: not a run")
    if script == "agent/chato.py":
        import contextlib
        import io
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                chato.parse_args(argv)
        except SystemExit:
            bad.append(f"{label}: agent/chato.py does not accept these flags")
    elif script == "agent/abuela.py":
        extra = set(f) - ABUELA_FLAGS
        if extra:
            bad.append(f"{label}: abuela.py has no {sorted(extra)}")
    else:
        bad.append(f"{label}: unknown script {script}")
    only = [x for x in str(f.get("--only", "")).split(",") if x]
    if not only:
        bad.append(f"{label}: no --only")
    buys = [x for x in only if not x.startswith("sell:")]
    sells = [x.partition(":")[2] for x in only if x.startswith("sell:")]
    if buys and sells:
        bad.append(f"{label}: buys and sells in one run")
    if "--max-deals" not in f:
        bad.append(f"{label}: no --max-deals")
    if buys:
        if "--cap" not in f:
            bad.append(f"{label}: a buy without --cap")
        for ref in buys:
            if ref not in BOOK:
                bad.append(f"{label}: {ref} is not a card")
                continue
            if ref in HELD:
                bad.append(f"{label}: {ref} is already ours (the plan would skip it)")
            if "--cap" in f and float(f["--cap"]) > ceiling(ref):
                bad.append(f"{label}: --cap {f['--cap']} is above the ceiling {ceiling(ref)} of {ref}")
        if "--reserve" not in f:
            bad.append(f"{label}: no --reserve")
    for ref in sells:
        if ref.isdigit():
            bad.append(f"{label}: sell:{ref} is an asset id, not known before the buy lands: use sell:<REF>")
            continue
        if ref not in BOOK:
            bad.append(f"{label}: {ref} is not a card")
            continue
        if "--allow-single" not in f:
            bad.append(f"{label}: sell:{ref} needs --allow-single (the copy is our last)")
        if "--floor" not in f:
            bad.append(f"{label}: sell:{ref} without --floor")
        elif int(f["--floor"]) < whole_value_floor(ref):
            bad.append(f"{label}: --floor {f['--floor']} is below the value {whole_value_floor(ref)} of {ref}")
    if dealer == "picaros":
        if sells:
            bad.append(f"{label}: nothing is ever sold to Los Picaros")
        if "--dealer" not in f or f["--dealer"] != "picaros":
            bad.append(f"{label}: not --dealer picaros")
        if any(BOOK.get(r) != 70 for r in buys):
            bad.append(f"{label}: Los Picaros only sells rares here")
        if len(buys) != 1 or str(f.get("--max-deals")) != "1":
            bad.append(f"{label}: one card and --max-deals 1 per Picaros step: a cooloff on the second card would leave a "
                       f"two-card step marked done with one bought")
    if dealer == "pilar" and f.get("--dealer") != "pilar":
        bad.append(f"{label}: not --dealer pilar")
    return bad


def fragment_violations(frag):
    bad = []
    for dealer in ("abuela", "chato", "pilar", "picaros"):
        proc = frag[dealer]
        steps = proc["steps"]
        labels = [s["label"] for s in steps]
        if len(set(labels)) != len(labels):
            bad.append(f"{dealer}: duplicate step labels")
        for s in steps:
            bad += step_violations(dealer, s)
        delays = [s["after_event"].get("delay_min", 0) for s in steps if s.get("enabled", True) and "after_event" in s]
        if delays != sorted(delays):
            bad.append(f"{dealer}: delays {delays} are not in list order: a later step would wait behind an earlier one")
    if "picaros" not in frag["chato"].get("exclude", []) or "pilar" not in frag["chato"].get("exclude", []):
        bad.append("chato: exclude must hold pilar and picaros, or its keeper counts their runs as its own")
    if "picaros" not in frag["picaros"].get("match", []):
        bad.append("picaros: match must name the dealer")
    g = frag["picaros"].get("gates", {})
    if not (g.get("no_duel_lock") and g.get("duel_quiet_min")):
        bad.append("picaros: gates must keep no_duel_lock and duel_quiet_min")
    return bad


class TestSundaySteps(unittest.TestCase):
    def setUp(self):
        self.frag = json.loads(FRAGMENT.read_text())

    def test_the_fragment_obeys_the_ladder_gate(self):
        self.assertEqual(fragment_violations(self.frag), [])

    def test_it_is_the_whole_plan(self):
        labels = {d: [s["label"] for s in self.frag[d]["steps"] if s.get("enabled", True)] for d in
                  ("abuela", "chato", "pilar", "picaros")}
        self.assertEqual(labels["abuela"], ["r3-a1-ret-uncommons", "r3-a2-ret-commons"])
        self.assertEqual(labels["picaros"], ["r3-p1a-ret-09", "r3-p1b-ret-10"])
        self.assertEqual(labels["chato"], [])              # nothing a dealer sells is inside our value but SAL-10
        self.assertEqual(len(labels["pilar"]), 4)

    # ---- the check itself: each doctored copy must be caught (otherwise the green test above says nothing)
    def doctored(self, dealer, label, edit):
        frag = copy.deepcopy(self.frag)
        for s in frag[dealer]["steps"]:
            if s["label"] == label:
                edit(s["cmd"])
        return fragment_violations(frag)

    def test_a_cap_above_the_ceiling_is_found(self):
        bad = self.doctored("abuela", "r3-a1-ret-uncommons", lambda c: c.__setitem__(c.index("--cap") + 1, "23"))
        self.assertTrue(any("above the ceiling 22" in b for b in bad), bad)

    def test_the_old_chato_cap_on_a_cheap_card_is_found(self):
        bad = self.doctored("picaros", "r3-p1a-ret-09", lambda c: c.__setitem__(c.index("--cap") + 1, "88"))
        self.assertTrue(any("above the ceiling 63" in b for b in bad), bad)

    def test_a_card_we_already_hold_is_found(self):
        bad = self.doctored("abuela", "r3-a1-ret-uncommons", lambda c: c.__setitem__(c.index("--only") + 1, "RET-06,SAL-05"))
        self.assertTrue(any("SAL-05 is already ours" in b for b in bad), bad)

    def test_a_floor_below_the_value_is_found(self):
        bad = self.doctored("pilar", "r3-l1-resell-ret-rares", lambda c: c.__setitem__(c.index("--floor") + 1, "60"))
        self.assertTrue(any("below the value 63" in b for b in bad), bad)

    def test_an_asset_id_placeholder_is_found(self):
        bad = self.doctored("pilar", "r3-l1-resell-ret-rares", lambda c: c.__setitem__(c.index("--only") + 1, "sell:827"))
        self.assertTrue(any("asset id" in b for b in bad), bad)

    def test_a_missing_allow_single_is_found(self):
        bad = self.doctored("pilar", "r3-l1-resell-ret-rares", lambda c: c.remove("--allow-single"))
        self.assertTrue(any("needs --allow-single" in b for b in bad), bad)

    def test_a_two_card_picaros_step_is_found(self):
        bad = self.doctored("picaros", "r3-p1a-ret-09", lambda c: c.__setitem__(c.index("--only") + 1, "RET-09,RET-10"))
        self.assertTrue(any("one card and --max-deals 1 per Picaros step" in b for b in bad), bad)

    def test_a_sell_to_picaros_is_found(self):
        bad = self.doctored("picaros", "r3-p1a-ret-09", lambda c: c.__setitem__(c.index("--only") + 1, "sell:RET-09"))
        self.assertTrue(any("nothing is ever sold to Los Picaros" in b for b in bad), bad)

    def test_a_flag_abuela_does_not_have_is_found(self):
        bad = self.doctored("abuela", "r3-a1-ret-uncommons", lambda c: c.extend(["--anchor", "5"]))
        self.assertTrue(any("abuela.py has no" in b for b in bad), bad)

    def test_a_flag_chato_does_not_parse_is_found(self):
        bad = self.doctored("pilar", "r3-l1-resell-ret-rares", lambda c: c.extend(["--sell-step", "0"]))
        self.assertTrue(any("does not accept these flags" in b for b in bad), bad)

    def test_a_delay_out_of_order_is_found(self):
        frag = copy.deepcopy(self.frag)
        frag["pilar"]["steps"][0]["after_event"]["delay_min"] = 99
        self.assertTrue(any("not in list order" in b for b in fragment_violations(frag)))

    def test_chato_must_exclude_the_new_dealer(self):
        frag = copy.deepcopy(self.frag)
        frag["chato"]["exclude"] = ["pilar"]
        self.assertTrue(any("exclude must hold" in b for b in fragment_violations(frag)))


if __name__ == "__main__":
    unittest.main()
