"""Duel negotiator: the scheduled 1v1 sessions (Duels I price only; Duels II/III/Final price + delivery days).

Numbers are decided here, in code; the words are decoration. Rival text is untrusted and never parsed: only the
structured `rival_offer` (price, and days in two-issue sessions) is read.

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
  - messages: [{"tick": 122, "from": "Rival Sol", "text": "...", "price": 102, "days": null}, ...]
  - `rounds` stayed 0 while rivals posted up to 8 messages and we were silent.
  - Our own message = one round of decay (measured 2026-10-02, duel 37): one message from us at tick 140 moved
    `rounds` from 0 to 1 at once. Listening, waiting and accepting are free; every send costs a decay step.

Strategy (all constants overridable from the command line):
  - Our numbers go out on a clock, not in reply to the rival, and never more than MAX_MSGS (3) per duel:
    the anchor after OPEN_WAIT ticks of free listening, the floor when the floor zone starts (last FLOOR_FRAC of
    the clock), and a last-chance number when LAST_CHANCE_TICKS remain. Seller asks cost x R, buyer bids
    value / R (R = 1.55 anchor, 1.22 floor, 1.08 last chance), so both roles are symmetric. An unchanged number
    is never resent.
  - Accept bar: the surplus of where the clock says our number should be (falling from anchor to floor, since
    patience is free) less one round of decay; and before any send we accept instead if the rival already beats
    the number we were about to send, less the round that sending would cost.
  - Last ACCEPT_ANY_TICKS ticks: accept anything strictly inside our limit (a sliver of share beats zero).
  - Never offer or accept across our limit (hard clamp, rounding always away from the limit).
  - One accept per team per tick: the most urgent (fewest ticks left, then biggest surplus) goes first; the
    others hold and are re-checked next tick. The duel is re-read just before accepting (offer id must match).
  - Two issues: utility = price surplus minus our days cost. Delivery is linear in days, so we offer an extreme
    day. If days are cheap for us (10 x weight <= DAYS_CHEAP x limit) we give the rival the day they seem to want
    and ask the days cost back in price, plus a premium that shrinks as we concede. If days are dear to us, we
    hold our best day and concede on price.
  - --mirror (off by default, unverified): read the rival's limit from the paired duel and ask for a share of the
    known pie (75% anchor, 55% floor, 30% last chance); hold silent when that pie is empty.

Usage (from the repo root):
    python3 agent/duel.py watch                 # read-only: prints what it WOULD send, sends nothing
    python3 agent/duel.py run                   # negotiates every live duel, one action per duel per tick
    python3 agent/duel.py watch --log-dir /tmp/x --until 22:58
    python3 agent/duel.py run --until 12:30     # Saturday Duels I: start before game hour 6.5, stop by wall time
Stops at --until, or after --idle-ticks (default 40) ticks with no live duel once it has seen one.
Only ONE process per team may run `run` (the server allows one message per duel per tick, one accept per tick).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402
from runlog import LOGS, RunLog, redact, write_json  # noqa: E402

# ---------------------------------------------------------------- strategy constants (CLI-overridable)

RATIOS = [1.55, 1.22]               # seller ask = cost x R, buyer bid = value / R: anchor, then floor
LAST_R = 1.08                       # last-chance offer, sent when LAST_CHANCE_TICKS remain
MAX_MSGS = 3                        # hard cap on our messages per duel: each one costs a round of decay
LAST_CHANCE_TICKS = 2               # ticks left when the last-chance offer goes out (rival still has time to accept)
ACCEPT_ANY_TICKS = 2                # in the last N ticks accept any offer strictly inside our limit
MIN_SURPLUS = 1                     # primas; an offer worth less than this to us is never accepted
MIRROR_SHARES = [0.75, 0.55]        # --mirror only: share of the known pie we ask for: anchor, then floor
MIRROR_LAST_SHARE = 0.30            # --mirror only: last-chance share
DAYS_CHEAP = 0.10                   # days are "cheap" for us when 10 x weight <= DAYS_CHEAP x limit
DAYS_PREMIUM = [0.8, 0.25]          # extra price asked on top of our days cost: anchor, then floor
FLOOR_FRAC = 0.35                   # in the last 35% of the clock our number is the floor, whatever the rival did
OPEN_WAIT = 2                       # ticks we listen before anchoring (listening is free; the rival may open/concede)
DEFAULT_DUEL_TICKS = 16             # Duels I/II (practice 12, Duels III/Final 12). Used for the floor zone
POST_GAP = 0.25                     # seconds between POSTs (5 req/s per key)

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


def days_profile(d: dict, override: str = "auto") -> tuple[int, float]:
    """(our best delivery day, primas we lose per day away from it). Linear in days.

    The sign convention was not visible on Friday (price-only practice). Order of evidence:
    --days-best override, a negative weight (flips the role default), keywords in `days_meaning`, role default
    (buyer wants it early, seller wants it late). `days_meaning` is logged raw on first sight so a human can set
    --days-best before a scored session if this guess is wrong.
    """
    w = d.get("your_days_weight")
    try:
        w = float(w) if w is not None else 0.0
    except (TypeError, ValueError):
        w = 0.0
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
        best = 0
    elif early_bad and not late_bad:
        best = 10
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


# ---------------------------------------------------------------- our numbers

def price_at(d: dict, r: float) -> int:
    """Price for ratio r, rounded away from our limit so int conversion never crosses it."""
    lim = d["your_limit"]
    if d["role"] == "seller":
        return max(lim + 1, int(math.ceil(lim * r)))
    return min(lim - 1, int(math.floor(lim / r)))


def mirror_limit(d: dict, every: list) -> int | None:
    """The rival's limit IF the mirror hypothesis holds (unverified, Friday practice).

    Duels come in pairs with consecutive ids (odd, odd+1): same item, same session, roles swapped, and the rules
    say both are played "on the same scenarios". If so, the rival's value when we sell is our value in the
    partner duel where we buy, and the rival's cost when we buy is our cost in the partner duel where we sell.
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
                  rival_limit: int | None = None) -> tuple[int, int | None]:
    """Our (price, days) at a position on the schedule (0 = anchor, top = floor; fractions interpolate).
    Price-only duels return days=None."""
    r = cfg.last_r if last else _interp(cfg.ratios, pos, geometric=True)
    base = price_at(d, r)
    pie = mirror_pie(d, rival_limit)
    if pie is not None and pie >= 2 and not two_issues(d):
        # --mirror: ask for a share of the known pie instead of a ratio (never beyond the rival's limit)
        top = max(1, len(cfg.ratios) - 1)
        share = MIRROR_LAST_SHARE if last else _interp(MIRROR_SHARES, pos * (len(MIRROR_SHARES) - 1) / top)
        lim = d["your_limit"]
        if d["role"] == "seller":
            return max(lim + 1, int(math.ceil(lim + share * pie))), None
        return min(lim - 1, int(math.floor(lim - share * pie))), None
    if not two_issues(d):
        return base, None
    best, w = days_profile(d, cfg.days_best)
    far = 10 - best                                 # the day we assume the rival wants
    if rival and rival[1] is not None and rival[1] != best:
        far = rival[1]                              # they told us, in structure, which day they want
    cheap = 10 * w <= cfg.days_cheap * d["your_limit"]
    if not cheap or far == best:
        return base, best
    top = max(1, len(cfg.ratios) - 1)
    prem = cfg.days_premium[-1] if last else _interp(cfg.days_premium, pos * (len(cfg.days_premium) - 1) / top)
    extra = int(math.ceil(w * abs(far - best) * (1 + prem)))   # our days cost, plus a share of their gain
    p = base + extra if d["role"] == "seller" else base - extra
    if not inside_limit(d, p) or surplus(d, p, far, cfg.days_best) < MIN_SURPLUS:
        return base, best
    return p, far


