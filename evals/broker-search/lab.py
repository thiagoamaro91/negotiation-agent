"""Overnight broker search lab (WP11): paired evaluation of a candidate bench policy against the free stall's rule.

Acceptance rule (fixed before any run, 4 Oct 02:40 Madrid; it is printed at the top of leaderboard.md):
  - "recommendable for the hard test": beats `stall` on `hard` by more than 2 SE, AND is not worse than `stall` beyond
    noise (diff + 1.96 SE < 0) on ANY other scenario, the five real-session refits included, AND drops no pair the
    stall would have crossed (dropped_vs_stall = 0: a pair the stall matched in the paired session whose two traders
    both leave unmatched under the candidate), AND bad_match = 0.
  - "recommendable everywhere": all of that, AND beats `stall` by more than 2 SE on `standard` and on each of the five
    refits.
  - anything else: "not recommended", with its numbers.

Per session (paired: the candidate and the stall meet the same traders): efficiency = true gains realised / the best
possible gains (bench_sim A8). diff = candidate - stall; SE = session SD / sqrt(n). Also counted: bad_match (matches
the live guard drops plus matches the engine refuses), dropped (eval_broker's guardrail: crossable pairs never matched;
the stall's own count is always 0) and dropped_vs_stall (above). A seed is a day of DAY sessions met by one policy
object, as the live broker meets a day's sessions; seeds are "<prefix>:<scenario>:<seed>".
"""
from __future__ import annotations

