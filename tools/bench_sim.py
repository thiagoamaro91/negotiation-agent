"""Market Test lab: synthetic bench sessions that compare the free stall's rule with our broker's policy.

Offline and keyless: nothing here touches the network. Both policies see the same sessions (paired seeds), so a
difference is the policy, not the draw. Each seed is a day of DAY (4) sessions met by one policy object, as the live
broker meets Saturday's sessions; every session is one sample in the table.

    python3 tools/bench_sim.py table --seeds 2000                       # standard and hard mixes
    python3 tools/bench_sim.py table --seeds 2000 --scenarios all --procs 8 --json results/sweep.json
    python3 tools/bench_sim.py list                                     # every scenario and what it changes
    python3 tools/bench_sim.py show --scenario hard --seed 3            # one session, tick by tick

Assumptions (each one is a knob of a scenario below; `--scenarios all` sweeps the ones that matter):
  A1 Traders. A session has N traders (10; 12 in the hard test), each a buyer or a seller of one unit with a true
     limit: buyers' values U(30, 80), sellers' costs U(20, 70) (overlapping ranges, the classic double-auction lab).
     Sides are 5/5 (6/6) by default; sweeps try random sides and 6/4, 4/6 splits.
  A2 Shading. Each trader quotes away from its limit by a share s ~ U(0, smax), smax 0.3: a buyer bids
     floor(L (1 - s r)), a seller asks ceil(L (1 + s r)), r = the share of the shading still in the quote.
  A3 Patience. A trader arriving at tick a stays P ticks (a .. a+P-1) unless matched, then leaves unmatched.
     P: impatient (share 0.4) U{2..5}, patient U{8..16}. The session is 16 ticks; whoever is left then leaves.
  A4 Relaxing vs firm. Firm traders (share 0.25) keep r = 1. Relaxing ones go from r = 1 at arrival to r = 1 - relax
     at their last tick along r = 1 - relax x^beta, x = elapsed share of their patience (beta 1: linear; > 1: hold,
     then concede late; < 1: concede early). relax 1 = the quote reaches the limit on the last tick.
  A5 Arrivals. a ~ U{0..7} (staggered); sweeps: everyone at tick 0, late (4..12), two waves (0 and 8).
  A6 One tick. Arrivals quote, the broker reads the book once and sends matches, the engine settles every valid match
     (two live offers of one run, a seller and a buyer, ask <= price <= bid - fee, each offer once), then traders at
     their last tick leave. A refused match moves nothing. Quotes are exogenous: no trader reacts to the broker.
  A7 Ids. A trader keeps its offer id ("b12-7") for the whole session and the price moves in place. ids=requote
     gives a new id every tick, so nothing can be tracked: the policy must fall back to the stall, not below it.
  A9 Expiry. By default a bench offer shows no expiry (the conservative case: who leaves when must be guessed).
     expiry=exact: each offer shows expires_tick = its trader's last tick; end: every offer shows the session's last
     tick (no information); early: the trader really leaves up to early_max (2) ticks BEFORE the tick its offer
     shows (early4: up to 4).
  A8 Score. Efficiency = gains realised between TRUE limits / the best possible gains, the max-weight matching on
     true limits over every trader of the session, ignoring when they were present (buyers' values high to low
     against sellers' costs low to high, while value > cost). The textbook denominator; the server may use another,
     but it is the same for both policies in a session, so the paired comparison (win rate) does not depend on it.
     Also reported: the ceiling, the best any broker that respects quotes could do (a max-weight matching over the
     pairs that ever crossed while both were on the book), so the room above the stall is visible.

The stall is the kit's bench_plan itself (kit/starter_broker.py), imported, not copied. Ours is agent/broker.py
BenchPolicy, with its priors fixed at the standard mix: in every other scenario the truth differs from what the policy
believes, which is the robustness test. "stall1" is a second reading of the rules ("crosses its best bid and ask every
tick"): one pair per tick.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from starter_broker import bench_plan  # noqa: E402  (the stall's exact rule)
import broker as brk  # noqa: E402

TICKS = 16  # a Market Test session (schedule: "ticks": 16)
DAY = 4     # sessions one broker process sees in a row (Saturday has 8; what it learns in one carries to the next)

BASE = {
    "traders": 10, "sides": "balanced",           # A1
    "buy": (30, 80), "sell": (20, 70),            # A1 limits
    "smax": 0.30, "sfix": None,                   # A2 shading U(0, smax), or every trader at sfix
    "imp_share": 0.4, "imp": (2, 5), "pat": (8, 16),  # A3 patience mix
    "firm": 0.25, "relax": 1.0, "beta": 1.0,      # A4
    "arrive": "stagger", "arr_max": 7,            # A5
    "ids": "stable", "makers": False,             # A7 (makers: each offer carries a pseudonym, as team offers do)
    "expiry": "none", "early_max": 2,             # A9: what expires_tick a bench offer shows
    "fee_bps": 0, "fee_card": 0,                  # our venue: zero fee
}

HARD = {"traders": 12, "firm": 0.5, "imp_share": 0.6, "imp": (1, 4), "pat": (5, 10)}  # firmer, more impatient

SCENARIOS = {
    "standard": {},
    "hard": HARD,
    # A2 shading
    "shade_0": {"smax": 0.0}, "shade_10": {"smax": 0.10}, "shade_20": {"smax": 0.20}, "shade_40": {"smax": 0.40},
    "shade_fix20": {"sfix": 0.20}, "shade_fix40": {"sfix": 0.40},
    # A3 patience
    "all_patient": {"imp_share": 0.0}, "all_impatient": {"imp_share": 1.0}, "imp_70": {"imp_share": 0.7},
    "short_patience": {"imp": (1, 3), "pat": (4, 8)}, "long_patience": {"imp": (4, 8), "pat": (12, 16)},
    # A4 firm share and relaxing curve
    "firm_0": {"firm": 0.0}, "firm_50": {"firm": 0.5}, "firm_80": {"firm": 0.8}, "firm_100": {"firm": 1.0},
    "concede_late": {"beta": 3.0}, "concede_early": {"beta": 0.4}, "relax_half": {"relax": 0.5},
    "relax_late_half": {"beta": 2.0, "relax": 0.6},
    # A5 arrivals
    "arrive_all0": {"arrive": "all0"}, "arrive_late": {"arrive": "late"}, "arrive_waves": {"arrive": "waves"},
    "arrive_spread": {"arr_max": 12},
    # A1 sides and limits
    "sides_random": {"sides": "random"}, "more_buyers": {"sides": "6/4"}, "more_sellers": {"sides": "4/6"},
    "wide_overlap": {"buy": (20, 90), "sell": (10, 80)}, "thin_overlap": {"buy": (45, 80), "sell": (20, 55)},
    "cheap_cards": {"buy": (6, 16), "sell": (4, 14)},
    # A7 ids
    "requote_ids": {"ids": "requote"}, "makers": {"makers": True},
    # A9 expiry shown in the book
    "expiry_exact": {"expiry": "exact"}, "expiry_end": {"expiry": "end"}, "expiry_early": {"expiry": "early"},
    "expiry_early4": {"expiry": "early", "early_max": 4},
    "hard_expiry_exact": {**HARD, "expiry": "exact"}, "hard_expiry_early": {**HARD, "expiry": "early"},
    # hard, with the same twists
    "hard_shade_40": {**HARD, "smax": 0.40}, "hard_all0": {**HARD, "arrive": "all0"},
    "hard_firm_80": {**HARD, "firm": 0.8}, "hard_concede_late": {**HARD, "beta": 3.0},
    "hard_random_sides": {**HARD, "sides": "random"}, "hard_requote": {**HARD, "ids": "requote"},
    # a worst case for any policy that trusts its priors: everything differs at once
    "adversarial": {"smax": 0.40, "imp_share": 0.7, "imp": (1, 3), "pat": (4, 8), "firm": 0.6, "beta": 3.0,
                    "relax": 0.6, "arrive": "all0", "sides": "random"},
}


def scenario(name: str) -> dict:
    return {**BASE, **SCENARIOS[name], "name": name}


# ---------------------------------------------------------------- sessions

def make_session(rng: random.Random, sc: dict, run: str = "b1") -> list:
    """The traders of one session (A1-A5). Each: id, side, limit, s, firm, P, a."""
    n = sc["traders"]
    if sc["sides"] == "balanced":
        sides = ["buy"] * (n // 2) + ["sell"] * (n - n // 2)
    elif sc["sides"] == "random":
        sides = [rng.choice(("buy", "sell")) for _ in range(n)]
    else:
        nb, ns = (int(x) for x in sc["sides"].split("/"))
        sides = ["buy"] * round(n * nb / (nb + ns))
        sides += ["sell"] * (n - len(sides))
    rng.shuffle(sides)
    out = []
    for i, side in enumerate(sides):
        lo, hi = sc["buy"] if side == "buy" else sc["sell"]
        imp = rng.random() < sc["imp_share"]
        plo, phi = sc["imp"] if imp else sc["pat"]
        if sc["arrive"] == "all0":
            a = 0
        elif sc["arrive"] == "late":
            a = rng.randint(4, 12)
        elif sc["arrive"] == "waves":
            a = rng.choice((0, 8))
        else:
            a = rng.randint(0, sc["arr_max"])
        out.append({"id": f"{run}-{i + 1}", "side": side, "limit": rng.uniform(lo, hi),
                    "s": sc["sfix"] if sc["sfix"] is not None else rng.uniform(0, sc["smax"]),
                    "firm": rng.random() < sc["firm"], "P": rng.randint(plo, phi), "a": a,
                    "maker": f"m{rng.randrange(16 ** 6):06x}", "early": rng.randint(0, sc["early_max"])})
    return out


def quote(tr: dict, t: int, sc: dict) -> int:
    """A2 + A4: the trader's whole-prima quote at tick t (never past its limit)."""
    if tr["firm"]:
        r = 1.0
    else:
        x = (t - tr["a"]) / (tr["P"] - 1) if tr["P"] > 1 else 1.0
        r = 1.0 - sc["relax"] * min(1.0, max(0.0, x)) ** sc["beta"]
    if tr["side"] == "buy":
        return max(1, math.floor(tr["limit"] * (1 - tr["s"] * r)))
    return max(1, math.ceil(tr["limit"] * (1 + tr["s"] * r)))