# ---------------------------------------------------------------- one decision per duel per tick

class DuelState:
    def __init__(self, d: dict, tick: int, duel_ticks: int):
        self.id = d["duel"]
        # a duel lasts duel_ticks; joining mid-way we only know the deadline, so never assume it is shorter
        self.total = max(1, duel_ticks, d["deadline_tick"] - tick)
        self.start = d["deadline_tick"] - self.total
        self.step = -1              # schedule index of the number we last sent (-1: none yet)
        self.sent = 0               # messages we have sent in this duel (each one = one round of decay)
        self.last_sent: tuple | None = None
        self.last_sent_tick: int | None = None
        self.rival_id_at_send = None
        self.accepted_at: int | None = None
        self.dumped = False
        self.last_rival = None
        self.rival_limit: int | None = None   # set only with --mirror


def offer_id(raw):
    """The rival offer's identity: its id when the server gives one, else its numbers."""
    return raw.get("id") if isinstance(raw, dict) and raw.get("id") is not None else parse_offer(raw)


def decide(d: dict, st: DuelState, tick: int, cfg) -> dict:
    """Returns {"action": "accept"|"say"|"hold", ...}. Pure: no I/O.

    Our own message = one round of decay (measured 2026-10-02, duel 37); listening, waiting and accepting are free.
    So our numbers go out on a clock, not in reply to the rival: the anchor after OPEN_WAIT ticks, the floor when
    the floor zone starts (last FLOOR_FRAC of the clock), the last-chance number when LAST_CHANCE_TICKS remain;
    at most MAX_MSGS in all. Between sends we only listen. The accept bar falls with time from the anchor to the
    floor (patience costs nothing), and before any send we accept instead if the rival already beats the number we
    were about to send, less the round that sending would cost.
    """
    left = d["deadline_tick"] - tick
    raw = d.get("rival_offer")
    rival = parse_offer(raw)
    decay = float(d.get("decay_per_round") or 0.06)
    top = len(cfg.ratios) - 1
    elapsed = tick - st.start
    floor_left = max(cfg.accept_any_ticks + 1, cfg.last_chance_ticks + 1, round(cfg.floor_frac * st.total))
    floor_at = max(cfg.open_wait, st.total - floor_left)          # elapsed tick at which the floor zone starts
    floor_zone = left <= floor_left
    last = left <= cfg.last_chance_ticks

    # where the clock says we stand on the schedule (fractional) and which number is due
    if floor_zone or top == 0:
        time_pos = float(top)
    elif elapsed < cfg.open_wait:
        time_pos = 0.0
    else:
        time_pos = top * (elapsed - cfg.open_wait) / max(1, floor_at - cfg.open_wait)
    due = int(math.floor(time_pos + 1e-9)) if elapsed >= cfg.open_wait or floor_zone else -1
    nxt_p, nxt_d = planned_offer(d, max(due, 0), cfg, rival, last, st.rival_limit)
    out = {"left": left, "step": due, "sent": st.sent, "next": nxt_p, "next_days": nxt_d, "rival": rival}

    if st.accepted_at is not None:
        return {**out, "action": "hold", "why": "accepted, waiting to settle"}

    # would we send this tick?
    budget = cfg.max_msgs - st.sent
    want_say = (due >= 0 and st.last_sent != (nxt_p, nxt_d) and left >= 1
                and (budget >= 2 or (budget == 1 and last)))   # the last message is kept for the last chance
    if last and budget >= 1 and st.last_sent != (nxt_p, nxt_d) and left >= 1:
        want_say = True

    if rival is not None:
        rp, rd = rival
        rd_ok = not (two_issues(d) and rd is None)
        rs = surplus(d, rp, rd, cfg.days_best) if rd_ok else -1e9
        out["rival_surplus"] = round(rs, 2)
        if rd_ok and inside_limit(d, rp) and rs >= MIN_SURPLUS:
            bp, bd = planned_offer(d, time_pos, cfg, rival, False, st.rival_limit)
            bar_s = surplus(d, bp, bd, cfg.days_best) * (1 - decay)
            if want_say:  # prefer accepting over a counter that would cost a round
                bar_s = min(bar_s, surplus(d, nxt_p, nxt_d, cfg.days_best) * (1 - decay))
            out["bar"] = round(bar_s, 2)
            if rs >= bar_s:
                return {**out, "action": "accept", "why": f"rival surplus {rs:.0f} >= bar {bar_s:.0f}"}
            if left <= cfg.accept_any_ticks:
                return {**out, "action": "accept", "why": f"endgame ({left} ticks left), inside limit"}

    if left < 1:
        return {**out, "action": "hold", "why": "deadline"}
    pie = mirror_pie(d, st.rival_limit)
    if pie is not None and pie < 2 and not two_issues(d):
        return {**out, "action": "hold", "why": f"walk: no zone of agreement (mirror pie {pie})"}
    if due < 0:
        return {**out, "action": "hold", "why": f"listening before we anchor ({cfg.open_wait} ticks, free)"}
    if st.last_sent == (nxt_p, nxt_d):
        return {**out, "action": "hold", "why": "our number stands (resending would cost a round)"}
    if not want_say:
        return {**out, "action": "hold", "why": f"message budget: {st.sent}/{cfg.max_msgs} sent, last kept for the end"}
    return {**out, "action": "say", "price": nxt_p, "days": nxt_d,
            "why": "last chance" if last else ("floor" if due >= top else f"step {due}")}


