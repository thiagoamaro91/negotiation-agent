"""Analyst on duty: one keyless, read-only command per Sunday trigger, each a short verdict with numbers.

Every command reads the logs the Mini pushes to `main` (logs/broker, logs/duel, logs/duels, logs/{abuela,chato,pilar},
logs/score.jsonl) and the public feed (logs/feed/, or the VM recorder's copy with --feed), reuses the labs we already
have (tools/eval_broker.py replays the stall, tools/duel_field_read.py reads rival shapes, tools/duel_matrix.py runs the
arena), prints a verdict and writes it to logs/analyst/<trigger>-<tick>.md; logs/analyst/LATEST.md is rebuilt after
every command (newest verdict per trigger, then the newest report in full). It never holds the key, never sends a
message, an offer or an accept, and never changes a live parameter: the only file it writes outside logs/analyst/ is
docs/duel-lab/duel-params-final.json, and only when `duels --matrix` finds a candidate that wins under the 2 SE rule.

    python3 tools/analyst.py bench [--session b53|latest] [--date 2026-10-04]   # after each Market Test
    python3 tools/analyst.py duels --session 3 [--matrix]   # Duels III read-out (+ arena check for the Final)
    python3 tools/analyst.py ladder                          # the 15 dealer-ladder slots this round
    python3 tools/analyst.py market                          # other teams on our venue v20
    python3 tools/analyst.py score                           # score split, rank, delta since the last trigger

Common flags: --logs DIR (default logs/), --feed DIR (repeatable; merged by event id; default logs/feed; on the VM add
~/bazaar/negotiation-agent/logs/feed, the live recorder), --live (also read /api/feed and /api/leaderboard, keyless
GETs), --out DIR (default logs/analyst), --no-write. Game text (offer notes, duel words, announcements) is never
printed: only ids, prices, ticks and counts.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

US = "t03"
VENUE = "v20"
URL = "https://bazaar.causaprima.ai"
DEALER_LEVEL = {"abuela": 1, "chato": 2, "pilar": 3, "picaros": 4, "banco": 5}
SLOTS_PER_LEVEL = 3
DUEL_SESSION_OFFSET = 1        # logs/duels "session" = arena session + 1 (server 1 = Friday practice, 2 = Duels I)
SE_RULE = 2.0                  # a candidate must beat the baseline by more than this many standard errors
MAX_CANDIDATES = 5             # arena budget per read-out
VM_FEED = Path.home() / "bazaar" / "negotiation-agent" / "logs" / "feed"


# ---------------------------------------------------------------- inputs (all read-only)

def read_jsonl(path: Path) -> list:
    out = []
    try:
        text = Path(path).read_text()
    except OSError:
        return out
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def merge_events(*sources) -> list:
    """Feed events from several files or lists, deduped by id, ordered by (tick, id)."""
    seen = {}
    for src in sources:
        for e in src:
            if isinstance(e, dict) and e.get("id") is not None:
                seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: (e.get("tick") or 0, e.get("id") or 0))


def public_get(path: str, timeout: float = 10.0):
    """One keyless GET (no key header is ever set)."""
    req = urllib.request.Request(URL + path, headers={"User-Agent": "t03-analyst/1 (read-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def load_feed(dirs: list, live: bool = False) -> tuple:
    """(events, leaderboard snapshots [(tick, body)]) from the feed dirs, plus the live window with --live."""
    sources, boards = [], []
    for d in dirs:
        d = Path(d).expanduser()
        sources.append(read_jsonl(d / "feed.jsonl"))
        for s in read_jsonl(d / "snapshots.jsonl"):
            if s.get("what") == "leaderboard" and isinstance(s.get("body"), dict):
                boards.append((s["body"].get("tick") or s.get("tick") or 0, s["body"]))
    if live:
        try:
            body = public_get("/api/feed?limit=1000")
            sources.append(body.get("events", body) if isinstance(body, dict) else body)
        except Exception as e:  # noqa: BLE001 - offline is a normal state for this tool
            print(f"(live feed unavailable: {type(e).__name__})")
        try:
            lb = public_get("/api/leaderboard")
            boards.append((lb.get("tick") or 0, lb))
        except Exception as e:  # noqa: BLE001
            print(f"(live leaderboard unavailable: {type(e).__name__})")
    boards.sort(key=lambda b: b[0])
    return merge_events(*sources), boards


def last_tick(events: list, default: int = 0) -> int:
    return max((e.get("tick") or 0 for e in events), default=default)


# ---------------------------------------------------------------- bench (after each Market Test)

def bench_starts(events: list) -> list:
    """[(start_tick, ticks, session, name)] of every bench.started in the feed."""
    out = []
    for e in events:
        if e.get("type") == "bench.started":
            p = e.get("payload") or {}
            out.append((p.get("start_tick") or e.get("tick") or 0, p.get("ticks") or 16, p.get("session"),
                        p.get("name") or ""))
    return out


def session_window(first_tick: int, starts: list) -> tuple:
    """(start, end, session no) of the feed's Market Test that contains first_tick; (None, None, None) if none."""
    for start, ticks, no, _name in sorted(starts, reverse=True):
        if start - 2 <= first_tick <= start + ticks:
            return start, start + ticks, no
    return None, None, None


def expiry_read(traders: dict, session_end) -> dict:
    """Do the bench offers show per-offer expiries that differ from the session end? `--policy ours` reads them."""
    exps = [t.get("expires") for t in traders.values()]
    shown = [x for x in exps if isinstance(x, (int, float))]
    distinct = sorted(set(shown))
    ref = session_end if session_end is not None else (max(distinct) if distinct else None)
    early = [x for x in shown if ref is not None and x < ref - 1]
    return {"shown": len(shown), "of": len(exps), "distinct": distinct[:12], "n_distinct": len(distinct),
            "ref_end": ref, "early": len(early),
            "differs": bool(shown) and (len(distinct) > 1 or bool(early))}


def first_cross(states: list, crossing) -> dict:
    """{(sell, buy): (tick, index)} of the first recorded book state on which each pair crossed."""
    out = {}
    for i, (tick, book) in enumerate(states):
        for e in crossing(book):
            out.setdefault(e, (tick, i))
    return out


