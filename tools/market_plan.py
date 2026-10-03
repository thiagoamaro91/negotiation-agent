"""Team 3's market plan, recomputed from scratch on every run: what to sell, buy and hold, at what price and WHEN.
Plans only: it never lists, accepts, cancels or sends anything. Every move needs a yes in the team chat.

It scores moves the way the game scores them (kit/RULES.md, Scoring). Holdings and cash never score; two things do:
- a TEAM TRADE scores the value we gain at our private values: value - price - fee for a buy, price - fee - the value
  of that copy for a sale (a second copy is worth 25 %, a third 10 %); the fee only when we are the side that accepts.
  These are the sells and buys, in P.
- a DEALER DEAL scores on the ladder: the share of the dealer's price range we capture, our best three deals per
  level. The range is secret, so the share is an ESTIMATE from the closes measured in the feed (tools/price_index.py).
  These are the dealer rows, in share of range, never in P.
A completed page's bonus counts only if the desk confirms it enters a trade's value (BRAIN_PAGE_BONUS=1); until then
no card is held for a page and no page is counted in any value.

How a team trade is planned. For every card and every moment (now, or when the next day opens) it estimates, team by
team, the chance that a team takes our price:
- would they value it at that price? the inferred distribution of their multiplier (tools/value_inference.py), pulled
  toward the uniform prior by how well the model predicted out of sample (`shrink`), with the copy marginal;
- can they pay it? their cash, rebuilt exactly from the public feed (tools/ledger.py), plus the next day's grant;
- could they buy it cheaper from a dealer? a team pays at most ~10 % over the highest close a dealer gives for it;
- are they active? a team with no public move in ACTIVE_TICKS ticks counts for little.
Expected gain = chance of a sale x gain x the round's weight (Friday counts half). A listing posted tonight that does
not sell tonight carries over to tomorrow, so "list now" is worth
P(tonight) x gain x 0.5 + (1 - P(tonight)) x P(tomorrow) x gain x 1, and "list tomorrow" is P(tomorrow) x gain x 1.
Every chance is an estimate and is capped at P_CAP.

Inputs (no key): the public feed and El Rastro board saved by tools/feed_recorder.py (BAZAAR_FEED=<dir> to read another
clone), the live board, catalog, clock, schedule and dealers (keyless, cached in logs/public/), and our private values
from logs/state/me.json; our cards = that snapshot + our public settlements, our cash = the ledger (exact).

    python3 tools/market_plan.py                # the plan now
    python3 tools/market_plan.py --json         # the same as data (for the dashboard)
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger as ledger_mod  # noqa: E402
import price_index  # noqa: E402
import value_inference as vi  # noqa: E402

CASH_RESERVE = 280          # level-2 venue bond 250 + 20 (README): kept while we have no venue of our own
VENUE_OPEN_RESERVE = 40     # with our venue open the bond is spent: the team's floor (plan v2.1, Saturday 17:16)
MIN_GAIN = 3.0              # smallest gain (P, after fees) worth one of our listings or our single accept per tick
ATTENTION = 0.5             # chance an interested team notices and takes our offer within one session
ACTIVE_TICKS = 40           # a team with no public move in this many ticks is treated as mostly idle
IDLE_FACTOR = 0.3
STILL_THERE = 0.6           # chance a standing bid or ask is still on the board when the next day opens
ACCEPT_P = 0.9              # chance our accept of a standing offer lands (someone may take or cancel it first)
P_CAP = 0.9                 # no estimated chance is shown above this: the model's own scorecard is ~42 % vs 40 % naive
DEALER_PREMIUM = 1.1        # a team pays at most ~10 % over the highest close a dealer gives for that rarity
LADDER_SLOTS = 3            # best three deals per level count (kit/RULES.md); a missing one counts zero
LADDER_PER_DAY = True       # slots counted since the day opened: each day is a round (unconfirmed: ask the desk)
LADDER_VALUE_GATE = True    # a dealer deal on the wrong side of our value scores 0: on Friday our Chato SAL-08 at 29
                            # (worth 32.5) scored and LAT-06 at 28 / LAT-07 at 29 (worth 27.5) did not (analysis-friday 6)
PAGE_BONUS_ENV = "BRAIN_PAGE_BONUS"   # =1 once the desk confirms the page bonus counts in a trade's value; off by default
PAGE_MAX_MISSING = 3        # with the bonus confirmed, a page is a target when at most this many cards are missing
ROUND_WEIGHT = {"fri": 0.5, "sat": 1.0, "sun": 1.0}
DAY_START_HOURS = {"sat": 4.0, "sun": 18.0}
LIQUIDATE_FROM_HOURS = 21.0  # game hours (Sunday ~12:00): stop holding for pages, sell what others value more
PAGE_CARDS = 10             # a page is a set's commons, uncommons and rares: cards 01-10
UNKNOWN_HOLDER = "?"        # copies minted but not seen in anyone's hands: a holder with no known preferences


# ---------------------------------------------------------------- pure rules

def fee(price: float, cards: int = 1) -> int:
    """El Rastro's fee: ceil(5 % of the price) + 1 P per card, paid by whoever accepts."""
    return math.ceil(0.05 * price) + cards


