"""Usage: python3 docs/duel-lab/duels3-lab/paired_v1.py   (about 40 s on 8 cores)

Provenance of the v1 row: blend vs the evals' v1 in the Duels II field, seeds 1100000..1100999, with and without
the 3 % busy accept slot that climb3.py adds (slot_busy 0.03)."""
import sys, json, math
from multiprocessing import Pool
from pathlib import Path
REPO = next(q for q in Path(__file__).resolve().parents if (q / 'tools' / 'duel_arena.py').exists())
sys.path.insert(0, str(REPO / 'tools'))
import duel_arena as A
blend = {**json.load(open(REPO / 'docs/duel-lab/duel-params-duels2-blend.json')), 'late_poll': 4, 'duel_ticks': 12}
v1 = json.load(open(REPO / 'docs/duel-lab/duels3-lab/v1-evals.json'))
duels3 = json.load(open(REPO / 'docs/duel-lab/duel-params-duels3.json'))

def run(job):
    name, p, slot, lo, hi = job
    vars(A).update(A.DUELS2_MODS); A.ARENA_DAYS = 'buyer:0,seller:10'
    res = A.evaluate(p, range(lo, hi), 3, kinds=[k for k in A.KINDS if A.DUELS2_WEIGHTS.get(k, 0) > 0],
                     weights=A.DUELS2_WEIGHTS, slot_busy=slot)
    ps = {}
    for r in res: ps.setdefault(r['seed'], []).append(r['score'])
    return {s: sum(v) / len(v) for s, v in ps.items()}

if __name__ == '__main__':
    chunks = [(1100000 + i, 1100000 + i + 125) for i in range(0, 1000, 125)]
    for slot in (0.0, 0.03):
        out = {}
        with Pool(8) as pool:
            for name, p in (('blend', blend), ('v1', v1), ('duels3', duels3)):
                parts = pool.map(run, [(name, p, slot, lo, hi) for lo, hi in chunks])
                out[name] = {k: v for d in parts for k, v in d.items()}
        for name in ('v1', 'duels3'):
            dd = [out[name][s] - out['blend'][s] for s in out['blend']]
            m = sum(dd) / len(dd); se = math.sqrt(sum((x - m) ** 2 for x in dd) / (len(dd) - 1) / len(dd))
            print(f'slot_busy {slot}: {name} - blend = {m:+.4f} +- {1.96 * se:.4f} (95 %), blend {sum(out["blend"].values()) / 1000:.4f}')
