"""Team 3's market plan, recomputed from scratch on every run: what to sell, buy and hold, at what price and WHEN.
Plans only: it never lists, accepts, cancels or sends anything. Every move needs a yes in the team chat.

How a decision is made. For every card and every moment (now, or when the next day opens) it estimates, team by team,
the chance that a team takes our price:
- would they value it at that price? the inferred distribution of their multiplier (tools/value_inference.py), with
  the copy marginal (a team that already holds the card values another copy at 25 %);
- can they pay it? their cash, rebuilt exactly from the public feed (tools/ledger.py), plus the next day's grant;
- could they buy it cheaper from a dealer? Abuela always sells commons and uncommons, El Chato rares for the teams that
  unlocked him (and for everyone once he opens to all);
- are they active? a team with no public move in ACTIVE_TICKS ticks counts for little.
Expected gain = chance of a sale x (price - our value) x the round's weight (Friday counts half). A listing posted
tonight that does not sell tonight carries over to tomorrow, so "list now" is worth
P(tonight) x gain x 0.5 + (1 - P(tonight)) x P(tomorrow) x gain x 1, and "list tomorrow" is P(tomorrow) x gain x 1.
The plan picks the best price and moment for each card; first copies of a page worth completing are held.

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
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger as ledger_mod  # noqa: E402
import value_inference as vi  # noqa: E402

CASH_RESERVE = 280          # level-2 venue bond 250 + 20 (README); the team decides whether we still want a venue
MIN_GAIN = 3.0              # smallest gain (P, after fees) worth one of our listings or our single accept per tick
ATTENTION = 0.5             # chance an interested team notices and takes our offer within one session
ACTIVE_TICKS = 40           # a team with no public move in this many ticks is treated as mostly idle
IDLE_FACTOR = 0.3
STILL_THERE = 0.6           # chance a standing bid or ask is still on the board when the next day opens
DEALER_PREMIUM = 1.1        # a team pays at most ~10 % over a dealer's list price for a rarity that dealer sells it
DEALER_CLOSE = 0.95         # what a haggled dealer price ends at, as a share of the list price
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
    return p_now * w_now + (1.0 - p_now) * p_next * w_next


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

def plan() -> dict:
    model, by_team, events, book = vi.load()
    cat = vi.catalog()
    clock, schedule, dealers = vi.public("clock", True), vi.public("schedule", True), vi.public("dealers", True)
    marginals = cat["values"]["copy_marginals"]
    page_bonus = cat["values"]["page_bonus"]
    rarity = {c["id"]: c["rarity"] for s in cat["sets"] for c in s["cards"]}
    minted = {c["id"]: c.get("minted") or 0 for s in cat["sets"] for c in s["cards"]}
    released = {s["id"] for s in cat["sets"] if s.get("released")}
    me = vi.load_me()
    ours = me["affinity"]
    mine = vi.our_cards(me, events)
    led = ledger_mod.build(events, schedule)
    cash = led[vi.US]["cash"]
    now_tick = events[-1]["tick"]
    hz = horizons(clock, schedule)
    liquidate = hz[0]["hours"] >= LIQUIDATE_FROM_HOURS
    teams = sorted(set(by_team) - {vi.US})
    res = {t: model.summary(model.posterior(by_team[t])) for t in teams}
    prior = {m: 1 / len(vi.MULTS) for m in vi.MULTS}
    held = vi.holdings(events, set(by_team))
    act = activity(events, now_tick)
    board, board_source = live_board(events)
    menu = dealer_menu(dealers)
    unlocked = {t: set(led[t]["unlocked"]) for t in led}
    free_now = cash - CASH_RESERVE

    def dist(team: str, s: str) -> dict:
        return prior if team == UNKNOWN_HOLDER else res[team]["dist"][s]

    def dealer_for(team: str, ref: str, h: dict) -> float | None:
        """The cheapest list price at which `team` could buy this rarity from a dealer at horizon h."""
        for price, did, open_all, opens in menu.get(rarity[ref], []):
            if open_all or did in unlocked.get(team, set()) or (opens is not None and h["hours"] >= opens):
                return price
        return None

    def p_buyer(team: str, ref: str, price: int, h: dict) -> float:
        need = price + fee(price)
        if led[team]["cash"] + h["grant"] < need:
            return 0.0
        d = dealer_for(team, ref, h)
        if d is not None and need > d * DEALER_PREMIUM:
            return 0.0
        k = held[team][ref]
        return p_value_at_least(dist(team, vi.set_of(ref)), book[ref], marginals[min(k, len(marginals) - 1)], need) * act[team]

    def p_sale(ref: str, price: int, h: dict) -> float:
        return any_of([ATTENTION * h["session"] * p_buyer(t, ref, price, h) for t in teams])

    def best_ask(ref: str, keep: float) -> dict | None:
        """The price and moment with the highest expected weighted gain for a listing of ours."""
        lo = math.ceil(keep + MIN_GAIN)
        hi = int(book[ref] * max(vi.MULTS) * 1.0) + 1
        best = None
        for price in range(lo, max(lo, hi) + 1):
            g = price - keep
            pn = p_sale(ref, price, hz[0])
            options = [("list now", carry_over(pn, hz[0]["weight"], p_sale(ref, price, hz[1]), hz[1]["weight"]) if len(hz) > 1
                        else pn * hz[0]["weight"], pn, 0)]
            if len(hz) > 1:
                pt = p_sale(ref, price, hz[1])
                options.append((f"list at {hz[1]['label']}", pt * hz[1]["weight"], pt, 1))
            for label, wp, p, hi_ in options:
                ev = wp * g
                if best is None or ev > best["ev"]:
                    best = {"action": label, "price": price, "gain": round(g, 1), "p": round(p, 2), "ev": round(ev, 1),
                            "horizon": hi_}
        return best if best and best["ev"] >= MIN_GAIN * 0.5 else None

    # ---- pages: worth completing? then hold the first copies
    pages = []
    for s in sorted(released):
        refs = [f"{s}-{n:02d}" for n in range(1, PAGE_CARDS + 1) if f"{s}-{n:02d}" in book]
        missing = [r for r in refs if mine[r] <= 0]
        bonus = page_bonus * sum(copy_value(book[r], ours[s], 0, marginals) for r in refs)
        cost, sources = 0.0, []
        for r in missing:
            d = dealer_for(vi.US, r, hz[-1])
            if d is None:
                cost = math.inf
                sources.append(f"{r}: no dealer")
            else:
                cost += d * DEALER_CLOSE
                sources.append(f"{r}: ~{d * DEALER_CLOSE:.0f} P from a dealer")
        net = bonus + sum(copy_value(book[r], ours[s], 0, marginals) for r in missing) - cost
        pages.append({"set": s, "have": len(refs) - len(missing), "of": len(refs), "missing": missing,
                      "bonus": round(bonus), "cost": None if math.isinf(cost) else round(cost),
                      "net": None if math.isinf(net) else round(net), "sources": sources,
                      "target": not liquidate and not math.isinf(net) and net > 0 and ours[s] >= 1.3})
    target_sets = {p["set"] for p in pages if p["target"]}

    sells, holds = [], []
    for ref, k in sorted(mine.items()):
        if k <= 0 or ref not in book:
            continue
        s = vi.set_of(ref)
        keep = copy_value(book[ref], ours[s], k - 1, marginals)
        if k == 1 and s in target_sets:
            holds.append({"ref": ref, "why": f"first copy on the {s} page, which is worth completing"})
            continue
        option = best_ask(ref, keep)
        bids = sorted((o for o in board if o["kind"] == "bid" and o["ref"] == ref and o["team"] != vi.US
                       and o["to"] in (None, vi.US)), key=lambda o: -o["price"])
        if bids:
            b = bids[0]
            g = b["price"] - fee(b["price"]) - keep
            alts = [("accept bid now", g * hz[0]["weight"])]
            if len(hz) > 1:
                alts.append((f"accept bid at {hz[1]['label']}", g * hz[1]["weight"] * STILL_THERE))
            label, ev = max(alts, key=lambda x: x[1])
            if g >= MIN_GAIN and (option is None or ev >= option["ev"]):
                option = {"action": label, "price": b["price"], "gain": round(g, 1), "p": 1.0 if "now" in label else STILL_THERE,
                          "ev": round(ev, 1), "offer": b["id"], "counterparty": b["team"], "horizon": 0 if "now" in label else 1}
        if option is None:
            continue
        h_sel = hz[min(option.get("horizon", 0), len(hz) - 1)]
        takers = sorted(((t, p_buyer(t, ref, option["price"], h_sel)) for t in teams), key=lambda x: -x[1])
        option.update(ref=ref, copy="spare" if k > 1 else "first", our_value=round(keep, 1),
                      likely_buyers=[{"team": t, "p": round(p, 2), "cash": led[t]["cash"]} for t, p in takers[:3] if p > 0])
        sells.append(option)

    buys = []
    for ref in sorted(book):
        s = vi.set_of(ref)
        if s not in released or int(ref.split("-")[1]) > PAGE_CARDS or mine[ref] > 0:
            continue
        page = next(p for p in pages if p["set"] == s)
        value = copy_value(book[ref], ours[s], 0, marginals) + (page["bonus"] if page["missing"] == [ref] else 0)
        options = []
        for o in board:
            if o["kind"] == "ask" and o["ref"] == ref and o["team"] != vi.US:
                g = value - o["price"] - fee(o["price"])
                options.append({"action": "accept ask now", "price": o["price"], "gain": round(g, 1), "p": 1.0,
                                "ev": round(g * hz[0]["weight"], 1), "counterparty": o["team"], "offer": o["id"],
                                "cost": o["price"] + fee(o["price"]), "when": "now"})
        for h in hz:
            d = dealer_for(vi.US, ref, h)
            if d is not None:
                price = round(d * DEALER_CLOSE)
                g = value - price
                did = next(x[1] for x in menu[rarity[ref]] if x[0] == d)
                options.append({"action": f"buy from {did}" + ("" if h["key"] == "now" else f" at {h['label']}"),
                                "price": price, "gain": round(g, 1), "p": 0.9, "ev": round(0.9 * g * h["weight"], 1),
                                "counterparty": did, "cost": price, "when": h["key"]})
        hold_teams = [t for t in teams if held[t][ref] > 0]
        unseen = max(0, minted.get(ref, 0) - sum(held[t][ref] for t in teams) - mine[ref])
        sellers = [(t, held[t][ref]) for t in hold_teams] + [(UNKNOWN_HOLDER, 1)] * min(unseen, 3)
        if sellers:
            for h in hz:
                best = None
                for bid in range(1, int(value - MIN_GAIN) + 1):
                    p = any_of([ATTENTION * h["session"] * (act[t] if t != UNKNOWN_HOLDER else 0.5)
                                * p_value_at_most(dist(t, s), book[ref], marginals[min(n - 1, len(marginals) - 1)],
                                                  bid - fee(bid))
                                for t, n in sellers])
                    ev = p * (value - bid) * h["weight"]
                    if best is None or ev > best["ev"]:
                        best = {"action": "bid" + ("" if h["key"] == "now" else f" at {h['label']}"), "price": bid,
                                "gain": round(value - bid, 1), "p": round(p, 2), "ev": round(ev, 1),
                                "counterparty": ", ".join(t if t != UNKNOWN_HOLDER else "unseen copy" for t, _ in sellers[:3]),
                                "cost": bid, "when": h["key"]}
                if best:
                    options.append(best)
        options = [o for o in options if o["gain"] >= MIN_GAIN and o["p"] >= 0.05 and o["ev"] >= 0.5]
        if not options:
            continue
        best = max(options, key=lambda o: o["ev"])
        best.update(ref=ref, our_value=round(value, 1), minted=minted.get(ref),
                    page_target=s in target_sets, completes_page=page["missing"] == [ref])
        buys.append(best)

    # cash: buys funded in order (target pages first, then expected gain); sales are not counted until they land
    left = {"now": free_now}
    for h in hz[1:]:
        left[h["key"]] = free_now + h["grant"]
    for b in sorted(buys, key=lambda b: (not b["page_target"], -b["ev"])):
        key = b["when"]
        if left.get(key, -1) >= b["cost"]:
            b["funded"] = True
            for k2 in left:
                if k2 == key or key == "now":
                    left[k2] -= b["cost"]
        else:
            b["funded"] = False
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
        decisions.append(f"Cash {cash} P is {-free_now} P under the {CASH_RESERVE} P venue reserve: no buy is funded until a "
                         f"sale lands or the next grant, unless the team drops or lowers the reserve.")
    for p in pages:
        if p["target"]:
            decisions.append(f"Page {p['set']}: {p['have']}/{p['of']}, missing {', '.join(p['missing'])}; completing it from "
                             f"dealers costs ~{p['cost']} P for a ~{p['bonus']} P bonus plus the cards' value (net ~{p['net']:+} P).")
    return {"tick": now_tick, "horizons": hz, "cash": cash, "reserve": CASH_RESERVE, "free_cash": free_now,
            "board": board_source, "me_tick": me.get("tick"), "pages": pages, "sells": sells, "buys": buys, "holds": holds,
            "decisions": decisions,
            "assumptions": [
                "the page bonus is 25 % of the page's first-copy values and counts in a trade's value: unconfirmed",
                "the fee is paid by whoever accepts; Friday trades count half (rounds averaged, Friday weighs half)",
                f"a team takes a good offer within a session with chance {ATTENTION}; dealers close at {DEALER_CLOSE:.0%} of list",
                "our cards: snapshot + public settlements (pack pulls since the snapshot are invisible); our cash: the ledger, exact",
            ]}


# ---------------------------------------------------------------- output

def show(p: dict) -> None:
    h = " · ".join(f"{x['label']} (weight {x['weight']}{', +' + str(x['grant']) + ' P grant' if x['grant'] else ''})" for x in p["horizons"])
    print(f"Team 3 market plan · tick {p['tick']} · cash {p['cash']} P (ledger), reserve {p['reserve']} P · {h}")
    print(f"board: {p['board']} · our cards: snapshot tick {p['me_tick']} + public settlements")
    if p["decisions"]:
        print("\nDECISIONS FOR THE TEAM")
        for d in p["decisions"]:
            print(f"  - {d}")
    print("\nSELL (expected gain = chance x gain x round weight)")
    for m in p["sells"]:
        who = ", ".join(f"{b['team']} {b['p']:.0%}" for b in m.get("likely_buyers", []))
        print(f"  {m['action']:24} {m['ref']:7} at {m['price']:>4} P  gain {m['gain']:+6.1f}  chance {m['p']:.0%}  "
              f"expected {m['ev']:+5.1f}  ({m['copy']}, worth {m['our_value']} to us) buyers: {who}")
    print("\nBUY")
    for m in p["buys"]:
        tag = "" if m["funded"] else "  [not funded]"
        tag += " [completes page]" if m["completes_page"] else " [page]" if m["page_target"] else ""
        print(f"  {m['action']:24} {m['ref']:7} at {m['price']:>4} P  gain {m['gain']:+6.1f}  chance {m['p']:.0%}  "
              f"expected {m['ev']:+5.1f}  from {m['counterparty']}{tag}")
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
