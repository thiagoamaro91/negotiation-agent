"""Offline eval of our venue broker on the Market Test (flow `broker`, results under evals/broker/).

What it measures. The Market Test hands every venue the same synthetic book of bench buyers and sellers; the score is
the share of the possible gains between the traders' TRUE limits that the venue realises (kit/RULES.md, "Your own
market"). This eval replays agent/broker.py's planning code (plan_book: the policy, the guard and the safety net,
exactly what `broker.py run` sends) on two groups of cases, tags[0] = real | synthetic:

  real       one case per Market Test session in a day's broker log (logs/broker/<date>.jsonl). The bench offers
             are rebuilt book state by book state as they arrived; the policy plans on each state and an offline
             engine applies the server's rules. True limits are hidden, so gains are measured on REVEALED limits
             (a buyer's highest bid seen, a seller's lowest ask seen: true value >= bid, true cost <= ask). Graded
             also against what really happened: the pairs the live broker matched (from its `matched` events).
             Assumption: offers do not react to our matches except by leaving the book. Its cost: an offer the
             live broker matched vanishes from the recording, so a replay that does NOT match it sees it leave
             early (censored path); a replay can never see the counterfactual quotes it would have shown.
  synthetic  tools/bench_sim.py sessions (its engine, simulate(), is reused as is) after refitting the scenario
             knobs on the same log (bench_sim fit/read_runs), plus the lab's hard scenarios. Paired seeds: a case
             is (scenario, seed), so every policy sees the same sessions. As in bench_sim, a seed is a day of DAY
             sessions met by one policy object; the first DAY-1 warm the policy, the last one is graded.

Grades (headline first; see evals/broker/metrics.md): bench_score, surplus_captured, dropped, bad_match, and on real
cases live_agree and vs_live. Game text is never read: only offer ids, prices, ticks and expiries.

Usage (from the repo root; offline, keyless, read-only on --logs):
    python3 tools/eval_broker.py --variant baseline --policy stall --logs /Volumes/bazaar/logs
    python3 tools/eval_broker.py --variant v1 --policy ours --logs /Volumes/bazaar/logs      # our bench policy
    python3 tools/eval_broker.py --compare v1                                                # paired delta vs baseline
    python3 tools/eval_broker.py --policy oracle --out-root /tmp/x    # harness checks: oracle | null | reckless
    node <claude-api skill>/shared/evals/report/build-report-lite.mjs evals/broker/

Harness policies (oracle, null, reckless) never write under evals/: they need --out-root elsewhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))
import bench_sim as bs  # noqa: E402
import broker as brk  # noqa: E402
import eval_common as ec  # noqa: E402

FLOW = "broker"
LIVE_POLICIES = ("stall", "ours")            # what agent/broker.py can run live (`run --policy ...`)
HARNESS_POLICIES = ("oracle", "null", "reckless")
SCENARIOS = "fitted,fitted_expiry_exact,standard,hard,hard_expiry_exact,adversarial"
SEEDS = 6

METRICS = [
    {"id": "bench_score", "label": "bench_score", "kind": "float", "scale": 1, "better": "higher"},
    {"id": "surplus_captured", "label": "surplus_capt", "kind": "float", "scale": 1, "better": "higher"},
    {"id": "dropped", "label": "dropped", "kind": "float", "scale": 10, "better": "lower"},
    # 0/1 per case; declared float so the lite report keeps bench_score as its headline (it picks the first binary)
    {"id": "bad_match", "label": "bad_match", "kind": "float", "scale": 1, "better": "lower"},
    {"id": "live_agree", "label": "live_agree", "kind": "float", "scale": 1, "better": "higher"},  # real only
    {"id": "vs_live", "label": "vs_live", "kind": "float", "scale": 1, "better": "higher"},        # real only
]
PERF = [{"id": "latency_s", "unit": "s"}, {"id": "matches"}, {"id": "ticks"}, {"id": "guard_dropped"}]


# ---------------------------------------------------------------- shared helpers

def side_quote(o: dict):
    """(side, quote) of a bench offer as the broker reads it: a seller asks want.cash, a buyer bids give.cash."""
    ask = (o.get("want") or {}).get("cash")
    return ("sell", ask) if ask else ("buy", (o.get("give") or {}).get("cash"))


def engine_check(book: dict, m, used: set) -> str | None:
    """None if the server would settle match m on this book, else why not. The rules of bench_sim.simulate (A6)."""
    try:
        sell, buy, price = m
    except (TypeError, ValueError):
        return "malformed"
    live = {o["id"]: o for o in book.get("bench_offers") or []}
    if sell not in live or buy not in live:
        return "unknown_offer"
    if sell in used or buy in used or sell == buy:
        return "offer_reused"
    if brk.run_of(sell) != brk.run_of(buy):
        return "different_runs"
    (ss, ask), (sb, bid) = side_quote(live[sell]), side_quote(live[buy])
    if ss != "sell" or sb != "buy":
        return "not_a_seller_and_a_buyer"
    if isinstance(price, bool) or not isinstance(price, int):
        return "price_not_whole"
    if price < ask or price + brk.fee_of(book, price) > bid:
        return "does_not_cross" if bid < ask else "price_outside_quotes"
    return None


def crossing_edges(book: dict) -> set:
    """(sell id, buy id) pairs a broker could match on this book state (bid covers ask + fee at some whole price)."""
    offers = [(o["id"],) + side_quote(o) for o in book.get("bench_offers") or []]
    sells = [(i, q) for i, s, q in offers if s == "sell"]
    buys = [(i, q) for i, s, q in offers if s == "buy"]
    return {(s, b) for s, qs in sells for b, qb in buys
            if brk.run_of(s) == brk.run_of(b) and qb >= qs and brk.price_for(book, qs, qb) is not None}


def max_matching(edges: dict) -> tuple:
    """(total weight, pairs) of the max-weight matching over edges {(sell, buy): weight} (bench_sim's DP)."""
    sells = sorted({s for s, _ in edges})
    buys = sorted({b for _, b in edges})
    if not edges:
        return 0.0, []
    left, right, swap = (buys, sells, False) if len(buys) >= len(sells) else (sells, buys, True)
    if len(right) > 16:
        raise ValueError("matching too large for the exact DP")

    def w(i, j):
        s, b = (right[j], left[i]) if not swap else (left[i], right[j])
        return edges.get((s, b))
    pairs = brk.best_matching(len(left), len(right), w)
    out = [((right[j], left[i]) if not swap else (left[i], right[j])) for i, j in pairs]
    return sum(edges[p] for p in out), out


def dropped_count(edges_seen: set, matched_ids: set) -> int:
    """Crossable pairs left at the end: the largest set of disjoint pairs that crossed on a book the policy saw,
    with neither offer ever matched by it."""
    left = {e: 1.0 for e in edges_seen if e[0] not in matched_ids and e[1] not in matched_ids}
    return int(round(max_matching(left)[0]))


def fmt_book(book: dict) -> str:
    rows = sorted(((o["id"],) + side_quote(o) for o in book.get("bench_offers") or []),
                  key=lambda r: (r[1], -r[2] if r[1] == "buy" else r[2]))
    return "; ".join(f"{s[0].upper()} {i}@{q}" for i, s, q in rows) or "(empty)"


# ---------------------------------------------------------------- policies

class Policy:
    """One policy object per case (per day for synthetic cases). plan(book, tick) -> (matches, guard_dropped)."""

    def __init__(self, name: str, oracle_plan: dict | None = None):
        self.name = name
        self.bench = brk.BenchPolicy() if name == "ours" else None
        self.oracle = oracle_plan or {}  # (sell, buy) -> True for the oracle's chosen pairs

    def params(self) -> str:
        if self.name == "stall":
            return "agent/broker.py plan_book(policy=None): the free stall's rule + guard + safety net (what Sunday runs)"
        if self.name == "ours":
            return "agent/broker.py plan_book(BenchPolicy): " + json.dumps(self.bench.p, sort_keys=True)
        return {"oracle": "harness: knows every trader's limit and schedule; matches the max-weight set of pairs that "
                          "ever cross, each at its first crossing",
                "null": "harness: never matches", "reckless": "harness: pairs the worst bids with the dearest asks "
                                                              "at the ask, crossing or not"}[self.name]

    def plan(self, book: dict, tick: int) -> tuple:
        if self.name in LIVE_POLICIES:
            ok, bad, _notes = brk.plan_book(book, tick, self.bench)
            if self.bench is not None:
                for sell, buy, _p in ok:
                    self.bench.sent(sell, buy, tick)
            return ok, len(bad)
        if self.name == "null":
            return [], 0
        offers = [(o["id"],) + side_quote(o) for o in book.get("bench_offers") or []]
        if self.name == "oracle":
            out, used = [], set()
            q = {i: qq for i, _s, qq in offers}
            for (s, b) in self.oracle:
                if s in q and b in q and s not in used and b not in used and q[b] >= q[s]:
                    p = brk.price_for(book, q[s], q[b])
                    if p is not None:
                        out.append((s, b, p))
                        used.update((s, b))
            return out, 0
        # reckless: lowest bids against highest asks, at the ask
        sells = sorted([(q, i) for i, s, q in offers if s == "sell"], reverse=True)
        buys = sorted([(q, i) for i, s, q in offers if s == "buy"])
        return [(si, bi, int(math.ceil(sq))) for (sq, si), (bq, bi) in zip(sells, buys)], 0


# ---------------------------------------------------------------- real cases (a day's broker log)

def read_log(path: Path) -> tuple:
    """(book states [(tick, book)], live matches [(tick, sell, buy, price)], run ends {run}). Numbers and ids only:
    of each bench offer we keep id, give.cash, want.cash and the expiry; offer notes and public offers are dropped."""
    states, live, ended = [], [], set()
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ev = row.get("event")
        if ev == "matched" and isinstance(row.get("sell"), str) and isinstance(row.get("buy"), str):
            live.append((row.get("tick"), row["sell"], row["buy"], row.get("price")))
        elif ev == "bench_run_end" and isinstance(row.get("bench_run"), str):
            ended.add(row["bench_run"])
        elif ev == "book" and isinstance(row.get("book"), dict) and brk._num(row.get("tick")):
            b = row["book"]
            bench = []
            for o in b.get("bench_offers") or []:
                try:
                    oid, gc, wc = str(o["id"]), o["give"]["cash"], o["want"]["cash"]
                except (KeyError, TypeError):
                    continue
                q = wc if wc else gc
                if not brk._num(q):
                    continue
                exp = next((o[k] for k in brk.EXPIRY_FIELDS if brk._num(o.get(k))), None)
                clean = {"id": oid, "maker": "bench", "give": {"cash": gc or 0, "assets": [], "types": []},
                         "want": {"cash": wc or 0, "assets": [], "types": []}}
                if exp is not None:
                    clean["expires_tick"] = exp
                bench.append(clean)
            states.append((int(row["tick"]), {"fee_bps": b.get("fee_bps") or 0, "fee_per_card": b.get("fee_per_card") or 0,
                                              "offers": [], "bench_offers": bench}))
    return states, live, ended


def real_sessions(states: list, live: list, ended: set) -> tuple:
    """({run: session}, {run: why excluded}). A session: its book states (only its own offers), every offer's
    revealed limit and side, its live matches. A run still on the book near the log's end, with no bench_run_end,
    is in progress: excluded."""
    runs: dict = {}
    for tick, book in states:
        by_run: dict = {}
        for o in book["bench_offers"]:
            by_run.setdefault(brk.run_of(o["id"]), []).append(o)
        for run, offers in by_run.items():
            runs.setdefault(run, []).append((tick, dict(book, bench_offers=offers)))
    last_tick = max((t for t, _ in states), default=0)
    out, excluded = {}, {}
    for run, sts in runs.items():
        if run not in ended and last_tick - sts[-1][0] < brk.RUN_QUIET:
            excluded[run] = "in progress (still on the book at the log's end)"
            continue
        traders: dict = {}
        for tick, book in sts:
            for o in book["bench_offers"]:
                side, q = side_quote(o)
                t = traders.setdefault(o["id"], {"id": o["id"], "side": side, "limit": q, "first": tick, "n": 0,
                                                 "expires": o.get("expires_tick")})
                t["limit"] = max(t["limit"], q) if side == "buy" else min(t["limit"], q)
                t["n"] += 1
        if not any(t["side"] == "buy" for t in traders.values()) or not any(t["side"] == "sell" for t in traders.values()):
            excluded[run] = "one side only"
            continue
        out[run] = {"run": run, "states": sts, "traders": traders,
                    "live": [m for m in live if brk.run_of(m[1]) == run]}
    return out, excluded


def real_denominators(sess: dict) -> tuple:
    """(best, ceiling, ceiling pairs) on revealed limits: best ignores time (bench_sim.best_gain); the ceiling is the
    max-weight matching over pairs that crossed on a recorded book state."""
    tr = sess["traders"]
    best = bs.best_gain(list(tr.values()))
    seen = set()
    for _t, book in sess["states"]:
        seen |= crossing_edges(book)
    ceil, pairs = max_matching({e: tr[e[1]]["limit"] - tr[e[0]]["limit"] for e in seen})
    return best, ceil, pairs


def run_real(sess: dict, policy: Policy) -> tuple:
    """Replays one recorded session through `policy`. Returns (grade, perf, trace)."""
    tr = sess["traders"]
    best, ceil, _ = real_denominators(sess)
    matched, used_ids, edges_seen = [], set(), set()
    bad = guard_dropped = 0
    trace = [{"role": "system", "content": f"policy {policy.name}: {policy.params()}\nreal session {sess['run']}; "
                                           "revealed limits; offers leave the book only as recorded or when matched"}]
    t0 = sess["states"][0][0]
    for tick, rec in sess["states"]:
        book = dict(rec, bench_offers=[o for o in rec["bench_offers"] if o["id"] not in used_ids])
        if not book["bench_offers"]:
            continue
        edges_seen |= crossing_edges(book)
        plan, gd = policy.plan(book, tick)
        guard_dropped += gd
        done, refused, used = [], [], set()
        for m in plan:
            why = engine_check(book, m, used)
            if why:
                bad += 1
                refused.append(f"REFUSED {m} ({why})")
                continue
            sell, buy, price = m
            used.update((sell, buy))
            gain = tr[buy]["limit"] - tr[sell]["limit"]
            if gain < 0:
                bad += 1
            matched.append((tick, sell, buy, price, gain))
            done.append(f"{sell} x {buy} @ {price} (revealed gain {gain:.0f})")
        used_ids |= used
        trace.append({"role": "user", "content": f"tick {tick} (+{tick - t0}) book: {fmt_book(book)}"})
        trace.append({"role": "assistant", "content": "; ".join(done + refused) or "no match"})
    gain = sum(m[4] for m in matched)
    live_pairs = {(s, b) for _t, s, b, _p in sess["live"]}
    ours = {(m[1], m[2]) for m in matched}
    live_gain = sum(tr[b]["limit"] - tr[s]["limit"] for s, b in live_pairs if s in tr and b in tr)
    union = live_pairs | ours
    grade = {"bench_score": gain / best if best > 1e-9 else 0.0,
             "surplus_captured": gain / ceil if ceil > 1e-9 else 0.0,
             "dropped": dropped_count(edges_seen, used_ids),
             "bad_match": int(bad > 0),
             "live_agree": len(live_pairs & ours) / len(union) if union else 1.0,
             "vs_live": (gain - live_gain) / best if best > 1e-9 else 0.0}
    perf = {"matches": len(matched), "ticks": len({t for t, _ in sess["states"]}), "guard_dropped": guard_dropped}
    trace.append({"role": "assistant", "content": f"session end: {len(matched)} matches, revealed gain {gain:.0f} of "
                                                  f"best {best:.0f} (ceiling {ceil:.0f}); live broker matched "
                                                  f"{len(live_pairs)} pairs, revealed gain {live_gain:.0f}"})
    return grade, perf, trace


def real_prompt(sess: dict, date: str) -> str:
    tr = list(sess["traders"].values())
    bids = [t["limit"] for t in tr if t["side"] == "buy"]
    asks = [t["limit"] for t in tr if t["side"] == "sell"]
    exps = {t["expires"] for t in tr}
    exp = ("none shown" if exps == {None} else "all equal (session end)" if len(exps) == 1
           else f"{len(exps)} distinct")
    best, ceil, _ = real_denominators(sess)
    book = sess["states"][0][1]
    return (f"real Market Test session {sess['run']} ({date}); {len({t for t, _ in sess['states']})} ticks recorded "
            f"({len(sess['states'])} book states); {len(tr)} bench offers: {len(bids)} buyers (highest bid seen "
            f"{min(bids):.0f}-{max(bids):.0f} P), {len(asks)} sellers (lowest ask seen {min(asks):.0f}-{max(asks):.0f} "
            f"P); expiries: {exp}; fee {book['fee_bps']} bps + {book['fee_per_card']} P/card; revealed best gains "
            f"{best:.0f} P, quote-respecting ceiling {ceil:.0f} P; live broker matched {len(sess['live'])} pairs")


def score_around(score_path: Path, sess: dict) -> dict:
    """bench_points in logs/score.jsonl just before and just after the session (None when not recorded)."""
    rows = []
    try:
        for line in score_path.read_text().splitlines():
            r = json.loads(line)
            bp = (r.get("score") or {}).get("bench_points")
            if brk._num(r.get("tick")):
                rows.append((r["tick"], bp))
    except (OSError, ValueError):
        return {}
    first, last = sess["states"][0][0], sess["states"][-1][0]
    before = [r for r in rows if r[0] < first]
    after = [r for r in rows if r[0] > last]
    return {"bench_points_before": before[-1] if before else None, "bench_points_after": after[0] if after else None}


# ---------------------------------------------------------------- synthetic cases (bench_sim after refit)

def fitted_scenarios(log: Path) -> tuple:
    """({name: scenario overrides}, note). The refit of bench_sim on the log; expiries corrected when every run shows
    one expiry for all its offers (bench_sim's fit counts distinct expiries across runs and reads 'early')."""
    runs = bs.read_runs(log)
    shows, sc = bs.fit(runs)
    note = ""
    per_run = [{r["expires"] for r in rs.values()} for rs in runs.values()]
    if all(len(e) == 1 and None not in e for e in per_run) and sc.get("expiry") != "end":
        note = f"refit said expiry={sc.get('expiry')!r}; every run shows one expiry for all offers: using 'end'"
        sc = {k: v for k, v in sc.items() if k != "early_max"}
        sc["expiry"] = "end"
    sc = {k: tuple(v) if isinstance(v, list) else v for k, v in sc.items()}
    return {"fitted": sc, "fitted_expiry_exact": {**sc, "expiry": "exact"}}, note


def sc_hash(sc: dict) -> str:
    return hashlib.sha256(json.dumps(sc, sort_keys=True).encode()).hexdigest()[:6]


def oracle_pairs_synth(traders: list, sc: dict) -> dict:
    """The ceiling's pairs (bench_sim.ceiling_gain), as {(sell id, buy id): True}."""
    buyers = [t for t in traders if t["side"] == "buy"]
    sellers = [t for t in traders if t["side"] == "sell"]
    ok = {}
    for i, b in enumerate(buyers):
        for j, s in enumerate(sellers):
            for t in range(bs.TICKS):
                if bs.present(b, t) and bs.present(s, t) and bs.quote(b, t, sc) >= bs.quote(s, t, sc):
                    ok[(i, j)] = b["limit"] - s["limit"]
                    break
    return {(sellers[j]["id"], buyers[i]["id"]): True for i, j in brk.best_matching(len(buyers), len(sellers),
                                                                                       lambda i, j: ok.get((i, j)))}


def synth_day(name: str, sc: dict, seed: int) -> list:
    """The DAY sessions of one seed, drawn exactly as bench_sim.run_scenario draws them (paired across policies)."""
    rng = random.Random(f"{name}:{seed}")
    return [bs.make_session(rng, sc, run=f"b{k + 1}") for k in range(bs.DAY)]


def run_synth(name: str, sc: dict, seed: int, policy_name: str) -> tuple:
    day = synth_day(name, sc, seed)
    traders, k_last = day[-1], len(day) - 1
    policy = Policy(policy_name, oracle_pairs_synth(traders, sc) if policy_name == "oracle" else None)
    for k, warm in enumerate(day[:-1]):  # the policy object meets the earlier sessions first, as live
        if policy_name != "oracle":
            bs.simulate(warm, sc, lambda b, t: policy.plan(b, t)[0], t0=100 * k)
    seen, edges_seen = [], set()
    gd = [0]

    def fn(book, t):
        edges_seen.update(crossing_edges(book))
        plan, g = policy.plan(book, t)
        gd[0] += g
        seen.append((t, book, list(plan)))
        return plan
    sim_trace = []
    r = bs.simulate(traders, sc, fn, sim_trace, t0=100 * k_last)
    limit = {t["id"]: t["limit"] for t in traders}
    acc = [x for x in sim_trace if x[1] != "book"]
    matched_ids = {x[1] for x in acc} | {x[2] for x in acc}
    neg = sum(1 for x in acc if limit[x[2]] - limit[x[1]] < 0)
    best, ceil = bs.best_gain(traders), bs.ceiling_gain(traders, sc)
    grade = {"bench_score": r["gain"] / best if best > 1e-9 else 0.0,
             "surplus_captured": r["gain"] / ceil if ceil > 1e-9 else 0.0,
             "dropped": dropped_count(edges_seen, matched_ids),
             "bad_match": int(r["refused"] + neg > 0)}
    trace = [{"role": "system", "content": f"policy {policy.name}: {policy.params()}\nsynthetic {name} seed {seed}: "
                                           f"session {bs.DAY} of {bs.DAY} (the first {bs.DAY - 1} warmed the policy); "
                                           f"true limits known to the grader only"}]
    t0 = 100 * k_last
    for t, book, plan in seen:
        acc_t = [x for x in acc if x[0] == t - t0]
        ok = {(x[1], x[2]) for x in acc_t}
        lines = [f"{x[1]} x {x[2]} @ {x[3]} (true gain {x[4]})" for x in acc_t]
        lines += [f"REFUSED {m}" for m in plan if (m[0], m[1]) not in ok]
        trace.append({"role": "user", "content": f"tick {t} (+{t - t0}) book: {fmt_book(book)}"})
        trace.append({"role": "assistant", "content": "; ".join(lines) or "no match"})
    trace.append({"role": "assistant", "content": f"session end: {r['matches']} matches, true gain {r['gain']:.1f} "
                                                  f"of best {best:.1f} (ceiling {ceil:.1f})"})
    perf = {"matches": r["matches"], "ticks": bs.TICKS, "guard_dropped": gd[0]}
    return grade, perf, trace


def synth_prompt(name: str, sc: dict, seed: int) -> str:
    traders = synth_day(name, sc, seed)[-1]
    v = [t["limit"] for t in traders if t["side"] == "buy"]
    c = [t["limit"] for t in traders if t["side"] == "sell"]
    return (f"synthetic session: scenario {name} seed {seed} (session {bs.DAY} of a {bs.DAY}-session day; the first "
            f"{bs.DAY - 1} warm the policy); {bs.TICKS} ticks; {len(traders)} traders: {len(v)} buyers (true values "
            f"{min(v):.0f}-{max(v):.0f} P), {len(c)} sellers (true costs {min(c):.0f}-{max(c):.0f} P); "
            f"{sum(t['firm'] for t in traders)} firm, {sum(t['P'] <= sc['imp'][1] for t in traders)} with patience <= "
            f"{sc['imp'][1]}; expiry shown: {sc['expiry']}; best gains {bs.best_gain(traders):.1f} P, quote-respecting "
            f"ceiling {bs.ceiling_gain(traders, sc):.1f} P")


# ---------------------------------------------------------------- runner

def build_cases(args) -> tuple:
    """([case], excluded {id: why}, notes). A case: id, tags, source, prompt, and what run_case needs."""
    cases, excluded, notes = [], {}, []
    log = Path(args.logs) / "broker" / f"{args.date}.jsonl"
    groups = {g.strip() for g in args.groups.split(",")}
    if "real" in groups:
        if not log.exists():
            notes.append(f"no broker log at {log}: no real cases")
        else:
            states, live, ended = read_log(log)
            sessions, ex = real_sessions(states, live, ended)
            for run, why in ex.items():
                excluded[f"real-{args.date}-{run}"] = why
            for run, sess in sorted(sessions.items(), key=lambda kv: kv[1]["states"][0][0]):
                cid = f"real-{args.date}-{run}"
                if real_denominators(sess)[1] <= 1e-9:
                    excluded[cid] = "no pair ever crossed on the recorded book: nothing any broker can match"
                    continue
                meta = {"run": run, "first_tick": sess["states"][0][0], "last_tick": sess["states"][-1][0],
                        "live_pairs": len(sess["live"]), **score_around(Path(args.logs) / "score.jsonl", sess)}
                cases.append({"id": cid, "tags": ["real", run], "source": f"broker/{args.date}.jsonl",
                              "prompt": real_prompt(sess, args.date), "meta": meta, "_sess": sess})
    if "synthetic" in groups:
        fitted, note = fitted_scenarios(log) if log.exists() else ({}, "no log: no refit")
        if note:
            notes.append(note)
        for name in [s.strip() for s in args.scenarios.split(",") if s.strip()]:
            if name in fitted:
                sc = {**bs.BASE, **fitted[name], "name": name}
                label = f"{name}@{sc_hash(fitted[name])}"
            elif name in bs.SCENARIOS:
                sc, label = bs.scenario(name), name
            else:
                notes.append(f"scenario {name}: unknown or no refit, skipped")
                continue
            for seed in range(args.seeds):
                cid = f"syn-{label}-s{seed}"
                if bs.ceiling_gain(synth_day(name, sc, seed)[-1], sc) <= 1e-9:
                    excluded[cid] = "no pair ever crosses on the book: nothing any broker can match"
                    continue
                cases.append({"id": cid, "tags": ["synthetic", name], "source": f"bench_sim {label} seed {seed}",
                              "prompt": synth_prompt(name, sc, seed),
                              "meta": {"scenario": name, "seed": seed,
                                       "overrides": fitted.get(name) or bs.SCENARIOS.get(name)},
                              "_sc": sc, "_name": name, "_seed": seed})
    return cases, excluded, notes


def run_case(case: dict, policy: str) -> tuple:
    if case["tags"][0] == "real":
        sess = case["_sess"]
        oracle = dict.fromkeys(real_denominators(sess)[2], True) if policy == "oracle" else None
        grade, perf, trace = run_real(sess, Policy(policy, oracle))
    else:
        grade, perf, trace = run_synth(case["_name"], case["_sc"], case["_seed"], policy)
    return grade, perf, trace, case["meta"]


def summarise(rows: list, label: str) -> list:
    lines = [ec.summary_line(FLOW, label, rows, METRICS)]
    for tag in sorted({r["tags"][0] for r in rows}):
        sub = [r for r in rows if r["tags"][0] == tag]
        lines.append("  " + ec.summary_line(FLOW, f"{label}:{tag}", sub, METRICS[:4]))
    for tag in sorted({r["tags"][1] for r in rows if r["tags"][0] == "synthetic"}):
        sub = [r for r in rows if r["tags"][0] == "synthetic" and r["tags"][1] == tag]
        mu, half, n = ec.mean_ci([r["grade"]["bench_score"] for r in sub])
        lines.append(f"    synthetic/{tag}: bench_score {mu:.3f} +- {half:.3f} (n={n})")
    return lines


def compare(variant: str, root: Path) -> None:
    """Paired per-case delta (variant - baseline) on every metric, over cases present in both; a CI that excludes 0
    is a difference above the noise floor."""
    def load(v):
        p = root / FLOW / v / "results.jsonl"
        by: dict = {}
        for line in p.read_text().splitlines() if p.exists() else []:
            r = json.loads(line)
            if r.get("status") == "ok":
                by.setdefault(r["prompt_id"], []).append(r)
        return by
    a, b = load("baseline"), load(variant)
    shared = sorted(set(a) & set(b))
    print(f"{variant} vs baseline: {len(shared)} shared cases")
    for m in METRICS:
        d = []
        for cid in shared:
            va = [r["grade"][m["id"]] for r in a[cid] if m["id"] in r["grade"]]
            vb = [r["grade"][m["id"]] for r in b[cid] if m["id"] in r["grade"]]
            if va and vb:
                d.append(sum(vb) / len(vb) - sum(va) / len(va))
        mu, half, n = ec.mean_ci(d)
        if n:
            sig = "ABOVE noise" if n > 1 and abs(mu) > half else "within noise"
            print(f"  {m['id']:<17} {mu:+.4f} +- {half:.4f} (n={n}) {sig}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", default="baseline", help="baseline or v<N>")
    ap.add_argument("--policy", default="stall", choices=LIVE_POLICIES + HARNESS_POLICIES,
                    help="stall: what Sunday runs (tools/factory_sunday.json); ours: BenchPolicy; the rest: harness")
    ap.add_argument("--reps", type=int, default=1, help="reps per case (the policies are deterministic: 1 suffices)")
    ap.add_argument("--logs", default=str(ROOT / "logs"), help="logs dir with broker/<date>.jsonl and score.jsonl "
                                                              "(read only)")
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"), help="which day's broker log")
    ap.add_argument("--groups", default="real,synthetic")
    ap.add_argument("--scenarios", default=SCENARIOS, help="synthetic scenarios (fitted* come from the refit)")
    ap.add_argument("--seeds", type=int, default=SEEDS, help="seeds per synthetic scenario")
    ap.add_argument("--timeout-s", type=float, default=60.0, help="wall-clock ceiling per case")
    ap.add_argument("--out-root", default=None, help="write <out-root>/broker/<variant>/ instead of evals/ "
                                                     "(required for oracle, null, reckless)")
    ap.add_argument("--compare", default=None, metavar="vN", help="only print vN's paired delta vs baseline")
    ap.add_argument("--change", default=None, help="non-baseline only: what this variant changes (change.md; first "
                                                    "line = label)")
    args = ap.parse_args(argv)

    evals = (ec.ROOT / "evals").resolve()
    out = Path(args.out_root).resolve() if args.out_root else evals
    if args.out_root and (out == evals or evals in out.parents):
        raise SystemExit("--out-root must be outside evals/")
    if args.policy in HARNESS_POLICIES and out == evals and not args.compare:
        raise SystemExit(f"--policy {args.policy} is a harness check: pass --out-root outside evals/")
    logs = Path(args.logs).resolve()
    if out == logs or logs in out.parents:
        raise SystemExit("the output root must not be inside --logs (logs are read only)")
    ec.EVALS = out  # eval_common resolves every flow path through this module global
    if args.compare:
        compare(ec.check_variant(args.compare), out)
        return 0

    cases, excluded, notes = build_cases(args)
    for n in notes:
        print(f"note: {n}")
    for cid, why in excluded.items():
        print(f"excluded {cid}: {why}")
    ec.write_state(FLOW, METRICS, PERF, {"headline": "bench_score", "groups": ["real", "synthetic"]})
    ec.write_cases(FLOW, [{k: v for k, v in c.items() if not k.startswith("_")} for c in cases],
                   "Broker eval cases (Market Test)", ["source", "prompt"])
    sha = ec.file_sha(ROOT / "agent" / "broker.py")
    change = None
    if args.variant != "baseline":
        change = args.change or f"broker.py --policy {args.policy}\n\nSame cases as baseline; only the bench policy changes."
    run = ec.Run(FLOW, args.variant, f"broker.py@{sha}+{args.policy}", change)
    t0 = time.time()
    for c in cases:
        for rep in range(args.reps):
            run.case(c["id"], rep, c["prompt"], c["tags"], lambda c=c: run_case(c, args.policy), args.timeout_s)
    rows = run.all_rows()
    print(f"{len(cases)} cases x {args.reps} reps in {time.time() - t0:.1f} s -> {run.dir}")
    if run.errors.exists():
        print(f"errors: {sum(1 for _ in run.errors.open())} (see {run.errors})")
    for line in summarise(rows, args.variant):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