def latency(live: list, first: dict) -> list:
    """Ticks between the first book on which a matched pair crossed and the tick we sent the match."""
    out = []
    for tick, s, b, _p in live:
        f = first.get((s, b))
        if f is not None and isinstance(tick, (int, float)):
            out.append(max(0, tick - f[0]))
    return out


def bench_verdict(r: dict) -> tuple:
    """('stall behaved' | 'something is wrong: ...', [problems])."""
    probs = []
    if r["dropped_live"]:
        probs.append(f"{r['dropped_live']} matches dropped by the guard ({', '.join(r['dropped_why'])})")
    if r["refused"]:
        probs.append(f"{r['refused']} matches refused by the venue")
    if r["read_errors"]:
        probs.append(f"{r['read_errors']} read errors during the session")
    if r["best"] > 0 and r["live_gain"] < r["replay_gain"] - max(1.0, 0.05 * r["best"]):
        probs.append(f"live gain {r['live_gain']:.0f} P below the stall replay {r['replay_gain']:.0f} P")
    # one pair can wait legitimately (its offers were in a better pair first): only a slow median is a problem
    if r["lat"] and statistics.median(r["lat"]) > 1:
        probs.append(f"slow matches: median {statistics.median(r['lat']):.0f} ticks from the cross to our match")
    if r["live_n"] == 0 and r["replay_n"] > 0:
        probs.append("no match sent although the stall replay finds some")
    return ("stall behaved" if not probs else "something is wrong: " + "; ".join(probs)), probs


def cmd_bench(a, events) -> tuple:
    import broker as brk
    import eval_broker as ebr
    date = a.date or time.strftime("%Y-%m-%d")
    path = Path(a.logs) / "broker" / f"{date}.jsonl"
    rows = read_jsonl(path)
    if not rows:
        return f"no broker log at {path}", [], 0, {}
    states, live, ended = ebr.read_log(path)
    sessions, excluded = ebr.real_sessions(states, live, ended)
    if not sessions:
        return "no finished Market Test session in the broker log", [f"excluded: {excluded}"], 0, {}
    name = a.session
    if name in (None, "", "latest"):
        name = max(sessions, key=lambda r: sessions[r]["states"][-1][0])
    if name not in sessions:
        return f"session {name} not found", [f"sessions: {', '.join(sorted(sessions))}; excluded {excluded}"], 0, {}
    sess = sessions[name]
    tr = sess["traders"]
    t_first, t_last = sess["states"][0][0], sess["states"][-1][0]
    start, end, no = session_window(t_first, bench_starts(events))
    best, ceil, _ = ebr.real_denominators(sess)
    live_pairs = [(t, s, b, p) for t, s, b, p in sess["live"]]
    live_gain = sum(tr[b]["limit"] - tr[s]["limit"] for _t, s, b, _p in live_pairs if s in tr and b in tr)
    g_stall, perf_stall, _ = ebr.run_real(sess, ebr.Policy("stall"))
    g_ours, perf_ours, _ = ebr.run_real(sess, ebr.Policy("ours"))
    replay_gain = g_stall["bench_score"] * best
    ours_gain = g_ours["bench_score"] * best
    ids = set(tr)
    run_rows = [r for r in rows if r.get("event") in ("dropped", "refused", "send_error")
                and (set(map(str, (r.get("match") or [])[:2])) & ids or r.get("sell") in ids or r.get("buy") in ids)]
    dropped = [r for r in run_rows if r.get("event") == "dropped"]
    refused = [r for r in run_rows if r.get("event") in ("refused", "send_error")]
    ts_books = [r.get("ts", "") for r in rows if r.get("event") == "book" and isinstance(r.get("book"), dict)
                and brk._num(r.get("tick")) and t_first <= r["tick"] <= t_last]
    lo, hi = (min(ts_books), max(ts_books)) if ts_books else ("", "")
    read_errors = [r for r in rows if r.get("event") in ("read_error", "bad_book", "error") and lo <= r.get("ts", "") <= hi]
    lat = latency(live_pairs, first_cross(sess["states"], ebr.crossing_edges))
    exp = expiry_read(tr, end)
    after = ebr.score_around(Path(a.logs) / "score.jsonl", sess)
    r = {"best": best, "ceil": ceil, "live_gain": live_gain, "replay_gain": replay_gain, "ours_gain": ours_gain,
         "live_n": len(live_pairs), "replay_n": perf_stall["matches"], "ours_n": perf_ours["matches"],
         "dropped_live": len(dropped), "dropped_why": sorted({str(d.get("why")) for d in dropped}),
         "refused": len(refused), "read_errors": len(read_errors), "lat": lat, "exp": exp,
         "replay_dropped": g_stall["dropped"], "live_agree": g_stall["live_agree"]}
    verdict, _ = bench_verdict(r)
    pct = (lambda x: f"{100 * x / best:.0f}%" if best > 0 else "n/a")
    lines = [
        f"session {name} (feed bench session {no}, ticks {start}-{end}; recorded {t_first}-{t_last}, "
        f"{len(sess['states'])} book states, {sum(1 for t in tr.values() if t['side'] == 'buy')} buyers / "
        f"{sum(1 for t in tr.values() if t['side'] == 'sell')} sellers)",
        f"efficiency proxy (revealed limits): live {live_gain:.0f} P = {pct(live_gain)} of best {best:.0f} P "
        f"({100 * live_gain / ceil if ceil > 0 else 0:.0f}% of the quote-respecting ceiling {ceil:.0f} P); "
        f"stall replay {replay_gain:.0f} P = {pct(replay_gain)}; "
        f"`--policy ours` replay {ours_gain:.0f} P = {pct(ours_gain)}",
        f"matches: live {len(live_pairs)}, stall replay {perf_stall['matches']}, ours replay {perf_ours['matches']}; "
        f"live vs replay pairs agree {g_stall['live_agree']:.2f}; crossable pairs the replay leaves "
        f"{g_stall['dropped']}",
        f"dropped by our guard: {len(dropped)}" + (f" ({', '.join(r['dropped_why'])})" if dropped else "")
        + f"; refused/send errors: {len(refused)}; read errors in the window: {len(read_errors)}",
        "book change -> match sent: " + (f"median {statistics.median(lat):.0f} tick(s), max {max(lat)} "
                                          f"over {len(lat)} matches" if lat else "no live match to time"),
        f"expiries: {exp['shown']}/{exp['of']} offers show one, {exp['n_distinct']} distinct "
        f"{exp['distinct']}, session end {exp['ref_end']}, {exp['early']} earlier than the end",
    ]
    if exp["differs"]:
        lines.append("=> per-offer expiries differ from the session end: `--policy ours` is a CANDIDATE for the next "
                     f"test (its replay here: {ours_gain:.0f} P vs stall {replay_gain:.0f} P). Needs a human yes; "
                     "the live policy is not changed by this tool.")
    else:
        lines.append("=> expiries carry no extra information: keep `--policy stall`.")
    if after:
        lines.append(f"official bench_points around the session (score.jsonl): before {after.get('bench_points_before')}"
                     f", after {after.get('bench_points_after')}")
    return f"bench {name}: {verdict}", lines, t_last, {"session": name, **{k: v for k, v in r.items() if k != 'exp'}}


