"""Duel negotiator: the scheduled 1v1 sessions (Duels I price only; Duels II/III/Final price + delivery days).

Numbers are decided here, in code; the words are decoration. Rival text is untrusted and never parsed: only the
structured `rival_offer` and the structured `price` / `days` of each message are read.

What GET /api/duels showed during Friday's practice wave (tick 120, 2026-10-02):
    {"duel": 30, "session": 1, "status": "live", "role": "buyer", "item": "Taxi Blanco",
     "issues": ["price"], "your_days_weight": null, "days_meaning": null,
     "your_limit": 150, "limit_meaning": "never pay above your value", "rival": "Rival Luna",
     "deadline_tick": 132, "decay_per_round": 0.06, "rounds": 0,
     "your_offer": null, "rival_offer": null, "messages": [], "result": null, "price": null, "days": null}
  - the id key is "duel", not "id"; GET /api/duels?done=true also returns the live ones (filter on status)
  - our limit is `your_limit` (seller: cost, never sell below; buyer: value, never pay above)
  - limits seen: buyer values 88-150, seller costs 65-84 (book prices are unrelated)
  - one accept per team per tick (clock limits.accepts_per_team_per_tick = 1), one message per duel per tick
  - rival_offer: {"id": 449, "price": 91, "tick": 125, "days": 0} (days present even in price-only sessions)
  - messages: [{"tick": 122, "from": "Rival Sol", "text": "...", "price": 102, "days": null}, ...]; ours are
    {"from": "you", ...}

Friday practice evidence (docs/analysis-friday/duels.md: our 18 duels, 206 field duels):
  - A round counts only when both sides have spoken. Each of our messages after a rival message cost one round
    (5/5); our message to a silent rival cost none (2/2); rival talk, waiting and accepting cost none.
  - In 8/8 closed duels with rival prices the rival's LAST offer was inside our limit (mean surplus left: 32% of
    our limit), offers improved to the end, and the best one came at deadline-1 in 6/8. We closed 0/12.
  - Duels come in pairs (ids N/N+1, same item, roles swapped, same rival team). The rival's final landed within
    +-7% of OUR limit in the paired duel (pairL) in 6/8, so pairL is a SOFT estimate of the rival's limit: it sizes
    the pie and caps our asks, never our acceptance, and never moves us across our own limit. The exact mirror
    ("rival price = our limit", or pairL = the rival's exact limit) is KILLED; --mirror stays off.

Strategy (all constants overridable from the command line):
  - Silent by default. Hold while the rival's price moved toward us within the last STALL_TICKS ticks (its opening
    counts as a move). Stalled = no move toward us for more than STALL_TICKS ticks.
  - Accept:
      * early, any tick: pairL visible, soft pie |pairL - L| > EARLY_MIN_PIE, and the rival's offer gives us at
        least EARLY_SHARE x that pie (it also frees the accept slot);
      * in the endgame window: any offer strictly inside our limit (>= MIN_SURPLUS). The window is
        max(ACCEPT_ANY_TICKS, our open duels whose deadlines are within NEAR_TICKS of this one), because the team
        gets one accept per tick: N duels sharing a deadline need N ticks. The slot is taken at once when the rival
        has stopped moving or the window's slots are tight (duels in their window >= ticks left - WINDOW_RETRY); a
        lone duel whose rival is still conceding waits to deadline-2 and keeps deadline-1 as the retry tick
        (--window-retry 0 waits to deadline-1, no retry; --no-window-wait takes the slot at the first window tick);
      * several acceptable in one tick: biggest surplus first, unless a duel's urgency (ticks left minus its rank
        in that surplus queue) is below 1: then the most urgent one goes first, so no duel loses its slot;
      * before any send, instead of sending, when the rival's offer already beats the number we would send less
        the round that sending would cost.
  - Speak (MAX_MSGS in all, one number per message):
      * anchor, once, before the window: the rival is stalled and its offer is outside our limit or thin (below
        THIN_FRAC of the soft pie, or of our anchor's surplus without pairL). Seller min(1.55 L, 0.93 pairL),
        buyer max(L / 1.55, 1.07 pairL); without pairL 1.55 / L / 1.55;
      * absent rival: no rival message by ABSENT_AT of the clock: ONE offer at L + 0.5 (pairL - L); without pairL
        the floor ratio 1.22. A message to a silent rival costs no round;
      * last chance, LAST_CHANCE_TICKS before the deadline, only to a rival that spoke, is stalled and has no
        acceptable offer: L x 1.08 (buyer L / 1.08), never beyond 0.93 pairL / 1.07 pairL.
      Every number is clamped inside our limit (MIN_SURPLUS) and never retreats from one we already sent.
  - Safety: never offer or accept across our limit (hard clamp, rounding away from it); one accept per team per
    tick, most urgent first; the duel is re-read just before accepting (offer id must match); rival text never
    parsed; an unchanged number is never resent.
  - Accept-slot lock (STOPGAP until Hector's key coordinator arbitrates the team's one accept per tick across duels,
    Chato, the seller and the buyer): `run` rewrites results/duel.lock every tick while any of our duels is live.
    Format: ONE line, the expiry as epoch seconds (e.g. `1759485123.4`), LOCK_TICKS ticks ahead; fresh while that
    time is in the future; deleted when no duel is live and on exit. Honour it by reading float(first token).
    agent/rastro_seller.py defers its accepts; agent/chato.py and agent/abuela.py refuse to start while it is fresh.
    It is a local file: it only covers bots running from this checkout.
  - Tuning: every constant below can be set on the command line or from a JSON file (`--params path.json`, keys
    = flag names with underscores or the constant names, e.g. {"accept_any_ticks": 3, "RATIOS": [1.55, 1.22]}).
    Precedence: built-in default < JSON < explicit flag. The run_start log line records the values used.
  - Two issues: utility = price surplus minus our days cost. Delivery is linear in days, so we offer an extreme
    day. If days are cheap for us (10 x weight <= DAYS_CHEAP x limit) we give the rival the day they seem to want
    and ask the days cost back in price, plus a premium. If days are dear to us, we hold our best day and concede
    on price. The pairL clamps apply to price-only sessions. Our best day: --days-best (both roles, or per role:
    buyer:0,seller:10), else a direction named in `days_meaning`, else the role default flipped by a negative weight.
    Two-issue messages carry a top-level "days" and the "offer" (say_body).
  - --mirror (off, KILLED in its exact form): treat pairL as the rival's exact limit, ask a share of that pie
    (75% anchor, 55% floor, 30% last chance) and walk when it is empty.
  - Off by default, measured in docs/duel-lab/improvements.md (on in docs/duel-lab/duel-params-duels1-improved.json):
      * --late-poll S --late-ticks N: in a tick where an open duel has N or fewer ticks left, the tick's accept waits
        for a second read of the duels S seconds before the tick ends (the rival's same-tick message is seen first).
        A late read that fails moves the accept to the next tick's first read; two in a row switch it off;
      * --slot-demand spoke|acceptable: only duels whose rival spoke / whose offer we would accept now count toward
        the accept slots a deadline cluster needs;
      * --last-share X: with pairL visible, the last chance at L + X (pairL - L) instead of the LAST_R ratio.
  - Off by default, measured in docs/duel-lab/duels2-params.md ("Duels II fixes"):
      * --hold-while-conceding (F1) --hold-ticks N --[no-]hold-counter: a window accept on an offer that improved on
        the rival's previous one, while the rival is still moving and N or more ticks are left, waits for deadline-1
        (the last tick whose accept settled in Duels I, 3/3), if the slots of the duels that need one still fit
        (otherwise the existing allocation decides and the lower-surplus duels accept earlier, as without it). A
        repeated number ends the wait. While it waits it counters one rung up the ratio schedule (a round) if that
        number beats the offer by more than the round, else it waits in silence (always with --no-hold-counter);
      * --silent-last-margin M (F2): the last chance to a rival that never spoke at L x (1 + M) (buyer L x (1 - M))
        instead of the LAST_R ratio (needs --absent-last to reach a silent rival at all);
      * --open-rung K (F3): the anchor opens at rung K of the ratio schedule instead of RATIOS[0]; in two-issue
        duels it already names both issues (our price, and the day the rival wants when days are cheap for us).
  - Accept path (default on, docs/duel-lab/duels2-params.md "Accept-path review"): the duel is re-read just before
    the POST and the accept goes only if the rival's offer has the same id and terms, or changed to terms at least as
    good for us (then those are taken); otherwise the next acceptable duel of the tick gets the accept. The accept
    endpoint cannot name the offer, so a replacement between that re-read and the POST is accepted as it stands: the
    response's price/days are checked and an `accept_mismatch` line is logged if they differ.

Usage (from the repo root):
    python3 agent/duel.py watch --once --log-dir /tmp/x   # read-only: one pass, prints what it WOULD do
    python3 agent/duel.py watch                          # read-only, every tick: prints what it WOULD send
    python3 agent/duel.py run --until 12:30              # Saturday Duels I: start before game hour 6.5
    python3 agent/duel.py run --until 12:30 --params results/duel-params.json   # tuned numbers, no code edit
    python3 agent/duel.py selftest --n 3000              # offline: rule fuzz + rival archetype simulation
Stops at --until, or after --idle-ticks (default 40) ticks with no live duel once it has seen one.
Only ONE process per team may run `run` (the server allows one message per duel per tick, one accept per tick).

Saturday timing (per Hector, and the team memo): game hours equal wall hours, the schedule maps hours 4.0-18.0
onto 09:00-23:00, so Duels I (hour 6.5) starts about 11:30 and Duels II (hour 13.0) about 18:00. Still read
GET /api/clock (`tick_seconds`) and GET /api/schedule (`now_hours`) at 09:00 before trusting that.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402
from runlog import LOGS, RunLog, redact, write_json  # noqa: E402

# ---------------------------------------------------------------- strategy constants (CLI-overridable)

RATIOS = [1.55, 1.22]               # seller ask = cost x R, buyer bid = value / R: anchor, then floor (absent rival)
LAST_R = 1.08                       # last-chance offer, sent when LAST_CHANCE_TICKS remain
MAX_MSGS = 2                        # hard cap on our messages per duel: after a rival message each one costs a round
LAST_CHANCE_TICKS = 2               # ticks left when the last-chance offer goes out (rival still has time to accept)
ACCEPT_ANY_TICKS = 3                # in the last N ticks accept any offer strictly inside our limit (one slot per duel)
NEAR_TICKS = 2                      # the window grows to the count of our open duels with deadlines this close (<0: off)
MIN_SURPLUS = 1                     # primas; an offer worth less than this to us is never accepted
STALL_TICKS = 3                     # the rival is stalled after more than this many ticks with no move toward us
THIN_FRAC = 0.5                     # an acceptable offer below this share of the soft pie (or anchor surplus) is thin
EARLY_SHARE = 0.85                  # early accept: rival surplus >= this share of the soft pie ...
EARLY_MIN_PIE = 2                   # ... and the soft pie is above this many primas
PAIR_SELL = 0.93                    # seller never asks above PAIR_SELL x pairL ...
PAIR_BUY = 1.07                     # ... buyer never bids below PAIR_BUY x pairL (soft estimate of the rival's limit)
ABSENT_AT = 0.5                     # silent rival: our one offer goes out once this share of the clock has passed
ABSENT_SHARE = 0.5                  # ... at L + ABSENT_SHARE x (pairL - L)
ABSENT_LAST = False                 # also send the last chance to a rival that never spoke (brief: ONE offer)
MIRROR_SHARES = [0.75, 0.55]        # --mirror only: share of the known pie we ask for: anchor, then floor
MIRROR_LAST_SHARE = 0.30            # --mirror only: last-chance share
DAYS_CHEAP = 0.10                   # days are "cheap" for us when 10 x weight <= DAYS_CHEAP x limit
DAYS_PREMIUM = [0.8, 0.25]          # extra price asked on top of our days cost: anchor, then floor
DEFAULT_DUEL_TICKS = 16             # Duels I/II (practice 12, Duels III/Final 12). Used for the mid-clock rule
POST_GAP = 0.25                     # seconds between POSTs (5 req/s per key)
LOCK_PATH = ROOT / "results" / "duel.lock"
LOCK_TICKS = 3                      # the lock expires this many ticks after its last refresh (a dead run frees it)
LATE_POLL = 0.0                     # off. > 0: in a tick where an open duel has LATE_TICKS or fewer ticks left, every
LATE_TICKS = 1                      # accept waits for a second read of the duels this many seconds before the tick ends
LATE_MAX_FAILS = 2                  # this many late reads failing in a row turn the late read off for the run
SLOT_DEMAND = "open"                # duels that count toward the deadline cluster's accept slots: every open one
LAST_SHARE = 0.0                    # off. > 0: with pairL visible, the last chance keeps this share of the soft pie
HOLD_WHILE_CONCEDING = False        # off. F1: a window accept waits for deadline-1 while the rival is still conceding
HOLD_TICKS = 2                      # ... only while at least this many ticks are left (deadline-1 accepts)
HOLD_COUNTER = True                 # ... and counters one rung while it waits (False: waits in silence, no round)
SILENT_LAST_MARGIN = 0.0            # off. F2: last chance to a rival that never spoke at L x (1 +- margin)
OPEN_RUNG = 0                       # F3: the anchor opens at this rung of the ratio schedule (0: RATIOS[0])
WINDOW_RETRY = 1                    # window wait keeps this many ticks before the deadline as retry (0: deadline-1)

SELL_LINES = [
    "Hola. This one is in perfect condition. {offer}.",
    "I can move a little for a quick deal: {offer}.",
    "Let's close it while it is still worth something to both of us: {offer}.",
    "Fair and fast: {offer}.",
    "Last word from me: {offer}.",
]
BUY_LINES = [
    "Hola. I like it, and I can pay {offer}.",
    "I can move a little for a quick deal: {offer}.",
    "Let's close it while it is still worth something to both of us: {offer}.",
    "Fair and fast: {offer}.",
    "Last word from me: {offer}.",
]


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------- reading the structure (never the words)

def parse_offer(x) -> tuple[int, int | None] | None:
    """An offer as (price, days). The server may send an int, {"price", "days"}, or wrap it in "offer"."""
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(x), None
    if isinstance(x, dict):
        if isinstance(x.get("offer"), dict):
            return parse_offer(x["offer"])
        p = x.get("price")
        if p is None:
            return None
        d = x.get("days")
        try:
            return int(p), (None if d is None else int(d))
        except (TypeError, ValueError):
            return None
    return None


def two_issues(d: dict) -> bool:
    return "days" in (d.get("issues") or [])


def role_days_best(override, role) -> str:
    """--days-best for this duel's role: "auto", "0" or "10" (both roles), or per role, "buyer:0,seller:10" (a role
    left out is "auto")."""
    override = str(override or "auto").strip()
    if override in ("auto", "0", "10"):
        return override
    for part in override.split(","):
        k, _, v = part.partition(":")
        if k.strip() == role and v.strip() in ("0", "10"):
            return v.strip()
    return "auto"


def days_best_ok(override) -> bool:
    override = str(override or "auto").strip()
    if override in ("auto", "0", "10"):
        return True
    parts = [x.partition(":") for x in override.split(",")]
    return bool(parts) and all(k.strip() in ("buyer", "seller") and sep and v.strip() in ("0", "10", "auto")
                               for k, sep, v in parts)


def days_profile(d: dict, override: str = "auto") -> tuple[int, float]:
    """(our best delivery day, primas we lose per day away from it). Linear in days.

    The sign convention was not visible on Friday (price-only practice). Order of evidence:
    --days-best override (for both roles, or per role: "buyer:0,seller:10"), keywords in `days_meaning`, then the
    role default (buyer wants it early, seller wants it late) flipped by a negative weight. The sign flip applies
    only when `days_meaning` named no direction: a server that both names the direction and signs the weight must
    not have it flipped twice. `days_meaning` is logged raw on first sight so a human can set --days-best before a
    scored session if this guess is wrong.
    """
    w = d.get("your_days_weight")
    try:
        w = float(w) if w is not None else 0.0
    except (TypeError, ValueError):
        w = 0.0
    override = role_days_best(override, d.get("role"))
    if override in ("0", "10"):
        return int(override), abs(w)
    best = 0 if d.get("role") == "buyer" else 10
    meaning = (d.get("days_meaning") or "").lower()
    late_bad = any(k in meaning for k in ("each day later", "per day later", "later costs", "every day of delay",
                                          "delay costs", "sooner is better", "earlier is better", "you want it early",
                                          "you want it soon"))
    early_bad = any(k in meaning for k in ("each day earlier", "per day earlier", "earlier costs", "rush costs",
                                           "later is better", "more time is better", "you want it late"))
    if late_bad and not early_bad:
        return 0, abs(w)
    if early_bad and not late_bad:
        return 10, abs(w)
    if w < 0:
        best = 10 - best
    return best, abs(w)


def days_cost(d: dict, days: int | None, override: str) -> float:
    if not two_issues(d) or days is None:
        return 0.0
    best, w = days_profile(d, override)
    return w * abs(int(days) - best)


def surplus(d: dict, price: int, days: int | None, override: str) -> float:
    """What a deal at (price, days) is worth to us, in primas, above our limit."""
    lim = d["your_limit"]
    s = (price - lim) if d["role"] == "seller" else (lim - price)
    return s - days_cost(d, days, override)


def inside_limit(d: dict, price: int) -> bool:
    """The hard rule, on price alone: seller never below cost, buyer never above value."""
    lim = d["your_limit"]
    return price >= lim if d["role"] == "seller" else price <= lim


def rival_msgs(d: dict) -> list:
    """The rival's messages (ours are from "you"). Only their tick / price / days are ever read."""
    name = d.get("rival")
    return [m for m in d.get("messages") or [] if isinstance(m, dict) and m.get("from") != "you"
            and (not name or m.get("from") == name)]


