"""Team 3's broker for our own venue: it matches the Market Test's bench offers better than the free stall does, and
crosses teams' public offers on our venue card by card, as the kit's starter broker does.

Where a broker can beat the stall. The free stall (kit/starter_broker.py, bench_plan) crosses, in every bench run and
every tick, the highest bid against the lowest ask while the bid covers it. A match must respect the quotes (ask <=
price, price + fee <= bid), so no broker can pair offers that do not cross; what it chooses is which crossing offers it
pairs, and when. The Market Test scores the gains between the TRUE limits. In tools/bench_sim.py the stall reaches
about 0.89 of the best possible gains and a clairvoyant quote-respecting broker about 0.96. The lab's verdict on that
gap: it is about timing, not limits. Knowing who leaves when, and pairing each trader at its last moment with its
best counterpart, is worth +3 to +4 points of efficiency; knowing the true limits as well adds under one more.
Guessing the departures from quote paths and a patience prior is noise at best and loses when the prior is wrong.

So the bench policy (pure: plan() never touches the network) is:
  1. Track every bench offer by id: side, first tick seen, quote path, and the expiry it shows, if the book shows one
     (EXPIRY_FIELDS; real team offers carry expires_tick).
  2. Blind (no expiries, or all equal, or not yet checked): the stall's exact rule. Our venue then earns exactly what
     the stall earns; nothing is risked on a guess.
  3. Expiries that tell traders apart AND that real departures have confirmed (TRUST_AFTER offers gone, none more than
     EXPIRY_TRUST_MAX ticks before the expiry it showed; a lie switches this off for the rest of the process):
     - a trader whose offer expires within the margin (learned from the departures seen; EXPIRY_MARGIN before) is
       leaving: it keeps its full estimated value; every other trader can wait (FUTURE_KNOWN = 1), so its priority is
       shrunk to the estimated clearing price;
     - estimated limits: a relaxed quote is extrapolated along a linear path whose slope ties each patience to one
       shading (priors below); an unmoved one is read as firm and shaded back by FIRM_SHADE;
     - among the pairs whose quotes cross NOW, the max-weight matching (exact, dynamic programming) on buyer priority
       minus seller priority, positive pairs only. With quotes as priorities this picks the same traders as the
       stall (zero-spread pairs aside: checked on 3,000 random books); with the priorities above it pairs the
       traders that are leaving with their best counterparts and holds the rest.
  4. Fallback: a run with no history yet, or any exception, uses the stall's rule for that run. A bug costs the edge,
     never the stall's half of the points.
  5. A guard checks every match before it is sent: two live offers of one bench run (or two public offers), a seller
     and a buyer, different makers on public offers (every bench offer shows maker "bench", so makers do not count
     there), each offer once, a whole price with ask <= price and price + fee <= bid.

Modes (from the repo root):
    python3 agent/broker.py plan --book FILE      # offline: the matches it would send for a recorded book (a JSON
                                                  # book, or a logs/broker/<date>.jsonl replayed state by state)
    python3 agent/broker.py selftest              # the simulator: stall vs ours on the standard and hard mixes
    python3 agent/broker.py run                   # live: our venue's book twice a second, matches sent on change
    python3 agent/broker.py run --policy stall    # live, but exactly the stall's rule (the safe fallback)
    python3 agent/broker.py watch                 # live and read-only: records the book, logs what it WOULD send

The broker key comes from the environment (BROKER_KEY) or from --key-file (default ~/.bazaar/broker.env, a line
BROKER_KEY=bk_...), written there by tools/open_venue.py. It is never printed or logged (runlog redacts bk_ keys too).
run writes a heartbeat to logs/state/desk-broker.json every loop and appends every changed book to
logs/broker/<date>.jsonl: the bench sessions recorded there are what we refit the priors on.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from bazaar_sdk import BazaarError, Broker  # noqa: E402
from runlog import LOGS, RunLog, redact  # noqa: E402

URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
KEY_FILE = Path.home() / ".bazaar" / "broker.env"
HEARTBEAT = LOGS / "state" / "desk-broker.json"

# ---------------------------------------------------------------- priors (refit after every real session)
# Defaults match tools/bench_sim.py's standard mix; the sweeps there test the policy with the truth far from them.
SMAX = 0.30             # largest shading share we expect (a buyer bids >= 70 % of its value at arrival)
FIRM_SHADE = 0.15       # a quote that never moved: firm, shaded by the mean of U(0, SMAX)
FIRST_SHADE = 0.10      # a quote seen once: firm or relaxing, we cannot tell yet
IMPATIENT_SHARE = 0.4   # patience prior: this share stays 2-5 ticks ...
IMPATIENT = (2, 5)
PATIENT = (8, 16)       # ... the rest 8-16 (a session is 16 ticks)
P_MAX = 16
FUTURE = 0.8            # share of a staying trader's surplus we expect it to earn later if we pass on it now
EXPIRY_FIELDS = ("expires_tick", "leaves_tick", "deadline_tick")  # a bench offer's last tick, if the book shows one
EXPIRY_MARGIN = 2       # a trader whose offer expires within this many ticks is treated as leaving now, until
                        # departures are seen; then the margin is (the earliest departure relative to its expiry) + 1:
                        # 0 when offers stay through their expiry tick, 1 when they are gone at it, 3 if 2 ticks early
EXPIRY_TRUST_MAX = 3    # an offer gone more than this many ticks before its expiry: expiries carry no timing at all
TRUST_AFTER = 3         # expiries steer the timing only after this many offers left the book close to their expiry
FUTURE_KNOWN = 1.0      # FUTURE when the run's offers show different expiries (who leaves when is then known)
BLIND = "stall"         # when expiries do not tell who leaves when: "stall" (its exact rule) or "policy" (estimates)
MIN_EDGE = 0.0          # a crossing pair is matched only if its buyer's priority beats its seller's by more than this
DP_MAX = 12             # exact matching up to this many offers on the smaller side, else the stall's rule

# ---------------------------------------------------------------- live loop
READ_EVERY = 0.5        # seconds between book reads (twice a second, as the starter)
CLOCK_EVERY = 1.0       # seconds between clock reads (the broker key allows 5 requests a second)
PENDING_TICKS = 2       # an offer we matched that still shows after this many ticks is planned again
REFUSED_TICKS = 1       # a refused pair is not sent again until this many ticks have passed
RUN_QUIET = 3           # a bench run is summarised in the log once none of its offers has shown for this many ticks
ALARM_TICKS = 2         # bench offers crossing this many ticks with nothing of the bench accepted: bench_alarm
ERROR_SLEEP = (0.5, 1, 2, 3, 5)  # seconds to wait after 1, 2, 3, ... read failures in a row (within a tick)
HTTP_TIMEOUT = 5.0      # seconds per request


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def run_of(offer_id) -> str:
    """The bench run of an offer id: "b12" in "b12-7". A match pairs two offers of one run."""
    return str(offer_id).split("-")[0]


def fee_of(book: dict, price: int) -> int:
    """The venue's fee on one card at `price`, rounded up, as the kit's public_plan computes it."""
    bps, per_card = book.get("fee_bps") or 0, book.get("fee_per_card") or 0
    return math.ceil(bps * price / 10000) + per_card


def price_for(book: dict, ask, bid):
    """The midpoint, lowered until the buyer can also pay the fee; None when no whole price fits [ask, bid - fee].
    Quotes that are not whole numbers are bounded to whole prices first (ask up, bid down)."""
    ask, bid = math.ceil(ask), math.floor(bid)
    for p in range((ask + bid) // 2, ask - 1, -1):
        if p + fee_of(book, p) <= bid:
            return p
    return None


# ---------------------------------------------------------------- the stall's rule (exactly kit bench_plan)

def bench_quotes(book: dict, skip=()) -> dict:
    """run -> (asks, bids), each a list of (quote, id) in book order. Malformed offers are skipped (bench_plan would
    raise on them); offers in `skip` (matched already, waiting to settle) too."""
    runs: dict = {}
    for o in book.get("bench_offers") or []:
        try:
            oid, want, give = o["id"], o["want"], o["give"]
            if oid in skip:
                continue
            asks, bids = runs.setdefault(str(oid).split("-")[0], ([], []))
            if want["cash"]:
                if _num(want["cash"]):
                    asks.append((want["cash"], oid))
            elif _num(give["cash"]):
                bids.append((give["cash"], oid))
        except (KeyError, TypeError, AttributeError):
            continue
    return runs


def stall_run(asks: list, bids: list, book: dict | None = None) -> list:
    """bench_plan for one run: highest bid against lowest ask while the bid covers it, at the midpoint. sorted() is
    stable, so among equal quotes the book's order decides, as in the stall. With `book`, the venue's fee counts too
    (the bid must cover price + fee, as for every match we send); at fee 0 that is the same plan."""
    plan = []
    for (ask, sell), (bid, buy) in zip(sorted(asks, key=lambda a: a[0]), sorted(bids, key=lambda b: -b[0])):
        if bid < ask:
            break
        price = (ask + bid) // 2 if book is None else price_for(book, ask, bid)
        if price is None:
            break
        plan.append((sell, buy, price))
    return plan


def stall_plan(book: dict, skip=(), fees: bool = False) -> list:
    """[(sell id, buy id, price)]: the free stall's rule over every bench run (fees=False: equal to kit bench_plan on
    any well-formed book, which tests/test_broker.py checks; fees=True: what our broker sends)."""
    plan = []
    for asks, bids in bench_quotes(book, skip).values():
        plan += stall_run(asks, bids, book if fees else None)
    return plan


# ---------------------------------------------------------------- estimates

def patience_prior(imp_share: float = IMPATIENT_SHARE, imp=IMPATIENT, pat=PATIENT, p_max: int = P_MAX) -> list:
    """prior[P] = chance a trader stays exactly P ticks (index 0 unused)."""
    prior = [0.0] * (p_max + 1)
    for (lo, hi), share in ((imp, imp_share), (pat, 1.0 - imp_share)):
        lo, hi = max(1, lo), min(p_max, hi)
        if hi >= lo:
            for p in range(lo, hi + 1):
                prior[p] += share / (hi - lo + 1)
    return prior


def hazard(prior: list, n: int) -> float:
    """Chance a trader seen for n ticks leaves after this one: P(P = n | P >= n)."""
    if n >= len(prior):
        return 1.0
    tail = sum(prior[n:])
    return prior[n] / tail if tail > 0 else 1.0


def estimate(side: str, quotes: list, tick: int, prior: list, smax: float = SMAX, firm_shade: float = FIRM_SHADE,
             first_shade: float = FIRST_SHADE) -> dict:
    """A trader's estimated true limit and its chance of leaving after `tick`, from its quote path.

    side "buy" (quotes are bids, below the value) or "sell" (asks, above the cost); quotes: [(tick, quote)] in tick
    order, the last one current. Returns limit, leave, kind (first | firm | relaxing | fast)."""
    t0, q0 = quotes[0]
    q = quotes[-1][1]
    n = tick - t0 + 1  # ticks it has been on the book, this one included
    sign = 1 if side == "buy" else -1
    if n <= 1 or len(quotes) < 2:
        return {"limit": q * (1 + sign * first_shade), "leave": hazard(prior, max(1, n)), "kind": "first"}
    age = tick - t0
    move = sign * (q - q0)
    if move <= 0:  # never relaxed (a quote moving away from its limit is read as firm too)
        return {"limit": q * (1 + sign * firm_shade), "leave": hazard(prior, n), "kind": "firm"}
    slope = move / age  # primas per tick toward the limit
    rho = slope / q0
    wsum = wleave = wlim = 0.0
    for p in range(max(n, 2), len(prior)):
        if prior[p] <= 0:
            continue
        k = rho * (p - 1)
        if side == "buy":
            s, jac = k / (1 + k), rho / (1 + k) ** 2
        else:
            if k >= 1:
                break
            s, jac = k / (1 - k), rho / (1 - k) ** 2
        if s > smax:
            break  # s grows with p: no longer patience fits the prior's shading
        w = prior[p] * jac
        wsum += w
        wlim += w * (q + sign * slope * (p - n))
        if p == n:
            wleave += w
    if wsum <= 0:  # relaxing faster than any shading the prior allows: it must be at its end
        return {"limit": q + sign * slope * 0.5, "leave": 0.8, "kind": "fast"}
    lim = wlim / wsum
    return {"limit": max(lim, q) if side == "buy" else min(lim, q), "leave": wleave / wsum, "kind": "relaxing"}


def clearing_price(values: list, costs: list):
    """The competitive price on estimated limits: buyers' values high to low against sellers' costs low to high."""
    b, s = sorted(values, reverse=True), sorted(costs)
    if not b or not s:
        return None
    k = 0
    while k < min(len(b), len(s)) and b[k] > s[k]:
        k += 1
    if k == 0:
        return (b[0] + s[0]) / 2
    lo = max(s[k - 1], b[k] if k < len(b) else -math.inf)
    hi = min(b[k - 1], s[k] if k < len(s) else math.inf)
    return (lo + hi) / 2


def best_matching(n_left: int, n_right: int, weight) -> list:
    """Exact max-weight matching on a small bipartite graph: weight(i, j) is a number or None (no edge). Dynamic
    programming over subsets of the right side; ties keep the first matching found (deterministic)."""
    dp = {0: (0.0, ())}
    for i in range(n_left):
        nxt = dict(dp)
        for mask, (v, pairs) in dp.items():
            for j in range(n_right):
                if mask >> j & 1:
                    continue
                w = weight(i, j)
                if w is None:
                    continue
                m2, v2 = mask | 1 << j, v + w
                if m2 not in nxt or v2 > nxt[m2][0] + 1e-9:
                    nxt[m2] = (v2, pairs + ((i, j),))
        dp = nxt
    return list(max(dp.values(), key=lambda x: x[0])[1])


# ---------------------------------------------------------------- tracker and policy

class Tracker:
    """Every bench offer we have seen: run, side, quote path (one quote per tick, the last read of the tick wins),
    first and last tick, and how it ended (matched by us, or gone: left, or taken elsewhere)."""

    def __init__(self):
        self.traders: dict = {}  # offer id -> trader
        self.ended: list = []    # traders that left the book, for the session log
        self.early = None        # most ticks an offer left the book before the expiry it showed (-1: one tick
                                 # after it, as when the expiry is the last tick on the book); None: none left yet
        self.departed = 0        # offers that left the book (not matched by us) while showing an expiry

    def observe(self, book: dict, tick: int, ours=()) -> None:
        seen = set()
        for o in book.get("bench_offers") or []:
            try:  # read as bench_quotes reads it: a seller needs only want.cash, a buyer give.cash
                oid = o["id"]
                ask = o["want"]["cash"]
                side, q = ("sell", ask) if ask else ("buy", o["give"]["cash"])
            except (KeyError, TypeError):
                continue
            if not _num(q):
                continue
            seen.add(oid)
            tr = self.traders.get(oid)
            if tr is None or tr["side"] != side:
                tr = self.traders[oid] = {"id": oid, "run": run_of(oid), "side": side, "maker": o.get("maker"),
                                          "first": tick, "last": tick, "quotes": [], "end": None, "expires": None}
            exp = next((o[k] for k in EXPIRY_FIELDS if _num(o.get(k))), None)
            if exp is not None:
                tr["expires"] = exp
            if tr["quotes"] and tr["quotes"][-1][0] == tick:
                tr["quotes"][-1] = (tick, q)
            elif not tr["quotes"] or tick > tr["quotes"][-1][0]:
                tr["quotes"].append((tick, q))
            tr["last"], tr["end"] = tick, None
        for oid, tr in self.traders.items():
            if oid not in seen and tr["end"] is None:
                tr["end"] = "matched" if oid in ours else "gone"
                tr["gone_tick"] = tick
                self.ended.append(tr)
                if tr["end"] == "gone" and tr.get("expires") is not None:
                    self.departed += 1
                    e = tr["expires"] - tick
                    self.early = e if self.early is None else max(self.early, e)

    def run_done(self, run: str, tick, quiet: int = RUN_QUIET) -> bool:
        """Every offer of the run has left the book, the last one at least `quiet` ticks ago."""
        trs = [tr for tr in self.traders.values() if tr["run"] == run]
        if not trs or any(tr["end"] is None for tr in trs):
            return False
        return tick is None or tick - max(tr.get("gone_tick", tick) for tr in trs) >= quiet


class BenchPolicy:
    """Our bench policy, one object per broker process (it keeps the quote paths). plan() is pure apart from that
    memory: no network, no clock."""

    def __init__(self, params: dict | None = None):
        p = {"smax": SMAX, "firm_shade": FIRM_SHADE, "first_shade": FIRST_SHADE, "imp_share": IMPATIENT_SHARE,
             "imp": IMPATIENT, "pat": PATIENT, "future": FUTURE, "future_known": FUTURE_KNOWN,
             "expiry_margin": EXPIRY_MARGIN, "use_expiry": True, "trust_after": TRUST_AFTER,
             "trust_max": EXPIRY_TRUST_MAX, "blind": BLIND, "min_edge": MIN_EDGE}
        p.update(params or {})
        self.p = p
        self.prior = patience_prior(p["imp_share"], tuple(p["imp"]), tuple(p["pat"]))
        self.tracker = Tracker()
        self.pending: dict = {}  # offer id -> tick we matched it (settling)
        self.refused: dict = {}  # (sell, buy) -> tick the server refused it
        self.notes: dict = {}    # run -> how this tick's plan was made (for the log)

    # -- what the live loop tells us back
    def sent(self, sell, buy, tick: int) -> None:
        self.pending[sell] = self.pending[buy] = tick

    def refused_pair(self, sell, buy, tick: int) -> None:
        self.refused[(sell, buy)] = tick

    def _skip(self, tick: int) -> set:
        for oid, t in list(self.pending.items()):
            if tick - t > PENDING_TICKS:
                del self.pending[oid]  # still on the book long after our match: plan it again
        for k, t in list(self.refused.items()):
            if tick - t >= REFUSED_TICKS:
                del self.refused[k]
        return set(self.pending)

    def estimate(self, tr: dict, tick: int, known: bool = False) -> dict:
        """estimate() from the quote path, corrected by the offer's expiry when the book shows one: due now means
        leaving; when the run's expiries differ (known), a later one means staying."""
        p = self.p
        e = estimate(tr["side"], tr["quotes"], tick, self.prior, p["smax"], p["firm_shade"], p["first_shade"])
        if p["use_expiry"] and tr.get("expires") is not None:
            early = self.tracker.early
            margin = p["expiry_margin"] if early is None else max(0, early + 1)  # learned from real departures
            if tr["expires"] - tick <= margin:
                e["leave"] = 1.0
            elif known:
                e["leave"] = 0.0
        return e

    def plan(self, book: dict, tick: int) -> list:
        """[(sell id, buy id, price)] for every bench run in `book` at `tick`."""
        self.tracker.observe(book, tick, ours=self.pending)
        skip = self._skip(tick)
        out, self.notes = [], {}
        for run, (asks, bids) in bench_quotes(book, skip).items():
            try:
                plan, why = self._plan_run(book, asks, bids, tick)
            except Exception as e:  # never worse than the stall because of a bug
                plan, why = stall_run(asks, bids, book), f"fallback:{type(e).__name__}"
            out += plan
            self.notes[run] = why
        return out

    def _plan_run(self, book: dict, asks: list, bids: list, tick: int):
        trs = self.tracker.traders
        if not asks or not bids:
            return [], "one_side"
        if not any(len(trs[oid]["quotes"]) >= 2 for _, oid in asks + bids if oid in trs):
            return stall_run(asks, bids, book), "stall:no_history"
        p = self.p
        exps = {trs[oid].get("expires") for _, oid in asks + bids}
        known = (p["use_expiry"] and None not in exps and len(exps) > 1  # expiries that tell traders apart ...
                 and self.tracker.departed >= p["trust_after"] and (self.tracker.early or 0) <= p["trust_max"])
        # and have been checked against real departures (and did not lie by much)
        if not known and p["blind"] == "stall":
            return stall_run(asks, bids, book), "stall:blind"
        future = p["future_known"] if known else p["future"]
        est = {oid: self.estimate(trs[oid], tick, known) for _, oid in asks + bids}
        price = clearing_price([est[o]["limit"] for _, o in bids], [est[o]["limit"] for _, o in asks])

        def prio(oid, side) -> float:  # buyers: higher is better; sellers: an effective cost, lower is better
            e = est[oid]
            stay = (1.0 - e["leave"]) * future
            if side == "buy":
                return e["limit"] - stay * max(0.0, e["limit"] - price)
            return e["limit"] + stay * max(0.0, price - e["limit"])

        bp = {oid: prio(oid, "buy") for _, oid in bids}
        sp = {oid: prio(oid, "sell") for _, oid in asks}
        left, right = list(bids), list(asks)
        swap = len(right) > len(left)
        if swap:
            left, right = right, left
        if len(right) > DP_MAX:
            return stall_run(asks, bids, book), "stall:too_big"

        def edge(i, j):  # a pair is worth its buyer's priority minus its seller's effective cost
            (qb, b), (qs, s) = (left[i], right[j]) if not swap else (right[j], left[i])
            if qb < qs or price_for(book, qs, qb) is None or (s, b) in self.refused:
                return None
            w = bp[b] - sp[s]
            return w if w > p["min_edge"] else None

        plan = []
        for i, j in best_matching(len(left), len(right), edge):
            (qb, b), (qs, s) = (left[i], right[j]) if not swap else (right[j], left[i])
            plan.append((s, b, price_for(book, qs, qb)))
        return plan, "policy:expiry" if known else "policy"