def words(d: dict, n_sent: int, price: int, days: int | None, last: bool = False) -> str:
    lines = SELL_LINES if d["role"] == "seller" else BUY_LINES
    offer = f"{price} P" + (f", delivery day {days}" if days is not None else "")
    return (lines[-1] if last else lines[min(n_sent, len(lines) - 2)]).format(offer=offer)


# ---------------------------------------------------------------- the loop

def mirror_evidence(d: dict, every: list) -> dict:
    """Did the rival ever offer across the limit the mirror hypothesis gives it? (evidence against it)"""
    ml = mirror_limit(d, every)
    if ml is None:
        return {}
    theirs = [m.get("price") for m in d.get("messages") or []
              if m.get("from") == d.get("rival") and isinstance(m.get("price"), (int, float))]
    crossed = [p for p in theirs if (p > ml if d.get("role") == "seller" else p < ml)]
    return {"mirror_rival_limit": ml, "rival_prices": theirs, "rival_crossed_mirror": crossed}


def surplus_share_note(d: dict) -> dict:
    """What we can say about a finished duel from our side alone."""
    p = d.get("price")
    if p is None:
        return {}
    lim = d["your_limit"]
    return {"our_surplus": (p - lim) if d["role"] == "seller" else (lim - p)}


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["watch", "run"])
    ap.add_argument("--ratios", default=",".join(str(r) for r in RATIOS), help="concession ratios, anchor first")
    ap.add_argument("--last-r", type=float, default=LAST_R)
    ap.add_argument("--accept-any-ticks", type=int, default=ACCEPT_ANY_TICKS)
    ap.add_argument("--max-msgs", type=int, default=MAX_MSGS)
    ap.add_argument("--last-chance-ticks", type=int, default=LAST_CHANCE_TICKS)
    ap.add_argument("--days-cheap", type=float, default=DAYS_CHEAP)
    ap.add_argument("--days-premium", default=",".join(str(x) for x in DAYS_PREMIUM))
    ap.add_argument("--days-best", default="auto", choices=["auto", "0", "10"],
                    help="override our preferred delivery day if days_meaning shows the guess is wrong")
    ap.add_argument("--duel-ticks", type=int, default=DEFAULT_DUEL_TICKS)
    ap.add_argument("--floor-frac", type=float, default=FLOOR_FRAC)
    ap.add_argument("--open-wait", type=int, default=OPEN_WAIT)
    ap.add_argument("--mirror", action="store_true",
                    help="trust the UNVERIFIED mirror hypothesis: read the rival's limit from the paired duel")
    ap.add_argument("--until", default="", help="stop at this local wall time, HH:MM")
    ap.add_argument("--idle-ticks", type=int, default=40, help="exit after this many ticks with no live duel "
                    "(only once we have seen one)")
    ap.add_argument("--log-dir", default=str(LOGS), help="where duel/<date>.jsonl and duels/duel-N.json go")
    cfg = ap.parse_args()
    cfg.ratios = [float(x) for x in cfg.ratios.split(",") if x.strip()]
    cfg.days_premium = [float(x) for x in cfg.days_premium.split(",") if x.strip()]
    if not cfg.ratios or any(r <= 1.0 for r in cfg.ratios) or cfg.last_r <= 1.0:
        sys.exit("ratios must be > 1.0 (1.0 is our limit)")
    if cfg.max_msgs < 1:
        sys.exit("--max-msgs must be >= 1")
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
    run.start(mode=cfg.cmd, ratios=cfg.ratios, last_r=cfg.last_r, accept_any_ticks=cfg.accept_any_ticks,
              days_cheap=cfg.days_cheap, days_best=cfg.days_best, floor_frac=cfg.floor_frac,
              max_msgs=cfg.max_msgs, last_chance_ticks=cfg.last_chance_ticks, open_wait=cfg.open_wait, duel_ticks=cfg.duel_ticks)

    states: dict[int, DuelState] = {}
    finished: set[int] = set()
    last_tick = None
    idle = 0
    seen_any = False
    while True:
        if stop_at and time.time() >= stop_at:
            run.event("stop", why="until")
            break
        try:
            clock = b.clock()
            tick = int(clock["tick"])
        except Exception as e:  # noqa: BLE001  (network, shape): wait and retry, never die
            run.event("error", where="clock", kind=type(e).__name__, msg=str(e)[:200])
            time.sleep(5)
            continue
        if tick == last_tick or clock.get("paused"):
            time.sleep(min(10.0, max(0.5, float(clock.get("next_tick_in", 2.0)) + 0.4)))
            continue
        last_tick = tick
        try:  # one bad shape or bug must never end an unattended run: log it and go to the next tick
            try:
                every = b.duels(done=True).get("duels", [])
            except BazaarError as e:
                run.event("error", where="duels", code=e.code, msg=e.message)
                continue
            live = [d for d in every if d.get("status") == "live"]

            # finished duels: log the result and save the transcript once
            for d in every:
                did = d.get("duel")
                if d.get("status") != "live" and did in states and did not in finished:
                    finished.add(did)
                    run.event("result", duel=did, role=d.get("role"), limit=d.get("your_limit"), status=d.get("status"),
                              result=d.get("result"), price=d.get("price"), days=d.get("days"), rounds=d.get("rounds"),
                              rival=d.get("rival"), **surplus_share_note(d), **mirror_evidence(d, every))
                    write_json(log_dir / "duels" / f"duel-{int(did):05d}.json", d)

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
                    run.event("duel_new", duel=did, role=d.get("role"), item=d.get("item"), limit=d.get("your_limit"),
                              issues=d.get("issues"), days_weight=d.get("your_days_weight"),
                              days_meaning=d.get("days_meaning"), rival=d.get("rival"),
                              deadline=d.get("deadline_tick"), decay=d.get("decay_per_round"), total_ticks=st.total,
                              mirror_rival_limit=mirror_limit(d, every), mirror_used=cfg.mirror)
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
                if cfg.mirror:
                    st.rival_limit = mirror_limit(d, every)
                decisions.append((d, st, decide(d, st, tick, cfg)))

            # one accept per team per tick: the most urgent, then the biggest surplus; the rest hold this tick
            accepts = [x for x in decisions if x[2]["action"] == "accept"]
            accepts.sort(key=lambda x: (x[2]["left"], -x[2].get("rival_surplus", 0)))
            for x in accepts[1:]:
                x[2]["action"] = "hold"
                x[2]["why"] = "acceptable, but one accept per tick: re-checked next tick"

            for d, st, dec in decisions:
                did = d["duel"]
                row = {k: dec.get(k) for k in ("left", "step", "rival", "rival_surplus", "next", "next_days", "why")}
                if dec["action"] == "hold":
                    run.event("hold", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, **row)
                    continue
                if dec["action"] == "accept":
                    if not sending:
                        run.event("would_accept", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, **row)
                        continue
                    # re-read just before accepting: the server accepts the standing offer, whatever it is by then
                    try:
                        fresh = next((x for x in b.duels().get("duels", []) if x.get("duel") == did), None)
                    except BazaarError as e:
                        run.event("error", where="reread", duel=did, code=e.code, msg=e.message)
                        continue
                    if fresh is None or offer_id(fresh.get("rival_offer")) != offer_id(d.get("rival_offer")):
                        run.event("accept_skipped", duel=did, why="rival offer changed", now=fresh and fresh.get("rival_offer"))
                        continue
                    try:
                        resp = b.duel_accept(did)
                        st.accepted_at = tick
                        run.event("accept", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, resp=resp, **row)
                    except BazaarError as e:
                        run.event("refused", duel=did, action="accept", code=e.code, msg=e.message, extra=e.extra)
                    time.sleep(POST_GAP)
                    continue
                # say
                price, days = dec["price"], dec["days"]
                if not inside_limit(d, price):  # cannot happen by construction; never send it, never crash
                    run.event("bug_skip", duel=did, price=price, limit=d["your_limit"], role=d["role"])
                    continue
                text = words(d, st.sent, price, days, last=dec["why"] == "last chance")
                if not sending:
                    run.event("would_say", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, price=price,
                              days=days, text=text, **{k: v for k, v in row.items() if k not in ("next", "next_days")})
                    st.last_sent, st.last_sent_tick, st.step = (price, days), tick, dec["step"]
                    st.sent += 1
                    st.rival_id_at_send = offer_id(d.get("rival_offer"))
                    continue
                try:
                    resp = b.duel_say(did, text, price=price, days=days)
                    st.last_sent, st.last_sent_tick, st.step = (price, days), tick, dec["step"]
                    st.sent += 1
                    st.rival_id_at_send = offer_id(d.get("rival_offer"))
                    run.event("say", duel=did, role=d["role"], limit=d["your_limit"], tick=tick, price=price, days=days,
                              resp=redact(resp), **{k: v for k, v in row.items() if k not in ("next", "next_days")})
                except BazaarError as e:
                    # 429 / wait_for_tick: skip this duel until the next tick, never retry-spam
                    run.event("refused", duel=did, action="say", code=e.code, msg=e.message, extra=e.extra)
                time.sleep(POST_GAP)

            # accepted duels that did not settle within two ticks are open again
            for st in states.values():
                if st.accepted_at is not None and tick - st.accepted_at >= 2 and st.id not in finished:
                    st.accepted_at = None
        except Exception as e:  # noqa: BLE001
            run.event("error", where="tick", tick=tick, kind=type(e).__name__, msg=str(e)[:300])
            time.sleep(2)

    run.end(duels_seen=len(states), finished=len(finished))


if __name__ == "__main__":
    main()