def rival_spoke(d: dict) -> bool:
    return bool(rival_msgs(d)) or d.get("rival_offer") is not None


def last_move_tick(d: dict, override: str = "auto") -> int | None:
    """Tick of the rival's latest step toward us (any step, not only a new best, so a cycler's reset does not
    hide its climb). Its opening message, priced or not, counts as a move."""
    msgs = rival_msgs(d)
    mv = None
    prev = None
    for m in msgs:
        t = m.get("tick")
        if not isinstance(t, int):
            continue
        if mv is None:
            mv = t
        p = m.get("price")
        if not isinstance(p, (int, float)) or isinstance(p, bool):
            continue
        days = m.get("days") if two_issues(d) else None
        u = surplus(d, int(p), int(days) if isinstance(days, (int, float)) else None, override)
        if prev is not None and u > prev:
            mv = t
        prev = u
    if mv is None and isinstance(d.get("rival_offer"), dict) and isinstance(d["rival_offer"].get("tick"), int):
        mv = d["rival_offer"]["tick"]   # a standing offer without any message (not seen on Friday)
    return mv


def rival_improved(d: dict, override: str = "auto") -> bool:
    """--hold-while-conceding: did the rival's last priced message improve (for us) on its previous one? A repeated
    number, a step back or a single message is not an improvement."""
    us = []
    for m in rival_msgs(d):
        p = m.get("price")
        if not isinstance(p, (int, float)) or isinstance(p, bool):
            continue
        days = m.get("days") if two_issues(d) else None
        us.append(surplus(d, int(p), int(days) if isinstance(days, (int, float)) else None, override))
    return len(us) >= 2 and us[-1] > us[-2]


# ---------------------------------------------------------------- our numbers

def price_at(d: dict, r: float) -> int:
    """Price for ratio r, rounded away from our limit so int conversion never crosses it."""
    lim = d["your_limit"]
    if d["role"] == "seller":
        return max(lim + 1, int(math.ceil(lim * r)))
    return min(lim - 1, int(math.floor(lim / r)))


def mirror_limit(d: dict, every: list) -> int | None:
    """Our limit in the paired duel (pairL): ids (odd, odd+1), same item and session, roles swapped.

    The rival plays both duels of the pair, so pairL is near the rival's limit here (within +-7% in 6/8 Friday
    duels) but not equal to it: the rules digest says limits get a secret scale and shift per duel.
    """
    did = d.get("duel")
    if not isinstance(did, int):
        return None
    partner = did + 1 if did % 2 else did - 1
    for x in every:
        if (x.get("duel") == partner and x.get("item") == d.get("item") and x.get("session") == d.get("session")
                and x.get("role") != d.get("role") and isinstance(x.get("your_limit"), (int, float))):
            return int(x["your_limit"])
    return None


def mirror_pie(d: dict, rival_limit: int | None) -> int | None:
    """The pie if rival_limit were the rival's limit (positive = a zone of agreement)."""
    if rival_limit is None:
        return None
    return (rival_limit - d["your_limit"]) if d["role"] == "seller" else (d["your_limit"] - rival_limit)


def _interp(xs: list, pos: float, geometric: bool = False) -> float:
    """Value at a fractional position along a schedule (pos 0 = first entry, len-1 = last)."""
    pos = max(0.0, min(float(pos), len(xs) - 1.0))
    i = int(math.floor(pos))
    if i >= len(xs) - 1:
        return xs[-1]
    f = pos - i
    if geometric:
        return xs[i] * (xs[i + 1] / xs[i]) ** f
    return xs[i] + (xs[i + 1] - xs[i]) * f


def planned_offer(d: dict, pos: float, cfg, rival: tuple[int, int | None] | None, last: bool,
                  rival_limit: int | None = None, base: int | None = None) -> tuple[int, int | None]:
    """Our (price, days) at a position on the ratio schedule (0 = anchor, top = floor; fractions interpolate).
    Price-only duels return days=None. `base` replaces the ratio's price (--silent-last-margin)."""
    r = cfg.last_r if last else _interp(cfg.ratios, pos, geometric=True)
    if base is None:
        base = price_at(d, r)
    pie = mirror_pie(d, rival_limit)
    if pie is not None and pie >= 2 and not two_issues(d):
        # --mirror: ask for a share of the known pie instead of a ratio (never beyond the rival's limit)
        top = max(1, len(cfg.ratios) - 1)
        shares = cfg.mirror_shares
        share = cfg.mirror_last_share if last else _interp(shares, pos * (len(shares) - 1) / top)
        lim = d["your_limit"]
        if d["role"] == "seller":
            return max(lim + 1, int(math.ceil(lim + share * pie))), None
        return min(lim - 1, int(math.floor(lim - share * pie))), None
    if not two_issues(d):
        return base, None
    best, w = days_profile(d, cfg.days_best)
    far = 10 - best                                 # the day we assume the rival wants
    if rival and rival[1] is not None:
        far = rival[1]                              # they told us, in structure, which day they want (our best day
                                                    # too: then we offer it, with no premium)
    cheap = 10 * w <= cfg.days_cheap * d["your_limit"]
    if not cheap or far == best:
        return base, best
    top = max(1, len(cfg.ratios) - 1)
    prem = cfg.days_premium[-1] if last else _interp(cfg.days_premium, pos * (len(cfg.days_premium) - 1) / top)
    extra = int(math.ceil(w * abs(far - best) * (1 + prem)))   # our days cost, plus a share of their gain
    p = base + extra if d["role"] == "seller" else base - extra
    if not inside_limit(d, p) or surplus(d, p, far, cfg.days_best) < cfg.min_surplus:
        return base, best
    return p, far