# ---------------------------------------------------------------- duels (after Duels III, ~12:30)

def duel_files(log_dir: Path, session: int) -> list:
    """Final duel files (not the *-first copies) of arena session `session` (server session + offset)."""
    out = []
    for f in sorted(Path(log_dir).glob("duel-*.json")):
        if f.stem.endswith("-first"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("session") == session + DUEL_SESSION_OFFSET:
            out.append(d)
    return out


def _priced(msgs: list) -> list:
    return [m for m in msgs if isinstance(m.get("price"), (int, float))]


def classify_duel(d: dict, min_surplus: float = 1.0) -> dict:
    """One duel, from its final file: what we got, and for a no-deal where it was lost.

    loss: mute (rival never priced), inside_not_taken (a rival offer was worth >= min_surplus to us in the last
    LATE_WINDOW ticks and we did not take it; early_inside_not_taken when it came earlier), short_of_limit (our last offer stayed above our limit and the rival's closest offer was within that
    margin: a last chance at our limit might have closed), deadline (the rival first priced in the last 2 ticks), no_zone
    (the rival never came within reach of our limit). Values use duel.surplus (our limit, the days term as duel.py
    reads it)."""
    import duel as dl
    ov = "auto"
    rival = _priced(dl.rival_msgs(d))
    ours = _priced([m for m in d.get("messages") or [] if isinstance(m, dict) and m.get("from") == "you"])
    deadline = d.get("deadline_tick")
    val = (lambda m: dl.surplus(d, int(m["price"]), m.get("days"), ov))
    row = {"duel": d.get("duel"), "role": d.get("role"), "rival": d.get("rival"), "status": d.get("status"),
           "limit": d.get("your_limit"), "result": d.get("result"), "price": d.get("price"), "days": d.get("days"),
           "rounds": d.get("rounds"), "rival_n": len(rival), "ours_n": len(ours), "loss": None,
           "best_rival": max((val(m) for m in rival), default=None),
           "our_last": val(ours[-1]) if ours else None, "first_rival_left": None, "conceding_at_accept": False}
    if rival and deadline is not None:
        row["first_rival_left"] = deadline - rival[0]["tick"]
    # the rival priced only after our first offer: it waited for our anchor
    row["anchor_elicited"] = bool(rival and ours and rival[0]["tick"] > ours[0]["tick"])
    if d.get("status") == "deal":
        if d.get("price") is not None and two(d):
            row["days_value"] = -dl.days_cost(d, d.get("days"), ov)
        # was the rival still moving our way when the deal closed: an improvement within its last 3 ticks?
        end = rival[-1]["tick"] if rival else None
        row["conceding_at_accept"] = any(val(rival[i]) > val(rival[i - 1]) and rival[i]["tick"] >= end - 2
                                         for i in range(1, len(rival)))
        return row
    inside = [m for m in rival if val(m) >= min_surplus]
    row["inside_left"] = (deadline - inside[0]["tick"]) if inside and deadline is not None else None
    if not rival:
        row["loss"] = "mute"
    elif inside and row["inside_left"] is not None and row["inside_left"] >= LATE_WINDOW:
        row["loss"] = "early_inside_not_taken"
    elif inside:
        row["loss"] = "inside_not_taken"
    elif row["first_rival_left"] is not None and row["first_rival_left"] <= 2:
        row["loss"] = "deadline"
    elif ours and row["our_last"] is not None and row["our_last"] > 0 and row["best_rival"] > -row["our_last"]:
        row["loss"] = "short_of_limit"
    else:
        row["loss"] = "no_zone"
    return row


def two(d: dict) -> bool:
    return "days" in (d.get("issues") or [])


LEVERS = {  # path read -> (lever, duel.py knob it maps to, bounded delta)
    "inside_not_taken": ("accept window (a rival offer inside our limit went untaken)", "accept_any_ticks", +1),
    "early_inside_not_taken": ("early accept (a rich offer before the last ticks; duel.py accepts early only with "
                               "the paired limit, off since Duels I: needs code, not params)", None, None),
    "short_of_limit": ("last-chance ticks", "last_chance_ticks", +1),
    "deadline": ("last-chance ticks", "last_chance_ticks", +1),
    "mute": ("last chance to a silent rival (F2)", "silent_last_margin", 0.05),
    "anchor_elicited": ("open-with-anchor timing (rivals that wait for our anchor)", "stall_ticks", -1),
    "conceding_at_accept": ("accept-while-conceding (hold for deadline-1, F1)", "hold_while_conceding", True),
}
LATE_WINDOW = 4          # a rival offer inside our limit this many ticks or more before the end is an early one
DOC_WORDS = {"accept_any_ticks": ("accept window", "accept_any", "accept-any"),  # how the WP1 doc names each lever
             "last_chance_ticks": ("last-chance", "last chance tick", "last_chance"),
             "silent_last_margin": ("silent_last_margin", "silent rival", "silent-last"),
             "stall_ticks": ("anchor",), "hold_while_conceding": ("conceding",)}
KNOB_DEFAULTS = {"accept_any_ticks": 3, "last_chance_ticks": 2, "silent_last_margin": 0.0, "stall_ticks": 4,
                 "hold_while_conceding": False}
ANCHOR_SHARE = 0.25      # open-with-anchor becomes a candidate when this share of duels had the rival wait for us
CONCEDING_SHARE = 0.5    # accept-while-conceding becomes a candidate when this share of deals took a still-moving rival


def duel_summary(rows: list) -> dict:
    by_role = collections.defaultdict(lambda: [0, 0])
    by_rival = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = 0 if r["status"] == "deal" else 1
        by_role[r["role"]][k] += 1
        by_rival[r["rival"]][k] += 1
    losses = collections.Counter(r["loss"] for r in rows if r["loss"])
    deals = [r for r in rows if r["status"] == "deal"]
    days = collections.Counter(r.get("days") for r in deals if r.get("days") is not None)
    dv = [r["days_value"] for r in deals if r.get("days_value") is not None]
    return {"n": len(rows), "deals": len(deals), "by_role": dict(by_role), "by_rival": dict(by_rival),
            "losses": dict(losses), "surplus": round(sum((r["result"] or 0) for r in deals), 1),
            "days": dict(days), "days_value": round(sum(dv), 1) if dv else None,
            "conceding_at_accept": sum(1 for r in deals if r["conceding_at_accept"])}


def lever_hits(rows: list, doc_text: str = "") -> list:
    """[(lever, knob, delta, n duels it would have touched, duel ids)], most hits first. No-deal causes count one
    hit each; the two session-wide reads (rivals waiting for our anchor, deals taken from a still-conceding rival)
    count only past their share threshold. A hit is a recorded path the lever acts on; whether the rival would then
    have accepted is the arena's question."""
    hits = collections.OrderedDict()

    def add(key, did):
        lev, knob, delta = LEVERS[key]
        h = hits.setdefault(knob or key, [lev, knob, delta, 0, []])
        h[3] += 1
        h[4].append(did)
    for r in rows:
        if r["loss"] in LEVERS:
            add(r["loss"], r["duel"])
    deals = [r for r in rows if r["status"] == "deal"]
    waited = [r for r in rows if r.get("anchor_elicited")]
    if rows and len(waited) / len(rows) >= ANCHOR_SHARE:
        for r in waited:
            add("anchor_elicited", r["duel"])
    moving = [r for r in deals if r["conceding_at_accept"]]
    if deals and len(moving) / len(deals) >= CONCEDING_SHARE:
        for r in moving:
            add("conceding_at_accept", r["duel"])
    out = sorted((tuple(h) for h in hits.values()), key=lambda h: -h[3])
    if doc_text:
        low = doc_text.lower()
        out = [h + (any(w in low for w in DOC_WORDS.get(h[1], ("early accept",))),) for h in out]
    return out


SHAPE_TO_KIND = {"every-tick": "linear", "stepped": "steady", "jump-hold": "fast", "oneshot": "oneshot",
                 "holds": "tft", "reactive": "tft"}


def field_weights(log_rows: dict, results: dict) -> dict:
    """Arena rival kinds counted from duel_field_read shapes of this session's duels: silent rivals are 'absent'
    when the duel ended without a deal, 'silent' when they took our offer."""
    import duel_field_read as dfr
    w = collections.Counter()
    for did, d in log_rows.items():
        s = dfr.shape(d)
        if s == "silent":
            w["silent" if results.get(did) == "deal" else "absent"] += 1
        else:
            w[SHAPE_TO_KIND.get(s, "steady")] += 1
    return dict(w)


def candidates_from(base: dict, hits: list, extra: dict) -> dict:
    """{name: params}: each lever with hits as a one-knob delta on the base, then any extra files; at most
    MAX_CANDIDATES. Bounded: integer knobs move by one tick and stay in 1..6; margins stay in 0..0.15."""
    out = {}
    for lev, knob, delta, n, *_ in hits:
        if n <= 0 or knob is None:
            continue
        p = dict(base)
        cur = p.get(knob, KNOB_DEFAULTS[knob])
        if isinstance(delta, bool):
            new = delta
        elif isinstance(delta, float):
            new = round(min(0.15, max(0.0, cur + delta)), 3)
        else:
            new = max(1, min(6, int(cur) + delta))
        if new == cur:
            continue
        p[knob] = new
        out[f"{knob}@{new}"] = p
    out.update(extra)
    return dict(list(out.items())[:MAX_CANDIDATES])


def pick_winner(cells: list, base: str, focus: str, guard_rows: list) -> tuple:
    """(winner or None, why). A candidate wins when it beats `base` on the `focus` world by more than SE_RULE standard
    errors and is not more than SE_RULE SE worse on any guard world (the D-1 stress and the observed mixes)."""
    by = collections.defaultdict(dict)
    for c in cells:
        by[c["policy"]][(c["world"], c["mode"])] = c
    best, why = None, []
    for pol, cs in by.items():
        if pol == base:
            continue
        f = [c for (w, _m), c in cs.items() if w == focus]
        if not f:
            why.append(f"{pol}: focus world missing")
            continue
        gain = min(c["delta"] - SE_RULE * c["se"] for c in f)
        worse = [f"{w} ({m}) {c['delta']:+.3f}±{c['se']:.3f}" for (w, m), c in cs.items()
                 if w in guard_rows and c["delta"] < -SE_RULE * c["se"]]
        if gain <= 0:
            got = ", ".join("%+.3f±%.3f" % (c["delta"], c["se"]) for c in f)
            why.append(f"{pol}: not 2 SE better on {focus} ({got})")
        elif worse:
            why.append(f"{pol}: 2 SE worse on {'; '.join(worse)}")
        else:
            d = max(c["delta"] for c in f)
            why.append(f"{pol}: WINS {d:+.3f} on {focus}")
            if best is None or d > best[1]:
                best = (pol, d)
    return (best[0] if best else None), why


def params_delta(base: dict, new: dict) -> dict:
    return {k: (base.get(k), new.get(k)) for k in sorted(set(base) | set(new)) if base.get(k) != new.get(k)}


def base_params_path(a) -> Path:
    for p in [a.base_params, ROOT / "docs/duel-lab/duel-params-duels3.json",
              ROOT / "docs/duel-lab/duel-params-duels2-final.json"]:
        if p and Path(p).exists():
            return Path(p)
    raise SystemExit("no base params file")


def run_matrix(a, base_path: Path, cands: dict, mix_file: Path, mix_name: str, out_dir: Path) -> list:
    import subprocess
    cand_dir = out_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, str(ROOT / "tools/duel_matrix.py"), "--session", str(a.matrix_session), "--sessions",
            str(a.sessions), "--params", f"base={base_path}", "--mix", f"{mix_name}={mix_file}", "--d1-stress",
            "--out-json", str(out_dir / "matrix.json"), "--out-md", str(out_dir / "matrix.md")]
    for name, p in cands.items():
        f = cand_dir / (name.replace("@", "-") + ".json")
        f.write_text(json.dumps(p, indent=2) + "\n")
        args += ["--params", f"{name}={f}"]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
    return json.loads((out_dir / "matrix.json").read_text())["cells"]


