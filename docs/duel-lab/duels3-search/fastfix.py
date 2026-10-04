"""Which lever of a finalist costs it against the `fast` rival (jump then hold) in duel_matrix's rival row world?

Scores the finalist with each lever reverted alone, in the matrix's `rival: fast` world (default days world, fast
rivals only, paired limit hidden, robust) on SELECT seeds (500000..), never the matrix's own seeds (970000..), plus
the main-world objective on select. Usage: python3 docs/duel-lab/duels3-search/fastfix.py <id>
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lab  # noqa: E402
import search  # noqa: E402

arena = lab.arena


def fast_world(args):
    name, params, s0, n = args
    saved = arena.PAIR_SEEN, arena.ARENA_DAYS
    arena.PAIR_SEEN, arena.ARENA_DAYS = 0.0, ""
    try:
        res = arena.evaluate(params, range(s0, s0 + n), 3, kinds=["fast"], weights=None)
    finally:
        arena.PAIR_SEEN, arena.ARENA_DAYS = saved
    ps = {}
    for r in res:
        a = ps.setdefault(r["seed"], [0.0, 0])
        a[0] += r["score"]
        a[1] += 1
    return name, ps


def main():
    cid = sys.argv[1]
    rows = {r["id"]: r for r in search.board.load(search.RESULTS)}
    p = rows[cid]["params"]
    items = [("incumbent", lab.INCUMBENT), ("finalist", p)]
    for k in search.SPACE:
        if search._get(p, k) != search._get(lab.INCUMBENT, k):
            items.append((f"without {k}", search._revert(p, k)))
    with mp.get_context("fork").Pool(4) as pool:
        got = dict(pool.map(fast_world, [(n, q, 500000, 300) for n, q in items]))
    base = got["incumbent"]
    out = []
    for n, q in items:
        m, se = lab.paired(got[n], base)
        out.append((n, m, se, search.cid(q)))
        print(f"{n:32s} fast Δ {m:+.4f} ±{se:.4f}  {search.cid(q)}", flush=True)
    (HERE / f"fastfix-{cid}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