def our_number(d: dict, st: "DuelState", cfg, rival, kind: str) -> tuple[int, int | None]:
    """Our (price, days) for a message of this kind: "anchor", "absent", "last" or "counter" (--hold-while-conceding).

    Price-only with pairL visible (and --mirror off): the anchor and the last chance never ask beyond
    PAIR_SELL x pairL (seller) / PAIR_BUY x pairL (buyer); the absent-rival offer sits at L + ABSENT_SHARE x
    (pairL - L). Then: never retreat from a number we already sent, and clamp inside our limit (MIN_SURPLUS).
    """
    top = len(cfg.ratios) - 1
    open_rung = min(max(0, int(getattr(cfg, "open_rung", 0))), top)
    silent_last = kind == "last" and getattr(cfg, "silent_last_margin", 0) > 0 and not rival_spoke(d)
    if kind == "anchor":
        p, days = planned_offer(d, open_rung, cfg, rival, False, st.rival_limit)
    elif kind == "absent":
        p, days = planned_offer(d, top, cfg, rival, False, st.rival_limit)
    elif kind == "counter":   # --hold-while-conceding: one rung past the last one we sent
        pos = open_rung + st.sent
        p, days = planned_offer(d, min(pos, top), cfg, rival, pos > top, st.rival_limit)
    elif silent_last:         # --silent-last-margin: L x (1 + margin), buyer L x (1 - margin)
        lim, m = d["your_limit"], cfg.silent_last_margin
        base = (max(lim + 1, int(math.ceil(lim * (1 + m) - 1e-9))) if d["role"] == "seller"
                else min(lim - 1, int(math.floor(lim * (1 - m) + 1e-9))))
        p, days = planned_offer(d, top, cfg, rival, True, st.rival_limit, base=base)
    else:
        p, days = planned_offer(d, top, cfg, rival, True, st.rival_limit)
    if two_issues(d):
        return p, days
    lim, pl, seller = d["your_limit"], st.pair_l, d["role"] == "seller"
    if pl is not None and st.rival_limit is None:
        if kind == "absent":
            mid = lim + cfg.absent_share * (pl - lim)
            p = int(math.ceil(mid)) if seller else int(math.floor(mid))
        elif kind == "last" and getattr(cfg, "last_share", 0) > 0 and not silent_last:   # --last-share
            mid = lim + cfg.last_share * (pl - lim)
            p = min(int(math.ceil(mid)), int(math.floor(cfg.pair_sell * pl))) if seller else \
                max(int(math.floor(mid)), int(math.ceil(cfg.pair_buy * pl)))
        elif seller:
            p = min(p, int(math.floor(cfg.pair_sell * pl)))
        else:
            p = max(p, int(math.ceil(cfg.pair_buy * pl)))
    if st.last_sent is not None and st.last_sent[0] is not None:
        prev = int(st.last_sent[0])
        p = min(p, prev) if seller else max(p, prev)
    p = max(lim + cfg.min_surplus, p) if seller else min(lim - cfg.min_surplus, p)
    return int(p), None


# ---------------------------------------------------------------- one decision per duel per tick

class DuelState:
    def __init__(self, d: dict, tick: int, duel_ticks: int):
        self.id = d["duel"]
        # A duel nobody has spoken in yet is seen on its first tick (the loop reads every tick): its length is the
        # deadline minus this tick (Duels III are 12 ticks, whatever duel_ticks says). Joining mid-way we only know
        # the deadline, so then never assume it is shorter than duel_ticks.
        seen = d["deadline_tick"] - tick
        fresh = (not d.get("messages") and d.get("your_offer") is None and d.get("rival_offer") is None
                 and not d.get("rounds"))
        self.total = max(1, seen) if fresh else max(1, duel_ticks, seen)
        self.start = d["deadline_tick"] - self.total
        self.step = None            # kind of the message we last sent (anchor / absent / last)
        self.sent = 0               # messages we have sent in this duel
        self.last_sent: tuple | None = None
        self.last_sent_tick: int | None = None
        self.rival_id_at_send = None
        self.accepted_at: int | None = None
        self.accepted_terms: tuple | None = None   # (price, days) we approved when we accepted (settled_mismatch)
        self.dumped = False
        self.last_rival = None
        self.window: int | None = None        # accept window for this tick (set by set_windows)
        self.pair_l: int | None = None        # our limit in the paired duel: a soft estimate of the rival's limit
        self.rival_limit: int | None = None   # set only with --mirror (pairL taken as exact)


def offer_id(raw):
    """The rival offer's identity: its id when the server gives one, else its numbers."""
    return raw.get("id") if isinstance(raw, dict) and raw.get("id") is not None else parse_offer(raw)


def sync_state(st: DuelState, d: dict) -> None:
    """A restarted run must not forget what we already said: count our messages, pick up our standing offer."""
    ours = [m for m in d.get("messages") or [] if isinstance(m, dict) and m.get("from") == "you"]
    st.sent = max(st.sent, len(ours))
    if st.last_sent is None:
        mine = parse_offer(d.get("your_offer"))
        if mine is not None:
            st.last_sent = (mine[0], mine[1] if two_issues(d) else None)


def record_say(st: DuelState, dec: dict, d: dict, tick: int) -> None:
    st.last_sent, st.last_sent_tick, st.step = (dec["price"], dec["days"]), tick, dec.get("step")
    st.sent += 1
    st.rival_id_at_send = offer_id(d.get("rival_offer"))


def soft_pie(d: dict, pair_l: int | None) -> int | None:
    return mirror_pie(d, pair_l)


def decide(d: dict, st: DuelState, tick: int, cfg) -> dict:
    """Returns {"action": "accept"|"say"|"hold", ...}. Pure: no I/O, no state change.

    Silent by default (rival talk and waiting are free; each of our messages after a rival message costs a round).
    Accept early on the soft-pie trigger, else in the endgame window; speak only to a stalled or silent rival.
    """
    left = d["deadline_tick"] - tick
    rival = parse_offer(d.get("rival_offer"))
    decay = float(d.get("decay_per_round") or 0.06)
    elapsed = tick - st.start
    spoke = rival_spoke(d)
    mv = last_move_tick(d, cfg.days_best)
    moving = spoke and mv is not None and tick - mv <= cfg.stall_ticks
    stalled = spoke and not moving
    pie = soft_pie(d, st.pair_l)
    acc_window = left <= max(cfg.accept_any_ticks, st.window or 0)   # accepting: grows with the deadline cluster
    window = left <= cfg.accept_any_ticks                             # talking: no new anchor in the last ticks
    last = left <= cfg.last_chance_ticks
    out = {"left": left, "sent": st.sent, "rival": rival, "pair_l": st.pair_l, "soft_pie": pie,
           "moving": moving, "last_move": mv, "step": None, "next": None, "next_days": None}

    if st.accepted_at is not None:
        return {**out, "action": "hold", "why": "accepted, waiting to settle"}
    if left < 1:
        return {**out, "action": "hold", "why": "deadline"}

    acceptable, rs = False, None
    if rival is not None:
        rp, rd = rival
        rd_ok = not (two_issues(d) and rd is None)
        rs = surplus(d, rp, rd, cfg.days_best) if rd_ok else -1e9
        out["rival_surplus"] = round(rs, 2)
        acceptable = rd_ok and inside_limit(d, rp) and rs >= cfg.min_surplus
    if acceptable:
        if pie is not None and pie > cfg.early_min_pie and rs >= cfg.early_share * pie:
            return {**out, "action": "accept", "kind": "early",
                    "why": f"early: surplus {rs:.0f} >= {cfg.early_share} x soft pie {pie}"}
        if acc_window:
            if getattr(cfg, "hold_while_conceding", False):   # read by allocate (F1)
                out["conceding"] = moving and rival_improved(d, cfg.days_best)
            return {**out, "action": "accept", "kind": "window", "why": f"endgame ({left} ticks left), inside limit"}

    hard = mirror_pie(d, st.rival_limit)
    if hard is not None and hard < 2 and not two_issues(d):
        return {**out, "action": "hold", "why": f"walk: no zone of agreement (mirror pie {hard})"}

    budget = cfg.max_msgs - st.sent
    absent_from = int(math.ceil(cfg.absent_at * st.total))
    kind = None
    if budget >= 1 and last and not acceptable and ((spoke and stalled) or (not spoke and cfg.absent_last)):
        kind = "last"
    elif budget >= 1 and not spoke and st.sent == 0 and elapsed >= absent_from:
        kind = "absent"
    elif budget >= 2 and not window and stalled:
        if not acceptable:
            kind = "anchor"
        else:
            if pie is not None and pie > cfg.early_min_pie:
                ref = pie
            else:
                ap, ad = our_number(d, st, cfg, rival, "anchor")
                ref = surplus(d, ap, ad, cfg.days_best)
            if rs < cfg.thin_frac * ref:
                kind = "anchor"
            out["thin_ref"] = round(ref, 2)

    if kind is None:
        if budget <= 0:
            why = f"message budget spent ({st.sent}/{cfg.max_msgs})"
        elif not spoke:
            why = (f"rival silent: listening until mid-clock (elapsed {elapsed}/{absent_from})" if st.sent == 0
                   else "rival silent: our one offer stands")
        elif moving:
            why = f"rival moved toward us at tick {mv}: listening (free)"
        elif window:
            why = "endgame window: no talk except the last chance to a stuck rival"
        elif acceptable:
            why = "rival offer inside our limit and not thin: waiting for the window"
        else:
            why = "last message kept for the last chance"
        return {**out, "action": "hold", "why": why}

    p, days = our_number(d, st, cfg, rival, kind)
    out.update(next=p, next_days=days, step=kind)
    if st.last_sent == (p, days):
        return {**out, "action": "hold", "why": f"our number {p} stands ({kind}; resending would cost a round)"}
    if acceptable:
        bar = surplus(d, p, days, cfg.days_best) * (1 - decay)
        out["bar"] = round(bar, 2)
        if rs >= bar:
            return {**out, "action": "accept", "kind": "instead",
                    "why": f"rival surplus {rs:.0f} >= our {kind} {p} less a round ({bar:.0f})"}
    return {**out, "action": "say", "price": p, "days": days,
            "why": {"last": "last chance", "absent": "absent rival: one offer", "anchor": "anchor (rival stalled)"}[kind]}


