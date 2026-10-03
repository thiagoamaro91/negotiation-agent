"""El Chato negotiator (the L2 dealer at El Rastro, next to Abuela Carmen).

Copied from agent/abuela.py (owned by the Abuela queue session; left untouched). Numbers are decided here, in code;
the words around them are decoration (structure binds).

What the feed showed in his first hour (Friday 22:00, 70 public messages, no deal closed yet):
- He sells uncommons and rares and buys them; no neighbourhood packs ("Abuela handles those").
- He opens at ~1.27 x list: 33 P for an uncommon (list 26), 97 P for a rare (list 77), 188 P for a silver pack.
- He concedes as much as we move or less ("You move, I move", "You moved three, I moved nothing").
- Buying from us he bids ~13 P for an uncommon and holds there.
- Strict, shrewd, long memory, low patience: every message carries a new price and new words, and we never
  call him Carmen or abuela ("Keep calling me abuela, the number goes the other way").
- One thread said "Silver pack" about a card topic: only the structured offer counts, offer_matches() stays.

Plan per deal is Abuela's: anchor low, step 1 P, and take his final offer if it is inside our limit. The ladder
scores the share of his price range we capture, so ending at his limit is the goal; our private value is a cap.

Usage (from the repo root):
    python3 agent/chato.py plan
    python3 agent/chato.py run --only SAL-08 --max-deals 1 --reserve 200 --cap 30
    python3 agent/chato.py run --only LAV-09 --max-deals 1 --anchor 60 --step 4 --cap 93 --reserve 200
Only ONE process per team may talk to El Chato at a time (one open conversation per dealer).
`run` refuses to start (exit 0) while agent/duel.py holds results/duel.lock (one line: expiry, epoch seconds).

Doña Pilar (--dealer pilar, L3 collector): she only BUYS from us (uncommon, rare, epic; she loves SAL and RET) and
sells gold packs only, so `plan`/`run` refuse buy targets for her and list sells only. Feed evidence: she opened at
16 and held 16 across 9 threads; another team asked 49, then 42, and sold LAV-08 at 19. So her first ask is
max(3 x her opening bid, floor + 20) and we come down 4 P per round, never below the floor (our private value of that
copy + 2), and take her final offer if it is at or above the floor. Logs go to logs/pilar/<date>.jsonl.
    python3 agent/chato.py plan --dealer pilar --only sell:42,sell:44 --allow-single
    python3 agent/chato.py run --dealer pilar --only sell:42,sell:44 --allow-single --max-deals 2
--allow-single lets an explicitly listed `sell:<asset_id>` go even when it is our last copy (or the copy we keep);
nothing is ever auto-selected that way: without an explicit id the agent sells spares only.
--sell-anchor N (absolute first ask) and --sell-step N override the dealer's selling defaults; the floor still holds.
--floor P replaces the default sell floor (private value + 2) with P for this run; a copy whose private value is above
P (hard minimum ceil(private value)) is refused: plan shows it, run stops before opening any thread.
    python3 agent/chato.py run --dealer pilar --only sell:42,sell:44 --allow-single --floor 18 --max-deals 2
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402
from runlog import RunLog, save_thread  # noqa: E402

RUN = RunLog("chato")       # logs/chato/<date>.jsonl, committed; keys are redacted (main() swaps it per --dealer)
DEALER = "chato"
CASH_RESERVE = 280          # default; the owner may lower it per run with --reserve
ANCHOR_FRAC = 0.40          # first counter, as a share of her opening price (buying)
ANCHOR_ABS = None           # --anchor N: absolute first bid when buying (overrides ANCHOR_FRAC)
SELL_ANCHOR_MULT = 1.6      # first ask, as a multiple of his opening bid (selling); he holds his bid, so stay short
SELL_ANCHOR_OVER_FLOOR = 0  # first ask is at least floor + this (selling); 0 for Chato, so his anchor is unchanged
SELL_ANCHOR_ABS = None      # --sell-anchor N: absolute first ask when selling (overrides the multiple; floor holds)
STEP = 1                    # primas per round when buying: he mirrors our step, his final comes at his limit
MAX_BID = None              # --max-bid N: our bids stop here; we then wait for his final (accepted up to the cap)
SELL_STEP = 2               # primas per round when selling (time is short and his bid barely moves)
MAX_ROUNDS = 12             # 60 s ticks: 12 rounds is 12 minutes; his patience is low
DUEL_LOCK = ROOT / "results" / "duel.lock"   # written by agent/duel.py run while any of our duels is live

# Per-dealer table. Chato's row is exactly the constants above, so no --dealer flag means no change.
DEALERS = {
    "chato": {"name": "El Chato", "buys": ("uncommon", "rare"), "sells_cards": True,
              "sell_anchor_mult": 1.6, "sell_anchor_over_floor": 0, "sell_step": 2, "example_bid": 13},
    # L3 collector: buys uncommon/rare/epic (loves SAL, RET), sells gold packs only. Opened 16, held 16 (feed).
    "pilar": {"name": "Doña Pilar", "buys": ("uncommon", "rare", "epic"), "sells_cards": False,
              "sell_anchor_mult": 3.0, "sell_anchor_over_floor": 20, "sell_step": 4, "example_bid": 16},
}
DEFAULT_DEALER = "chato"
DEALER_NAME = DEALERS[DEFAULT_DEALER]["name"]
SELL_RARITIES = DEALERS[DEFAULT_DEALER]["buys"]       # what the dealer buys from us
DEALER_SELLS_CARDS = DEALERS[DEFAULT_DEALER]["sells_cards"]


def apply_dealer(dealer: str, sell_anchor: int | None = None, sell_step: int | None = None) -> None:
    """Point every dealer-specific global at one row of DEALERS (plus the --sell-anchor/--sell-step overrides)."""
    global DEALER, DEALER_NAME, SELL_RARITIES, DEALER_SELLS_CARDS, SELL_ANCHOR_MULT, SELL_ANCHOR_OVER_FLOOR
    global SELL_ANCHOR_ABS, SELL_STEP
    d = DEALERS[dealer]
    DEALER, DEALER_NAME = dealer, d["name"]
    SELL_RARITIES, DEALER_SELLS_CARDS = d["buys"], d["sells_cards"]
    SELL_ANCHOR_MULT, SELL_ANCHOR_OVER_FLOOR = d["sell_anchor_mult"], d["sell_anchor_over_floor"]
    SELL_ANCHOR_ABS = sell_anchor
    SELL_STEP = d["sell_step"] if sell_step is None else int(sell_step)


def duel_lock_fresh(path: Path = DUEL_LOCK) -> bool:
    """True while the duel bot holds the team's accept slot (first token of the file = expiry, epoch seconds)."""
    try:
        return float(path.read_text().split()[0]) > time.time()
    except (OSError, ValueError, IndexError):
        return False


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def log(event: str, **data) -> None:
    RUN.event(event, **data)


