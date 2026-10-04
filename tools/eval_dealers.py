"""Offline eval of the dealer negotiators (agent/abuela.py for Abuela Carmen L1, agent/chato.py for El Chato L2 and,
with --dealer pilar, Doña Pilar L3). No network, no key, nothing posted to the game; it only reads logs.

Why: the dealer ladder scores the share of each dealer's price range we capture (best three deals per level), and a
deal on the wrong side of our private value earns nothing. Changing a bot's anchor, step, cap or floor is cheap to try
here and expensive to try live, where every conversation is a ladder slot and a dealer's patience.

Evaluation model (evals/dealers/metrics.md has the full argument):
- Cases are OUR real dealer negotiations (Friday + Saturday), rebuilt from logs/threads/ (complete transcripts) and
  the public feed (logs/feed/ + logs/feed-vm/, which also has the conversations no bot saved).
- Two metric groups per row:
  real_*  the AUDIT of what really happened in that conversation, graded against our private value. Identical in
          every variant: it is the reference, not something a config can change.
  others  a COUNTERFACTUAL REPLAY: the real bot code (abuela.negotiate / chato.negotiate, unchanged) plays the case
          against a simulated dealer. While our bids equal the real ones the dealer answers exactly as the real one
          did (real prefix); from the first different bid on, a dealer model fitted on every OTHER team's
          conversations in the feed answers, conditioned on what this conversation revealed (its final offer is
          taken as its secret limit, the round it came in as its patience). Modelled numbers, never real ones.
- The model is validated by `--validate`: one-step accuracy on held-out conversations (ours, t03) and closed-loop
  fidelity (the bot with the flags it really ran, against the model, should land where the real thread did).
Dealer words and any game text are never read into cases, traces or prompts: prices, ticks, cards, limits only.

Usage (from the repo root):
    python3 tools/eval_dealers.py --variant baseline --reps 5                  # Sunday flags, writes evals/dealers/
    python3 tools/eval_dealers.py --variant v1 --reps 5 --set abuela.step=2 --change "Abuela steps 2 P"
    python3 tools/eval_dealers.py --validate                                   # model + harness checks, prints only
    python3 tools/eval_dealers.py --policy oracle --out-root <scratch>/evals   # harness checks never write evals/
    python3 tools/eval_dealers.py --logs /Volumes/bazaar/logs ...              # read-only logs elsewhere (the Mini)
--set takes <section>.<knob>=<value>; sections and knobs are in BASELINE below (None/none clears a knob).
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools", ROOT / "agent", ROOT / "kit"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import eval_common  # noqa: E402
from eval_common import Run, file_sha, mean_ci, summary_line, write_cases, write_state  # noqa: E402
from bazaar_sdk import BazaarError  # noqa: E402

import abuela  # noqa: E402  (importing the bots writes nothing; RunLog only makes logs/<agent>/ if missing)
import chato  # noqa: E402
from dealer_client import copy_marginal, ladder_floor  # noqa: E402

FLOW = "dealers"
TEAM = "t03"
DEALERS = ("abuela", "chato", "pilar")
EXPIRY = 4                  # a dealer offer lapses 4 ticks after it is posted (thread 472: created 309, expires 313)
BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
COPY_MARGINALS = (1.0, 0.25, 0.1)
PILAR_FAV = ("SAL", "RET")  # her menu lists these sets first; she opens higher on them (22 vs 16)
MAX_SIM_TICKS = 400         # a simulated conversation never runs longer (the bots' budgets are 12-40 rounds)

# The settings Sunday would run (tools/factory_sunday.json, dealer steps; they are off by default there). Sections are
# per dealer and item class; a case uses the section of its dealer/side/rarity.
#   abuela:        r3-slots-1-3  --cap 22 --reserve 20 (abuela.py has no step/anchor/round flags: module defaults)
#   chato.rare:    r3-slot-1-rare --anchor 60 --step 4 --cap 88 --reserve 40 --max-rounds 40
#   chato.uncommon, chato.sell: not run on Sunday, so the bot's own defaults
#   pilar.sell:    r2-fill-mal / r3-resell-ret --floor = ceil(private value) (18 for MAL, 23 for RET), --sell-step 1,
#                  --max-rounds 40; the first ask uses the bot's rule max(1.25 x her bid, floor + 9) (Sunday wrote
#                  27 for floor 18, which matches, and 30 for floor 23, where the rule gives 32)
# Cash is never binding in the eval (reserve + 10^6 P): the limit is min(private value, cap) for a buy.
BASELINE = {
    "abuela": {"cap": 22, "step": 1, "anchor_frac": 0.40, "max_rounds": 40, "sell_anchor_mult": 2.2,
               "floor_margin": 2},
    "chato.rare": {"anchor": 60, "step": 4, "cap": 88, "max_bid": None, "max_rounds": 40},
    "chato.uncommon": {"anchor": None, "step": 1, "cap": None, "max_bid": None, "max_rounds": 12},
    "chato.sell": {"sell_anchor": None, "sell_step": None, "max_rounds": None, "floor_margin": 2},
    "pilar.sell": {"sell_anchor": None, "sell_step": 1, "max_rounds": 40, "floor_margin": 0},
}


# ================================================================ reading the logs

def read_jsonl(path: Path) -> list:
    out = []
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a recorder cut mid-line: skip it
    return out


def load_events(logs: Path) -> list:
    """Public feed events from both recorders (the VM one has no Friday gap), deduplicated by event id."""
    seen = {}
    for p in (logs / "feed" / "feed.jsonl", logs / "feed-vm" / "feed.jsonl"):
        for e in read_jsonl(p):
            if isinstance(e, dict) and "id" in e:
                seen[e["id"]] = e
    return [seen[k] for k in sorted(seen)]


def load_cards(logs: Path) -> dict:
    p = logs / "public" / "catalog.json"
    if not p.exists():
        p = ROOT / "logs" / "public" / "catalog.json"
    cat = json.loads(p.read_text())
    return {c["id"]: {"set": s["id"], "rarity": c["rarity"], "book": c["book"]} for s in cat["sets"] for c in s["cards"]}


def load_me(logs: Path) -> dict:
    p = logs / "state" / "me.json"
    return json.loads(p.read_text()) if p.exists() else {}


def offer_cash(o: dict):
    if not o:
        return None
    v = (o.get("want") or {}).get("cash") or (o.get("give") or {}).get("cash")
    return int(v) if v else None


def offer_ref(o: dict):
    for side in ("give", "want"):
        part = (o or {}).get(side) or {}
        for a in part.get("assets") or []:
            if isinstance(a, dict) and a.get("ref"):
                return a["ref"], a.get("id")
        for t in part.get("types") or []:
            if isinstance(t, str) and t.startswith("card:"):
                return t.split(":", 1)[1], None
    return None, None


def raw_threads(logs: Path, events: list) -> dict:
    """{thread id: {team, dealer, topic, open_tick, msgs: [(order, tick, sender, price, final, ref, asset, status)]}}
    for every dealer conversation. Thread files (complete) win over the feed (which has gaps)."""
    out = {}
    for e in events:
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if p.get("kind") != "persona" or p.get("with") not in DEALERS:
            continue
        tid = p.get("thread")
        if e["type"] == "thread.opened":
            t = out.setdefault(tid, {"team": p.get("team"), "dealer": p["with"], "msgs": [], "source": "feed"})
            t.update(topic=p.get("topic"), open_tick=e.get("tick"))
        elif e["type"] == "thread.message":
            t = out.setdefault(tid, {"team": p.get("team"), "dealer": p["with"], "msgs": [], "source": "feed",
                                     "topic": None, "open_tick": e.get("tick")})
            o = p.get("offer") or {}
            ref, asset = offer_ref(o)
            t["msgs"].append((e["id"], e.get("tick"), p.get("sender"), offer_cash(o), bool(o.get("final")), ref, asset,
                              None))
    for f in sorted((logs / "threads").glob("thread-*.json")):
        try:
            th = json.loads(f.read_text())
        except ValueError:
            continue
        if th.get("with") not in DEALERS or th.get("kind") not in (None, "persona"):
            continue
        msgs = []
        for m in th.get("messages") or []:
            o = m.get("offer") or {}
            ref, asset = offer_ref(o)
            msgs.append((m.get("id"), m.get("tick"), m.get("sender"), offer_cash(o), bool(o.get("final")), ref, asset,
                         o.get("status")))
        out[th["id"]] = {"team": th.get("team"), "dealer": th["with"], "topic": th.get("topic"),
                         "open_tick": th.get("created_tick"), "msgs": msgs, "source": "thread_file",
                         "status": th.get("status"), "closed_reason": th.get("closed_reason")}
    for t in out.values():
        t["msgs"].sort(key=lambda m: (m[0] is None, m[0]))
    return out


def dealer_settlements(events: list) -> list:
    out = []
    for e in events:
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if e["type"] == "settlement" and p.get("persona") in DEALERS:
            team = [x for x in p.get("parties") or [] if x != p["persona"]]
            out.append({"tick": e.get("tick"), "dealer": p["persona"], "team": team[0] if team else None,
                        "price": p.get("price"), "refs": [i.get("ref") for i in p.get("items") or []]})
    return out


def day_starts(events: list) -> list:
    return sorted((e.get("tick") or 0, (e.get("payload") or {}).get("day")) for e in events if e["type"] == "day.opened")


def day_of(tick, starts: list) -> str:
    day = "?"
    for t, d in starts:
        if tick is not None and tick >= t:
            day = d
    return day


# ================================================================ one negotiation, as numbers

def rebuild(tid: int, t: dict, cards: dict, setts: list, used: set) -> dict:
    """Prices only: the dealer's offers D, our offers U, the dealer's answer to each of ours, the outcome."""
    dealer = t["dealer"]
    topic = t.get("topic") or {}
    side = "buy" if "buy" in topic else ("sell" if "sell" in topic else None)
    item = asset = kind = None
    if side == "buy":
        v = topic["buy"] or {}
        if "card" in v:
            item, kind = v["card"], "card"
        elif "pack" in v:
            item, kind = v["pack"], "pack"
    elif side == "sell":
        ids = (topic["sell"] or {}).get("assets") or []
        asset = ids[0] if ids else None
        kind = "card"
    for m in t["msgs"]:
        if item is None and m[5]:
            item, kind = m[5], "card"
            if side is None:
                side = "buy" if m[2] == dealer else "sell"
        if side == "sell" and asset is None and m[6]:
            asset = m[6]
    D = [(m[1], m[3], m[4], m[7]) for m in t["msgs"] if m[2] == dealer]
    U = [(m[1], m[3], m[7]) for m in t["msgs"] if m[2] != dealer]
    resp = [D[k + 1] if k + 1 < len(D) else None for k in range(len(U))]
    info = cards.get(item or "", {})
    r = {"thread": tid, "team": t.get("team"), "dealer": dealer, "side": side, "kind": kind, "item": item,
         "asset_id": asset, "rarity": info.get("rarity"), "set": info.get("set"), "book": info.get("book"),
         "open_tick": t.get("open_tick"), "source": t.get("source"),
         "D": [[d[0], d[1], d[2]] for d in D], "U": [[u[0], u[1]] for u in U],
         "resp": [None if x is None else [x[1], x[2]] for x in resp]}
    # outcome: a thread file says it exactly (the settled offer); otherwise match the feed's settlement
    deal_price = deal_by = None
    if t.get("source") == "thread_file":
        if t.get("status") == "deal":
            for m in t["msgs"]:
                if m[7] == "settled":
                    deal_price = m[3]
                    deal_by = "dealer_accepted_ours" if m[2] != dealer else ("took_final" if m[4] else "took_ask")
    else:
        ticks = [m[1] for m in t["msgs"] if m[1] is not None]
        if ticks:
            for i, s in enumerate(setts):
                if i in used or s["dealer"] != dealer or s["team"] != t.get("team"):
                    continue
                if (item in s["refs"]) and min(ticks) <= (s["tick"] or 0) <= max(ticks) + 3:
                    used.add(i)
                    deal_price = s["price"]
                    break
        if deal_price is not None:
            finals = [d[1] for d in D if d[2]]
            if finals and deal_price == finals[-1]:
                deal_by = "took_final"
            elif U and U[-1][1] == deal_price and (not D or D[-1][1] != deal_price):
                deal_by = "dealer_accepted_ours"
            elif deal_price in [d[1] for d in D]:
                deal_by = "took_ask"
            else:
                deal_by = "unknown"
    final = next(([d[1], k] for k, d in enumerate(D) if d[2]), None)   # [price, dealer message index]
    r["final"] = final
    if deal_price is not None:
        r["outcome"] = "deal"
    elif final is not None:
        r["outcome"] = "walked_after_final"
    else:
        r["outcome"] = "no_deal"
    r["deal_price"], r["deal_by"] = deal_price, deal_by
    return r


def all_negotiations(logs: Path) -> tuple:
    events = load_events(logs)
    cards = load_cards(logs)
    setts = dealer_settlements(events)
    raw = raw_threads(logs, events)
    used = set()
    negos = [rebuild(tid, raw[tid], cards, setts, used) for tid in sorted(raw)]
    return negos, events, cards


def class_key(dealer: str, side: str, rarity: str, set_: str) -> str:
    k = f"{dealer}.{side}.{rarity}"
    if dealer == "pilar":
        k += ".fav" if set_ in PILAR_FAV else ".other"
    return k


def step_bucket(step):
    if step is None:
        return "first"
    if step <= 0:
        return 0
    return min(int(step), 4)


# ================================================================ the dealer model

class DealerModel:
    """Fitted on every conversation in the feed except `exclude_team`'s (ours), per class (dealer, side, rarity):
    - drops[(i, step)]: the dealer's move toward us when answering our i-th offer (0-based, 3 = 3 or later) after
      we moved `step` P ("first" for our opening offer, 0 = no move, 4 = 4 or more). Backs off to (i, any step),
      then to (any i, step), then to the class.
    - L: final offers (taken as the conversation's secret limit), P: our offer count when the final came,
      tol: how far from his own new price a dealer still accepted our offer.
    - ref_open / ref_best: the class's usual opening and the 10th (buy) / 90th (sell) percentile of negotiated deal
      prices: the reference spread range_share is measured on."""

    MIN_CELL = 5

    def __init__(self, negos: list, exclude_team: str = TEAM):
        self.t = collections.defaultdict(lambda: {"drops": collections.defaultdict(list), "L": [], "P": [], "tol": [],
                                                  "open": collections.Counter(), "deals": [], "n": 0})
        self.welcome = set()
        for r in negos:
            if r["side"] not in ("buy", "sell") or r["kind"] != "card" or not r["rarity"] or not r["D"]:
                continue
            if r["D"][0][1] is None:
                continue
            key = class_key(r["dealer"], r["side"], r["rarity"], r["set"])
            if self.is_welcome(r):
                self.welcome.add(r["thread"])
                continue
            c = self.t[key]
            c["open"][r["D"][0][1]] += 1
            if r["deal_price"] is not None:
                c["deals"].append(r["deal_price"])
            if r["team"] == exclude_team:
                continue
            c["n"] += 1
            self._fit_one(c, r)

    @staticmethod
    def is_welcome(r: dict) -> bool:
        """Abuela's fixed first-deal price (17 for an uncommon, 7 for a common: about 0.7 x list)."""
        if r["dealer"] != "abuela" or r["side"] != "buy" or not r["D"] or r["D"][0][1] is None:
            return False
        return r["D"][0][1] <= 0.75 * BOOK.get(r["rarity"], 10)

    def _fit_one(self, c: dict, r: dict) -> None:
        sign = 1 if r["side"] == "buy" else -1
        a = r["D"][0][1]
        prev_b = None
        for i, (u, resp) in enumerate(zip(r["U"], r["resp"])):
            b = u[1]
            if resp is None:
                break
            step = None if prev_b is None else (0 if b is None else sign * (b - prev_b))
            if resp[0] is None:  # no price in his answer: he accepted our offer if it settled at our price
                if b is not None and r["deal_price"] == b and r["deal_by"] in ("dealer_accepted_ours", "unknown"):
                    c["tol"].append(max(0, sign * (a - b)))
                break
            if resp[1]:
                c["L"].append(resp[0])
                c["P"].append(i + 1)
                break
            c["drops"][(min(i, 3), step_bucket(step))].append(sign * (a - resp[0]))
            a = resp[0]
            if b is not None:
                prev_b = b

    def has(self, key: str) -> bool:
        return key in self.t and self.t[key]["n"] > 0

    def cell(self, key: str, i: int, s) -> list:
        d = self.t[key]["drops"]
        exact = d.get((min(i, 3), s), [])
        if len(exact) >= self.MIN_CELL:
            return exact
        same_i = [x for (ii, ss), v in d.items() if ii == min(i, 3) and ss != 0 for x in v] if s != 0 else []
        if s != 0 and len(same_i) >= self.MIN_CELL:
            return same_i
        same_s = [x for (ii, ss), v in d.items() if ss == s for x in v]
        if len(same_s) >= self.MIN_CELL:
            return same_s
        pooled = [x for (ii, ss), v in d.items() if (ss != 0) == (s != 0) for x in v]
        return pooled or [0]

    def refs(self, key: str, side: str) -> tuple:
        c = self.t[key]
        ref_open = c["open"].most_common(1)[0][0] if c["open"] else None
        deals = sorted(c["deals"])
        if len(deals) >= 3:
            q = 0.10 if side == "buy" else 0.90
            ref_best = deals[min(len(deals) - 1, max(0, int(round(q * (len(deals) - 1)))))]
        elif c["L"]:
            ref_best = min(c["L"]) if side == "buy" else max(c["L"])
        else:
            ref_best = ref_open
        return ref_open, ref_best


def med(xs: list):
    return statistics.median_low(sorted(xs)) if xs else None


def conversation_params(case: dict, model: DealerModel, rng: random.Random, deterministic: bool) -> dict:
    """The conversation's hidden numbers. What the real thread revealed is used as it is (a final offer = its secret
    limit and its patience); the rest is drawn from the class prior, kept consistent with what the thread showed."""
    key, side = case["class"], case["side"]
    c = model.t[key]
    real = case["real"]
    sign = 1 if side == "buy" else -1
    pick = (lambda xs: med(xs)) if deterministic else (lambda xs: rng.choice(xs) if xs else None)
    if case.get("welcome"):
        return {"L": case["opening"], "P": 10 ** 6, "tol": 0, "L_from": "welcome", "P_from": "welcome"}
    seen = [d[1] for d in real["D"] if d[1] is not None]
    if real["final"] is not None:
        L, L_from = real["final"][0], "real_final"
    else:
        bound = min(seen) if side == "buy" else max(seen)
        if real["deal_price"] is not None:
            bound = min(bound, real["deal_price"]) if side == "buy" else max(bound, real["deal_price"])
        ok = [x for x in c["L"] if sign * (bound - x) >= 0]
        L = pick(ok) if ok else bound
        L_from = "prior" if ok else "bound"
    answered = sum(1 for x in real["resp"] if x is not None and x[0] is not None and not x[1])
    final_k = None
    if real["final"] is not None:
        for k, x in enumerate(real["resp"]):
            if x is not None and x[1]:
                final_k = k + 1
                break
    if final_k is not None:
        P, P_from = final_k, "real_final"
    else:
        okp = [x for x in c["P"] if x > answered]
        P = pick(okp) if okp else answered + 1
        P_from = "prior" if okp else "bound"
    tol = pick(c["tol"]) if c["tol"] else 1
    return {"L": int(L), "P": int(P), "tol": int(tol), "L_from": L_from, "P_from": P_from}


# ================================================================ what /api/me would say for a case

def account_view(case: dict, affinity: dict = None) -> dict:
    """What the live /api/me would return while this case's conversation runs, in its real shape (affinity, and assets
    with id, kind, ref, serial, rarity, set, your_value): the bots re-read it before every decision and re-price the card
    from it (agent/dealer_client.live_limit), so a harness that answered only {"cash": ...} would close every thread as
    limit_unknown. The account is built so that it says what the case says, never something kinder:
      buy:  we hold the copies the case's private value implies (private_source "..._copyN": N - 1 held, else none), and
            the set multiplier is `affinity[set]` when given (the real one, from logs/state/me.json), else the one that
            makes book x multiplier x copy marginal equal the case's private value
      sell: the copy sold (asset_id, your_value = private) plus the copies that make it a spare of the right rank: the
            fewest held (1, 2, 3) for which ceil(book x multiplier x marginal) does not exceed ceil(private)
    so the live gate never sits above the case's own value and never below it by more than the rounding."""
    item, rarity, side = case["item"], case.get("rarity"), case["side"]
    book = case.get("book") or BOOK.get(rarity, 0)
    set_id = str(item).split("-")[0]   # the set the bots look the multiplier up by (case["set"] is the same in real data)
    private = float(case["private"])
    base = {"kind": "card", "ref": item, "rarity": rarity, "set": set_id, "name": item, "print_run": None}
    assets = []
    if side == "buy":
        src = str(case.get("private_source") or "")
        held = int(src.rsplit("_copy", 1)[1]) - 1 if "_copy" in src and src.rsplit("_copy", 1)[1].isdigit() else 0
        mult = (affinity or {}).get(set_id)
        if mult is None and book:
            mult = private / (book * copy_marginal(held + 1))
        for i in range(held):
            assets.append(dict(base, id=800000 + i, serial=i + 1, your_value=private))
    else:
        mult = (affinity or {}).get(set_id)
        n = 3
        if mult is None and book:
            n = 2 if str(case.get("private_source")) in ("assumed_spare", "bot_log_floor_minus_2") else 1
            mult = private / (book * copy_marginal(n))
        else:
            for k in (1, 2, 3):
                g = ladder_floor(book, mult, copy_marginal(k))
                if g is not None and g <= math.ceil(private):
                    n = k
                    break
        assets.append(dict(base, id=case["asset_id"], serial=99, your_value=private))
        for i in range(n - 1):
            assets.append(dict(base, id=810000 + i, serial=i + 1, your_value=private))
    return {"cash": 10 ** 6, "score": {"deals": 1}, "affinity": {set_id: mult} if mult is not None else {},
            "assets": assets}


# ================================================================ the simulated dealer the bots talk to

class SimDealer:
    """Duck-typed stand-in for agent/dealer_client.DealerBazaar: the calls abuela.negotiate / chato.negotiate make
    (open_thread, thread, me, say, accept, close_thread, wait_tick). One message per tick, the dealer answers on the
    next tick, his offers lapse EXPIRY ticks after they are posted, an accept settles on the next tick, a message after
    his final offer makes him walk, and repeating a price earns nothing. While our offers equal the real thread's
    (and `prefix` is on) he answers with the real dealer's numbers; afterwards with the model."""

    TID = 9000

    def __init__(self, case: dict, model: DealerModel, params: dict, seed: str, deterministic: bool,
                 prefix: bool = True, model_on: bool = True, affinity: dict = None):
        self.case, self.model, self.p = case, model, params
        self.affinity = affinity
        self.seed, self.det = seed, deterministic
        self.prefix, self.model_on = prefix, model_on
        self.sign = 1 if case["side"] == "buy" else -1
        self.tick = 1000
        self.start = None
        self.status = None
        self.closed_reason = None
        self.offers = []
        self.next_id = 1
        self.pending = []          # our offers waiting for his answer: (tick sent, price)
        self.k = 0                 # our offers answered so far
        self.prev_bid = None
        self.ask = None
        self.final_posted = False
        self.said_tick = None
        self.pending_accept = None
        self.deal = None           # (price, by)
        self.diverged_at = None    # our offer number (1-based) where the real prefix ended
        self.events = []           # (tick, who, what, price, source) for the trace
        self.offers_seen = []      # every price the dealer offered (for missed_ok_offer)

    # ---- dealer side
    def _post(self, price: int, final: bool, source: str) -> None:
        for o in self.offers:
            if o["status"] == "open":
                o["status"] = "cancelled"
        c = self.case
        if c["side"] == "buy":
            give, want = {"cash": 0, "assets": [], "types": [f"card:{c['item']}"]}, {"cash": price, "assets": [], "types": []}
        else:
            give, want = {"cash": price, "assets": [], "types": []}, {"cash": 0, "assets": [{"id": c["asset_id"]}], "types": []}
        o = {"id": self.next_id, "maker": c["dealer"], "status": "open", "final": final, "give": give, "want": want,
             "created_tick": self.tick, "expires_tick": self.tick + EXPIRY}
        self.next_id += 1
        self.offers.append(o)
        self.ask = price
        self.final_posted = self.final_posted or final
        self.offers_seen.append(price)
        self.events.append((self.tick, "dealer", "final" if final else "offer", price, source))

    def _accept_ours(self, price: int, source: str) -> None:
        self.status = "deal"
        self.deal = (price, "dealer_accepted_ours")
        self.events.append((self.tick, "dealer", "accepts our offer", price, source))

    def _walk(self, why: str) -> None:
        self.status, self.closed_reason = "closed", why
        for o in self.offers:
            if o["status"] == "open":
                o["status"] = "cancelled"
        self.events.append((self.tick, "dealer", why, None, "rule"))

    def _rng(self, *parts) -> random.Random:
        return random.Random(":".join(str(x) for x in (self.seed,) + parts))

    def _answer(self, bid) -> None:
        self.k += 1
        real = self.case["real"]
        k = self.k
        if self.final_posted:  # he named his last word and we did not take it: he walks
            self._walk("walked_after_final")
            return
        if self.prefix and self.diverged_at is None:
            if k <= len(real["U"]) and real["U"][k - 1][1] == bid and real["resp"][k - 1] is not None:
                r = real["resp"][k - 1]
                if r[0] is None:
                    if real["deal_price"] == bid:
                        self._accept_ours(bid, "real")
                        self.prev_bid = bid
                        return
                else:
                    self._post(r[0], r[1], "real")
                    self.prev_bid = bid
                    return
            self.diverged_at = k
        if not self.model_on:
            self.events.append((self.tick, "dealer", "silent (no real answer, model off)", None, "rule"))
            return
        self._model_answer(bid)

    def _model_answer(self, bid) -> None:
        sign, L, P, tol = self.sign, self.p["L"], self.p["P"], self.p["tol"]
        if self.case.get("welcome"):
            self._post(self.ask, False, "model")
            return
        step = None if self.prev_bid is None else (0 if bid is None else sign * (bid - self.prev_bid))
        s = step_bucket(step)
        if s == 0:
            drop = 0
        else:
            cell = self.model.cell(self.case["class"], self.k - 1, s)
            drop = med(cell) if self.det else self._rng("drop", self.k).choice(cell)
        new = self.ask - sign * drop
        new = max(L, new) if sign == 1 else min(L, new)
        if bid is not None:
            self.prev_bid = bid
        past_limit = bid is not None and (bid >= L if sign == 1 else bid <= L)
        if past_limit and (sign * (new - bid) <= tol or self.k >= P):  # close enough, or out of patience
            self._accept_ours(bid, "model")
        elif self.k >= P:
            self._post(L, True, "model")
        else:
            self._post(new, False, "model")

    def _turn(self) -> None:
        if self.pending_accept is not None:
            o, self.pending_accept = self.pending_accept, None
            if self.status == "open":
                self.status = "deal"
                o["status"] = "accepted"
                self.deal = (offer_cash(o), "took_final" if o["final"] else "took_ask")
            return
        if self.status != "open":
            return
        for o in self.offers:
            if o["status"] == "open" and o["expires_tick"] <= self.tick:
                o["status"] = "expired"
        due = [m for m in self.pending if m[0] < self.tick]
        self.pending = [m for m in self.pending if m[0] >= self.tick]
        for _, price in due:
            if self.status == "open":
                self._answer(price)

    # ---- the client surface the bots use
    def open_thread(self, with_, topic=None, venue=None):
        if with_ != self.case["dealer"]:
            raise BazaarError("not_found", "wrong dealer", 404)
        if self.status == "open":
            raise BazaarError("thread_exists", "", 409)
        self.status, self.start = "open", self.tick
        self.events.append((self.tick, "us", "open", None, "policy"))
        self._post(self.case["opening"], False, "real")
        return {"id": self.TID, "status": "open"}

    def thread(self, tid):
        if tid != self.TID or self.status is None:
            raise BazaarError("not_found", "", 404)
        return {"id": tid, "status": self.status, "closed_reason": self.closed_reason, "messages": [],
                "standing_offers": [dict(o) for o in self.offers if o["status"] in ("open", "queued")]}

    def me(self):
        return account_view(self.case, self.affinity)

    def say(self, tid, text="", price=None, offer=None, topic=None):
        if self.status != "open":
            raise BazaarError("thread_closed", "", 409)
        if self.said_tick == self.tick:
            raise BazaarError("wait_for_tick", "one message per thread per tick", 429)
        self.said_tick = self.tick
        p = None if price is None else int(price)
        self.pending.append((self.tick, p))
        self.events.append((self.tick, "us", "offer", p, "policy"))
        return {"ok": True}

    def accept(self, oid):
        o = next((x for x in self.offers if x["id"] == oid), None)
        if o is None or o["status"] != "open" or self.status != "open":
            raise BazaarError("offer_not_open", "", 409)
        o["status"] = "queued"
        self.pending_accept = o
        self.events.append((self.tick, "us", "accept", offer_cash(o), "policy"))
        return {"ok": True}

    def close_thread(self, tid):
        if self.status != "open":
            raise BazaarError("thread_closed", "", 409)
        self.status, self.closed_reason = "closed", "closed_by_us"
        for o in self.offers:
            if o["status"] in ("open", "queued"):
                o["status"] = "cancelled"
        self.events.append((self.tick, "us", "close", None, "policy"))
        return {"ok": True}

    def wait_tick(self):
        self.tick += 1
        if self.start is not None and self.tick - self.start > MAX_SIM_TICKS:
            raise RuntimeError(f"simulated conversation passed {MAX_SIM_TICKS} ticks")
        self._turn()
        return {"tick": self.tick}


# ================================================================ policies

class NullRun:
    """Stands in for the bots' RunLog: nothing is written to logs/."""

    def __init__(self):
        self.events = []

    def event(self, event, **data):
        self.events.append((event, data))

    def start(self, **data):
        pass

    def end(self, **data):
        pass


BOT_GLOBALS = ("CASH_RESERVE", "MAX_ROUNDS", "ANCHOR_ABS", "ANCHOR_FRAC", "STEP", "MAX_BID", "RUN", "DEALER",
               "DEALER_NAME", "SELL_RARITIES", "DEALER_SELLS_CARDS", "SELL_ANCHOR_MULT", "SELL_ANCHOR_OVER_FLOOR",
               "SELL_ANCHOR_ABS", "SELL_STEP", "MAX_DEFER_TICKS", "duel_lock_fresh")


@contextlib.contextmanager
def bot_globals(mod):
    saved = {n: getattr(mod, n) for n in BOT_GLOBALS if hasattr(mod, n)}
    try:
        yield
    finally:
        for n, v in saved.items():
            setattr(mod, n, v)


def section_of(case: dict) -> str:
    if case["dealer"] == "abuela":
        return "abuela"
    if case["dealer"] == "pilar":
        return "pilar.sell"
    if case["side"] == "sell":
        return "chato.sell"
    return "chato.rare" if case["rarity"] == "rare" else "chato.uncommon"


def bot_target(case: dict, cfg: dict) -> dict:
    """What the bot's build_plan would hand to negotiate(): the limit is min(private, cap) for a buy, and a floor of
    ceil(private) + floor_margin for a sell (chato.py's default is private + 2; Sunday's --floor is ceil(private))."""
    private = case["private"]
    if case["side"] == "buy":
        cap = cfg.get("cap")
        value = min(private, cap) if cap is not None else private
        if cfg.get("limit_override") is not None:  # fidelity runs: exactly the limit the real bot logged
            value = cfg["limit_override"]
        return {"side": "buy", "item": case["item"], "name": case["item"],
                "book": case["book"] or BOOK.get(case["rarity"], 0), "value": value, "private": private}
    if cfg.get("floor") is not None:
        floor = cfg["floor"]
    else:
        floor = math.ceil(private + (cfg.get("floor_margin") or 0))
    return {"side": "sell", "item": case["item"], "name": case["item"], "asset_id": case["asset_id"],
            "value": floor, "private": private}


def run_bot(case: dict, cfg: dict, sim: SimDealer) -> dict:
    """The real decision code: abuela.negotiate or chato.negotiate, unchanged, against the simulated dealer."""
    mod = abuela if case["dealer"] == "abuela" else chato
    target = bot_target(case, cfg)
    with bot_globals(mod):
        mod.RUN = NullRun()
        mod.duel_lock_fresh = lambda *a, **k: False
        mod.CASH_RESERVE = 0
        if mod is abuela:
            mod.STEP = int(cfg.get("step", 1))
            mod.ANCHOR_FRAC = float(cfg.get("anchor_frac", 0.40))
            mod.MAX_ROUNDS = int(cfg.get("max_rounds", 40))
            mod.SELL_ANCHOR_MULT = float(cfg.get("sell_anchor_mult", 2.2))
        else:
            mod.apply_dealer(case["dealer"], cfg.get("sell_anchor"), cfg.get("sell_step"), cfg.get("max_rounds"))
            mod.ANCHOR_ABS = cfg.get("anchor")
            mod.STEP = int(cfg.get("step") or 1)
            mod.MAX_BID = cfg.get("max_bid")
        r = mod.negotiate(sim, target, bool(case.get("welcome")))
    return {"result": r.get("result"), "limit": target["value"]}


def run_null(case: dict, cfg: dict, sim: SimDealer) -> dict:
    """Opens the conversation, never offers or accepts, closes when the round budget is gone."""
    sim.open_thread(case["dealer"])
    for _ in range(int(cfg.get("max_rounds") or 12)):
        sim.wait_tick()
    if sim.status == "open":
        sim.close_thread(SimDealer.TID)
    return {"result": "null", "limit": None}


def run_reckless(case: dict, cfg: dict, sim: SimDealer) -> dict:
    """Accepts the dealer's first standing offer, whatever its price (the guardrail must light up)."""
    sim.open_thread(case["dealer"])
    o = sim.thread(SimDealer.TID)["standing_offers"][-1]
    sim.accept(o["id"])
    sim.wait_tick()
    return {"result": "reckless", "limit": None}


def run_oracle(case: dict, cfg: dict, sim: SimDealer) -> dict:
    """Knows the conversation's secret limit L and takes it if it is inside our private value: the best in-limit
    price the dealer would ever give. An upper bound for the grader, not a policy anyone could run."""
    sim.open_thread(case["dealer"])
    L = sim.p["L"]
    ok = L <= case["private"] if case["side"] == "buy" else L >= case["private"]
    if ok:
        sim._post(L, True, "oracle")
        sim.accept(sim.offers[-1]["id"])
        sim.wait_tick()
    else:
        sim.close_thread(SimDealer.TID)
    return {"result": "oracle", "limit": case["private"]}


POLICIES = {"bot": run_bot, "null": run_null, "reckless": run_reckless, "oracle": run_oracle}


# ================================================================ grading

def in_limit(side: str, price, private) -> bool:
    return price is not None and (price <= private if side == "buy" else price >= private)


def share(side: str, price, open_, best) -> float:
    """Share of [open_, best] captured: 0 at the opening, 1 at (or past) the reference best price."""
    if price is None or open_ is None or best is None:
        return 0.0
    span = (open_ - best) if side == "buy" else (best - open_)
    got = (open_ - price) if side == "buy" else (price - open_)
    if span <= 0:
        return 1.0 if got >= 0 else 0.0
    return max(0.0, min(1.0, got / span))


def book_value(case: dict, affinity: dict):
    """Our value of a bought card computed here, independently of case["private"] and of the bot's limit: book x set
    multiplier (first copy). None for a sell or an unknown set (over_value then never fires)."""
    if case.get("side") != "buy" or not affinity or case.get("set") not in affinity or case.get("book") is None:
        return None
    return round(case["book"] * affinity[case["set"]], 2)


def grade(case: dict, price, offers_seen: list, L=None, prefix: str = "", value=None) -> dict:
    """value: book x set multiplier (book_value) for over_value, the guardrail that a buy never pays more than the card
    is worth to us whatever limit the bot was handed (Friday: LAT-06/07 bought at 28/29 against 27.5, from a bot
    limit of 30/31)."""
    side, private = case["side"], case["private"]
    ok = in_limit(side, price, private)
    g = {
        prefix + "deal_in_limit": 1 if ok else 0,
        prefix + "over_value": 1 if (side == "buy" and price is not None and value is not None and price > value)
        else 0,
        prefix + "range_share": round(share(side, price, case["ref_open"], case["ref_best"]), 4) if ok else 0.0,
        prefix + "limit_breach": 1 if (price is not None and not ok) else 0,
        prefix + "missed_ok_offer": 1 if (price is None and any(in_limit(side, p, private) for p in offers_seen)) else 0,
    }
    if L is not None:
        g[prefix + "limit_share"] = round(share(side, price, case["opening"], L), 4) if ok else 0.0
    return g


def real_grade(case: dict, value=None) -> dict:
    real = case["real"]
    return grade(case, real["deal_price"], [d[1] for d in real["D"] if d[1] is not None], prefix="real_",
                 value=value)


METRICS = [
    {"id": "deal_in_limit", "kind": "binary", "label": "deal in limit"},
    {"id": "over_value", "kind": "binary", "better": "lower", "label": "over value"},
    {"id": "range_share", "kind": "float", "scale": 1, "label": "range share"},
    {"id": "limit_share", "kind": "float", "scale": 1, "label": "limit share"},
    {"id": "limit_breach", "kind": "binary", "better": "lower", "label": "limit breach"},
    {"id": "missed_ok_offer", "kind": "binary", "better": "lower", "label": "missed offer"},
    {"id": "real_deal_in_limit", "kind": "binary", "label": "REAL in limit"},
    {"id": "real_over_value", "kind": "binary", "better": "lower", "label": "REAL over value"},
    {"id": "real_range_share", "kind": "float", "scale": 1, "label": "REAL share"},
    {"id": "real_limit_breach", "kind": "binary", "better": "lower", "label": "REAL breach"},
    {"id": "real_missed_ok_offer", "kind": "binary", "better": "lower", "label": "REAL missed"},
]
PERF = [{"id": "rounds", "label": "our offers"}, {"id": "ticks", "label": "ticks"},
        {"id": "real_prefix", "label": "real answers"}, {"id": "latency_s", "label": "latency", "unit": "s"}]


# ================================================================ cases

def bot_runs(logs: Path) -> dict:
    """{thread: {agent, argv, limit}} from the bots' own logs (logs/<agent>/*.jsonl): the flags each conversation
    really ran with, and the limit the bot logged when it opened (value = min(private, cap) or the sell floor)."""
    out = {}
    for agent in DEALERS:
        argv = None
        for f in sorted((logs / agent).glob("*.jsonl")):
            for e in read_jsonl(f):
                if e.get("event") == "run_start":
                    argv = e.get("argv")
                elif e.get("event") in ("open", "resume") and e.get("thread") is not None:
                    rec = out.setdefault(e["thread"], {"agent": agent, "argv": argv, "limit": e.get("value"),
                                                       "runs": 0})
                    rec["runs"] += 1
    return out


def private_value(r: dict, me: dict, cards: dict, run: dict) -> tuple:
    """Our private value of the card at stake. Buys: book x set multiplier for a first copy (the bots only buy cards
    we do not hold). Sells: the copy's your_value in logs/state/me.json, else the bot's logged floor minus its +2
    margin, else a spare (x0.25)."""
    aff = (me.get("affinity") or {}).get(r["set"])
    if aff is None:
        return None, "no_affinity"
    book = r["book"] or BOOK.get(r["rarity"], 0)
    if r["side"] == "buy":
        held = sum(1 for a in me.get("assets") or [] if a.get("ref") == r["item"])
        if me.get("tick") is not None and r["open_tick"] is not None and r["open_tick"] < me["tick"]:
            held = 0  # bought before the snapshot: the bot only targets cards we did not hold then
        m = COPY_MARGINALS[min(held, len(COPY_MARGINALS) - 1)]
        return round(book * aff * m, 2), "book_x_multiplier" + ("" if held == 0 else f"_copy{held + 1}")
    for a in me.get("assets") or []:
        if a.get("id") == r["asset_id"] and a.get("your_value") is not None:
            return float(a["your_value"]), "me_json"
    if run and run.get("limit") is not None and "--floor" not in (run.get("argv") or []):
        return float(run["limit"]) - 2, "bot_log_floor_minus_2"
    return round(book * aff * COPY_MARGINALS[1], 2), "assumed_spare"


def build_cases(logs: Path, model: DealerModel, negos: list, events: list, cards: dict) -> tuple:
    me = load_me(logs)
    runs = bot_runs(logs)
    starts = day_starts(events)
    cases, excluded = [], []
    for r in negos:
        if r["team"] != TEAM:
            continue
        tid = r["thread"]
        why = None
        if r["kind"] == "pack":
            why = "pack: no per-card private value, and neither bot trades packs"
        elif r["side"] not in ("buy", "sell") or not r["rarity"]:
            why = "item or side not reconstructable"
        elif not r["D"] or r["D"][0][1] is None:
            why = "the dealer never named a price"
        if why:
            excluded.append({"thread": tid, "dealer": r["dealer"], "why": why})
            continue
        run = runs.get(tid)
        private, psrc = private_value(r, me, cards, run)
        if private is None:
            excluded.append({"thread": tid, "dealer": r["dealer"], "why": "no private value"})
            continue
        key = class_key(r["dealer"], r["side"], r["rarity"], r["set"])
        ref_open, ref_best = model.refs(key, r["side"])
        welcome = tid in model.welcome
        day = day_of(r["open_tick"], starts)
        D = [d[1] for d in r["D"]]
        U = [u[1] for u in r["U"]]
        dpath = " ".join("-" if p is None else f"{p}{'F' if d[2] else ''}" for p, d in zip(D, r["D"]))
        upath = " ".join("-" if p is None else str(p) for p in U) or "none"
        outcome_s = (f"deal {r['deal_price']} ({r['deal_by']})" if r["deal_price"] is not None else r["outcome"])
        prompt = (f"dealer={r['dealer']} {r['side']} {r['item']} ({r['rarity']}, {r['set']}) private={private:g} "
                  f"open={D[0]} ref_open={ref_open} ref_best={ref_best} | real dealer: {dpath} | real ours: {upath} | "
                  f"{outcome_s}")
        cases.append({
            "id": f"{r['dealer']}-{tid}", "tags": [r["dealer"], r["side"], r["outcome"], day] + (["welcome"] if welcome else []),
            "source": r["source"], "thread": tid, "dealer": r["dealer"], "side": r["side"], "item": r["item"],
            "asset_id": r["asset_id"], "rarity": r["rarity"], "set": r["set"], "book": r["book"],
            "class": key, "open_tick": r["open_tick"], "day": day, "opening": D[0], "private": private,
            "private_source": psrc, "ref_open": ref_open, "ref_best": ref_best, "welcome": welcome,
            "bot_run": run, "prompt": prompt,
            "real": {k: r[k] for k in ("D", "U", "resp", "final", "outcome", "deal_price", "deal_by")},
            "real_path": f"{dpath} / {upath}", "real_outcome": outcome_s,
        })
    return cases, excluded


# ================================================================ one case

def config_from_argv(case: dict) -> dict:
    """The flags a real conversation ran with (from its bot log), as a config section."""
    run = case.get("bot_run") or {}
    argv = list(run.get("argv") or [])

    def flag(name, cast=int):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return cast(argv[i + 1])
        return None

    if case["dealer"] == "abuela":
        cfg = {"cap": flag("--cap", float), "step": 1, "anchor_frac": 0.40, "max_rounds": 40}
    elif case["side"] == "buy":
        cfg = {"anchor": flag("--anchor"), "step": flag("--step") or 1, "cap": flag("--cap", float),
               "max_bid": flag("--max-bid"), "max_rounds": flag("--max-rounds")}
    else:
        cfg = {"sell_anchor": flag("--sell-anchor"), "sell_step": flag("--sell-step"),
               "max_rounds": flag("--max-rounds"), "floor": flag("--floor"), "floor_margin": 2}
    if cfg.get("max_rounds") is None:
        cfg["max_rounds"] = 40 if case["dealer"] == "abuela" else (40 if case["dealer"] == "pilar" else 12)
    if run.get("limit") is not None:  # exactly the limit the bot logged (its value or floor)
        if case["side"] == "buy":
            cfg["limit_override"] = float(run["limit"])
        else:
            cfg["floor"] = run["limit"]
    return cfg


def simulate(case: dict, model: DealerModel, policy: str, cfg: dict, rep: int, seed: int,
             deterministic: bool = False, prefix: bool = True, model_on: bool = True, affinity: dict = None) -> tuple:
    rng = random.Random(f"{seed}:{case['id']}:{rep}:params")
    params = conversation_params(case, model, rng, deterministic)
    sim = SimDealer(case, model, params, f"{seed}:{case['id']}:{rep}", deterministic, prefix=prefix, model_on=model_on,
                    affinity=affinity)
    out = POLICIES[policy](case, cfg, sim)
    price = sim.deal[0] if sim.deal else None
    return sim, params, out, price


def trace_of(case: dict, policy_label: str, cfg: dict, params: dict, sim: SimDealer, out: dict) -> list:
    turns = [{"role": "system", "content": (
        f"policy {policy_label}; config {json.dumps(cfg, sort_keys=True)}; case {case['id']} {case['side']} "
        f"{case['item']} private={case['private']:g} ({case['private_source']}); dealer: real answers while our "
        f"offers equal the real ones, then the model (L={params['L']} from {params['L_from']}, patience P={params['P']} "
        f"from {params['P_from']}, tol={params['tol']}). Numbers only: no game text.")}]
    for tick, who, what, price, source in sim.events:
        t = tick - (sim.start or tick)
        if who == "dealer":
            turns.append({"role": "user", "content": f"round {t}: dealer {what}" + (f" {price}" if price is not None else "")
                          + f" [{source}]"})
        else:
            turns.append({"role": "assistant", "content": f"round {t}: {what}" + (f" {price}" if price is not None else "")})
    end = (f"deal at {sim.deal[0]} ({sim.deal[1]})" if sim.deal else f"no deal ({sim.closed_reason or sim.status})")
    turns.append({"role": "tool_result", "content": f"outcome: {end}; bot result {out.get('result')}; "
                                                    f"bot limit {out.get('limit')}; real: {case['real_outcome']}"})
    return turns


def case_fn(case: dict, model: DealerModel, policy: str, cfg: dict, rep: int, seed: int, label: str,
            affinity: dict = None):
    def fn():
        sim, params, out, price = simulate(case, model, policy, cfg, rep, seed, affinity=affinity)
        value = book_value(case, affinity)
        g = grade(case, price, sim.offers_seen, L=params["L"], value=value)
        g.update(real_grade(case, value))
        ours = [e for e in sim.events if e[1] == "us" and e[2] == "offer"]
        real_answers = sum(1 for e in sim.events if e[1] == "dealer" and e[4] == "real") - 1
        perf = {"rounds": len(ours), "ticks": sim.tick - (sim.start or sim.tick), "real_prefix": max(0, real_answers)}
        meta = {"policy": policy, "config": cfg, "deal_price": price, "deal_by": sim.deal[1] if sim.deal else None,
                "end": sim.closed_reason or sim.status, "diverged_at": sim.diverged_at, "params": params,
                "offers_seen": sim.offers_seen, "bot_result": out.get("result"), "bot_limit": out.get("limit"),
                "private": case["private"], "real_deal_price": case["real"]["deal_price"]}
        return g, perf, trace_of(case, label, cfg, params, sim, out), meta
    return fn


# ================================================================ validation

def validate(negos: list, cases: list, model: DealerModel) -> None:
    """Prints (1) one-step accuracy of the model on every conversation's next dealer answer, held-out (ours) vs
    in-sample (other teams), against a 'he holds his price' baseline; (2) harness fidelity: the bot with the flags
    it really ran, against the real dealer path, must send the real offers; (3) closed-loop model fidelity: the same
    bot against the model alone (the conversation's revealed limit and patience, medians elsewhere)."""
    print("== 1. one-step accuracy of the dealer's next counter (median drop), by class")
    print(f"{'class':28} {'set':6} {'n':>5} {'MAE model':>9} {'MAE hold':>9} {'exact':>6}")
    rows = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for r in negos:
        if r["side"] not in ("buy", "sell") or r["kind"] != "card" or not r["rarity"] or not r["D"]:
            continue
        if r["D"][0][1] is None or r["thread"] in model.welcome:
            continue
        key = class_key(r["dealer"], r["side"], r["rarity"], r["set"])
        if not model.has(key):
            continue
        sign = 1 if r["side"] == "buy" else -1
        a, prev_b = r["D"][0][1], None
        tag = "ours" if r["team"] == TEAM else "field"
        for i, (u, resp) in enumerate(zip(r["U"], r["resp"])):
            if resp is None or resp[0] is None or resp[1]:
                break
            b = u[1]
            step = None if prev_b is None else (0 if b is None else sign * (b - prev_b))
            s = step_bucket(step)
            pred = a if s == 0 else a - sign * med(model.cell(key, i, s))
            row = rows[(key, tag)]
            row[0] += 1
            row[1] += abs(pred - resp[0])
            row[2] += abs(a - resp[0])
            row[3] += int(pred == resp[0])
            a = resp[0]
            if b is not None:
                prev_b = b
    tot = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for (key, tag), (n, em, eh, ex) in sorted(rows.items()):
        print(f"{key:28} {tag:6} {n:5d} {em / n:9.2f} {eh / n:9.2f} {ex / n:6.0%}")
        for t in (tag, "all"):
            tt = tot[t]
            tt[0] += n
            tt[1] += em
            tt[2] += eh
            tt[3] += ex
    for t, (n, em, eh, ex) in sorted(tot.items()):
        print(f"{'TOTAL':28} {t:6} {n:5d} {em / n:9.2f} {eh / n:9.2f} {ex / n:6.0%}")
    print("\n== 1b. priors per class (other teams): secret limit L = final offers, patience P = our offers by the final")
    print(f"{'class':28} {'convs':>5} {'finals':>6} {'L p10/med/p90':>16} {'P p10/med/p90':>14} {'tol med':>7} "
          f"{'ref open':>8} {'ref best':>8}")

    def q(xs, f):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))] if xs else None

    for key in sorted(model.t):
        c = model.t[key]
        if not c["n"]:
            continue
        side = key.split(".")[1]
        ro, rb = model.refs(key, side)
        print(f"{key:28} {c['n']:5d} {len(c['L']):6d} {str((q(c['L'], .1), med(c['L']), q(c['L'], .9))):>16} "
              f"{str((q(c['P'], .1), med(c['P']), q(c['P'], .9))):>14} {str(med(c['tol'])):>7} {str(ro):>8} {str(rb):>8}")
    print("\n== 2. harness fidelity: real flags, real dealer path only (no model)")
    print("== 3. closed-loop model fidelity: real flags, model only (revealed L/P, medians)")
    print(f"{'case':14} {'real offers':34} {'2: replayed':34} {'2 end':>8} {'3 end':>8} {'real end':>8}")
    h_ok = m_err = m_n = m_same = 0
    n_bot = 0
    for c in cases:
        if not c.get("bot_run"):
            continue
        n_bot += 1
        cfg = config_from_argv(c)
        sim2, _, _, p2 = simulate(c, model, "bot", cfg, 0, 0, deterministic=True, prefix=True, model_on=False)
        sim3, _, _, p3 = simulate(c, model, "bot", cfg, 0, 0, deterministic=True, prefix=False, model_on=True)
        real_u = [u[1] for u in c["real"]["U"] if u[1] is not None]
        got_u = [e[3] for e in sim2.events if e[1] == "us" and e[2] == "offer"]
        same = got_u[:len(real_u)] == real_u and p2 == c["real"]["deal_price"]
        h_ok += int(same)
        rp = c["real"]["deal_price"]
        if rp is not None and p3 is not None:
            m_err += abs(p3 - rp)
            m_n += 1
        m_same += int((rp is None) == (p3 is None))
        print(f"{c['id']:14} {' '.join(map(str, real_u))[:34]:34} {' '.join(map(str, got_u))[:34]:34} "
              f"{str(p2):>8} {str(p3):>8} {str(rp):>8}")
    print(f"harness: {h_ok}/{n_bot} conversations replayed exactly (same offers, same deal)")
    print(f"model closed loop: deal/no-deal agrees on {m_same}/{n_bot}; end-price MAE {m_err / max(1, m_n):.2f} P "
          f"over {m_n} deals")