def cmd_duels(a, events) -> tuple:
    import duel_field_read as dfr
    logs = Path(a.logs)
    rows = [classify_duel(d) for d in duel_files(logs / "duels", a.session)]
    if not rows:
        return f"no duel files for session {a.session} (server session {a.session + DUEL_SESSION_OFFSET})", [], 0, {}
    ids = {r["duel"] for r in rows}
    log = logs / "duel" / f"{a.date or time.strftime('%Y-%m-%d')}.jsonl"
    log_rows = {k: v for k, v in dfr.load(log, "").items() if k in ids} if log.exists() else {}
    s = duel_summary(rows)
    doc = ROOT / "docs/duel-lab/duels3-params.md"
    doc_text = doc.read_text() if doc.exists() else ""
    hits = lever_hits(rows, doc_text)
    tick = max((r.get("deadline_tick") or 0 for r in duel_files(logs / "duels", a.session)), default=0)
    lines = [f"{s['n']} duels, {s['deals']} deals, our surplus {s['surplus']} P; "
             + ", ".join(f"{role}: {v[0]} deals / {v[1]} no-deals" for role, v in sorted(s["by_role"].items())),
             "no-deals by cause: " + (", ".join(f"{k} {v}" for k, v in sorted(s["losses"].items())) or "none"),
             "day term: deals by delivery day " + (", ".join(f"d{k}: {v}" for k, v in sorted(s["days"].items())) or "-")
             + (f"; days worth {s['days_value']:+.1f} P to us over all deals" if s["days_value"] is not None else ""),
             f"accepts taken while the rival was still conceding: {s['conceding_at_accept']} of {s['deals']}"]
    worst = sorted(((v[1], k) for k, v in s["by_rival"].items() if v[1]), reverse=True)[:5]
    if worst:
        lines.append("rivals with no-deals: " + ", ".join(f"{k} {n}" for n, k in worst))
    for r in rows:
        if r["loss"] and r["loss"] != "no_zone":
            lines.append(f"  duel {r['duel']} {r['role']} vs {r['rival']}: {r['loss']} (best rival offer "
                         f"{_f(r['best_rival'])} P to us, our last offer left us {_f(r['our_last'])} P, rival first "
                         f"priced {_f(r['first_rival_left'])} ticks before the end"
                         + (f", first inside our limit {r['inside_left']} ticks before the end" if r.get("inside_left")
                            is not None else "") + ")")
    lines.append("levers (" + ("WP1 doc read" if doc_text else "WP1 doc docs/duel-lab/duels3-params.md not found") + "):")
    for h in hits:
        step = "" if h[2] is None else (str(h[2]) if isinstance(h[2], bool) else f"{h[2]:+}")
        lines.append(f"  {h[0]} -> {h[1] or 'no knob'} {step}: would touch {h[3]} duel(s) "
                     f"{h[4][:8]}"
                     + ("" if len(h) < 6 else (" (named in the WP1 doc)" if h[5] else " (not in the WP1 doc)")))
    if not hits:
        lines.append("  none: every no-deal was outside our limit (no lever would have changed an outcome)")
    weights = field_weights(log_rows, {r["duel"]: r["status"] for r in rows}) if log_rows else {}
    lines.append("field refit (duel_field_read shapes -> arena kinds): " + (json.dumps(weights) if weights
                                                                               else "no duel log for this session"))
    verdict = f"duels session {a.session}: {s['deals']}/{s['n']} deals, {s['surplus']} P"
    extra = {"summary": s, "weights": weights, "hits": [list(h[:5]) for h in hits]}
    if a.matrix:
        if not weights:
            lines.append("matrix skipped: no field to refit")
        else:
            out_dir = Path(a.out) / f"matrix-s{a.session}"
            out_dir.mkdir(parents=True, exist_ok=True)
            mix_file = out_dir / "field.json"
            mix_file.write_text(json.dumps(weights, indent=1) + "\n")
            base_path = base_params_path(a)
            base = json.loads(base_path.read_text())
            extra_c = {}
            for spec in a.candidate:
                n, _, f = spec.partition("=")
                extra_c[n] = json.loads(Path(f).expanduser().read_text())
            cands = candidates_from(base, hits, extra_c)
            if not cands:
                lines.append("matrix: no candidate (no lever has hits, no --candidate): keep")
                verdict += "; Final params: keep"
            else:
                mix_name = f"Duels {'I' * a.session} field"
                cells = run_matrix(a, base_path, cands, mix_file, mix_name, out_dir)
                guards = [f"mix: {mix_name}", "mix: Duels I field", "mix: likely field", f"d1: {mix_name}"]
                win, why = pick_winner(cells, "base", f"mix: {mix_name}", guards)
                lines.append(f"matrix (arena session {a.matrix_session}, {a.sessions} sessions, base {base_path.name}"
                             f"): {out_dir / 'matrix.md'}")
                lines += [f"  {w}" for w in why]
                if win:
                    new = cands[win]
                    target = ROOT / "docs/duel-lab/duel-params-final.json"
                    if a.write:
                        target.write_text(json.dumps(new, indent=2) + "\n")
                    lines.append(f"=> Final params delta {params_delta(base, new)}: written to {target.relative_to(ROOT)}"
                                 " (a human copies it to the factory's params path; nothing live changes here)")
                    verdict += f"; Final params: CHANGE {params_delta(base, new)}"
                else:
                    lines.append("=> keep the Duels III params for the Final")
                    verdict += "; Final params: keep"
                extra["matrix_why"] = why
    return verdict, lines, tick, extra


