"""Duel tuner: evolutionary search over agent/duel.py's --params values, refereed by tools/duel_arena.py. No network,
no key.

  - Starts from duel.py's own defaults (the Friday-analysis behaviour) or from --start FILE.
  - Tuning set: arena sessions on seeds 0.. against the TUNE rival kinds. Held-out set: fresh seeds (500000..)
    against every kind, including tft and deadline, which the search never sees.
  - Objective: mean score per duel, blended with the worst quartile of per-rival-kind means
    (duel_arena.objective, lambda 0.25), so a policy cannot win by giving up on one kind of rival.
  - A candidate replaces the incumbent only if it also beats it on the held-out set: higher objective AND a paired
    per-session mean-score difference at least 2 standard errors above zero (same seeds = same scenarios).
  - Duels I only: it must also keep up on Friday's real rival paths (duel_arena.friday_replay, 8 closed practice
    duels, rivals that never accept) and on duel.py's own selftest simulation (Thiago's rival archetypes, a second
    and independent rival model): on each, no more than 0.01 under duel.py's defaults.
  - Deadline-1 accepts: 11 field deals were recorded on the deadline tick, so an accept at deadline-1 probably
    settles, but it is unconfirmed. A quarter of the tuning sessions lose such accepts (expected value under that
    doubt), and a candidate must not lose more than 0.03 mean score against duel.py's defaults on a third of the
    held-out seeds where they never settle. These three guards compare with the defaults, not the incumbent, so
    small losses cannot pile up step after step.
  - Rounds rule: half the sessions use "exchange" (ceil(switches / 2)), half "min" (min of message counts): both
    fit all 18 Friday duels, so the params must hold up under either.
  - Writes the best params as a duel.py --params file (flag names, read by duel.py's make_cfg) and a markdown
    report: what moved, by how much, on which rivals, and a stress table.

Usage (from the repo root):
    python3 tools/duel_tune.py --session 1 --gens 40 --out results/duel-params.json \\
        --report docs/duel-lab/duels1-tuning.md
    python3 agent/duel.py watch --params results/duel-params.json          # what duel.py will do with them
    python3 tools/duel_tune.py --session 2 --max-minutes 420 --tune-sessions 200 --holdout-sessions 400 \\
        --out ~/lab/duel/best_params_duels2.json --report ~/lab/duel/report_duels2.md
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import duel  # noqa: E402
import duel_arena as arena  # noqa: E402

TUNE_KINDS = ["steady", "fast", "cycler", "oneshot", "llm", "absent", "hardliner", "linear", "silent"]
HOLDOUT_SEED0 = 500000

# the duel.py params the search moves (flag names, as a --params file has them)
TUNABLE = ["ratios", "last_r", "max_msgs", "last_chance_ticks", "accept_any_ticks", "near_ticks", "stall_ticks",
           "thin_frac", "early_share", "early_min_pie", "pair_sell", "pair_buy", "absent_at", "absent_share",
           "absent_last", "window_wait", "days_cheap", "days_premium"]
# search space in flat form: ratios -> anchor, floor; days_premium -> prem0, prem1
SPACE = {
    "anchor": (1.15, 2.6), "floor": (1.02, 1.9), "last_r": (1.005, 1.5),
    "max_msgs": (1, 4), "last_chance_ticks": (1, 4), "accept_any_ticks": (1, 6), "near_ticks": (-1, 4),
    "stall_ticks": (1, 8), "thin_frac": (0.0, 1.0), "early_share": (0.5, 1.3), "early_min_pie": (1.0, 25.0),
    "pair_sell": (0.8, 1.05), "pair_buy": (0.95, 1.2), "absent_at": (0.0, 0.95), "absent_share": (0.1, 0.95),
    "days_cheap": (0.02, 0.5), "prem0": (0.1, 1.5), "prem1": (0.0, 0.8),
}
INTS = {"max_msgs", "last_chance_ticks", "accept_any_ticks", "near_ticks", "stall_ticks"}
BOOLS = ["absent_last", "window_wait"]
DAYS_KEYS = {"days_cheap", "prem0", "prem1"}


def defaults() -> dict:
    """duel.py's built-in values for every tunable param (what an empty --params file gives)."""
    cfg = duel.make_cfg(["watch"])
    return {k: (list(getattr(cfg, k)) if isinstance(getattr(cfg, k), list) else getattr(cfg, k)) for k in TUNABLE}


