"""Duel arena: simulated Duels sessions that drive agent/duel.py's decide() offline. No network, no key.

It drives agent/duel.py exactly as its `run` loop does each tick (sync_state, set_windows, decide, allocate,
record_say), with the cfg duel.py's own make_cfg builds from `--params FILE`, against a population of rival bots on
scenarios drawn like Friday's practice wave, and scores every duel the way the rules describe it. A params dict is
the content of such a file ({} = duel.py's defaults). tools/duel_tune.py uses the arena as the referee.

What it models (and the evidence behind each choice; see docs/analysis-friday/duels.md):
  - Scenarios come in pairs: duels N (odd) and N+1, same item, same rival team, roles swapped. One base cost C and
    value V per item (costs 65-134, values up to ~190, value/cost 1.06-2.3, and ~12% thin or empty pies). Each
    duel gets its own secret scale (+-4%) and shift (+-3 P) applied to both limits, so our limit in the paired
    duel is close to, but not equal to, the rival's limit (Friday: within 7% in 6/8).
  - Rounds (MEASURED rule, 18/18 Friday duels): a round needs both sides to have spoken. Default rule "exchange":
    rounds = ceil(speaker switches / 2), so our message right after a rival message costs a round at once (duel 37)
    and an opening to a silent rival costs nothing until it answers. Alternative "min": min(our msgs, theirs).
  - Timing: each tick both sides see the other's messages from earlier ticks (we poll at the tick start); our
    message is listed before the rival's within a tick. --late-look N lets us also see the rival's same-tick message
    in the last N ticks (a second poll late in the tick), to price that loop change.
  - Accepts: a side accepts the other's standing offer; it settles at the next tick. An accept at deadline-1
    counts (11 field deals were recorded on the deadline tick); d1_settles=False is the stress case where it does
    not. One accept per team per tick across all live duels (duel.allocate decides which), and --slot-busy P
    takes the slot away for a whole tick with probability P (another agent on our key accepting).
    Duels of one wave start together or one or two ticks apart (offsets 0, 0, 0, 1, 2), as in duel.py's selftest.
  - Score per duel: our share of the pie times (1 - decay)^rounds. Share = our surplus / pie, pie = buyer value -
    seller cost. With two issues, surplus is price surplus minus the days cost (weight x days away from the best
    day) and the pie is the best joint pie over days 0-10, so trading days well raises the share. A deal outside
    our limit scores the (negative) share without decay, floored at -1; no deal scores 0.
  - Rivals never parse text either: they see our structured offers only. Archetypes fitted to Friday's paths:
    steady (9/10, 93/94), fast (99/100), cycler (37/38), oneshot (29/30), llm (103/104), absent (23/24, 91/92,
    139/140), plus classic styles: hardliner, linear, tft (tit-for-tat), deadline, and silent (never speaks, but
    accepts a good enough offer). Each rival team gets its own random parameters, shared by both duels of its pair.

Usage (from the repo root):
    python3 tools/duel_arena.py                                   # duel.py's defaults, Duels I
    python3 tools/duel_arena.py --params results/duel-params.json --sessions 300 --stress
    python3 tools/duel_arena.py --session 2 --params ~/lab/duel/best_params_duels2.json
    python3 tools/duel_arena.py --session 2 --pair-seen 0 --weights duels1 --params a.json --params b.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
import duel  # noqa: E402

SESSIONS = {
    1: {"name": "Duels I", "issues": ["price"], "ticks": 16, "decay": 0.06, "concurrent": 3, "duels": 34},
    2: {"name": "Duels II", "issues": ["price", "days"], "ticks": 16, "decay": 0.08, "concurrent": 6, "duels": 68},
    3: {"name": "Duels III", "issues": ["price", "days"], "ticks": 12, "decay": 0.10, "concurrent": 4, "duels": 68},
    4: {"name": "Final", "issues": ["price", "days"], "ticks": 12, "decay": 0.10, "concurrent": 4, "duels": 34},
}
SCALE, SHIFT = 0.04, 3.0        # the secret per-duel transform of both limits
THIN_PIES = 0.12                # share of items with a thin or empty pie
NEVER_TAKES = 0.5               # share of rivals that never accept our offer (Friday: 0 of 7 taken; field closed 47%)
FITTED = ["steady", "fast", "cycler", "oneshot", "llm", "absent"]
CLASSIC = ["hardliner", "linear", "tft", "deadline", "silent"]
# Friday's 9 pairs: steady 2, fast 1, cycler 1, oneshot 1, llm 1, absent 3. Classic styles weigh 1 each.
WEIGHTS = {"steady": 2, "fast": 1, "cycler": 1, "oneshot": 1, "llm": 1, "absent": 2,
           "hardliner": 1, "linear": 1, "tft": 1, "deadline": 1, "silent": 1}
# Duels I (Saturday, our 34 duels, logs/duels session 2), each rival path read by eye: 13 conceded every tick to the
# end (linear), 5 every 2-4 ticks (steady), 4 jumped then held (fast), 1 spoke once (oneshot), 2 froze on one number
# and took our last chance (tft-like), 2 never spoke but took our offer (silent), 7 never spoke nor took (absent).
DUELS1_WEIGHTS = {"linear": 13, "steady": 5, "fast": 4, "oneshot": 1, "tft": 2, "silent": 2, "absent": 7,
                  "cycler": 0, "llm": 0, "hardliner": 0, "deadline": 0}
# Share of duels whose paired limit duel.mirror_limit finds. Friday: the pair was (odd, odd + 1), same rival team.
# Duels I: 0 of 34 (pairs are (even, odd) with a different rival in each, and the limits are unrelated: 2360 / 2361).
PAIR_SEEN = 1.0
# Two issues. The server's days_meaning wording is unknown, so the arena's names no direction (duel.py then uses its
# role default and the weight's sign, not its own keyword list). DAYS_FLIP: every side's best day is the opposite of
# the role default (buyer late, seller early) and the weight shown to us is negative, as a server that signs it would.
DAYS_WORDING = "primas per day away from your preferred delivery day"
DAYS_FLIP = False

OFFSETS = (0, 0, 0, 1, 2)        # start offsets of the duels in one wave (ticks)
# duel.py --late-poll (a second read of the duels late in the tick): the share of the rival's same-tick messages that
# land after that read anyway (slow bots), and the share of late reads that never happen (network, tick over first)
LATE_MISS = 0.15
LATE_FAIL = 0.03


def cfg_for(params: dict, ticks: int):
    """duel.py's cfg for these params, built exactly as `duel.py run --params FILE` builds it (make_cfg)."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "params.json"
        f.write_text(json.dumps({**params, "duel_ticks": ticks}))
        return duel.make_cfg(["watch", "--params", str(f)])


