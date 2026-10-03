"""Duel A/B referee: one candidate --params set against the current best, on the arena's held-out sessions and its
three extra referees. No network, no key. Used for docs/duel-lab/improvements.md.

A candidate is kept only if
  - held-out (fresh seeds 500000.., all eleven rival kinds): its paired per-session mean-score difference is more than
    2 standard errors above zero, and it is not worse beyond 2 SE on the kinds no change was designed on (tft and
    deadline);
  - Friday replay (8 real rival paths), duel.py's own simulate() (Thiago's archetypes, 3000 duels) and the stress
    where an accept at deadline-1 never settles: not worse than the current best by more than TOL.

Usage (from the repo root):
    python3 tools/duel_ab.py --base docs/duel-lab/duel-params-duels1-safe.json --cand '{"late_poll": 8}'
    python3 tools/duel_ab.py --base docs/duel-lab/duel-params-duels1-safe.json --cand path.json --design
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import duel  # noqa: E402
import duel_arena as arena  # noqa: E402

HOLDOUT_SEED0 = 500000
DESIGN_KINDS = ["steady", "fast", "cycler", "oneshot", "llm", "absent", "hardliner", "linear", "silent"]
UNSEEN = ("tft", "deadline")
TOL = {"replay": 0.01, "selftest": 0.01, "d1_lost": 0.01}


def params_arg(x: str) -> dict:
    x = x.strip()
    return json.loads(x) if x.startswith("{") else arena.load_policy(x)


def paired(a: list, b: list, kinds=None) -> tuple:
    """Mean score difference per duel (b - a) and its standard error, clustered by session (same seeds = same
    scenarios, so the difference is paired)."""
    by = {}
    n = 0
    for ra, rb in zip(a, b):
        assert (ra["seed"], ra["duel"]) == (rb["seed"], rb["duel"])
        if kinds and ra["kind"] not in kinds:
            continue
        by[ra["seed"]] = by.get(ra["seed"], 0.0) + rb["score"] - ra["score"]
        n += 1
    if not n or len(by) < 2:
        return 0.0, 0.0
    tot = list(by.values())
    m = sum(tot) / len(tot)
    var = sum((t - m) ** 2 for t in tot) / (len(tot) - 1)
    return sum(tot) / n, math.sqrt(len(tot) * var) / n


def mean(rs: list, kinds=None) -> float:
    rs = [r for r in rs if not kinds or r["kind"] in kinds]
    return sum(r["score"] for r in rs) / max(1, len(rs))


def selftest_value(params: dict, n: int = 3000, seed: int = 7, **kw) -> float:
    cfg = arena.cfg_for(params, 16)
    res = duel.simulate(duel, cfg, n_duels=n, seed=seed, **kw)
    z = sum(s["zopa"] for s in res["by_kind"].values())
    assert not res["violations"], res["violations"][:3]
    return sum(s["value"] for s in res["by_kind"].values()) / max(1, z)


def replay_value(params: dict) -> float:
    rr = [r for r in arena.friday_replay(params) if r["scored"]]
    return sum(r["score"] for r in rr) / max(1, len(rr))


def compare(base: dict, cand: dict, sessions: int = 300, design: bool = False, mods: dict = None) -> dict:
    """Every number the report needs for one candidate against the base."""
    g = vars(arena)
    saved = {k: g[k] for k in (mods or {})}
    g.update(mods or {})
    try:
        if design:
            seeds, kinds = range(0, sessions), DESIGN_KINDS
        else:
            seeds, kinds = range(HOLDOUT_SEED0, HOLDOUT_SEED0 + sessions), None
        a, b = arena.evaluate(base, seeds, 1, kinds=kinds), arena.evaluate(cand, seeds, 1, kinds=kinds)
        d, se = paired(a, b)
        out = {"base": mean(a), "cand": mean(b), "diff": d, "se": se,
               "deals_base": sum(r["deal"] for r in a) / len(a), "deals_cand": sum(r["deal"] for r in b) / len(b)}
        if not design:
            du, seu = paired(a, b, UNSEEN)
            out.update(unseen_base=mean(a, UNSEEN), unseen_cand=mean(b, UNSEEN), unseen_diff=du, unseen_se=seu)
            a1 = arena.evaluate(base, seeds, 1, d1_settles=False)
            b1 = arena.evaluate(cand, seeds, 1, d1_settles=False)
            out.update(d1_base=mean(a1), d1_cand=mean(b1), d1_diff=paired(a1, b1)[0], d1_se=paired(a1, b1)[1])
            out.update(replay_base=replay_value(base), replay_cand=replay_value(cand),
                       self_base=selftest_value(base), self_cand=selftest_value(cand))
        return out
    finally:
        g.update(saved)


def verdict(r: dict) -> str:
    why = []
    if r["diff"] <= 2 * r["se"]:
        why.append("held-out gain not above 2 SE")
    if r.get("unseen_diff", 0) < -2 * r.get("unseen_se", 0):
        why.append("worse on tft/deadline")
    if r["replay_cand"] < r["replay_base"] - TOL["replay"]:
        why.append("Friday replay")
    if r["self_cand"] < r["self_base"] - TOL["selftest"]:
        why.append("duel.py selftest")
    if r["d1_cand"] < r["d1_base"] - TOL["d1_lost"]:
        why.append("deadline-1 never settles")
    return "KEEP" if not why else "REJECT (" + "; ".join(why) + ")"


def line(name: str, r: dict) -> str:
    return (f"| {name} | {r['cand']:.4f} | {r['diff']:+.4f} +- {r['se']:.4f} | {r['unseen_diff']:+.4f} +- "
            f"{r['unseen_se']:.4f} | {r['replay_cand']:.3f} ({r['replay_cand'] - r['replay_base']:+.3f}) | "
            f"{r['self_cand']:.3f} ({r['self_cand'] - r['self_base']:+.3f}) | {r['d1_cand']:.3f} "
            f"({r['d1_cand'] - r['d1_base']:+.3f}) | {verdict(r)} |")


HEADER = ("| candidate | held-out mean | paired diff vs base | diff on tft + deadline | Friday replay | "
          "duel.py selftest | D-1 never settles | verdict |\n|---|---|---|---|---|---|---|---|")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="params JSON (file or inline) of the current best")
    ap.add_argument("--cand", action="append", required=True, help="candidate params, on top of --base (repeatable)")
    ap.add_argument("--sessions", type=int, default=300)
    ap.add_argument("--design", action="store_true", help="design set (seeds 0.., no tft / deadline) only")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    base = params_arg(a.base)
    rows = {}
    for c in a.cand:
        cand = {**base, **params_arg(c)}
        rows[c] = compare(base, cand, a.sessions, a.design)
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    if a.design:
        for c, r in rows.items():
            print(f"{c}: design mean {r['cand']:.4f} vs {r['base']:.4f}, diff {r['diff']:+.4f} +- {r['se']:.4f}, "
                  f"deals {r['deals_cand']:.3f} vs {r['deals_base']:.3f}")
        return
    print(HEADER)
    for c, r in rows.items():
        print(line(c, r))


if __name__ == "__main__":
    main()