def _f(x) -> str:
    return "-" if x is None else f"{x:.0f}"


# ---------------------------------------------------------------- ladder (the 15 dealer slots this round)

def round_start(events: list) -> tuple:
    """(tick, round no, name) of the latest round.started."""
    best = (0, None, "")
    for e in events:
        if e.get("type") == "round.started":
            p = e.get("payload") or {}
            best = (e.get("tick") or 0, p.get("round"), p.get("name") or "")
    return best


def our_values(logs: Path) -> dict:
    """{"bot": {ref: [(ts, side, value)]}, "held": {ref: value}}: what our dealer bots valued each card at when they
    opened a thread or planned a trade (logs/<dealer>/*.jsonl), and the value of the copy we still hold
    (logs/state/me.json, which may be worth more than a spare we sold)."""
    bot, held = collections.defaultdict(list), {}
    try:
        for a in json.loads((logs / "state" / "me.json").read_text()).get("assets") or []:
            if a.get("ref") and isinstance(a.get("your_value"), (int, float)):
                held.setdefault(a["ref"], a["your_value"])
    except (OSError, ValueError):
        pass
    for agent in DEALER_LEVEL:
        for f in sorted((logs / agent).glob("*.jsonl")) if (logs / agent).exists() else []:
            for r in read_jsonl(f):
                ev = r.get("event")
                for p in ([r] if ev == "open" else (r.get("plan") or []) if ev == "run_start" else []):
                    if isinstance(p, dict) and p.get("item") and isinstance(p.get("value"), (int, float)):
                        bot[p["item"]].append((str(r.get("ts", ""))[:19], p.get("side"), p["value"]))
    return {"bot": {k: sorted(v) for k, v in bot.items()}, "held": held}