DEFAULTS = defaults()


def flat(params: dict) -> dict:
    f = {**DEFAULTS, **{k: v for k, v in params.items() if k in TUNABLE}}
    r, prem = [float(x) for x in f.pop("ratios")], [float(x) for x in f.pop("days_premium")]
    f["anchor"], f["floor"] = r[0], r[-1]
    f["prem0"], f["prem1"] = prem[0], prem[-1]
    return f


def unflat(f: dict) -> dict:
    p = {k: v for k, v in f.items() if k not in ("anchor", "floor", "prem0", "prem1")}
    a = max(f["anchor"], f["floor"] + 0.01)
    p["ratios"] = [round(a, 3), round(f["floor"], 3)]
    p["last_r"] = round(min(f["last_r"], f["floor"] - 0.005), 3)
    p["days_premium"] = [round(f["prem0"], 3), round(f["prem1"], 3)]
    for k in SPACE:
        if k in p and k not in INTS:
            p[k] = round(p[k], 3)
    return {k: p[k] for k in TUNABLE}


def valid(p: dict) -> bool:
    return p["ratios"][0] > p["ratios"][-1] > p["last_r"] > 1.0 and p["max_msgs"] >= 1


def draw(k: str, rng: random.Random):
    lo, hi = SPACE[k]
    return rng.randint(lo, hi) if k in INTS else rng.uniform(lo, hi)


def keys_for(session: int) -> list:
    return [k for k in SPACE if session > 1 or k not in DAYS_KEYS]


def mutate(params: dict, rng: random.Random, rate: float, session: int) -> dict:
    f = flat(params)
    keys = keys_for(session) + BOOLS
    changed = False
    while not changed:
        for k in keys:
            if rng.random() > rate:
                continue
            changed = True
            if k in BOOLS:
                f[k] = not f[k]
                continue
            lo, hi = SPACE[k]
            if k in INTS:
                f[k] = max(lo, min(hi, f[k] + rng.choice([-2, -1, 1, 2])))
            else:
                f[k] = max(lo, min(hi, f[k] + rng.gauss(0, 0.12 * (hi - lo))))
    p = unflat(f)
    return p if valid(p) else mutate(params, rng, rate, session)


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    fa, fb = flat(a), flat(b)
    p = unflat({k: (fa[k] if rng.random() < 0.5 else fb[k]) for k in fa})
    return p if valid(p) else a


def random_params(rng: random.Random, session: int) -> dict:
    f = flat({})
    for k in keys_for(session):
        f[k] = draw(k, rng)
    for k in BOOLS:
        f[k] = rng.random() < 0.5
    p = unflat(f)
    return p if valid(p) else random_params(rng, session)


# ---------------------------------------------------------------- evaluation (worker processes)

def replay_score(params: dict) -> float:
    rr = [r for r in arena.friday_replay(params) if r["scored"]]
    return sum(r["score"] for r in rr) / max(1, len(rr))


def selftest_value(params: dict, ticks: int = 16) -> float:
    """Mean value per duel with a zone of agreement in duel.py's own simulate() (3000 duels, seed 7)."""
    res = duel.simulate(duel, arena.cfg_for(params, ticks), n_duels=3000, seed=7, ticks=ticks)
    return duel.sim_table(res)[-1][4]


def d1_value(params: dict, seeds, session: int, kinds, slot_busy: float, weights: dict = None) -> float:
    """Mean score per duel if an accept at deadline-1 never settles (a third of the seeds)."""
    res = arena.evaluate(params, seeds[::3], session, kinds=kinds, slot_busy=slot_busy, d1_settles=False,
                         weights=weights)
    return sum(r["score"] for r in res) / max(1, len(res))