# ---------------------------------------------------------------- public offers and the guard

def public_matches(book: dict) -> list:
    """Teams' real offers on our venue, card by card, exactly as the kit's starter broker does."""
    from starter_broker import public_plan
    return public_plan(book)


def guard(plan: list, book: dict) -> tuple:
    """(matches to send, [(match, reason)] dropped). Every rule a match must meet before it leaves the machine."""
    offers = {}
    for kind in ("bench_offers", "offers"):
        for o in book.get(kind) or []:
            if isinstance(o, dict) and "id" in o:
                offers[o["id"]] = (kind, o)
    used, ok, bad = set(), [], []
    for m in plan:
        try:
            sell, buy, price = m
            if sell not in offers or buy not in offers:
                raise ValueError("unknown_offer")
            (ks, s), (kb, b) = offers[sell], offers[buy]
            if ks != kb:
                raise ValueError("bench_with_public")
            if sell in used or buy in used or sell == buy:
                raise ValueError("offer_reused")
            if ks == "bench_offers" and run_of(sell) != run_of(buy):
                raise ValueError("different_runs")
            ask, bid = s["want"]["cash"], b["give"]["cash"]
            if not (_num(ask) and ask > 0 and _num(bid) and bid > 0) or s["give"].get("cash") or b["want"].get("cash"):
                raise ValueError("not_a_seller_and_a_buyer")
            if ks == "offers" and s.get("maker") is not None and s.get("maker") == b.get("maker"):
                raise ValueError("same_maker")  # public offers only: every bench offer's maker is "bench"
            if isinstance(price, bool) or not isinstance(price, int):
                raise ValueError("price_not_whole")
            if price < ask or price + fee_of(book, price) > bid:
                raise ValueError("price_outside_quotes")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            bad.append((m, str(e) if isinstance(e, ValueError) else f"malformed:{type(e).__name__}"))
            continue
        used.update((sell, buy))
        ok.append((sell, buy, price))
    return ok, bad