def set_windows(pairs: list, cfg) -> None:
    """Each duel's accept window this tick: max(ACCEPT_ANY_TICKS, our open duels whose deadline is within
    NEAR_TICKS of its own). The team has one accept per tick, so N duels ending together need N ticks."""
    open_ = [(d, st) for d, st in pairs if st.accepted_at is None and needs_slot(d, cfg)]
    for d, st in pairs:
        near = 0
        if cfg.near_ticks >= 0:
            near = sum(1 for x, _ in open_ if abs(x["deadline_tick"] - d["deadline_tick"]) <= cfg.near_ticks)
        st.window = max(cfg.accept_any_ticks, near)


def needs_slot(d: dict, cfg) -> bool:
    """Does this duel count toward the accept slots the deadline cluster needs? --slot-demand open (default): every
    open duel. spoke: only duels whose rival has spoken (a rival that never spoke has no offer for us to accept).
    acceptable: only duels whose standing rival offer we would accept now (the others keep deadline-1 as retry)."""
    mode = getattr(cfg, "slot_demand", "open")
    if mode == "acceptable":
        r = parse_offer(d.get("rival_offer"))
        return r is not None and inside_limit(d, r[0]) and surplus(d, r[0], r[1], cfg.days_best) >= cfg.min_surplus
    return mode == "open" or rival_spoke(d)


def late_due(decisions: list, cfg) -> bool:
    """--late-poll: this tick gets a second read, because one of our open duels has LATE_TICKS or fewer ticks left
    (the rival's message of this tick, often its best one at deadline-1, lands after our first read)."""
    return getattr(cfg, "late_poll", 0) > 0 and any(
        x[1].accepted_at is None and 1 <= x[2]["left"] <= cfg.late_ticks for x in decisions)


def acceptable_offer(d: dict, offer, cfg) -> bool:
    """The hard checks on an offer's terms: both issues named when the duel has two, inside our limit, worth at least
    MIN_SURPLUS to us."""
    if offer is None or (two_issues(d) and offer[1] is None):
        return False
    return inside_limit(d, offer[0]) and surplus(d, offer[0], offer[1], cfg.days_best) >= cfg.min_surplus


def accept_candidates(decisions: list) -> list:
    """The tick's one accept, in order: the duel allocate chose, then the ones it held for the one accept per tick
    (slot_rank 1, 2, ...). Empty when allocate chose none (for example when the accept waits for the late read)."""
    chosen = [x for x in decisions if x[2]["action"] == "accept"]
    if not chosen:
        return []
    return chosen + sorted((x for x in decisions if x[2]["action"] == "hold" and x[2].get("slot_rank")),
                           key=lambda x: x[2]["slot_rank"])


def fresh_check(d: dict, fresh: dict | None, cfg) -> tuple[str, tuple | None]:
    """The duel re-read just before the accept, against the one we decided on.
    ("same", terms): same offer id and terms. ("better", terms): the rival replaced its offer with terms still
    acceptable and at least as good for us (take them: a rival that posted this tick cannot post again before the tick
    ends). ("changed", None): anything else (gone, finished, worse): no accept on this duel this tick."""
    approved = parse_offer(d.get("rival_offer"))
    if fresh is None or fresh.get("status", "live") != "live" or approved is None:
        return "changed", None
    now = parse_offer(fresh.get("rival_offer"))
    if now is None or not acceptable_offer(fresh, now, cfg):
        return "changed", None
    if offer_id(fresh.get("rival_offer")) == offer_id(d.get("rival_offer")) and now == approved:
        return "same", now
    if surplus(fresh, now[0], now[1], cfg.days_best) >= surplus(d, approved[0], approved[1], cfg.days_best):
        return "better", now
    return "changed", None


def try_accepts(b, run, cands: list, tick: int, cfg, **tag) -> bool:
    """POST the tick's one accept to the first candidate whose re-read still shows its offer (or a better one). A
    candidate whose offer changed for the worse passes the accept to the next one, so one rival's move never wastes
    the tick's slot. A refusal or a failed read ends the tick's accepts. The accept endpoint cannot name the offer, so
    a replacement between the re-read and the POST is accepted as it stands: the response is checked and logged as
    `accept_mismatch`. Returns True when an accept went out."""
    for d, st, dec in cands:
        did = d["duel"]
        row = {k: dec.get(k) for k in ("left", "rival", "rival_surplus", "pair_l", "soft_pie", "moving", "why")}
        try:
            fresh = next((x for x in b.duels().get("duels", []) if x.get("duel") == did), None)
        except BazaarError as e:
            run.event("error", where="reread", duel=did, code=e.code, msg=e.message, **tag)
            return False
        verdict, terms = fresh_check(d, fresh, cfg)
        if verdict == "changed":
            run.event("accept_skipped", duel=did, why="rival offer changed", now=fresh and fresh.get("rival_offer"),
                      **tag)
            continue
        try:
            resp = b.duel_accept(did)
        except BazaarError as e:
            run.event("refused", duel=did, action="accept", code=e.code, msg=e.message, extra=e.extra, **tag)
            return False
        st.accepted_at, st.accepted_terms = tick, (terms[0], terms[1] if two_issues(fresh) else None)
        run.event("accept", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, taken=verdict,
                  terms=list(terms), resp=resp, **tag, **row)
        if isinstance(resp, dict):
            rp, rd = resp.get("price"), resp.get("days")
            if (isinstance(rp, (int, float)) and int(rp) != terms[0]) or \
                    (two_issues(fresh) and isinstance(rd, (int, float)) and int(rd) != terms[1]):
                days = int(rd) if two_issues(fresh) and isinstance(rd, (int, float)) else terms[1]
                run.event("accept_mismatch", duel=did, approved=list(terms), accepted={"price": rp, "days": rd},
                          surplus=round(surplus(fresh, int(rp if isinstance(rp, (int, float)) else terms[0]), days,
                                                cfg.days_best), 2), **tag)
        return True
    return False


def allocate(decisions: list, cfg, late: bool = False) -> list:
    """One accept per team per tick.

    A window accept waits while its rival is still conceding and the window has a spare slot (duels inside their
    window with this deadline or earlier < ticks left - 1): a lone duel then takes deadline-2 and keeps deadline-1
    as the retry. Of the rest, the biggest surplus goes first, unless some duel's urgency (ticks left minus its
    rank in that surplus queue) is below 1: then the most urgent goes first, so no duel loses its slot.
    --late-poll: in a tick that gets a second read (late_due), the first read accepts nothing; the late read
    (late=True) decides again on fresh duels and takes the slot.
    --hold-while-conceding (F1): before all that, a window accept on a rival still conceding waits for deadline-1
    when the slots fit without its retry tick (duels in their window with this deadline or earlier < ticks left), and
    counters one rung while it waits if that number beats the offer by more than a round.
    The duels held by the one accept per tick get "slot_rank" (1 = next in line): if the chosen duel's re-read shows
    its offer changed for the worse, the run loop gives the tick's accept to the next one (accept_candidates)."""
    demand = [x for x in decisions
              if x[1].accepted_at is None and 1 <= x[2]["left"] <= max(cfg.accept_any_ticks, x[1].window or 0)
              and needs_slot(x[0], cfg)]
    if getattr(cfg, "hold_while_conceding", False):
        for d, st, dec in decisions:
            if (dec["action"] != "accept" or dec.get("kind") != "window" or not dec.get("conceding")
                    or dec["left"] < cfg.hold_ticks):
                continue
            tight = sum(1 for x in demand if x[0]["deadline_tick"] <= d["deadline_tick"])
            if tight >= dec["left"]:
                continue   # the slots would not fit: the allocation below decides, as without the flag
            dec["action"] = "hold"
            dec["why"] = f"rival still conceding: waiting for deadline-1 ({tight} duel(s) need a slot)"
            if getattr(cfg, "hold_counter", True) and st.sent < cfg.max_msgs:
                p, days = our_number(d, st, cfg, dec.get("rival"), "counter")
                bar = surplus(d, p, days, cfg.days_best) * (1 - float(d.get("decay_per_round") or 0.06))
                if st.last_sent != (p, days) and inside_limit(d, p) and bar > dec.get("rival_surplus", 0):
                    dec.update(action="say", price=p, days=days, step="counter", next=p, next_days=days,
                               why=f"rival still conceding: counter one rung ({p}) and wait for deadline-1")
    if getattr(cfg, "window_wait", True):
        for d, st, dec in decisions:
            if dec["action"] != "accept" or dec.get("kind") != "window" or not dec.get("moving"):
                continue
            tight = sum(1 for x in demand if x[0]["deadline_tick"] <= d["deadline_tick"])
            if tight < dec["left"] - getattr(cfg, "window_retry", 1):
                dec["action"] = "hold"
                dec["why"] = f"window: rival still conceding, waiting one tick ({tight} duel(s) need a slot)"
    queue = [x for x in decisions if x[2]["action"] == "accept"]
    queue.sort(key=lambda x: (-x[2].get("rival_surplus", 0), x[2]["left"]))
    if queue:
        # The duels worth keeping: biggest surplus first, each into the latest free tick before its deadline. One that
        # finds no free tick could only be saved by letting a bigger one expire, so it goes last (it used to win on
        # urgency: surpluses 50 and 5 on the same last tick took the 5).
        taken, keep, drop = set(), [], []
        for x in queue:
            slot = next((s for s in range(max(1, x[2]["left"]) - 1, -1, -1) if s not in taken), None)
            (drop if slot is None else keep).append(x)
            if slot is not None:
                taken.add(slot)
        urgency = [(x[2]["left"] - rank, rank) for rank, x in enumerate(keep)]
        first = min(range(len(keep)), key=lambda i: urgency[i]) if min(urgency)[0] < 1 else 0
        order = [keep[first]] + [x for i, x in enumerate(keep) if i != first] + drop
        for rank, x in enumerate(order):
            if rank:
                x[2]["action"] = "hold"
                x[2]["slot_rank"] = rank
                x[2]["why"] = "acceptable, but one accept per tick: re-checked next tick"
    if not late and late_due(decisions, cfg):
        for x in queue:
            if x[2]["action"] == "accept":
                x[2]["action"], x[2]["late"] = "hold", True
                x[2]["why"] = f"accept waits for the late read, {cfg.late_poll:g} s before the tick ends"
    return decisions


def say_body(text: str, price: int, days: int | None) -> dict:
    """The body of POST /api/duels/{id}/messages. RULES: in a two-issue session both sides send {"text", "price",
    "days"} (or both inside "offer"), and a priced message without days is refused (missing_days). The kit's
    duel_say sends "price" and "offer" but no top-level "days", so two-issue messages carry all three, consistent."""
    body = {"text": text, "price": int(price)}
    if days is not None:
        body["days"] = int(days)
        body["offer"] = {"price": int(price), "days": int(days)}
    return body


def post_say(b, did: int, text: str, price: int, days: int | None) -> dict:
    """Send one message: price-only through the kit's duel_say, two-issue with say_body (a top-level days too)."""
    if days is None:
        return b.duel_say(did, text, price=price)
    return b._call("POST", f"/api/duels/{int(did)}/messages", say_body(text, price, days))


def words(d: dict, n_sent: int, price: int, days: int | None, last: bool = False) -> str:
    lines = SELL_LINES if d["role"] == "seller" else BUY_LINES
    offer = f"{price} P" + (f", delivery day {days}" if days is not None else "")
    return (lines[-1] if last else lines[min(n_sent, len(lines) - 2)]).format(offer=offer)