# ================================================================ main

def parse_set(items: list, base: dict) -> dict:
    cfg = copy.deepcopy(base)
    for it in items or []:
        if "=" not in it or "." not in it.split("=", 1)[0]:
            raise SystemExit(f"--set wants <section>.<knob>=<value>, got {it!r}")
        k, v = it.split("=", 1)
        sec, knob = k.rsplit(".", 1)
        if sec not in cfg:
            raise SystemExit(f"--set: unknown section {sec!r} (have {', '.join(cfg)})")
        if knob not in cfg[sec]:
            raise SystemExit(f"--set: unknown knob {knob!r} in {sec} (have {', '.join(cfg[sec])})")
        if v.lower() in ("none", "null", ""):
            cfg[sec][knob] = None
        else:
            try:
                cfg[sec][knob] = int(v)
            except ValueError:
                cfg[sec][knob] = float(v)
    return cfg


def policy_label(policy: str) -> str:
    """One label per run (the report shows a single model per variant): both bot files with their content hashes."""
    if policy != "bot":
        return f"{policy}@eval_dealers.py"
    return "+".join(f"{f}@{file_sha(ROOT / 'agent' / f)}" for f in ("abuela.py", "chato.py"))


def case_level(rows: list, metrics: tuple) -> str:
    """Mean of per-case means (the report's way) with a CI over cases: reps of one case are not independent cases,
    so this interval, not summary_line's per-row one, is the one to quote."""
    parts = []
    for m in metrics:
        by = collections.defaultdict(list)
        for r in rows:
            if r.get("status") == "ok" and m in r["grade"]:
                by[r["prompt_id"]].append(r["grade"][m])
        mu, half, n = mean_ci([sum(v) / len(v) for v in by.values()])
        parts.append(f"{m} {mu:.3f} +- {half:.3f}")
    return f"case-level (n={len(set(r['prompt_id'] for r in rows))} cases): " + "; ".join(parts)


