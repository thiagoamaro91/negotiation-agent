"""Duels III overnight search driver: sweep, random search, local climbs and the TEST gate, all offline.

Phases (each appends to results.jsonl next to this file and refreshes leaderboard.md at least every 30 minutes):
    sweep    one lever at a time around the incumbent (train seeds), plus the named hypotheses
    random   random multi-lever perturbations of the incumbent and of the best candidates so far (train), the best
             promoted to the select seeds; runs until --until (HH:MM, local time)
    climb    coordinate ascent from the best select candidates, every step confirmed on the select seeds
    test     the finalists on the TEST seeds (main, drift, final, D-1 stress, per rival type); acceptance rule in
             board.py. The duel_matrix and selftest gates run separately (gate.sh).

Usage (repo root):
    nice -n 10 python3 docs/duel-lab/duels3-search/search.py sweep --workers 4
    nice -n 10 python3 docs/duel-lab/duels3-search/search.py random --until 05:30 --workers 4
    nice -n 10 python3 docs/duel-lab/duels3-search/search.py climb --until 06:45 --workers 4
    nice -n 10 python3 docs/duel-lab/duels3-search/search.py test --top 8 --workers 4
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lab  # noqa: E402
import board  # noqa: E402

RESULTS = HERE / "results.jsonl"
# The training objective: paired diffs per seed. The D-1 stress is in it because the sweep showed the biggest raw
# gains (hold for deadline-1, window_retry 0) all come from accepting at deadline-1, which never settles at 15 s ticks.
OBJ_W = {"main": 0.5, "drift": 0.15, "final": 0.15, "d1": 0.2}
D1_FLOOR = -0.03                                       # acceptance rule (3): never a parent or finalist below it
N = {"train": 200, "select": 600, "test": 2000}
CHUNK = 50
REFRESH_S = 25 * 60

INC = lab.INCUMBENT

# ---------------------------------------------------------------- the search space

def _set(p: dict, key: str, v) -> dict:
    q = copy.deepcopy(p)
    if key == "anchor":
        q["ratios"] = [round(v, 3)] + q["ratios"][1:]
    elif key == "floor":
        q["ratios"] = q["ratios"][:-1] + [round(v, 3)]
    elif key == "prem0":
        q["days_premium"] = [round(v, 3), q["days_premium"][1]]
    elif key == "prem1":
        q["days_premium"] = [q["days_premium"][0], round(v, 3)]
    else:
        q[key] = round(v, 3) if isinstance(v, float) else v
    return q


def _get(p: dict, key: str):
    return {"anchor": lambda: p["ratios"][0], "floor": lambda: p["ratios"][-1], "prem0": lambda: p["days_premium"][0],
            "prem1": lambda: p["days_premium"][1]}.get(key, lambda: p.get(key, DEFAULTS.get(key)))()


# Defaults of duel.py for keys the incumbent leaves out (flags WP1 added, default off).
DEFAULTS = {"hold_while_conceding": False, "hold_ticks": 2, "hold_counter": True, "silent_last_margin": 0.0,
            "open_rung": 0, "window_retry": 1, "min_surplus": 1, "near_ticks": -1}
# key: (kind, lo, hi) for random search; grid for the sweep
SPACE = {
    "anchor": ("f", 1.30, 2.40, [1.35, 1.45, 1.55, 1.70, 1.85, 2.0, 2.2]),
    "floor": ("f", 1.05, 1.60, [1.10, 1.18, 1.25, 1.35, 1.42, 1.50]),
    "last_r": ("f", 1.02, 1.45, [1.03, 1.06, 1.10, 1.20, 1.25, 1.30, 1.40]),
    "max_msgs": ("i", 1, 4, [1, 3, 4]),
    "last_chance_ticks": ("i", 1, 7, [1, 2, 3, 5, 6]),
    "accept_any_ticks": ("i", 1, 10, [2, 3, 4, 5, 7, 8, 9]),
    "near_ticks": ("i", -1, 3, [0, 1, 2, 3]),
    "stall_ticks": ("i", 1, 6, [1, 2, 4, 5, 6]),
    "thin_frac": ("f", 0.0, 0.8, [0.0, 0.1, 0.3, 0.4, 0.5, 0.7]),
    "absent_at": ("f", 0.0, 0.85, [0.0, 0.08, 0.25, 0.33, 0.42, 0.5, 0.6, 0.75]),
    "absent_share": ("f", 0.1, 1.0, [0.3, 0.45, 0.75, 0.9]),
    "absent_last": ("b", None, None, [False]),
    "window_wait": ("b", None, None, [False]),
    "window_retry": ("i", 0, 3, [0, 2, 3]),
    "days_cheap": ("f", 0.0, 0.6, [0.0, 0.08, 0.12, 0.25, 0.35, 0.5]),
    "prem0": ("f", 0.3, 2.6, [0.6, 0.9, 1.1, 1.6, 2.0, 2.5]),
    "prem1": ("f", 0.0, 1.2, [0.0, 0.2, 0.3, 0.6, 0.8, 1.0]),
    "late_ticks": ("i", 1, 5, [1, 2, 4, 5]),
    "slot_demand": ("c", ["open", "spoke", "acceptable"], None, ["open", "spoke"]),
    # min_surplus > 1 fails duel.py selftest ("say retreats": a last chance above our previous offer), found by the
    # 04:14 gate run; kept out of the space since then.
    "hold_while_conceding": ("b", None, None, [True]),
    "hold_ticks": ("i", 1, 4, [3, 4]),
    "hold_counter": ("b", None, None, [False]),
    "silent_last_margin": ("f", 0.0, 0.45, [0.05, 0.1, 0.15, 0.2, 0.3, 0.4]),
    # last_while_moving (F4) is out since the incumbent turned it off for Sunday (d623273, review of #72: a slow
    # message can cost another duel's late accept, which the arena does not model)
    "early_share": ("f", 0.6, 1.0, [0.7, 0.85, 0.95]),        # needs the soft pie: inert with the pair hidden
}


def valid(p: dict) -> bool:
    r = p["ratios"]
    return all(r[i] > r[i + 1] for i in range(len(r) - 1)) and r[-1] > 1.0 and p["last_r"] > 1.0 and \
        lab.check(p) is None


def hypotheses() -> list:
    """Named structured candidates: (name, params)."""
    out = []
    # (a) open ourselves against a mute rival at tick N (12-tick duels, decay 0.10): absent_at = N / 12
    for n in (0, 1, 2, 3, 4, 6, 8):
        out.append((f"H-a open to a mute rival at tick {n}", _set(INC, "absent_at", round(n / 12, 3))))
    for n, m in ((1, 0.15), (2, 0.15), (2, 0.25), (4, 0.25)):
        q = _set(_set(INC, "absent_at", round(n / 12, 3)), "silent_last_margin", m)
        out.append((f"H-a open at tick {n}, mute last chance at L x (1 +- {m})", q))
    # (d) the Final's single round: fewer concurrent duels already modelled; a wider endgame for one round
    for a, lc in ((5, 3), (7, 4), (6, 5), (8, 5)):
        q = _set(_set(INC, "accept_any_ticks", a), "last_chance_ticks", lc)
        out.append((f"H-d endgame accept {a} / last chance {lc}", q))
    # a three-rung schedule (anchor, middle, floor) and opening at the middle rung (F3)
    a, f = INC["ratios"]
    three = copy.deepcopy(INC)
    three["ratios"] = [a, round((a + f) / 2, 3), f]
    out.append(("H three-rung ratios", three))
    out.append(("H three-rung ratios, open at the middle rung", {**three, "open_rung": 1}))
    out.append(("H three-rung ratios, max_msgs 3", {**three, "max_msgs": 3}))
    # F1 hold while conceding, WP1 default-off flags
    out.append(("H F1 hold while conceding", {**INC, "hold_while_conceding": True}))
    out.append(("H F1 hold, silent wait", {**INC, "hold_while_conceding": True, "hold_counter": False}))
    out.append(("H F2 silent last margin 0.1", {**INC, "silent_last_margin": 0.1}))
    # the Duels II blend levels it came from (does the refit still help?)
    out.append(("H days_best off (auto)", {k: v for k, v in INC.items() if k != "days_best"}))
    return [(n, p) for n, p in out if valid(p)]


def sweep_cands() -> list:
    out = []
    for key, (kind, lo, hi, grid) in SPACE.items():
        for v in grid:
            if v == _get(INC, key):
                continue
            p = _set(INC, key, v)
            if key == "hold_ticks" or key == "hold_counter":
                p["hold_while_conceding"] = True
            if valid(p):
                out.append((f"S {key}={v}", p))
    return out


def mutate(p: dict, rng: random.Random, k: int) -> dict:
    q = copy.deepcopy(p)
    for key in rng.sample(list(SPACE), k):
        kind, lo, hi, grid = SPACE[key]
        cur = _get(q, key)
        if kind == "f":
            v = rng.uniform(lo, hi) if rng.random() < 0.3 else min(hi, max(lo, cur + rng.gauss(0, 0.15 * (hi - lo))))
            q = _set(q, key, float(v))
        elif kind == "i":
            v = rng.randint(lo, hi) if rng.random() < 0.3 else min(hi, max(lo, cur + rng.choice([-2, -1, 1, 2])))
            q = _set(q, key, int(v))
        elif kind == "b":
            q = _set(q, key, not cur)
        else:
            q = _set(q, key, rng.choice(lo))
    if q.get("hold_ticks", 2) != 2 or q.get("hold_counter") is False:
        q.setdefault("hold_while_conceding", True)
    return q


# ---------------------------------------------------------------- evaluation

def cid(p: dict) -> str:
    return hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:10]


class Evaluator:
    def __init__(self, workers: int):
        self.pool = mp.get_context("fork").Pool(workers)
        self.base = {}          # (world, split) -> (per_seed, per_kind)
        self.done = board.load(RESULTS)
        self.last_board = 0.0

    def _run(self, items: list, worlds: list, split: str) -> dict:
        """items: [(key, params)] -> {key: {world: (per_seed, per_kind)}}; None for params duel.py rejects."""
        s0, n = lab.SEEDS[split], N[split]
        jobs = [(key, p, w, s, min(CHUNK, s0 + n - s)) for key, p in items for w in worlds
                for s in range(s0, s0 + n, CHUNK)]
        out = {}
        for key, w, s, ps, pk in self.pool.imap_unordered(lab.job, jobs, chunksize=1):
            if ps is None:
                out[key] = None
                continue
            if key in out and out[key] is None:
                continue
            slot = out.setdefault(key, {}).setdefault(w, ({}, {}))
            slot[0].update(ps)
            for k, v in pk.items():
                slot[1].setdefault(k, {}).update(v)
        return out

    def baseline(self, worlds: list, split: str):
        need = [w for w in worlds if (w, split) not in self.base]
        if need:
            got = self._run([("__inc__", INC)], need, split)["__inc__"]
            for w in need:
                self.base[(w, split)] = got[w]

    def score(self, items: list, split: str, worlds=None, phase="", names=None) -> list:
        worlds = worlds or list(OBJ_W)
        self.baseline(worlds, split)
        got = self._run([(cid(p), p) for _, p in items], worlds, split)
        rows = []
        for (name, p) in items:
            key = cid(p)
            g = got.get(key)
            row = {"id": key, "name": name, "phase": phase, "split": split, "n": N[split], "params": p,
                   "change": lab.fmt_diff(p), "t": time.strftime("%H:%M:%S")}
            if g is None:
                row["error"] = "rejected by duel.py"
                rows.append(row)
                continue
            for w in worlds:
                m, se = lab.paired(g[w][0], self.base[(w, split)][0])
                row[w] = {"mean": round(lab.mean_of(g[w][0]), 5), "delta": round(m, 5), "se": round(se, 5)}
                if split == "test" and w == "main":
                    row["kinds"] = {k: [round(a, 5), round(b, 5)]
                                    for k, (a, b) in lab.kind_paired(g[w][1], self.base[(w, split)][1]).items()}
            if all(w in row for w in OBJ_W):
                seeds = [s for s in g["main"][0] if all(s in g[w][0] for w in OBJ_W)]
                diffs = []
                for s in seeds:
                    x = 0.0
                    for w, wt in OBJ_W.items():
                        c, b = g[w][0][s], self.base[(w, split)][0][s]
                        x += wt * (c[0] / c[1] - b[0] / b[1])
                    diffs.append(x)
                mm = sum(diffs) / len(diffs)
                sd = (sum((d - mm) ** 2 for d in diffs) / max(1, len(diffs) - 1)) ** 0.5
                row["obj"] = {"delta": round(mm, 5), "se": round(sd / len(diffs) ** 0.5, 5)}
            rows.append(row)
        with RESULTS.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        self.done.extend(rows)
        if time.time() - self.last_board > REFRESH_S:
            self.refresh()
        return rows

    def refresh(self):
        board.write(self.done)
        self.last_board = time.time()


def best(done: list, split: str, k: int, key="obj") -> list:
    rows = [r for r in done if r.get("split") == split and key in r and "error" not in r
            and r.get("d1", {"delta": 0})["delta"] >= D1_FLOOR]
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: -r[key]["delta"]):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
        if len(out) >= k:
            break
    return out


def until_ts(hhmm: str) -> float:
    hh, mm = hhmm.split(":")
    lt = time.localtime()
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(hh), int(mm), 0, 0, 0, -1))
    return t if t > time.time() - 12 * 3600 else t + 86400


def promote(ev: Evaluator, rows: list, phase: str) -> list:
    """Re-score on the select seeds (main, drift, final and the D-1 stress) the rows not already there."""
    have = {r["id"] for r in ev.done if r.get("split") == "select"}
    todo = [(r["name"], r["params"]) for r in rows if r["id"] not in have]
    if todo:
        return ev.score(todo, "select", worlds=list(OBJ_W), phase=phase)
    return []


# ---------------------------------------------------------------- phases

def phase_sweep(ev: Evaluator):
    items = [("incumbent", INC)] + hypotheses() + sweep_cands()
    print(f"sweep: {len(items)} candidates on {N['train']} train sessions x {len(OBJ_W)} worlds", flush=True)
    ev.score(items, "train", phase="sweep")
    promote(ev, best(ev.done, "train", 12), "sweep")
    ev.refresh()


def phase_random(ev: Evaluator, until: float, seed: int):
    rng = random.Random(seed)
    batch, rounds = 32, 0
    while time.time() < until:
        parents = [INC] + [r["params"] for r in best(ev.done, "select", 6)] + \
                  [r["params"] for r in best(ev.done, "train", 6)]
        items, seen = [], {r["id"] for r in ev.done if r.get("split") == "train"}
        tries = 0
        while len(items) < batch and tries < batch * 20:
            tries += 1
            par = parents[0] if rng.random() < 0.3 else rng.choice(parents)
            q = mutate(par, rng, rng.choice([1, 2, 2, 3, 3, 4]))
            if cid(q) in seen or not valid(q):
                continue
            seen.add(cid(q))
            items.append((f"R{rounds}", q))
        ev.score(items, "train", phase="random")
        rounds += 1
        if rounds % 4 == 0:
            promote(ev, best(ev.done, "train", 8), "random")
            top = best(ev.done, "select", 1)
            print(time.strftime("%H:%M"), f"random round {rounds}: {len(ev.done)} rows; best select",
                  top[0]["obj"] if top else None, top[0]["change"] if top else "", flush=True)
    promote(ev, best(ev.done, "train", 10), "random")
    ev.refresh()


def phase_climb(ev: Evaluator, until: float, starts: int, ids: list = None):
    """Coordinate ascent on the select objective: from each start, try every lever's neighbours (grid values and a
    step each way), move to the best that beats the current point by more than one SE of the difference."""
    pool = best(ev.done, "select", 10 ** 6)
    first = [r for i in (ids or []) for r in pool if r["id"] == i][:len(ids or [])]
    starts_ = first or pool[:starts]
    for i, st in enumerate(starts_):
        if time.time() >= until:
            break
        mine = time.time() + (until - time.time()) / (len(starts_) - i)     # an even share of what is left
        cur = st
        improved = True
        while improved and time.time() < mine:
            improved = False
            items = []
            for key, (kind, lo, hi, grid) in SPACE.items():
                v0 = _get(cur["params"], key)
                vals = set(grid) | ({True, False} if kind == "b" else set())
                if kind == "f":
                    vals |= {min(hi, v0 + 0.06 * (hi - lo)), max(lo, v0 - 0.06 * (hi - lo))}
                elif kind == "i":
                    vals |= {min(hi, v0 + 1), max(lo, v0 - 1)}
                for v in vals:
                    if v == v0:
                        continue
                    q = _set(cur["params"], key, v)
                    if valid(q):
                        items.append((f"C {key}={v:g}" if isinstance(v, float) else f"C {key}={v}", q))
            rows = ev.score(items, "train", phase="climb")
            rows = [r for r in rows if "obj" in r and r.get("d1", {"delta": 0})["delta"] >= D1_FLOOR]
            cand = sorted(rows, key=lambda r: -r["obj"]["delta"])[:6]
            sel = promote(ev, cand, "climb") or [r for r in ev.done if r.get("split") == "select"
                                                 and r["id"] in {c["id"] for c in cand}]
            top = sorted([r for r in sel if "obj" in r and r.get("d1", {"delta": 0})["delta"] >= D1_FLOOR],
                         key=lambda r: -r["obj"]["delta"])
            if top and top[0]["obj"]["delta"] > cur["obj"]["delta"] + top[0]["obj"]["se"] * 0.5:
                print(time.strftime("%H:%M"), "climb step:", top[0]["change"], top[0]["obj"], flush=True)
                cur = top[0]
                improved = True
    ev.refresh()


def _revert(p: dict, key: str) -> dict:
    """p with one lever back at the incumbent's value (keys the incumbent leaves out are dropped)."""
    flag = {"anchor": "ratios", "floor": "ratios", "prem0": "days_premium", "prem1": "days_premium"}.get(key, key)
    if flag not in INC:
        q = copy.deepcopy(p)
        q.pop(flag, None)
        return q
    q = _set(p, key, _get(INC, key))
    if key in ("anchor", "floor") and len(q["ratios"]) == len(INC["ratios"]) and q["ratios"] == INC["ratios"]:
        q["ratios"] = list(INC["ratios"])
    return q