# ---------------------------------------------------------------- accept-slot lock (shared with our other bots)

_LOCK_MINE = False


def write_lock(tick_seconds, lock_ticks: int = LOCK_TICKS) -> None:
    """results/duel.lock: one line, the expiry in epoch seconds. While it is fresh, rastro_seller.py defers
    accepts and chato.py will not start. Written atomically (tmp file + rename)."""
    global _LOCK_MINE
    try:
        ts = float(tick_seconds) if tick_seconds else 60.0
    except (TypeError, ValueError):
        ts = 60.0
    exp = time.time() + max(1, lock_ticks) * max(5.0, ts)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCK_PATH.with_name(LOCK_PATH.name + ".tmp")
    tmp.write_text(f"{exp:.1f}\n")
    os.replace(tmp, LOCK_PATH)
    _LOCK_MINE = True


def lock_fresh(path: Path = LOCK_PATH) -> bool:
    """The reader side (what the other bots do): fresh while the expiry on the first line is in the future."""
    try:
        return float(path.read_text().split()[0]) > time.time()
    except (OSError, ValueError, IndexError):
        return False


def clear_lock() -> None:
    """Remove the lock if this process wrote it."""
    global _LOCK_MINE
    if _LOCK_MINE:
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
        _LOCK_MINE = False


# ---------------------------------------------------------------- the loop

def mirror_evidence(d: dict, every: list) -> dict:
    """Did the rival offer across our paired limit? (the exact mirror would forbid it)"""
    ml = mirror_limit(d, every)
    if ml is None:
        return {}
    theirs = [m.get("price") for m in d.get("messages") or []
              if m.get("from") == d.get("rival") and isinstance(m.get("price"), (int, float))]
    crossed = [p for p in theirs if (p > ml if d.get("role") == "seller" else p < ml)]
    return {"mirror_rival_limit": ml, "rival_prices": theirs, "rival_crossed_mirror": crossed}


def settled_mismatch(d: dict, st: "DuelState") -> dict | None:
    """A finished duel that settled on other terms than the ones we approved when we accepted (the accept endpoint
    cannot name the offer): the alarm fields, else None."""
    if st is None or st.accepted_terms is None or d.get("status") != "deal":
        return None
    p, days = d.get("price"), d.get("days") if two_issues(d) else None
    if p is None or (int(p), None if days is None else int(days)) == st.accepted_terms:
        return None
    return {"approved": list(st.accepted_terms), "settled": {"price": p, "days": days},
            "surplus": round(surplus(d, int(p), None if days is None else int(days), "auto"), 2)}


def surplus_share_note(d: dict) -> dict:
    """What we can say about a finished duel from our side alone."""
    p = d.get("price")
    if p is None:
        return {}
    lim = d["your_limit"]
    return {"our_surplus": (p - lim) if d["role"] == "seller" else (lim - p)}


def _csv(x) -> str:
    return ",".join(str(v) for v in x)


def tick_left(clock: dict) -> float:
    """Seconds until the next tick, never more than a whole tick (a bad next_tick_in must not oversleep the tick)."""
    try:
        ts = float(clock.get("tick_seconds") or 30.0)
        return max(0.0, min(float(clock.get("next_tick_in", ts)), ts))
    except (TypeError, ValueError):
        return 0.0


def late_pass(b, run, cfg, states: dict, tick: int, sending: bool, tick_end: float) -> bool:
    """--late-poll: the tick's second read, LATE_POLL seconds before it ends. The rival's message of this tick (its
    best one, at deadline-1, in 6/8 Friday duels) lands after our first read; reading again before accepting lets the
    one accept of this tick take it. Accepts only: this tick's messages went out in the first read.
    Returns False when the read did not happen (tick over, paused, network): the caller then accepts in the next
    tick's first read, so one failed late read never holds accepts for two ticks."""
    try:
        clock = b.clock()
        if int(clock["tick"]) != tick or clock.get("paused"):
            run.event("late_skipped", tick=tick, now=clock.get("tick"), paused=clock.get("paused"))
            return False
        time.sleep(max(0.0, min(tick_end, time.time() + tick_left(clock)) - cfg.late_poll - time.time()))
        clock = b.clock()
        if int(clock["tick"]) != tick:
            run.event("late_skipped", tick=tick, now=clock.get("tick"), why="tick over before the late read")
            return False
    except Exception as e:  # noqa: BLE001  (network, shape): no late accept this tick
        run.event("error", where="late", tick=tick, kind=type(e).__name__, msg=str(e)[:200])
        return False
    every = None
    for attempt in range(3):   # a slow or failed read is retried while 2 s of the tick remain
        try:
            every = b.duels(done=True).get("duels", [])
            break
        except Exception as e:  # noqa: BLE001
            run.event("error", where="late", tick=tick, attempt=attempt, kind=type(e).__name__, msg=str(e)[:200])
            if time.time() + 1.0 > tick_end - 2.0:
                break
            time.sleep(1.0)
    if every is None:
        return False
    pairs = []
    for d in every:
        st = states.get(d.get("duel"))
        if d.get("status") != "live" or st is None:
            continue
        if d.get("rival_offer") != st.last_rival:   # what the late read is for: logged so Saturday can measure it
            st.last_rival = d.get("rival_offer")
            run.event("rival", duel=d["duel"], offer=d.get("rival_offer"), rounds=d.get("rounds"), late=True)
        st.pair_l = mirror_limit(d, every)
        st.rival_limit = st.pair_l if cfg.mirror else None
        sync_state(st, d)
        pairs.append((d, st))
    set_windows(pairs, cfg)
    decisions = allocate([(d, st, decide(d, st, tick, cfg)) for d, st in pairs], cfg, late=True)
    cands = accept_candidates(decisions)
    if cands:
        d, st, dec = cands[0]
        row = {k: dec.get(k) for k in ("left", "rival", "rival_surplus", "pair_l", "soft_pie", "moving", "why")}
        if not inside_limit(d, dec["rival"][0]):  # cannot happen by construction; never accept it
            run.event("bug_skip", duel=d["duel"], action="accept", rival=dec["rival"], limit=d["your_limit"])
        elif not sending:
            run.event("would_accept", duel=d["duel"], role=d["role"], limit=d["your_limit"], tick=tick, late=True,
                      **row)
        else:
            try_accepts(b, run, cands, tick, cfg, late=True)
    return True


# flags that are not tuning: never taken from a --params file
NOT_PARAMS = {"cmd", "params", "until", "once", "log_dir", "n", "seed", "idle_ticks"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Duel negotiator (watch / run / selftest)")
    ap.add_argument("cmd", choices=["watch", "run", "selftest"])
    ap.add_argument("--params", default=None, help="JSON file of tuning values (keys: flag names or constant names)")
    ap.add_argument("--ratios", default=_csv(RATIOS), help="anchor ratio, floor ratio")
    ap.add_argument("--last-r", type=float, default=LAST_R)
    ap.add_argument("--max-msgs", type=int, default=MAX_MSGS)
    ap.add_argument("--last-chance-ticks", type=int, default=LAST_CHANCE_TICKS)
    ap.add_argument("--accept-any-ticks", type=int, default=ACCEPT_ANY_TICKS)
    ap.add_argument("--near-ticks", type=int, default=NEAR_TICKS,
                    help="accept window = max(accept-any-ticks, our open duels with deadlines this close); <0: off")
    ap.add_argument("--min-surplus", type=int, default=MIN_SURPLUS)
    ap.add_argument("--stall-ticks", type=int, default=STALL_TICKS)
    ap.add_argument("--thin-frac", type=float, default=THIN_FRAC)
    ap.add_argument("--early-share", type=float, default=EARLY_SHARE)
    ap.add_argument("--early-min-pie", type=float, default=EARLY_MIN_PIE)
    ap.add_argument("--pair-sell", type=float, default=PAIR_SELL)
    ap.add_argument("--pair-buy", type=float, default=PAIR_BUY)
    ap.add_argument("--absent-at", type=float, default=ABSENT_AT)
    ap.add_argument("--absent-share", type=float, default=ABSENT_SHARE)
    ap.add_argument("--absent-last", action=argparse.BooleanOptionalAction, default=ABSENT_LAST,
                    help="also send the last chance to a rival that never spoke (free: no round while it is silent)")
    ap.add_argument("--no-window-wait", dest="window_wait", action="store_false",
                    help="take the accept slot at the first window tick even when the rival is still conceding")
    ap.add_argument("--window-retry", type=int, default=WINDOW_RETRY,
                    help="window wait keeps this many ticks before the deadline as retry: 1 takes a lone duel at "
                         "deadline-2, 0 at deadline-1 (no retry if that accept fails)")
    ap.add_argument("--mirror-shares", default=_csv(MIRROR_SHARES))
    ap.add_argument("--mirror-last-share", type=float, default=MIRROR_LAST_SHARE)
    ap.add_argument("--days-cheap", type=float, default=DAYS_CHEAP)
    ap.add_argument("--days-premium", default=_csv(DAYS_PREMIUM))
    ap.add_argument("--days-best", default="auto",
                    help="override our preferred delivery day if days_meaning shows the guess is wrong: 0 or 10 for "
                         "both roles, or per role, e.g. buyer:0,seller:10")
    ap.add_argument("--duel-ticks", type=int, default=DEFAULT_DUEL_TICKS)
    ap.add_argument("--post-gap", type=float, default=POST_GAP)
    ap.add_argument("--lock-ticks", type=int, default=LOCK_TICKS)
    ap.add_argument("--late-poll", type=float, default=LATE_POLL,
                    help="seconds before the tick ends for a second read of the duels in the last --late-ticks ticks "
                         "of any open duel; that tick's accepts wait for it (0: off)")
    ap.add_argument("--late-ticks", type=int, default=LATE_TICKS)
    ap.add_argument("--last-share", type=float, default=LAST_SHARE,
                    help="price-only, pairL visible: the last chance at L + share x (pairL - L) instead of the "
                         "--last-r ratio (0: off)")
    ap.add_argument("--slot-demand", default=SLOT_DEMAND, choices=["open", "spoke", "acceptable"],
                    help="which duels count toward the accept slots a deadline cluster needs: every open one, those "
                         "whose rival has spoken, or those with a rival offer we would accept now")
    ap.add_argument("--hold-while-conceding", action=argparse.BooleanOptionalAction, default=HOLD_WHILE_CONCEDING,
                    help="F1: a window accept on a rival still conceding waits for deadline-1 (if the slots fit)")
    ap.add_argument("--hold-ticks", type=int, default=HOLD_TICKS,
                    help="F1: wait only while at least this many ticks are left (2: accept at deadline-1)")
    ap.add_argument("--hold-counter", action=argparse.BooleanOptionalAction, default=HOLD_COUNTER,
                    help="F1: counter one rung while waiting, when it beats the offer by more than a round")
    ap.add_argument("--silent-last-margin", type=float, default=SILENT_LAST_MARGIN,
                    help="F2: last chance to a rival that never spoke at L x (1 + M), buyer L x (1 - M) (0: off)")
    ap.add_argument("--open-rung", type=int, default=OPEN_RUNG,
                    help="F3: the anchor opens at this rung of --ratios (0: the first ratio)")
    ap.add_argument("--mirror", action="store_true",
                    help="KILLED hypothesis: take the paired limit as the rival's exact limit (keep off)")
    ap.add_argument("--until", default="", help="stop at this local wall time, HH:MM")
    ap.add_argument("--once", action="store_true", help="one pass, then exit (even with the clock paused)")
    ap.add_argument("--idle-ticks", type=int, default=40, help="exit after this many ticks with no live duel "
                    "(only once we have seen one)")
    ap.add_argument("--log-dir", default=str(LOGS), help="where duel/<date>.jsonl and duels/duel-N.json go")
    ap.add_argument("--n", type=int, default=3000, help="selftest: simulated duels")
    ap.add_argument("--seed", type=int, default=7, help="selftest: random seed")
    return ap


def load_params(path: str, ap: argparse.ArgumentParser) -> dict:
    """A --params JSON file as parser defaults. Keys are flag dests (accept_any_ticks) or constant names
    (ACCEPT_ANY_TICKS, DEFAULT_DUEL_TICKS); lists may be JSON lists or comma strings. Unknown keys are an error."""
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict):
        sys.exit(f"--params {path}: expected a JSON object")
    dests = {a.dest for a in ap._actions} - NOT_PARAMS - {"help"}
    out = {}
    for k, v in raw.items():
        key = {"default_duel_ticks": "duel_ticks"}.get(str(k).lower(), str(k).lower().replace("-", "_"))
        if key not in dests:
            sys.exit(f"--params {path}: unknown key {k!r} (known: {', '.join(sorted(dests))})")
        out[key] = _csv(v) if isinstance(v, list) else v
    return out