# ---------------------------------------------------------------- words (never contradict the number)

BUY_LINES = [
    "Buenas. Straight offer, cash ready: {p} P.",
    "I hear you. I move, you move: {p} P.",
    "Fair is fair. {p} P, paid on the spot.",
    "One more step from me: {p} P.",
    "No theatre. {p} P.",
    "I am still here and still serious: {p} P.",
    "Moving again. {p} P.",
    "Let us close it. {p} P.",
    "Another step: {p} P. Your turn.",
    "{p} P. Clean card, clean deal.",
    "Up again, {p} P.",
    "{p} P, and I keep moving.",
]
SELL_LINES = [
    "Buenas. Clean card, straight price: {p} P.",
    "I move, you move. {p} P.",
    "Coming down: {p} P.",
    "Fair is fair. {p} P.",
    "No theatre. {p} P and it is yours.",
    "Another step down: {p} P.",
    "{p} P. Your turn.",
    "Down again, {p} P.",
]


def line(lines: list, n: int, p: int) -> str:
    return lines[n % len(lines)].format(p=p)


# ---------------------------------------------------------------- offers

def her_open_offer(thread: dict) -> dict | None:
    hers = [o for o in thread.get("standing_offers") or []
            if o.get("maker") == DEALER and o.get("status") in ("open", "queued")]
    return hers[-1] if hers else None


