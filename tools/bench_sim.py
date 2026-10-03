"""Market Test lab: synthetic bench sessions that compare the free stall's rule with our broker's policy.

Offline and keyless: nothing here touches the network. Both policies see the same sessions (paired seeds), so a
difference is the policy, not the draw. Each seed is a day of DAY (4) sessions met by one policy object, as the live
broker meets Saturday's sessions; every session is one sample in the table.

    python3 tools/bench_sim.py table --seeds 2000                       # standard and hard mixes
    python3 tools/bench_sim.py table --seeds 2000 --scenarios all --procs 8 --json results/sweep.json
    python3 tools/bench_sim.py list                                     # every scenario and what it changes
    python3 tools/bench_sim.py show --scenario hard --seed 3            # one session, tick by tick
    python3 tools/bench_sim.py refit --log logs/broker/2026-10-03.jsonl --seeds 500   # after a real session
    python3 tools/bench_sim.py refit --log logs/broker/2026-10-03.jsonl --seeds 500 --runs b53   # one session
    python3 tools/bench_sim.py replay --log logs/broker/2026-10-03.jsonl --run b36   # a run nothing matched
    python3 tools/bench_sim.py candidate --policy maxweight --scenarios hard,standard --refit-runs all,b36

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
     expiry=exact: each offer shows expires_tick = its trader's last tick (gone_at: the tick after it, the other
     reading of an expiry); end: every offer shows the session's last
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
tick"): one pair per tick. "maxpairs" pairs, every tick, as many crossing offers as possible (ties: the largest sum of
bid - ask); docs/plans/market-test-sunday.md has its verdict (it loses to the stall), and `table` prints it against the
stall in a second table.
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
    "expiry_gone_at": {"expiry": "gone_at"}, "hard_expiry_gone_at": {**HARD, "expiry": "gone_at"},
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


def maxpairs_run(asks: list, bids: list, book: dict | None = None) -> list:
    """Every tick, among the offers whose quotes cross now, the matching with the most pairs; ties broken by the
    largest sum of (bid - ask); each pair at its midpoint (lowered for the fee, as every match we send). asks, bids:
    [(quote, id)] of ONE bench run. When the stall's own pairs are already that many, the stall's plan is returned
    as it is (same pairs, same prices).

    Exact: a buyer crosses every seller whose ask is at most its bid (with the fee, still monotone), so the
    neighbourhoods are nested and n pairs exist iff the n highest bids and the n lowest asks pair up in reverse order
    (highest bid with the n-th lowest ask). That set also has the largest sum of (bid - ask) among n-pair matchings,
    because the sum depends only on which offers are matched. tests/test_bench_sim.py checks it against an exhaustive
    max-weight matching with weight BIG + (bid - ask)."""
    stall = brk.stall_run(asks, bids, book)
    a = sorted(asks, key=lambda x: x[0])   # lowest ask first; stable, so the book's order among equal quotes
    b = sorted(bids, key=lambda x: -x[0])  # highest bid first

    def crosses(ask, bid) -> bool:
        return bid >= ask and (book is None or brk.price_for(book, ask, bid) is not None)

    k = next((n for n in range(min(len(a), len(b)), 0, -1)
              if all(crosses(a[n - 1 - i][0], b[i][0]) for i in range(n))), 0)
    if k <= len(stall):
        return stall
    plan = []
    for i in range(k):
        (ask, sell), (bid, buy) = a[k - 1 - i], b[i]
        plan.append((sell, buy, (ask + bid) // 2 if book is None else brk.price_for(book, ask, bid)))
    return plan


def maxpairs_plan(book: dict, skip=()) -> list:
    """maxpairs_run over every bench run of the book (a run's offers never pair with another run's)."""
    plan = []
    for asks, bids in brk.bench_quotes(book, skip).values():
        plan += maxpairs_run(asks, bids, book)
    return plan


def maxweight_plan(book: dict, skip=(), shade: float = 0.15) -> list:
    """Second candidate from the review of maxpairs: per bench run, the max-weight matching over the pairs whose
    quotes cross now, a pair's weight being its estimated true surplus under a firm-shade prior,
    bid / (1 - shade) - ask * (1 - shade); positive pairs only; each pair at its midpoint (fee counted)."""
    plan = []
    for asks, bids in brk.bench_quotes(book, skip).values():
        def w(i, j):
            (qa, _), (qb, _) = asks[i], bids[j]
            if qb < qa or brk.price_for(book, qa, qb) is None:
                return None
            v = qb / (1 - shade) - qa * (1 - shade)
            return v if v > 0 else None
        for i, j in brk.best_matching(len(asks), len(bids), w):
            plan.append((asks[i][1], bids[j][1], brk.price_for(book, asks[i][0], bids[j][0])))
    return plan


CANDIDATES = {"maxpairs": lambda book: maxpairs_plan(book), "maxweight": lambda book: maxweight_plan(book)}


def candidate_row(name: str, sc: dict, plan, seeds: int, prefix: str) -> dict:
    """candidate - stall on `seeds` x DAY sessions drawn from seeds "<prefix>:<name>:<seed>" (a prefix other than
    the table's empty one gives seeds the table never saw). bad counts matches the engine refused."""
    diffs, bad = [], 0
    for seed in range(seeds):
        rng = random.Random(f"{prefix}:{name}:{seed}" if prefix else f"{name}:{seed}")
        for k in range(DAY):
            traders = make_session(rng, sc, run=f"b{k + 1}")
            best = best_gain(traders)
            if best <= 1e-9:
                continue
            st = simulate(traders, sc, lambda b, t: bench_plan(b), t0=100 * k)["gain"]
            r = simulate(traders, sc, lambda b, t: plan(b), t0=100 * k)
            bad += r["refused"]
            diffs.append((r["gain"] - st) / best)
    n = len(diffs)
    se = statistics.pstdev(diffs) / math.sqrt(n) if n > 1 else 0.0
    m = statistics.fmean(diffs) if n else 0.0
    return {"scenario": name, "n": n, "diff": m, "se": se, "z": m / se if se else 0.0, "bad": bad}


def cmd_candidate(args) -> int:
    plan = CANDIDATES[args.policy]
    jobs = [(nm, {**scenario(nm)}) for nm in [x.strip() for x in args.scenarios.split(",") if x.strip()]]
    for runs in [x.strip() for x in (args.refit_runs or "").split(",") if x.strip()]:
        recorded = read_runs(Path(args.log))
        pick = recorded if runs == "all" else {r: recorded[r] for r in runs.split("+")}
        jobs.append((f"refit {runs}", {**BASE, **fit(pick)[1], "name": "fitted"}))
    print(f"{args.policy} - stall, {args.seeds} seeds x {DAY} sessions, seed prefix {args.prefix!r}")
    print("| scenario | sessions | diff | SE | z | bad |")
    print("|---|---|---|---|---|---|")
    bad = 0
    for nm, sc in jobs:
        r = candidate_row(nm, sc, plan, args.seeds, args.prefix)
        bad += r["bad"]
        print(f"| {nm} | {r['n']} | {r['diff']:+.4f} | {r['se']:.4f} | {r['z']:+.1f} | {r['bad']} |", flush=True)
    return 1 if bad else 0


def offer(tr: dict, oid: str, q: int, sc: dict, t0: int = 0) -> dict:
    o = {"id": oid, "status": "open", "bench": True, "maker": "bench"}  # as the game shows every bench offer
    if tr["side"] == "sell":
        o["give"] = {"cash": 0, "assets": [{"kind": "card", "ref": "BEN-01"}], "types": []}
        o["want"] = {"cash": q, "assets": [], "types": []}
    else:
        o["give"] = {"cash": q, "assets": [], "types": []}
        o["want"] = {"cash": 0, "assets": [], "types": ["card:BEN-01"]}
    if sc["makers"]:  # a pseudonym per trader instead of the game's shared "bench"
        o["maker"] = tr["maker"]
    last = min(tr["a"] + tr["P"] - 1, TICKS - 1)
    if sc["expiry"] == "exact":
        o["expires_tick"] = t0 + last
    elif sc["expiry"] == "gone_at":  # the other reading of an expiry: the first tick it is no longer there
        o["expires_tick"] = t0 + last + 1
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
        ok, bad = brk.guard(plan, book)
        ours_fn.dropped += len(bad)  # the guard dropping our own plan is a bug: the selftest fails on it
        for sell, buy, _p in ok:
            ours.sent(sell, buy, t)
        return ok
    ours_fn.dropped = 0

    def stall(book, t):
        plan = bench_plan(book)
        stall.dropped += len(brk.guard(plan, book)[1])  # what the live `run --policy stall` guard would drop
        return plan
    stall.dropped = 0

    def stall1(book, t):
        out, seen = [], set()
        for m in bench_plan(book):
            r = brk.run_of(m[0])
            if r not in seen:
                seen.add(r)
                out.append(m)
        return out

    def maxpairs(book, t):
        plan = maxpairs_plan(book)
        maxpairs.dropped += len(brk.guard(plan, book)[1])  # a match the live guard would refuse: bad_match
        return plan
    maxpairs.dropped = 0

    return {"stall": stall, "ours": ours_fn, "stall1": stall1, "maxpairs": maxpairs}


# ---------------------------------------------------------------- statistics

def run_scenario(args) -> dict:
    name, seeds, extra, params = args
    sc = {**scenario(name), **(extra or {})}
    effs = {"stall": [], "ours": [], "stall1": [], "maxpairs": [], "ceiling": []}
    diffs, mp_diffs, refused, dropped, mp_bad = [], [], 0, 0, 0
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
                if pname == "maxpairs":
                    mp_bad += r["refused"]  # the engine refused a match: it broke a quote, a run or reuse
            if best <= 1e-9:
                continue
            res["ceiling"] = ceiling_gain(traders, sc) / best
            for key in effs:
                effs[key].append(res[key])
            diffs.append(res["ours"] - res["stall"])
            mp_diffs.append(res["maxpairs"] - res["stall"])
        dropped += fns["ours"].dropped + fns["stall"].dropped
        mp_bad += fns["maxpairs"].dropped
    n = len(diffs)

    def p10(xs):
        xs = sorted(xs)
        return xs[max(0, math.ceil(0.10 * len(xs)) - 1)] if xs else float("nan")

    sd = statistics.pstdev(diffs) if n > 1 else 0.0
    mp_se = statistics.pstdev(mp_diffs) / math.sqrt(n) if n > 1 else 0.0
    return {"scenario": name, "n": n, "secs": round(time.time() - t0, 1),
            "mp_diff_mean": statistics.fmean(mp_diffs) if n else 0.0, "mp_diff_se": mp_se,
            "mp_diff_ci95": 1.96 * mp_se, "mp_win": sum(d > 1e-9 for d in mp_diffs) / n if n else 0.0,
            "mp_tie": sum(abs(d) <= 1e-9 for d in mp_diffs) / n if n else 0.0,
            "mp_loss": sum(d < -1e-9 for d in mp_diffs) / n if n else 0.0,
            "mp_worst_diff": min(mp_diffs) if n else 0.0, "mp_bad_match": mp_bad,
            **{f"{k}_mean": statistics.fmean(v) for k, v in effs.items()},
            **{f"{k}_p10": p10(v) for k, v in effs.items()},
            "diff_mean": statistics.fmean(diffs), "diff_ci95": 1.96 * sd / math.sqrt(n) if n else 0.0,
            "win": sum(d > 1e-9 for d in diffs) / n, "tie": sum(abs(d) <= 1e-9 for d in diffs) / n,
            "loss": sum(d < -1e-9 for d in diffs) / n, "worst_diff": min(diffs), "ours_refused": refused,
            "guard_dropped": dropped}


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


def fmt_mp_table(rows: list) -> str:
    """maxpairs against the stall: mean efficiencies, the paired difference with its SE and 95 % half-width (1.96 SE),
    the share of sessions it wins / ties / loses, and bad_match (a match the guard or the engine would refuse)."""
    head = (f"{'scenario':<20} {'n':>5} | {'stall':>6} {'maxp':>6} {'ceil':>6} | {'maxp-stall':>10} {'SE':>6} "
            f"{'+-95%':>6} {'z':>6} | {'win':>5} {'tie':>5} {'loss':>5} | {'worst':>7} {'bad':>4}")
    out = [head, "-" * len(head)]
    for r in rows:
        z = r["mp_diff_mean"] / r["mp_diff_se"] if r["mp_diff_se"] > 0 else 0.0
        out.append(f"{r['scenario']:<20} {r['n']:>5} | {r['stall_mean']:6.3f} {r['maxpairs_mean']:6.3f} "
                   f"{r['ceiling_mean']:6.3f} | {r['mp_diff_mean']:+10.4f} {r['mp_diff_se']:6.4f} "
                   f"{r['mp_diff_ci95']:6.4f} {z:+6.2f} | {r['mp_win']:5.1%} {r['mp_tie']:5.1%} {r['mp_loss']:5.1%} "
                   f"| {r['mp_worst_diff']:+7.3f} {r['mp_bad_match']:>4}")
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
    print("\nmaxpairs (most crossing pairs every tick) against the stall:")
    print(fmt_mp_table(rows), flush=True)
    mp_worse = [r["scenario"] for r in rows if r["mp_diff_mean"] + r["mp_diff_ci95"] < 0]
    print(f"\nscenarios where maxpairs is significantly below the stall: {mp_worse or 'none'}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({"seeds": args.seeds, "rows": rows}, indent=1) + "\n")
    mp_bad = sum(r["mp_bad_match"] for r in rows)
    if mp_bad:
        print(f"WARNING: maxpairs planned {mp_bad} matches the guard or the engine refuses (bad_match)")
    bad = sum(r["ours_refused"] for r in rows) + mp_bad
    if bad:
        print(f"WARNING: the engine refused {bad} of our matches (the guard should make that impossible)")
    dropped = sum(r.get("guard_dropped", 0) for r in rows)
    if dropped:
        print(f"WARNING: the guard dropped {dropped} planned bench matches (ours or the stall's); live, those are "
              f"never sent")
    return 1 if bad or dropped else 0


# ---------------------------------------------------------------- refit from a recorded session

def read_runs(path: Path) -> dict:
    """Bench offers' paths from a broker log (logs/broker/<date>.jsonl): run -> offer id -> side, quotes per tick,
    first/last tick seen, the tick it was gone, shown expiry, and how it ended (ours: we matched it; engine: the
    book's settlements name it, as on the free stall, where the engine crosses first; left: gone before the run's
    end; end: on the book until the run ended). Game text is never read, only numbers and ids."""
    runs, ours, settled, ticks = {}, set(), set(), []
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("event") == "matched":
            ours.update((row.get("sell"), row.get("buy")))
        book, t = row.get("book"), row.get("tick")
        if row.get("event") != "book" or not isinstance(book, dict) or not isinstance(t, (int, float)):
            continue
        ticks.append(t)
        for st in book.get("settlements") or []:
            if isinstance(st, dict):
                settled.update(v for v in st.values() if isinstance(v, str) and "-" in v)
        for o in book.get("bench_offers") or []:
            try:
                oid, ask, bid = o["id"], o["want"]["cash"], o["give"]["cash"]
            except (KeyError, TypeError):
                continue
            side, q = ("sell", ask) if ask else ("buy", bid)
            if not isinstance(q, (int, float)):
                continue
            rec = runs.setdefault(brk.run_of(oid), {}).setdefault(
                oid, {"side": side, "quotes": [], "first": t, "last": t, "expires": None})
            if rec["quotes"] and rec["quotes"][-1][0] == t:
                rec["quotes"][-1] = (t, q)
            else:
                rec["quotes"].append((t, q))
            rec["last"] = t
            exp = next((o[k] for k in brk.EXPIRY_FIELDS if isinstance(o.get(k), (int, float))), None)
            if exp is not None:
                rec["expires"] = exp
    ticks = sorted(set(ticks))
    for offers in runs.values():
        end = max(r["last"] for r in offers.values())
        for oid, r in offers.items():
            r["gone"] = next((t for t in ticks if t > r["last"]), None)
            r["how"] = ("ours" if oid in ours else "engine" if oid in settled
                        else "end" if r["last"] == end else "left")
    return runs


def fit(runs: dict) -> tuple:
    """(what the session shows, scenario overrides that reproduce it). Rough by design: one session is ~10 traders."""
    offers = [dict(r, run=run) for run, rs in runs.items() for r in rs.values()]
    if not offers:
        raise SystemExit("no bench offers in this log")
    start = {run: min(r["first"] for r in rs.values()) for run, rs in runs.items()}
    for r in offers:
        r["arrive"] = r["first"] - start[r["run"]]
        r["life"] = r["last"] - r["first"] + 1
        q0, q1 = r["quotes"][0][1], r["quotes"][-1][1]
        r["move"] = ((q1 - q0) if r["side"] == "buy" else (q0 - q1)) / max(1, q0)  # relaxation, as a share
    seen3 = [r for r in offers if r["life"] >= 3]
    firm = sum(r["move"] <= 0 for r in seen3) / len(seen3) if seen3 else None
    relaxers = sorted(r["move"] for r in offers if r["move"] > 0)
    leavers = sorted(r["life"] for r in offers if r["how"] == "left")
    exps = [r for r in offers if r["expires"] is not None]
    early = [r["expires"] - r["gone"] for r in exps if r["how"] == "left" and r["gone"] is not None]
    buys = sorted(r["quotes"][-1][1] for r in offers if r["side"] == "buy")
    sells = sorted(r["quotes"][-1][1] for r in offers if r["side"] == "sell")
    nb, ns = sum(r["side"] == "buy" for r in offers), sum(r["side"] == "sell" for r in offers)
    shows = {"runs": len(runs), "offers": len(offers), "buyers": nb, "sellers": ns,
             "arrivals": sorted(r["arrive"] for r in offers), "leaver_lifetimes": leavers,
             "ends": {h: sum(r["how"] == h for r in offers) for h in ("ours", "engine", "left", "end")},
             "firm_share_of_3plus": firm, "relaxer_moves": [round(m, 3) for m in relaxers],
             "buyer_quotes": buys, "seller_quotes": sells,
             "expiries": {"shown": len(exps), "distinct": len({r["expires"] - start[r["run"]] for r in exps}),
                          "leavers_ticks_early": early}}
    sc = {"traders": max(2, round(len(offers) / len(runs))),
          "sides": "balanced" if abs(nb - ns) <= len(runs) else "random"}
    if relaxers:
        sc["smax"] = round(min(0.6, max(0.05, 1.2 * relaxers[int(0.9 * (len(relaxers) - 1))])), 2)
    if firm is not None:
        sc["firm"] = round(firm, 2)
    if leavers:
        short = [x for x in leavers if x <= 5]
        long_ = [x for x in leavers if x > 5]
        sc["imp_share"] = round(len(short) / len(leavers), 2)
        if short:
            sc["imp"] = (min(short), max(short))
        if long_:
            sc["pat"] = (min(long_), max(16, max(long_)))
    arr = shows["arrivals"]
    sc.update({"arrive": "all0"} if max(arr) == 0 else {"arrive": "stagger", "arr_max": max(arr)})
    if buys and sells:
        top = 1 + sc.get("smax", 0.3) / 2
        sc["buy"] = (round(buys[0], 1), round(buys[-1] * top, 1))
        sc["sell"] = (round(sells[0] / top, 1), round(sells[-1], 1))
    if not exps:
        sc["expiry"] = "none"
    elif shows["expiries"]["distinct"] <= 1:
        sc["expiry"] = "end"
    elif not early or max(early) <= 0:
        sc["expiry"] = "exact"
    else:
        sc.update({"expiry": "early", "early_max": max(early)})
    return shows, sc


def cmd_refit(args) -> int:
    runs = read_runs(Path(args.log))
    if args.runs:
        want = {r.strip() for r in args.runs.split(",") if r.strip()}
        missing = want - set(runs)
        if missing:
            raise SystemExit(f"runs not in {args.log}: {sorted(missing)} (there: {sorted(runs)})")
        runs = {k: v for k, v in runs.items() if k in want}
    shows, sc = fit(runs)
    print("what the recorded session shows:")
    for k, v in shows.items():
        print(f"  {k}: {v}")
    print("\nscenario overrides that reproduce it (on top of the base mix):")
    print(f"  {json.dumps(sc)}")
    if args.seeds:
        SCENARIOS["fitted"] = sc
        rows = [run_scenario(("fitted", args.seeds, None, None))]
        print()
        print(fmt_table(rows))
        print()
        print(fmt_mp_table(rows))
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps({"seeds": args.seeds, "runs": sorted(runs), "fitted": sc,
                                                   "rows": rows}, indent=1) + "\n")
    return 0


def replay_run(offers: dict, plan) -> list:
    """Replay one recorded bench run against a plan function (book -> [(sell, buy, price)]): every trader quotes as
    it did on record, tick by tick, and leaves once matched. Valid only for a run where nothing was matched on record
    (b36: the guard dropped every pair), so every path is whole. Returns [(tick, sell, buy, price)]."""
    ticks = sorted({t for r in offers.values() for t, _ in r["quotes"]})
    paths = {oid: dict(r["quotes"]) for oid, r in offers.items()}
    gone, out = set(), []
    for t in ticks:
        bench = []
        for oid, path in paths.items():
            if t in path and oid not in gone:
                tr = {"side": offers[oid]["side"], "a": 0, "P": TICKS}
                bench.append(offer(tr, oid, path[t], {"makers": False, "expiry": "none"}))
        book = {"venue": "replay", "fee_bps": 0, "fee_per_card": 0, "offers": [], "bench_offers": bench}
        ok, _bad = brk.guard(plan(book), book)  # what the live guard lets through
        for sell, buy, price in ok:
            gone.update((sell, buy))
            out.append((t, sell, buy, price))
    return out


def proxy_limits(offers: dict, firm_shade: float = 0.0) -> dict:
    """Limits stand-ins for a recorded run: each trader's last (most relaxed) quote; with firm_shade, a quote that
    never moved toward its limit is shaded that much further (a firm trader's limit lies beyond its quote)."""
    lim = {}
    for oid, r in offers.items():
        q0, q = r["quotes"][0][1], r["quotes"][-1][1]
        sign = 1 if r["side"] == "buy" else -1
        if firm_shade and sign * (q - q0) <= 0:
            q = q * (1 + firm_shade) if sign > 0 else q / (1 + firm_shade)
        lim[oid] = q
    return lim


def cmd_replay(args) -> int:
    runs = read_runs(Path(args.log))
    if args.run not in runs:
        raise SystemExit(f"{args.run} not in {args.log} (there: {sorted(runs)})")
    offers = runs[args.run]
    censored = [oid for oid, r in offers.items() if r["how"] in ("ours", "engine")]
    if censored:
        raise SystemExit(f"{args.run}: {len(censored)} offers were matched on record, so their paths end early and a "
                         f"replay would be biased; only a run with no match on record can be replayed")
    plans = {"stall": lambda b: brk.stall_plan(b, fees=True), "maxpairs": maxpairs_plan}
    for name, plan in plans.items():
        pairs = replay_run(offers, plan)
        parts = []
        for label, shade in (("Q", 0.0), ("F15", 0.15)):
            lim = proxy_limits(offers, shade)
            v = sorted((lim[o] for o in lim if offers[o]["side"] == "buy"), reverse=True)
            c = sorted(lim[o] for o in lim if offers[o]["side"] == "sell")
            best = sum(max(0.0, b - s) for b, s in zip(v, c))
            gain = sum(lim[b] - lim[s] for _, s, b, _ in pairs)
            parts.append(f"{label} {gain / best:.3f} ({gain:.1f} of {best:.1f})" if best > 0 else f"{label} n/a")
        print(f"{name:<9} {len(pairs)} matches; efficiency {'; '.join(parts)}")
        for t, sell, buy, price in pairs:
            print(f"  tick {t}: {sell} x {buy} at {price}")
    return 0


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
    f = sub.add_parser("refit", help="fit the scenario knobs to a recorded session (logs/broker/<date>.jsonl)")
    f.add_argument("--log", required=True)
    f.add_argument("--seeds", type=int, default=0, help="also run stall vs ours on the fitted scenario")
    f.add_argument("--runs", default=None, help="fit only these bench runs, e.g. b53 or b53,b70 (default: all)")
    f.add_argument("--json", default=None, help="also write the fit and the row here")
    c = sub.add_parser("candidate", help="one candidate policy minus the stall, paired, on fresh seeds")
    c.add_argument("--policy", choices=sorted(CANDIDATES), default="maxweight")
    c.add_argument("--seeds", type=int, default=1000)
    c.add_argument("--prefix", default="unseen", help="seed prefix; '' reuses the table's seeds")
    c.add_argument("--scenarios", default="hard,standard")
    c.add_argument("--log", default="logs/broker/2026-10-03.jsonl")
    c.add_argument("--refit-runs", default="", help="also scenarios fitted to recorded runs: all,b36,b53+b70,...")
    rp = sub.add_parser("replay", help="replay a recorded run that nothing matched: stall vs maxpairs on its paths")
    rp.add_argument("--log", required=True)
    rp.add_argument("--run", required=True, help="a bench run with no match on record, e.g. b36")
    s = sub.add_parser("show", help="one session, tick by tick")
    s.add_argument("--scenario", default="standard")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--books", action="store_true")
    args = ap.parse_args(argv)
    if args.mode == "list":
        for nm, d in SCENARIOS.items():
            print(f"{nm:<20} {d or '(the base mix)'}")
        return 0
    return {"table": cmd_table, "show": cmd_show, "refit": cmd_refit, "replay": cmd_replay,
            "candidate": cmd_candidate}[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