def load_policy(path) -> dict:
    """A --params file as a dict, checked by duel.py's own loader (unknown keys exit)."""
    params = json.loads(Path(path).expanduser().read_text())
    cfg_for(params, 16)
    return params


# ---------------------------------------------------------------- rivals (structure only, like us)

class Rival:
    """A rival bot for one duel. role is the RIVAL's role; limit is its own (cost or value)."""
    kind = "base"

    def __init__(self, role: str, limit: int, T: int, p: dict, days=None):
        self.role, self.L, self.T, self.p = role, limit, T, p
        self.days = days                  # (best_day, weight) in two-issue sessions, else None
        self.last = None                  # our last offer we have seen, (price, day)

    # money helpers ------------------------------------------------
    def price(self, m: float, day=None) -> int:
        """The price that leaves the rival a margin m of its limit (plus its days cost), never across its limit."""
        extra = self.day_cost(day)
        if self.role == "seller":
            return max(self.L, int(math.ceil(self.L * (1 + m) + extra)))
        return min(self.L, int(math.floor(self.L * (1 - m) - extra)))

    def day_cost(self, day) -> float:
        if self.days is None or day is None:
            return 0.0
        best, w = self.days
        return w * abs(day - best)

    def utility(self, price: int, day=None) -> float:
        s = (price - self.L) if self.role == "seller" else (self.L - price)
        return s - self.day_cost(day)

    def day_for(self, ours) -> int | None:
        """Day the rival names: its best, or ours if it is flexible and we named one."""
        if self.days is None:
            return None
        if self.p.get("flex") and ours is not None and ours[1] is not None:
            return ours[1]
        return self.days[0]

    # behaviour ----------------------------------------------------
    def margin(self, e: int, view: dict) -> float | None:
        """The margin the rival would ask at elapsed tick e (None: it says nothing)."""
        return None

    def speaks(self, e: int, view: dict) -> bool:
        return False

    def accepts(self, e: int, view: dict) -> bool:
        """AC-next: our standing offer is at least as good for it as its own current number; plus an end window."""
        ours = view["our_offer"]
        if ours is None or not self.p.get("takes", True):
            return False
        u = self.utility(*ours)
        if u < 0:
            return False
        m = self.margin(e, view)
        if m is not None and u >= m * self.L - 1e-9:
            return True
        end_m = self.p.get("end_margin")
        return end_m is not None and self.T - e <= self.p.get("end_ticks", 2) and u >= end_m * self.L

    def act(self, e: int, view: dict) -> dict:
        if self.accepts(e, view):
            return {"accept": True}
        if self.speaks(e, view):
            m = self.margin(e, view)
            if m is not None:
                day = self.day_for(view["our_offer"])
                return {"say": (self.price(m, day), day)}
        return {}


def _tau(e: int, e0: int, T: int) -> float:
    return max(0.0, min(1.0, (e - e0) / max(1, T - 1 - e0)))


class Steady(Rival):
    """Friday 9/10 and 93/94: monotone, every 1-3 ticks, ends at deadline-1 just inside its limit."""
    kind = "steady"

    def margin(self, e, view):
        p = self.p
        if e < p["e0"]:
            return None
        return p["m0"] - (p["m0"] - p["m_end"]) * _tau(e, p["e0"], self.T) ** p["beta"]

    def speaks(self, e, view):
        p = self.p
        return e >= p["e0"] and ((e - p["e0"]) % p["every"] == 0 or e == self.T - 1)


class Fast(Rival):
    """Friday 99/100: two big jumps in two ticks to about its limit, then holds."""
    kind = "fast"

    def margin(self, e, view):
        p = self.p
        if e < p["e0"]:
            return None
        k = min(e - p["e0"], p["jumps"])
        return p["m0"] - (p["m0"] - p["m_end"]) * (1 - 0.5 ** k) / (1 - 0.5 ** p["jumps"])

    def speaks(self, e, view):
        return self.p["e0"] <= e <= self.p["e0"] + self.p["jumps"]


class Cycler(Rival):
    """Friday 37/38: repeats its opening, then a 3-step cycle that resets; best number at deadline-1."""
    kind = "cycler"

    def margin(self, e, view):
        p = self.p
        if e < p["hold"]:
            return p["m0"]
        left = self.T - e
        if left <= 3:
            return max(p["m_min"], p["m0"] - (4 - left) * p["step"])
        phase = (e - p["hold"]) % 3
        return p["m0"] if phase == 2 else max(p["m_min"], p["m0"] - (phase + 1) * p["step"])

    def speaks(self, e, view):
        return True

    def accepts(self, e, view):
        ours = view["our_offer"]
        return (ours is not None and self.p.get("takes", True)
                and self.utility(*ours) >= self.margin(e, view) * self.L)


class OneShot(Rival):
    """Friday 29/30: one opening around deadline-8, then silence; takes a good enough offer."""
    kind = "oneshot"

    def margin(self, e, view):
        return self.p["m0"] if e >= self.p["e0"] else None

    def speaks(self, e, view):
        return e == self.p["e0"]

    def accepts(self, e, view):
        ours = view["our_offer"]
        return ours is not None and self.p.get("takes", True) and self.utility(*ours) >= self.p["m_acc"] * self.L


class LLM(Rival):
    """Friday 103/104: opens near its limit, then moves only after we move, a few primas at a time."""
    kind = "llm"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.m = self.p["m0"]
        self.answered = 0                 # how many of our messages it has answered

    def margin(self, e, view):
        return self.m if e >= self.p["e0"] else None

    def speaks(self, e, view):
        p = self.p
        if e == p["e0"]:
            return True
        if len(view["our_msgs"]) > self.answered:
            self.answered = len(view["our_msgs"])
            self.m = max(p["m_floor"], self.m - p["step"] / self.L)
            return True
        if p["final"] and e == self.T - 2 and self.m > p["m_floor"]:
            self.m = p["m_floor"] + (self.m - p["m_floor"]) * 0.4
            return True
        return False