def present(tr: dict, t: int) -> bool:
    return tr["a"] <= t <= min(tr["a"] + tr["P"] - 1, TICKS - 1)


def best_gain(traders: list) -> float:
    """A8: max-weight matching on true limits, ignoring time (sorted buyers against sorted sellers)."""
    v = sorted((t["limit"] for t in traders if t["side"] == "buy"), reverse=True)
    c = sorted(t["limit"] for t in traders if t["side"] == "sell")
    return sum(max(0.0, b - s) for b, s in zip(v, c))


def ceiling_gain(traders: list, sc: dict) -> float:
    """The best a quote-respecting broker could do: max-weight matching over pairs that ever crossed while both were
    on the book (quotes do not react to the broker, so any such disjoint set of pairs is reachable)."""
    buyers = [t for t in traders if t["side"] == "buy"]
    sellers = [t for t in traders if t["side"] == "sell"]
    ok = {}
    for i, b in enumerate(buyers):
        for j, s in enumerate(sellers):
            for t in range(TICKS):
                if present(b, t) and present(s, t) and quote(b, t, sc) >= quote(s, t, sc):
                    ok[(i, j)] = b["limit"] - s["limit"]
                    break
    pairs = brk.best_matching(len(buyers), len(sellers), lambda i, j: ok.get((i, j)))
    return sum(ok[p] for p in pairs)