import math
import random
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for p in (ROOT / "kit", ROOT / "agent", ROOT / "tools", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import bench_sim as bs  # noqa: E402
import broker as brk  # noqa: E402
import eval_broker as eb  # noqa: E402
import policies as pol  # noqa: E402
from starter_broker import bench_plan  # noqa: E402

REQUIRED = ["hard", "standard", "firm_50", "firm_80", "all_impatient", "short_patience", "thin_overlap",
            "wide_overlap", "arrive_all0", "arrive_late"]
REFITS = ["b36", "b53", "b70", "b88", "b104"]
EXTRA = ["refit all"]  # pooled refit: reported, not part of the rule (the five single refits are)
LOG = pol.LOG

_FITTED: dict = {}


def refit_scenario(runs: str, log: Path = LOG) -> dict:
    """bench_sim's fitted scenario for one recorded run ("b36"), a "+" list, or "all"."""
    key = (runs, str(log))
    if key not in _FITTED:
        recorded = bs.read_runs(Path(log))
        pick = recorded if runs == "all" else {r: recorded[r] for r in runs.split("+")}
        _FITTED[key] = {**bs.BASE, **bs.fit(pick)[1], "name": f"refit {runs}"}
    return _FITTED[key]


def scenario(label: str) -> dict:
    if label.startswith("refit "):
        return refit_scenario(label.split(" ", 1)[1])
    return bs.scenario(label)


def battery(extra: bool = True) -> list:
    """The required scenario labels: the ten simulator mixes and the five single refits (+ the pooled refit)."""
    return REQUIRED + [f"refit {r}" for r in REFITS] + (EXTRA if extra else [])


# ---------------------------------------------------------------- one session

class Guarded:
    """What the live loop does with a plan: the guard drops what the server would refuse (counted as bad_match)."""

    def __init__(self, inner):
        self.inner = inner
        self.bad = 0

    def __call__(self, book, tick):
        ok, bad = brk.guard(self.inner.plan(book, tick), book)
        self.bad += len(bad)
        for s, b, _ in ok:
            if hasattr(self.inner, "sent"):
                self.inner.sent(s, b, tick)
        return ok


def session(traders: list, sc: dict, fn, t0: int) -> dict:
    """bench_sim.simulate plus who was matched with whom and the crossable pairs seen (for dropped)."""
    trace: list = []
    r = bs.simulate(traders, sc, fn, trace, t0)
    side = {tr["id"]: tr["side"] for tr in traders}
    pairs = [(row[1], row[2]) for row in trace if row[1] != "book"]
    matched = {x for p in pairs for x in p}
    edges = set()
    fee_book = {"fee_bps": sc["fee_bps"], "fee_per_card": sc["fee_card"]}
    for row in trace:
        if row[1] != "book":
            continue
        sells = [(i, q) for i, q in row[2] if side.get(i) == "sell"]
        buys = [(i, q) for i, q in row[2] if side.get(i) == "buy"]
        edges.update((s, b) for s, qs in sells for b, qb in buys
                     if qb >= qs and brk.price_for(fee_book, qs, qb) is not None)
    return {"gain": r["gain"], "refused": r["refused"], "pairs": pairs, "matched": matched, "edges": edges}


def dropped_count(edges: set, matched: set) -> int:
    """eval_broker.dropped_count's number (the most disjoint crossable pairs with neither offer ever matched) by
    augmenting paths (Kuhn) instead of its subset DP, which is exponential in the side size; the test checks that the
    two agree."""
    adj: dict = {}
    for s, b in edges:
        if s not in matched and b not in matched:
            adj.setdefault(s, []).append(b)
    owner: dict = {}

    def augment(s, seen) -> bool:
        for b in adj[s]:
            if b in seen:
                continue
            seen.add(b)
            if b not in owner or augment(owner[b], seen):
                owner[b] = s
                return True
        return False

    return sum(augment(s, set()) for s in sorted(adj))


def dropped_vs_stall(stall_pairs: list, matched: set) -> int:
    """Pairs the stall matched whose two traders the candidate left both unmatched."""
    return sum(s not in matched and b not in matched for s, b in stall_pairs)


# ---------------------------------------------------------------- one scenario

def evaluate(spec: dict, label: str, seeds: int, prefix: str, start: int = 0) -> dict:
    """candidate - stall over seeds [start, start + seeds) x DAY sessions of scenario `label`."""
    sc = scenario(label)
    stall_fn = lambda b, t: bench_plan(b)  # noqa: E731  the kit's own rule, as bench_sim's table uses it
    diffs, effs_s, effs_c = [], [], []
    bad = refused = dropped = dropped_sessions = dvs = 0
    t_start = time.time()
    for seed in range(start, start + seeds):
        rng = random.Random(f"{prefix}:{label}:{seed}")
        day = [bs.make_session(rng, sc, run=f"b{k + 1}") for k in range(bs.DAY)]
        g = Guarded(pol.build(spec))
        for k, traders in enumerate(day):
            best = bs.best_gain(traders)
            if hasattr(g.inner, "start_session"):
                g.inner.start_session(traders, 100 * k)
            st = session(traders, sc, stall_fn, 100 * k)
            cd = session(traders, sc, g, 100 * k)
            refused += cd["refused"]
            if best <= 1e-9:
                continue
            d = dropped_count(cd["edges"], cd["matched"])
            dropped += d
            dropped_sessions += d > 0
            dvs += dropped_vs_stall(st["pairs"], cd["matched"])
            effs_s.append(st["gain"] / best)
            effs_c.append(cd["gain"] / best)
            diffs.append((cd["gain"] - st["gain"]) / best)
        bad += g.bad
    return summarise(label, diffs, effs_s, effs_c, bad=bad + refused, dropped=dropped,
                     dropped_sessions=dropped_sessions, dropped_vs_stall=dvs, secs=time.time() - t_start)


def summarise(label: str, diffs: list, effs_s: list, effs_c: list, **counts) -> dict:
    n = len(diffs)
    m = statistics.fmean(diffs) if n else 0.0
    se = statistics.pstdev(diffs) / math.sqrt(n) if n > 1 else 0.0
    return {"scenario": label, "n": n, "stall": statistics.fmean(effs_s) if n else 0.0,
            "cand": statistics.fmean(effs_c) if n else 0.0, "diff": m, "se": se, "ci95": 1.96 * se,
            "z": m / se if se > 0 else 0.0, "win": sum(d > 1e-9 for d in diffs) / n if n else 0.0,
            "loss": sum(d < -1e-9 for d in diffs) / n if n else 0.0, "sum": sum(diffs),
            "sumsq": sum(d * d for d in diffs), **counts}


def merge(a: dict, b: dict) -> dict:
    """Two partial rows of one scenario (disjoint seed ranges) as one row (exact pooled mean and SD)."""
    n = a["n"] + b["n"]
    if not n:
        return dict(a)
    m = (a["sum"] + b["sum"]) / n
    var = max(0.0, (a["sumsq"] + b["sumsq"]) / n - m * m)
    se = math.sqrt(var / n) if n > 1 else 0.0
    out = dict(a)
    out.update({"n": n, "sum": a["sum"] + b["sum"], "sumsq": a["sumsq"] + b["sumsq"], "diff": m, "se": se,
                "ci95": 1.96 * se, "z": m / se if se > 0 else 0.0,
                "stall": (a["stall"] * a["n"] + b["stall"] * b["n"]) / n,
                "cand": (a["cand"] * a["n"] + b["cand"] * b["n"]) / n,
                "win": (a["win"] * a["n"] + b["win"] * b["n"]) / n,
                "loss": (a["loss"] * a["n"] + b["loss"] * b["n"]) / n})
    for k in ("bad", "dropped", "dropped_sessions", "dropped_vs_stall", "secs"):
        out[k] = a.get(k, 0) + b.get(k, 0)
    return out


# ---------------------------------------------------------------- the rule

def worse(r: dict) -> bool:
    return r["diff"] + r["ci95"] < 0


def beats(r: dict) -> bool:
    return r["diff"] > 2 * r["se"]


def verdict(rows: dict) -> tuple:
    """(verdict, reasons) under the acceptance rule. rows: scenario label -> row; must hold `hard`, `standard`, the
    other required mixes and the five single refits. Labels outside the battery (the pooled refit) are reported but
    do not decide."""
    required = battery(extra=False)
    missing = [k for k in required if k not in rows]
    if missing:
        return "incomplete", [f"missing {', '.join(missing)}"]
    reasons = []
    if not beats(rows["hard"]):
        reasons.append(f"hard {rows['hard']['diff']:+.4f} is not > 2 SE ({2 * rows['hard']['se']:.4f})")
    w = [k for k in required if worse(rows[k])]
    if w:
        reasons.append("worse beyond noise on " + ", ".join(w))
    dv = [k for k in required if rows[k].get("dropped_vs_stall", 0) > 0]
    if dv:
        reasons.append("drops pairs the stall crossed on " + ", ".join(dv))
    bm = [k for k in required if rows[k].get("bad", 0) > 0]
    if bm:
        reasons.append("bad_match on " + ", ".join(bm))
    if reasons:
        return "not recommended", reasons
    everywhere = [k for k in ["standard"] + [f"refit {r}" for r in REFITS] if not beats(rows[k])]
    if everywhere:
        return "recommendable for the hard test", ["not > 2 SE on " + ", ".join(everywhere)]
    return "recommendable everywhere", []


def screen_margin(rows: dict) -> float:
    """How far a candidate is from passing the hard-test rule, in SE units (> 0: it passes on these seeds): the
    smaller of (z_hard - 2) and, over every other required scenario, (z + 1.96). bad_match counts as failing; drops
    are reported beside it, not folded in, so a policy that wins on efficiency but drops pairs still shows up."""
    required = battery(extra=False)
    m = rows["hard"]["z"] - 2.0
    for k in required:
        if k != "hard":
            m = min(m, rows[k]["z"] + 1.96)
    if any(rows[k].get("bad", 0) for k in required):
        m = min(m, -99.0)
    return m