class Absent(Rival):
    kind = "absent"

    def accepts(self, e, view):
        return False


class Silent(Rival):
    """Never speaks; accepts our standing offer once it leaves it a big enough margin."""
    kind = "silent"

    def accepts(self, e, view):
        ours = view["our_offer"]
        return ours is not None and e >= self.p["e0"] and self.utility(*ours) >= self.p["m_acc"] * self.L


class Hardliner(Steady):
    kind = "hardliner"


class Linear(Steady):
    kind = "linear"


class TitForTat(Rival):
    """Opens high and mirrors our concessions primas for primas; holds while we are silent; maybe splits at the end."""
    kind = "tft"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.m = self.p["m0"]
        self.seen = 0

    def margin(self, e, view):
        return self.m if e >= self.p["e0"] else None

    def speaks(self, e, view):
        p = self.p
        if e < p["e0"]:
            return False
        msgs = view["our_msgs"]
        if len(msgs) > self.seen:
            if self.seen >= 1:
                step = abs(msgs[-1][1] - msgs[self.seen - 1][1])
                self.m = max(p["m_floor"], self.m - step / self.L)
            self.seen = len(msgs)
            return True
        if p["split"] and e == self.T - 2 and view["our_offer"] is not None:
            u_ours = self.utility(*view["our_offer"]) / self.L
            self.m = max(p["m_floor"], (self.m + max(u_ours, p["m_floor"])) / 2)
            return True
        return e == p["e0"] or (e - p["e0"]) % 3 == 0


class Deadline(Rival):
    """Silent until the end, then one number close to its limit."""
    kind = "deadline"

    def margin(self, e, view):
        return self.p["m"] if e >= self.T - self.p["at"] else None

    def speaks(self, e, view):
        return e == self.T - self.p["at"]


KINDS = {"steady": Steady, "fast": Fast, "cycler": Cycler, "oneshot": OneShot, "llm": LLM, "absent": Absent,
         "silent": Silent, "hardliner": Hardliner, "linear": Linear, "tft": TitForTat, "deadline": Deadline}


def rival_params(kind: str, rng: random.Random, T: int) -> dict:
    """One rival team's parameters (shared by both duels of its pair). Ranges fitted to Friday's paths."""
    u = rng.uniform
    end = {"end_margin": u(0.0, 0.05), "end_ticks": rng.choice([1, 2])} if rng.random() < 0.5 else {}
    flex = rng.random() < 0.5
    takes = rng.random() >= NEVER_TAKES   # some bots only ever post numbers and never accept ours
    return {"takes": takes, **_kind_params(kind, rng, T, u, end, flex)}   # silent overrides takes