def value_at(values: dict, ref: str, side: str, ts: str) -> tuple:
    """(value, source) for a deal: the newest bot value for this card and side logged at or before the deal ("bot"),
    else the held copy's value ("held"), else (None, None). A buy-side value is never used for a sale: a card we
    needed for the album is worth more than the spare we later sell."""
    ts = str(ts or "")[:19]
    rows = [r for r in (values.get("bot") or {}).get(ref, []) if r[1] == side and (not ts or r[0] <= ts)]
    if rows:
        return rows[-1][2], "bot"
    v = (values.get("held") or {}).get(ref)
    return (v, "held") if v is not None else (None, None)


def dealer_deals(events: list, since: int, team: str = US) -> list:
    """Our dealer settlements since tick `since`: [{tick, dealer, level, side, ref, kind, price}]."""
    out = []
    for e in events:
        p = e.get("payload") or {}
        if e.get("type") != "settlement" or (e.get("tick") or 0) < since or p.get("persona") not in DEALER_LEVEL:
            continue
        if team not in (p.get("parties") or []):
            continue
        for it in p.get("items") or []:
            side = "buy" if it.get("to") == team else "sell"
            out.append({"tick": e.get("tick"), "dealer": p["persona"], "level": DEALER_LEVEL[p["persona"]],
                        "side": side, "ref": it.get("ref"), "kind": it.get("kind"), "price": p.get("price"),
                        "ts": str(e.get("seen_at") or "")[:19]})
    return out


def ladder_slots(deals: list, values: dict) -> dict:
    """{level: {"deals": [...], "best": [...top 3 by gain], "zero": [...wrong side of our value], "check": [...]}}.
    A deal's gain at our private value: buy = value - price, sell = price - value; a gain below 0 scores 0 (the value
    gate). A sale below the value of the copy we still hold goes to "check", not "zero": the copy sold was a spare,
    which may be worth less to us. values: our_values()."""
    out = {lv: {"deals": [], "best": [], "zero": [], "check": []} for lv in sorted(set(DEALER_LEVEL.values()))}
    for d in deals:
        v, src = value_at(values, d["ref"], d["side"], d.get("ts"))
        d = dict(d, value=v, source=src, gain=None if v is None or d["price"] is None
                 else round((v - d["price"]) if d["side"] == "buy" else (d["price"] - v), 1))
        out[d["level"]]["deals"].append(d)
        if d["gain"] is not None and d["gain"] < 0:
            out[d["level"]]["check" if d["side"] == "sell" and src == "held" else "zero"].append(d)
    for lv, s in out.items():
        ok = [d for d in s["deals"] if d not in s["zero"]]
        s["best"] = sorted(ok, key=lambda d: -(d["gain"] if d["gain"] is not None else -1e9))[:SLOTS_PER_LEVEL]
    return out


def cmd_ladder(a, events) -> tuple:
    start, no, name = round_start(events)
    deals = dealer_deals(events, start)
    slots = ladder_slots(deals, our_values(Path(a.logs)))
    filled = sum(len(s["best"]) for s in slots.values())
    lines = [f"round {no} {name!s} since tick {start}: {len(deals)} dealer deals of ours"]
    names = {v: k for k, v in DEALER_LEVEL.items()}
    todo = []
    for lv, s in slots.items():
        got = len(s["best"])
        lines.append(f"  L{lv} {names[lv]}: {got}/{SLOTS_PER_LEVEL} slots"
                     + ("".join(f"; {d['side']} {d['ref']} @ {d['price']} (value {_f(d['value'])}, gain "
                                f"{_f(d['gain'])})" for d in s["best"])))
        for d in s["zero"]:
            lines.append(f"    scored 0 (wrong side of value): tick {d['tick']} {d['side']} {d['ref']} @ {d['price']}"
                         f" vs value {_f(d['value'])}")
        for d in s["check"]:
            lines.append(f"    check: tick {d['tick']} sold {d['ref']} @ {d['price']} below the {_f(d['value'])} of the "
                         "copy we hold (a spare may be worth less; scored 0 if not)")
        if got < SLOTS_PER_LEVEL:
            todo.append(f"{SLOTS_PER_LEVEL - got} x L{lv} {names[lv]}")
    lines.append("left before 14:00: " + (", ".join(todo) if todo else "nothing: 15/15 filled")
                 + " (higher levels weigh more; every deal must clear our value)")
    zero = sum(len(s["zero"]) for s in slots.values())
    return (f"ladder: {filled}/15 slots filled, {zero} deal(s) scored 0", lines, last_tick(events),
            {"filled": filled, "zero": zero, "todo": todo})