def offer_price(o: dict) -> int:
    """Cash in her offer: what she wants when she sells, what she gives when she buys."""
    return int((o.get("want") or {}).get("cash") or (o.get("give") or {}).get("cash") or 0)


def offer_matches(o: dict, side: str, item: str, asset_id: int | None) -> bool:
    """Read the structure, not the words: the offer must move the item we negotiated."""
    give, want = o.get("give") or {}, o.get("want") or {}
    if side == "buy":
        refs = [a.get("ref") for a in give.get("assets") or []] + [t.split(":", 1)[-1] for t in give.get("types") or []]
        return item in refs and bool(want.get("cash"))
    ids = [a.get("id") if isinstance(a, dict) else a for a in want.get("assets") or []]
    return asset_id in ids and bool(give.get("cash"))


def sell_anchor(her: int, floor: int) -> int:
    """Our first ask when selling: --sell-anchor if set, else max(mult x her opening bid, floor + over_floor).
    For Chato (over_floor 0) this is round(1.6 x her), exactly as before; the caller still clamps it to the floor."""
    if SELL_ANCHOR_ABS is not None:
        return int(SELL_ANCHOR_ABS)
    return max(int(round(her * SELL_ANCHOR_MULT)), int(floor) + SELL_ANCHOR_OVER_FLOOR)


def sell_ladder(her: int, floor: int) -> list:
    """The asks a sell walks through if the dealer holds `her` (shown by plan; she may cross or stop us earlier)."""
    out, a = [], max(sell_anchor(her, floor), int(floor))
    while a > floor and len(out) < 30:
        out.append(a)
        a -= SELL_STEP
    return out + [int(floor)]


# ---------------------------------------------------------------- one negotiation

