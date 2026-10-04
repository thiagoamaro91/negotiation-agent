"""Duels III overnight search: worlds, a self-play rival and paired evaluation on top of tools/duel_arena.py.

Read-only and offline (no network, no key). Every candidate is a `duel.py --params` dict; the arena drives
agent/duel.py's own decide / set_windows / allocate with the cfg duel.py's make_cfg builds from it. agent/duel.py is
never edited: every lever goes through params or WP1's flags.

Worlds (all: two issues, the Duels II days world fitted from our 68 Duels II duels, paired limit never visible,
duel.py robust on days, as `duel.py run` starts on Sunday):
    main    Duels III (68 duels, 12 ticks, decay 0.10, 4 at once), the Duels II field refit plus SELF (a copy of
            duel.py with the incumbent params) at SELF_WEIGHT
    drift   the same, the mix shifted 20 % toward the deadline-concede and mute (silent, absent) types
    final   the Grand Final: one round, 34 duels, same 12 ticks and decay, main's mix
    d1      main with an accept sent at deadline-1 never settling (15 s ticks)
Seeds: train 0.., select 500000.., test 900000.. (the arena convention).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
import duel_arena as arena  # noqa: E402
import duel  # noqa: E402

INCUMBENT_PATH = ROOT / "docs" / "duel-lab" / "duel-params-duels3.json"
INCUMBENT = json.loads(INCUMBENT_PATH.read_text())
SEEDS = {"train": 0, "select": 500000, "test": 900000}
SELF_WEIGHT = 8          # of 76: ~10.5 % of the main mix is a copy of ourselves (orchestrator, 02:25)
DRIFT_SHARE = 0.20
DRIFT_TO = {"deadline": 0.5, "silent": 0.25, "absent": 0.25}


# ---------------------------------------------------------------- self-play rival

_SELF_CFG = {}


def _self_cfg(T: int):
    if T not in _SELF_CFG:
        saved = arena.ARENA_DAYS
        arena.ARENA_DAYS = ""                       # robust, as `duel.py run` on Sunday
        try:
            _SELF_CFG[T] = arena.cfg_for(INCUMBENT, T)
        finally:
            arena.ARENA_DAYS = saved
    return _SELF_CFG[T]


class SelfRival(arena.Rival):
    """agent/duel.py with the incumbent params, playing the other side. It sees what a server would show it: its own
    limit and days weight, our messages one tick late, its own messages. One accept per duel (its team's slot
    allocation is not modelled), paired limit hidden, as ours."""
    kind = "self"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cfg = _self_cfg(self.T)
        self.msgs = []                 # server-shaped messages in its own frame (tick = elapsed)
        self.seen = 0
        self.st = None
        self.mine = None               # its standing offer (price, day)
        self.rid = 0
        self.d = None

    def _view(self):
        two = self.days is not None
        best, w = self.days if two else (None, None)
        d = {"duel": 1, "session": 3, "status": "live", "role": self.role, "item": "item-self",
             "issues": ["price", "days"] if two else ["price"],
             "your_days_weight": (-w if best != (0 if self.role == "buyer" else 10) else w) if two else None,
             "days_meaning": (arena.WORDING_EARN if best == 10 else arena.WORDING_PAY) if two else None,
             "your_limit": self.L, "limit_meaning": "", "rival": "Rival X", "deadline_tick": self.T,
             "decay_per_round": 0.10, "rounds": 0, "your_offer": None, "rival_offer": None, "messages": [],
             "result": None, "price": None, "days": None}
        return d

    def act(self, e, view):
        if self.d is None:
            self.d = self._view()
            self.st = duel.DuelState(self.d, e, self.T)
        d = self.d
        ours = view["our_msgs"]
        while self.seen < len(ours):                      # our messages land in its frame one tick late
            _, p, day = ours[self.seen]
            self.seen += 1
            self.rid += 1
            d["messages"].append({"tick": e - 1, "from": "Rival X", "text": "", "price": p, "days": day})
            d["rival_offer"] = {"id": self.rid, "price": p, "tick": e - 1, "days": day if day is not None else 0}
        duel.sync_state(self.st, d)
        duel.set_windows([(d, self.st)], self.cfg)
        dec = duel.decide(d, self.st, e, self.cfg)
        if dec["action"] == "accept" and view["our_offer"] is not None:
            self.st.accepted_at = e
            return {"accept": True}
        if dec["action"] == "say":
            duel.record_say(self.st, dec, d, e)
            d["messages"].append({"tick": e, "from": "you", "text": "", "price": dec["price"], "days": dec["days"]})
            d["your_offer"] = {"price": dec["price"], "days": dec["days"] if dec["days"] is not None else 0}
            return {"say": (dec["price"], dec["days"])}
        return {}


arena.KINDS["self"] = SelfRival


# ---------------------------------------------------------------- worlds

def _norm(w: dict) -> dict:
    t = sum(w.values())
    return {k: v / t for k, v in w.items() if v > 0}


MAIN_W = {**{k: v for k, v in arena.DUELS2_WEIGHTS.items() if v > 0}, "self": SELF_WEIGHT}
_m = _norm(MAIN_W)
DRIFT_W = {k: round(100 * ((1 - DRIFT_SHARE) * _m.get(k, 0) + DRIFT_SHARE * DRIFT_TO.get(k, 0)), 4)
           for k in set(_m) | set(DRIFT_TO)}
DAYS_MODS = {k: v for k, v in arena.DUELS2_MODS.items()}           # empirical weights, rivals' day, pair hidden

WORLDS = {
    "main": {"session": 3, "weights": MAIN_W, "d1": True},
    "drift": {"session": 3, "weights": DRIFT_W, "d1": True},
    "final": {"session": 4, "weights": MAIN_W, "d1": True},
    "d1": {"session": 3, "weights": MAIN_W, "d1": False},
}


def run_world(params: dict, world: str, seeds) -> list:
    """Every duel result of these params in one world over these seeds."""
    w = WORLDS[world]
    g = vars(arena)
    saved = {k: g[k] for k in set(DAYS_MODS) | {"ARENA_DAYS"}}
    g.update(DAYS_MODS)
    arena.ARENA_DAYS = ""
    try:
        kinds = [k for k in arena.KINDS if w["weights"].get(k, 0) > 0]
        return arena.evaluate(params, seeds, w["session"], kinds=kinds, weights=w["weights"], d1_settles=w["d1"])
    finally:
        g.update(saved)


def job(args: tuple) -> tuple:
    """Pool worker: (key, params, world, seed0, n) -> (key, world, seed0, {seed: [sum, n]}, {kind: {seed: [s, n]}})."""
    key, params, world, seed0, n = args
    try:
        res = run_world(params, world, range(seed0, seed0 + n))
    except SystemExit as e:                          # duel.py rejected the params
        return key, world, seed0, None, str(e)
    per_seed, per_kind = {}, {}
    for r in res:
        a = per_seed.setdefault(r["seed"], [0.0, 0])
        a[0] += r["score"]
        a[1] += 1
        b = per_kind.setdefault(r["kind"], {}).setdefault(r["seed"], [0.0, 0])
        b[0] += r["score"]
        b[1] += 1
    return key, world, seed0, per_seed, per_kind


# ---------------------------------------------------------------- statistics

def paired(cand: dict, base: dict) -> tuple:
    """(mean diff, SE) of per-seed mean scores over the seeds both have."""
    seeds = [s for s in cand if s in base]
    diffs = [cand[s][0] / cand[s][1] - base[s][0] / base[s][1] for s in seeds]
    n = len(diffs)
    if n == 0:
        return 0.0, 0.0
    m = sum(diffs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in diffs) / max(1, n - 1))
    return m, sd / math.sqrt(n)


def kind_paired(cand: dict, base: dict) -> dict:
    """{kind: (diff in mean score per duel of that kind, SE)}: per-seed diffs of the kind's sum, scaled per duel."""
    out = {}
    for k in cand:
        if k not in base:
            continue
        seeds = [s for s in cand[k] if s in base[k]]
        if not seeds:
            continue
        n_duels = sum(cand[k][s][1] for s in seeds)
        diffs = [cand[k][s][0] - base[k][s][0] for s in seeds]
        m = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((x - m) ** 2 for x in diffs) / max(1, len(diffs) - 1))
        per = len(seeds) / n_duels                       # duels of this kind per seed, inverted
        out[k] = (m * per, sd / math.sqrt(len(diffs)) * per)
    return out


def mean_of(per_seed: dict) -> float:
    return sum(v[0] for v in per_seed.values()) / max(1, sum(v[1] for v in per_seed.values()))


def check(params: dict) -> str | None:
    """None if duel.py accepts these params, else its error."""
    try:
        arena.cfg_for(params, 12)
    except SystemExit as e:
        return str(e)
    return None


def diff(params: dict, base: dict = None) -> dict:
    """What a candidate changes against the incumbent."""
    base = INCUMBENT if base is None else base
    keys = list(dict.fromkeys(list(base) + list(params)))
    return {k: params.get(k) for k in keys if params.get(k) != base.get(k)}


def fmt_diff(params: dict) -> str:
    d = diff(params)
    if not d:
        return "(incumbent)"
    parts = []
    for k, v in d.items():
        if isinstance(v, list):
            v = "[" + ", ".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v) + "]"
        elif isinstance(v, float):
            v = f"{v:g}"
        parts.append(f"{k}={v}")
    return ", ".join(parts)