def copy_value(book: float, mult: float, copy_index: int, marginals: list) -> float:
    """Value of the copy_index-th copy (0 = first) of a card."""
    return book * mult * marginals[min(copy_index, len(marginals) - 1)]


def p_value_at_least(dist: dict, book: float, marginal: float, threshold: float) -> float:
    """Chance a team values a card at `threshold` or more, given the distribution of its set multiplier."""
    return sum(p for m, p in dist.items() if book * float(m) * marginal >= threshold)


def p_value_at_most(dist: dict, book: float, marginal: float, threshold: float) -> float:
    return sum(p for m, p in dist.items() if book * float(m) * marginal <= threshold)


def any_of(probs: list) -> float:
    """Chance that at least one of several independent takers says yes."""
    q = 1.0
    for p in probs:
        q *= 1.0 - max(0.0, min(1.0, p))
    return 1.0 - q


def carry_over(p_now: float, w_now: float, p_next: float, w_next: float) -> float:
    """Weighted chance of a sale for an offer posted now that stays up into the next session if it does not fill."""
    return cap(p_now * w_now + (1.0 - p_now) * p_next * w_next)


def cap(p: float) -> float:
    """An estimated chance, never shown as a certainty."""
    return max(0.0, min(P_CAP, p))


def trade_gain(side: str, price: float, value: float, we_accept: bool) -> float:
    """What a team trade scores for us, in P at our private values: a buy gains value - price, a sale price - value
    (`value` = that copy's value: 25 % for a second copy); the fee is ours only when we accept the other side's offer."""
    f = fee(price) if we_accept else 0
    return (value - price - f) if side == "buy" else (price - f - value)


def ladder_slots(shares: list, slots: int = LADDER_SLOTS) -> list:
    """Our best `slots` ladder shares at one level, best first; a missing deal counts 0."""
    return (sorted(shares, reverse=True) + [0.0] * slots)[:slots]


def ladder_gain(slots: list, share: float) -> float:
    """How much a new deal with `share` raises the level's average over its best slots (0 if it beats none)."""
    return max(0.0, share - min(slots)) / len(slots) if slots else 0.0


# ---------------------------------------------------------------- the world as the files and the public API show it

def live_board(events: list) -> tuple[list, str]:
    """Open offers on El Rastro, makers translated from pseudonyms to teams via the feed's offer.listed. Live keyless
    read first, the recorder's last snapshot if the server is unreachable."""
    makers = {}
    for e in events:
        o = e["payload"].get("offer")
        if e["type"] == "offer.listed" and isinstance(o, dict):
            makers[o["id"]] = o.get("maker")
    try:
        with urllib.request.urlopen(f"{vi.URL}/api/venues/rastro/offers", timeout=10) as r:
            body, source = json.load(r), "live"
    except OSError:
        snaps = [s for s in vi.rows("snapshots.jsonl") if s.get("what") == "rastro"]
        body = snaps[-1]["body"] if snaps else {"offers": []}
        source = f"recorder snapshot (tick {snaps[-1]['tick'] if snaps else '?'})"
    offers = body.get("offers", body) if isinstance(body, dict) else body
    out = []
    for o in offers:
        if o.get("status") not in (None, "open"):
            continue
        give, want = o.get("give") or {}, o.get("want") or {}
        team = makers.get(o["id"], "?")
        gives = [a.get("ref") for a in give.get("assets") or [] if isinstance(a, dict)]
        wants = vi.card_types(want)
        if len(gives) == 1 and want.get("cash") and not wants and not want.get("assets"):
            out.append({"kind": "ask", "ref": gives[0], "price": want["cash"], "team": team, "id": o["id"], "to": o.get("to")})
        elif len(wants) == 1 and give.get("cash") and not gives:
            out.append({"kind": "bid", "ref": wants[0], "price": give["cash"], "team": team, "id": o["id"], "to": o.get("to")})
    return out, source