def stall_rule_plan(book: dict, skip=(), refused=None) -> list:
    """The stall's rule within each bench run (stall_plan with the venue's fee), pairs in `refused` left out. What
    the safety net sends and what the alarm looks for. A run's pairs never mix with another run's."""
    return [m for m in stall_plan(book, skip, fees=True) if (m[0], m[1]) not in (refused or {})]


def safety_net(book: dict, ok: list, bad: list, skip=(), refused=None) -> list:
    """The Market Test must never score 0 because of our own checks. Saturday 11:50: the guard dropped all 15 bench
    pairs as "same_maker" (every bench offer's maker is "bench"), the session counted 0 and the market fell by 1.9.
    So when the guard dropped bench matches and let none through, the stall's rule (per run, fee counted) is sent as
    it is: the server checks every match itself and a refused one costs nothing (refused pairs are not sent again,
    as everywhere else). A policy that chose to wait sends nothing and drops nothing: the net stays off."""
    bench_ids = {o.get("id") for o in book.get("bench_offers") or [] if isinstance(o, dict)}
    if not bench_ids or any(m[0] in bench_ids for m in ok):
        return []
    if not any(isinstance(m, (list, tuple)) and m and m[0] in bench_ids for m, _ in bad):
        return []
    used = {x for m in ok for x in m[:2]}
    return stall_rule_plan(book, set(skip) | used, refused)