def phase_prune(ev: Evaluator, top: int):
    """Drop the levers a finalist changes for nothing: revert each one alone (select seeds); revert together every
    one whose revert moves the objective by less than PRUNE_TOL, and keep the pruned file if it holds."""
    tol = 0.0002
    for r in best(ev.done, "select", top):
        if r["name"].startswith("P "):
            continue
        keys = [k for k in SPACE if _get(r["params"], k) != _get(INC, k)]
        items = [(f"P {r['id']} without {k}", _revert(r["params"], k)) for k in keys]
        items = [(n, q) for n, q in items if valid(q)]
        rows = ev.score(items, "select", phase="prune")
        inert = [k for k, row in zip(keys, rows) if "obj" in row and row["obj"]["delta"] >= r["obj"]["delta"] - tol]
        q = r["params"]
        for k in inert:
            q = _revert(q, k)
        if inert and valid(q) and cid(q) != r["id"]:
            row = ev.score([(f"P {r['id']} pruned", q)], "select", phase="prune")[0]
            print(time.strftime("%H:%M"), "prune", r["id"], "drop", inert, "->", row.get("obj"), "was", r["obj"],
                  flush=True)
    ev.refresh()


def phase_test(ev: Evaluator, top: int, extra: list):
    rows = best(ev.done, "select", top)
    ids = {r["id"] for r in rows}
    for name in extra:                                   # named rows to test too (e.g. hypotheses)
        rows += [r for r in best(ev.done, "select", 10 ** 6) if r["name"] == name and r["id"] not in ids]
    items = [(r["name"], r["params"]) for r in rows]
    print(f"test: {len(items)} finalists on {N['test']} test sessions", flush=True)
    ev.score(items, "test", worlds=list(OBJ_W), phase="test")
    ev.refresh()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("phase", choices=["sweep", "random", "climb", "prune", "test", "board"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--until", default="")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--starts", type=int, default=4)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--from-ids", default="", help="climb: comma-separated start ids (default: the best on select)")
    a = ap.parse_args()
    if a.phase == "board":
        board.write(board.load(RESULTS))
        return
    ev = Evaluator(min(4, a.workers))
    t0 = time.time()
    try:
        if a.phase == "sweep":
            phase_sweep(ev)
        elif a.phase == "random":
            phase_random(ev, until_ts(a.until), a.seed)
        elif a.phase == "climb":
            phase_climb(ev, until_ts(a.until), a.starts, [x for x in a.from_ids.split(",") if x])
        elif a.phase == "prune":
            phase_prune(ev, a.top)
        else:
            phase_test(ev, a.top, a.extra)
    finally:
        ev.refresh()
        ev.pool.close()
    print(f"{a.phase} done in {(time.time() - t0) / 60:.1f} min, {len(ev.done)} rows", flush=True)


if __name__ == "__main__":
    main()