def offer(tr: dict, oid: str, q: int, sc: dict, t0: int = 0) -> dict:
    o = {"id": oid, "status": "open"}
    if tr["side"] == "sell":
        o["give"] = {"cash": 0, "assets": [{"kind": "card", "ref": "BEN-01"}], "types": []}
        o["want"] = {"cash": q, "assets": [], "types": []}
    else:
        o["give"] = {"cash": q, "assets": [], "types": []}
        o["want"] = {"cash": 0, "assets": [], "types": ["card:BEN-01"]}
    if sc["makers"]:
        o["maker"] = tr["maker"]
    last = min(tr["a"] + tr["P"] - 1, TICKS - 1)
    if sc["expiry"] == "exact":
        o["expires_tick"] = t0 + last
    elif sc["expiry"] == "end":
        o["expires_tick"] = t0 + TICKS - 1
    elif sc["expiry"] == "early":
        o["expires_tick"] = t0 + min(TICKS - 1, last + tr["early"])
    return o


def simulate(traders: list, sc: dict, policy, trace: list | None = None, t0: int = 0) -> dict:
    """A6: run one session. policy(book, tick) -> [(sell, buy, price)]. Returns gain, matches, refused. t0: the
    game tick of the session's first tick (a policy that lives all day sees later sessions at later ticks)."""
    by_id = {}
    alive = {t["id"]: t for t in traders}
    gain, matches, refused = 0.0, 0, 0
    n_quote = 0
    for t in range(TICKS):
        offers = []
        for tr in traders:
            if tr["id"] in alive and present(tr, t):
                if sc["ids"] == "requote":
                    n_quote += 1
                    oid = f"{tr['id'].split('-')[0]}-{n_quote}"
                else:
                    oid = tr["id"]
                by_id[oid] = tr
                offers.append(offer(tr, oid, quote(tr, t, sc), sc, t0))
        book = {"venue": "v99", "tick": t0 + t, "fee_bps": sc["fee_bps"], "fee_per_card": sc["fee_card"], "offers": [],
                "bench_offers": offers}
        live = {o["id"]: o for o in offers}
        used = set()
        plan = policy(book, t0 + t) if offers else []
        for m in plan:
            try:
                sell, buy, price = m
                s, b = live[sell], live[buy]
            except (KeyError, TypeError, ValueError):
                refused += 1
                continue
            ask, bid = s["want"]["cash"], b["give"]["cash"]
            fee = brk.fee_of(book, price) if isinstance(price, int) else 0
            if (sell in used or buy in used or brk.run_of(sell) != brk.run_of(buy) or not ask or not bid
                    or not isinstance(price, int) or price < ask or price + fee > bid):
                refused += 1
                continue
            used.update((sell, buy))
            ts, tb = by_id[sell], by_id[buy]
            gain += tb["limit"] - ts["limit"]
            matches += 1
            alive.pop(ts["id"], None)
            alive.pop(tb["id"], None)
            if trace is not None:
                trace.append((t, sell, buy, price, round(tb["limit"] - ts["limit"], 1)))
        if trace is not None:
            trace.append((t, "book", [(o["id"], o["want"]["cash"] or o["give"]["cash"]) for o in offers]))
    return {"gain": gain, "matches": matches, "refused": refused}