def make_cfg(argv: list):
    ap = build_parser()
    pre = ap.parse_args(argv)
    if pre.params:
        ap.set_defaults(**load_params(pre.params, ap))   # explicit flags still win
    cfg = ap.parse_args(argv)
    cfg.ratios = [float(x) for x in str(cfg.ratios).split(",") if x.strip()]
    cfg.days_premium = [float(x) for x in str(cfg.days_premium).split(",") if x.strip()]
    cfg.mirror_shares = [float(x) for x in str(cfg.mirror_shares).split(",") if x.strip()]
    if not cfg.ratios or any(r <= 1.0 for r in cfg.ratios) or cfg.last_r <= 1.0:
        sys.exit("ratios must be > 1.0 (1.0 is our limit)")
    if cfg.max_msgs < 1:
        sys.exit("--max-msgs must be >= 1")
    if cfg.min_surplus < 1:
        sys.exit("--min-surplus must be >= 1 (0 would accept at our limit)")
    if not cfg.mirror_shares or not cfg.days_premium:
        sys.exit("--mirror-shares and --days-premium need at least one value")
    if cfg.late_poll < 0 or cfg.late_ticks < 1:
        sys.exit("--late-poll must be >= 0 (0: off) and --late-ticks >= 1")
    if not days_best_ok(cfg.days_best):
        sys.exit("--days-best must be auto, 0, 10 or per role like buyer:0,seller:10")
    if cfg.window_retry < 0:
        sys.exit("--window-retry must be >= 0")
    if cfg.hold_ticks < 1 or not 0 <= cfg.silent_last_margin < 1 or cfg.open_rung < 0:
        sys.exit("--hold-ticks must be >= 1, --silent-last-margin in [0, 1), --open-rung >= 0")
    return cfg


def params_of(cfg) -> dict:
    """Every tuning value in use, for the run_start log line (and to copy into a --params file)."""
    return {k: v for k, v in sorted(vars(cfg).items()) if k not in NOT_PARAMS}


def main() -> None:
    cfg = make_cfg(sys.argv[1:])
    if cfg.cmd == "selftest":
        raise SystemExit(selftest(cfg))
    load_env()
    sending = cfg.cmd == "run"
    log_dir = Path(cfg.log_dir)

    run = RunLog("duel")
    run.path = log_dir / "duel" / (time.strftime("%Y-%m-%d") + ".jsonl")
    run.path.parent.mkdir(parents=True, exist_ok=True)

    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"],
               wait_on_tick=False)
    stop_at = None
    if cfg.until:
        hh, mm = cfg.until.split(":")
        lt = time.localtime()
        stop_at = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(hh), int(mm), 0, 0, 0, -1))
    run.start(mode=cfg.cmd, params_file=cfg.params, once=cfg.once,
              lock=str(LOCK_PATH.relative_to(ROOT)) if sending else None, **params_of(cfg))

    states: dict[int, DuelState] = {}
    finished: set[int] = set()
    last_tick = None
    late_failed = False     # --late-poll: last tick's late read did not happen, so this tick accepts in its first read
    late_fails = 0          # late reads failed in a row
    idle = 0
    seen_any = False
    passes = 0
    try:
        while True:
            if cfg.once and passes >= 1:
                break
            if stop_at and time.time() >= stop_at:
                run.event("stop", why="until")
                break
            try:
                clock = b.clock()
                tick = int(clock["tick"])
            except Exception as e:  # noqa: BLE001  (network, shape): wait and retry, never die
                run.event("error", where="clock", kind=type(e).__name__, msg=str(e)[:200])
                if cfg.once:
                    break
                time.sleep(5)
                continue
            if not cfg.once and (tick == last_tick or clock.get("paused")):
                time.sleep(min(10.0, max(0.5, float(clock.get("next_tick_in", 2.0)) + 0.4)))
                continue
            passes += 1
            last_tick = tick
            tick_end = time.time() + tick_left(clock)
            try:  # one bad shape or bug must never end an unattended run: log it and go to the next tick
                try:
                    every = b.duels(done=True).get("duels", [])
                except BazaarError as e:
                    run.event("error", where="duels", code=e.code, msg=e.message)
                    continue
                live = [d for d in every if d.get("status") == "live"]
                if sending:  # the accept slot is ours while any duel is live
                    if live:
                        write_lock(clock.get("tick_seconds"), cfg.lock_ticks)
                    else:
                        clear_lock()
                if cfg.once:
                    run.event("pass", tick=tick, paused=clock.get("paused"), tick_seconds=clock.get("tick_seconds"),
                              duels=len(every), live=len(live))

                # finished duels: log the result and save the transcript once
                for d in every:
                    did = d.get("duel")
                    if d.get("status") != "live" and did in states and did not in finished:
                        finished.add(did)
                        run.event("result", duel=did, role=d.get("role"), limit=d.get("your_limit"),
                                  status=d.get("status"), result=d.get("result"), price=d.get("price"),
                                  days=d.get("days"), rounds=d.get("rounds"), rival=d.get("rival"),
                                  **surplus_share_note(d), **mirror_evidence(d, every))
                        write_json(log_dir / "duels" / f"duel-{int(did):05d}.json", d)
                        alarm = settled_mismatch(d, states.get(did))
                        if alarm:
                            run.event("accept_mismatch", duel=did, where="settled", **alarm)

                if not live:
                    idle += 1
                    if seen_any and idle >= cfg.idle_ticks:
                        run.event("stop", why=f"no live duel for {idle} ticks")
                        break
                    continue
                idle = 0
                seen_any = True

                decisions = []
                for d in live:
                    did = d["duel"]
                    st = states.get(did)
                    if st is None:
                        st = states[did] = DuelState(d, tick, cfg.duel_ticks)
                        run.event("duel_new", duel=did, role=d.get("role"), item=d.get("item"),
                                  limit=d.get("your_limit"), issues=d.get("issues"),
                                  days_weight=d.get("your_days_weight"), days_meaning=d.get("days_meaning"),
                                  rival=d.get("rival"), deadline=d.get("deadline_tick"),
                                  decay=d.get("decay_per_round"), total_ticks=st.total,
                                  pair_limit=mirror_limit(d, every), mirror_used=cfg.mirror)
                    if not st.dumped and (d.get("rival_offer") is not None or d.get("messages")
                                          or d.get("days_meaning") is not None):
                        st.dumped = True  # first sight of the parts we had not seen: keep the raw object
                        write_json(log_dir / "duels" / f"duel-{int(did):05d}-first.json", d)
                    if d.get("rival_offer") != st.last_rival:
                        st.last_rival = d.get("rival_offer")
                        run.event("rival", duel=did, offer=d.get("rival_offer"), rounds=d.get("rounds"),
                                  your_offer=d.get("your_offer"),
                                  text=(str((d.get("messages") or [{}])[-1].get("text") or "")[:160]
                                        if d.get("messages") else None))  # logged only, never acted on
                    st.pair_l = mirror_limit(d, every)   # soft estimate, always read
                    st.rival_limit = st.pair_l if cfg.mirror else None
                    sync_state(st, d)
                    decisions.append((d, st))
                set_windows(decisions, cfg)
                decisions = [(d, st, decide(d, st, tick, cfg)) for d, st in decisions]

                allocate(decisions, cfg, late=late_failed)

                for d, st, dec in decisions:
                    did = d["duel"]
                    row = {k: dec.get(k) for k in ("left", "step", "rival", "rival_surplus", "pair_l", "soft_pie",
                                                   "moving", "next", "next_days", "why")}
                    row["window"] = st.window
                    if dec["action"] == "hold":
                        run.event("hold", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, **row)
                        continue
                    if dec["action"] == "accept":
                        if not inside_limit(d, dec["rival"][0]):  # cannot happen by construction; never accept it
                            run.event("bug_skip", duel=did, action="accept", rival=dec["rival"], limit=d["your_limit"])
                            continue
                        if not sending:
                            run.event("would_accept", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, **row)
                            continue
                        # re-read just before accepting: the server accepts the standing offer, whatever it is by then
                        try_accepts(b, run, accept_candidates(decisions), tick, cfg)
                        time.sleep(cfg.post_gap)
                        continue
                    # say
                    price, days = dec["price"], dec["days"]
                    if not inside_limit(d, price):  # cannot happen by construction; never send it, never crash
                        run.event("bug_skip", duel=did, price=price, limit=d["your_limit"], role=d["role"])
                        continue
                    text = words(d, st.sent, price, days, last=dec["why"] == "last chance")
                    if not sending:
                        run.event("would_say", duel=did, role=d["role"], limit=d["your_limit"], tick=tick,
                                  price=price, days=days, text=text,
                                  **{k: v for k, v in row.items() if k not in ("next", "next_days")})
                        record_say(st, dec, d, tick)
                        continue
                    try:
                        resp = post_say(b, did, text, price, days)
                        record_say(st, dec, d, tick)
                        run.event("say", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, price=price,
                                  days=days, resp=redact(resp),
                                  **{k: v for k, v in row.items() if k not in ("next", "next_days")})
                    except BazaarError as e:
                        # 429 / wait_for_tick: skip this duel until the next tick, never retry-spam
                        run.event("refused", duel=did, action="say", code=e.code, msg=e.message, extra=e.extra)
                    time.sleep(cfg.post_gap)

                if not cfg.once and not late_failed and late_due(decisions, cfg):
                    try:
                        late_ok = late_pass(b, run, cfg, states, tick, sending, tick_end)
                    except Exception as e:  # noqa: BLE001  a crash in the late read is a FAILED late read: counted
                        # toward late_off, and the next tick's first read accepts (no accept is held twice)
                        run.event("error", where="late_pass", tick=tick, kind=type(e).__name__, msg=str(e)[:300])
                        late_ok = False
                    late_failed = not late_ok
                    late_fails = late_fails + 1 if late_failed else 0
                    if late_fails >= LATE_MAX_FAILS:
                        cfg.late_poll = 0.0
                        run.event("late_off", tick=tick, why=f"{late_fails} late reads failed in a row")
                else:
                    late_failed = False

                # accepted duels that did not settle within two ticks are open again
                for st in states.values():
                    if st.accepted_at is not None and tick - st.accepted_at >= 2 and st.id not in finished:
                        st.accepted_at = None
            except Exception as e:  # noqa: BLE001
                run.event("error", where="tick", tick=tick, kind=type(e).__name__, msg=str(e)[:300])
                time.sleep(2)
    except KeyboardInterrupt:
        run.event("stop", why="ctrl-c")
    finally:
        if sending:
            clear_lock()
    run.end(duels_seen=len(states), finished=len(finished))


