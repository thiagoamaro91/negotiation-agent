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
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402
from runlog import RunLog, save_thread  # noqa: E402

RUN = RunLog("chato")       # logs/chato/<date>.jsonl, committed; keys are redacted
DEALER = "chato"
CASH_RESERVE = 280          # default; the owner may lower it per run with --reserve
ANCHOR_FRAC = 0.40          # first counter, as a share of her opening price (buying)
ANCHOR_ABS = None           # --anchor N: absolute first bid when buying (overrides ANCHOR_FRAC)
SELL_ANCHOR_MULT = 1.6      # first ask, as a multiple of his opening bid (selling); he holds his bid, so stay short
STEP = 1                    # primas per round when buying: he mirrors our step, his final comes at his limit
SELL_STEP = 2               # primas per round when selling (time is short and his bid barely moves)
MAX_ROUNDS = 12             # 60 s ticks: 12 rounds is 12 minutes; his patience is low
DUEL_LOCK = ROOT / "results" / "duel.lock"   # written by agent/duel.py run while any of our duels is live


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


# ---------------------------------------------------------------- one negotiation

def negotiate(b: Bazaar, target: dict, first_deal: bool, resume: int | None = None) -> dict:
    side, item, value = target["side"], target["item"], target["value"]
    asset_id = target.get("asset_id")
    topic = {"buy": {"card": item}} if side == "buy" else {"sell": {"assets": [asset_id]}}
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
                nxt = int(round(her * SELL_ANCHOR_MULT))
        else:
            nxt = ours + STEP if side == "buy" else ours - SELL_STEP
        nxt = int(min(nxt, reservation)) if side == "buy" else int(max(nxt, reservation))
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

def build_plan(b: Bazaar, me: dict, only: list[str] | None, cap: float | None) -> list[dict]:
    """Buys: uncommons and rares Chato sells that we do not hold, ranked by our value.
    Sells: our duplicate uncommons/rares (a spare is worth much less to us). --cap lowers (never raises) our value as the
    most we pay (the ladder scores his price range, not our value)."""
    catalog = b.catalog()
    released = {s["id"] for s in catalog["sets"] if s["released"]}
    held = {}
    for a in me["assets"]:
        if a["kind"] == "card":
            held.setdefault(a["ref"], []).append(a)
    buys = []
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
        if len(copies) > 1 and copies[0]["rarity"] in ("uncommon", "rare"):
            spare = max(copies, key=lambda a: a["serial"])  # keep the lowest serial
            sells.append({"side": "sell", "item": ref, "name": spare["name"], "asset_id": spare["id"],
                          "value": spare["your_value"] + 2, "private": spare["your_value"]})
    plan = sells + buys  # sells first: they bring cash in
    if only:
        keys = set(only)
        plan = [p for p in plan if (p["side"] == "buy" and p["item"] in keys) or f"sell:{p.get('asset_id')}" in keys]
    return plan


def bid_ladder(limit: float, spendable: int) -> list:
    """The bids a buy would walk through with --anchor (shown by plan; she may cross or stop us earlier)."""
    top = int(min(limit, spendable))
    if ANCHOR_ABS is None or top < 1:
        return []
    out, b = [], int(ANCHOR_ABS)
    while b < top and len(out) < 30:
        out.append(b)
        b += STEP
    return out + [top]


def main() -> None:
    global CASH_RESERVE, MAX_ROUNDS, ANCHOR_ABS, STEP
    load_env()
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
    args = ap.parse_args()
    if args.step < 1 or (args.anchor is not None and args.anchor < 1):
        ap.error("--step and --anchor must be >= 1")
    if args.cmd == "run" and duel_lock_fresh():
        print(f"WARNING: {DUEL_LOCK.relative_to(ROOT)} is fresh: the duel bot holds the team's accept slot. "
              "Not starting El Chato; try again after the duel wave.", flush=True)
        return
    ANCHOR_ABS, STEP = args.anchor, args.step
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"])
    me = b.me()
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    plan = build_plan(b, me, only, args.cap)
    CASH_RESERVE = args.reserve
    MAX_ROUNDS = args.max_rounds
    print(f"{me['name']} cash={me['cash']} level={me['level']} deals={me['score'].get('deals')}")
    for p in plan:
        print(f"  {p['side']:4} {p['item']:7} limit={p['value']:6.1f} private={p['private']:6.1f}  {p.get('name', '')}")
    print(f"reserve={CASH_RESERVE} (spendable {me['cash'] - CASH_RESERVE} P) anchor={ANCHOR_ABS or f'{ANCHOR_FRAC} x her ask'} "
          f"step={STEP} cap={args.cap}")
    for p in plan:
        if p["side"] == "buy" and ANCHOR_ABS is not None:
            print(f"  bids {p['item']}: {' '.join(str(x) for x in bid_ladder(p['value'], me['cash'] - CASH_RESERVE))}"
                  f" (then wait for his final; take it if <= {int(min(p['value'], me['cash'] - CASH_RESERVE))})")
    if args.cmd == "plan":
        return
    RUN.start(cash=me["cash"], level=me["level"], deals=me["score"].get("deals"), reserve=CASH_RESERVE, cap=args.cap,
              plan=[{k: p.get(k) for k in ("side", "item", "asset_id", "value")} for p in plan[:args.max_deals + 3]])
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
