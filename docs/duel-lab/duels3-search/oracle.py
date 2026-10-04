"""Hypotheses (b) and (c): what a role-specific or a rival-type-specific setting would be worth, as a ceiling.

duel.py's params cannot condition on our role (only days_best is per role) or on the rival's type, so these levers
cannot ship tonight. This measures the ceiling instead: every one-lever sweep candidate is scored in the main world
with the result split by (rival type, our role); for each split the best single lever change against the
incumbent is picked (on train seeds) and re-measured on select seeds, and the ceiling is the duel-weighted sum of
those per-split gains. An oracle that knows the type is an upper bound: recognising a bot (tools/duel_book.py)
costs ticks and errs.

Usage (repo root): nice -n 10 python3 docs/duel-lab/duels3-search/oracle.py --workers 4
Writes oracle.md next to this file.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lab  # noqa: E402
import search  # noqa: E402

CHUNK = 50


def job(args):
    key, params, world, s0, n = args
    res = lab.run_world(params, world, range(s0, s0 + n))
    out = {}
    for r in res:
        for split in (("kind", r["kind"]), ("role", r["role"])):
            a = out.setdefault(split, {}).setdefault(r["seed"], [0.0, 0])
            a[0] += r["score"]
            a[1] += 1
    return key, out


def run(pool, items, s0, n, world="main"):
    jobs = [(k, p, world, s, min(CHUNK, s0 + n - s)) for k, p in items for s in range(s0, s0 + n, CHUNK)]
    got = {}
    for key, out in pool.imap_unordered(job, jobs, chunksize=1):
        g = got.setdefault(key, {})
        for split, ps in out.items():
            g.setdefault(split, {}).update(ps)
    return got


def delta(c: dict, b: dict) -> tuple:
    """Mean diff per duel of this split and its SE (per-seed sums, scaled by duels per seed)."""
    seeds = [s for s in c if s in b]
    nd = sum(c[s][1] for s in seeds)
    d = [c[s][0] - b[s][0] for s in seeds]
    m = sum(d) / len(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, len(d) - 1))
    per = len(seeds) / nd
    return m * per, sd / math.sqrt(len(d)) * per, nd / len(seeds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--train", type=int, default=300)
    ap.add_argument("--select", type=int, default=600)
    a = ap.parse_args()
    items = [("inc", lab.INCUMBENT)] + [(search.cid(p), p) for _, p in search.sweep_cands()]
    names = {search.cid(p): n[2:] for n, p in search.sweep_cands()}
    params = dict(items)
    pool = mp.get_context("fork").Pool(min(4, a.workers))
    tr = run(pool, items, lab.SEEDS["train"], a.train)
    base = tr["inc"]
    picks = {}
    for split in base:
        best = None
        for k, _ in items[1:]:
            if split not in tr[k]:
                continue
            m, se, per = delta(tr[k][split], base[split])
            if best is None or m > best[1]:
                best = (k, m, se, per)
        picks[split] = best
    keys = sorted({v[0] for v in picks.values()} | {"inc"})
    sel = run(pool, [(k, params[k]) for k in keys], lab.SEEDS["select"], a.select)
    pool.close()
    L = ["# Ceiling of role- and rival-type-specific settings (hypotheses b, c)", "",
         __doc__.split("\n\n")[1].replace("\n", " "), "",
         f"Train {a.train} sessions (pick), select {a.select} sessions (re-measure), main world.", "",
         "| split | duels per session | best single lever (train pick) | train Δ per duel | select Δ per duel |",
         "|---|---|---|---|---|"]
    ceil = {"kind": 0.0, "role": 0.0}
    ceil_se = {"kind": 0.0, "role": 0.0}
    total = {}
    for split, (k, m, se, per) in sorted(picks.items(), key=lambda x: (x[0][0], -x[1][3])):
        sm, sse, sper = delta(sel[k][split], sel["inc"][split])
        total[split[0]] = total.get(split[0], 0) + sper
        ceil[split[0]] += max(0.0, sm) * sper
        ceil_se[split[0]] += (sse * sper) ** 2
        L.append(f"| {split[0]}: {split[1]} | {sper:.1f} | {names.get(k, k)} | {m:+.4f} ±{se:.4f} | "
                 f"{sm:+.4f} ±{sse:.4f} |")
    L.append("")
    for s in ("kind", "role"):
        L.append(f"- Ceiling by {'rival type' if s == 'kind' else 'our role'}: {ceil[s] / total[s]:+.4f} per duel "
                 f"(±{math.sqrt(ceil_se[s]) / total[s]:.4f}; negative select gains counted as 0, so this is an "
                 f"optimistic bound).")
    (HERE / "oracle.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
