"""Overnight broker search driver (WP11). Offline and keyless; nothing here touches the network.

    nice -n 10 python3 evals/broker-search/search.py run --until-utc 05:20 --procs 3   # the night's search
    python3 evals/broker-search/search.py board                                        # rewrite leaderboard.md
    python3 evals/broker-search/search.py confirm --spec '{"family": "blind_est", "params": {}}'
    python3 evals/broker-search/search.py plan                                         # what `run` would do

Three seed streams, so that no number in the leaderboard comes from the seeds a candidate was chosen on:
  screen   selection: 200 seeds x 4 sessions per scenario; a two-step screen (hard, standard and the pooled refit
           first, the rest of the battery only for a candidate positive on hard and not worse beyond noise on the
           other two); candidates are ranked by lab.screen_margin.
  unseen   the leaderboard: 1,000 seeds per scenario on the whole battery, for the top screened members of each family
           and for the references.
  holdout  2,000 seeds, only for a candidate the unseen run calls recommendable (the winner's-curse check).
Each round samples new members of every family (half at random, half by mutating the best screened members), screens
them, confirms the new top members, and rewrites leaderboard.md at least every 30 minutes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lab  # noqa: E402
import policies as pol  # noqa: E402

RUNS = HERE / "runs"
SCREEN = RUNS / "screen.jsonl"
CONFIRM = RUNS / "confirm.jsonl"
BOARD = HERE / "leaderboard.md"
BOARD_COPY = Path.home() / "logs" / "wp11-broker-search.leaderboard.md"
FAMILIES = ["blind_est", "timing", "hybrid", "hybrid_est"]
FAMILY_TITLES = {"blind_est": "1 blind estimates (BenchPolicy, BLIND=policy)",
                 "timing": "2 timing rules without expiries", "hybrid": "3 hybrid: stall + leave classifier swap",
                 "hybrid_est": "3b hybrid: leave classifier inside BenchPolicy"}
REFERENCES = [
    {"family": "blind_est", "params": {}, "ref": "broker.py BenchPolicy, its own priors, BLIND=policy"},
    {"family": "maxpairs", "ref": "WP2's maxpairs (memo: loses)"},
    {"family": "maxweight", "ref": "WP2's maxweight (memo: loses)"},
    {"family": "oracle_swap", "params": {"hi": 0.5, "lo": 0.5, "delta": 1.0, "max_swaps": 3, "refill": False,
                                         "sides": "both"}, "ref": "ORACLE: the swap with perfect leave flags"},
    {"family": "oracle_est", "params": {}, "ref": "ORACLE: BenchPolicy with perfect leave flags"},
    {"family": "oracle_est", "params": {"noise": 0.05}, "ref": "ORACLE: BenchPolicy, 5 % of leave flags flipped"},
    {"family": "oracle_est", "params": {"noise": 0.15}, "ref": "ORACLE: BenchPolicy, 15 % of leave flags flipped"},
    {"family": "oracle_est", "params": {"noise": 0.30}, "ref": "ORACLE: BenchPolicy, 30 % of leave flags flipped"},
]
SCREEN_SEEDS, CONFIRM_SEEDS, HOLDOUT_SEEDS, CHUNK = 200, 1000, 2000, 250
FIRST = ["hard", "standard", "refit all"]
BOARD_EVERY = 30 * 60

ACCEPTANCE = """**Acceptance rule (fixed at 02:40 Madrid, before any search run).** A candidate is *recommendable for the hard
test* only if it beats `stall` on `hard` by more than 2 SE, AND is not worse than `stall` beyond noise (diff + 1.96 SE
< 0) on ANY other scenario, the five real-session refits included, AND drops no pair the stall would have crossed
(`dropped_vs_stall` = 0: a pair the stall matched in the paired session whose two traders both leave unmatched under the
candidate), AND `bad_match` = 0. It is *recommendable everywhere* only if it also beats `stall` by more than 2 SE on
`standard` and on each of the five refits. Anything else is *not recommended*. Deployment: the policy is fixed when
the broker starts (08:55) and a restart is allowed only between tests (09:49-10:49 is the first long window), so a
hard-test-only candidate could at most run from the 10:49 test on, and the hard test (09:39) itself would run the
stall."""


def spec_id(spec: dict) -> str:
    core = {"family": spec["family"], "params": spec.get("params", {})}
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:10]


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


# ---------------------------------------------------------------- work units

def unit(job: tuple) -> tuple:
    sid, spec, label, seeds, prefix, start = job
    return sid, label, lab.evaluate(spec, label, seeds, prefix, start)


def run_units(pool, jobs: list) -> dict:
    """sid -> label -> merged row."""
    out: dict = {}
    it = pool.imap_unordered(unit, jobs) if pool else map(unit, jobs)
    for sid, label, row in it:
        d = out.setdefault(sid, {})
        d[label] = lab.merge(d[label], row) if label in d else row
    return out


def chunks(sid, spec, labels, seeds, prefix) -> list:
    return [(sid, spec, lb, min(CHUNK, seeds - s), prefix, s) for lb in labels for s in range(0, seeds, CHUNK)]


def compact(rows: dict) -> dict:
    keep = ("n", "stall", "cand", "diff", "se", "z", "win", "loss", "bad", "dropped", "dropped_sessions",
            "dropped_vs_stall")
    return {lb: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if k in keep}
            for lb, r in rows.items()}


def screen(pool, specs: list) -> list:
    """Two-step screen on the `screen` seeds; returns the screen records (also appended to SCREEN)."""
    jobs = [j for sp in specs for j in chunks(spec_id(sp), sp, FIRST, SCREEN_SEEDS, "screen")]
    first = run_units(pool, jobs)
    rest_labels = [lb for lb in lab.battery() if lb not in FIRST]
    go = [sp for sp in specs if first[spec_id(sp)]["hard"]["z"] > 0
          and all(not lab.worse(first[spec_id(sp)][lb]) for lb in FIRST[1:])]
    more = run_units(pool, [j for sp in go for j in chunks(spec_id(sp), sp, rest_labels, SCREEN_SEEDS, "screen")])
    recs = []
    for sp in specs:
        sid = spec_id(sp)
        rows = {**first[sid], **more.get(sid, {})}
        full = all(lb in rows for lb in lab.battery(extra=False))
        rec = {"sid": sid, "family": sp["family"], "params": sp.get("params", {}), "full": full,
               "margin": lab.screen_margin(rows) if full else None,
               "mean_diff": sum(r["diff"] for r in rows.values()) / len(rows), "rows": compact(rows),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        append(SCREEN, rec)
        recs.append(rec)
    return recs


def confirm(pool, spec: dict, prefix: str = "unseen", seeds: int = CONFIRM_SEEDS) -> dict:
    sid = spec_id(spec)
    rows = run_units(pool, chunks(sid, spec, lab.battery(), seeds, prefix))[sid]
    v, why = lab.verdict(rows)
    rec = {"sid": sid, "family": spec["family"], "params": spec.get("params", {}), "ref": spec.get("ref"),
           "prefix": prefix, "seeds": seeds, "verdict": v, "why": why, "rows": compact(rows),
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    append(CONFIRM, rec)
    return rec


# ---------------------------------------------------------------- sampling

def mutate(params: dict, family: str, rng: random.Random) -> dict:
    """Copy of params with one to three keys redrawn from a fresh sample of the same family (for timing, a fresh
    sample of the same mechanism)."""
    fresh = pol.sample(family, rng)
    for _ in range(50):
        if family != "timing" or fresh["mech"] == params.get("mech"):
            break
        fresh = pol.sample(family, rng)
    out = dict(params)
    keys = [k for k in out if k in fresh and k != "mech"]
    for k in rng.sample(keys, min(len(keys), rng.randint(1, 3))):
        out[k] = fresh[k]
    if "rho_slow" in out:
        out["rho_slow"] = min(out["rho_slow"], out["rho_fast"])
    if family == "hybrid":
        out["lo"] = min(out["lo"], out["hi"])
    if family == "blind_est":
        out["imp"] = [out["imp"][0], max(out["imp"][1], out["imp"][0] + 1)]
        out["pat"] = [out["pat"][0], max(out["pat"][1], out["pat"][0] + 2)]
    return out


def partial_margin(rec: dict) -> float:
    """lab.screen_margin when the whole battery was screened; else the same margin over the first step's scenarios
    (hard, standard, pooled refit), minus 100 so fully screened members always rank first."""
    if rec.get("full"):
        return rec["margin"]
    rows = rec["rows"]
    return min(rows["hard"]["z"] - 2.0, *(rows[k]["z"] + 1.96 for k in FIRST[1:])) - 100.0


def top(recs: list, family: str, k: int) -> list:
    """The family's best screened members: fully screened first (by margin), then the rest (by first-step margin)."""
    fam = [r for r in recs if r["family"] == family]
    return sorted(fam, key=lambda r: (partial_margin(r), r["mean_diff"]), reverse=True)[:k]


