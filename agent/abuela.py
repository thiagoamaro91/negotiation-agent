"""Abuela Carmen negotiator (the L1 dealer at El Rastro).

Numbers are decided here, in code; the words around them are decoration (structure binds).

What the feed showed on Friday evening, before this was written:
- A team's first deal with her is a fixed "welcome" price (about 0.7 x list: 17 P for a pack or an uncommon,
  7 P for a common). It never moves, and a deal at her opening price does not count toward unlocking L2.
  So we take it once, on the item with the biggest private-value gain.
- After that she opens at about 1.15 x list, concedes ~4 P on her first move, then mirrors our step size.
  She only moves when we move; the same price twice earns nothing.
- When her patience runs out she names a final offer at her limit ("final": true): take it or she walks.

Plan per negotiated deal: anchor low enough that meeting in the middle would cross her limit, then step
1 P per round. Either she holds at her limit, accepts us, or names her limit as a final offer; in every case we
end at (or near) her limit, which is the full share of her price range, the thing the ladder score counts.

Usage (from the repo root):
    python3 agent/abuela.py plan          # show what we would trade and our private values
    python3 agent/abuela.py run           # work through the plan, one conversation at a time
    python3 agent/abuela.py run --only LAV-07,sell:39
Only ONE process per team may talk to Abuela at a time (one open conversation per dealer).
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
from memory import Memory, kind_of  # noqa: E402

FAST_STEPS = False          # team decision: 1 P per round tonight; memory only changes the step if --fast-steps is passed
MEM: Memory | None = None  # learned from every past conversation (agent/memory.py); None with --no-memory
RUN = RunLog("abuela")      # logs/abuela/<date>.jsonl, committed; keys are redacted
DEALER = "abuela"
CASH_RESERVE = 280          # keep the L2 venue bond (250 + 20) plus a little
ANCHOR_FRAC = 0.40          # first counter, as a share of her opening price (buying)
SELL_ANCHOR_MULT = 2.2      # first ask, as a multiple of her opening bid (selling)
STEP = 1                    # primas per round: small steps earn small steps, and run her patience out
WELCOME_MAX_FRAC = 0.75     # a first-deal price at or under 0.75 x book is her fixed welcome price
MAX_ROUNDS = 40


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
    "Buenas tardes, Abuela Carmen! What a beautiful stall. Could you do {p} P for it?",
    "Ay, Abuela, you are very kind. I am a young collector on a small budget: {p} P?",
    "Gracias for your patience, Abuela. I can stretch a little, {p} P.",
    "Your cards remind me of my grandmother's album. {p} P, por favor?",
    "I would treasure it, Abuela. {p} P is what I can manage today.",
    "Que amable! Let me add a little: {p} P.",
    "Abuela, you have the best stall in El Rastro. {p} P?",
    "One more small step from me: {p} P. Gracias, de verdad.",
]
SELL_LINES = [
    "Buenas tardes, Abuela Carmen! I have a spare for your boxes. Would {p} P be fair?",
    "Ay, Abuela, it is in perfect condition, look. {p} P?",
    "Gracias, Abuela. For you I can come down a little: {p} P.",
    "Some child at El Rastro will love it. {p} P, por favor?",
    "You are very kind, Abuela. {p} P and it is yours.",
    "A small step from me: {p} P. Que tenga un buen dia!",
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

def negotiate(b: Bazaar, target: dict, first_deal: bool) -> dict:
    side, item, value = target["side"], target["item"], target["value"]
    asset_id = target.get("asset_id")
    topic = {"buy": {"card": item}} if side == "buy" else {"sell": {"assets": [asset_id]}}
    try:
        th = b.open_thread(DEALER, topic=topic)
    except BazaarError as e:
        log("open_refused", item=item, side=side, code=e.code, msg=e.message)
        return {"result": "refused", "code": e.code}
    tid = th["id"]
    log("open", thread=tid, side=side, item=item, value=value, welcome=first_deal)

    ours: int | None = None
    said = 0
    last_her = None
    answered = None  # id of her offer we last countered
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

        def good(p: int) -> bool:
            return p <= reservation if side == "buy" else p >= reservation

        # 1) the welcome price (~0.7 x book) never moves and is far below our value: take it at once.
        #    Capped at WELCOME_MAX_FRAC x book so a normal opening is never mistaken for it.
        if first_deal and side == "buy" and good(her) and her <= WELCOME_MAX_FRAC * target["book"]:
            b.accept(o["id"])
            log("accept", thread=tid, price=her, why="welcome")
            return settle(b, tid, her)
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
            nxt = int(her * ANCHOR_FRAC) if side == "buy" else int(round(her * SELL_ANCHOR_MULT))
        else:
            step = STEP
            if side == "buy" and MEM and FAST_STEPS and kind_of(item):  # opt-in (--fast-steps): +3 while far from the learned probe, then +1
                step = 3 if MEM.advice(kind_of(item))["probe"] - ours > 3 else STEP
            nxt = ours + step if side == "buy" else ours - STEP
        if side == "buy" and MEM and kind_of(item):  # memory: never bid past what she has ever needed before she names a final
            nxt = min(nxt, MEM.advice(kind_of(item))["ceiling"])
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

def build_plan(b: Bazaar, me: dict, only: list[str] | None) -> list[dict]:
    """Buys: cards Abuela sells (released commons/uncommons) that complete our best pages, ranked by value.
    Sells: our duplicate copies, which are worth only 25% to us."""
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
            if c["rarity"] not in ("common", "uncommon") or c["id"] in held:
                continue
            v = b.value(c["id"])["your_value"]
            buys.append({"side": "buy", "item": c["id"], "name": c["name"], "book": c["book"], "value": v})
    buys.sort(key=lambda x: -(x["value"] - 0.8 * x["book"]))
    sells = []
    for ref, copies in held.items():
        if len(copies) > 1 and copies[0]["rarity"] in ("common", "uncommon"):
            spare = max(copies, key=lambda a: a["serial"])  # keep the lowest serial
            sells.append({"side": "sell", "item": ref, "name": spare["name"], "asset_id": spare["id"],
                          "value": spare["your_value"] + 2})
    plan = []
    for i in range(max(len(buys), len(sells))):  # alternate so cash stays above the reserve
        if i < len(buys):
            plan.append(buys[i])
        if i < len(sells):
            plan.append(sells[i])
    if only:
        keys = set(only)
        plan = [p for p in plan if p["item"] in keys or f"sell:{p.get('asset_id')}" in keys]
    return plan


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--only", default="", help="comma list of card refs and/or sell:<asset_id>")
    ap.add_argument("--max-deals", type=int, default=6)
    ap.add_argument("--no-memory", action="store_true", help="skip the learning step and use the fixed numbers above")
    ap.add_argument("--fast-steps", action="store_true", help="let memory climb +3 P per round while far from its learned probe (default: STEP)")
    args = ap.parse_args()
    global FAST_STEPS
    FAST_STEPS = args.fast_steps
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"])
    global MEM
    if not args.no_memory:
        MEM = Memory.refresh(b)  # analyse every past conversation (ours good and bad, and the public ones) BEFORE doing anything
    me = b.me()
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    plan = build_plan(b, me, only)
    print(f"{me['name']} cash={me['cash']} level={me['level']} deals={me['score'].get('deals')}")
    for p in plan:
        print(f"  {p['side']:4} {p['item']:7} value={p['value']:6.1f}  {p.get('name', '')}")
    if args.cmd == "plan":
        return
    RUN.start(cash=me["cash"], level=me["level"], deals=me["score"].get("deals"),
              plan=[{k: p.get(k) for k in ("side", "item", "asset_id", "value")} for p in plan[:args.max_deals + 3]])
    done = 0
    for target in plan:
        if done >= args.max_deals:
            break
        me = b.me()
        if target["side"] == "buy" and me["cash"] - CASH_RESERVE < 5:
            log("skip_cash", item=target["item"], cash=me["cash"])
            continue
        first = (me["score"].get("deals") or 0) == 0
        r = negotiate(b, target, first)
        if r.get("thread"):
            save_thread(b, r["thread"])  # full transcript, her words included
        if MEM:
            MEM = Memory.refresh(b, public=False, quiet=True)  # learn from the conversation we just had before the next one
            mine = [x for x in MEM.samples if x["source"] == "own" and x["thread"] == r.get("thread")]
            if mine:
                log("lesson", thread=r["thread"], grade=MEM.grade(mine[0])[0], why=MEM.grade(mine[0])[1])
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
