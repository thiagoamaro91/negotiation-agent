"""Candidate bench policies for the overnight search (WP11). Each is blind: it sees only what a bench book shows on
Saturday (ids, sides, quotes; no per-offer expiry), keeps quote paths across ticks, and plans per bench run.

Families (search order):
  blind_est  agent/broker.py BenchPolicy with BLIND = "policy" (priorities from estimated limits and a patience prior),
             every prior overridden through its params; slope="hazard" swaps the quote-path slope rule for one that
             ignores the slope-patience link (leave chance from the age alone, limit extrapolated over the expected
             remaining life).
  timing     the stall's plan, changed by quote-path rules: "second" swaps a patient-looking member of a stall pair
             for an unmatched impatient-looking trader that also crosses the partner ("match the second-best pair
             first"); "hold" keeps a stall pair back while its counterpart is still relaxing and the other side has
             >= N patient-looking traders.
  hybrid     the stall's plan, changed only when a classifier of "leaving after this tick" (leave_model.py, fitted on
             the five recorded sessions, or on simulator paths for the "sim" variant) says an unmatched trader is
             about to leave: the same swap as timing/second, urgency = the classifier's probability.
  hybrid_est the same classifier inside BenchPolicy's priorities (its leave chance replaces the patience prior's);
             added after the first smoke run showed the swap losing even with perfect leave flags (oracle_swap)
             while BenchPolicy with perfect leave flags (oracle_est) wins.
References (not candidates; they read the simulator's truth): oracle_swap (the swap with perfect leave flags) and
oracle_est (BenchPolicy whose leave estimate is the truth), to show how much the mechanisms could earn at best.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for p in (ROOT / "kit", ROOT / "agent", ROOT / "tools", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import bench_sim as bs  # noqa: E402
import broker as brk  # noqa: E402
import leave_model as lm  # noqa: E402

TICKS = bs.TICKS
LOG = ROOT / "logs" / "broker" / "2026-10-03.jsonl"


# ---------------------------------------------------------------- quote-path reading (pure)

def path_stats(tr: dict, tick: int, run_start: int, window: int = 1) -> dict:
    """What a quote path says at `tick`: n (ticks on the book), move (relaxed share of the first quote), rho (relaxed
    share per tick), recent (relaxed toward the limit within the last `window` ticks), st (session clock)."""
    quotes = tr["quotes"]
    t0, q0 = quotes[0]
    q = quotes[-1][1]
    sign = 1 if tr["side"] == "buy" else -1
    n = tick - t0 + 1
    age = tick - t0
    move = sign * (q - q0) / q0 if q0 else 0.0
    rho = move / age if age > 0 else 0.0
    recent = any(sign * (b[1] - a[1]) > 0 for a, b in zip(quotes, quotes[1:]) if b[0] > tick - window)
    return {"n": n, "move": move, "rho": rho, "recent": recent, "st": tick - run_start, "first": len(quotes) < 2}


def heuristic_urgency(ps: dict, cfg: dict) -> float:
    """Leave-soon score in [0, 1] from a quote path: the session's last ticks are 1; first sight u_first; never
    relaxed u_firm; relaxing at least rho_fast per tick 1, at most rho_slow 0, in between 0.5."""
    if ps["st"] >= TICKS - 1 - cfg["end_margin"]:
        return 1.0
    if ps["first"]:
        return cfg["u_first"]
    if ps["move"] <= 0:
        return cfg["u_firm"]
    if ps["rho"] >= cfg["rho_fast"]:
        return 1.0
    if ps["rho"] <= cfg["rho_slow"]:
        return 0.0
    return 0.5


def _crosses(book: dict, ask, bid) -> bool:
    return bid >= ask and brk.price_for(book, ask, bid) is not None


def swap_run(asks: list, bids: list, book: dict, urg: dict, cfg: dict) -> list:
    """The stall's plan for one run, then up to max_swaps swaps: an unmatched trader x with urgency >= hi replaces the
    same-side member y of a stall pair when y's urgency <= lo, x crosses y's partner, and x's quote is at most `delta`
    (share of y's quote) worse than y's. Best swap first (largest urgency gap, then smallest quote loss). refill: the
    stall's rule again over the offers left (so a freed y still trades now if it crosses someone free). Every pair
    respects the quotes; each offer once."""
    q = {oid: v for v, oid in asks + bids}
    pairs = [[s, b] for s, b, _ in brk.stall_run(asks, bids, book)]
    taken = {x for p in pairs for x in p}
    free = {"buy": [oid for _, oid in bids if oid not in taken], "sell": [oid for _, oid in asks if oid not in taken]}
    sides = ("buy", "sell") if cfg["sides"] == "both" else (cfg["sides"],)
    for _ in range(cfg["max_swaps"]):
        best = None
        for side in sides:
            for x in free[side]:
                if urg.get(x, 0.0) < cfg["hi"]:
                    continue
                for idx, (s, b) in enumerate(pairs):
                    y, partner = (b, s) if side == "buy" else (s, b)
                    if urg.get(y, 0.0) > cfg["lo"]:
                        continue
                    ask, bid = (q[partner], q[x]) if side == "buy" else (q[x], q[partner])
                    if not _crosses(book, ask, bid):
                        continue
                    loss = abs(q[y] - q[x]) / max(1.0, q[y])
                    if loss > cfg["delta"]:
                        continue
                    key = (urg.get(x, 0.0) - urg.get(y, 0.0), -loss)
                    if best is None or key > best[0]:
                        best = (key, side, x, idx)
        if best is None:
            break
        _, side, x, idx = best
        s, b = pairs[idx]
        if side == "buy":
            free["buy"].remove(x)
            free["buy"].append(b)
            pairs[idx] = [s, x]
        else:
            free["sell"].remove(x)
            free["sell"].append(s)
            pairs[idx] = [x, b]
    plan = [(s, b, brk.price_for(book, q[s], q[b])) for s, b in pairs]
    if cfg.get("refill"):
        used = {x for p in pairs for x in p}
        plan += brk.stall_run([a for a in asks if a[1] not in used], [b for b in bids if b[1] not in used], book)
    return plan


def hold_run(asks: list, bids: list, book: dict, urg: dict, recent: dict, st: int, cfg: dict) -> list:
    """The stall's plan for one run minus the pairs held back: a pair (s, b) waits when, for an allowed orientation
    (X, C) of it, C's quote relaxed within the window (recent[C]), C's side has at least N other patient-looking
    traders (urgency <= lo), and X looks patient too; never in the last ticks (st >= t_max)."""
    if st >= cfg["t_max"]:
        return brk.stall_run(asks, bids, book)
    patient = {"buy": sum(urg.get(o, 0.0) <= cfg["lo"] for _, o in bids),
               "sell": sum(urg.get(o, 0.0) <= cfg["lo"] for _, o in asks)}
    plan = []
    for s, b, price in brk.stall_run(asks, bids, book):
        hold = False
        for x, c, cside in ((s, b, "buy"), (b, s, "sell")):
            if cfg["persp"] != "either" and cfg["persp"] != ("sell" if x == s else "buy"):
                continue
            others = patient[cside] - (urg.get(c, 0.0) <= cfg["lo"])
            if recent.get(c) and others >= cfg["N"] and urg.get(x, 0.0) <= cfg["lo"]:
                hold = True
        if not hold:
            plan.append((s, b, price))
    return plan


# ---------------------------------------------------------------- policy objects

class PathPolicy:
    """Base for the timing and hybrid families: a Tracker of quote paths, a run's start, and a fallback to the
    stall's rule for a run on any exception (as BenchPolicy does)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tracker = brk.Tracker()
        self.starts: dict = {}
        self.fallbacks = 0

    def sent(self, sell, buy, tick):  # the simulator settles at once; nothing to remember
        pass

    def urgency(self, oid: str, tick: int) -> float:
        raise NotImplementedError

    def plan_run(self, book, asks, bids, tick) -> list:
        raise NotImplementedError

    def plan(self, book: dict, tick: int) -> list:
        self.tracker.observe(book, tick)
        out = []
        for run, (asks, bids) in brk.bench_quotes(book).items():
            self.starts.setdefault(run, tick)
            if not asks or not bids:
                continue
            try:
                out += self.plan_run(book, asks, bids, tick)
            except Exception:
                self.fallbacks += 1
                out += brk.stall_run(asks, bids, book)
        return out

    def stats(self, oid, tick, window=1):
        tr = self.tracker.traders[oid]
        return path_stats(tr, tick, self.starts[brk.run_of(oid)], window)


class Timing(PathPolicy):
    def plan_run(self, book, asks, bids, tick):
        c = self.cfg
        ids = [o for _, o in asks + bids]
        ps = {o: self.stats(o, tick, c.get("W", 1)) for o in ids}
        urg = {o: heuristic_urgency(ps[o], c) for o in ids}
        if c["mech"] == "second":
            return swap_run(asks, bids, book, urg, c)
        st = tick - self.starts[brk.run_of(ids[0])]
        return hold_run(asks, bids, book, urg, {o: ps[o]["recent"] for o in ids}, st, c)


_MODELS: dict = {}


def leave_weights(kind: str) -> list:
    """The classifier's weights, fitted once per process: "real" on the recorded sessions (bench_sim.read_runs),
    "sim" on 600 unmatched simulator sessions of the standard mix (seed prefix "train", never used for scoring)."""
    if kind not in _MODELS:
        if kind == "real":
            X, y = lm.samples_from_runs(bs.read_runs(LOG))
        else:
            name = {"sim": "standard", "sim_hard": "hard"}[kind]
            sc = bs.scenario(name)
            rng = random.Random(f"train:{name}")
            X, y = lm.samples_from_traders([(bs.make_session(rng, sc), sc) for _ in range(600)], bs.quote, TICKS)
        _MODELS[kind] = lm.fit(X, y)
    return _MODELS[kind]


class Hybrid(PathPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.w = leave_weights(cfg["model"])

    def plan_run(self, book, asks, bids, tick):
        urg = {}
        for _, o in asks + bids:
            tr = self.tracker.traders[o]
            urg[o] = lm.predict(self.w, lm.features(tr["side"], tr["quotes"], tick, self.starts[brk.run_of(o)]))
        return swap_run(asks, bids, book, urg, self.cfg)


class HybridEstimate(brk.BenchPolicy):
    """Family 3b: BenchPolicy (blind = "policy") whose leave chance is the classifier's probability (times
    leave_scale, capped at 1) instead of the patience prior's; limits estimated from quotes as broker.py does."""

    def __init__(self, params: dict):
        p = dict(params)
        self.w = leave_weights(p.pop("model"))
        self.scale = p.pop("leave_scale", 1.0)
        super().__init__({**p, "blind": "policy"})
        self.starts: dict = {}

    def plan(self, book, tick):
        for run in brk.bench_quotes(book):
            self.starts.setdefault(run, tick)
        return super().plan(book, tick)

    def estimate(self, tr, tick, known=False):
        e = super().estimate(tr, tick, known)
        x = lm.features(tr["side"], tr["quotes"], tick, self.starts.get(tr["run"], tr["first"]))
        e["leave"] = min(1.0, self.scale * lm.predict(self.w, x))
        return e


class OracleSwap(PathPolicy):
    """Reference only: the swap with the simulator's truth (1 = leaves after this tick, else 0)."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.last: dict = {}

    def start_session(self, traders, t0):
        self.last.update({tr["id"]: t0 + min(tr["a"] + tr["P"] - 1, TICKS - 1) for tr in traders})

    def plan_run(self, book, asks, bids, tick):
        urg = {o: 1.0 if self.last.get(o) == tick else 0.0 for _, o in asks + bids}
        return swap_run(asks, bids, book, urg, self.cfg)


class BlindEstimate(brk.BenchPolicy):
    """Family 1: BenchPolicy, blind = "policy", priors from params; slope "prior" (broker.py's rule) or "hazard"."""

    def __init__(self, params: dict):
        p = dict(params)
        self.slope = p.pop("slope", "prior")
        super().__init__({**p, "blind": "policy"})

    def estimate(self, tr, tick, known=False):
        if self.slope == "prior":
            return super().estimate(tr, tick, known)
        p = self.p
        quotes = tr["quotes"]
        t0, q0 = quotes[0]
        q = quotes[-1][1]
        sign = 1 if tr["side"] == "buy" else -1
        n = tick - t0 + 1
        tail = [(k, w) for k, w in enumerate(self.prior) if k >= n and w > 0]
        mass = sum(w for _, w in tail)
        remaining = sum((k - n) * w for k, w in tail) / mass if mass > 0 else 0.0
        leave = brk.hazard(self.prior, n)
        if len(quotes) < 2:
            return {"limit": q * (1 + sign * p["first_shade"]), "leave": leave, "kind": "first"}
        move = sign * (q - q0)
        if move <= 0:
            return {"limit": q * (1 + sign * p["firm_shade"]), "leave": leave, "kind": "firm"}
        slope = move / (tick - t0)
        return {"limit": q + sign * slope * remaining, "leave": leave, "kind": "relaxing"}


class OracleEstimate(brk.BenchPolicy):
    """Reference only: BenchPolicy whose leave estimate is the truth and FUTURE = 1 (what it does with known
    departures), limits still estimated from quotes."""

    def __init__(self, params: dict | None = None):
        p = dict(params or {})
        self.noise = p.pop("noise", 0.0)  # chance each leave flag is flipped (deterministic per offer and tick)
        super().__init__({**p, "blind": "policy", "future": 1.0})
        self.last: dict = {}

    def start_session(self, traders, t0):
        self.last.update({tr["id"]: t0 + min(tr["a"] + tr["P"] - 1, TICKS - 1) for tr in traders})

    def estimate(self, tr, tick, known=False):
        e = super().estimate(tr, tick, known)
        leave = self.last.get(tr["id"]) == tick
        if self.noise and random.Random(f"noise:{tr['id']}:{tick}").random() < self.noise:
            leave = not leave
        e["leave"] = 1.0 if leave else 0.0
        return e


class Stateless:
    """A plan function of the book alone (bench_sim's maxpairs / maxweight), as a policy object."""

    def __init__(self, fn):
        self.fn = fn

    def plan(self, book, tick):
        return self.fn(book)


def build(spec: dict):
    """A fresh policy object for one simulated day. spec: {"family": ..., "params": {...}}."""
    fam, p = spec["family"], spec.get("params", {})
    if fam == "blind_est":
        return BlindEstimate(p)
    if fam == "timing":
        return Timing(p)
    if fam == "hybrid":
        return Hybrid(p)
    if fam == "hybrid_est":
        return HybridEstimate(p)
    if fam == "oracle_swap":
        return OracleSwap(p)
    if fam == "oracle_est":
        return OracleEstimate(p)
    if fam == "maxpairs":
        return Stateless(bs.maxpairs_plan)
    if fam == "maxweight":
        return Stateless(bs.maxweight_plan)
    if fam == "stall":
        return Stateless(lambda b: brk.stall_plan(b, fees=True))
    raise ValueError(f"unknown family {fam}")


# ---------------------------------------------------------------- search spaces

def sample(family: str, rng: random.Random) -> dict:
    """One random member of a family's parameter space."""
    if family == "blind_est":
        lo = rng.choice((1, 2))
        plo = rng.randint(4, 9)
        return {"smax": round(rng.uniform(0.1, 0.5), 3), "firm_shade": round(rng.uniform(0.0, 0.3), 3),
                "first_shade": round(rng.uniform(0.0, 0.25), 3), "imp_share": round(rng.uniform(0.0, 1.0), 3),
                "imp": [lo, rng.randint(lo + 1, 6)], "pat": [plo, rng.randint(max(plo + 2, 10), 16)],
                "future": round(rng.uniform(0.0, 1.2), 3), "min_edge": rng.choice((0.0, 0.5, 1.0, 2.0, 4.0)),
                "expiry_margin": rng.choice((0, 1, 2, 3)), "slope": rng.choice(("prior", "hazard"))}
    if family == "timing":
        fast = round(rng.uniform(0.02, 0.2), 3)
        c = {"mech": rng.choice(("second", "hold")), "u_first": rng.choice((0.0, 0.5, 1.0)),
             "u_firm": rng.choice((0.0, 0.5, 1.0)), "rho_fast": fast, "rho_slow": round(rng.uniform(0.0, fast), 3),
             "end_margin": rng.choice((0, 1, 2)), "lo": rng.choice((0.0, 0.5))}
        if c["mech"] == "second":
            c.update({"hi": rng.choice((0.5, 1.0)), "delta": round(rng.uniform(0.0, 0.6), 3),
                      "max_swaps": rng.choice((1, 2, 3)), "refill": rng.random() < 0.5,
                      "sides": rng.choice(("buy", "sell", "both"))})
        else:
            c.update({"W": rng.choice((1, 2, 3)), "N": rng.choice((1, 2, 3, 4)),
                      "persp": rng.choice(("sell", "buy", "either")), "t_max": rng.randint(3, 14)})
        return c
    if family == "hybrid":
        hi = round(rng.uniform(0.25, 0.95), 3)
        return {"model": rng.choice(("real", "real", "sim", "sim_hard")), "hi": hi, "lo": round(rng.uniform(0.02, hi), 3),
                "delta": round(rng.uniform(0.0, 0.6), 3), "max_swaps": rng.choice((1, 2, 3)),
                "refill": rng.random() < 0.5, "sides": rng.choice(("buy", "sell", "both"))}
    if family == "hybrid_est":
        return {"model": rng.choice(("real", "real", "sim", "sim_hard")),
                "leave_scale": round(rng.uniform(0.5, 2.5), 3), "future": round(rng.uniform(0.2, 1.2), 3),
                "smax": round(rng.uniform(0.1, 0.5), 3), "firm_shade": round(rng.uniform(0.0, 0.3), 3),
                "first_shade": round(rng.uniform(0.0, 0.25), 3), "min_edge": rng.choice((0.0, 0.5, 1.0, 2.0, 4.0))}
    raise ValueError(family)