def activity(events: list, now_tick: int) -> dict:
    """team -> 1.0 if it made a public move in the last ACTIVE_TICKS ticks, else IDLE_FACTOR."""
    last = {}
    for e in events:
        p = e["payload"]
        who = set()
        if e["type"] in ("thread.opened", "thread.message"):
            who.add(p.get("team"))
        elif e["type"] == "offer.listed" and isinstance(p.get("offer"), dict):
            who.add(p["offer"].get("maker"))
        elif e["type"] == "settlement":
            who.update(p.get("parties") or [])
        for t in who:
            if t:
                last[t] = e["tick"]
    return collections.defaultdict(lambda: IDLE_FACTOR,
                                   {t: 1.0 if now_tick - tk <= ACTIVE_TICKS else IDLE_FACTOR for t, tk in last.items()})


def dealer_menu(dealers: dict) -> dict:
    """rarity -> [(list price, dealer id, open to all?, game hour it opens to all)] for active dealers, cheapest first."""
    out = collections.defaultdict(list)
    for d in dealers.get("personas", []):
        if d.get("status") != "active" or not d.get("enabled", True):
            continue
        at = (d.get("unlock") or {}).get("open_to_all_at")
        opens = None
        if isinstance(at, str):
            try:
                opens = float(at.strip("+h"))
            except ValueError:
                opens = None
        always = bool((d.get("unlock") or {}).get("always"))
        for item in (d.get("menu") or {}).get("sells", []):
            if item.get("rarity") and item.get("list_price"):
                out[item["rarity"]].append((item["list_price"], d["id"], always or bool(d.get("open_to_all")), opens))
    for r in out:
        out[r].sort()
    return out


def horizons(clock: dict, schedule: dict) -> list:
    """The moments a decision can be taken: now, and the opening of the next day if there is one."""
    day = clock.get("today") or "fri"
    hours = clock.get("t_hours") or schedule.get("now_hours") or 0
    upcoming = schedule.get("upcoming", [])
    nxt = {"fri": "sat", "sat": "sun"}.get(day)
    now = {"key": "now", "label": f"now ({day})", "weight": ROUND_WEIGHT.get(day, 1.0), "grant": 0, "hours": hours,
           "session": 1.0 if clock.get("doors") == "open" else 0.0}
    out = [now]
    if nxt:
        start = DAY_START_HOURS[nxt]
        grant = sum((u.get("params") or {}).get("cash", 0) for u in upcoming
                    if u.get("action") == "grant_all" and start <= u["at_hours"] < start + 0.5)
        out.append({"key": f"{nxt}-open", "label": f"{nxt} 09:00", "weight": ROUND_WEIGHT[nxt], "grant": grant,
                    "hours": start, "session": 1.0})
    return out


# ---------------------------------------------------------------- the plan

def deal_share(row: dict | None, price: float, opening: float | None, value: float | None) -> float | None:
    """ESTIMATED ladder share of one dealer deal: 0 at the dealer's opening price (RULES: it does not count), 0 on the
    wrong side of our value when LADDER_VALUE_GATE (a buy above it, a sale below it), else the share of the measured
    range; None when the range is unknown. `value` = our value of that copy (None for packs: luck is not valued)."""
    if opening is not None and price == opening:
        return 0.0
    if row is None:
        return None
    if LADDER_VALUE_GATE and value is not None and (price > value if row["side"] == "sells" else price < value):
        return 0.0
    return price_index.ladder_share(row, price)


def our_ladder(events: list, dprices: dict, kind_of, since_tick: int, value_of) -> dict:
    """dealer -> our deals with it since `since_tick`, each with its estimated ladder share (deal_share).
    value_of(ref, side) -> our value of that copy, or None."""
    out = collections.defaultdict(list)
    for d in price_index.dealer_deals(events, kind_of):
        if d["team"] != vi.US or d["tick"] < since_tick:
            continue
        row = dprices.get(price_index.key_of(d["dealer"], d["side"], d["kind"]))
        share = deal_share(row, d["price"], d["opening"], value_of(d["ref"], d["side"]))
        out[d["dealer"]].append({"tick": d["tick"], "ref": d["ref"], "side": d["side"], "price": d["price"], "share": share})
    return out


def day_start_tick(events: list) -> int:
    """The tick the current day opened (0 if the feed shows no opening)."""
    return max((e["tick"] for e in events if e["type"] == "day.opened"), default=0)


def page_bonus_on() -> bool:
    """Read at every plan (the brain loads its settings file after importing this module)."""
    return os.environ.get(PAGE_BONUS_ENV) == "1"


def cash_reserve(our_ledger: dict) -> int:
    """Cash we never plan to spend: the venue bond while we have no venue, the team's floor once ours is open."""
    return VENUE_OPEN_RESERVE if our_ledger.get("venue") else CASH_RESERVE