def new_specs(recs: list, rng: random.Random, per_family: int) -> list:
    seen = {r["sid"] for r in recs}
    out = []
    for fam in FAMILIES:
        best = top(recs, fam, 5)
        tries = 0
        made = 0
        while made < per_family and tries < 50 * per_family:
            tries += 1
            if best and made % 2 == 1:
                params = mutate(rng.choice(best)["params"], fam, rng)
            else:
                params = pol.sample(fam, rng)
            sp = {"family": fam, "params": params}
            if spec_id(sp) in seen:
                continue
            seen.add(spec_id(sp))
            out.append(sp)
            made += 1
    return out


# ---------------------------------------------------------------- leaderboard

def cell(r: dict | None) -> str:
    if not r:
        return "-"
    return f"{r['diff']:+.4f} ±{1.96 * r['se']:.4f}"


def best_confirmed(conf: list, family: str):
    rank = {"recommendable everywhere": 3, "recommendable for the hard test": 2, "not recommended": 1,
            "incomplete": 0}
    fam = [c for c in conf if c["family"] == family and not c.get("ref") and c["prefix"] == "unseen"]
    if not fam:
        return None
    return max(fam, key=lambda c: (rank[c["verdict"]], lab.screen_margin(c["rows"]),
                                   sum(r["diff"] for r in c["rows"].values())))