# ---------------------------------------------------------------- market (other teams on v20)

def venue_activity(events: list, venue: str = VENUE, us: str = US) -> dict:
    listed, trades, ann = [], [], []
    for e in events:
        p = e.get("payload") or {}
        t = e.get("type")
        if t == "offer.listed" and p.get("venue") == venue:
            o = p.get("offer") or {}
            listed.append({"tick": e.get("tick"), "maker": o.get("maker") or e.get("actor"), "id": o.get("id"),
                           "give": _items(o.get("give")), "want": _items(o.get("want"))})
        elif t == "settlement" and p.get("venue") == venue:
            trades.append({"tick": e.get("tick"), "parties": p.get("parties") or [], "price": p.get("price"),
                           "items": [i.get("ref") for i in p.get("items") or []], "fee": p.get("fee")})
        elif t == "venue.announcement" and (p.get("venue") == venue or e.get("actor") == venue):
            ann.append(e.get("tick") or 0)
    others = [x for x in trades if us not in x["parties"]]
    return {"listed": listed, "trades": trades, "others": others, "announcements": ann}


def _items(side) -> str:
    side = side or {}
    parts = [f"{side.get('cash')} P"] if side.get("cash") else []
    parts += [a.get("ref") or a.get("kind") for a in side.get("assets") or []]
    parts += list(side.get("types") or [])
    return "+".join(map(str, parts)) or "-"


def preceded(tick: int, marks: list, window: int) -> int | None:
    """Ticks since the latest mark at or before `tick` within `window`, else None."""
    prior = [m for m in marks if m <= tick and tick - m <= window]
    return tick - max(prior) if prior else None


def outreach_ticks(logs: Path) -> list:
    """Ticks of our own outreach (tools/outreach.py logs, if WP3's tool ran) and announcements (tools/announce.py)."""
    out = []
    for agent in ("outreach", "announce", "matchmaker"):
        d = logs / agent
        for f in sorted(d.glob("*.jsonl")) if d.exists() else []:
            for r in read_jsonl(f):
                if r.get("event") in ("announce", "sent", "outreach", "message", "post") and isinstance(r.get("tick"), int):
                    out.append(r["tick"])
    return out


def cmd_market(a, events) -> tuple:
    v = venue_activity(events)
    marks = sorted(set(v["announcements"]) | set(outreach_ticks(Path(a.logs))))
    makers = collections.Counter(x["maker"] for x in v["listed"])
    lines = [f"{len(v['listed'])} offers listed on {VENUE} by {len(makers)} maker(s): "
             + ", ".join(f"{m} {n}" for m, n in makers.most_common(8)),
             f"{len(v['trades'])} settlements on {VENUE}, {len(v['others'])} between other teams",
             f"{len(v['announcements'])} venue announcements on {VENUE}; {len(marks)} announcement/outreach marks"]
    for x in v["listed"][-12:]:
        p = preceded(x["tick"], marks, a.window)
        lines.append(f"  tick {x['tick']} {x['maker']}: gives {x['give']} wants {x['want']} | "
                     + (f"{p} ticks after an announcement/outreach" if p is not None else
                        f"no announcement/outreach in the {a.window} ticks before"))
    for x in v["others"]:
        p = preceded(x["tick"], marks, a.window)
        lines.append(f"  TRADE tick {x['tick']} {'/'.join(x['parties'])} {x['items']} @ {x['price']} | "
                     + (f"{p} ticks after an announcement/outreach" if p is not None else "unprompted"))
    led = sum(1 for x in v["listed"] if preceded(x["tick"], marks, a.window) is not None)
    verdict = (f"market: {len(v['others'])} trade(s) between other teams on {VENUE}, {len(v['listed'])} listings "
               f"({led} within {a.window} ticks of an announcement/outreach)")
    return verdict, lines, last_tick(events), {"others": len(v["others"]), "listed": len(v["listed"]), "led": led}


# ---------------------------------------------------------------- score

SPLIT = ("score", "negotiating", "market", "duel_points", "ladder_points", "bench_points", "mm_points", "rank")


def board_row(body: dict, team: str = US) -> tuple:
    """(our row, leader row, row above us) from one leaderboard body."""
    teams = sorted(body.get("teams") or [], key=lambda t: t.get("rank") or 99)
    me = next((t for t in teams if t.get("team") == team), None)
    above = None
    if me:
        ups = [t for t in teams if (t.get("rank") or 99) < (me.get("rank") or 99)]
        above = ups[-1] if ups else None
    return me, (teams[0] if teams else None), above


def score_delta(cur: dict, prev: dict | None) -> dict:
    if not prev:
        return {}
    return {k: round(cur[k] - prev[k], 3) for k in SPLIT if isinstance(cur.get(k), (int, float))
            and isinstance(prev.get(k), (int, float))}