def _kind_params(kind: str, rng: random.Random, T: int, u, end: dict, flex: bool) -> dict:
    if kind == "steady":
        return {"m0": u(0.2, 0.5), "m_end": u(0.0, 0.06), "beta": u(0.5, 2.5), "every": rng.choice([1, 1, 2, 3]),
                "e0": rng.randint(0, 2), "flex": flex, **end}
    if kind == "fast":
        return {"m0": u(0.25, 0.4), "m_end": u(0.0, 0.04), "jumps": rng.choice([2, 2, 3]), "e0": rng.randint(0, 2),
                "flex": flex, **end}
    if kind == "cycler":
        return {"m0": u(0.45, 0.75), "step": u(0.05, 0.07), "hold": rng.randint(4, 7), "m_min": u(0.25, 0.4),
                "flex": False}
    if kind == "oneshot":
        return {"m0": u(0.3, 0.7), "e0": rng.randint(2, max(2, T // 2)), "m_acc": u(0.05, 0.3), "flex": flex}
    if kind == "llm":
        return {"m0": u(0.05, 0.25), "m_floor": u(0.0, 0.05), "step": u(2, 4), "e0": rng.randint(0, 1),
                "final": rng.random() < 0.5, "flex": flex, "end_margin": u(0.0, 0.05), "end_ticks": 2}
    if kind == "silent":
        return {"m_acc": u(0.02, 0.25), "e0": rng.randint(0, T // 2), "takes": True}
    if kind == "hardliner":
        return {"m0": u(0.35, 0.6), "m_end": u(0.2, 0.35), "beta": 3.0, "every": 1, "e0": rng.randint(0, 2),
                "flex": False}
    if kind == "linear":
        return {"m0": u(0.2, 0.5), "m_end": u(0.0, 0.08), "beta": 1.0, "every": 1, "e0": rng.randint(0, 2),
                "flex": flex, **end}
    if kind == "tft":
        return {"m0": u(0.2, 0.45), "m_floor": u(0.0, 0.08), "e0": rng.randint(0, 2), "split": rng.random() < 0.5,
                "flex": flex}
    if kind == "deadline":
        return {"m": u(0.0, 0.12), "at": rng.choice([1, 2, 2, 3]), "flex": flex, "end_margin": u(0.0, 0.05),
                "end_ticks": 2}
    return {}


# ---------------------------------------------------------------- scenarios

class Duel:
    def __init__(self, did, pair, role, our_limit, rival_limit, kind, rp, T, decay, issues, days=None):
        self.id, self.pair, self.role, self.kind = did, pair, role, kind
        self.our_limit, self.rival_limit = our_limit, rival_limit
        self.T, self.decay, self.issues = T, decay, issues
        self.days = days                  # {"ours": (best, w), "rival": (best, w)} or None
        rrole = "buyer" if role == "seller" else "seller"
        self.rival = KINDS[kind](rrole, rival_limit, T, rp, days["rival"] if days else None)

    def pie(self) -> float:
        """Best joint surplus (two issues: over days 0-10)."""
        v, c = (self.rival_limit, self.our_limit) if self.role == "seller" else (self.our_limit, self.rival_limit)
        if not self.days:
            return float(v - c)
        return max(v - c - self.our_days_cost(x) - self.rival.day_cost(x) for x in range(11))

    def our_days_cost(self, day) -> float:
        if not self.days or day is None:
            return 0.0
        best, w = self.days["ours"]
        return w * abs(day - best)

    def our_surplus(self, price: int, day=None) -> float:
        s = (price - self.our_limit) if self.role == "seller" else (self.our_limit - price)
        return s - self.our_days_cost(day)


def make_session(seed: int, sess: dict, kinds: list, weights: dict = None) -> list:
    """All our duels of one session, as pairs (odd id, odd id + 1), one rival team per pair."""
    rng = random.Random(seed)
    weights = weights or WEIGHTS
    T, decay, issues = sess["ticks"], sess["decay"], sess["issues"]
    two = "days" in issues
    out = []
    for k in range(sess["duels"] // 2):
        kind = rng.choices(kinds, weights=[weights.get(x, 1) for x in kinds])[0]
        rp = rival_params(kind, rng, T)
        C = rng.uniform(65, 134)
        ratio = rng.uniform(0.92, 1.06) if rng.random() < THIN_PIES else rng.uniform(1.06, 2.3)
        V = min(C * ratio, 190.0)
        wts = {"buyer": rng.uniform(0, 4), "seller": rng.uniform(0, 4)} if two else None
        base = 2 * k + 1                                  # pairs are (odd, odd + 1), as on the server
        roles = ["seller", "buyer"] if rng.random() < 0.5 else ["buyer", "seller"]
        for j, role in enumerate(roles):
            s, h = rng.uniform(1 - SCALE, 1 + SCALE), rng.uniform(-SHIFT, SHIFT)
            cost, value = max(1, round(C * s + h)), max(2, round(V * s + h))
            ours, theirs = (cost, value) if role == "seller" else (value, cost)
            days = None
            if two:
                rrole = "buyer" if role == "seller" else "seller"
                fb, fs = (10, 0) if DAYS_FLIP else (0, 10)
                days = {"ours": (fb if role == "buyer" else fs, round(wts[role], 2)),
                        "rival": (fb if rrole == "buyer" else fs, round(wts[rrole], 2))}
            out.append(Duel(base + j, k, role, ours, theirs, kind, rp, T, decay, issues, days))
    rng.shuffle(out)
    # keep pairs mostly together: sort by pair with a little jitter so some partners land in the next wave
    out.sort(key=lambda x: x.pair + rng.uniform(0, 1.2))
    return out


# ---------------------------------------------------------------- one session

def rounds_of(msgs: list, rule: str) -> int:
    """msgs: [(tick, side), ...] in posting order, side "us" or "them"."""
    if rule == "min":
        n = sum(1 for _, s in msgs if s == "us")
        return min(n, len(msgs) - n)
    switches, prev = 0, None
    for _, s in msgs:
        if prev is not None and s != prev:
            switches += 1
        prev = s
    return (switches + 1) // 2


def score_deal(dl: Duel, price: int, day, rounds: int) -> tuple:
    """(share, score) of a deal for us, as the rules describe it."""
    pie = dl.pie()
    s = dl.our_surplus(price, day)
    if pie <= 0:
        return (0.0 if s >= 0 else -1.0), (0.0 if s >= 0 else -1.0)
    share = s / pie
    if s < 0:
        share = max(-1.0, share)
        return share, share
    return share, share * (1 - dl.decay) ** rounds


def server_view(dl: Duel, sess_no: int, deadline: int) -> dict:
    """The duel as GET /api/duels shows it to us."""
    two = bool(dl.days)
    d = {"duel": dl.id, "session": sess_no, "status": "live", "role": dl.role, "item": f"item-{dl.pair}",
         "issues": list(dl.issues),
         "your_days_weight": (-dl.days["ours"][1] if DAYS_FLIP else dl.days["ours"][1]) if two else None,
         "days_meaning": DAYS_WORDING if two else None,
         "your_limit": dl.our_limit, "limit_meaning": "", "rival": f"Rival {dl.pair}",
         "deadline_tick": deadline, "decay_per_round": dl.decay, "rounds": 0, "your_offer": None,
         "rival_offer": None, "messages": [], "result": None, "price": None, "days": None}
    return d


def play_session(duels: list, sess: dict, cfg, seed: int, rounds_rule: str = "exchange", late_look: int = 0,
                 slot_busy: float = 0.0, sess_no: int = 1, d1_settles: bool = True) -> list:
    """Plays every duel of a session in waves of sess["concurrent"]. Returns one result dict per duel.

    Each tick follows duel.py's run loop: for every live duel pair_l = mirror_limit, sync_state; then set_windows,
    decide, allocate (one accept per team per tick); then our accept or message (record_say)."""
    rng = random.Random(seed * 7919 + 1)
    lrng = random.Random(seed * 104729 + 5)       # late-read draws only, so flags off replay the same worlds
    prng = random.Random(seed * 31337 + 7)        # paired-limit visibility only (PAIR_SEEN)
    hidden = {dl.pair for dl in duels if PAIR_SEEN < 1 and prng.random() >= PAIR_SEEN}

    def pair_of(d, every):
        return None if int(d["item"].split("-")[1]) in hidden else duel.mirror_limit(d, every)
    late_fails = 0                                # late reads failed in a row (duel.LATE_MAX_FAILS: late read off)
    T = sess["ticks"]
    results, every = [], []
    waves = [duels[i:i + sess["concurrent"]] for i in range(0, len(duels), sess["concurrent"])]
    for w, wave in enumerate(waves):
        S = 1000 + w * (T + 4)
        xs = []
        for dl in wave:
            s0 = S + rng.choice(OFFSETS)
            xs.append({"dl": dl, "S": s0, "D": s0 + T, "d": server_view(dl, sess_no, s0 + T), "st": None,
                       "msgs": [], "ours": [], "theirs": [], "deal": None, "oid": 0})
        end = max(x["D"] for x in xs)
        busy = {t: rng.random() < slot_busy for t in range(S, end)}
        fallback = False                          # last tick's late read failed: accept in this tick's first read
        for tick in range(S, end):
            live = [x for x in xs if x["S"] <= tick < x["D"] and not x["deal"]]
            for x in live:
                if x["st"] is None:
                    every.append(x["d"])
                    x["st"] = duel.DuelState(x["d"], tick, cfg.duel_ticks)
            # 1. rivals decide on what they could see by the start of this tick
            rival_acts = {}
            for x in live:
                ours = x["ours"][-1][1:] if x["ours"] else None
                view = {"our_offer": ours, "our_msgs": list(x["ours"]),
                        "their_last": x["theirs"][-1] if x["theirs"] else None}
                rival_acts[x["dl"].id] = x["dl"].rival.act(tick - x["S"], view)
            # 2. we decide, as duel.py's loop does (optionally seeing the rival's same-tick message near the end)
            pairs = []
            for x in live:
                d, st = x["d"], x["st"]
                ra = rival_acts[x["dl"].id]
                if late_look and x["D"] - tick <= late_look and "say" in ra:
                    _post_rival(x, ra.pop("say"), tick)
                st.pair_l = pair_of(d, every)
                st.rival_limit = st.pair_l if cfg.mirror else None
                duel.sync_state(st, d)
                pairs.append((d, st))
            duel.set_windows(pairs, cfg)
            decisions = [(d, st, duel.decide(d, st, tick, cfg)) for d, st in pairs]
            if fallback or late_fails >= getattr(duel, "LATE_MAX_FAILS", 1 << 30):
                duel.allocate(decisions, cfg, late=True)
            else:
                duel.allocate(decisions, cfg)
            if busy[tick]:
                for dd in decisions:
                    if dd[2]["action"] == "accept":
                        dd[2]["action"], dd[2]["why"] = "hold", "slot taken by another agent"
            byid = {x["dl"].id: x for x in live}
            # 3. accepts settle (ours first: we act at the start of the tick)
            for d, st, dec in decisions:
                x = byid[d["duel"]]
                if dec["action"] == "accept" and d["rival_offer"] is not None:
                    st.accepted_at = tick
                    p, day = d["rival_offer"]["price"], d["rival_offer"].get("days")
                    x["deal"] = (p, day if x["dl"].days else None, tick, "us")
            for did, ra in rival_acts.items():
                x = byid[did]
                if not x["deal"] and ra.get("accept") and x["ours"]:
                    _, p, day = x["ours"][-1]
                    x["deal"] = (p, day, tick, "them")
            # 4. messages: ours, then the rival's
            for d, st, dec in decisions:
                x = byid[d["duel"]]
                if x["deal"] or dec["action"] != "say":
                    continue
                _post_ours(x, st, dec, d, tick)
            late = (not fallback and late_fails < getattr(duel, "LATE_MAX_FAILS", 1 << 30)
                    and getattr(duel, "late_due", None) and duel.late_due(decisions, cfg))
            fallback = bool(late) and lrng.random() < LATE_FAIL     # the late read will not happen this tick
            if late:
                late_fails = late_fails + 1 if fallback else 0
            held = []                                     # rival messages that land after our late read
            for did, ra in rival_acts.items():
                x = byid[did]
                if not x["deal"] and "say" in ra:
                    if late and lrng.random() < LATE_MISS:
                        held.append((x, ra["say"]))
                    else:
                        _post_rival(x, ra["say"], tick)
            if late and not fallback and not busy[tick]:
                # duel.py --late-poll: the second read of this tick, accepts only (run loop: duel.late_pass)
                again = []
                for x in live:
                    if x["deal"]:
                        continue
                    d, st = x["d"], x["st"]
                    st.pair_l = pair_of(d, every)
                    st.rival_limit = st.pair_l if cfg.mirror else None
                    duel.sync_state(st, d)
                    again.append((d, st))
                duel.set_windows(again, cfg)
                again = duel.allocate([(d, st, duel.decide(d, st, tick, cfg)) for d, st in again], cfg, late=True)
                for d, st, dec in again:
                    if dec["action"] == "accept" and d["rival_offer"] is not None:
                        st.accepted_at = tick
                        x = byid[d["duel"]]
                        x["deal"] = (d["rival_offer"]["price"],
                                     d["rival_offer"].get("days") if x["dl"].days else None, tick, "us")
            for x, say in held:
                if not x["deal"]:
                    _post_rival(x, say, tick)
            for x in live:
                x["d"]["rounds"] = rounds_of(x["msgs"], rounds_rule)
                st = x["st"]
                if st.accepted_at is not None and tick - st.accepted_at >= 2 and not x["deal"]:
                    st.accepted_at = None
        for x in xs:
            dl, d = x["dl"], x["d"]
            r = {"duel": dl.id, "wave": w, "kind": dl.kind, "role": dl.role, "limit": dl.our_limit,
                 "rival_limit": dl.rival_limit, "pie": round(dl.pie(), 2), "pair_limit": pair_of(d, every),
                 "sent": len(x["ours"]), "rival_msgs": len(x["theirs"]), "deal": False, "share": 0.0, "score": 0.0,
                 "rounds": d["rounds"]}
            if x["deal"] and not d1_settles and x["deal"][2] >= x["D"] - 1:
                r["lost_at_d1"] = True                          # accepted at deadline-1, never settled
            elif x["deal"]:
                p, day, at, who = x["deal"]
                rounds = rounds_of(x["msgs"], rounds_rule)      # nothing is posted after the accept
                share, score = score_deal(dl, p, day, rounds)
                r.update(deal=True, price=p, day=day, tick=at, at=at - x["S"], by=who, rounds=rounds,
                         share=round(share, 4), score=round(score, 4),
                         inside=(p >= dl.our_limit) if dl.role == "seller" else (p <= dl.our_limit))
            d["status"] = "deal" if x["deal"] else "no_deal"
            results.append(r)
    return results


def _post_ours(x: dict, st, dec: dict, d: dict, tick: int) -> None:
    duel.record_say(st, dec, d, tick)
    x["ours"].append((tick, dec["price"], dec["days"]))
    x["msgs"].append((tick, "us"))
    d["messages"].append({"tick": tick, "from": "you", "text": "", "price": dec["price"], "days": dec["days"]})
    d["your_offer"] = {"price": dec["price"], "days": dec["days"] if dec["days"] is not None else 0}


def _post_rival(x: dict, say: tuple, tick: int) -> None:
    price, day = say
    x["oid"] += 1
    x["theirs"].append((tick, price, day))
    x["msgs"].append((tick, "them"))
    d = x["d"]
    d["rival_offer"] = {"id": x["oid"], "price": price, "tick": tick, "days": day if day is not None else 0}
    d["messages"].append({"tick": tick, "from": d["rival"], "text": "", "price": price, "days": day})


# ---------------------------------------------------------------- Friday replay (the real rival paths)

def friday_duels(log_dir: Path = ROOT / "logs" / "duels", session: int = 1) -> list:
    """Closed duels of one server session (structure only: limits, roles, rival prices and ticks; text is never read).
    Server session 1 is Friday's practice, 2 is Duels I (Saturday); logs/duels holds both."""
    out = []
    for f in sorted(log_dir.glob("duel-*.json")):
        if "-first" in f.name:
            continue
        d = json.loads(f.read_text())
        if (d.get("status") in ("deal", "no_deal") and isinstance(d.get("your_limit"), (int, float))
                and d.get("session", 1) == session):
            out.append(d)
    return out


def duels1_duels(log_dir: Path = ROOT / "logs" / "duels") -> list:
    """Duels I's closed duels (server session 2, Saturday 11:30-13:25, to tick 630)."""
    return friday_duels(log_dir, session=2)


def _replay_pass(wave: list, every: list, tick: int, see: int, cfg, late: bool = False) -> list:
    """One read of the Friday wave at this tick: the rival messages posted before tick `see`, then duel.py's
    set_windows / decide / allocate."""
    decisions = []
    for w in wave:
        if w["deal"]:
            continue
        d = w["d"]
        theirs = [(t, p) for t, p in w["path"] if t < see]
        mine = [m for m in d["messages"] if m["from"] == "you"]
        d["messages"] = sorted(mine + [{"tick": t, "from": d["rival"], "price": p, "days": None, "text": ""}
                                       for t, p in theirs], key=lambda m: (m["tick"], m["from"] != "you"))
        if theirs:
            d["rival_offer"] = {"id": len(theirs), "price": theirs[-1][1], "tick": theirs[-1][0], "days": 0}
        w["st"].pair_l = duel.mirror_limit(d, every)
        w["st"].rival_limit = w["st"].pair_l if cfg.mirror else None
        duel.sync_state(w["st"], d)
        decisions.append((d, w["st"]))
    duel.set_windows(decisions, cfg)
    decisions = [(d, st, duel.decide(d, st, tick, cfg)) for d, st in decisions]
    if late:
        return duel.allocate(decisions, cfg, late=True)
    duel.allocate(decisions, cfg)
    return decisions


def friday_replay(params: dict, ticks: int = 12, late_look: int = 0, files: list = None) -> list:
    """Our policy against the rival price paths Friday's bots actually posted (they do not react to us here, and
    never accept). One accept per tick across duels sharing a deadline. The rival's limit is unknown, so the pie is
    the SOFT pie from the paired duel; duels with no rival price or a soft pie under 3 P are not scored."""
    every = files if files is not None else friday_duels()
    cfg = cfg_for(params, ticks)
    results = []
    for D in sorted({x["deadline_tick"] for x in every}):
        wave = []
        for x in every:
            if x["deadline_tick"] != D:
                continue
            path = [(m["tick"], m["price"]) for m in x.get("messages") or []
                    if m.get("from") == x.get("rival") and isinstance(m.get("price"), (int, float))]
            d = {**{k: x[k] for k in ("duel", "session", "role", "item", "issues", "your_days_weight", "days_meaning",
                                      "your_limit", "rival", "deadline_tick", "decay_per_round")},
                 "status": "live", "rounds": 0, "your_offer": None, "rival_offer": None, "messages": []}
            wave.append({"d": d, "path": path, "st": duel.DuelState(d, D - ticks, ticks), "deal": None})
        for tick in range(D - ticks, D):
            decisions = _replay_pass(wave, every, tick, tick + (1 if late_look and D - tick <= late_look else 0), cfg)
            for d, st, dec in decisions:
                w = next(w for w in wave if w["d"] is d)
                if dec["action"] == "accept":
                    w["deal"] = (d["rival_offer"]["price"], tick)
                elif dec["action"] == "say":
                    duel.record_say(st, dec, d, tick)
                    d["messages"].append({"tick": tick, "from": "you", "price": dec["price"], "days": None, "text": ""})
                    d["your_offer"] = {"price": dec["price"], "days": 0}
            if getattr(duel, "late_due", None) and duel.late_due(decisions, cfg):
                # duel.py --late-poll: the second read sees the rival's message of this tick; accepts only
                for d, st, dec in _replay_pass(wave, every, tick, tick + 1, cfg, late=True):
                    if dec["action"] == "accept":
                        next(w for w in wave if w["d"] is d)["deal"] = (d["rival_offer"]["price"], tick)
        for w in wave:
            d = w["d"]
            pair = duel.mirror_limit(d, every)
            pie = duel.mirror_pie(d, pair)
            r = {"duel": d["duel"], "role": d["role"], "limit": d["your_limit"], "pair_limit": pair, "soft_pie": pie,
                 "rival_prices": len(w["path"]), "sent": sum(1 for m in d["messages"] if m["from"] == "you"),
                 "deal": bool(w["deal"]), "score": 0.0, "share": 0.0, "scored": bool(w["path"]) and (pie or 0) >= 3}
            if w["deal"]:
                price, at = w["deal"]
                seq = [(m["tick"], "us" if m["from"] == "you" else "them") for m in d["messages"] if m["tick"] < at
                       or (m["tick"] == at and m["from"] != "you")]
                rounds = rounds_of(seq, "exchange")
                s = (price - d["your_limit"]) if d["role"] == "seller" else (d["your_limit"] - price)
                share = s / pie if pie and pie > 0 else 0.0
                r.update(price=price, at=at - (D - ticks), rounds=rounds, share=round(share, 3),
                         score=round(share * (1 - d["decay_per_round"]) ** rounds, 3))
            results.append(r)
    return results


def duels1_replay(params: dict, files: list = None, ticks: int = 16) -> list:
    """Our policy against the rival price paths of Duels I, on the real tick timeline (duels overlap as they did, so
    they share the one accept per tick). Rivals do not react or accept; after a rival's last message its offer stands
    to the deadline (none walked away in Duels I). Where we accepted, the rival's path ends there, so waiting longer
    than we did finds no better offer here: this replay can only show what waiting COSTS. The paired limit is looked
    up as in the run loop (Duels I: never found). The late read sees the rival's same-tick message, as `run` did.
    Scored: duels where the rival posted a price. Score = our surplus / our limit x (1 - decay) ^ rounds; `result`
    is the server's number (surplus x decay, primas)."""
    every = files if files is not None else duels1_duels()
    cfg = cfg_for(params, ticks)
    ws = []
    for x in every:
        path = [(m["tick"], m["price"]) for m in x.get("messages") or []
                if m.get("from") == x.get("rival") and isinstance(m.get("price"), (int, float))]
        d = {**{k: x[k] for k in ("duel", "session", "role", "item", "issues", "your_days_weight", "days_meaning",
                                  "your_limit", "rival", "deadline_tick", "decay_per_round")},
             "status": "live", "rounds": 0, "your_offer": None, "rival_offer": None, "messages": []}
        ws.append({"d": d, "path": path, "S": x["deadline_tick"] - ticks, "D": x["deadline_tick"], "st": None,
                   "deal": None, "real": x})
    if not ws:
        return []
    for tick in range(min(w["S"] for w in ws), max(w["D"] for w in ws)):
        live = [w for w in ws if w["S"] <= tick < w["D"] and not w["deal"]]
        if not live:
            continue
        for w in live:
            if w["st"] is None:
                w["st"] = duel.DuelState(w["d"], tick, ticks)
        decisions = _replay_pass(live, every, tick, tick, cfg)
        for d, st, dec in decisions:
            w = next(w for w in live if w["d"] is d)
            if dec["action"] == "accept":
                w["deal"] = (d["rival_offer"]["price"], tick)
            elif dec["action"] == "say":
                duel.record_say(st, dec, d, tick)
                d["messages"].append({"tick": tick, "from": "you", "price": dec["price"], "days": None, "text": ""})
                d["your_offer"] = {"price": dec["price"], "days": 0}
        if getattr(duel, "late_due", None) and duel.late_due(decisions, cfg):
            for d, st, dec in _replay_pass([w for w in live if not w["deal"]], every, tick, tick + 1, cfg, late=True):
                if dec["action"] == "accept":
                    next(w for w in live if w["d"] is d)["deal"] = (d["rival_offer"]["price"], tick)
    results = []
    for w in ws:
        d, real = w["d"], w["real"]
        r = {"duel": d["duel"], "role": d["role"], "limit": d["your_limit"], "rival_prices": len(w["path"]),
             "sent": sum(1 for m in d["messages"] if m["from"] == "you"), "deal": bool(w["deal"]), "score": 0.0,
             "result": 0.0, "scored": bool(w["path"]), "real_result": real.get("result") or 0.0,
             "real_deal": real.get("status") == "deal"}
        if w["deal"]:
            price, at = w["deal"]
            seq = [(m["tick"], "us" if m["from"] == "you" else "them") for m in d["messages"] if m["tick"] < at
                   or (m["tick"] == at and m["from"] != "you")]
            rounds = rounds_of(seq, "exchange")
            s = (price - d["your_limit"]) if d["role"] == "seller" else (d["your_limit"] - price)
            k = (1 - d["decay_per_round"]) ** rounds
            r.update(price=price, at=at - w["S"], left=w["D"] - at, rounds=rounds, result=round(s * k, 2),
                     score=round(s / d["your_limit"] * k, 4))
        results.append(r)
    return results


def duels1_line(name: str, params: dict) -> str:
    rr = [r for r in duels1_replay(params) if r["scored"]]
    n = max(1, len(rr))
    return (f"{name}: mean score {sum(r['score'] for r in rr) / n:.4f}, result {sum(r['result'] for r in rr):.1f} P, "
            f"deals {sum(r['deal'] for r in rr)}/{len(rr)} (real run: {sum(r['real_result'] for r in rr):.1f} P, "
            f"{sum(r['real_deal'] for r in rr)} deals)")


def replay_line(name: str, params: dict, late_look: int = 0) -> str:
    rr = [r for r in friday_replay(params, late_look=late_look) if r["scored"]]
    return (f"{name}: mean score {sum(r['score'] for r in rr) / max(1, len(rr)):.3f}, deals "
            f"{sum(r['deal'] for r in rr)}/{len(rr)} (" + ", ".join(f"{r['duel']}: {r['score']:.2f}" for r in rr) + ")")


# ---------------------------------------------------------------- evaluation

def evaluate(params: dict, seeds, session: int = 1, kinds=None, rounds_rule: str = "exchange", late_look: int = 0,
             slot_busy: float = 0.0, weights: dict = None, d1_settles: bool = True) -> list:
    """Every duel result for these params over the given session seeds (same seeds = same scenarios and rivals)."""
    sess = SESSIONS[session]
    cfg = cfg_for(params, sess["ticks"])
    kinds = kinds or (FITTED + CLASSIC)
    out = []
    for s in seeds:
        res = play_session(make_session(s, sess, kinds, weights), sess, cfg, s, rounds_rule, late_look, slot_busy,
                           sess_no=session, d1_settles=d1_settles)
        for r in res:
            r["seed"] = s
        out.extend(res)
    return out


def summary(results: list) -> dict:
    """Mean score, worst quartile, deal rate, rounds; overall and per rival kind."""
    def stats(rs):
        if not rs:
            return {}
        sc = sorted(r["score"] for r in rs)
        q = max(1, len(sc) // 4)
        deals = [r for r in rs if r["deal"]]
        return {"n": len(rs), "mean": round(sum(sc) / len(sc), 4), "worst_q": round(sum(sc[:q]) / q, 4),
                "deal_rate": round(len(deals) / len(rs), 3),
                "share": round(sum(r["share"] for r in deals) / len(deals), 4) if deals else 0.0,
                "rounds": round(sum(r["rounds"] for r in deals) / len(deals), 2) if deals else 0.0,
                "msgs": round(sum(r["sent"] for r in rs) / len(rs), 2),
                "outside": sum(1 for r in deals if r["share"] < 0)}
    kinds = sorted({r["kind"] for r in results})
    return {"all": stats(results), **{k: stats([r for r in results if r["kind"] == k]) for k in kinds}}


def objective(results: list, lam: float = 0.25) -> float:
    """Mean score, blended with the worst quartile of per-kind means (absent excluded: it never deals)."""
    s = summary(results)
    means = sorted(v["mean"] for k, v in s.items() if k not in ("all", "absent") and v)
    q = max(1, len(means) // 4)
    return (1 - lam) * s["all"]["mean"] + lam * (sum(means[:q]) / q)


def table(rows: dict, kinds=None) -> str:
    """Markdown table: one column per policy, mean score (deal rate) per kind."""
    names = list(rows)
    kinds = kinds or [k for k in rows[names[0]] if k != "all"]
    out = ["| rivals | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in ["all"] + list(kinds):
        cells = []
        for n in names:
            v = rows[n].get(k) or {}
            cells.append(f"{v.get('mean', 0):.3f} ({v.get('deal_rate', 0):.0%} deals, {v.get('rounds', 0):.1f} rd)"
                         if v else "-")
        out.append(f"| {'**all**' if k == 'all' else k} | " + " | ".join(cells) + " |")
    worst = ["worst quartile (all duels)"] + [f"{rows[n]['all']['worst_q']:.3f}" for n in names]
    out.append("| " + " | ".join(worst) + " |")
    return "\n".join(out)


FIRMER = {**{k: 1 for k in WEIGHTS}, "hardliner": 3, "llm": 2, "tft": 2, "cycler": 2}
STRESS = [  # (label, module overrides, evaluate() kwargs): what if our rival model is wrong?
    ("as modelled", {}, {}),
    ("rounds = min(our msgs, theirs)", {}, {"rounds_rule": "min"}),
    ("accept slot busy 15% of ticks", {}, {"slot_busy": 0.15}),
    ("80% of rivals never accept ours", {"NEVER_TAKES": 0.8}, {}),
    ("20% of rivals never accept ours", {"NEVER_TAKES": 0.2}, {}),
    ("paired limit noisier (+-8%, +-6 P)", {"SCALE": 0.08, "SHIFT": 6.0}, {}),
    ("firmer field (hardliner, llm, tft, cycler)", {}, {"weights": FIRMER}),
    ("Friday archetypes only", {}, {"kinds": FITTED}),
    ("we also see the rival's last-tick message", {}, {"late_look": 1}),
    ("an accept at deadline-1 does not settle", {}, {"d1_settles": False}),
    ("late read: 40% of rival messages land after it, 15% of reads fail", {"LATE_MISS": 0.4, "LATE_FAIL": 0.15}, {}),
    ("late read: every one fails (falls back to the next tick)", {"LATE_FAIL": 1.0}, {}),
    ("paired limit never visible (Duels I: 0/34)", {"PAIR_SEEN": 0.0}, {}),
    ("Duels I field mix, paired limit never visible", {"PAIR_SEEN": 0.0}, {"weights": DUELS1_WEIGHTS}),
    ("Duels I mix, no pair, deadline-1 does not settle", {"PAIR_SEEN": 0.0},
     {"weights": DUELS1_WEIGHTS, "d1_settles": False}),
    ("Duels I mix, no pair, accept slot busy 15%", {"PAIR_SEEN": 0.0}, {"weights": DUELS1_WEIGHTS, "slot_busy": 0.15}),
]


def stress(policies: dict, seeds, session: int = 1) -> str:
    """Markdown table: mean score per duel for each policy under each stress variant."""
    g = globals()
    out = ["| variant | " + " | ".join(policies) + " |", "|---|" + "---|" * len(policies)]
    for label, mods, kw in STRESS:
        saved = {k: g[k] for k in mods}
        g.update(mods)
        try:
            cells = [summary(evaluate(p, seeds, session, **kw))["all"]["mean"] for p in policies.values()]
        finally:
            g.update(saved)
        best = max(cells)
        out.append(f"| {label} | " + " | ".join(f"**{c:.3f}**" if c == best else f"{c:.3f}" for c in cells) + " |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", type=int, default=1, choices=sorted(SESSIONS))
    ap.add_argument("--sessions", type=int, default=200, help="simulated sessions per policy")
    ap.add_argument("--seed0", type=int, default=900000, help="first seed (the tuner tunes on 0.., holds out 500000..)")
    ap.add_argument("--params", action="append", default=[], help="extra params JSON to compare (repeatable)")
    ap.add_argument("--rounds-rule", default="exchange", choices=["exchange", "min"])
    ap.add_argument("--late-look", type=int, default=0)
    ap.add_argument("--slot-busy", type=float, default=0.0)
    ap.add_argument("--pair-seen", type=float, default=None, help="share of duels whose paired limit is visible "
                    "(default PAIR_SEEN = 1; Duels I: 0)")
    ap.add_argument("--weights", default="friday", choices=["friday", "duels1"],
                    help="rival mix: Friday-fitted WEIGHTS or the Duels I mix (DUELS1_WEIGHTS)")
    ap.add_argument("--json", action="store_true", help="print the summaries as JSON")
    ap.add_argument("--stress", action="store_true", help="also print the stress table (what if the model is wrong)")
    a = ap.parse_args()
    global PAIR_SEEN
    if a.pair_seen is not None:
        PAIR_SEEN = a.pair_seen
    weights = DUELS1_WEIGHTS if a.weights == "duels1" else None
    seeds = range(a.seed0, a.seed0 + a.sessions)
    policies = {"defaults": {}}
    for p in a.params:
        policies[Path(p).stem] = load_policy(p)
    rows = {n: summary(evaluate(p, seeds, a.session, rounds_rule=a.rounds_rule, late_look=a.late_look,
                                slot_busy=a.slot_busy, weights=weights)) for n, p in policies.items()}
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    print(f"{SESSIONS[a.session]['name']}: {a.sessions} sessions, rounds rule {a.rounds_rule}, late look "
          f"{a.late_look}, slot busy {a.slot_busy}. Cells: mean score per duel (deal rate, rounds per deal).\n")
    print(table(rows))
    print("\nFriday replay (closed practice duels with rival prices; rivals do not react or accept; soft pie):")
    for n, p in policies.items():
        print("  " + replay_line(n, p, a.late_look))
    print("\nDuels I replay (real timeline, 16 ticks; rivals do not react or accept; score = surplus / our limit x "
          "decay):")
    for n, p in policies.items():
        print("  " + duels1_line(n, p))
    if a.stress:
        print("\nStress (mean score per duel):\n")
        print(stress(policies, seeds, a.session))


if __name__ == "__main__":
    main()
