"""One fair price for every Team 3 tool: La Celestina (tools/celestina.py) and its concierge (tools/concierge.py).

Pure functions over public settlements (the feed's `settlement` payloads), stdlib only, no I/O.

- fair_price(): the Celestina rule. A card's fair price is the median of its last 5 team-to-team single-card cash
  trades. A dealer is another market: what it pays a team for a card is the dealer's buy price (a floor), what it
  charges is its sell price (a ceiling), and neither is a fair price between teams. Dealer prices are used only when
  fewer than 2 team trades exist, and the text and `basis` then say whose price it is.
- price_range(): the concierge's range, the 25th to 75th percentile of public team trades, returned by fair_price()
  as its second field, `range`.
"""
from __future__ import annotations

import math
import re
import statistics

REF_N = 5                  # fair price = median of the last 5 team-to-team trades
RANGE_N = 15               # the range looks at up to the last 15 team-to-team trades
DEALER_NAMES = {"abuela": "Abuela", "chato": "El Chato", "pilar": "Pilar"}
TEAM_RE = re.compile(r"^t\d+$")


def num(x) -> float:
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e9 else 0


def percentile(xs, q: float) -> float:
    """Linear interpolation between the closest ranks (agent/market_desk.py's percentile)."""
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def price_range(prices) -> dict | None:
    """The 25th to 75th percentile of some prices, rounded to whole primas: {low, median, high, trades}; None when
    there are none."""
    ps = [p for p in prices if num(p) > 0]
    if not ps:
        return None
    lo, mid, hi = (round(percentile(ps, q)) for q in (0.25, 0.5, 0.75))
    return {"low": lo, "median": mid, "high": hi, "trades": len(ps)}


def cash_trade(payload: dict, tick=None) -> dict | None:
    """One settlement payload as a single-card cash trade, or None (bundles of different cards, swaps, no price).
    k copies of one card from one party to another count at price / k. `side` is "team" (team to team),
    "dealer_buys" (a team sold to a dealer: the dealer's buy price) or "dealer_sells" (a dealer sold to a team).
    A dealer is the settlement's persona, or any party that is not a team (a settlement that forgot its persona)."""
    p = payload if isinstance(payload, dict) else {}
    items = [i for i in p.get("items") or [] if isinstance(i, dict)]
    if not items or any(i.get("kind", "card") != "card" for i in items) or num(p.get("price")) <= 0:
        return None
    if len({i.get("ref") for i in items}) != 1 or len({i.get("frm") for i in items}) != 1 \
            or len({i.get("to") for i in items}) != 1 or not isinstance(items[0].get("ref"), str):
        return None
    i = items[0]
    dealer = p.get("persona") or next((x for x in (i.get("frm"), i.get("to"))
                                       if isinstance(x, str) and not TEAM_RE.match(x)), None)
    side = "team" if not dealer else "dealer_sells" if i.get("frm") == dealer else "dealer_buys"
    return {"ref": i["ref"], "settlement": p.get("settlement"), "tick": p.get("tick", tick),
            "price": round(num(p["price"]) / len(items), 1), "qty": len(items), "venue": p.get("venue"),
            "dealer": dealer, "side": side, "frm": i.get("frm"), "to": i.get("to")}


def cash_trades(events) -> dict:
    """ref -> its single-card cash trades from feed events, oldest first (events sorted by id)."""
    out: dict = {}
    for e in sorted((e for e in events if isinstance(e, dict) and e.get("type") == "settlement"),
                    key=lambda e: e.get("id") or 0):
        row = cash_trade(e.get("payload") or {}, e.get("tick"))
        if row is not None:
            out.setdefault(row["ref"], []).append(row)
    return out


def fair_price(recent, n: int = REF_N, range_n: int = RANGE_N) -> dict:
    """A card's fair price from its trades, NEWEST FIRST: {price, n, basis, text, range}. `basis` is "teams", or
    "dealer_buys" / "dealer_sells" when it falls back to a dealer's price. `range` is price_range() of the team-to-team
    trades (None without any): dealer trades never enter it."""
    recent = [r for r in recent or [] if isinstance(r, dict) and num(r.get("price")) > 0]
    team_all = [r["price"] for r in recent if r.get("side", "team") == "team"]
    rng = price_range(team_all[:range_n])
    team = team_all[:n]
    if len(team) >= 2:
        p = round(statistics.median(team), 1)
        return {"price": p, "n": len(team), "basis": "teams",
                "text": f"about {p:g} P (last team-to-team trades: {', '.join(f'{x:g}' for x in team)})", "range": rng}
    out, parts = None, []
    for side in ("dealer_buys", "dealer_sells"):
        rows = [r for r in recent if r.get("side") == side][:n]
        if not rows:
            continue
        p = round(statistics.median(r["price"] for r in rows), 1)
        name = DEALER_NAMES.get(rows[0].get("dealer"), str(rows[0].get("dealer")).title())
        parts.append(f"{name} pays about {p:g} P for it" if side == "dealer_buys" else f"{name} sells it for about {p:g} P")
        out = out or {"price": p, "n": len(rows), "basis": side}
    if out:
        return {**out, "text": "; ".join(parts) + " (no team-to-team trades yet)", "range": rng}
    if team:
        return {"price": team[0], "n": 1, "basis": "teams", "text": f"about {team[0]:g} P (one team-to-team trade)",
                "range": rng}
    return {"price": None, "n": 0, "basis": None, "text": None, "range": None}