def cmd_score(a, events, boards) -> tuple:
    rows = read_jsonl(Path(a.logs) / "score.jsonl")
    cur = None
    if rows:
        r = rows[-1]
        cur = {"tick": r.get("tick"), "cash": r.get("cash"), **{k: (r.get("score") or {}).get(k) for k in SPLIT}}
    lb_tick, me, lead, above = None, None, None, None
    if boards:
        lb_tick, body = boards[-1]
        me, lead, above = board_row(body)
    if me and (cur is None or (lb_tick or 0) > (cur.get("tick") or 0)):
        cur = {"tick": lb_tick, "cash": cur.get("cash") if cur else None,
               **{k: me.get(k) for k in ("score", "negotiating", "market", "rank")},
               **{k: (cur or {}).get(k) for k in ("duel_points", "ladder_points", "bench_points", "mm_points")}}
    if cur is None:
        return "score: no data", [], 0, {}
    state = Path(a.out) / "score-state.json"
    prev = None
    if a.since_tick is not None:
        prev = next((dict(tick=r.get("tick"), **{k: (r.get("score") or {}).get(k) for k in SPLIT})
                     for r in reversed(rows) if (r.get("tick") or 0) <= a.since_tick), None)
    elif state.exists():
        try:
            prev = json.loads(state.read_text())
        except ValueError:
            prev = None
    d = score_delta(cur, prev)
    lines = [f"tick {cur['tick']}: score {cur.get('score')} = negotiating {cur.get('negotiating')} + market "
             f"{cur.get('market')} (+ judges later); rank {cur.get('rank')}; cash {cur.get('cash')}",
             f"inside: duel_points {cur.get('duel_points')}, ladder_points {cur.get('ladder_points')}, bench_points "
             f"{cur.get('bench_points')}, mm_points {cur.get('mm_points')} (score.jsonl at tick {rows[-1].get('tick') if rows else '-'})"]
    if lead:
        lines.append(f"leader {lead.get('team')} {lead.get('score')} (market {lead.get('market')})"
                     + (f"; next above us {above.get('team')} {above.get('score')} "
                        f"(gap {round((above.get('score') or 0) - (cur.get('score') or 0), 2)})" if above else ""))
    if prev:
        lines.append(f"since tick {prev.get('tick')}: " + ", ".join(f"{k} {v:+}" for k, v in d.items() if v))
    if a.write:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(cur) + "\n")
    verdict = (f"score: {cur.get('score')} rank {cur.get('rank')}"
               + (f" ({d.get('score', 0):+} since tick {prev.get('tick')})" if prev else ""))
    return verdict, lines, cur.get("tick") or 0, {"cur": cur, "delta": d}


# ---------------------------------------------------------------- reports

def write_report(out: Path, trigger: str, tick: int, verdict: str, lines: list) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{trigger}-{tick}.md"
    body = [f"# {trigger} at tick {tick}", "", f"_{time.strftime('%Y-%m-%d %H:%M:%S')} local, tools/analyst.py_", "",
            f"**{verdict}**", ""] + [f"- {l}" if not l.startswith("  ") else f"  - {l.strip()}" for l in lines]
    f.write_text("\n".join(body) + "\n")
    rebuild_latest(out, f)
    return f


def rebuild_latest(out: Path, newest: Path | None = None) -> None:
    """LATEST.md: the session's handoff (HANDOFF.md, if written), the newest verdict per trigger (one line each), then
    the newest report in full."""
    per = {}
    for f in sorted(out.glob("*-*.md"), key=lambda p: p.stat().st_mtime):
        if f.name in ("LATEST.md", "HANDOFF.md") or not f.stem.rsplit("-", 1)[-1].isdigit():
            continue
        per[f.stem.rsplit("-", 1)[0]] = f
        newest = f if newest is None or f.stat().st_mtime >= newest.stat().st_mtime else newest
    rows = ["# Analyst on duty: latest", ""]
    if (out / "HANDOFF.md").exists():
        rows += ["```", (out / "HANDOFF.md").read_text().strip(), "```", ""]
    rows += ["| trigger | report | verdict |", "|---|---|---|"]
    for trig, f in sorted(per.items()):
        verdict = next((l.strip("*") for l in f.read_text().splitlines() if l.startswith("**")), "")
        rows.append(f"| {trig} | {f.name} | {verdict.replace('|', '/')} |")
    if newest is not None:
        rows += ["", "---", "", newest.read_text()]
    (out / "LATEST.md").write_text("\n".join(rows) + "\n")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["bench", "duels", "ladder", "market", "score", "latest"],
                    help="latest: only rebuild LATEST.md (after writing logs/analyst/HANDOFF.md)")
    ap.add_argument("--logs", default=str(ROOT / "logs"))
    ap.add_argument("--feed", action="append", default=None, help="feed dir (repeatable, merged by event id)")
    ap.add_argument("--live", action="store_true", help="also read /api/feed and /api/leaderboard (keyless GETs)")
    ap.add_argument("--out", default=str(ROOT / "logs" / "analyst"))
    ap.add_argument("--no-write", dest="write", action="store_false")
    ap.add_argument("--date", default=None, help="day of logs/broker and logs/duel (default today)")
    ap.add_argument("--session", default=None, help="bench: bXX or latest; duels: arena session (3 = Duels III)")
    ap.add_argument("--matrix", action="store_true", help="duels: run duel_matrix on the refit field")
    ap.add_argument("--matrix-session", type=int, default=4, help="duels: arena session the params are for (4 = Final)")
    ap.add_argument("--sessions", type=int, default=60, help="duels: arena sessions per matrix cell")
    ap.add_argument("--base-params", default=None, help="duels: baseline params (default duel-params-duels3.json)")
    ap.add_argument("--candidate", action="append", default=[], help="duels: NAME=FILE extra candidate")
    ap.add_argument("--window", type=int, default=40, help="market: ticks an announcement/outreach counts before")
    ap.add_argument("--since-tick", type=int, default=None, help="score: delta against this tick, not the last run")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "latest":
        Path(a.out).mkdir(parents=True, exist_ok=True)
        rebuild_latest(Path(a.out))
        print(f"-> {Path(a.out) / 'LATEST.md'}")
        return 0
    feeds = a.feed or [str(ROOT / "logs" / "feed")]
    events, boards = load_feed(feeds, a.live)
    if a.cmd == "duels":
        a.session = int(a.session or 3)
    if a.cmd == "bench":
        verdict, lines, tick, extra = cmd_bench(a, events)
        a.session = extra.get("session", a.session)
    elif a.cmd == "duels":
        verdict, lines, tick, extra = cmd_duels(a, events)
    elif a.cmd == "ladder":
        verdict, lines, tick, extra = cmd_ladder(a, events)
    elif a.cmd == "market":
        verdict, lines, tick, extra = cmd_market(a, events)
    else:
        verdict, lines, tick, extra = cmd_score(a, events, boards)
    print(verdict)
    for l in lines:
        print(("  " if not l.startswith("  ") else "    ") + l.strip())
    if a.write:
        trig = a.cmd + (f"-{a.session}" if a.cmd in ("bench", "duels") and a.session else "")
        print(f"-> {write_report(Path(a.out), trig, tick, verdict, lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
