"""Duels III climb under the fixed referee (WP1, night of 4 Oct). Offline: drives tools/duel_arena.py. No network.

Every cell: session 3 (12 ticks, decay 0.10, 4 at once), --days-best buyer:0,seller:10, accept slot busy 3 % of
ticks (slot_busy 0.03, the tuner's assumption), rounds rule "exchange" unless the world says otherwise; the world's
module overrides (WORLDS) on top. Research script for docs/duel-lab/duels3-params.md, not a tool.

  python3 climb3.py hyp   --out OUT --workers 7 [--sessions 600]     # named hypotheses x worlds, paired vs blend
  python3 climb3.py coord --out OUT --workers 7 --start FILE         # coordinate search on tune seeds
  python3 climb3.py eval  --out OUT --cand NAME=FILE ...             # named files x worlds on test seeds
"""
import argparse, json, math, multiprocessing as mp, sys, time, random
from pathlib import Path
REPO = next(p for p in Path(__file__).resolve().parents if (p / "tools" / "duel_arena.py").exists())
sys.path.insert(0, str(REPO / "tools")); sys.path.insert(0, str(REPO / "agent")); sys.path.insert(0, str(REPO / "kit"))
import duel_arena as A  # noqa

SESSION = 3
TEST0, TUNE0 = int(__import__("os").environ.get("TEST0", 900000)), 0
DM = "buyer:0,seller:10"
D2K = [k for k in A.KINDS if A.DUELS2_WEIGHTS.get(k, 0) > 0]
WORLDS = {
    "duels2":          {"mods": dict(A.DUELS2_MODS), "w": "duels2", "kw": {}},
    "duels2 D-1 fails": {"mods": dict(A.DUELS2_MODS), "w": "duels2", "kw": {"d1_settles": False}},
    "duels2 slot 15%": {"mods": dict(A.DUELS2_MODS), "w": "duels2", "kw": {"slot_busy": 0.15}},
    "duels2 friendly": {"mods": {**A.DUELS2_MODS, "NEVER_TAKES": 0.2, "THIN_PIES": 0.06}, "w": "duels2", "kw": {}},
    "duels2 late read poor": {"mods": {**A.DUELS2_MODS, "LATE_MISS": 0.4, "LATE_FAIL": 0.15}, "w": "duels2", "kw": {}},
    "duels2 rounds=min": {"mods": dict(A.DUELS2_MODS), "w": "duels2", "kw": {"rounds_rule": "min"}},
    "Duels I mix":     {"mods": {"PAIR_SEEN": 0.0}, "w": "duels1", "kw": {}},
    "likely field":    {"mods": {"PAIR_SEEN": 0.0}, "w": "field", "kw": {}},
}
MAIN = "duels2"


def weights_of(name):
    return {"duels2": A.DUELS2_WEIGHTS, "duels1": A.DUELS1_WEIGHTS, "field": A.FIELD_WEIGHTS}[name]


def cell(job):
    cname, params, wname, seeds = job
    w = WORLDS[wname]
    g = vars(A)
    keys = set(w["mods"]) | {"ARENA_DAYS", "PAIR_SEEN"}
    saved = {k: g[k] for k in keys}
    g.update(w["mods"]); A.ARENA_DAYS = DM
    kw = {"slot_busy": 0.03, **w["kw"]}
    try:
        wt = weights_of(w["w"])
        res = A.evaluate(params, seeds, SESSION, kinds=[k for k in A.KINDS if wt.get(k, 0) > 0], weights=wt, **kw)
    finally:
        g.update(saved)
    ps = {}
    for r in res:
        ps.setdefault(r["seed"], []).append(r["score"])
    deals = [r for r in res if r["deal"]]
    extra = {"deal_rate": round(len(deals) / len(res), 4),
             "seller_day10": round(sum(1 for r in deals if r["role"] == "seller" and r["day"] == 10) / max(1, sum(1 for r in deals if r["role"] == "seller")), 3),
             "buyer_day0": round(sum(1 for r in deals if r["role"] == "buyer" and r["day"] == 0) / max(1, sum(1 for r in deals if r["role"] == "buyer")), 3),
             "rounds": round(sum(r["rounds"] for r in deals) / max(1, len(deals)), 3),
             "by_kind": {k: round(sum(r["score"] for r in res if r["kind"] == k) / max(1, sum(1 for r in res if r["kind"] == k)), 4) for k in sorted({r["kind"] for r in res})},
             "outside": sum(1 for r in deals if r["share"] < 0)}
    return cname, wname, {s: sum(v) / len(v) for s, v in ps.items()}, extra


def paired(a, b):
    d = [a[s] - b[s] for s in a]
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, n - 1))
    return m, sd / math.sqrt(n)


def mean(ps):
    return sum(ps.values()) / len(ps)


def run_grid(cands, worlds, seeds, workers):
    jobs = [(c, p, w, list(seeds)) for c, p in cands.items() for w in worlds]
    with mp.Pool(workers) as pool:
        out = pool.map(cell, jobs, chunksize=1)
    res = {}
    for c, w, ps, extra in out:
        res[(c, w)] = (ps, extra)
    return res


