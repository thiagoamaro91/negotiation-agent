"""Offline eval of the duel negotiator (agent/duel.py): three flows, one runner. No network, no key, no model.

Each flow replays agent/duel.py through the engines tools/duel_arena.py already has, one row per duel:

    duels-friday    Friday's practice duels (server session 1) on duel_arena.friday_replay: the rival price paths
                    the bots actually posted, fixed (rivals never react to us and never accept). Pie = the SOFT pie
                    from the paired duel's limit, as the arena scores it.
    duels-saturday  Saturday's real duels (server session 2 = Duels I, plus any later price-only session found in
                    the logs, tagged by session) on duel_arena.duels1_replay: the real tick timeline, so overlapping
                    duels share the one accept per tick. Rivals fixed, never accept. Score = surplus / our limit x
                    decay^rounds (the rival's limit, so the pie, is unknown); vs_real compares with the server result.
    duels-arena     duel_arena's synthetic TEST sessions (seeds 900000.., every rival kind) where rivals DO react
                    and accept. Default: Sunday's format (arena session 3 = Duels III: price + days, 12 ticks, decay
                    0.10), paired limit hidden as in Duels I (0 of 34 found). One case = one duel; tags[0] = rival kind.

The engines are reused as they are. They expose no per-tick trace, so while one runs this file wraps duel.decide and
duel.record_say (module attributes the engines call) to record what the policy saw and did each tick, and swaps
duel.decide for the harness check policies (--policy oracle|null|reckless). Nothing in agent/ or the engines changes.

Grades per duel (evals/<flow>/metrics.md explains each, and what was left out):
    score            headline: the duel score as the engine computes it, clipped to [-1, 1]
    deal             1 if a deal was reached
    missed_ok_offer  1 if the policy saw a rival offer inside our limit (>= 1 P surplus) and ended with no deal
    limit_breach     1 if we sent, or a deal closed at, a price past our own limit (guardrail: must stay 0)
    vs_real          real flows only: replayed score minus the score of what actually happened (server result)

Game text is never read: only limits, roles, ticks and prices (rival message `text` stays in the log files).

Usage (from the repo root):
    python3 tools/eval_duels.py --flow duels-friday                      # baseline params, logs/
    python3 tools/eval_duels.py --flow duels-saturday --logs /Volumes/bazaar/logs
    python3 tools/eval_duels.py --flow duels-arena          # 100 sessions from seed 900000
    python3 tools/eval_duels.py --flow duels-friday --variant v1 --params docs/duel-lab/duel-params-duels2-tuned.json
    python3 tools/eval_duels.py --flow duels-friday --policy oracle --out-root /tmp/x   # harness checks
    node <claude-api skill>/shared/evals/report/build-report-lite.mjs evals/duels-friday/
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import duel_arena as arena  # noqa: E402  (puts agent/ and kit/ on the path)
import eval_common as ec  # noqa: E402

duel = arena.duel

FLOWS = ("duels-friday", "duels-saturday", "duels-arena")
BASELINE_PARAMS = ROOT / "docs" / "duel-lab" / "duel-params-duels2-final.json"
POLICIES = ("duel", "oracle", "null", "reckless")
SESSION_NAMES = {1: "Friday practice", 2: "Duels I"}       # server session numbers seen in logs/duels
FRIDAY_TICKS = 12

RATE = {"kind": "float", "scale": 1}      # 0/1 metrics: see metrics.md ("Why the 0/1 metrics are not kind binary")
METRICS = [
    {"id": "score", "label": "score", "kind": "float", "scale": 1},
    {"id": "deal", "label": "deal", **RATE, "rate": True},
    {"id": "missed_ok_offer", "label": "missed ok", **RATE, "rate": True, "better": "lower"},
    {"id": "limit_breach", "label": "breach", **RATE, "rate": True, "better": "lower"},
]
VS_REAL = {"id": "vs_real", "label": "vs real", "kind": "float", "scale": 1}
PERF = [
    {"id": "surplus_P", "label": "surplus", "unit": "P"},
    {"id": "rounds", "label": "rounds"},
    {"id": "deal_tick", "label": "deal tick", "unit": "ticks from start"},
    {"id": "msgs_sent", "label": "msgs sent"},
    {"id": "best_offer_score", "label": "best offer score"},
]
PERF_REAL = [{"id": "real_result_P", "label": "real result", "unit": "P"},
             {"id": "vs_real_P", "label": "vs real", "unit": "P"}]


# ---------------------------------------------------------------- policies (duel.decide's signature)

def null_decide(d, st, tick, cfg):
    """Never speaks, never accepts: must score 0 deals and 0 score."""
    return {"left": d["deadline_tick"] - tick, "action": "hold", "why": "null policy", "rival": None}


def reckless_decide(d, st, tick, cfg):
    """Broken on purpose: opens past its own limit and accepts any rival offer, whatever the price."""
    left = d["deadline_tick"] - tick
    out = {"left": left, "rival": duel.parse_offer(d.get("rival_offer"))}
    if st.accepted_at is not None or left < 1:
        return {**out, "action": "hold", "why": "reckless: settled or over"}
    if out["rival"] is not None:
        p = out["rival"][0]
        s = (p - d["your_limit"]) if d["role"] == "seller" else (d["your_limit"] - p)
        return {**out, "action": "accept", "kind": "reckless", "rival_surplus": s, "why": "reckless: take anything"}
    if st.sent == 0:
        lim = d["your_limit"]
        p = max(1, int(lim * 0.5)) if d["role"] == "seller" else int(math.ceil(lim * 1.5))
        days = 5 if duel.two_issues(d) else None
        return {**out, "action": "say", "price": p, "days": days, "step": "reckless",
                "why": "reckless: offer past our limit"}
    return {**out, "action": "hold", "why": "reckless: waiting"}


def make_oracle(plan: dict, truth):
    """Accepts each duel's planned offer at its planned tick (or later, if the slot was lost): plan = duel id ->
    (tick, our surplus), from oracle_plan. truth(d, price, day) = our real surplus. Silent, so it pays no rounds."""
    def oracle_decide(d, st, tick, cfg):
        left = d["deadline_tick"] - tick
        rival = duel.parse_offer(d.get("rival_offer"))
        out = {"left": left, "rival": rival}
        planned = plan.get(d["duel"])
        if st.accepted_at is not None or left < 1 or rival is None or planned is None:
            return {**out, "action": "hold", "why": "oracle: nothing planned here"}
        s = truth(d, rival[0], rival[1])
        if tick >= planned[0] and s >= planned[1] - 1e-9:
            return {**out, "action": "accept", "kind": "oracle", "rival_surplus": s, "why": "oracle: planned offer"}
        return {**out, "action": "hold", "why": f"oracle: waiting for tick {planned[0]}"}
    return oracle_decide


def assign_max(value: list) -> dict:
    """Max-weight assignment (Hungarian, rows <= columns): row -> column."""
    n, m = len(value), len(value[0])
    inf = float("inf")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = -value[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return {p[j] - 1: j - 1 for j in range(1, m + 1) if p[j]}


def oracle_plan(silent: "Recorder", value_of, cfg) -> dict:
    """The best slot-feasible set of silent accepts, from a pass where we never spoke: for every duel and tick, the
    offer it would see then (the late read's view when the duel is in its own late window), worth value_of(did, offer)
    in score units; at most one accept per tick across overlapping duels (the team's limit), total score maximised.
    Returns duel id -> (tick, our surplus at that offer)."""
    late_on = getattr(cfg, "late_poll", 0) > 0
    cells = {}                                       # did -> {tick: (value, surplus)}
    for did, calls in silent.calls.items():
        by_tick = defaultdict(list)
        for t, seen, _ in calls:
            by_tick[t].append(seen)
        D = silent.deadline[did]
        row = {}
        for t, views in by_tick.items():
            seen = views[-1] if late_on and 1 <= D - t <= cfg.late_ticks else views[0]
            if seen is None:
                continue
            val = value_of(did, seen)
            if val is not None and val[0] > 0:
                row[t] = val
        if row:
            cells[did] = row
    # independent groups: duels whose candidate ticks overlap
    spans = sorted((min(r), max(r), did) for did, r in cells.items())
    groups, cur, end = [], [], None
    for a, b, did in spans:
        if cur and a > end:
            groups.append(cur)
            cur, end = [], None
        cur.append(did)
        end = b if end is None else max(end, b)
    if cur:
        groups.append(cur)
    plan = {}
    for g in groups:
        ticks = sorted({t for did in g for t in cells[did]})
        width = max(len(ticks), len(g))
        value = [[cells[did].get(t, (0.0, 0))[0] if k < len(ticks) else 0.0
                  for k, t in enumerate(ticks + [None] * (width - len(ticks)))] for did in g]
        for i, k in assign_max(value).items():
            if k < len(ticks) and ticks[k] in cells[g[i]]:
                plan[g[i]] = (ticks[k], cells[g[i]][ticks[k]][1])
    return plan


# ---------------------------------------------------------------- recorder (wraps the engine's calls into duel.py)

class Recorder:
    """Per duel id: every decide() call (tick, the rival offer it saw, the decision dict, which allocate may still
    change in place) and every message actually sent (record_say)."""

    def __init__(self):
        self.calls = defaultdict(list)    # duel id -> [(tick, rival offer seen, dec)]
        self.says = {}                    # (duel id, tick) -> (price, days)
        self.deadline = {}                # duel id -> deadline tick


@contextmanager
def recording(decide_fn):
    rec = Recorder()
    orig_decide, orig_say = duel.decide, duel.record_say

    def decide(d, st, tick, cfg):
        dec = decide_fn(d, st, tick, cfg)
        rec.calls[d["duel"]].append((tick, duel.parse_offer(d.get("rival_offer")), dec))
        rec.deadline[d["duel"]] = d["deadline_tick"]
        return dec

    def record_say(st, dec, d, tick):
        orig_say(st, dec, d, tick)
        rec.says[(d["duel"], tick)] = (dec["price"], dec.get("days"))

    duel.decide, duel.record_say = decide, record_say
    try:
        yield rec
    finally:
        duel.decide, duel.record_say = orig_decide, orig_say


def policy_fn(name: str, plan: dict = None, truth=None):
    if name == "duel":
        return duel.decide
    if name == "null":
        return null_decide
    if name == "reckless":
        return reckless_decide
    if name == "oracle":
        return make_oracle(plan or {}, truth)
    raise SystemExit(f"unknown policy {name!r}")


# ---------------------------------------------------------------- shared helpers

def price_surplus(d: dict, price) -> float:
    return (price - d["your_limit"]) if d["role"] == "seller" else (d["your_limit"] - price)


def inside(role: str, limit, price) -> bool:
    return price >= limit if role == "seller" else price <= limit


def clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def session_tag(s: int) -> str:
    return f"s{s}-" + SESSION_NAMES.get(s, "session").lower().replace(" ", "-")


def rival_path(x: dict) -> list:
    """(tick, price) of the rival's priced messages. Only tick / from / price are read, never text."""
    return [(m["tick"], m["price"]) for m in x.get("messages") or []
            if m.get("from") == x.get("rival") and isinstance(m.get("price"), (int, float))
            and isinstance(m.get("tick"), int)]


def real_closer(x: dict) -> str:
    """Who closed a real deal: "us" (we took the rival's standing price) or "rival" (it took ours); "" if no deal."""
    if x.get("status") != "deal" or not isinstance(x.get("price"), (int, float)):
        return ""
    theirs = rival_path(x)
    ours = [m.get("price") for m in x.get("messages") or [] if m.get("from") == "you"]
    if theirs and theirs[-1][1] == x["price"]:
        return "us"
    return "rival" if x["price"] in ours else "?"


def our_says(rec: Recorder, did) -> list:
    return sorted((t, p, dd) for (i, t), (p, dd) in rec.says.items() if i == did)


def trace_turns(rec: Recorder, did, start: int, T: int, truth, deal: tuple, system: str, two: bool) -> list:
    """Tick-by-tick turns. deal = (price, day, tick, by) or None."""
    def offer(o):
        if o is None:
            return "no rival offer yet"
        p, dd = o
        return f"rival offer {p}" + (f" day {dd}" if two and dd is not None else "") + f" (our surplus {truth(o):+.1f})"

    turns = [{"role": "system", "content": system}]
    by_tick = defaultdict(list)
    for t, seen, dec in rec.calls.get(did, []):
        by_tick[t].append((seen, dec))
    says = {t: (p, dd) for t, p, dd in our_says(rec, did)}
    for t in sorted(by_tick):
        first_seen, first = by_tick[t][0]
        late = by_tick[t][1:]
        user = f"tick {t - start}/{T} (left {first.get('left')}): {offer(first_seen)}"
        if late and late[-1][0] != first_seen:
            user += f" | late read: {offer(late[-1][0])}"
        turns.append({"role": "user", "content": user})
        if deal and deal[2] == t and deal[3] == "us":
            act = f"accept {deal[0]}" + (f" day {deal[1]}" if two and deal[1] is not None else "")
            if any(dc.get("action") == "accept" for _, dc in late):
                act += " (late read)"
        elif t in says:
            p, dd = says[t]
            act = f"say {p}" + (f" day {dd}" if two and dd is not None else "") + f" ({first.get('why', '')})"
        else:
            act = f"hold ({first.get('why', '')})"
            if first.get("action") == "say":
                act = f"hold (decided to say {first.get('price')}, not sent: the duel settled first)"
        if late and not (deal and deal[2] == t and deal[3] == "us"):
            act += f" | late read: {late[-1][1].get('action')} ({late[-1][1].get('why', '')})"
        turns.append({"role": "assistant", "content": act})
        if deal and deal[2] == t and deal[3] == "them":
            turns.append({"role": "tool_result", "content": f"rival accepted our standing offer {deal[0]}"})
    return turns


def breach_of(rec: Recorder, did, role: str, limit, deal) -> int:
    sent_out = any(not inside(role, limit, p) for _, p, _ in our_says(rec, did))
    deal_out = deal is not None and not inside(role, limit, deal[0])
    return int(sent_out or deal_out)


def missed_of(rec: Recorder, did, truth, dealt: bool) -> int:
    if dealt:
        return 0
    return int(any(seen is not None and truth(seen) >= 1 for _, seen, _ in rec.calls.get(did, [])))


def params_label(policy: str, params_path) -> str:
    """Policy + duel.py hash + the params file's name AND content hash (a file edited in place keeps its name), so
    ec.Run refuses to mix rows from two different settings in one variant."""
    name = f"{Path(params_path).name}@{ec.file_sha(params_path)}" if params_path else "{}"
    base = f"duel.py@{ec.file_sha(ROOT / 'agent' / 'duel.py')}+{name}"
    return base if policy == "duel" else f"{policy}@eval_duels.py+{base}"


# ---------------------------------------------------------------- real flows (Friday, Saturday)

def load_real(logs: Path, sessions) -> tuple:
    """(closed duels by session, excluded [(id, reason)]) from <logs>/duels/duel-*.json (skips *-first.json)."""
    closed, live = defaultdict(list), []
    for f in sorted((logs / "duels").glob("duel-*.json")):
        if "-first" in f.name:
            continue
        x = json.loads(f.read_text())
        if x.get("session") not in sessions:
            continue
        if x.get("status") in ("deal", "no_deal") and isinstance(x.get("your_limit"), (int, float)):
            closed[x["session"]].append(x)
        else:
            live.append(x)
    return closed, live


def session_ticks(logs: Path, ids: set, default: int) -> int:
    """Duel length from the duel bot's own duel_new lines (total_ticks), else the default."""
    seen = Counter()
    for f in sorted((logs / "duel").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("event") == "duel_new" and r.get("duel") in ids and isinstance(r.get("total_ticks"), int):
                seen[r["total_ticks"]] += 1
    return seen.most_common(1)[0][0] if seen else default


def real_cases(flow: str, logs: Path) -> tuple:
    """[(group key, engine fn(params, policy) -> (results, recorder), [case dicts])], excluded [(id, why)]."""
    groups, excluded = [], []
    if flow == "duels-friday":
        closed, live = load_real(logs, {1})
        sess_list = [(1, closed.get(1, []), FRIDAY_TICKS)]
    else:
        found = sorted({x for x in _sessions_in(logs) if x >= 2})
        closed, live = load_real(logs, set(found))
        sess_list = []
        for s in found:
            ids = {x["duel"] for x in closed.get(s, [])}
            sess_list.append((s, closed.get(s, []), session_ticks(logs, ids, 16)))
    for x in live:
        excluded.append((f"{x.get('duel')}", f"session {x.get('session')}: status {x.get('status')} (not closed: "
                                             "no server result to compare, and "
                                             + ("no rival price" if not rival_path(x) else "still running") + ")"))
    for s, files, ticks in sess_list:
        if not files:
            continue
        if any("days" in (x.get("issues") or []) for x in files):
            for x in files:
                excluded.append((str(x["duel"]), f"session {s} is two-issue: duels1_replay is price-only (it drops "
                                                 "the rival's day), so its score would be wrong"))
            continue
        cases = []
        for x in files:
            path = rival_path(x)
            if not path:
                excluded.append((str(x["duel"]), f"session {s}: the rival never posted a price (replay rivals never "
                                                 "accept, so nothing can happen here)"))
                continue
            if flow == "duels-friday":
                pie = duel.mirror_pie(x, duel.mirror_limit(x, files))
                if (pie or 0) < 3:
                    excluded.append((str(x["duel"]), f"soft pie {pie} < 3 P (paired limit missing or no zone): "
                                                     "friday_replay does not score it"))
                    continue
            cases.append(x)
        groups.append((s, files, ticks, cases))
    return groups, excluded


def _sessions_in(logs: Path) -> set:
    out = set()
    for f in (logs / "duels").glob("duel-*.json"):
        if "-first" not in f.name:
            s = json.loads(f.read_text()).get("session")
            if isinstance(s, int):
                out.add(s)
    return out


def run_real_engine(flow: str, params: dict, files: list, ticks: int, policy: str, scored: set = None) -> tuple:
    """One replay of a whole session (its duels share the accept slot). The oracle plans only over the scored duels,
    so an unscored one never takes a slot from a scored one."""
    def engine():
        if flow == "duels-friday":
            return arena.friday_replay(params, ticks=ticks, files=files)
        return arena.duels1_replay(params, files=files, ticks=ticks)

    plan = None
    if policy == "oracle":
        cfg = arena.cfg_for(params, ticks)
        byid = {x["duel"]: x for x in files}

        def value_of(did, offer):
            if scored is not None and did not in scored:
                return None
            x = byid[did]
            s = price_surplus(x, offer[0])
            den = (duel.mirror_pie(x, duel.mirror_limit(x, files)) if flow == "duels-friday" else x["your_limit"])
            return (clip(s / den), s) if s >= 1 and den and den > 0 else None

        with recording(null_decide) as silent:
            engine()
        plan = oracle_plan(silent, value_of, cfg)
    with recording(policy_fn(policy, plan, lambda d, p, dd: price_surplus(d, p))) as rec:
        res = engine()
    return {r["duel"]: r for r in res}, rec


def real_case_row(flow: str, s: int, x: dict, ticks: int, r: dict, rec: Recorder, system: str) -> tuple:
    did, role, L, D = x["duel"], x["role"], x["your_limit"], x["deadline_tick"]
    S = D - ticks
    decay = x.get("decay_per_round") or 0.06
    path = rival_path(x)
    best_s = max((price_surplus(x, p) for _, p in path), default=0)
    if flow == "duels-friday":
        pie = r.get("soft_pie") or 0
        best_score = clip(best_s / pie) if pie > 0 and best_s > 0 else 0.0
        real_score = 0.0 if x.get("status") != "deal" else clip((x.get("result") or 0) / pie if pie > 0 else 0)
    else:
        best_score = clip(best_s / L) if best_s > 0 else 0.0
        real_score = clip((x.get("result") or 0.0) / L)
    deal = (r["price"], None, S + r["at"], "us") if r.get("deal") else None
    score = clip(r.get("score", 0.0))
    truth = (lambda o: price_surplus(x, o[0]))
    grade = {"score": round(score, 4), "deal": int(bool(deal)),
             "missed_ok_offer": missed_of(rec, did, truth, bool(deal)),
             "limit_breach": breach_of(rec, did, role, L, deal),
             "vs_real": round(score - real_score, 4)}
    surplus = price_surplus(x, deal[0]) if deal else 0
    real_res = float(x.get("result") or 0.0)
    our_res = (r.get("result") if flow == "duels-saturday" else
               (surplus * (1 - decay) ** r.get("rounds", 0) if deal else 0.0))
    perf = {"surplus_P": surplus, "rounds": r.get("rounds", 0) if deal else 0,
            "deal_tick": r["at"] if deal else None, "msgs_sent": r.get("sent", 0),
            "best_offer_score": round(best_score, 4), "real_result_P": real_res,
            "vs_real_P": round((our_res or 0.0) - real_res, 2)}
    turns = trace_turns(rec, did, S, ticks, truth, deal, system, False)
    end = f"end: deal at {deal[0]} tick {r['at']}, {perf['rounds']} round(s)" if deal else "end: no deal"
    turns.append({"role": "tool_result", "content": end + f"; score {grade['score']:.3f}; real: {x.get('status')} "
                                                          f"result {real_res:g} P"})
    tags = [session_tag(s), role] if flow == "duels-saturday" else [role]
    tags += ["deal" if deal else "no_deal", f"real:{x.get('status')}"]
    if real_closer(x) == "rival":
        tags.append("real:rival_took_ours")
    if grade["missed_ok_offer"]:
        tags.append("missed_ok")
    if grade["limit_breach"]:
        tags.append("breach")
    meta = {"session": s, "duel": did, "price": deal[0] if deal else None,
            "engine": "friday_replay" if flow == "duels-friday" else "duels1_replay"}
    return grade, perf, turns, meta, tags


def real_prompt(flow: str, s: int, x: dict, ticks: int) -> str:
    S = x["deadline_tick"] - ticks
    path = " ".join(f"{t - S}:{p}" for t, p in rival_path(x))
    real = (f"deal at {x.get('price')}, {x.get('rounds')} round(s), result {x.get('result')} P"
            if x.get("status") == "deal" else "no deal")
    return (f"{SESSION_NAMES.get(s, f'server session {s}')} (session {s}) | duel {x['duel']} | role {x['role']} | "
            f"limit {x['your_limit']} | {ticks} ticks, deadline tick {x['deadline_tick']}, decay "
            f"{x.get('decay_per_round')} | rival prices by elapsed tick: {path} | real: {real}")




ENGINE_CACHE: dict = {}      # (flow, group, rep) -> engine output or the exception it raised


def cached_engine(key: tuple, build):
    """Runs one engine pass (a whole session: its duels share the accept slot) once per (group, rep), inside the
    first case's timeout; every case of the group then reads its own row from it."""
    if key not in ENGINE_CACHE:
        try:
            ENGINE_CACHE[key] = build()
        except Exception as e:  # noqa: BLE001 - re-raised for every case of the group, so each lands in errors.jsonl
            ENGINE_CACHE[key] = e
    got = ENGINE_CACHE[key]
    if isinstance(got, Exception):
        raise got
    return got


def run_real(a, flow: str, params: dict, run: ec.Run, system: str) -> tuple:
    groups, excluded = real_cases(flow, Path(a.logs))
    case_list = []
    for s, files, ticks, cases in groups:
        for x in cases:
            cid = ("fri-" if flow == "duels-friday" else "sat-") + f"{x['duel']:04d}"
            real = x.get("status")
            first = [x["role"]] if flow == "duels-friday" else [session_tag(s), x["role"]]
            case_list.append({"id": cid, "tags": first + [f"real:{real}"], "source": f"duels/duel-{x['duel']:05d}.json",
                              "role": x["role"], "limit": x["your_limit"], "session": s,
                              "deadline": x["deadline_tick"], "rival_prices": len(rival_path(x)),
                              "real_outcome": real, "real_closed_by": real_closer(x),
                              "real_result": x.get("result") or 0.0})
            for rep in range(a.reps):
                tags: list = []

                def fn(x=x, s=s, files=files, ticks=ticks, cases=cases, rep=rep, tags=tags):
                    res, rec = cached_engine((flow, s, rep), lambda: run_real_engine(
                        flow, params, files, ticks, a.policy, {c["duel"] for c in cases}))
                    grade, perf, turns, meta, t = real_case_row(flow, s, x, ticks, res[x["duel"]], rec, system)
                    tags[:] = t                       # Run.case writes the row after fn returns
                    return grade, perf, turns, meta

                run.case(cid, rep, real_prompt(flow, s, x, ticks), tags, fn, a.timeout_s)
    return case_list, excluded


# ---------------------------------------------------------------- arena flow

def arena_truth(byid: dict):
    def truth(d, price, day):
        dl = byid[d["duel"]]
        return dl.our_surplus(price, day if dl.days else None)
    return truth


@contextmanager
def pair_seen(value):
    saved = arena.PAIR_SEEN
    if value is not None:
        arena.PAIR_SEEN = value
    try:
        yield
    finally:
        arena.PAIR_SEEN = saved


def run_arena_engine(params: dict, seed: int, sess_no: int, policy: str, kinds: list, weights, seen) -> tuple:
    sess = arena.SESSIONS[sess_no]
    byid = {dl.id: dl for dl in arena.make_session(seed, sess, kinds, weights)}   # ground truth (limits, days)
    truth = arena_truth(byid)
    with pair_seen(seen):
        with recording(null_decide) as silent:     # what the rivals offer when we never speak (oracle and ceiling)
            arena.evaluate(params, [seed], sess_no, kinds, weights=weights)
        best = {did: max((truth({"duel": did}, *o) for _, o, _ in calls if o is not None), default=-1e9)
                for did, calls in silent.calls.items()}
        plan = None
        if policy == "oracle":
            def value_of(did, offer):
                s, pie = truth({"duel": did}, *offer), byid[did].pie()
                return (clip(s / pie), s) if s >= 1 and pie > 0 else None
            plan = oracle_plan(silent, value_of, arena.cfg_for(params, sess["ticks"]))
        with recording(policy_fn(policy, plan, truth)) as rec:
            res = arena.evaluate(params, [seed], sess_no, kinds, weights=weights)
    return {r["duel"]: r for r in res}, rec, byid, best


def arena_case_row(sess_no: int, seed: int, dl, r: dict, rec: Recorder, best: dict, system: str) -> tuple:
    sess = arena.SESSIONS[sess_no]
    T, two = sess["ticks"], bool(dl.days)
    calls = rec.calls.get(dl.id, [])
    start = calls[0][0] if calls else 0
    deal = (r["price"], r.get("day"), r["tick"], r["by"]) if r.get("deal") else None
    pie = dl.pie()

    def truth(o):
        return dl.our_surplus(o[0], o[1] if two else None)

    b = best.get(dl.id, -1e9)
    grade = {"score": round(clip(r.get("score", 0.0)), 4), "deal": int(bool(deal)),
             "missed_ok_offer": missed_of(rec, dl.id, truth, bool(deal)),
             "limit_breach": breach_of(rec, dl.id, dl.role, dl.our_limit, deal)}
    perf = {"surplus_P": round(truth((deal[0], deal[1])), 2) if deal else 0,
            "rounds": r.get("rounds", 0) if deal else 0, "deal_tick": r.get("at") if deal else None,
            "msgs_sent": r.get("sent", 0),
            "best_offer_score": round(clip(b / pie), 4) if pie > 0 and b > 0 else 0.0}
    turns = trace_turns(rec, dl.id, start, T, truth, deal, system, two)
    end = ((f"end: deal at {deal[0]}" + (f" day {deal[1]}" if two else "") + f" by {deal[3]} at tick "
            f"{r.get('at')}, {perf['rounds']} round(s), share {r.get('share', 0):.3f}") if deal else "end: no deal")
    turns.append({"role": "tool_result", "content": end + f"; score {grade['score']:.3f}; rival {dl.kind} limit "
                                                          f"{dl.rival_limit}, pie {pie:.1f}"})
    tags = [dl.kind, dl.role, "deal" if deal else "no_deal"]
    if deal:
        tags.append(f"by:{deal[3]}")
    if grade["missed_ok_offer"]:
        tags.append("missed_ok")
    if grade["limit_breach"]:
        tags.append("breach")
    meta = {"seed": seed, "session": sess_no, "duel": dl.id, "price": deal[0] if deal else None,
            "day": deal[1] if deal else None, "engine": "duel_arena.evaluate"}
    return grade, perf, turns, meta, tags


def arena_prompt(sess_no: int, seed: int, dl, seen) -> str:
    sess = arena.SESSIONS[sess_no]
    txt = (f"arena {sess['name']} format (session {sess_no}: {sess['ticks']} ticks, decay {sess['decay']}, "
           f"{'+'.join(sess['issues'])}) | seed {seed} duel {dl.id} | role {dl.role} | limit {dl.our_limit} | rival "
           f"{dl.kind} (limit {dl.rival_limit}, accepts ours: {'yes' if dl.rival.p.get('takes', True) else 'no'}) | "
           f"pie {dl.pie():.1f} | paired limit seen: {'no' if seen == 0 else 'as arena'}")
    if dl.days:
        (ob, ow), (rb, rw) = dl.days["ours"], dl.days["rival"]
        txt += f" | days: our weight {ow} best day {ob}; rival weight {rw} best day {rb}"
    return txt


def run_arena(a, params: dict, run: ec.Run, system: str) -> tuple:
    sess = arena.SESSIONS[a.arena_session]
    kinds = arena.FITTED + arena.CLASSIC
    weights = arena.DUELS1_WEIGHTS if a.weights == "duels1" else None
    case_list = []
    for seed in range(a.seed0, a.seed0 + a.sessions):
        duels_ = sorted(arena.make_session(seed, sess, kinds, weights), key=lambda x: x.id)
        for dl in duels_:
            cid = f"arena-{seed}-{dl.id:02d}"
            case_list.append({"id": cid, "tags": [dl.kind, dl.role], "source": f"duel_arena seed {seed} duel {dl.id}",
                              "kind": dl.kind, "role": dl.role, "limit": dl.our_limit,
                              "rival_limit": dl.rival_limit, "pie": round(dl.pie(), 1), "seed": seed})
            for rep in range(a.reps):
                tags: list = []

                def fn(dl=dl, seed=seed, rep=rep, tags=tags):
                    res, rec, byid, best = cached_engine(
                        ("arena", seed, rep), lambda: run_arena_engine(params, seed, a.arena_session, a.policy, kinds,
                                                                      weights, a.pair_seen))
                    grade, perf, turns, meta, t = arena_case_row(a.arena_session, seed, byid[dl.id], res[dl.id], rec,
                                                                 best, system)
                    tags[:] = t
                    return grade, perf, turns, meta

                run.case(cid, rep, arena_prompt(a.arena_session, seed, dl, a.pair_seen), tags, fn, a.timeout_s)
    return case_list, []


# ---------------------------------------------------------------- summary

def summarize(flow: str, variant: str, rows: list, metrics: list, cluster_key: str = None) -> list:
    """Mean +- 95% CI per metric (summary_line; the 0/1 metrics get Wilson intervals), per tags[0] group, the
    run-to-run spread across reps, and the noise floor for a paired comparison of two params files."""
    ok = [r for r in rows if r.get("status") == "ok"]
    as_binary = [{**m, "kind": "binary" if m.get("rate") else m["kind"]} for m in metrics]
    out = [ec.summary_line(flow, variant, ok, as_binary)]
    groups = defaultdict(list)
    for r in ok:
        groups[r["tags"][0] if r.get("tags") else "?"].append(r["grade"]["score"])
    out.append("  score by " + ("session" if flow == "duels-saturday" else "rival kind" if flow == "duels-arena"
                                else "role") + ": " + ", ".join(
        f"{k} {sum(v) / len(v):.3f} (n={len(v)})" for k, v in sorted(groups.items())))
    by_case = defaultdict(list)
    for r in ok:
        by_case[r["prompt_id"]].append(r["grade"]["score"])
    spread = max((max(v) - min(v) for v in by_case.values() if len(v) > 1), default=None)
    out.append("  reps: " + ("1 per case (the replays are deterministic; rerun with --reps 2 to check)"
                             if spread is None else f"max score spread across reps of one case = {spread:.4f}"))
    scores = [sum(v) / len(v) for v in by_case.values()]
    n = len(scores)
    if n > 1:
        m = sum(scores) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in scores) / (n - 1))
        out.append(f"  noise floor: per-case score sd {sd:.3f}, n {n}: a mean difference between two params files "
                   f"under {1.96 * math.sqrt(2) * sd / math.sqrt(n):.3f} is within case-sampling noise if the two "
                   f"were unrelated; paired on the same cases it is 1.96 x sd(per-case diff) / sqrt(n), smaller, and "
                   f"the run itself adds no noise (deterministic)")
    if cluster_key:
        cl = defaultdict(list)
        for r in ok:
            cl[r["meta"][cluster_key]].append(r["grade"]["score"])
        means = [sum(v) / len(v) for v in cl.values()]
        k = len(means)
        if k > 1:
            mu = sum(means) / k
            sd = math.sqrt(sum((x - mu) ** 2 for x in means) / (k - 1))
            out.append(f"  score clustered by {cluster_key} ({k} sessions): {mu:.3f} +- {1.96 * sd / math.sqrt(k):.3f} "
                       "(duels of one session share the accept slot and rival teams: this CI is the honest one)")
    return out


# ---------------------------------------------------------------- main

def load_params(spec: str) -> tuple:
    """(params dict, label path). '{}' = duel.py's defaults. Files are checked by duel.py's own loader."""
    if spec.strip() == "{}":
        return {}, None
    return arena.load_policy(spec), Path(spec)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flow", required=True, choices=FLOWS)
    ap.add_argument("--variant", default="baseline", help="baseline or v1, v2, ...")
    ap.add_argument("--change", default=None, help="non-baseline: one line on what this variant changes")
    ap.add_argument("--params", default=str(BASELINE_PARAMS), help="duel.py --params JSON ('{}' = defaults); "
                    "default: docs/duel-lab/duel-params-duels2-final.json, the Duels II file (the baseline of the "
                    "Duels III climb, not a Sunday file)")
    ap.add_argument("--policy", default="duel", choices=POLICIES, help="duel = agent/duel.py; oracle / null / "
                    "reckless are the harness checks (write them under --out-root, not evals/)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--logs", default=str(ROOT / "logs"), help="logs root holding duels/ and duel/ (read-only)")
    ap.add_argument("--timeout-s", type=float, default=120.0, help="ceiling per case (the first case of a session "
                    "runs the whole session)")
    ap.add_argument("--out-root", default=None, help="write <out-root>/<flow>/ instead of evals/<flow>/")
    ap.add_argument("--sessions", type=int, default=100, help="arena: simulated sessions (cases = sessions x duels)")
    ap.add_argument("--seed0", type=int, default=900000, help="arena: first seed (900000.. = the test split: duel_tune "
                    "tunes on 0.. and selects on 500000.., its stress uses 800000..)")
    ap.add_argument("--arena-session", type=int, default=3, choices=sorted(arena.SESSIONS),
                    help="arena: format (1 Duels I, 2 Duels II, 3 Duels III, 4 Final); default 3 = Sunday")
    ap.add_argument("--pair-seen", type=float, default=0.0, help="arena: share of duels whose paired limit is "
                    "visible (Duels I: 0 of 34)")
    ap.add_argument("--weights", default="all", choices=["all", "duels1"],
                    help="arena rival mix: all = every kind at the arena's Friday weights; duels1 = Duels I mix")
    a = ap.parse_args(argv)
    if a.policy != "duel" and a.out_root is None:
        raise SystemExit("--policy oracle/null/reckless are harness checks: pass --out-root (a scratch directory)")
    if a.out_root:
        ec.EVALS = Path(a.out_root).expanduser().resolve()
    ENGINE_CACHE.clear()
    params, ppath = load_params(a.params)
    label = params_label(a.policy, ppath)
    flow = a.flow
    real = flow != "duels-arena"
    if not real:   # arena case ids hold only the seed: the format, the visible-pair share and the rival mix go in the label
        label += f"+arena=s{a.arena_session}:pair{a.pair_seen}:{a.weights}"
    metrics = METRICS + ([VS_REAL] if real else [])
    extra = {"headline": "score", "baseline_params": str(BASELINE_PARAMS.relative_to(ROOT)),
             "runner": "tools/eval_duels.py"}
    if not real:
        extra["arena"] = {"session": a.arena_session, "seed0": a.seed0, "sessions": a.sessions,
                          "pair_seen": a.pair_seen, "weights": a.weights}
    ec.write_state(flow, metrics, PERF + (PERF_REAL if real else []), extra)
    run = ec.Run(flow, a.variant, label, a.change or f"params {ppath.name if ppath else '{}'}")
    system = f"policy {label}; params {json.dumps(params, sort_keys=True)}"
    if real:
        cases, excluded = run_real(a, flow, params, run, system)
    else:
        cases, excluded = run_arena(a, params, run, system)
    title = {"duels-friday": "Duels: Friday practice replay (server session 1)",
             "duels-saturday": "Duels: Saturday real duels replay (server session 2+)",
             "duels-arena": f"Duels: arena held-out sessions ({arena.SESSIONS[a.arena_session]['name']} format)"}[flow]
    cols = (["kind", "role", "limit", "rival_limit", "pie", "seed"] if not real else
            ["role", "limit", "session", "deadline", "rival_prices", "real_outcome", "real_closed_by", "real_result"])
    ec.write_cases(flow, cases, title, cols)
    if excluded:
        md = ec.flow_dir(flow) / "cases.md"
        md.write_text(md.read_text() + f"\n## Excluded ({len(excluded)})\n\n| duel | why |\n|---|---|\n"
                      + "".join(f"| {i} | {w} |\n" for i, w in excluded))
    rows = run.all_rows()
    errs = len(run.errors.read_text().splitlines()) if run.errors.exists() else 0
    print(f"{flow}/{a.variant} [{label}]: {len(cases)} cases, {len(excluded)} excluded, {len(rows)} rows, "
          f"{errs} errors -> {run.dir}")
    for line in summarize(flow, a.variant, rows, metrics, "seed" if not real else None):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