def write_board(started: float | None = None, note: str = "") -> None:
    scr, conf = read_jsonl(SCREEN), read_jsonl(CONFIRM)
    labels = lab.battery()
    now = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=2)))
    out = [f"# Broker overnight search: leaderboard", "",
           f"Updated {now:%H:%M} Madrid ({len(scr)} candidates screened, {len(conf)} confirmed runs). "
           f"{note}".rstrip(), "", ACCEPTANCE, "",
           "Cells: candidate − stall in efficiency (share of the best possible gains), 95 % CI = ±1.96 SE, on 1,000 "
           "`unseen` seeds × 4 sessions per scenario (selection used separate `screen` seeds). `drop` = pairs the stall "
           "crossed that the candidate let both traders leave unmatched, summed over the required scenarios; the stall's "
           "own count of crossable pairs left unmatched is always 0. `bad` = matches the guard or the engine refused.",
           ""]
    head = "| row | verdict | " + " | ".join(labels) + " | drop | bad |"
    out += [head, "|" + "---|" * (len(labels) + 4)]

    def line(name, c):
        rows = c["rows"]
        req = lab.battery(extra=False)
        drop = sum(rows[k].get("dropped_vs_stall", 0) for k in req if k in rows)
        bad = sum(rows[k].get("bad", 0) for k in req if k in rows)
        return (f"| {name} | {c['verdict']} | " + " | ".join(cell(rows.get(lb)) for lb in labels)
                + f" | {drop} | {bad} |")

    for fam in FAMILIES:
        c = best_confirmed(conf, fam)
        if c:
            out.append(line(f"{FAMILY_TITLES[fam]} `{c['sid']}`", c))
        else:
            out.append(f"| {FAMILY_TITLES[fam]} | not confirmed yet | " + " | ".join("-" for _ in labels) + " | | |")
    refs = {}
    for c in conf:
        if c.get("ref") and c["prefix"] == "unseen":
            refs[c["ref"]] = c
    for name, c in refs.items():
        out.append(line(f"ref: {name}", c))
    hold = [c for c in conf if c["prefix"] == "holdout"]
    if hold:
        out += ["", "## Holdout runs (2,000 `holdout` seeds, only for candidates the unseen run called recommendable)",
                "", head, "|" + "---|" * (len(labels) + 4)]
        out += [line(f"{c['family']} `{c['sid']}`", c) for c in hold]
    out += ["", "## Best members (parameters, and why the rule says what it says)", ""]
    for fam in FAMILIES:
        c = best_confirmed(conf, fam)
        n_scr = sum(r["family"] == fam for r in scr)
        n_full = sum(r["family"] == fam and r.get("full") for r in scr)
        n_conf = sum(x["family"] == fam and not x.get("ref") and x["prefix"] == "unseen" for x in conf)
        out.append(f"- **{FAMILY_TITLES[fam]}**: {n_scr} screened, {n_full} passed the first screen step, {n_conf} "
                   f"confirmed.")
        if c:
            out.append(f"  best `{c['sid']}` {json.dumps(c['params'], sort_keys=True)}: {c['verdict']}"
                       + (f" ({'; '.join(c['why'])})" if c["why"] else ""))
    out += ["", "## Every confirmed run", "", "| row | prefix | verdict | hard | standard | refits (min z) | worst z | "
            "drop |", "|---|---|---|---|---|---|---|---|"]
    for c in conf:
        rows = c["rows"]
        req = lab.battery(extra=False)
        refit_z = min(rows[f"refit {r}"]["z"] for r in lab.REFITS)
        worst = min(req, key=lambda k: rows[k]["z"])
        drop = sum(rows[k].get("dropped_vs_stall", 0) for k in req)
        name = f"ref: {c['ref']}" if c.get("ref") else f"{c['family']} `{c['sid']}`"
        out.append(f"| {name} | {c['prefix']} | {c['verdict']} | {cell(rows['hard'])} | {cell(rows['standard'])} | "
                   f"{refit_z:+.1f} | {worst} {rows[worst]['z']:+.1f} | {drop} |")
    text = "\n".join(out) + "\n"
    BOARD.write_text(text)
    try:
        BOARD_COPY.parent.mkdir(parents=True, exist_ok=True)
        BOARD_COPY.write_text(text)
    except OSError:
        pass