# The world the arena plays in (--weights, --pair-seen, --days-mode) and the params held fixed (--fixed-from): set
# inside each worker by run_eval, since spawned worker processes do not inherit the parent's module globals.
WORLD = {"weights": None, "pair_seen": None, "days_mode": "", "fixed": {}}


def apply_world(world: dict) -> dict:
    """Set the arena globals for this world; returns the rival weights to pass to arena.evaluate."""
    if world.get("pair_seen") is not None:
        arena.PAIR_SEEN = world["pair_seen"]
    arena.ARENA_DAYS = world.get("days_mode") or ""
    return {"duels1": arena.DUELS1_WEIGHTS, "field": arena.FIELD_WEIGHTS,
            "blend": arena.BLEND_WEIGHTS}.get(world.get("weights"))


def run_eval(job: tuple) -> dict:
    params, seeds, session, kinds, slot_busy, held_out = job[:6]
    world = job[6] if len(job) > 6 else WORLD
    weights = apply_world(world)
    params = {**params, **world.get("fixed", {})}
    res = []
    for rule in ("exchange", "min"):
        for d1 in (True, False):
            group = [s for s in seeds if (s % 2 == 0) == (rule == "exchange")
                     and (held_out or ((s // 2) % 4 != 3)) == d1]
            res.extend(arena.evaluate(params, group, session, kinds=kinds, rounds_rule=rule, slot_busy=slot_busy,
                                      d1_settles=d1, weights=weights))
    per_seed = {}
    for r in res:
        per_seed.setdefault(r["seed"], []).append(r["score"])
    return {"params": params, "obj": arena.objective(res), "summary": arena.summary(res),
            "per_seed": {s: sum(v) / len(v) for s, v in per_seed.items()},
            "replay": replay_score(params) if session == 1 else None,
            "sim": selftest_value(params) if session == 1 and held_out else None,
            "d1": d1_value(params, seeds, session, kinds, slot_busy, weights) if held_out else None}


def paired(a: dict, b: dict) -> tuple:
    """(mean, standard error) of per-session mean score differences a - b on the same seeds."""
    diffs = [a["per_seed"][s] - b["per_seed"][s] for s in a["per_seed"]]
    n = len(diffs)
    m = sum(diffs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in diffs) / max(1, n - 1))
    return m, sd / math.sqrt(n)


def key_of(p: dict) -> str:
    return json.dumps(p, sort_keys=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", type=int, default=1, choices=sorted(arena.SESSIONS))
    ap.add_argument("--gens", type=int, default=30)
    ap.add_argument("--pop", type=int, default=12, help="parents kept per generation")
    ap.add_argument("--children", type=int, default=32, help="candidates per generation")
    ap.add_argument("--tune-sessions", type=int, default=120)
    ap.add_argument("--holdout-sessions", type=int, default=240)
    ap.add_argument("--slot-busy", type=float, default=0.03, help="chance per tick that another agent takes the accept")
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 1))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--start", default="", help="a --params file to start from (default: duel.py's defaults)")
    ap.add_argument("--out", required=True, help="where the best params go (a duel.py --params file)")
    ap.add_argument("--report", required=True, help="where the markdown report goes")
    ap.add_argument("--max-minutes", type=float, default=0, help="stop after this many minutes (0 = no limit)")
    ap.add_argument("--weights", default="friday", choices=["friday", "duels1", "field", "blend"],
                    help="rival mix: Friday-fitted WEIGHTS, the Duels I field mix (DUELS1_WEIGHTS) or the likely "
                         "field from the Saturday research (FIELD_WEIGHTS)")
    ap.add_argument("--pair-seen", type=float, default=None, help="share of duels whose paired limit is visible "
                    "(arena default 1.0, Friday; Duels I: 0 of 34)")
    ap.add_argument("--days-mode", default="", help='"" robust (duel.py run before --days-confirmed), "confirmed", '
                    'or a --days-best value')
    ap.add_argument("--fixed-from", default="", help="a --params file whose non-tunable keys (and --freeze keys) are "
                    "held fixed in every candidate and written to --out (e.g. the PR #10 flags)")
    ap.add_argument("--freeze", default="", help="comma list of tunable keys held at their --fixed-from value")
    a = ap.parse_args()
    fixed = {}
    if a.fixed_from:
        src = arena.load_policy(a.fixed_from)
        frozen = {k.strip() for k in a.freeze.split(",") if k.strip()}
        fixed = {k: v for k, v in src.items() if (k not in TUNABLE or k in frozen) and k != "duel_ticks"}
    WORLD.update({"weights": a.weights, "pair_seen": a.pair_seen, "days_mode": a.days_mode, "fixed": fixed})
    apply_world(WORLD)
    rng = random.Random(a.seed)
    sess = arena.SESSIONS[a.session]
    tune_seeds = list(range(0, a.tune_sessions))
    hold_seeds = list(range(HOLDOUT_SEED0, HOLDOUT_SEED0 + a.holdout_sessions))
    all_kinds = arena.FITTED + arena.CLASSIC
    tune_kinds = TUNE_KINDS
    if a.weights in ("duels1", "field", "blend"):   # tune and hold out on every kind the mix weighs
        mix = {"duels1": arena.DUELS1_WEIGHTS, "field": arena.FIELD_WEIGHTS, "blend": arena.BLEND_WEIGHTS}[a.weights]
        tune_kinds = [k for k in arena.KINDS if mix.get(k, 0) > 0]
        all_kinds = tune_kinds
    t0 = time.time()

    named = {"defaults": {}}
    if a.start:
        start = arena.load_policy(a.start)
        named["start"] = {k: start[k] for k in TUNABLE if k in start}

    pool = mp.Pool(a.workers)

    def tune_eval(cands):
        return pool.map(run_eval, [(c, tune_seeds, a.session, tune_kinds, a.slot_busy, False, WORLD) for c in cands])

    def hold_eval(cands):
        return pool.map(run_eval, [(c, hold_seeds, a.session, all_kinds, a.slot_busy, True, WORLD) for c in cands])

    held = dict(zip(named, hold_eval(list(named.values()))))
    ref = held["defaults"]
    ok = [n for n in held if n == "defaults" or (
        (held[n]["replay"] is None or held[n]["replay"] >= ref["replay"] - 0.01)
        and (held[n]["sim"] is None or held[n]["sim"] >= ref["sim"] - 0.01) and held[n]["d1"] >= ref["d1"] - 0.03)]
    best_named = max(ok, key=lambda n: held[n]["obj"])
    inc, inc_hold = dict(named[best_named]), held[best_named]
    inc_tune = tune_eval([inc])[0]
    history = [{"gen": 0, "from": best_named, "tune_obj": round(inc_tune["obj"], 4),
                "hold_obj": round(inc_hold["obj"], 4), "hold_mean": inc_hold["summary"]["all"]["mean"],
                "replay": inc_hold["replay"], "sim": inc_hold["sim"], "d1": inc_hold["d1"]}]
    log(f"start: {best_named} held-out obj {inc_hold['obj']:.4f} mean {inc_hold['summary']['all']['mean']:.4f} "
        f"replay {inc_hold['replay']} selftest {inc_hold['sim']}")

    seen = {key_of(inc)}
    rejected = {}                         # held-out gate failures, by reason
    pop = [inc_tune] + tune_eval([random_params(rng, a.session) for _ in range(a.children)])
    pop += tune_eval([mutate(inc, rng, 0.15, a.session) for _ in range(a.children)])
    tried = len(pop)
    write_out(a, inc, inc_hold, held, named, history, tried, t0)
    for gen in range(1, a.gens + 1):
        if a.max_minutes and time.time() - t0 > a.max_minutes * 60:
            log(f"time limit after {gen - 1} generations")
            break
        pop.sort(key=lambda r: -r["obj"])
        parents = pop[:a.pop]
        kids = []
        while len(kids) < a.children:
            r = rng.random()
            if r < 0.1:
                c = random_params(rng, a.session)
            elif r < 0.3:
                c = crossover(rng.choice(parents)["params"], rng.choice(parents)["params"], rng)
                c = mutate(c, rng, 0.1, a.session)
            elif r < 0.45:
                c = mutate(inc, rng, rng.choice([0.08, 0.15]), a.session)
            else:
                c = mutate(rng.choice(parents[:max(2, a.pop // 2)])["params"], rng, rng.choice([0.1, 0.2, 0.35]),
                           a.session)
            if key_of(c) not in seen:
                seen.add(key_of(c))
                kids.append(c)
        pop = parents + tune_eval(kids)
        tried += len(kids)
        pop.sort(key=lambda r: -r["obj"])
        # held-out gate: the top few by tuning objective that beat the incumbent on the tuning set
        cands = [r for r in pop[:6] if r["obj"] > inc_tune["obj"] and key_of(r["params"]) != key_of(inc)]
        if cands:
            for r, h in zip(cands, hold_eval([r["params"] for r in cands])):
                m, se = paired(h, inc_hold)
                ref = held["defaults"]
                replay_ok = h["replay"] is None or h["replay"] >= ref["replay"] - 0.01
                sim_ok = h["sim"] is None or h["sim"] >= ref["sim"] - 0.01
                d1_ok = h["d1"] >= ref["d1"] - 0.03
                if h["obj"] > inc_hold["obj"] and m > 2 * se and replay_ok and sim_ok and d1_ok:
                    log(f"gen {gen}: NEW incumbent: held-out obj {inc_hold['obj']:.4f} -> {h['obj']:.4f} "
                        f"(paired diff {m:+.4f} +- {se:.4f}), tune obj {r['obj']:.4f}, replay {h['replay']}, "
                        f"selftest {h['sim']}, d1-unsettled {h['d1']:.4f}")
                    inc, inc_hold, inc_tune = dict(r["params"]), h, r
                    history.append({"gen": gen, "tune_obj": round(r["obj"], 4), "hold_obj": round(h["obj"], 4),
                                    "hold_mean": h["summary"]["all"]["mean"], "paired": [round(m, 4), round(se, 4)],
                                    "replay": h["replay"], "sim": h["sim"], "d1": h["d1"]})
                    write_out(a, inc, inc_hold, held, named, history, tried, t0)
                    break
                why = [w for w, bad in (("held-out objective", h["obj"] <= inc_hold["obj"]),
                                        ("paired diff under 2 SE", m <= 2 * se), ("Friday replay", not replay_ok),
                                        ("selftest", not sim_ok), ("deadline-1", not d1_ok)) if bad]
                rejected[", ".join(why)] = rejected.get(", ".join(why), 0) + 1
        if gen % 5 == 0:
            log(f"gen {gen}: tried {tried}, best tune obj {pop[0]['obj']:.4f}, incumbent tune {inc_tune['obj']:.4f} "
                f"held-out {inc_hold['obj']:.4f}; rejected at the held-out gate: {rejected}")
    write_out(a, inc, inc_hold, held, named, history, tried, t0, final=True)
    pool.close()
    log(f"done: {tried} candidates in {(time.time() - t0) / 60:.1f} min; best held-out obj {inc_hold['obj']:.4f}")


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def write_out(a, inc: dict, inc_hold: dict, held: dict, named: dict, history: list, tried: int, t0: float,
              final: bool = False) -> None:
    sess = arena.SESSIONS[a.session]
    out = {k: v for k, v in flat_to_file(inc).items()}
    out.update(WORLD.get("fixed", {}))
    out["duel_ticks"] = sess["ticks"]
    Path(a.out).expanduser().parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).expanduser().write_text(json.dumps(out, indent=2) + "\n")
    rows = {n: held[n]["summary"] for n in named}
    rows["tuned"] = inc_hold["summary"]
    base, tf = flat({}), flat(inc)
    objs = ", ".join(f"{n} {held[n]['obj']:.4f}" for n in named)
    lines = [f"# Duel tuning report: {sess['name']}", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `tools/duel_tune.py` in "
             f"{(time.time() - t0) / 60:.1f} min, {tried} candidates{'' if final else ' (run still going)'}. "
             f"Tuned params: `{a.out}` (a `duel.py --params` file). The arena drives agent/duel.py's own decide / "
             f"set_windows / allocate with the cfg duel.py's make_cfg builds from that file.", "",
             f"Tuning set: {a.tune_sessions} simulated sessions (seeds 0..) against {', '.join(TUNE_KINDS)}. "
             f"Held-out: {a.holdout_sessions} fresh sessions (seeds {HOLDOUT_SEED0}..) against every kind, "
             f"including tft and deadline, never seen while tuning. Each session: {sess['duels']} duels, "
             f"{sess['ticks']} ticks, decay {sess['decay']}, {sess['concurrent']} at once, one accept per tick, "
             f"slot taken by another agent {a.slot_busy:.0%} of ticks; half the sessions count rounds as "
             f"ceil(switches / 2), half as min(our messages, theirs).", "",
             "## Held-out results", "",
             "Cells: mean score per duel (share of the pie x decay^rounds; 0 without a deal), deal rate, "
             "rounds per deal. `defaults` = agent/duel.py as it is on main (the Friday-analysis behaviour).",
             "", arena.table(rows), "",
             f"Objective (0.75 x mean + 0.25 x worst quartile of per-kind means, absent excluded): {objs}, "
             f"tuned {inc_hold['obj']:.4f}.", "",
             "## What moved", "", "| param | duel.py default | tuned |", "|---|---|---|"]
    for k in tf:
        if a.session == 1 and k in DAYS_KEYS:
            continue
        moved = " (moved)" if tf[k] != base[k] else ""
        lines.append(f"| {k} | {base[k]} | {tf[k]}{moved} |")
    if a.session == 1:
        lines += ["", "## Two more referees", "",
                  "Friday replay: our policy against the price paths Friday's rival bots really posted (8 closed "
                  "practice duels; the rivals do not react to us and never accept; the pie is the soft pie from the "
                  "paired duel). duel.py selftest: `duel.simulate` (Thiago's own rival archetypes, 3000 duels, seed "
                  "7), mean value per duel with a zone of agreement.", "",
                  "| policy | Friday replay | duel.py selftest |", "|---|---|---|"]
        for n in named:
            lines.append(f"| {n} | {held[n]['replay']:.3f} | {held[n]['sim']:.3f} |")
        lines.append(f"| tuned | {inc_hold['replay']:.3f} | {inc_hold['sim']:.3f} |")
    if final:
        stress_seeds = list(range(800000, 800000 + max(40, a.holdout_sessions // 3)))
        lines += ["", "## Stress: what if the rival model is wrong", "",
                  f"Mean score per duel on {len(stress_seeds)} more fresh sessions, all rival kinds, one change at a "
                  "time (best per row in bold):", "",
                  arena.stress({**named, "tuned": inc}, stress_seeds, a.session)]
    lines += ["", "## Accepted steps", "",
              "| gen | held-out objective | held-out mean | paired diff vs previous | Friday replay | selftest | "
              "mean if D-1 accepts do not settle |", "|---|---|---|---|---|---|---|"]
    for h in history:
        rp = "-" if h.get("replay") is None else f"{h['replay']:.3f}"
        sm = "-" if h.get("sim") is None else f"{h['sim']:.3f}"
        lines.append(f"| {h['gen']} | {h['hold_obj']} | {h['hold_mean']} | {h.get('paired', '-')} | {rp} | {sm} | "
                     f"{h['d1']:.3f} |")
    Path(a.report).expanduser().parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).expanduser().write_text("\n".join(lines) + "\n")


def flat_to_file(p: dict) -> dict:
    """Every tunable value, as a --params file holds them (defaults filled in)."""
    return {k: v for k, v in {**DEFAULTS, **{k: p[k] for k in TUNABLE if k in p}}.items()}


if __name__ == "__main__":
    main()