def plan(split: dict | None = None) -> dict:
    bonus_on = page_bonus_on()
    model, by_team, events, book = vi.load()
    cat = vi.catalog()
    clock, schedule, dealers = vi.public("clock", True), vi.public("schedule", True), vi.public("dealers", True)
    marginals = cat["values"]["copy_marginals"]
    page_bonus = cat["values"]["page_bonus"]
    rarity, kind_of, kind_of_topic = price_index.card_kinds(cat)
    minted = {c["id"]: c.get("minted") or 0 for s in cat["sets"] for c in s["cards"]}
    released = {s["id"] for s in cat["sets"] if s.get("released")}
    me = vi.load_me()
    ours = me["affinity"]
    mine = vi.our_cards(me, events)
    led = ledger_mod.build(events, schedule)
    cash, cash_source = led[vi.US]["cash"], "ledger"
    chk = ledger_mod.check_us(led)
    if chk is not None and not chk["ok"]:  # the rebuild disagrees with the real account: trust the account
        cash, cash_source = me["cash"], f"account at tick {chk['tick']} (ledger check failed: {chk['rebuilt']} P rebuilt)"
    now_tick = events[-1]["tick"]
    hz = horizons(clock, schedule)
    liquidate = hz[0]["hours"] >= LIQUIDATE_FROM_HOURS
    teams = sorted(set(by_team) - {vi.US})
    res = {t: model.summary(model.posterior(by_team[t]), by_team[t]) for t in teams}
    split = split or model.time_split(by_team)
    lam = split["shrink"]
    prior = {m: 1 / len(vi.MULTS) for m in vi.MULTS}
    held = vi.holdings(events, set(by_team))
    act = activity(events, now_tick)
    board, board_source = live_board(events)
    menu = dealer_menu(dealers)
    dprices = price_index.dealer_prices(events, kind_of, kind_of_topic, dealers)
    unlocked = {t: set(led[t]["unlocked"]) for t in led}
    reserve = cash_reserve(led[vi.US])
    free_now = cash - reserve
    calibrated = {t: {s: vi.shrink(res[t]["dist"][s], lam) for s in model.sets} for t in teams}

    def dist(team: str, s: str) -> dict:
        return prior if team == UNKNOWN_HOLDER else calibrated[team][s]

    def can_deal(team: str, did: str, open_all: bool, opens, h: dict) -> bool:
        return open_all or did in unlocked.get(team, set()) or (opens is not None and h["hours"] >= opens)

    def dealer_for(team: str, kind: str, h: dict) -> dict | None:
        """The measured price row of the dealer that sells this kind most cheaply to `team` at horizon h."""
        rows = [dprices.get(price_index.key_of(did, "sells", kind)) for _, did, open_all, opens in menu.get(kind, [])
                if can_deal(team, did, open_all, opens, h)]
        rows = [r for r in rows if r]
        return min(rows, key=lambda r: r["median"]) if rows else None

    def p_buyer(team: str, ref: str, price: int, h: dict) -> float:
        need = price + fee(price)
        if led[team]["cash"] + h["grant"] < need:
            return 0.0
        d = dealer_for(team, rarity[ref], h)
        if d is not None and need > d["high"] * DEALER_PREMIUM:
            return 0.0
        k = held[team][ref]
        return p_value_at_least(dist(team, vi.set_of(ref)), book[ref], marginals[min(k, len(marginals) - 1)], need) * act[team]

    def p_sale(ref: str, price: int, h: dict) -> float:
        return cap(any_of([ATTENTION * h["session"] * p_buyer(t, ref, price, h) for t in teams]))

    def best_ask(ref: str, keep: float) -> dict | None:
        """The price and moment with the highest expected weighted gain for a listing of ours (the buyer accepts: no fee)."""
        lo = math.ceil(keep + MIN_GAIN)
        hi = int(book[ref] * max(vi.MULTS) * 1.0) + 1
        best = None
        for price in range(lo, max(lo, hi) + 1):
            g = trade_gain("sell", price, keep, we_accept=False)
            pn = p_sale(ref, price, hz[0])
            pt = p_sale(ref, price, hz[1]) if len(hz) > 1 else 0.0
            options = [("list now", carry_over(pn, hz[0]["weight"], pt, hz[1]["weight"]) if len(hz) > 1
                        else pn * hz[0]["weight"], cap(pn + (1 - pn) * pt), 0)]  # chance it sells tonight or, carried over, tomorrow
            if len(hz) > 1:
                options.append((f"list at {hz[1]['label']}", pt * hz[1]["weight"], pt, 1))
            for label, wp, p, hi_ in options:
                ev = wp * g
                if best is None or ev > best["ev"]:
                    best = {"action": label, "price": price, "gain": round(g, 1), "p": round(p, 2), "ev": round(ev, 1),
                            "horizon": hi_}
        return best if best and best["ev"] >= MIN_GAIN * 0.5 else None

    # ---- pages: information only, unless the desk confirms the bonus counts in a trade's value
    pages = []
    for s in sorted(released):
        refs = [f"{s}-{n:02d}" for n in range(1, PAGE_CARDS + 1) if f"{s}-{n:02d}" in book]
        missing = [r for r in refs if mine[r] <= 0]
        bonus = page_bonus * sum(copy_value(book[r], ours[s], 0, marginals) for r in refs)
        pages.append({"set": s, "have": len(refs) - len(missing), "of": len(refs), "missing": missing,
                      "bonus_if_confirmed": round(bonus), "bonus_counted": bonus_on,
                      "target": bonus_on and not liquidate and 0 < len(missing) <= PAGE_MAX_MISSING
                      and ours[s] >= 1.3})
    target_sets = {p["set"] for p in pages if p["target"]}

    # ---- team trades: sells (value gained at our private values)
    sells, holds = [], []
    for ref, k in sorted(mine.items()):
        if k <= 0 or ref not in book:
            continue
        s = vi.set_of(ref)
        keep = copy_value(book[ref], ours[s], k - 1, marginals)
        if k == 1:  # never propose selling our last copy of a card
            if s in target_sets:
                holds.append({"ref": ref, "why": f"first copy on the {s} page (page bonus confirmed, {PAGE_MAX_MISSING} or fewer missing)"})
            continue
        option = best_ask(ref, keep)
        bids = sorted((o for o in board if o["kind"] == "bid" and o["ref"] == ref and o["team"] != vi.US
                       and o["to"] in (None, vi.US)), key=lambda o: -o["price"])
        if bids:
            b = bids[0]
            g = trade_gain("sell", b["price"], keep, we_accept=True)
            alts = [("accept bid now", ACCEPT_P * g * hz[0]["weight"] * hz[0]["session"], ACCEPT_P)]
            if len(hz) > 1:
                alts.append((f"accept bid at {hz[1]['label']}", ACCEPT_P * STILL_THERE * g * hz[1]["weight"], ACCEPT_P * STILL_THERE))
            label, ev, p = max(alts, key=lambda x: x[1])
            if g >= MIN_GAIN and (option is None or ev >= option["ev"]):
                option = {"action": label, "price": b["price"], "gain": round(g, 1), "p": round(p, 2), "ev": round(ev, 1),
                          "offer": b["id"], "counterparty": b["team"], "horizon": 0 if "now" in label else 1}
        if option is None:
            continue
        h_sel = {**hz[min(option.get("horizon", 0), len(hz) - 1)], "session": 1.0}
        takers = sorted(((t, cap(ATTENTION * p_buyer(t, ref, option["price"], h_sel))) for t in teams), key=lambda x: -x[1])
        option.update(ref=ref, copy="spare" if k > 1 else "first", our_value=round(keep, 1), scores="team trade",
                      likely_buyers=[{"team": t, "p": round(p, 2), "cash": led[t]["cash"]} for t, p in takers[:3] if p > 0])
        sells.append(option)

    # ---- team trades: buys (only cards we lack: a second copy is worth 25 %)
    buys = []
    for ref in sorted(book):
        s = vi.set_of(ref)
        if s not in released or int(ref.split("-")[1]) > PAGE_CARDS or mine[ref] > 0:
            continue
        page = next(p for p in pages if p["set"] == s)
        completes = page["missing"] == [ref]
        value = copy_value(book[ref], ours[s], 0, marginals) + (page["bonus_if_confirmed"] if completes and bonus_on else 0)
        options = []
        for o in board:
            if o["kind"] == "ask" and o["ref"] == ref and o["team"] != vi.US and o["to"] in (None, vi.US):
                g = trade_gain("buy", o["price"], value, we_accept=True)
                options.append({"action": "accept ask now", "price": o["price"], "gain": round(g, 1), "p": ACCEPT_P,
                                "ev": round(ACCEPT_P * g * hz[0]["weight"], 1), "counterparty": o["team"], "offer": o["id"],
                                "cost": o["price"] + fee(o["price"]), "when": "now"})
        hold_teams = [t for t in teams if held[t][ref] > 0]
        unseen = max(0, minted.get(ref, 0) - sum(held[t][ref] for t in teams) - mine[ref])
        sellers = [(t, held[t][ref]) for t in hold_teams] + [(UNKNOWN_HOLDER, 1)] * min(unseen, 3)
        if sellers:
            for h in hz:
                best = None
                for bid in range(1, int(value - MIN_GAIN) + 1):
                    p = cap(any_of([ATTENTION * h["session"] * (act[t] if t != UNKNOWN_HOLDER else 0.5)
                                    * p_value_at_most(dist(t, s), book[ref], marginals[min(n - 1, len(marginals) - 1)],
                                                      bid - fee(bid))
                                    for t, n in sellers]))
                    g = trade_gain("buy", bid, value, we_accept=False)
                    ev = p * g * h["weight"]
                    if best is None or ev > best["ev"]:
                        best = {"action": "bid" + ("" if h["key"] == "now" else f" at {h['label']}"), "price": bid,
                                "gain": round(g, 1), "p": round(p, 2), "ev": round(ev, 1),
                                "counterparty": ", ".join(t if t != UNKNOWN_HOLDER else "unseen copy" for t, _ in sellers[:3]),
                                "cost": bid, "when": h["key"]}
                if best:
                    options.append(best)
        options = [o for o in options if o["gain"] >= MIN_GAIN and o["p"] >= 0.05 and o["ev"] >= 0.5]
        if not options:
            continue
        best = max(options, key=lambda o: o["ev"])
        best.update(ref=ref, our_value=round(value, 1), minted=minted.get(ref), scores="team trade",
                    page_target=s in target_sets, completes_page=completes)
        buys.append(best)

    # ---- dealer deals: the ladder (estimated share of the dealer's range, never P)
    since = day_start_tick(events) if LADDER_PER_DAY else 0

    def value_of(ref: str, side: str) -> float | None:
        """Our value of the copy a past dealer deal moved: a card bought = a first copy; a card sold = a spare when we
        still hold one, else the first copy. Packs: None."""
        if ref not in book:
            return None
        k = 0 if side == "sells" else (1 if mine[ref] >= 1 else 0)
        return copy_value(book[ref], ours[vi.set_of(ref)], k, marginals)

    ladder = our_ladder(events, dprices, kind_of, since, value_of)
    slots = {d: ladder_slots([x["share"] or 0.0 for x in ladder.get(d, [])]) for d in {r["dealer"] for r in dprices.values()}}
    sold_to_teams = {s["ref"] for s in sells}
    dealer_rows = []
    for key, r in sorted(dprices.items()):
        did, side, kind = r["dealer"], r["side"], r["kind"]
        entry = next((x for x in menu.get(kind, []) if x[1] == did), None)
        access = [h for h in hz if h["session"] > 0 and (entry is None or can_deal(vi.US, did, entry[2], entry[3], h))]
        if not access or (side == "sells" and entry is None and not kind.startswith("pack:")):
            continue
        if side == "sells":  # we buy: pay the median close (rounded up), the cards we lack first
            price = math.ceil(r["median"])
            cards = sorted((ref for ref in book if rarity[ref] == kind and vi.set_of(ref) in released and mine[ref] <= 0),
                           key=lambda ref: -copy_value(book[ref], ours[vi.set_of(ref)], 0, marginals))
            cand = [{"ref": ref, "value": round(copy_value(book[ref], ours[vi.set_of(ref)], 0, marginals), 1),
                     "below_value": price <= copy_value(book[ref], ours[vi.set_of(ref)], 0, marginals)} for ref in cards[:3]]
            if not kind.startswith("pack:") and not cand:
                continue
            steps = range(int(r["low"]), int(math.ceil(r["median"])) + 1)
            action, cost = f"buy from {did}", price
        else:  # we sell: the median close (rounded down), our least valuable spares of that rarity first
            price = math.floor(r["median"])
            spares = sorted(((ref, k) for ref, k in mine.items() if k > 1 and rarity.get(ref) == kind),
                            key=lambda x: copy_value(book[x[0]], ours[vi.set_of(x[0])], x[1] - 1, marginals))
            cand = [{"ref": ref, "value": round(copy_value(book[ref], ours[vi.set_of(ref)], k - 1, marginals), 1),
                     "below_value": price >= copy_value(book[ref], ours[vi.set_of(ref)], k - 1, marginals),
                     "in_team_sells": ref in sold_to_teams} for ref, k in spares[:3]]
            if not cand:
                continue
            steps = range(int(math.floor(r["median"])), int(r["high"]) + 1)
            action, cost = f"sell to {did}", 0
        reliable = r["source"] in ("measured", "fallback")  # one close, or a list price, gives no range to speak of
        below = any(c["below_value"] for c in cand) if cand else None
        share = price_index.ladder_share(r, price) if reliable else None
        counted = 0.0 if share is None or (LADDER_VALUE_GATE and below is False) else share
        when = access[0]["key"]
        dealer_rows.append({
            "action": action + ("" if when == "now" else f" at {access[0]['label']}"),
            "dealer": did, "side": side, "kind": kind, "price": price, "cost": cost, "when": when,
            "opening": r["opening"], "low": r["low"], "median": r["median"], "high": r["high"], "n": r["n"], "source": r["source"],
            "share": share, "ladder": [{"price": x, "share": price_index.ladder_share(r, x)} for x in steps][:12] if reliable else [],
            "slots": [round(x, 2) for x in slots.get(did, ladder_slots([]))],
            "adds": round(ladder_gain(slots.get(did, ladder_slots([])), counted), 3),
            "below_value": below, "cards": cand, "scores": "dealer ladder (estimate)"})
    dealer_rows.sort(key=lambda d: (d["below_value"] is not True, -d["adds"], -(d["share"] or 0), d["price"]))

    # cash: certain team buys first (accepting a listed ask), then dealer buys by ladder gain, then team bids by
    # expected gain; sales are not counted until they land
    left = {"now": free_now}
    for h in hz[1:]:
        left[h["key"]] = free_now + h["grant"]
    order = ([b for b in buys if b["action"].startswith("accept")]
             + [d for d in dealer_rows if d["side"] == "sells" and d["adds"] > 0 and d["below_value"] is not False]
             + sorted((b for b in buys if not b["action"].startswith("accept")), key=lambda b: (not b["page_target"], -b["ev"])))
    for b in order:
        key = b["when"]
        if left.get(key, -1) >= b["cost"]:
            b["funded"] = True
            for k2 in left:
                if k2 == key or key == "now":
                    left[k2] -= b["cost"]
        else:
            b["funded"] = False
    for d in dealer_rows:
        d.setdefault("funded", True if d["side"] == "buys" else None)  # a sale needs no cash; None = not considered
    sells.sort(key=lambda m: -m["ev"])
    buys.sort(key=lambda m: (not m["funded"], -m["ev"]))
    decisions = []
    for o in board:  # our own live offers that lose value at our private values
        if o["team"] != vi.US or o["ref"] not in book or vi.set_of(o["ref"]) not in ours:
            continue
        s, k = vi.set_of(o["ref"]), mine[o["ref"]]
        if o["kind"] == "ask" and k > 0:
            v = copy_value(book[o["ref"]], ours[s], k - 1, marginals)
            on_page = s in target_sets and k == 1
            if o["price"] < v or on_page:
                decisions.insert(0, f"WARNING: our listing {o['id']} sells {o['ref']} at {o['price']} P"
                                    + (f", below its {v:.0f} P value to us" if o["price"] < v else "")
                                    + (f"; it is our only copy on the {s} page we want to complete" if on_page else "")
                                    + ": cancel it?")
        if o["kind"] == "bid" and o["price"] > copy_value(book[o["ref"]], ours[s], max(k, 0), marginals):
            v = copy_value(book[o["ref"]], ours[s], max(k, 0), marginals)
            decisions.insert(0, f"WARNING: our bid {o['id']} offers {o['price']} P for {o['ref']}, above its {v:.0f} P value to us: cancel it?")
    if free_now < 0:
        decisions.append(f"Cash {cash} P is {-free_now} P under the {reserve} P reserve: no buy is funded until a "
                         f"sale lands or the next grant, unless the team drops or lowers the reserve.")
    for did in sorted(slots):
        best = next((d for d in dealer_rows if d["dealer"] == did and d["adds"] > 0 and d["below_value"]), None)
        if best:
            top = best["ladder"][0] if best["side"] == "sells" else best["ladder"][-1]
            cards = ", ".join(c["ref"] for c in best["cards"] if c["below_value"])
            decisions.append(f"Ladder {did} (estimate): best {LADDER_SLOTS} {'today' if LADDER_PER_DAY else 'so far'} "
                             f"{' / '.join(f'{x:.2f}' for x in slots[did])}. "
                             f"{best['action'].capitalize()}: {'an' if best['kind'][0] in 'aeiou' else 'a'} {best['kind']} "
                             f"({cards}) at the median close {best['price']} P "
                             f"captures ~{best['share']:.0%} of the range"
                             + (f", at {top['price']} P ~{top['share']:.0%}" if top["price"] != best["price"] else "")
                             + f" (closes {best['low']}-{best['high']}, opening {best['opening']}, n={best['n']}, {best['source']}).")
    for p in pages:
        if p["missing"] and len(p["missing"]) <= PAGE_MAX_MISSING:
            decisions.append(f"Page {p['set']}: {p['have']}/{p['of']}, missing {', '.join(p['missing'])}. Holdings never score; "
                             + (f"the ~{p['bonus_if_confirmed']} P page bonus counts in the completing card's trade value (confirmed)."
                                if bonus_on else
                                f"the ~{p['bonus_if_confirmed']} P page bonus is NOT counted until the desk confirms it enters "
                                f"trade value (BRAIN_PAGE_BONUS=1)."))
    return {"tick": now_tick, "horizons": hz, "cash": cash, "cash_source": cash_source, "reserve": reserve, "free_cash": free_now,
            "board": board_source, "me_tick": me.get("tick"), "pages": pages, "sells": sells, "buys": buys, "holds": holds,
            "dealer": dealer_rows, "ladder_ours": {d: v for d, v in ladder.items()}, "dealer_prices": dprices,
            "calibration": {"shrink": lam, "p_cap": P_CAP}, "page_bonus_confirmed": bonus_on,
            "decisions": decisions,
            "assumptions": [
                "scored like the game: team trades = value gained at our private values (P); dealer deals = estimated share "
                "of the dealer's range on the ladder (best 3 per level); holdings and cash never score",
                f"ladder share is an estimate from measured closes: (opening - price) / (opening - lowest close) for a buy, "
                f"mirrored for a sale; slots counted {'since the day opened (each day a round: unconfirmed)' if LADDER_PER_DAY else 'all weekend'}",
                "a dealer deal on the wrong side of our value (a buy above it, a sale below it) scores 0 on the ladder"
                + (" (Friday's Chato deals say so)" if LADDER_VALUE_GATE else ": gate OFF"),
                "page bonus " + ("counted in the completing card's trade value (BRAIN_PAGE_BONUS=1)" if bonus_on
                                 else "not counted anywhere until the desk confirms it (BRAIN_PAGE_BONUS=1 turns it on)"),
                f"the fee is paid by whoever accepts; Friday trades count half; a team takes a good offer within a session "
                f"with chance {ATTENTION}",
                f"chances are estimates: multiplier beliefs keep {lam:.0%} of the model's confidence (fitted out of sample) "
                f"and no chance is shown above {P_CAP:.0%}",
                "our cards: snapshot + public settlements (pack pulls since the snapshot are invisible); our cash: the ledger, exact",
            ]}