# ---------------------------------------------------------------- offline simulation (selftest)
#
# Rival archetypes from Friday's practice duels (docs/analysis-friday/duels.md, Q4). Every rival has a true limit R
# within +-7% of our paired limit, never offers or accepts across R, and accepts our standing offer when it sits no
# further from its own current price than tau of the way to R (tau_end at deadline-1). Rounds: each of our messages
# after a rival message costs one; a message to a silent rival costs none. Value of a deal = our share of the true
# pie x (1 - decay) ^ rounds; no deal = 0. The rival models are guesses: the counts are for comparing rules.

ARCHETYPES = ("steady", "fast", "cycler", "oneshot", "llm", "absent")


class SimRival:
    def __init__(self, rng: random.Random, kind: str, we_sell: bool, R: float, start: int, deadline: int):
        self.rng, self.kind, self.R, self.sells, self.D = rng, kind, R, not we_sell, deadline
        self.plan: dict = {}
        self.price = None
        self.tau, self.tau_end = rng.uniform(0.0, 0.4), rng.uniform(0.4, 1.0)
        self.dead, self.thresh, self.seen_ours, self.final_move = False, None, None, False
        last = deadline - 1
        lvl = self.level
        if kind == "steady":       # 9/10, 93/94: monotone every 1-3 ticks, ends at D-1 near its limit
            o = start + rng.randint(0, 3)
            x0, x1, k, g = rng.uniform(.45, .75), rng.uniform(.93, 1.0), rng.randint(1, 3), rng.uniform(1.0, 2.0)
            for t in list(range(o, last, k)) + [last]:
                self.plan[t] = lvl(x0 + (x1 - x0) * ((t - o) / max(1, last - o)) ** g)
        elif kind == "fast":       # 99/100: two big jumps in two ticks to about its limit, then holds
            o = start + rng.randint(0, 4)
            x0, x1 = rng.uniform(.6, .8), rng.uniform(.97, 1.0)
            self.plan = {o: lvl(x0), o + 1: lvl(x0 + (x1 - x0) * 2 / 3), o + 2: lvl(x1)}
        elif kind == "cycler":     # 37/38: repeats its opening x5, then +s, +s, reset; one more step at D-1
            o = start + rng.randint(0, 2)
            x0 = rng.uniform(.45, .65)
            s = (max(x0 + .06, rng.uniform(.6, .8)) - x0) / 3
            a = 0
            for t in range(o, last + 1):
                i = t - o
                a = 0 if i <= 5 else (min(3, a + 1) if t == last else [1, 2, 0][(i - 6) % 3])
                self.plan[t] = lvl(x0 + a * s)
            self.tau = rng.uniform(0.0, 0.3)
        elif kind == "oneshot":    # 29/30: one opening around D-8, then nothing
            self.plan = {max(start, deadline - rng.randint(6, 10)): lvl(rng.uniform(.5, .9))}
            self.tau = rng.uniform(.2, .8)
        elif kind == "llm":        # 103/104: opens near, moves 3 P once, then only in reply to our concessions
            o = start + rng.randint(0, 6)
            p0 = lvl(rng.uniform(.75, .95))
            self.plan = {o: p0, o + 2: p0 + (3 if not self.sells else -3)}
            self.final_move = rng.random() < 0.5
            self.tau = rng.uniform(.2, .6)
        elif kind == "absent":     # 23/24, 91/92, 139/140: never speaks; half are passive accepters
            self.dead = rng.random() < 0.5
            self.thresh = lvl(rng.uniform(.75, 1.0))
        self.plan = {t: p for t, p in self.plan.items() if start <= t <= last}

    def level(self, x: float) -> int:
        """The rival's price at factor x of its limit (x < 1 favours the rival)."""
        return int(round(self.R / x)) if self.sells else int(round(self.R * x))

    def inside(self, x) -> bool:
        return x >= self.R if self.sells else x <= self.R

    def clip(self, p: int) -> int:
        return max(p, int(math.ceil(self.R))) if self.sells else min(p, int(math.floor(self.R)))

    def good(self, x, target) -> bool:
        return x >= target if self.sells else x <= target

    def accepts(self, t: int, x: int) -> bool:
        if not self.inside(x):
            return False
        if self.kind == "absent":
            return not self.dead and self.rng.random() < 0.7 and self.good(x, self.thresh)
        if self.price is None:
            return False
        if self.kind == "llm" and abs(x - self.price) <= 0.05 * self.price:
            return True
        tau = self.tau_end if t >= self.D - 1 else self.tau
        return self.good(x, self.price + tau * (self.R - self.price))

    def act(self, t: int, d: dict):
        ours = (d.get("your_offer") or {}).get("price")
        if ours is not None and self.accepts(t, ours):
            return "accept", ours
        p = self.plan.get(t)
        if self.kind == "llm" and self.price is not None:
            move = 0.0
            if ours is not None and ours != self.seen_ours:
                if self.seen_ours is None:
                    move = self.rng.randint(2, 3)
                else:
                    conceded = (self.seen_ours - ours) if not self.sells else (ours - self.seen_ours)
                    move = conceded * self.rng.uniform(0.5, 1.0) if conceded > 0 else 0.0
                self.seen_ours = ours
            if self.final_move and t == self.D - 2:
                move += 0.25 * abs(self.R - self.price)
            if move >= 1:
                p = int(round(self.price + (-move if self.sells else move)))
        if p is None:
            return None
        self.price = self.clip(p)
        return "say", self.price


def _phase(u: float, p_post: float, p_race: float) -> str:
    return "race" if u < p_race else ("post" if u < p_race + p_post else "pre")


def _old_allocate(decisions: list) -> None:
    accepts = sorted([x for x in decisions if x[2]["action"] == "accept"],
                     key=lambda x: (x[2]["left"], -x[2].get("rival_surplus", 0)))
    for x in accepts[1:]:
        x[2]["action"] = "hold"


def _old_record(st, dec: dict, d: dict, tick: int) -> None:
    st.last_sent, st.last_sent_tick, st.step = (dec["price"], dec["days"]), tick, dec.get("step")
    st.sent += 1
    st.rival_id_at_send = offer_id(d.get("rival_offer"))


def simulate(mod, cfg, n_duels: int = 3000, seed: int = 7, kinds=ARCHETYPES, d1_settles: bool = True,
             p_post: float = 0.4, p_race: float = 0.05, p_refuse: float = 0.1, pair_seen: float = 0.85, sizes=(1, 2, 3),
             ticks: int = 16, decay: float = 0.06, offsets=(0, 0, 0, 1, 2)) -> dict:
    """Run `mod.decide` (this module, or an older copy of it) against scripted rivals, in waves of 1-3 concurrent
    duels sharing one accept per tick. Worlds depend only on the seed, so two modules face the same rivals.
    p_post: the rival moves after our actions this tick (we decided on its previous offer; it can take ours at once).
    p_race: the rival moves between our read and our accept (the re-read sees a new offer and skips the accept).
    p_refuse: our accept is refused (a teammate's bot took the tick's slot, a 429).
    offsets: deadline offsets drawn per duel (0 only = every duel of a wave shares one deadline)."""
    stats = {k: {"duels": 0, "zopa": 0, "deals": 0, "value": 0.0, "sends": 0, "rounds": 0} for k in kinds}
    out = {"violations": [], "max_sends": 0, "max_sends_before_last": 0, "late_lost": 0, "by_kind": stats,
           "duels": 0, "our_accepts": 0, "rival_accepts": 0, "acceptable_at_end": 0, "slot_lost": 0}
    record = getattr(mod, "record_say", _old_record)
    done, wave, oid = 0, 0, 1
    while done < n_duels:
        wave += 1
        wr = random.Random(seed * 1_000_003 + wave)
        start = 1000
        duels = []
        for i in range(wr.choice(sizes)):
            role = wr.choice(["seller", "buyer"])
            L = wr.randint(65, 160)
            k = wr.uniform(0.9, 2.3)
            pair = round(L * k) if role == "seller" else round(L / k)
            R = pair * (1 + wr.uniform(-0.07, 0.07))
            kind = kinds[(done + i) % len(kinds)]
            D = start + ticks + wr.choice(offsets)
            rival = SimRival(random.Random(wr.random()), kind, role == "seller", R, start, D)
            d = {"duel": 2 * i + 1, "session": 1, "status": "live", "role": role, "item": f"I{i}", "issues": ["price"],
                 "your_days_weight": None, "days_meaning": None, "your_limit": L, "rival": f"Rival {kind}",
                 "deadline_tick": D, "decay_per_round": decay, "rounds": 0, "your_offer": None, "rival_offer": None,
                 "messages": [], "result": None, "price": None, "days": None}
            st = mod.DuelState(d, start, ticks)
            st.pair_l = pair if wr.random() < pair_seen else None
            zopa = (R - L) if role == "seller" else (L - R)
            duels.append({"d": d, "st": st, "rival": rival, "kind": kind, "pie": zopa, "open": True, "deal": None,
                          "sends": 0, "last_sends": 0,
                          "phase": {t: _phase(wr.random(), p_post, p_race) for t in range(start, D + 1)},
                          "refuse": {t: wr.random() < p_refuse for t in range(start, D + 1)}})
        done += len(duels)

        def settle(x, price, t, by):
            d = x["d"]
            out["our_accepts" if by == "us" else "rival_accepts"] += 1
            x["open"] = False
            d["status"] = "deal"
            if not inside_limit(d, price) or surplus(d, price, None, "auto") < MIN_SURPLUS:
                out["violations"].append(f"deal at {price} vs limit {d['your_limit']} ({d['role']})")
            if not d1_settles and t >= d["deadline_tick"] - 1:
                out["late_lost"] += 1
                return
            x["deal"] = price

        def rival_turn(x, t):
            nonlocal oid
            res = x["rival"].act(t, x["d"])
            if res is None:
                return
            if res[0] == "accept":
                settle(x, res[1], t, "rival")
                return
            d = x["d"]
            oid += 1
            d["messages"].append({"tick": t, "from": d["rival"], "text": "", "price": res[1], "days": None})
            d["rival_offer"] = {"id": oid, "price": res[1], "tick": t, "days": 0}

        for t in range(start, max(x["d"]["deadline_tick"] for x in duels) + 1):
            for x in duels:
                if x["open"] and t >= x["d"]["deadline_tick"]:
                    x["open"] = False
                    x["d"]["status"] = "no_deal"
                    r = parse_offer(x["d"].get("rival_offer"))
                    if r is not None and inside_limit(x["d"], r[0]) and surplus(x["d"], r[0], None, "auto") >= 1:
                        out["acceptable_at_end"] += 1   # an acceptable offer stood at the deadline: a lost slot
            live = [x for x in duels if x["open"]]
            if not live:
                break
            for x in live:
                if x["phase"][t] == "pre":
                    rival_turn(x, t)
            live = [x for x in live if x["open"]]
            snaps = [(x, copy.deepcopy(x["d"])) for x in live]
            for x, snap in snaps:
                if hasattr(mod, "sync_state"):
                    mod.sync_state(x["st"], snap)
            if hasattr(mod, "set_windows"):
                mod.set_windows([(snap, x["st"]) for x, snap in snaps], cfg)
            decisions = [(snap, x["st"], mod.decide(snap, x["st"], t, cfg)) for x, snap in snaps]
            if hasattr(mod, "allocate"):
                mod.allocate(decisions, cfg)
            else:
                _old_allocate(decisions)
            for x in live:
                if x["open"] and x["phase"][t] == "race":
                    rival_turn(x, t)
            for (x, snap), (_, st, dec) in zip(snaps, decisions):
                if not x["open"] or dec["action"] == "hold":
                    continue
                d = x["d"]
                if dec["action"] == "accept":
                    rp = parse_offer(snap.get("rival_offer"))
                    if rp is None or not inside_limit(d, rp[0]) or surplus(d, rp[0], None, "auto") < MIN_SURPLUS:
                        out["violations"].append(f"accept decision on {rp} vs limit {d['your_limit']} ({d['role']})")
                        continue
                    if offer_id(d.get("rival_offer")) != offer_id(snap.get("rival_offer")) or x["refuse"][t]:
                        continue   # the re-read saw a new offer, or the slot was taken: next tick
                    st.accepted_at = t
                    settle(x, rp[0], t, "us")
                    continue
                p = dec["price"]
                if not inside_limit(d, p) or surplus(d, p, None, "auto") < MIN_SURPLUS:
                    out["violations"].append(f"offer {p} vs limit {d['your_limit']} ({d['role']})")
                    continue
                if any(m.get("from") != "you" for m in d["messages"]):
                    d["rounds"] += 1
                oid += 1
                d["messages"].append({"tick": t, "from": "you", "text": "", "price": p, "days": None})
                d["your_offer"] = {"id": oid, "price": p, "tick": t, "days": 0}
                record(st, dec, snap, t)
                x["sends"] += 1
                x["last_sends"] += dec.get("why") == "last chance"

            for x in live:
                if x["open"] and x["phase"][t] == "post":
                    rival_turn(x, t)
            if getattr(mod, "late_due", None) and mod.late_due(decisions, cfg):
                # --late-poll: a second read after the rival's moves of this tick; it takes the tick's one accept
                late = [(x, copy.deepcopy(x["d"])) for x in live if x["open"]]
                for x, snap in late:
                    mod.sync_state(x["st"], snap)
                mod.set_windows([(snap, x["st"]) for x, snap in late], cfg)
                again = mod.allocate([(snap, x["st"], mod.decide(snap, x["st"], t, cfg)) for x, snap in late], cfg,
                                     late=True)
                for (x, snap), (_, st, dec) in zip(late, again):
                    if dec["action"] != "accept" or x["refuse"][t]:
                        continue
                    rp = parse_offer(snap.get("rival_offer"))
                    if (rp is None or not inside_limit(x["d"], rp[0])
                            or surplus(x["d"], rp[0], None, "auto") < MIN_SURPLUS):
                        out["violations"].append(f"late accept on {rp} vs limit {x['d']['your_limit']}")
                        continue
                    st.accepted_at = t
                    settle(x, rp[0], t, "us")

        for x in duels:
            s = stats[x["kind"]]
            s["duels"] += 1
            out["duels"] += 1
            s["sends"] += x["sends"]
            out["max_sends"] = max(out["max_sends"], x["sends"])
            out["max_sends_before_last"] = max(out["max_sends_before_last"], x["sends"] - x["last_sends"])
            if x["pie"] < 1:
                continue
            s["zopa"] += 1
            if x["deal"] is not None:
                d = x["d"]
                share = surplus(d, x["deal"], None, "auto") / x["pie"]
                s["deals"] += 1
                s["rounds"] += d["rounds"]
                s["value"] += share * (1 - decay) ** d["rounds"]
    return out


