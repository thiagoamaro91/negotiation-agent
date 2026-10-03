"""TRAIN-only grid on arena session 3 (Duels III), PAIR_SEEN 0, all kinds, seeds 0..N-1. Paired vs base.
usage: grid.py base.json grid.json [n_sessions] [workers]   grid.json = list of override dicts"""
import json, math, sys, multiprocessing as mp
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]  # repo root (this file lives in evals/duels-arena/climb/)
sys.path.insert(0, str(ROOT / "tools"))
import duel_arena as arena
arena.PAIR_SEEN = 0.0
KINDS = arena.FITTED + arena.CLASSIC

def run(job):
    params, seeds, kw = job
    arena.PAIR_SEEN = 0.0
    return [(r["seed"], r["duel"], r["kind"], r["score"], r["deal"]) for r in arena.evaluate(params, seeds, 3, KINDS, **kw)]

def paired(a, b):
    by = {}
    for x, y in zip(a, b):
        by[x[0]] = by.get(x[0], 0.0) + y[3] - x[3]
    t = list(by.values()); m = sum(t) / len(t)
    var = sum((v - m) ** 2 for v in t) / (len(t) - 1)
    return sum(t) / len(a), math.sqrt(len(t) * var) / len(a)

if __name__ == "__main__":
    base = json.loads(Path(sys.argv[1]).read_text())
    grid = json.loads(Path(sys.argv[2]).read_text()) if not sys.argv[2].startswith("[") else json.loads(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    d1 = len(sys.argv) > 5 and sys.argv[5] == "d1"
    import os; s0 = int(os.environ.get("SEED0", "0")); seeds = list(range(s0, s0 + n))
    kw = {"d1_settles": False} if d1 else {}
    if len(sys.argv) > 6 and sys.argv[6] == "duels1": kw["weights"] = arena.DUELS1_WEIGHTS
    chunks = [seeds[i::w] for i in range(w)]
    with mp.Pool(w) as pool:
        def ev(p):
            res = pool.map(run, [(p, c, kw) for c in chunks])
            out = sorted(x for r in res for x in r)
            return out
        a = ev(base)
        ma = sum(x[3] for x in a) / len(a)
        print(f"base mean {ma:.4f} deals {sum(x[4] for x in a)/len(a):.3f} (n={len(a)})", flush=True)
        rows = []
        for g in grid:
            b = ev({**base, **g})
            d, se = paired(a, b)
            rows.append((d, se, g))
            print(f"{d:+.4f} +- {se:.4f}  z {d/se if se else 0:+.1f}  {json.dumps(g)}", flush=True)
        print("BEST:", json.dumps(max(rows, key=lambda r: r[0])[2]))