def table(res, cands, worlds, base):
    lines = []
    for w in worlds:
        b = res[(base, w)][0]
        lines.append(f"## {w}  (base {base} {mean(b):.4f})")
        for c in cands:
            ps, ex = res[(c, w)]
            if c == base:
                lines.append(f"  {c:38s} {mean(ps):.4f}  deals {ex['deal_rate']:.3f} s10 {ex['seller_day10']:.2f} b0 {ex['buyer_day0']:.2f} rd {ex['rounds']:.2f} out {ex['outside']}")
                continue
            m, se = paired(ps, b)
            flag = "**" if m > 2 * se else ("__" if m < -2 * se else "  ")
            lines.append(f"  {c:38s} {mean(ps):.4f}  {flag}{m:+.4f} +-{1.96 * se:.4f}{flag} deals {ex['deal_rate']:.3f} s10 {ex['seller_day10']:.2f} b0 {ex['buyer_day0']:.2f} rd {ex['rounds']:.2f} out {ex['outside']}")
    return "\n".join(lines)


def load(f):
    return json.loads(Path(f).read_text())


def hyp_cands(base, v1, final12):
    C = {"blend": base, "v1 (evals)": v1, "final12": final12, "blend lct2": {**base, "last_chance_ticks": 2}}
    for x in (0.0, 0.09, 0.3, 0.5):                       # (a) mute rival: when the one offer goes out
        C[f"a absent_at {x}"] = {**base, "absent_at": x}
    C["a absent_last off"] = {**base, "absent_last": False}
    for m in (0.05, 0.10, 0.15, 0.25):
        C[f"a silent_last_margin {m}"] = {**base, "silent_last_margin": m}
    C["a open anchor at 0 (absent_at 0, floor=anchor)"] = {**base, "absent_at": 0.0, "ratios": [1.624, 1.5]}
    for t in (1, 2, 3, 5, 6):                               # (b) last-chance timing
        C[f"b last_chance_ticks {t}"] = {**base, "last_chance_ticks": t}
    for r in (1.08, 1.12, 1.2, 1.25):
        C[f"b last_r {r}"] = {**base, "last_r": r}
    for t in (2, 3, 4, 8, 12):                              # (c) accept while conceding vs waiting
        C[f"c accept_any_ticks {t}"] = {**base, "accept_any_ticks": t}
    C["c accept now (any 12, no window wait)"] = {**base, "accept_any_ticks": 12, "window_wait": False}
    C["c window_wait off"] = {**base, "window_wait": False}
    C["c window_retry 0"] = {**base, "window_retry": 0}
    C["c hold_while_conceding"] = {**base, "hold_while_conceding": True}
    C["c hold_while_conceding no counter"] = {**base, "hold_while_conceding": True, "hold_counter": False}
    for t in (2, 4, 6):
        C[f"c stall_ticks {t}"] = {**base, "stall_ticks": t}
    for n in (0, 2):
        C[f"c near_ticks {n}"] = {**base, "near_ticks": n}
    C["c slot_demand open"] = {**base, "slot_demand": "open"}
    for x in (0.0, 0.05, 0.1, 0.25, 0.35, 0.5, 1.0):        # (d) days lever
        C[f"d days_cheap {x}"] = {**base, "days_cheap": x}
    for pr in ([0.6, 0.2], [0.3, 0.0], [2.0, 0.8], [1.0, 1.0]):
        C[f"d days_premium {pr}"] = {**base, "days_premium": pr}
    for r in ([1.45, 1.25], [1.8, 1.35], [1.624, 1.2], [2.0, 1.4]):
        C[f"x ratios {r}"] = {**base, "ratios": r}
    for m in (1, 3):
        C[f"x max_msgs {m}"] = {**base, "max_msgs": m}
    C["x thin_frac 0.5"] = {**base, "thin_frac": 0.5}
    C["x late_ticks 2"] = {**base, "late_ticks": 2}
    C["x late_poll 0 (no late read)"] = {**base, "late_poll": 0}
    return C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["hyp", "coord", "eval"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--sessions", type=int, default=600)
    ap.add_argument("--base", default=str(REPO / "docs/duel-lab/duel-params-duels2-blend.json"))
    ap.add_argument("--v1", default="")
    ap.add_argument("--cand", action="append", default=[])
    ap.add_argument("--worlds", default="")
    ap.add_argument("--minutes", type=float, default=60)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    base = {**load(a.base), "late_poll": 4, "duel_ticks": 12}
    final12 = {**load(REPO / "docs/duel-lab/duel-params-duels2-final.json"), "late_poll": 4, "duel_ticks": 12}
    v1 = load(a.v1) if a.v1 else {**final12, "last_chance_ticks": 2}
    worlds = [w for w in (a.worlds.split(",") if a.worlds else WORLDS)]
    t0 = time.time()
    if a.phase in ("hyp", "eval"):
        cands = hyp_cands(base, v1, final12) if a.phase == "hyp" else {"blend": base}
        for spec in a.cand:
            n, _, f = spec.partition("=")
            cands[n] = {**load(f), "late_poll": 4, "duel_ticks": 12}
        seeds = range(TEST0, TEST0 + a.sessions)
        res = run_grid(cands, worlds, seeds, a.workers)
        txt = table(res, list(cands), worlds, "blend")
        (out / f"{a.phase}.txt").write_text(txt + f"\n\n{time.time() - t0:.0f} s, {a.sessions} sessions per cell, seeds {TEST0}..\n")
        dump = {f"{c}|{w}": {"per_seed": ps, **ex} for (c, w), (ps, ex) in res.items()}
        (out / f"{a.phase}.json").write_text(json.dumps({"cands": cands, "cells": dump}))
        print(txt)
        return
    # coord: coordinate search on tune seeds in the main world; a step must beat the incumbent by > 2 SE there and
    # not lose more than 0.03 vs blend in the D-1 world, nor more than 2 SE vs the incumbent in the slot-15% world.
    start = {**load(a.cand[0].partition("=")[2]), "late_poll": 4, "duel_ticks": 12} if a.cand else base
    grid = {
        "absent_at": [0.0, 0.09, 0.18, 0.3], "last_chance_ticks": [1, 2, 3, 4, 5], "last_r": [1.08, 1.12, 1.155, 1.2],
        "accept_any_ticks": [2, 3, 4, 6, 8, 12], "window_wait": [True, False], "stall_ticks": [2, 3, 4, 6],
        "near_ticks": [-1, 0, 2], "days_cheap": [0.0, 0.05, 0.1, 0.174, 0.25, 0.35, 0.5],
        "days_premium": [[1.33, 0.432], [0.6, 0.2], [2.0, 0.8], [0.3, 0.0]],
        "ratios": [[1.624, 1.306], [1.45, 1.25], [1.8, 1.35], [1.624, 1.2], [2.0, 1.4]],
        "max_msgs": [1, 2, 3], "thin_frac": [0.216, 0.5], "absent_share": [0.608],
        "absent_last": [True, False], "slot_demand": ["acceptable", "open"],
    }
    tune = list(range(TUNE0, TUNE0 + a.sessions))
    inc, log = dict(start), []
    rng = random.Random(3)
    base_d1 = run_grid({"blend": base}, ["duels2 D-1 fails"], tune, a.workers)[("blend", "duels2 D-1 fails")][0]
    inc_res = run_grid({"inc": inc}, [MAIN, "duels2 slot 15%"], tune, a.workers)
    improved = True
    rounds = 0
    while improved and time.time() - t0 < a.minutes * 60 and rounds < 4:
        improved, rounds = False, rounds + 1
        keys = list(grid); rng.shuffle(keys)
        for k in keys:
            cands = {f"{k}={json.dumps(v)}": {**inc, k: v} for v in grid[k] if inc.get(k) != v}
            if not cands:
                continue
            r = run_grid(cands, [MAIN], tune, a.workers)
            best, bm = None, 0.0
            for c in cands:
                m, se = paired(r[(c, MAIN)][0], inc_res[("inc", MAIN)][0])
                if m > 2 * se and m > bm:
                    best, bm, bse = c, m, se
            if best is None:
                log.append(f"{k}: no move ({len(cands)} tried)")
                continue
            chk = run_grid({best: cands[best]}, ["duels2 D-1 fails", "duels2 slot 15%"], tune, a.workers)
            d1 = mean(chk[(best, "duels2 D-1 fails")][0]) - mean(base_d1)
            m15, se15 = paired(chk[(best, "duels2 slot 15%")][0], inc_res[("inc", "duels2 slot 15%")][0])
            if d1 < -0.03 or m15 < -2 * se15:
                log.append(f"{k}: {best} +{bm:.4f} (se {bse:.4f}) REJECTED by stress (D-1 vs blend {d1:+.4f}, slot15 {m15:+.4f} se {se15:.4f})")
                continue
            inc = cands[best]
            inc_res = {("inc", MAIN): r[(best, MAIN)], ("inc", "duels2 slot 15%"): chk[(best, "duels2 slot 15%")]}
            improved = True
            log.append(f"{k}: MOVE {best} +{bm:.4f} (se {bse:.4f}); D-1 vs blend {d1:+.4f}; slot15 {m15:+.4f}; main now {mean(r[(best, MAIN)][0]):.4f}  [{time.time() - t0:.0f} s]")
            (out / "coord.json").write_text(json.dumps(inc, indent=1))
            (out / "coord.log").write_text("\n".join(log) + "\n")
            print(log[-1], flush=True)
    (out / "coord.json").write_text(json.dumps(inc, indent=1))
    (out / "coord.log").write_text("\n".join(log) + f"\ndone in {time.time() - t0:.0f} s, {rounds} rounds\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