# ---------------------------------------------------------------- output

def show(p: dict) -> None:
    h = " · ".join(f"{x['label']} (weight {x['weight']}{', +' + str(x['grant']) + ' P grant' if x['grant'] else ''})" for x in p["horizons"])
    print(f"Team 3 market plan · tick {p['tick']} · cash {p['cash']} P ({p.get('cash_source', 'ledger')}), reserve {p['reserve']} P · {h}")
    print(f"board: {p['board']} · our cards: snapshot tick {p['me_tick']} + public settlements")
    if p["decisions"]:
        print("\nDECISIONS FOR THE TEAM")
        for d in p["decisions"]:
            print(f"  - {d}")
    print("\nSELL TO TEAMS (scores the value gained at our private values; expected = est. chance x gain x round weight)")
    for m in p["sells"]:
        who = ", ".join(f"{b['team']} ~{b['p']:.0%}" for b in m.get("likely_buyers", []))
        print(f"  {m['action']:24} {m['ref']:7} at {m['price']:>4} P  gain {m['gain']:+6.1f}  chance ~{m['p']:.0%}  "
              f"expected {m['ev']:+5.1f}  ({m['copy']}, worth {m['our_value']} to us) likely buyers (est.): {who}")
    print("\nBUY FROM TEAMS (scores value - price - fee at our private values)")
    for m in p["buys"]:
        tag = "" if m["funded"] else "  [not funded]"
        tag += " [completes page]" if m["completes_page"] else " [page]" if m["page_target"] else ""
        print(f"  {m['action']:24} {m['ref']:7} at {m['price']:>4} P  gain {m['gain']:+6.1f}  chance ~{m['p']:.0%}  "
              f"expected {m['ev']:+5.1f}  from {m['counterparty']}{tag}")
    print("\nDEALER LADDER (scores the share of the dealer's range, an ESTIMATE from measured closes; never P)")
    for d in p["dealer"]:
        cards = ", ".join(f"{c['ref']} ({c['value']})" + ("" if c["below_value"] else " above value") for c in d["cards"]) or "-"
        share = f"~{d['share']:.0%}" if d["share"] is not None else "n/a (few closes)"
        print(f"  {d['action']:28} {d['kind']:18} at {d['price']:>4} P  share {share}  adds {d['adds']:.3f}  "
              f"slots {d['slots']}  closes {d['low']}-{d['high']} opening {d['opening']} n={d['n']} {d['source']}  cards: {cards}")
    if p["holds"]:
        print("\nHOLD")
        for x in p["holds"]:
            print(f"  {x['ref']:7} {x['why']}")
    print("\nASSUMPTIONS")
    for a in p["assumptions"]:
        print(f"  - {a}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Team 3's market plan (plans only, never sends).")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    p = plan()
    if args.json:
        print(json.dumps(p, indent=1, default=str))
    else:
        show(p)


if __name__ == "__main__":
    main()