def policies(sc: dict, params: dict | None = None) -> dict:
    """Fresh policy callables for one session. params: overrides for BenchPolicy (to test variants)."""
    ours = brk.BenchPolicy(params)

    def ours_fn(book, t):
        plan = ours.plan(book, t)
        ok, _ = brk.guard(plan, book)
        for sell, buy, _p in ok:
            ours.sent(sell, buy, t)
        return ok

    def stall1(book, t):
        out, seen = [], set()
        for m in bench_plan(book):
            r = brk.run_of(m[0])
            if r not in seen:
                seen.add(r)
                out.append(m)
        return out

    return {"stall": lambda book, t: bench_plan(book), "ours": ours_fn, "stall1": stall1}


# ---------------------------------------------------------------- statistics

def run_scenario(args) -> dict:
    name, seeds, extra, params = args
    sc = {**scenario(name), **(extra or {})}
    effs = {"stall": [], "ours": [], "stall1": [], "ceiling": []}
    diffs, refused = [], 0
    t0 = time.time()
    for seed in range(seeds):
        rng = random.Random(f"{name}:{seed}")
        day = [make_session(rng, sc, run=f"b{k + 1}") for k in range(DAY)]
        fns = policies(sc, params)  # one broker process for the whole day: what it learns carries over
        for k, traders in enumerate(day):
            best = best_gain(traders)
            res = {}
            for pname, fn in fns.items():
                r = simulate(traders, sc, fn, t0=100 * k)
                res[pname] = r["gain"] / best if best > 1e-9 else None
                if pname == "ours":
                    refused += r["refused"]
            if best <= 1e-9:
                continue
            res["ceiling"] = ceiling_gain(traders, sc) / best
            for key in effs:
                effs[key].append(res[key])
            diffs.append(res["ours"] - res["stall"])
    n = len(diffs)

    def p10(xs):
        xs = sorted(xs)
        return xs[max(0, math.ceil(0.10 * len(xs)) - 1)] if xs else float("nan")

    sd = statistics.pstdev(diffs) if n > 1 else 0.0
    return {"scenario": name, "n": n, "secs": round(time.time() - t0, 1),
            **{f"{k}_mean": statistics.fmean(v) for k, v in effs.items()},
            **{f"{k}_p10": p10(v) for k, v in effs.items()},
            "diff_mean": statistics.fmean(diffs), "diff_ci95": 1.96 * sd / math.sqrt(n) if n else 0.0,
            "win": sum(d > 1e-9 for d in diffs) / n, "tie": sum(abs(d) <= 1e-9 for d in diffs) / n,
            "loss": sum(d < -1e-9 for d in diffs) / n, "worst_diff": min(diffs), "ours_refused": refused}