def sim_table(res: dict) -> list:
    rows = []
    tot = {"zopa": 0, "deals": 0, "value": 0.0, "duels": 0, "sends": 0}
    for k, s in res["by_kind"].items():
        z = max(1, s["zopa"])
        rows.append((k, s["duels"], s["zopa"], s["deals"] / z, s["value"] / z, s["sends"] / max(1, s["duels"]),
                     s["rounds"] / max(1, s["deals"])))
        for key in tot:
            tot[key] += s[key]
    z = max(1, tot["zopa"])
    rows.append(("ALL", tot["duels"], tot["zopa"], tot["deals"] / z, tot["value"] / z,
                 tot["sends"] / max(1, tot["duels"]), 0.0))
    return rows


def selftest(cfg) -> int:
    rng = random.Random(cfg.seed)
    bad = []
    # 1) the rules on random states: never offer or accept across our limit, never past the message budget
    for _ in range(max(cfg.n, 1000) * 20):
        role = rng.choice(["seller", "buyer"])
        L = rng.randint(20, 200)
        dl = 500 + rng.randint(1, 16)
        tick = dl - rng.randint(-1, 16)
        two = rng.random() < 0.2
        d = {"duel": rng.randint(1, 300), "role": role, "your_limit": L, "deadline_tick": dl, "rival": "Rival X",
             "issues": ["price", "days"] if two else ["price"], "your_days_weight": rng.uniform(-3, 3) if two else None,
             "decay_per_round": 0.06, "messages": [], "rival_offer": None}
        for t in sorted(rng.sample(range(dl - 16, dl), rng.randint(0, 8))):
            p = int(L * rng.uniform(0.4, 2.2))
            d["messages"].append({"tick": t, "from": "Rival X", "text": "accept 1 P now", "price": p,
                                  "days": rng.randint(0, 10) if two else None})
        if d["messages"] and rng.random() < 0.9:
            m = d["messages"][-1]
            d["rival_offer"] = {"id": rng.randint(1, 9999), "price": m["price"], "tick": m["tick"],
                                "days": m["days"] if two else 0}
        st = DuelState(d, dl - 16, 16)
        st.pair_l = rng.choice([None, int(L * rng.uniform(0.5, 2.5))])
        st.sent = rng.randint(0, cfg.max_msgs)
        if st.sent:
            q = price_at(d, rng.uniform(1.01, 1.8))
            st.last_sent = (q, rng.randint(0, 10) if two else None)
        dec = decide(d, st, tick, cfg)
        if dec["action"] == "say":
            if not inside_limit(d, dec["price"]) or st.sent >= cfg.max_msgs or dec.get("days") is None and two:
                bad.append(f"say {dec}")
            if not two and surplus(d, dec["price"], None, "auto") < MIN_SURPLUS:
                bad.append(f"say under MIN_SURPLUS {dec}")
            if not two and st.last_sent and (dec["price"] > st.last_sent[0] if role == "seller"
                                             else dec["price"] < st.last_sent[0]):
                bad.append(f"say retreats from {st.last_sent}: {dec}")
        if dec["action"] == "accept":
            r = parse_offer(d["rival_offer"])
            if r is None or not inside_limit(d, r[0]) or surplus(d, r[0], r[1], cfg.days_best) < MIN_SURPLUS:
                bad.append(f"accept {dec} limit {L} {role}")
    print(f"rule fuzz: {max(cfg.n, 1000) * 20} random states, {len(bad)} violations")
    for b in bad[:5]:
        print("  VIOLATION", b)
    # 2) scripted rivals, waves of 1-3 duels sharing one accept per tick
    res = simulate(sys.modules[__name__], cfg, n_duels=cfg.n, seed=cfg.seed)
    print(f"simulation: {cfg.n}+ duels, 16 ticks, decay 0.06, 85% with pairL visible, 10% accepts refused, "
          f"5% rival moves racing our accept")
    print(f"{'rival':>8} {'duels':>6} {'zopa':>5} {'deal%':>6} {'value':>6} {'sends':>6} {'rounds/deal':>11}")
    for k, n, z, dr, v, sd, rd in sim_table(res):
        print(f"{k:>8} {n:>6} {z:>5} {100 * dr:>5.1f}% {v:>6.3f} {sd:>6.2f} {rd:>11.2f}")
    print(f"limit violations: {len(res['violations'])}   max sends per duel: {res['max_sends']}   "
          f"max sends before the last chance: {res['max_sends_before_last']}")
    for v in res["violations"][:5]:
        print("  VIOLATION", v)
    # 3) accept staggering: 3 and 6 duels sharing one deadline, window grown to N vs fixed at ACCEPT_ANY_TICKS
    fixed = copy.copy(cfg)
    fixed.near_ticks = -1
    print("shared deadline (one accept per tick): accepts landed by us / rival, acceptable offers left at the end")
    for size in (3, 6):
        for label, c in (("window max(3,N)", cfg), (f"fixed {cfg.accept_any_ticks}", fixed)):
            r = simulate(sys.modules[__name__], c, n_duels=max(600, cfg.n // 2), seed=cfg.seed + size, sizes=(size,),
                         offsets=(0,))
            bad += [f"{size} concurrent: {v}" for v in r["violations"]]
            print(f"  {size} concurrent, {label:>16}: {r['duels']} duels, ours {r['our_accepts']}, "
                  f"rival {r['rival_accepts']}, left acceptable {r['acceptable_at_end']}")
    # 4) allocation order and the lock reader
    def fake(left, rs, dl):
        st = DuelState({"duel": 1, "deadline_tick": dl}, dl - 16, 16)
        return ({"deadline_tick": dl}, st, {"action": "accept", "kind": "early", "left": left, "rival_surplus": rs})
    q = allocate([fake(3, 10, 100), fake(3, 30, 100), fake(3, 20, 100)], cfg, late=True)
    if [x[2]["action"] for x in q] != ["hold", "accept", "hold"]:
        bad.append("allocate: biggest surplus did not go first")
    q = allocate([fake(5, 30, 100), fake(5, 20, 100), fake(1, 5, 96)], cfg, late=True)
    if [x[2]["action"] for x in q] != ["hold", "hold", "accept"]:
        bad.append("allocate: the duel about to expire did not go first")
    q = allocate([fake(5, 30, 100), fake(5, 20, 100), fake(1, 5, 96)], cfg)
    if [x[2]["action"] for x in q] != (["hold"] * 3 if cfg.late_poll > 0 else ["hold", "hold", "accept"]):
        bad.append("allocate: --late-poll did not move the last tick's accept to the late read")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        lp = Path(tmp) / "duel.lock"
        for text, want in ((f"{time.time() + 60:.1f}\n", True), (f"{time.time() - 1:.1f}\n", False), ("x\n", False)):
            lp.write_text(text)
            if lock_fresh(lp) != want:
                bad.append(f"lock_fresh({text.strip()!r}) != {want}")
        if lock_fresh(Path(tmp) / "missing.lock"):
            bad.append("lock_fresh on a missing file")
    for b in bad[:5]:
        print("  FAIL", b)
    ok = not bad and not res["violations"] and res["max_sends"] <= cfg.max_msgs
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    main()