def noise_floor(rows: list, metric: str) -> str:
    """A/A check: per case, mean over even reps minus mean over odd reps; the CI of that paired delta is about the
    smallest paired difference two configs can show at this rep count."""
    by = collections.defaultdict(lambda: ([], []))
    for r in rows:
        if r.get("status") == "ok" and metric in r["grade"]:
            by[r["prompt_id"]][r["rep"] % 2].append(r["grade"][metric])
    deltas = [sum(a) / len(a) - sum(b) / len(b) for a, b in by.values() if a and b]
    if len(deltas) < 2:
        return f"{metric}: A/A needs >= 2 reps"
    m, half, n = mean_ci(deltas)
    return f"{metric}: A/A paired delta (even vs odd reps) {m:+.3f} +- {half:.3f} over {n} cases"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--variant", default="baseline", help="baseline or v<N>")
    ap.add_argument("--reps", type=int, default=5, help="replays per case (the model's draws differ per rep)")
    ap.add_argument("--logs", default=str(ROOT / "logs"), help="logs directory to read (read-only)")
    ap.add_argument("--timeout-s", type=float, default=60.0, help="wall-clock ceiling per (case, rep)")
    ap.add_argument("--policy", choices=sorted(POLICIES), default="bot",
                    help="bot = the real decision code; oracle/null/reckless are harness checks (need --out-root)")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KNOB=VALUE",
                    help="override a BASELINE knob, e.g. abuela.step=2, chato.rare.anchor=56, pilar.sell.sell_step=2")
    ap.add_argument("--change", default=None, help="one line for change.md (non-baseline variants)")
    ap.add_argument("--seed", type=int, default=0, help="seed of the model's draws (common across variants)")
    ap.add_argument("--out-root", default=None, help="write <out-root>/dealers/ instead of evals/dealers/")
    ap.add_argument("--only", default="", help="comma list of case ids")
    ap.add_argument("--validate", action="store_true", help="print the model and harness checks; write nothing")
    args = ap.parse_args(argv)

    logs = Path(args.logs)
    negos, events, cards = all_negotiations(logs)
    model = DealerModel(negos)
    cases, excluded = build_cases(logs, model, negos, events, cards)
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in keep]
    if args.validate:
        validate(negos, cases, model)
        return 0
    if args.policy != "bot" and not args.out_root:
        raise SystemExit("--policy oracle/null/reckless are harness checks: pass --out-root (never evals/)")
    if args.variant == "baseline" and args.set and not args.out_root:
        raise SystemExit("baseline is the Sunday config: put --set overrides in a v<N> variant")
    if args.out_root:
        eval_common.EVALS = Path(args.out_root)
    cfg = parse_set(args.set, BASELINE)
    print(f"{len(cases)} cases, {len(excluded)} excluded; model fitted on "
          f"{sum(c['n'] for c in model.t.values())} other-team conversations", flush=True)
    for e in excluded:
        print(f"  excluded thread {e['thread']} ({e['dealer']}): {e['why']}")

    write_state(FLOW, METRICS, PERF, extra={
        "headline": "deal_in_limit", "baseline_config": BASELINE,
        "note": "real_* = audit of the real conversation (same in every variant); the rest = counterfactual "
                "replay against the dealer model (modelled numbers)"})
    write_cases(FLOW, cases,
                "Dealer negotiation cases (our real conversations with Abuela, El Chato and Pilar)",
                ["class", "private", "private_source", "ref_open", "ref_best", "real_path", "real_outcome"])

    change = None
    if args.variant != "baseline":
        change = args.change or ("config: " + ", ".join(args.set) if args.set else "no change")
        if args.set and args.change:
            change = f"{args.change}\n\nOverrides: {', '.join(args.set)}"
    label = policy_label(args.policy)
    affinity = load_me(logs).get("affinity") or {}
    run = Run(FLOW, args.variant, label, change=change)
    for c in cases:
        sec = cfg[section_of(c)]
        for rep in range(args.reps):
            run.case(c["id"], rep, c["prompt"], c["tags"], case_fn(c, model, args.policy, sec, rep, args.seed, label, affinity),
                     timeout_s=args.timeout_s)
    rows = run.all_rows()
    print(summary_line(FLOW, args.variant, rows, METRICS))
    for d in DEALERS:
        sub = [r for r in rows if r["tags"] and r["tags"][0] == d]
        if sub:
            print("  " + summary_line(FLOW, f"{args.variant}:{d}", sub, METRICS[:6]))
    print("  " + case_level(rows, ("deal_in_limit", "over_value", "range_share", "limit_share", "limit_breach",
                                   "real_deal_in_limit", "real_over_value", "real_range_share")))
    if args.reps >= 2:
        print("  noise floor " + noise_floor(rows, "deal_in_limit"))
        print("  noise floor " + noise_floor(rows, "range_share"))
    errs = run.errors.read_text().count("\n") if run.errors.exists() else 0
    if errs:
        print(f"  {errs} attempts in errors.jsonl (not scored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