def negotiate(b: Bazaar, target: dict, first_deal: bool, resume: int | None = None) -> dict:
    side, item, value = target["side"], target["item"], target["value"]
    asset_id = target.get("asset_id")
    if side == "buy" and not DEALER_SELLS_CARDS:  # e.g. Pilar sells gold packs only: never open a card buy
        log("refuse_buy", item=item, dealer=DEALER)
        return {"result": "refused", "code": "dealer_sells_no_cards"}
    topic ={"buy": {"card": item}} if side == "buy" else {"sell": {"assets": [asset_id]}}
    ours: int | None = None
    said = 0
    last_her = None
    answered = None  # id of his offer we last countered
    if resume:
        # pick up a conversation an earlier process left open: continue from our last number, never step back
        tid = resume
        msgs = sorted((b.thread(tid).get("messages") or []), key=lambda m: m.get("id") or 0)
        mine = [m for m in msgs if m.get("sender") != DEALER and m.get("offer")]
        if mine:
            ours = offer_price(mine[-1]["offer"])
            said = len(mine)
            if msgs[-1].get("sender") != DEALER:  # our number is the latest word: wait for his answer
                o = her_open_offer(b.thread(tid))
                answered = o["id"] if o else None
        log("resume", thread=tid, side=side, item=item, value=value, ours=ours, answered=answered)
    else:
        try:
            th = b.open_thread(DEALER, topic=topic)
        except BazaarError as e:
            log("open_refused", item=item, side=side, code=e.code, msg=e.message)
            return {"result": "refused", "code": e.code}
        tid = th["id"]
        log("open", thread=tid, side=side, item=item, value=value)

    for rnd in range(MAX_ROUNDS):
        t = b.thread(tid)
        status = t.get("status")
        if status != "open":
            log("closed", thread=tid, status=status, reason=t.get("closed_reason"), ours=ours, her=last_her)
            return {"result": status, "thread": tid, "ours": ours, "her": last_her}
        o = her_open_offer(t)
        if o is None:
            b.wait_tick()
            continue
        if not offer_matches(o, side, item, asset_id):
            log("mismatch", thread=tid, offer=o)  # a switched item: never accept it
            b.wait_tick()
            continue
        her = offer_price(o)
        final = bool(o.get("final"))
        if her != last_her:
            log("her", thread=tid, price=her, final=final, round=rnd)
        last_her = her
        cash = b.me()["cash"] if side == "buy" else None
        reservation = (min(value, cash - CASH_RESERVE) if side == "buy" else value)
        reservation = int(reservation) if side == "buy" else int(-(-reservation // 1))

        def good(p: int) -> bool:
            return p <= reservation if side == "buy" else p >= reservation

        # 2) her last word: take it if it is still a good deal, else walk
        if final:
            if good(her):
                b.accept(o["id"])
                log("accept", thread=tid, price=her, why="final")
                return settle(b, tid, her)
            b.close_thread(tid)
            log("walk", thread=tid, price=her, reservation=reservation)
            return {"result": "walked_by_us", "thread": tid}
        # 3) she has not answered our last number yet: never bid against ourselves
        if o["id"] == answered:
            b.wait_tick()
            continue
        # 4) our next number: low anchor, then STEP per round toward her
        if ours is None:
            if side == "buy":
                nxt = int(ANCHOR_ABS) if ANCHOR_ABS is not None else int(her * ANCHOR_FRAC)
            else:
                nxt = sell_anchor(her, reservation)
        else:
            nxt = ours + STEP if side == "buy" else ours - SELL_STEP
        nxt = int(min(nxt, reservation)) if side == "buy" else int(max(nxt, reservation))
        if side == "buy" and MAX_BID is not None:
            nxt = min(nxt, int(MAX_BID))  # stop bidding here; his final is still taken up to the reservation
        # 5) she is already at (or past) our next number: take her price
        crossed = her <= nxt if side == "buy" else her >= nxt
        if crossed and good(her):
            b.accept(o["id"])
            log("accept", thread=tid, price=her, why="crossed", ours=ours)
            return settle(b, tid, her)
        if ours is not None and nxt == ours:  # pinned at our reservation: wait for her final offer
            b.wait_tick()
            continue
        ours = nxt
        b.say(tid, line(BUY_LINES if side == "buy" else SELL_LINES, said, ours), price=ours)
        answered = o["id"]
        said += 1
        log("say", thread=tid, price=ours, her=her)
        b.wait_tick()
    b.close_thread(tid)
    log("max_rounds", thread=tid, ours=ours, her=last_her)
    return {"result": "max_rounds", "thread": tid}


def settle(b: Bazaar, tid: int, price: int) -> dict:
    for _ in range(4):  # it settles on the next tick
        b.wait_tick()
        t = b.thread(tid)
        if t.get("status") != "open":
            break
    log("result", thread=tid, status=t.get("status"), price=price, reason=t.get("closed_reason"))
    return {"result": t.get("status"), "thread": tid, "price": price}


# ---------------------------------------------------------------- what to trade

def listed_sell_ids(only: list[str] | None) -> list[int]:
    """The asset ids named as sell:<asset_id> in --only, in order."""
    out = []
    for x in only or []:
        k, _, v = x.partition(":")
        if k == "sell" and v.isdigit():
            out.append(int(v))
    return out


def build_plan(b: Bazaar, me: dict, only: list[str] | None, cap: float | None, allow_single: bool = False) -> list[dict]:
    """Buys: uncommons and rares Chato sells that we do not hold, ranked by our value (none for a dealer that sells
    no cards, e.g. Pilar). Sells: our duplicate cards of a rarity the dealer buys (a spare is worth much less to us).
    With allow_single, an asset named as sell:<asset_id> in `only` may go even if it is our last copy; nothing is
    auto-selected that way. --cap lowers (never raises) our value as the most we pay (the ladder scores his price
    range, not our value)."""
    held = {}
    for a in me["assets"]:
        if a["kind"] == "card":
            held.setdefault(a["ref"], []).append(a)
    buys = []
    if DEALER_SELLS_CARDS:
        catalog = b.catalog()
        released = {s["id"] for s in catalog["sets"] if s["released"]}
        for s in catalog["sets"]:
            if s["id"] not in released:
                continue
            for c in s["cards"]:
                if c["rarity"] not in ("uncommon", "rare") or c["id"] in held:
                    continue
                if only and c["id"] not in only:
                    continue
                v = b.value(c["id"])["your_value"]
                buys.append({"side": "buy", "item": c["id"], "name": c["name"], "book": c["book"],
                             "value": min(v, cap) if cap else v, "private": v})
        buys.sort(key=lambda x: -x["private"])
    sells = []
    for ref, copies in held.items():
        if len(copies) > 1 and copies[0]["rarity"] in SELL_RARITIES:
            spare = max(copies, key=lambda a: a["serial"])  # keep the lowest serial
            sells.append({"side": "sell", "item": ref, "name": spare["name"], "asset_id": spare["id"],
                          "value": spare["your_value"] + 2, "private": spare["your_value"]})
    if allow_single:  # only explicitly named ids; the floor is still that copy's private value + 2
        by_id = {a["id"]: a for copies in held.values() for a in copies}
        planned = {s["asset_id"] for s in sells}
        for aid in listed_sell_ids(only):
            a = by_id.get(aid)
            if a is None or aid in planned or a["rarity"] not in SELL_RARITIES:
                continue
            sells.append({"side": "sell", "item": a["ref"], "name": a["name"], "asset_id": aid,
                          "value": a["your_value"] + 2, "private": a["your_value"], "single": True,
                          "last": len(held[a["ref"]]) == 1})
            planned.add(aid)
    plan = sells + buys  # sells first: they bring cash in
    if only:
        keys = set(only)
        plan = [p for p in plan if (p["side"] == "buy" and p["item"] in keys) or f"sell:{p.get('asset_id')}" in keys]
    return plan


def apply_floor(plan: list[dict], floor: int | None) -> tuple[list[dict], list[dict]]:
    """--floor P replaces the default sell floor (private value + 2) with P for this run. P below our private value of
    a copy (hard minimum ceil(private)) is refused for that copy: it comes back in the second list and is never sold."""
    if floor is None:
        return plan, []
    kept, refused = [], []
    for p in plan:
        if p["side"] != "sell":
            kept.append(p)
        elif int(floor) < math.ceil(p["private"]):
            refused.append(dict(p, why=f"--floor {floor} is below our private value {p['private']} "
                                       f"(minimum {math.ceil(p['private'])})"))
        else:
            kept.append(dict(p, value=int(floor), floor_override=True))
    return kept, refused


def bid_ladder(limit: float, spendable: int) -> list:
    """The bids a buy would walk through with --anchor (shown by plan; she may cross or stop us earlier)."""
    top = int(min(limit, spendable, MAX_BID if MAX_BID is not None else limit))
    if ANCHOR_ABS is None or top < 1:
        return []
    out, b = [], int(ANCHOR_ABS)
    while b < top and len(out) < 30:
        out.append(b)
        b += STEP
    return out + [top]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--only", default="", help="comma list of card refs and/or sell:<asset_id>")
    ap.add_argument("--max-deals", type=int, default=3)
    ap.add_argument("--resume", type=int, default=None, help="thread id to continue for the first target")
    ap.add_argument("--max-rounds", type=int, default=MAX_ROUNDS)
    ap.add_argument("--reserve", type=int, default=CASH_RESERVE, help="cash we never spend below")
    ap.add_argument("--cap", type=float, default=None, help="most we pay for any card (default: our value)")
    ap.add_argument("--anchor", type=int, default=None, help="absolute first bid when buying (overrides ANCHOR_FRAC)")
    ap.add_argument("--step", type=int, default=STEP, help="primas per round when buying (default 1)")
    ap.add_argument("--max-bid", type=int, default=None, help="highest number we send when buying; his final is still taken up to the cap")
    ap.add_argument("--dealer", choices=sorted(DEALERS), default=DEFAULT_DEALER,
                    help="which dealer to talk to (default chato; pilar buys from us only)")
    ap.add_argument("--allow-single", action="store_true",
                    help="with explicit sell:<asset_id> entries only: sell that copy even if it is our last one")
    ap.add_argument("--sell-anchor", type=int, default=None,
                    help="absolute first ask when selling, in P (default per dealer: chato 1.6 x his bid, "
                         "pilar max(3 x her bid, floor + 20)); never below the floor")
    ap.add_argument("--sell-step", type=int, default=None, help="primas per round when selling (default chato 2, pilar 4)")
    ap.add_argument("--floor", type=int, default=None,
                    help="sell floor in P for this run, replacing private value + 2; refused below ceil(private value)")
    args = ap.parse_args(argv)
    if args.step < 1 or (args.anchor is not None and args.anchor < 1):
        ap.error("--step and --anchor must be >= 1")
    if (args.sell_step is not None and args.sell_step < 1) or (args.sell_anchor is not None and args.sell_anchor < 1):
        ap.error("--sell-step and --sell-anchor must be >= 1")
    if args.floor is not None and args.floor < 1:
        ap.error("--floor must be >= 1")
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if args.allow_single and not listed_sell_ids(only):
        ap.error("--allow-single needs explicit --only sell:<asset_id> entries (nothing is auto-selected)")
    if not DEALERS[args.dealer]["sells_cards"]:
        buys = [x for x in only if not x.startswith("sell:")]
        if buys:
            ap.error(f"{args.dealer} sells no cards to us (gold packs only): refusing buy targets {','.join(buys)}; "
                     "list sell:<asset_id> entries only")
    return args


def sell_skips(me: dict, only: list[str] | None, plan: list[dict], allow_single: bool) -> list[str]:
    """Why each explicitly listed sell:<asset_id> is not in the plan (plan output only)."""
    by_id = {a["id"]: a for a in me["assets"]}
    planned = {p.get("asset_id") for p in plan}
    out = []
    for aid in listed_sell_ids(only):
        if aid in planned:
            continue
        a = by_id.get(aid)
        if a is None:
            why = "not one of our assets"
        elif a.get("kind") != "card":
            why = f"not a card ({a.get('kind')})"
        elif a.get("rarity") not in SELL_RARITIES:
            why = f"{DEALER} does not buy {a.get('rarity')}"
        elif not allow_single:
            why = "not a spare (our last copy, or the copy we keep): add --allow-single to sell it"
        else:
            why = "not planned"
        out.append(f"  skip sell:{aid} {(a or {}).get('ref', '')}: {why}")
    return out


def main() -> None:
    global CASH_RESERVE, MAX_ROUNDS, ANCHOR_ABS, STEP, MAX_BID, RUN
    load_env()
    args = parse_args()
    apply_dealer(args.dealer, args.sell_anchor, args.sell_step)
    extra = (args.dealer != DEFAULT_DEALER or args.allow_single or args.sell_anchor is not None
             or args.sell_step is not None or args.floor is not None)  # print/log the new selling details; plain chato output is unchanged
    if args.cmd == "run" and duel_lock_fresh():
        print(f"WARNING: {DUEL_LOCK.relative_to(ROOT)} is fresh: the duel bot holds the team's accept slot. "
              f"Not starting {DEALER_NAME}; try again after the duel wave.", flush=True)
        return
    ANCHOR_ABS, STEP, MAX_BID = args.anchor, args.step, args.max_bid
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"])
    me = b.me()
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    plan = build_plan(b, me, only, args.cap, allow_single=args.allow_single)
    plan, floor_refused = apply_floor(plan, args.floor)
    CASH_RESERVE = args.reserve
    MAX_ROUNDS = args.max_rounds
    print(f"{me['name']} cash={me['cash']} level={me['level']} deals={me['score'].get('deals')}")
    for p in plan:
        print(f"  {p['side']:4} {p['item']:7} limit={p['value']:6.1f} private={p['private']:6.1f}  {p.get('name', '')}"
              + (f"  asset={p.get('asset_id')}{(' LAST COPY' if p.get('last') else ' KEPT COPY') if p.get('single') else ''}"
                 if extra and p['side'] == 'sell' else ""))
    print(f"reserve={CASH_RESERVE} (spendable {me['cash'] - CASH_RESERVE} P) anchor={ANCHOR_ABS or f'{ANCHOR_FRAC} x her ask'} "
          f"step={STEP} cap={args.cap}")
    for p in plan:
        if p["side"] == "buy" and ANCHOR_ABS is not None:
            print(f"  bids {p['item']}: {' '.join(str(x) for x in bid_ladder(p['value'], me['cash'] - CASH_RESERVE))}"
                  f" (then wait for his final; take it if <= {int(min(p['value'], me['cash'] - CASH_RESERVE))})")
    if extra:
        first = (f"{SELL_ANCHOR_ABS}" if SELL_ANCHOR_ABS is not None
                 else f"max({SELL_ANCHOR_MULT} x her bid, floor + {SELL_ANCHOR_OVER_FLOOR})")
        print(f"dealer={DEALER} ({DEALER_NAME}) buys={','.join(SELL_RARITIES)} first ask={first} sell_step={SELL_STEP} "
              f"allow_single={args.allow_single}")
        if args.dealer != DEFAULT_DEALER and args.cmd == "plan":
            try:  # her live menu, to cross-check the table above (read-only GET)
                menu = (b.dealer(DEALER) or {}).get("menu") or {}
                print(f"  menu buys: {[x.get('rarity') for x in menu.get('buys') or []]} "
                      f"sells: {[x.get('pack') or x.get('rarity') for x in menu.get('sells') or []]}")
            except Exception as e:  # noqa: BLE001  (plan output must not die on a menu read)
                print(f"  menu read failed: {e}")
        for p in plan:
            if p["side"] == "sell":
                eg = DEALERS[DEALER]["example_bid"]
                floor = int(-(-p["value"] // 1))
                asks = []
                for x in sell_ladder(eg, floor):
                    asks.append(x)
                    if x <= eg:  # she is at our ask: we take her price there
                        break
                then = f"she crosses: deal at {eg}" if asks[-1] <= eg else f"then her final; take it if >= {floor}"
                print(f"  asks {p['item']} (asset {p['asset_id']}) if she bids {eg}: "
                      f"{' '.join(str(x) for x in asks)} ({then})")
        for s in sell_skips(me, only, plan + floor_refused, args.allow_single):
            print(s)
        for p in floor_refused:
            print(f"  REFUSED sell:{p['asset_id']} {p['item']}: {p['why']}")
    if args.cmd == "plan":
        return
    if floor_refused:  # never sell a copy below our private value: stop before any thread opens
        print(f"Not starting: {len(floor_refused)} sell(s) refused by --floor; raise it or drop those ids.", flush=True)
        sys.exit(2)
    if args.dealer != DEFAULT_DEALER:
        RUN = RunLog(args.dealer)  # logs/<dealer>/<date>.jsonl
    RUN.start(cash=me["cash"], level=me["level"], deals=me["score"].get("deals"), reserve=CASH_RESERVE, cap=args.cap,
              plan=[{k: p.get(k) for k in ("side", "item", "asset_id", "value")} for p in plan[:args.max_deals + 3]],
              **({"dealer": DEALER, "allow_single": args.allow_single, "sell_anchor": SELL_ANCHOR_ABS,
                  "sell_step": SELL_STEP, "floor": args.floor} if extra else {}))
    done = 0
    for target in plan:
        if done >= args.max_deals:
            break
        me = b.me()
        if target["side"] == "buy" and me["cash"] - CASH_RESERVE < max(5, ANCHOR_ABS or 0):
            log("skip_cash", item=target["item"], cash=me["cash"], reserve=CASH_RESERVE, anchor=ANCHOR_ABS)
            continue   # e.g. before the grant: never open at a bid below --anchor and burn a dealer slot
        r = negotiate(b, target, False, resume=args.resume if target is plan[0] else None)
        if r.get("thread"):
            save_thread(b, r["thread"])  # full transcript, her words included
        if r.get("result") == "deal":
            done += 1
        if r.get("code") in ("persona_quota", "cooloff", "locked"):
            log("stop", code=r["code"])
            break
    me = b.me()
    s = me["score"]
    RUN.end(cash=me["cash"], level=me["level"], unlocked=me["unlocked"], deals=s.get("deals"),
            ladder_points=s.get("ladder_points"), score=s.get("score"), rank=s.get("rank"))


if __name__ == "__main__":
    main()
