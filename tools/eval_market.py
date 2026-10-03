"""Offline eval of the market desk (agent/market_desk.py): where, card by card, does it gain or lose at our values?

The engine is tools/market_replay.py (boards rebuilt tick by tick from the public feed, our holdings moved by our
public settlements, one accept per tick, our bids and their "plausible" fills). This file does not re-implement it:
it wraps `market_desk.decide` with a recorder for the length of one replay, so every tick's board, cash, holdings and
decisions are kept, and then grades the replay card by card with its own, independent arithmetic.

Case unit: one (day, card) opportunity window. A card is a case for a day when, at some tick of that day, the board
held an offer the desk could structurally take (a one-card listing for cash, or a cash bid for one card, on a venue
that is not ours, not made by us, addressed to nobody or to us), or when another team sold it to a team on a venue.
The whole day is replayed once (cash, caps and the one-accept-per-tick slot couple the cards, and splitting them
would hide that), then each case is graded from that day's replay. A whole-day replay as a single case would give
one number and no signal on where the desk gains or loses; one case per tick would be thousands of near-identical
rows. Days are replayed independently, each from --cash.

Grade (headline first): surplus_P (value minus price and fee on a buy, price minus fee minus our copy's value on a
sale, value minus price on a filled bid; at our private values, recomputed here, not taken from the desk's records),
bad_trade (guardrail: any trade below our value after fees), missed_good (an in-the-money offer sat on the board
with room in cash and the policy traded nothing on that card that day), cash_floor_breach, plausible_fill (the
surplus leans on a bid fill inferred from evidence, not observed) and contested (a listing we took was really taken
by another team: we would have had to win that race). See evals/market-desk/metrics.md.

Our private values (set multipliers) only reach results.jsonl, traces and report.html, which stay out of git
(evals/market-desk/.gitignore). cases.jsonl, cases.md and metrics.md carry card refs and prices only. Game text
(offer notes, messages) is never read into a prompt, a trace or a report: only offer structure and numbers.

    python3 tools/eval_market.py                                    # baseline: Sunday's factory config, all days
    python3 tools/eval_market.py --logs /Volumes/bazaar/logs --to-tick 1200   # the share's logs, frozen at a tick
    python3 tools/eval_market.py --variant v1 --min-cash 100 --change "min cash 100: the bond is paid"
    python3 tools/eval_market.py --policy oracle --out-root <scratch>   # harness checks: oracle | null | reckless
    python3 tools/eval_market.py --compare baseline v1              # paired per-case deltas with a 95% CI
    python3 tools/eval_market.py --cases-only                       # write cases.jsonl / cases.md and stop

Read-only on the game: no network, no key, nothing is sent. --logs is only read; output goes under evals/ (or
--out-root, which the harness-check policies require so they never land in evals/).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import eval_common as ec  # noqa: E402
import market_desk as md  # noqa: E402
import market_replay as mr  # noqa: E402

FLOW = "market-desk"
DESK_DECIDE = md.decide            # the function under test, captured before any patching
FRIDAY_SETS = {"LAV", "MAL", "LAT", "SAL"}
POLICIES = ("desk", "oracle", "null", "reckless")
EPS = 1e-6
# 0/1 metrics are declared "float" in _state.json so the report's primary metric is surplus_P (the lite report
# picks the first "binary" one); the CI printed here still treats them as rates (Wilson).
METRICS = [
    {"id": "surplus_P", "label": "surplus P", "kind": "float", "better": "higher",
     "note": "value earned at our private values, net of fees (P)"},
    {"id": "bad_trade", "label": "bad trade", "kind": "float", "scale": 1, "better": "lower", "values": "0/1",
     "note": "guardrail: a trade below our value after fees; must be 0"},
    {"id": "missed_good", "label": "missed good", "kind": "float", "scale": 1, "better": "lower", "values": "0/1"},
    {"id": "cash_floor_breach", "label": "cash breach", "kind": "float", "scale": 1, "better": "lower",
     "values": "0/1"},
    {"id": "plausible_fill", "label": "plausible fill", "kind": "float", "scale": 1, "better": "lower",
     "values": "0/1", "note": "honesty flag: surplus from a bid fill inferred from evidence, not observed"},
    {"id": "contested", "label": "contested", "kind": "float", "scale": 1, "better": "lower", "values": "0/1",
     "note": "honesty flag: a listing we took was really taken by another team (a race we would have to win)"},
]
RATE_METRICS = {m["id"] for m in METRICS if m.get("values") == "0/1"}
PERF_FIELDS = [{"id": "latency_s", "label": "latency", "unit": "s"}, {"id": "trades", "label": "trades"},
               {"id": "bid_fills", "label": "bid fills"}]


# ---------------------------------------------------------------- inputs (read-only)

def load_inputs(logs: Path, feeds: list | None) -> tuple:
    """(events, me, catalog, feed paths). Never fetches anything: a missing catalog is an error, not a GET."""
    paths = [Path(p) for p in feeds] if feeds else [logs / "feed-vm" / "feed.jsonl", logs / "feed" / "feed.jsonl"]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise SystemExit(f"no feed file under {logs} (looked for feed-vm/feed.jsonl and feed/feed.jsonl)")
    me_p, cat_p = logs / "state" / "me.json", logs / "public" / "catalog.json"
    for p in (me_p, cat_p):
        if not p.exists():
            raise SystemExit(f"missing {p}: this eval reads it from --logs and never fetches it")
    return mr.load(paths), json.loads(me_p.read_text()), json.loads(cat_p.read_text()), paths


def day_windows(events: list) -> list:
    """[(day, first tick, last tick)] from day.opened / day.closed. A day starts the tick after the previous one
    closed (Saturday opened at Friday's last tick, 159, while the clock was paused)."""
    ticks = [e["tick"] for e in events if isinstance(e.get("tick"), int)]
    if not ticks:
        return []
    opened = [(e["tick"], str((e.get("payload") or {}).get("day") or "day")) for e in events
              if e.get("type") == "day.opened"]
    closed = sorted(e["tick"] for e in events if e.get("type") == "day.closed")
    if not opened:
        return [("all", min(ticks), max(ticks))]
    out = []
    for i, (_t, name) in enumerate(opened):
        start = min(ticks) if i == 0 else out[-1][2] + 1
        end = next((c for c in closed if c >= start), max(ticks))
        if end >= start:
            out.append((name, start, end))
    return out


class Context:
    """Time-varying facts the replay does not track: venue fees and owners, released sets, game hours per tick."""

    def __init__(self, events: list, catalog: dict, me: dict):
        self.me_id = me["id"]
        self.values = Values(catalog, me.get("affinity") or {})
        self.by_tick: dict = {}
        for e in events:
            self.by_tick.setdefault(e.get("tick") or 0, []).append(e)
        self.venue_changes = []
        for e in events:
            p, t = e.get("payload") or {}, e.get("type")
            vid = p.get("venue")
            if not isinstance(vid, str):
                continue
            if t == "venue.opened":
                self.venue_changes.append((e["tick"], vid, {"fee": (int(p.get("fee_bps") or 0),
                                                                    int(p.get("fee_per_card") or 0)),
                                                            "owner": p.get("owner"), "house": False}))
            elif t == "venue.fee_changed":
                self.venue_changes.append((e["tick"], vid, {"fee": (int(p.get("fee_bps") or 0),
                                                                    int(p.get("fee_per_card") or 0))}))
            elif t == "venue.closed":
                self.venue_changes.append((e["tick"], vid, {"closed": True}))
        self.venue_changes.sort(key=lambda x: x[0])
        sets = {s["id"] for s in catalog.get("sets", [])}
        self.first_seen = {s: 0 for s in FRIDAY_SETS & sets}
        for e in events:
            p = e.get("payload") or {}
            refs = [i.get("ref") for i in p.get("items") or [] if isinstance(i, dict)]
            o = p.get("offer")
            if isinstance(o, dict):
                refs += [a.get("ref") for a in (o.get("give") or {}).get("assets") or [] if isinstance(a, dict)]
            for r in refs:
                if isinstance(r, str) and md.REF_RE.match(r) and r[:3] in sets:
                    self.first_seen.setdefault(r[:3], e.get("tick") or 0)
        known = sorted({(e["tick"], float(e["t"])) for e in events
                        if isinstance(e.get("tick"), int) and isinstance(e.get("t"), (int, float))})
        self.hours_known = dict(known)
        self.hours_ticks = [k for k, _ in known]

    def venues_at(self, t: int) -> dict:
        table = {md.HOME: {"fee": md.DEFAULT_FEE, "owner": None, "house": True}}
        for tick, vid, upd in self.venue_changes:
            if tick > t:
                break
            table.setdefault(vid, {"fee": md.WORST_FEE, "owner": None, "house": False}).update(upd)
        return table

    def released_at(self, t: int) -> set:
        return {s for s, t0 in self.first_seen.items() if t0 <= t}

    def hours_at(self, t: int) -> float:
        """Game hours at tick t from the feed's own clock (Friday 60 ticks per game hour, Saturday 120): the replay
        uses t / 60, which makes the per-hour caps half as tight on Saturday."""
        if t in self.hours_known:
            return self.hours_known[t]
        ks = self.hours_ticks
        if not ks:
            return t / md.TICKS_PER_GAME_HOUR
        lo = max((k for k in ks if k < t), default=None)
        hi = min((k for k in ks if k > t), default=None)
        if lo is not None and hi is not None:
            a, b = self.hours_known[lo], self.hours_known[hi]
            return a + (b - a) * (t - lo) / (hi - lo)
        if lo is not None:
            return self.hours_known[lo] + (t - lo) / md.TICKS_PER_GAME_HOUR
        return max(0.0, self.hours_known[hi] - (hi - t) / md.TICKS_PER_GAME_HOUR)


# ---------------------------------------------------------------- the grader's own arithmetic

class Values:
    """Our value of a card, written independently of the desk's Valuer: book x set multiplier x copy marginal
    (1, 0.25, 0.1 for the 1st, 2nd, 3rd+ copy). No page bonus (unconfirmed whether trades score it)."""

    def __init__(self, catalog: dict, affinity: dict):
        self.cards = {}
        for s in catalog.get("sets", []):
            for c in s.get("cards", []):
                self.cards[c["id"]] = (s["id"], c.get("rarity"), float(c.get("book") or 0), bool(c.get("hidden")))
        self.marg = [float(x) for x in (catalog.get("values") or {}).get("copy_marginals") or [1.0, 0.25, 0.1]]
        self.aff = {k: float(v) for k, v in (affinity or {}).items()}

    def first(self, ref: str) -> float:
        c = self.cards.get(ref)
        if not c or c[3]:
            return 0.0
        return c[2] * self.aff.get(c[0], 0.0)

    def more(self, ref: str, k: int) -> float:
        """Value of one more copy when we hold k."""
        return self.first(ref) * self.marg[min(k, len(self.marg) - 1)]

    def copy(self, ref: str, k: int) -> float:
        """What giving up one of our k copies loses us."""
        return 0.0 if k <= 0 else self.first(ref) * self.marg[min(k - 1, len(self.marg) - 1)]

    def describe(self, ref: str) -> tuple:
        c = self.cards.get(ref)
        return (c[0], c[1]) if c else (ref[:3], None)


def venue_fee(price: int, fee: tuple) -> int:
    """Fee for one card at `price`: ceil(price x bps / 10000) + per-card fee (paid by the side that accepts)."""
    bps, per = int(fee[0]), int(fee[1])
    return -(-int(price) * bps // 10000) + per


def opportunity_gain(o: dict, k: int, values: Values, fee: int) -> float:
    """Gain at our values of taking a board offer right now, with k copies held."""
    if o["side"] == "buy":
        return values.more(o["ref"], k) - o["price"] - fee
    return o["price"] - fee - values.copy(o["ref"], k)


def verify_evidence(ctx: Context, t: int, ref: str, bid_price: int) -> str | None:
    """Re-checks a plausible bid fill: at tick t another team sold `ref` alone for cash at or under what our bid nets
    the seller, or listed it alone for a cash ask (>= 1 P, nothing else wanted) at or under that. A swap listing
    (want cash 0) is not an ask. Returns a short structural description, or None."""
    net = bid_price - venue_fee(bid_price, md.DEFAULT_FEE)
    for e in ctx.by_tick.get(t, []):
        p = e.get("payload") or {}
        if e.get("type") == "settlement" and p.get("venue") and isinstance(p.get("price"), int) and p["price"] >= 1:
            cards = [i for i in p.get("items") or [] if isinstance(i, dict) and i.get("kind") == "card"]
            if len(cards) == 1 and cards[0].get("ref") == ref and cards[0].get("frm") != ctx.me_id \
                    and p["price"] <= net:
                return f"settlement: {cards[0].get('frm')} sold {ref} at {p['price']}"
        elif e.get("type") == "offer.listed":
            o = p.get("offer") or {}
            g, w = o.get("give") or {}, o.get("want") or {}
            ga = [a for a in g.get("assets") or [] if isinstance(a, dict)]
            if o.get("maker") != ctx.me_id and len(ga) == 1 and ga[0].get("ref") == ref and not g.get("cash") \
                    and not (w.get("assets") or w.get("types") or w.get("cards")) \
                    and isinstance(w.get("cash"), int) and 1 <= w["cash"] <= net:
                return f"listing: {o.get('maker')} asked {w['cash']} for {ref}"
    return None


# ---------------------------------------------------------------- board scan and the recorder

def takeable(boards: dict, tick: int, me_id: str, our_assets: dict, venues: dict) -> list:
    """Every board offer a team in our seat could accept this tick, by structure only (the desk's own checks):
    a one-card listing for cash or a cash bid for one card; never ours, never on our own venue."""
    out = []
    for vid, offs in (boards or {}).items():
        if (venues.get(vid) or {}).get("owner") == me_id or (venues.get(vid) or {}).get("closed"):
            continue
        for o in offs or []:
            if not isinstance(o, dict) or o.get("maker") == me_id:
                continue
            shape = md.classify(o)
            if shape == "listing":
                c, side = md.check_listing(o, me_id, tick), "buy"
            elif shape == "bid":
                c, side = md.check_bid(o, me_id, our_assets, tick), "sell"
            else:
                continue
            if c["ok"]:
                out.append({"offer": o.get("id"), "side": side, "ref": c["ref"], "price": c["price"], "venue": vid,
                            "partner": o.get("maker"), "asset": c.get("asset")})
    return out


REC_KEYS = ("kind", "action", "reason", "offer", "price", "fee", "venue", "value", "gain", "need")


class Recorder:
    """Stands in for market_desk.decide during one replay: fixes the snapshot (venue fees and owners, released sets,
    game hours), calls the policy, and keeps what this tick looked like and what the policy did."""

    def __init__(self, policy, ctx: Context):
        self.policy, self.ctx = policy, ctx
        self.ticks: dict = {}

    def __call__(self, snap, valuer, tape, ledger, cfg, bidbook=None, swapbook=None):
        t = snap["tick"]
        snap["venues"] = self.ctx.venues_at(t)      # the replay passes El Rastro only: team venues looked house-run
        snap["released"] = self.ctx.released_at(t)  # the replay hard-codes Friday's four sets (no El Retiro bids)
        snap["t_hours"] = self.ctx.hours_at(t)      # read back by the replay's ledger for the caps
        res = self.policy(snap, valuer, tape, ledger, cfg, bidbook, swapbook)
        holdings = snap.get("holdings") or {}
        counts = {r: len(a) for r, a in holdings.items() if a}
        our_assets = {a["id"]: r for r, lst in holdings.items() for a in lst if isinstance(a, dict) and "id" in a}
        offers: dict = {}
        for o in takeable(snap.get("boards") or {}, t, self.ctx.me_id, our_assets, snap["venues"]):
            offers.setdefault(o["ref"], []).append(o)
        recs: dict = {}
        for r in res.get("records") or []:
            if isinstance(r.get("card"), str):
                recs.setdefault(r["card"], []).append({k: r.get(k) for k in REC_KEYS if r.get(k) is not None})
        bids = {ref: b.get("price") for ref, b in (bidbook or {}).items() if b.get("offer") is not None}
        self.ticks[t] = {"cash": int(snap.get("cash") or 0), "counts": counts, "offers": offers, "recs": recs,
                         "accept": res.get("accept"), "bids": bids, "venues": snap["venues"],
                         "hours": snap["t_hours"]}
        return res


@contextmanager
def patched_decide(fn):
    old = mr.md.decide
    mr.md.decide = fn
    try:
        yield
    finally:
        mr.md.decide = old


# ---------------------------------------------------------------- policies: the desk and the harness checks

def desk_policy(snap, valuer, tape, ledger, cfg, bidbook=None, swapbook=None):
    return DESK_DECIDE(snap, valuer, tape, ledger, cfg, bidbook, swapbook)


def null_policy(snap, valuer, tape, ledger, cfg, bidbook=None, swapbook=None):
    return {"records": [], "accept": None, "bids": [], "swaps": []}


def _accept(o: dict, t: int, fee: int, value: float, gain: float) -> dict:
    return {"tick": t, "offer": o["offer"], "side": o["side"], "card": o["ref"], "price": o["price"], "fee": fee,
            "asset": o.get("asset"), "partner": o.get("partner"), "venue": o["venue"], "value": round(value, 2),
            "gain": round(gain, 2), "kind": o["side"], "action": "take", "reason": "harness policy"}


def make_oracle(ctx: Context, floor: int):
    """Takes the best in-the-money offer each tick (gain > 0 at our values) while cash after it stays >= floor.
    Never sells a last copy (the grader does not count that as an opportunity either). Every venue but ours."""
    def oracle(snap, valuer, tape, ledger, cfg, bidbook=None, swapbook=None):
        t, cash = snap["tick"], int(snap.get("cash") or 0)
        holdings = snap.get("holdings") or {}
        counts = {r: len(a) for r, a in holdings.items() if a}
        assets = {a["id"]: r for r, lst in holdings.items() for a in lst if isinstance(a, dict) and "id" in a}
        best = None
        for o in takeable(snap.get("boards") or {}, t, ctx.me_id, assets, snap["venues"]):
            fee = venue_fee(o["price"], snap["venues"].get(o["venue"], {}).get("fee") or md.WORST_FEE)
            k = counts.get(o["ref"], 0)
            if o["side"] == "buy" and cash - o["price"] - fee < floor:
                continue
            if o["side"] == "sell":
                if k < 2:
                    continue
                if o.get("asset") is None:   # pick a spare: the highest serial, never the lowest
                    copies = sorted(holdings.get(o["ref"]) or [], key=lambda a: (a.get("serial") or 0, a.get("id")))
                    o = {**o, "asset": copies[-1]["id"]}
            g = opportunity_gain(o, k, ctx.values, fee)
            if g > EPS and (best is None or g > best[1]):
                v = ctx.values.more(o["ref"], k) if o["side"] == "buy" else ctx.values.copy(o["ref"], k)
                best = (o, g, fee, v)
        acc = _accept(best[0], t, best[2], best[3], best[1]) if best else None
        return {"records": [acc] if acc else [], "accept": acc, "bids": [], "swaps": []}
    return oracle


def make_reckless(ctx: Context):
    """Accepts the first offer it can pay for (or a bid for any card it holds, last copies included), every tick,
    with no value check at all. It exists to light the guardrails."""
    def reckless(snap, valuer, tape, ledger, cfg, bidbook=None, swapbook=None):
        t, cash = snap["tick"], int(snap.get("cash") or 0)
        holdings = snap.get("holdings") or {}
        counts = {r: len(a) for r, a in holdings.items() if a}
        assets = {a["id"]: r for r, lst in holdings.items() for a in lst if isinstance(a, dict) and "id" in a}
        for o in takeable(snap.get("boards") or {}, t, ctx.me_id, assets, snap["venues"]):
            fee = venue_fee(o["price"], snap["venues"].get(o["venue"], {}).get("fee") or md.WORST_FEE)
            k = counts.get(o["ref"], 0)
            if o["side"] == "buy" and cash < o["price"] + fee:
                continue
            if o["side"] == "sell":
                if k < 1:
                    continue
                if o.get("asset") is None:
                    o = {**o, "asset": holdings[o["ref"]][0]["id"]}
            v = ctx.values.more(o["ref"], k) if o["side"] == "buy" else ctx.values.copy(o["ref"], k)
            acc = _accept(o, t, fee, v, opportunity_gain(o, k, ctx.values, fee))
            return {"records": [acc], "accept": acc, "bids": [], "swaps": []}
        return {"records": [], "accept": None, "bids": [], "swaps": []}
    return reckless


def make_policy(name: str, ctx: Context, floor: int):
    if name == "desk":
        return desk_policy
    if name == "null":
        return null_policy
    if name == "oracle":
        return make_oracle(ctx, floor)
    if name == "reckless":
        return make_reckless(ctx)
    raise SystemExit(f"unknown policy {name!r}")


def replay_day(events, me, catalog, cfg, cash0, ctx, policy, t_from, t_to) -> tuple:
    rec = Recorder(policy, ctx)
    with patched_decide(rec):
        rr = mr.replay(events, me, catalog, cfg, cash0, t_from=t_from, t_to=t_to)
    return rr, rec


# ---------------------------------------------------------------- cases

def build_cases(events, me, catalog, cfg, ctx, days) -> list:
    """The case list, from a null-policy replay (the boards as they really were) plus real team-to-team sales."""
    out = []
    for day, t0, t1 in days:
        _, rec = replay_day(events, me, catalog, cfg, 0, ctx, null_policy, t0, t1)
        per: dict = {}
        for t in sorted(rec.ticks):
            for ref, offs in rec.ticks[t]["offers"].items():
                c = per.setdefault(ref, {"listings": {}, "bids": {}})
                for o in offs:
                    book = c["listings"] if o["side"] == "buy" else c["bids"]
                    if o["offer"] not in book:
                        book[o["offer"]] = (o["price"], o["venue"], t)
        real: dict = {}
        for t in range(t0, t1 + 1):
            for e in ctx.by_tick.get(t, []):
                p = e.get("payload") or {}
                if e.get("type") != "settlement" or not p.get("venue") or not isinstance(p.get("price"), int):
                    continue
                cards = [i for i in p.get("items") or [] if isinstance(i, dict) and i.get("kind") == "card"]
                if len(cards) == 1 and p["price"] >= 1 and isinstance(cards[0].get("ref"), str) \
                        and md.REF_RE.match(cards[0]["ref"]):
                    real.setdefault(cards[0]["ref"], []).append(p["price"])
        start_counts = rec.ticks[t0]["counts"] if t0 in rec.ticks else {}
        for ref in sorted(set(per) | set(real)):
            if ref not in ctx.values.cards:
                continue
            c = per.get(ref) or {"listings": {}, "bids": {}}
            sid, rarity = ctx.values.describe(ref)
            ask = min(c["listings"].values(), default=None)
            bid = max(c["bids"].values(), key=lambda x: (x[0], -x[2]), default=None)
            prices = real.get(ref) or []
            tags = [day] + (["buy"] if c["listings"] else []) + (["sell"] if c["bids"] else []) \
                + [sid, rarity or "unknown", "real-trade" if prices else "no-real-trade"]
            case = {"id": f"{day}-{ref}", "tags": tags, "day": day, "card": ref, "t_from": t0, "t_to": t1,
                    "listings": len(c["listings"]), "best_ask": f"{ask[0]} on {ask[1]} at t{ask[2]}" if ask else "",
                    "bids": len(c["bids"]), "best_bid": f"{bid[0]} on {bid[1]} at t{bid[2]}" if bid else "",
                    "real_trades": len(prices),
                    "real_prices": f"{min(prices)}-{max(prices)}" if prices else "",
                    "source": f"public feed ticks {t0}-{t1}; board offers by structure only"}
            case["_held"] = start_counts.get(ref, 0)   # private: prompt only, never cases.jsonl
            out.append(case)
    return out


def prompt_of(c: dict) -> str:
    sid = c["card"][:3]
    rar = next((t for t in c["tags"][1:] if t in ("common", "uncommon", "rare", "epic", "legendary")), "?")
    return (f"day {c['day']} · card {c['card']} ({sid} {rar}) · ticks {c['t_from']}-{c['t_to']}\n"
            f"board: {c['listings']} listings" + (f" (best ask {c['best_ask']})" if c["best_ask"] else "")
            + f", {c['bids']} bids" + (f" (best bid {c['best_bid']})" if c["best_bid"] else "") + "\n"
            f"we hold {c.get('_held', '?')} at the window start\n"
            f"real team-to-team sales of this card that day: {c['real_trades']}"
            + (f" at {c['real_prices']} P" if c["real_prices"] else ""))


def public_case(c: dict) -> dict:
    return {k: v for k, v in c.items() if not k.startswith("_")}


# ---------------------------------------------------------------- grading one case from its day's replay

def day_ledger(rr: dict, rec: Recorder, ctx: Context, cash0: int) -> list:
    """Every trade and bid fill of the day, in replay order, with the grader's fee, value, surplus and cash after."""
    evs = [(x["tick"], 0, i, "trade", x) for i, x in enumerate(rr["trades"])] + \
          [(f["tick"], 1, i, "fill", f) for i, f in enumerate(rr["fills"])]
    evs.sort(key=lambda e: e[:3])
    cash, out, same_tick = cash0, [], {}
    for t, _o, _i, kind, x in evs:
        ref = x["card"]
        tk = rec.ticks.get(t) or {}
        venues = tk.get("venues") or ctx.venues_at(t)
        k = (tk.get("counts") or {}).get(ref, 0) + same_tick.get((t, ref), 0)
        row = {"tick": t, "kind": kind, "card": ref, "price": x["price"], "venue": x.get("venue") or md.HOME}
        if kind == "trade":
            fee = venue_fee(x["price"], (venues.get(row["venue"]) or {}).get("fee") or md.WORST_FEE)
            row.update(side=x["side"], fee=fee, offer=x.get("offer"), desk_fee=x.get("fee"),
                       contested=bool(x.get("contested")))
            if (venues.get(row["venue"]) or {}).get("owner") == ctx.me_id:
                row.update(value=0.0, surplus=0.0, impossible="our own venue: the server refuses it")
            elif x["side"] == "buy":
                v = ctx.values.more(ref, k)
                row.update(value=v, surplus=v - x["price"] - fee)
            else:
                v = ctx.values.copy(ref, k)
                row.update(value=v, surplus=x["price"] - fee - v)
            cash += (x["price"] - fee) if x["side"] == "sell" else -(x["price"] + fee)
            same_tick[(t, ref)] = same_tick.get((t, ref), 0) + (1 if x["side"] == "buy" else -1)
        else:
            ev = verify_evidence(ctx, t, ref, x["price"])
            v = ctx.values.more(ref, k)
            row.update(side="bid", fee=0, value=v, evidence=ev, surplus=(v - x["price"]) if ev else 0.0,
                       rejected=ev is None)
            cash -= x["price"]   # the replay paid for it either way; keep the same cash path
            same_tick[(t, ref)] = same_tick.get((t, ref), 0) + 1
        row["cash_after"] = cash
        out.append(row)
    return out


def grade_case(case: dict, rr: dict, rec: Recorder, ledger: list, ctx: Context, *, floor: int,
               missed_min: float, system: str) -> tuple:
    ref, t0, t1 = case["card"], case["t_from"], case["t_to"]
    mine = [r for r in ledger if r["card"] == ref]
    counted = [r for r in mine if not r.get("rejected") and not r.get("impossible")]
    surplus = sum(r["surplus"] for r in counted)
    bad = any(r["surplus"] < -EPS for r in counted)
    breach = any(r["cash_after"] < floor for r in mine if r["side"] in ("buy", "bid"))
    fills = [r for r in counted if r["kind"] == "fill"]
    contested = any(r.get("contested") for r in mine if r["kind"] == "trade")
    # opportunities on the board for this card, at our values, with room in cash
    best_opp, missed = None, None
    for t in range(t0, t1 + 1):
        tk = rec.ticks.get(t)
        if not tk:
            continue
        k = tk["counts"].get(ref, 0)
        for o in tk["offers"].get(ref, []):
            fee = venue_fee(o["price"], (tk["venues"].get(o["venue"]) or {}).get("fee") or md.WORST_FEE)
            if o["side"] == "buy" and tk["cash"] - o["price"] - fee < floor:
                continue
            if o["side"] == "sell" and k < 2:
                continue   # never count selling a last copy as an opportunity (page bonus not modelled)
            g = opportunity_gain(o, k, ctx.values, fee)
            if best_opp is None or g > best_opp["gain"]:
                best_opp = {"tick": t, "offer": o["offer"], "side": o["side"], "price": o["price"], "fee": fee,
                            "venue": o["venue"], "gain": round(g, 2)}
            if not counted and g >= missed_min and (missed is None or g > missed["gain"]):
                why = [r.get("reason") for r in tk["recs"].get(ref, []) if r.get("offer") == o["offer"]]
                missed = {"tick": t, "offer": o["offer"], "side": o["side"], "price": o["price"], "fee": fee,
                          "venue": o["venue"], "gain": round(g, 2), "policy_reason": why[0] if why else None}
    grade = {"surplus_P": round(surplus, 2), "bad_trade": int(bad), "missed_good": int(missed is not None),
             "cash_floor_breach": int(breach), "plausible_fill": int(bool(fills)), "contested": int(contested)}
    claimed = sum(float(x.get("gain") or 0) for x in rr["trades"] if x["card"] == ref) + \
        sum(float(f.get("gain") or 0) for f in rr["fills"] if f["card"] == ref)
    meta = {"trades": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in mine],
            "best_opportunity": best_opp, "missed": missed, "policy_claimed_gain": round(claimed, 2),
            "grader_vs_policy_gain": round(surplus - claimed, 2),
            "rejected_fills": sum(1 for r in mine if r.get("rejected")), "window": [t0, t1]}
    perf = {"trades": sum(1 for r in mine if r["kind"] == "trade"), "bid_fills": len(fills)}
    return grade, perf, trace_of(case, rec, mine, missed, grade, system), meta


def trace_of(case: dict, rec: Recorder, mine: list, missed, grade: dict, system: str, cap: int = 250) -> list:
    """Per-tick turns, only when something about this card changed: user = what the board showed (structure and
    numbers only), assistant = what the policy did."""
    ref = case["card"]
    turns = [{"role": "system", "content": system}]
    by_tick: dict = {}
    for r in mine:
        by_tick.setdefault(r["tick"], []).append(r)
    last, n, elided = None, 0, 0
    for t in range(case["t_from"], case["t_to"] + 1):
        tk = rec.ticks.get(t)
        if not tk:
            continue
        offers = tk["offers"].get(ref, [])
        recs = tk["recs"].get(ref, [])
        acc = tk["accept"] if (tk["accept"] or {}).get("card") == ref else None
        live = tk["bids"].get(ref)
        k = tk["counts"].get(ref, 0)
        sig = (tuple((o["offer"], o["price"]) for o in offers), k, live,
               tuple((r.get("action"), r.get("offer"), str(r.get("reason", ""))[:12]) for r in recs))
        if not offers and not recs and live is None and t not in by_tick:
            last = sig
            continue
        if sig == last and t not in by_tick:
            continue
        last = sig
        if n >= cap:
            elided += 1
            continue
        n += 1
        asks = "; ".join(f"{o['venue']} {o['price']} (offer {o['offer']}, {o['partner']})"
                         for o in sorted(offers, key=lambda o: o["price"]) if o["side"] == "buy") or "none"
        bids = "; ".join(f"{o['venue']} {o['price']} (offer {o['offer']}, {o['partner']})"
                         for o in sorted(offers, key=lambda o: -o["price"]) if o["side"] == "sell") or "none"
        turns.append({"role": "user", "content": f"tick {t} (game h {tk['hours']:.2f}) · cash {tk['cash']} · "
                                                 f"we hold {k} × {ref}\nasks: {asks}\nbids: {bids}"
                                                 + (f"\nour live bid: {live}" if live is not None else "")})
        said = []
        for r in recs:
            bits = [str(r.get("action")), str(r.get("kind", ""))]
            if r.get("offer") is not None:
                bits.append(f"offer {r['offer']}")
            if r.get("price") is not None:
                bits.append(f"@ {r['price']}")
            if r.get("venue"):
                bits.append(f"on {r['venue']}")
            line = " ".join(bits) + (f": {r['reason']}" if r.get("reason") else "")
            if line not in said:
                said.append(line)
        for r in by_tick.get(t, []):
            if r["kind"] == "trade":
                said.append(f"=> {r['side'].upper()} {ref} @ {r['price']} fee {r['fee']} on {r['venue']}: grader "
                            f"value {r['value']:.2f}, surplus {r['surplus']:+.2f}, cash after {r['cash_after']}"
                            + (" [really taken by another team]" if r.get("contested") else "")
                            + (f" [{r['impossible']}]" if r.get("impossible") else ""))
            else:
                said.append(f"=> BID FILL (plausible) {ref} @ {r['price']}: "
                            + (f"evidence {r['evidence']}, surplus {r['surplus']:+.2f}" if r["evidence"]
                               else "evidence rejected by the grader (no cash sale or ask at or under the bid): "
                                    "surplus 0"))
        if acc and not any(s.startswith("=>") for s in said):
            said.append(f"take {acc.get('side')} offer {acc.get('offer')} @ {acc.get('price')}")
        turns.append({"role": "assistant", "content": "\n".join(said) or "no action on this card"})
    if elided:
        turns.append({"role": "user", "content": f"... {elided} more ticks with changes elided"})
    turns.append({"role": "tool_result", "name": "grader", "content": json.dumps(
        {"grade": grade, "missed": missed}, sort_keys=True)})
    return turns


def evaluate(events, me, catalog, cfg, *, policy: str = "desk", cash: int = 355, floor: int = 280,
             missed_min: float = 3.0, days: list | None = None, cases: list | None = None) -> dict:
    """Runs every day and grades every case in memory: {case id: (grade, perf, trace, meta)}. Used by the tests."""
    ctx = Context(events, catalog, me)
    days = days if days is not None else day_windows(events)
    cases = cases if cases is not None else build_cases(events, me, catalog, cfg, ctx, days)
    pol = make_policy(policy, ctx, floor)
    out = {}
    for day, t0, t1 in days:
        rr, rec = replay_day(events, me, catalog, cfg, cash, ctx, pol, t0, t1)
        led = day_ledger(rr, rec, ctx, cash)
        for c in cases:
            if c["day"] == day:
                out[c["id"]] = grade_case(c, rr, rec, led, ctx, floor=floor, missed_min=missed_min, system=policy)
    return out


# ---------------------------------------------------------------- labels, summary, compare

def config_label(cfg: md.Config) -> str:
    d = md.Config()
    diffs = [f"{f.name}={getattr(cfg, f.name)}" for f in dataclasses.fields(cfg)
             if getattr(cfg, f.name) != getattr(d, f.name)]
    return ",".join(diffs) or "defaults"


def case_means(rows: list) -> dict:
    """{case id: {metric: mean over status-ok reps}} - the report builder's way."""
    acc: dict = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        for m, v in r["grade"].items():
            acc.setdefault(r["prompt_id"], {}).setdefault(m, []).append(v)
    return {cid: {m: sum(v) / len(v) for m, v in ms.items()} for cid, ms in acc.items()}


def summarize(variant: str, rows: list) -> str:
    means = case_means(rows)
    per_case = [{"prompt_id": cid, "status": "ok", "grade": g} for cid, g in means.items()]
    ci_metrics = [{**m, "kind": "binary" if m["id"] in RATE_METRICS else m["kind"]} for m in METRICS]
    lines = [ec.summary_line(FLOW, variant, per_case, ci_metrics)]
    days: dict = {}
    for cid, g in means.items():
        days.setdefault(cid.split("-", 1)[0], []).append(g["surplus_P"])
    lines.append("  day totals (sum of per-case surplus_P): "
                 + ", ".join(f"{d} {sum(v):+.1f} P over {len(v)} cases" for d, v in sorted(days.items())))
    s = [g["surplus_P"] for g in means.values()]
    if len(s) > 1:
        mu, half, n = ec.mean_ci(s)
        sd = math.sqrt(sum((x - mu) ** 2 for x in s) / (n - 1))
        lines.append(f"  noise floor: the replay is deterministic (reps only re-check that), so the noise is which "
                     f"cases the market offered. Unpaired, two configs need |delta mean surplus_P| > "
                     f"{half * math.sqrt(2):.2f} P (sd {sd:.2f}, n {n}); use --compare for the paired CI, which is "
                     f"tighter because unchanged cases cancel.")
    nz = sorted(((g["surplus_P"], cid) for cid, g in means.items() if abs(g["surplus_P"]) > EPS))
    if nz:
        lines.append("  cases with surplus: " + ", ".join(f"{cid} {v:+.1f}" for v, cid in nz))
    for m in ("bad_trade", "missed_good", "cash_floor_breach", "plausible_fill", "contested"):
        ids = [cid for cid, g in means.items() if g.get(m, 0) > 0]
        if ids:
            lines.append(f"  {m}: {', '.join(sorted(ids))}")
    return "\n".join(lines)


def compare(root: Path, a: str, b: str) -> str:
    rows = {}
    for v in (a, b):
        p = root / FLOW / v / "results.jsonl"
        if not p.exists():
            raise SystemExit(f"no results for {v} at {p}")
        rows[v] = case_means([json.loads(x) for x in p.read_text().splitlines() if x.strip()])
    ids = sorted(set(rows[a]) & set(rows[b]))
    out = [f"[{FLOW}] {b} - {a}, paired over {len(ids)} cases"]
    for m in METRICS:
        d = [rows[b][i][m["id"]] - rows[a][i][m["id"]] for i in ids if m["id"] in rows[b][i] and m["id"] in rows[a][i]]
        if not d:
            continue
        mu, half, n = ec.mean_ci(d)
        sig = "significant" if n > 1 and abs(mu) > half else "within noise"
        moved = sum(1 for x in d if abs(x) > EPS)
        out.append(f"  {m['id']}: {mu:+.3f} [{mu - half:+.3f}, {mu + half:+.3f}] (n={n}, {moved} cases moved, {sig})")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="Offline eval of the market desk over recorded days (no network)")
    ap.add_argument("--variant", default="baseline", help="baseline or v1, v2, ...")
    ap.add_argument("--change", default=None, help="non-baseline: what this variant changes (first line = label)")
    ap.add_argument("--policy", choices=POLICIES, default="desk",
                    help="desk = agent/market_desk.py; oracle / null / reckless are harness checks (need --out-root)")
    ap.add_argument("--reps", type=int, default=1, help="the replay is deterministic: reps > 1 only re-check that")
    ap.add_argument("--logs", default=str(ROOT / "logs"), help="logs dir with feed/, feed-vm/, state/me.json and "
                                                               "public/catalog.json (read-only)")
    ap.add_argument("--feed", action="append", default=None, help="feed JSONL (repeatable; default: feed-vm + feed)")
    ap.add_argument("--cash", type=int, default=355, help="cash at the start of each replayed day (default 355, as "
                                                          "tools/market_replay.py: 205 + the 150 grant)")
    ap.add_argument("--floor", type=int, default=280, help="grader's cash floor for cash_floor_breach and for what "
                                                           "counts as an opportunity with room (team rule: 280)")
    ap.add_argument("--missed-min", type=float, default=3.0, help="smallest gain (P) that counts as a missed good offer")
    ap.add_argument("--to-tick", type=int, default=None, help="ignore feed events after this tick (freezes a live "
                                                             "feed so variants compare on the same data)")
    ap.add_argument("--days", default=None, help="comma list of days to run (default: every day in the feed)")
    ap.add_argument("--limit", type=int, default=None, help="run only the first N cases (smoke test)")
    ap.add_argument("--timeout-s", type=float, default=300.0, help="wall-clock ceiling per day replay and per case")
    ap.add_argument("--out-root", default=None, help="write evals here instead of evals/ (required for oracle, "
                                                     "null and reckless)")
    ap.add_argument("--cases-only", action="store_true", help="write cases.jsonl, cases.md and _state.json, then stop")
    ap.add_argument("--refresh-cases", action="store_true", help="rewrite cases.jsonl from the current logs "
                                                                 "(it is the signed-off list: use with care)")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), default=None, help="paired deltas B - A and exit")
    md.add_config_args(ap)
    ap.add_argument("--team-venues", dest="no_team_venues", action="store_false",
                    help="also take offers on other teams' venues (baseline, like Sunday's factory: El Rastro only)")
    ap.set_defaults(no_team_venues=True)
    args = ap.parse_args()

    if args.out_root:
        ec.EVALS = Path(args.out_root).resolve()
    if args.compare:
        print(compare(ec.EVALS, *args.compare))
        return
    if args.policy != "desk" and not args.out_root:
        raise SystemExit("harness-check policies write only under --out-root, never evals/")
    variant = ec.check_variant(args.variant)
    cfg = md.build_config(args)
    logs = Path(args.logs)
    events, me, catalog, feeds = load_inputs(logs, args.feed)
    if args.to_tick is not None:
        events = [e for e in events if (e.get("tick") or 0) <= args.to_tick]
    last_tick = max((e["tick"] for e in events if isinstance(e.get("tick"), int)), default=0)
    ctx = Context(events, catalog, me)
    days = day_windows(events)
    if args.days:
        want = {d.strip() for d in args.days.split(",") if d.strip()}
        days = [d for d in days if d[0] in want]
    print(f"{len(events)} feed events from {', '.join(map(str, feeds))}; days "
          + ", ".join(f"{d} t{a}-{b}" for d, a, b in days) + f"; holdings from {logs / 'state' / 'me.json'} "
          f"(tick {me.get('tick')}) moved by our public settlements")

    flow = ec.flow_dir(FLOW)
    cases = build_cases(events, me, catalog, cfg, ctx, days)
    ec.write_state(FLOW, METRICS, PERF_FIELDS, {
        "headline": "surplus_P",
        "case_unit": "one (day, card) opportunity window, graded from a whole-day replay of the public feed",
        "grader": "tools/eval_market.py (programmatic; fills are plausible, not observed)"})
    signed = flow / "cases.jsonl"
    columns = ["day", "card", "listings", "best_ask", "bids", "best_bid", "real_trades", "real_prices"]
    title = "Market desk eval cases: one (day, card) opportunity window"
    if not signed.exists() or args.refresh_cases:
        ec.write_cases(FLOW, [public_case(c) for c in cases], title, columns)
    else:
        ids = {json.loads(x)["id"] for x in signed.read_text().splitlines() if x.strip()}
        new = [c["id"] for c in cases if c["id"] not in ids]
        gone = sorted(ids - {c["id"] for c in cases})
        if new:
            print(f"note: {len(new)} cases in these logs are not in the signed-off cases.jsonl (not run): "
                  + ", ".join(new[:12]) + (" ..." if len(new) > 12 else "") + " (--refresh-cases to add them)")
        if gone and not args.days:
            print(f"note: {len(gone)} signed-off cases have no data in these logs: " + ", ".join(gone[:12]))
        cases = [c for c in cases if c["id"] in ids]
    if args.cases_only:
        print(f"wrote {flow / 'cases.jsonl'} ({len(cases)} cases) and {flow / '_state.json'}")
        return
    if args.limit:
        cases = cases[:args.limit]

    sha = ec.file_sha(ROOT / "agent" / "market_desk.py")
    if args.policy == "desk":
        model = f"market_desk.py@{sha}+{config_label(cfg)}+cash={args.cash}+feed<=t{last_tick}"
    else:
        model = (f"policy:{args.policy}@eval_market.py@{ec.file_sha(Path(__file__))}+cash={args.cash}"
                 f"+floor={args.floor}+feed<=t{last_tick}")
    run = ec.Run(FLOW, variant, model, change=args.change)
    prior = {r.get("model") for r in run.all_rows()}
    if prior and prior != {model}:
        raise SystemExit(f"{run.results} was written by {sorted(prior)}, not {model}: use a new variant "
                         f"(or move the old results away)")
    system = (f"policy: {args.policy} ({model})\nengine: tools/market_replay.py replay, decide() wrapped by "
              f"tools/eval_market.py (venue fees/owners, released sets and game hours from the feed)\n"
              f"cash at day start {args.cash} · grader floor {args.floor} · missed-good threshold {args.missed_min} P\n"
              f"private: this trace holds our values and stays out of git")
    pol = make_policy(args.policy, ctx, args.floor)
    for day, t0, t1 in days:
        todo = [c for c in cases if c["day"] == day]
        for rep in range(args.reps):
            pending = [c for c in todo if (c["id"], rep) not in run.done]
            if not pending:
                continue
            err = None
            try:
                with ec.ceiling(args.timeout_s):
                    rr, rec = replay_day(events, me, catalog, cfg, args.cash, ctx, pol, t0, t1)
                    led = day_ledger(rr, rec, ctx, args.cash)
            except Exception as e:  # noqa: BLE001 - every case of the day records the failure through Run.case
                err = e
            for c in pending:
                def fn(c=c):
                    if err is not None:
                        raise err
                    return grade_case(c, rr, rec, led, ctx, floor=args.floor, missed_min=args.missed_min,
                                      system=system + f"\nday {day} ticks {t0}-{t1} · rep {rep}")
                run.case(c["id"], rep, prompt_of(c), c["tags"], fn, timeout_s=args.timeout_s)
    rows = run.all_rows()
    if args.reps > 1:
        by: dict = {}
        for r in rows:
            by.setdefault(r["prompt_id"], set()).add(json.dumps(r["grade"], sort_keys=True))
        drift = [cid for cid, gs in by.items() if len(gs) > 1]
        print("determinism: " + (f"{len(drift)} cases differ across reps: {drift[:8]}" if drift else
                                 "every rep graded the same"))
    print(summarize(variant, rows))
    errs = run.errors.read_text().splitlines() if run.errors.exists() else []
    if errs:
        print(f"{len(errs)} failed attempts in {run.errors}")


if __name__ == "__main__":
    main()