def plan_book(book: dict, tick: int, policy: BenchPolicy | None, refused: dict | None = None,
              skip=()) -> tuple:
    """Everything we would send for one state of the book: (matches, dropped, notes). policy None = the stall's
    rule. refused: pairs not to send again yet; skip: offers we matched already (still settling)."""
    notes = {}
    skip = set(skip)
    try:
        bench = policy.plan(book, tick) if policy is not None else stall_plan(book, skip, fees=True)
        notes = dict(policy.notes) if policy is not None else {"*": "stall"}
    except Exception as e:  # the policy object itself broke: the stall's rule for the whole book
        bench, notes = stall_plan(book, skip, fees=True), {"*": f"fallback:{type(e).__name__}"}
    try:
        public = public_matches(book)
    except Exception as e:
        public, notes["public"] = [], f"error:{type(e).__name__}"
    plan = [m for m in bench + public
            if (m[0], m[1]) not in (refused or {}) and m[0] not in skip and m[1] not in skip]
    ok, bad = guard(plan, book)
    net = safety_net(book, ok, bad, skip, refused)
    if net:
        notes["safety_net"] = len(net)
        ok = ok + net
    return ok, bad, notes


# ---------------------------------------------------------------- live loop

def load_broker_key(key_file: Path) -> str:
    """BROKER_KEY from the environment, else the key file. The key is returned, never printed."""
    key = os.environ.get("BROKER_KEY", "").strip()
    if key:
        return key
    try:
        for line in Path(key_file).expanduser().read_text().splitlines():
            if line.strip().startswith("BROKER_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise SystemExit(f"no broker key: set BROKER_KEY or write BROKER_KEY=... to {key_file} (tools/open_venue.py run)")


def book_state(book: dict, tick) -> tuple:
    """What a plan depends on: the tick and every offer's id and prices. Planning once per state means a refused
    match is not sent again every half second."""
    def sig(o):
        if not isinstance(o, dict):
            return (str(o)[:40],)
        g, w = o.get("give") or {}, o.get("want") or {}
        return (str(o.get("id")), str(g.get("cash")), str(w.get("cash")), str(o.get("status")))
    return (tick, tuple(sig(o) for o in book.get("bench_offers") or []),
            tuple(sig(o) for o in book.get("offers") or []))


class ReadOnlyBroker(Broker):
    """watch mode: a Broker that refuses every request except GET before it leaves the machine."""

    def _call(self, method, path, body=None, query=None):
        if method != "GET":
            raise BazaarError("read_only", f"watch mode refused {method} {path}", 0)
        return super()._call(method, path, body, query)


class Desk:
    """One broker process. step() is one loop: read, plan when the book changed, send, log, heartbeat. The client
    only needs book(), clock() and match(): tests drive it with a fake one. send=False (watch) plans and logs what
    it WOULD send, and sends nothing."""

    def __init__(self, client, log, policy_name: str = "ours", now=time.time, heartbeat: Path = HEARTBEAT,
                 send: bool = True):
        self.c, self.log, self.now, self.heartbeat = client, log, now, heartbeat
        self.send_on, self.mode = send, "run" if send else "watch"
        self.policy_name = policy_name
        self.policy = BenchPolicy() if policy_name == "ours" else None
        self.tracker = self.policy.tracker if self.policy is not None else Tracker()  # quote paths for the log
        self.restore()
        self.state = None
        self.tick = None
        self.last_clock = 0.0
        self.errors = 0
        self.reads = 0
        self.unlogged = 0
        self.refused: dict = {}  # (sell, buy) -> tick refused, for every match (bench and public)
        self.pending: dict = {}  # offer id -> tick we matched it: not planned again while it settles
        self.last_decision: dict = {}
        self.counts = {"sent": 0, "accepted": 0, "refused": 0, "dropped": 0}
        self.runs_logged: dict = {}  # bench run -> traders already summarised in the log
        self.idle_since = None       # first tick bench offers crossed and nothing of the bench was accepted
        self.alarm = None            # that tick, once the idle stretch reached ALARM_TICKS (heartbeat + one log line)

    def step(self) -> float:
        """One loop; returns how long to sleep before the next."""
        t = self.now()
        try:
            if self.tick is None or t - self.last_clock >= CLOCK_EVERY:
                clock = self.c.clock()
                self.tick, self.last_clock = clock.get("tick"), t
            book = self.c.book()
            self.reads += 1
            self.errors = 0
        except Exception as e:  # BazaarError (the server restarting, say) or anything else: keep going
            self.errors += 1
            self.log.event("read_error", error=f"{type(e).__name__}: {e}"[:200], in_a_row=self.errors)
            self.beat("read_error")
            return ERROR_SLEEP[min(self.errors, len(ERROR_SLEEP)) - 1]
        if not isinstance(book, dict):
            self.log.event("bad_book", kind=type(book).__name__)
            self.beat("bad_book")
            return READ_EVERY
        tick = book.get("tick") if _num(book.get("tick")) else self.tick
        state = book_state(book, tick)
        if state != self.state and not _num(book.get("tick")) and self.now() - self.last_clock > 0.2:
            try:  # the book changed and carries no tick: make sure the change is not filed under the old tick
                self.tick, self.last_clock = self.c.clock().get("tick"), self.now()
                tick = self.tick
                state = book_state(book, tick)
            except Exception as e:
                self.log.event("read_error", where="clock", error=f"{type(e).__name__}: {e}"[:200])
        if state == self.state:
            self.unlogged += 1
            self.beat("same_book")
            return READ_EVERY
        self.state = state
        self.record(book, tick)
        self.refused = {k: v for k, v in self.refused.items() if tick is None or v is None or tick - v < REFUSED_TICKS}
        self.pending = {k: v for k, v in self.pending.items() if tick is None or v is None or tick - v <= PENDING_TICKS}
        matches, dropped, notes = plan_book(book, tick if tick is not None else 0, self.policy, self.refused,
                                            self.pending)
        if self.policy is None:  # the stall's rule keeps no paths: track them here, for the log
            self.tracker.observe(book, tick if tick is not None else 0, ours=self.pending)
        for m, why in dropped:
            self.counts["dropped"] += 1
            self.log.event("dropped", tick=tick, match=list(m), why=why)
        if notes.get("safety_net"):
            self.log.event("safety_net", tick=tick, matches=[list(m) for m in matches], dropped=len(dropped))
        bench_ids = {o.get("id") for o in book.get("bench_offers") or [] if isinstance(o, dict)}
        bench_accepted = False
        for sell, buy, price in matches:
            if self.send(sell, buy, price, tick) and sell in bench_ids:
                bench_accepted = True
        self.watch_bench(book, tick, bench_accepted)
        self.last_decision = {"tick": tick, "matches": [list(m) for m in matches], "notes": notes,
                              "dropped": len(dropped)}
        self.end_runs(tick)
        self.beat("planned")
        return READ_EVERY

    def watch_bench(self, book: dict, tick, bench_accepted: bool) -> None:
        """Alarm when bench offers have crossed for ALARM_TICKS ticks and nothing of the bench was accepted: whatever
        the cause (a guard, refusals, a policy waiting too long), the session is slipping. Heartbeat field
        bench_alarm = the tick it started; one log line per stretch. Check it before each session."""
        if tick is None:
            return
        try:
            crossing = bool(stall_rule_plan(book, self.pending))
        except Exception:  # never let the alarm cost the loop its heartbeat
            crossing = False
        if bench_accepted or not crossing:
            self.idle_since = self.alarm = None
            return
        if self.idle_since is None:
            self.idle_since = tick
        if self.alarm is None and tick - self.idle_since >= ALARM_TICKS:
            self.alarm = self.idle_since
            self.log.event("bench_alarm", tick=tick, since=self.idle_since,
                           crossing=[list(m) for m in stall_rule_plan(book, self.pending)][:5])

    def send(self, sell, buy, price, tick) -> bool:
        """Send one match; True when the venue accepted it (watch mode: never)."""
        if not self.send_on:
            self.log.event("WOULD", tick=tick, sell=sell, buy=buy, price=price)
            return False
        self.counts["sent"] += 1
        try:
            r = self.c.match(sell, buy, price)
        except BazaarError as e:  # taken since the read, a shape the venue cannot cross, ...: not retried this tick
            self.counts["refused"] += 1
            self.refused[(sell, buy)] = tick
            if self.policy is not None:
                self.policy.refused_pair(sell, buy, tick if tick is not None else 0)
            self.log.event("refused", tick=tick, sell=sell, buy=buy, price=price, code=e.code,
                           msg=(e.message or "")[:200], status=e.status)
            return False
        except Exception as e:
            self.counts["refused"] += 1
            self.refused[(sell, buy)] = tick
            self.log.event("send_error", tick=tick, sell=sell, buy=buy, price=price, error=f"{type(e).__name__}"[:80])
            return False
        self.counts["accepted"] += 1
        self.pending[sell] = self.pending[buy] = tick
        if self.policy is not None:
            self.policy.sent(sell, buy, tick if tick is not None else 0)
        self.log.event("matched", tick=tick, sell=sell, buy=buy, price=price,
                       result={k: v for k, v in (r or {}).items() if k in ("id", "status", "price", "tick", "settles")})
        return True

    def record(self, book: dict, tick) -> None:
        """Every changed book, appended without printing (the training data for the next refit)."""
        row = redact({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": getattr(self.log, "run_id", None),
                      "agent": "broker", "event": "book", "tick": tick, "same_reads_before": self.unlogged,
                      "book": book})
        self.unlogged = 0
        path = getattr(self.log, "path", None)
        if path is None:
            return
        try:
            with open(path, "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"cannot append the book ({e})", flush=True)

    def end_runs(self, tick) -> None:
        """When a bench run has left the book, log every trader's path and how it ended (refit data). A run that
        gets new traders after its summary is summarised again."""
        tr = self.tracker
        for run in {t["run"] for t in tr.traders.values()}:
            rows = [{"id": t["id"], "side": t["side"], "first": t["first"], "last": t["last"], "end": t["end"],
                     "gone": t.get("gone_tick"), "expires": t.get("expires"), "quotes": t["quotes"]}
                    for t in tr.traders.values() if t["run"] == run]
            if len(rows) > self.runs_logged.get(run, 0) and tr.run_done(run, tick):
                self.runs_logged[run] = len(rows)
                self.log.event("bench_run_end", tick=tick, bench_run=run, traders=rows,
                               matched=sum(1 for r in rows if r["end"] == "matched") // 2)

    def restore(self) -> None:
        """What an earlier process learned today about expiries (a supervised restart must not start blind)."""
        try:
            hb = json.loads(self.heartbeat.read_text())
            learned = hb.get("learned") or {}
            if learned.get("day") == time.strftime("%Y-%m-%d") and isinstance(learned.get("departed"), int):
                self.tracker.departed = learned["departed"]
                if learned.get("early") is None or isinstance(learned.get("early"), int):
                    self.tracker.early = learned.get("early")
        except (OSError, ValueError, AttributeError):
            pass

    def beat(self, what: str) -> None:
        hb = {"agent": "broker", "mode": self.mode, "policy": self.policy_name, "pid": os.getpid(), "tick": self.tick,
              "what": what, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "epoch": round(self.now(), 1),
              "reads": self.reads, "read_errors_in_a_row": self.errors, "last_decision": self.last_decision,
              "bench_alarm": self.alarm,
              "learned": {"day": time.strftime("%Y-%m-%d"), "departed": self.tracker.departed,
                          "early": self.tracker.early},
              **self.counts}
        try:
            self.heartbeat.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.heartbeat.with_suffix(".tmp")
            tmp.write_text(json.dumps(redact(hb), ensure_ascii=False) + "\n")
            os.replace(tmp, self.heartbeat)
        except OSError:
            pass


def cmd_run(args) -> None:
    key = load_broker_key(Path(args.key_file))
    watch = args.mode == "watch"
    # short timeout, one retry: a hung read must not cost a whole 30 s tick (the loop reads again in half a second)
    broker = (ReadOnlyBroker if watch else Broker)(URL, key, timeout=HTTP_TIMEOUT, retries=1)
    log = RunLog("broker")
    log.start(mode=args.mode, policy=args.policy, url=URL)
    desk = Desk(broker, log, args.policy, send=not watch)
    print(f"broker {args.mode} ({args.policy}); heartbeat {HEARTBEAT}, log {log.path}. Ctrl-C to stop.", flush=True)
    try:
        while True:
            try:
                wait = desk.step()
            except Exception as e:  # unattended: log it and keep the loop alive
                tb = traceback.extract_tb(e.__traceback__)[-1]
                log.event("error", where=f"step:{tb.lineno}", error=f"{type(e).__name__}: {e}"[:300])
                wait = 2.0
            time.sleep(wait)
    except KeyboardInterrupt:
        log.end(**desk.counts)


# ---------------------------------------------------------------- offline modes

def read_books(path: Path) -> list:
    """[(tick, book)] from a book JSON, or from a JSONL of rows with a "book" (logs/broker/<date>.jsonl)."""
    text = Path(path).read_text()
    try:
        one = json.loads(text)
        if isinstance(one, dict):
            return [(one.get("tick") if _num(one.get("tick")) else 0, one.get("book", one))]
    except ValueError:
        pass
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("book"), dict):
            t = row.get("tick")
            out.append((t if _num(t) else row["book"].get("tick", 0), row["book"]))
    return out


def cmd_plan(args) -> None:
    books = read_books(Path(args.book))
    if not books:
        raise SystemExit(f"{args.book}: no book found")
    policy = BenchPolicy() if args.policy == "ours" else None
    for tick, book in books:
        tick = args.tick if args.tick is not None else (tick or 0)
        ok, bad, notes = plan_book(book, tick, policy)
        stall = stall_plan(book, skip=set(policy.pending) if policy else ())
        if not ok and not bad and not args.all:
            continue
        print(f"tick {tick}: {len(book.get('bench_offers') or [])} bench offers, {len(book.get('offers') or [])} "
              f"public; plan {notes}")
        for sell, buy, price in ok:
            print(f"  match sell={sell} buy={buy} price={price}")
        for m, why in bad:
            print(f"  DROPPED {m}: {why}")
        if policy is not None and sorted(stall) != sorted(m for m in ok if str(m[0])[:1] == "b"):
            print(f"  (the stall would send: {stall})")
        if policy is not None:  # replay: what we would have sent counts as matched in the next state
            for sell, buy, _ in ok:
                policy.sent(sell, buy, tick)


def cmd_selftest(args) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import bench_sim
    scen = "standard,hard,expiry_exact,hard_expiry_exact,expiry_early4,adversarial"  # blind, then expiries shown
    rc = bench_sim.main(["table", "--seeds", str(args.seeds), "--scenarios", scen, "--procs",
                         str(args.procs)])
    raise SystemExit(rc)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("plan", help="offline: the matches for a recorded book")
    p.add_argument("--book", required=True, help="a book JSON, or logs/broker/<date>.jsonl to replay")
    p.add_argument("--tick", type=int, default=None, help="override the tick (single book)")
    p.add_argument("--policy", choices=("ours", "stall"), default="ours")
    p.add_argument("--all", action="store_true", help="also print states with nothing to match")
    s = sub.add_parser("selftest", help="simulate: stall vs ours (tools/bench_sim.py)")
    s.add_argument("--seeds", type=int, default=400)
    s.add_argument("--procs", type=int, default=1)
    for mode, what in (("run", "live loop on our venue: reads, plans and sends matches (needs the broker key)"),
                       ("watch", "live, read-only: reads and records the book, logs what it WOULD match, sends nothing "
                                 "(works with the free stall's key too)")):
        r = sub.add_parser(mode, help=what)
        r.add_argument("--key-file", default=str(KEY_FILE))
        r.add_argument("--policy", choices=("ours", "stall"), default="ours")
    args = ap.parse_args(argv)
    {"plan": cmd_plan, "selftest": cmd_selftest, "run": cmd_run, "watch": cmd_run}[args.mode](args)


if __name__ == "__main__":
    main()