def fmt_table(rows: list) -> str:
    head = (f"{'scenario':<20} {'n':>5} | {'stall':>6} {'p10':>6} | {'ours':>6} {'p10':>6} | {'diff':>7} {'+-95%':>6} "
            f"| {'win':>5} {'tie':>5} {'loss':>5} | {'ceil':>6} {'stall1':>6}")
    out = [head, "-" * len(head)]
    for r in rows:
        out.append(f"{r['scenario']:<20} {r['n']:>5} | {r['stall_mean']:6.3f} {r['stall_p10']:6.3f} | "
                   f"{r['ours_mean']:6.3f} {r['ours_p10']:6.3f} | {r['diff_mean']:+7.4f} {r['diff_ci95']:6.4f} | "
                   f"{r['win']:5.1%} {r['tie']:5.1%} {r['loss']:5.1%} | {r['ceiling_mean']:6.3f} "
                   f"{r['stall1_mean']:6.3f}")
    return "\n".join(out)


def cmd_table(args) -> int:
    names = list(SCENARIOS) if args.scenarios == "all" else [s.strip() for s in args.scenarios.split(",") if s.strip()]
    for nm in names:
        if nm not in SCENARIOS:
            raise SystemExit(f"unknown scenario {nm}; see `list`")
    params = json.loads(args.params) if args.params else None
    jobs = [(nm, args.seeds, None, params) for nm in names]
    if args.procs > 1:
        import multiprocessing as mp
        with mp.Pool(args.procs) as pool:
            rows = pool.map(run_scenario, jobs, chunksize=1)
    else:
        rows = [run_scenario(j) for j in jobs]
    print(fmt_table(rows), flush=True)
    worse = [r["scenario"] for r in rows if r["diff_mean"] + r["diff_ci95"] < 0]
    print(f"\nscenarios where ours is significantly below the stall: {worse or 'none'}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({"seeds": args.seeds, "rows": rows}, indent=1) + "\n")
    bad = sum(r["ours_refused"] for r in rows)
    if bad:
        print(f"WARNING: the engine refused {bad} of our matches (the guard should make that impossible)")
    return 1 if bad else 0


def cmd_show(args) -> int:
    sc = scenario(args.scenario)
    traders = make_session(random.Random(f"{args.scenario}:{args.seed}"), sc)
    for tr in sorted(traders, key=lambda x: (x["side"], -x["limit"])):
        print(f"  {tr['id']:>6} {tr['side']:<4} limit {tr['limit']:6.1f} s {tr['s']:.2f} "
              f"{'firm' if tr['firm'] else 'relax'} arrive {tr['a']:>2} patience {tr['P']:>2}")
    best = best_gain(traders)
    print(f"best {best:.1f}, ceiling {ceiling_gain(traders, sc):.1f}")
    for pname, fn in policies(sc).items():
        trace = []
        r = simulate(traders, sc, fn, trace)
        print(f"\n{pname}: gain {r['gain']:.1f} ({r['gain'] / best:.3f}), {r['matches']} matches")
        for row in trace:
            if row[1] != "book":
                print(f"  tick {row[0]:>2}: {row[1]} x {row[2]} at {row[3]} (true gain {row[4]})")
            elif args.books:
                print(f"  tick {row[0]:>2} book {row[2]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("table", help="stall vs ours per scenario")
    t.add_argument("--seeds", type=int, default=1000)
    t.add_argument("--scenarios", default="standard,hard", help="comma list, or all")
    t.add_argument("--procs", type=int, default=1)
    t.add_argument("--json", default=None, help="also write the rows here (results/ is not committed)")
    t.add_argument("--params", default=None, help="BenchPolicy overrides as JSON, e.g. '{\"future\": 0.5}'")
    sub.add_parser("list", help="the scenarios")
    s = sub.add_parser("show", help="one session, tick by tick")
    s.add_argument("--scenario", default="standard")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--books", action="store_true")
    args = ap.parse_args(argv)
    if args.mode == "list":
        for nm, d in SCENARIOS.items():
            print(f"{nm:<20} {d or '(the base mix)'}")
        return 0
    return cmd_table(args) if args.mode == "table" else cmd_show(args)


if __name__ == "__main__":
    raise SystemExit(main())
