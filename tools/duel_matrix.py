"""Duel matrix: every candidate --params file against every rival kind, rival mix and days world, on fresh seeds.

The decision table for a params change before a duel session: tools/duel_tune.py finds candidates in one world;
this checks each of them in all the others (the Duels I field, the likely field from the Saturday research, each
rival kind alone, the days worlds of duel_arena.DAYS_STRESS) plus the Duels I replay, in robust and confirmed mode.
No network, no key. Runs the cells in parallel.

Usage (from the repo root):
    python3 tools/duel_matrix.py --session 2 --sessions 60 \\
        --params deployed=docs/duel-lab/duel-params-duels2-final.json --params tuned=~/lab/tuned.json \\
        --out-md docs/duel-lab/duels2-matrix.md --out-json results/duels2-matrix.json
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import duel_arena as arena  # noqa: E402

MIXES = {"Duels II field": "duels2", "Duels I field": "duels1", "likely field": "field"}


def mix_weights(name: str):
    return {"duels1": arena.DUELS1_WEIGHTS, "field": arena.FIELD_WEIGHTS, "duels2": arena.DUELS2_WEIGHTS}[name]


def mix_mods(name: str) -> dict:
    """Module overrides a mix brings with it: the Duels II field also has its days world (arena.DUELS2_MODS)."""
    return {k: v for k, v in arena.DUELS2_MODS.items() if k != "PAIR_SEEN"} if name == "duels2" else {}


def mix_kinds(name: str) -> list:
    w = mix_weights(name)
    return [k for k in arena.KINDS if w.get(k, 0) > 0]


def cell(job: tuple) -> tuple:
    """One cell: (row, column, policy) -> per-seed mean scores and the summary."""
    row, col, pname, params, seeds, session, world = job
    g = vars(arena)
    saved = {k: g[k] for k in set(world["mods"]) | {"PAIR_SEEN", "ARENA_DAYS"}}
    g.update(world["mods"])
    arena.PAIR_SEEN = 0.0
    arena.ARENA_DAYS = world["days_mode"]
    try:
        res = arena.evaluate(params, seeds, session, kinds=world["kinds"], weights=world["weights"],
                             **world.get("kw", {}))
    finally:
        g.update(saved)
    per_seed = {}
    for r in res:
        per_seed.setdefault(r["seed"], []).append(r["score"])
    return row, col, pname, arena.summary(res)["all"], {s: sum(v) / len(v) for s, v in per_seed.items()}


def load_mix(path) -> dict:
    """A --mix file: {arena kind: weight}, every kind known to the arena, weights >= 0, at least one positive."""
    w = json.loads(Path(path).expanduser().read_text())
    bad = [k for k in w if k not in arena.KINDS]
    if bad or not w or any(not isinstance(v, (int, float)) or v < 0 for v in w.values()) or not sum(w.values()):
        raise SystemExit(f"{path}: bad mix (unknown kinds {bad} or weights not >= 0 with one positive)")
    return {k: w.get(k, 0) for k in arena.KINDS}


def jobs_for(policies: dict, seeds, session: int, mixes: dict | None = None, d1: bool = False) -> list:
    """Every cell. mixes: extra {label: weights} next to the named MIXES (a field refit from the last session; no
    module overrides); d1: one more row per mix, robust, where an accept at deadline-1 does not settle
    (arena d1_settles=False)."""
    out = []
    all_mixes = {label: (mix_weights(mix), mix_mods(mix)) for label, mix in MIXES.items()}
    all_mixes.update({label: (w, {}) for label, w in (mixes or {}).items()})
    for mode, days_mode in (("robust", ""), ("confirmed", "confirmed")):
        for label, (wts, mods) in all_mixes.items():
            w = {"mods": dict(mods), "days_mode": days_mode, "weights": wts,
                 "kinds": [k for k in arena.KINDS if wts.get(k, 0) > 0]}
            out += [(f"mix: {label}", mode, n, p, seeds, session, w) for n, p in policies.items()]
    if d1:
        for label, (wts, mods) in all_mixes.items():
            w = {"mods": dict(mods), "days_mode": "", "weights": wts,
                 "kinds": [k for k in arena.KINDS if wts.get(k, 0) > 0], "kw": {"d1_settles": False}}
            out += [(f"d1: {label}", "robust", n, p, seeds, session, w) for n, p in policies.items()]
    for kind in arena.KINDS:
        if kind == "absent":
            continue
        w = {"mods": {}, "days_mode": "", "weights": None, "kinds": [kind]}
        out += [(f"rival: {kind}", "robust", n, p, seeds, session, w) for n, p in policies.items()]
    for label, mods in arena.DAYS_STRESS:
        w = {"mods": dict(mods), "days_mode": "", "weights": arena.FIELD_WEIGHTS, "kinds": mix_kinds("field")}
        out += [(f"days: {label}", "robust", n, p, seeds, session, w) for n, p in policies.items()]
    return out


def paired(a: dict, b: dict) -> tuple:
    diffs = [a[s] - b[s] for s in a]
    n = len(diffs)
    m = sum(diffs) / n
    sd = (sum((x - m) ** 2 for x in diffs) / max(1, n - 1)) ** 0.5
    return m, sd / n ** 0.5


def json_cell(row: str, col: str, policy: str, c: dict, delta: float, se: float) -> dict:
    """One --out-json cell. delta and se stay unrounded: a reader applying the 2 SE rule must decide on full precision
    (rounding to 4 places can turn 0.01006 +- 0.005049, which fails, into 0.0101 +- 0.0050, which passes)."""
    return {"world": row, "mode": col, "policy": policy, "mean": c["mean"], "delta": float(delta), "se": float(se),
            "deal_rate": c["deal_rate"], "rounds": c["rounds"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", type=int, default=2, choices=sorted(arena.SESSIONS))
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--seed0", type=int, default=970000, help="fresh seeds (the tuner uses 0.. and 500000..)")
    ap.add_argument("--params", action="append", default=[], help="NAME=FILE (repeatable); the first is the baseline")
    ap.add_argument("--mix", action="append", default=[], help="LABEL=FILE (repeatable): an extra rival mix, "
                    "{arena kind: weight}, e.g. the field refit by tools/analyst.py duels")
    ap.add_argument("--d1-stress", action="store_true", help="add a row per mix where a deadline-1 accept does not settle")
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 1))
    ap.add_argument("--out-md", default="")
    ap.add_argument("--out-json", default="")
    a = ap.parse_args()
    policies = {}
    for spec in a.params:
        name, _, f = spec.partition("=")
        policies[name] = arena.load_policy(Path(f).expanduser())
    base = next(iter(policies))
    seeds = list(range(a.seed0, a.seed0 + a.sessions))
    t0 = time.time()
    with mp.Pool(a.workers) as pool:
        mixes = {}
        for spec in a.mix:
            label, _, f = spec.partition("=")
            mixes[label] = load_mix(f)
        results = pool.map(cell, jobs_for(policies, seeds, a.session, mixes, a.d1_stress))
    table, per_seed = {}, {}
    for row, col, pname, summ, ps in results:
        table.setdefault((row, col), {})[pname] = summ
        per_seed[(row, col, pname)] = ps
    replay = {n: arena.duels1_line(n, p) for n, p in policies.items()}
    replay2 = {n: arena.duels2_line(n, p) for n, p in policies.items()}

    names = list(policies)
    lines = [f"# Duel matrix: {arena.SESSIONS[a.session]['name']}", "",
             f"{a.sessions} fresh sessions per cell (seeds {a.seed0}..), paired limit never visible, "
             f"{(time.time() - t0) / 60:.1f} min. Cells: mean score per duel (share of the pie x decay^rounds, 0 "
             f"without a deal). Delta: each candidate minus `{base}` on the same seeds, with its standard error; "
             f"**bold** = more than 2 SE better, _italic_ = more than 2 SE worse.", "",
             "| world | mode | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    out_json = []
    for (row, col), cells in table.items():
        parts = []
        for n in names:
            c = cells[n]
            txt = f"{c['mean']:.3f}"
            if n != base:
                m, se = paired(per_seed[(row, col, n)], per_seed[(row, col, base)])
                mark = "**" if m > 2 * se else ("_" if m < -2 * se else "")
                txt += f" ({mark}{m:+.3f}{mark} ±{se:.3f})"
                out_json.append(json_cell(row, col, n, c, m, se))
            else:
                out_json.append(json_cell(row, col, n, c, 0.0, 0.0))
            parts.append(txt)
        lines.append(f"| {row} | {col} | " + " | ".join(parts) + " |")
    lines += ["", "Duels I replay (real rival price paths; rivals do not react or accept):", ""]
    lines += [f"- {replay[n]}" for n in names]
    lines += ["", "Duels II replay (real (price, day) paths, 16 ticks, decay 0.08; rivals do not react or accept):", ""]
    lines += [f"- {replay2[n]}" for n in names]
    md = "\n".join(lines) + "\n"
    print(md)
    if a.out_md:
        Path(a.out_md).expanduser().write_text(md)
    if a.out_json:
        Path(a.out_json).expanduser().write_text(json.dumps({"cells": out_json, "replay": replay, "replay2": replay2},
                                                            indent=1))


if __name__ == "__main__":
    main()