# ---------------------------------------------------------------- commands

def until_ts(hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    now = dt.datetime.now(dt.timezone.utc)
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t < now - dt.timedelta(hours=1):
        t += dt.timedelta(days=1)
    return t.timestamp()


def cmd_run(args) -> int:
    import multiprocessing as mp
    deadline = until_ts(args.until_utc)
    rng = random.Random(args.rng)
    pool = mp.Pool(args.procs) if args.procs > 1 else None
    conf = read_jsonl(CONFIRM)
    done = {(c["sid"], c["prefix"]) for c in conf}
    for ref in REFERENCES:
        if (spec_id(ref), "unseen") not in done:
            print(f"reference {ref['ref']}", flush=True)
            confirm(pool, ref)
    write_board(note="References confirmed; search starting.")
    last_board = time.time()
    rnd = 0
    while time.time() < deadline - args.margin:
        rnd += 1
        recs = read_jsonl(SCREEN)
        specs = new_specs(recs, rng, args.per_family)
        t0 = time.time()
        screen(pool, specs)
        recs = read_jsonl(SCREEN)
        print(f"round {rnd}: screened {len(specs)} in {time.time() - t0:.0f}s; total {len(recs)}", flush=True)
        done = {(c["sid"], c["prefix"]) for c in read_jsonl(CONFIRM)}
        if time.time() - last_board >= BOARD_EVERY - 300 or rnd == 1:
            for fam in FAMILIES:
                for r in top(recs, fam, args.confirm_top):
                    if (r["sid"], "unseen") in done or time.time() > deadline - args.margin / 2:
                        continue
                    sp = {"family": fam, "params": r["params"]}
                    c = confirm(pool, sp)
                    print(f"  confirmed {fam} {r['sid']}: {c['verdict']}", flush=True)
                    if c["verdict"].startswith("recommendable") and (r["sid"], "holdout") not in done:
                        h = confirm(pool, sp, "holdout", HOLDOUT_SEEDS)
                        print(f"  holdout {fam} {r['sid']}: {h['verdict']}", flush=True)
            write_board(note=f"Search running (round {rnd}).")
            last_board = time.time()
    write_board(note="Search finished.")
    if pool:
        pool.close()
    return 0


def cmd_confirm(args) -> int:
    import multiprocessing as mp
    spec = json.loads(args.spec)
    pool = mp.Pool(args.procs) if args.procs > 1 else None
    c = confirm(pool, spec, args.prefix, args.seeds)
    print(json.dumps({k: c[k] for k in ("sid", "verdict", "why")}))
    for lb, r in c["rows"].items():
        print(f"  {lb:<16} {r['diff']:+.4f} ±{1.96 * r['se']:.4f} z {r['z']:+.1f} drop {r['dropped_vs_stall']}")
    write_board()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--until-utc", required=True, help="HH:MM UTC to stop starting new work (Madrid = UTC+2)")
    r.add_argument("--procs", type=int, default=3)
    r.add_argument("--per-family", type=int, default=6)
    r.add_argument("--confirm-top", type=int, default=2)
    r.add_argument("--margin", type=float, default=600.0, help="seconds before the deadline to stop")
    r.add_argument("--rng", default="wp11")
    c = sub.add_parser("confirm")
    c.add_argument("--spec", required=True)
    c.add_argument("--prefix", default="unseen")
    c.add_argument("--seeds", type=int, default=CONFIRM_SEEDS)
    c.add_argument("--procs", type=int, default=3)
    sub.add_parser("board")
    sub.add_parser("plan")
    args = ap.parse_args(argv)
    if args.mode == "board":
        write_board()
        print(BOARD.read_text())
        return 0
    if args.mode == "plan":
        print("families:", FAMILIES)
        print("references:", [r["ref"] for r in REFERENCES])
        print("battery:", lab.battery())
        print(f"seeds: screen {SCREEN_SEEDS}, unseen {CONFIRM_SEEDS}, holdout {HOLDOUT_SEEDS}")
        return 0
    return {"run": cmd_run, "confirm": cmd_confirm}[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
