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
import contextlib
import json
import math
import statistics
import sys
import tempfile
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


def run_last_ticks(states: list, run_of) -> dict:
    """{bench run: last tick it showed an offer} over every recorded book state, finished or not."""
    out = {}
    for tick, book in states:
        for o in book.get("bench_offers") or []:
            out[run_of(o["id"])] = tick
    return out


def pick_session(requested, sessions: dict, excluded: dict, run_last: dict, feed_starts: list) -> tuple:
    """(session name or None, why). 'latest' is the newest run in the log, finished or not, and nothing older: an
    unfinished newest run, or a Market Test the feed shows started after it with no book in the log (not pushed yet,
    or our broker missed it), gives None, never the previous session's verdict."""
    if requested not in (None, "", "latest"):
        if requested in sessions:
            return requested, ""
        if requested in excluded:
            return None, f"session {requested}: {excluded[requested]}"
        return None, f"session {requested} is not in the broker log"
    if not run_last:
        return None, "no Market Test session in the broker log"
    newest = max(run_last, key=lambda r: run_last[r])
    if newest not in sessions:
        return None, f"newest session {newest}: {excluded.get(newest, 'not finished')}"
    first = sessions[newest]["states"][0][0]
    later = sorted(st for st in feed_starts if st[0] > first + 2)
    if later:
        return None, (f"the feed shows Market Test session {later[-1][2]} starting at tick {later[-1][0]}, after "
                      f"{newest}, and the broker log has no book for it (not pushed yet, or our broker missed it)")
    return newest, ""


def run_end_expiries(rows: list, ids: set) -> dict:
    """{offer id: {"expires": tick}} from the broker's bench_run_end rows (each trader's path, as the tracker kept it)."""
    out = {}
    for r in rows:
        if r.get("event") == "bench_run_end":
            for t in r.get("traders") or []:
                if isinstance(t, dict) and t.get("id") in ids:
                    out[t["id"]] = {"expires": t.get("expires")}
    return out


def ours_risk_note(path: Path = ROOT / "evals/broker/narrative.md") -> str:
    """The eval's own row for the expiry-exact counterfactual (our repo file, not game text)."""
    try:
        for line in path.read_text().splitlines():
            if line.startswith("| fitted_expiry_exact"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                return (f"evals/broker/narrative.md, fitted_expiry_exact: delta bench_score {cells[2]}, 95% CI {cells[3]},"
                        f" dropped crossable pairs {cells[4]} (ours drops pairs the stall would match)")
    except OSError:
        pass
    return "evals/broker/narrative.md: ours +0.030 bench_score on fitted_expiry_exact but 3 crossable pairs dropped"


OURS_SWITCH = [  # what a human runs on the Mini, BETWEEN two Market Tests (never during one)
    "tmux kill-window -t factory:broker",
    "edit tools/factory_sunday.json: broker \"cmd\" \"--policy\", \"stall\" -> \"--policy\", \"ours\"",
    "python3 tools/factory.py up --yes",
    "check: tail -1 logs/broker/$(date +%F).jsonl shows run_start with \"policy\": \"ours\"",
]


MAX_TICK_GAP = 2   # the broker logs a book row every tick it runs (book_state carries the tick): a longer gap = blind


def coverage(book_ticks: list, start, end) -> tuple:
    """(ok, why): the broker's book rows cover the feed session [start, end] tick by tick (no gap over MAX_TICK_GAP)
    and reach its end. A tracker's bench_run_end is not proof the whole test was pushed."""
    if start is None or end is None:
        return False, "no bench.started in the feed for this session (cannot tell when it ends)"
    ts = sorted({t for t in book_ticks if start - MAX_TICK_GAP <= t <= end + 50})
    if not ts or ts[-1] < end:
        return False, f"the broker log stops at tick {ts[-1] if ts else '-'}, before the session's end at {end}"
    if ts[0] > start + MAX_TICK_GAP:
        return False, f"the broker log starts at tick {ts[0]}, after the session's start at {start}"
    gaps = [(x, y) for x, y in zip(ts, ts[1:]) if y - x > MAX_TICK_GAP and x <= end]
    if gaps:
        return False, f"the broker log has a gap {gaps[0][0]}->{gaps[0][1]} inside the session ({start}-{end})"
    return True, f"broker log covers ticks {start}-{end}"


def paired_mean_se(deltas: list) -> tuple:
    n = len(deltas)
    if n < 2:
        return (deltas[0] if deltas else 0.0), float("inf")
    m = sum(deltas) / n
    return m, (sum((x - m) ** 2 for x in deltas) / (n - 1)) ** 0.5 / n ** 0.5


def ours_decision(stall_gain: float, ours_gain: float, synth: list) -> tuple:
    """(switch, why). Differing expiries only make the comparison eligible. Switch to `ours` only when it does not
    lose on this session's replay AND the paired synthetic deltas (ours - stall bench_score, the day's refit with
    per-offer expiries) are above 0 by more than SE_RULE standard errors AND ours drops no more crossable pairs.
    synth: [(delta, dropped_ours, dropped_stall)]."""
    if ours_gain < stall_gain:
        return False, f"ours replays worse than the stall on this session ({ours_gain:.0f} P vs {stall_gain:.0f} P)"
    m, se = paired_mean_se([d for d, *_ in synth])
    if not synth or not m > SE_RULE * se:
        return False, (f"ours is not more than 2 SE ahead on the refit with per-offer expiries "
                       f"({m:+.3f} ± {se:.3f} bench_score over {len(synth)} paired seeds)")
    d_ours, d_stall = sum(x[1] for x in synth), sum(x[2] for x in synth)
    if d_ours > d_stall:
        return False, f"ours drops more crossable pairs than the stall on the refit ({d_ours} vs {d_stall})"
    return True, f"ours {m:+.3f} ± {se:.3f} bench_score over {len(synth)} paired seeds, dropped {d_ours} vs {d_stall}"


def synth_ours_vs_stall(log: Path, seeds: int) -> list:
    """[(ours - stall bench_score, dropped ours, dropped stall)] on eval_broker's fitted_expiry_exact scenario."""
    import eval_broker as ebr
    scs, _note = ebr.fitted_scenarios(log)
    sc = {**ebr.bs.BASE, **scs["fitted_expiry_exact"]}
    out = []
    for seed in range(seeds):
        g_s = ebr.run_synth("fitted_expiry_exact", sc, seed, "stall")[0]
        g_o = ebr.run_synth("fitted_expiry_exact", sc, seed, "ours")[0]
        out.append((g_o["bench_score"] - g_s["bench_score"], g_o["dropped"], g_s["dropped"]))
    return out


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
    name, why = pick_session(a.session, sessions, excluded, run_last_ticks(states, brk.run_of), bench_starts(events))
    if name is None:
        last = max((t for t, _ in states), default=0)
        return (f"bench: pending / insufficient data: {why}", [f"finished sessions in the log: "
                f"{', '.join(sorted(sessions)) or 'none'}; rerun in 3 minutes after the Mini pushes"], last, {})
    sess = sessions[name]
    tr = sess["traders"]
    t_first, t_last = sess["states"][0][0], sess["states"][-1][0]
    start, end, no = session_window(t_first, bench_starts(events))
    book_ticks = [r["tick"] for r in rows if r.get("event") == "book" and isinstance(r.get("tick"), int)]
    covered, cwhy = coverage(book_ticks, start, end)
    if not covered:
        return (f"bench {name}: pending / insufficient data: {cwhy}", ["no verdict and no recommendation until the "
                "log covers the whole session; rerun after the Mini pushes"], t_last, {"session": name})
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
    exp = expiry_read({**run_end_expiries(rows, set(tr)), **{k: v for k, v in tr.items() if v.get("expires")
                                                           is not None}}, end)
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
        synth = synth_ours_vs_stall(path, a.ours_seeds) if a.ours_seeds > 0 else []
        switch, swhy = ours_decision(replay_gain, ours_gain, synth)
        lines.append(f"per-offer expiries differ from the session end: `ours` vs `stall` compared ({cwhy}): {swhy}")
        if switch:
            lines.append("=> RECOMMENDATION (needs a human yes): switch to `--policy ours` (agent/broker.py "
                         "BenchPolicy: the stall's rule when blind, timing-aware when expiries are shown and confirmed "
                         f"by departures) for the next tests. Replay here: ours {ours_gain:.0f} P vs stall "
                         f"{replay_gain:.0f} P. Risk: {ours_risk_note()}. Switch only BETWEEN tests (after this one "
                         "ends, at least 5 minutes before the next; Sunday 09:55-10:45, 10:55-11:45, 11:55-13:45), "
                         "never during one.")
            lines += [f"  {c}" for c in OURS_SWITCH]
        else:
            lines.append(f"=> stall stays (ours {ours_gain:.0f} P vs stall {replay_gain:.0f} P on this session).")
    else:
        lines.append("=> per-offer expiries all at the session end (as on Saturday): keep `--policy stall`.")
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


def expected_cells(focus: str, guard_rows: list) -> set:
    """Every (world, mode) cell a verdict needs: the focus world in both modes, each mix guard in both modes, each d1
    guard in robust mode (duel_matrix --d1-stress runs d1 rows robust only)."""
    need = {(focus, "robust"), (focus, "confirmed")}
    for g in guard_rows:
        need |= {(g, "robust"), (g, "confirmed")} if g.startswith("mix:") else {(g, "robust")}
    return need


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def pick_winner(cells: list, base: str, focus: str, guard_rows: list) -> tuple:
    """(winner or None, why). A candidate wins when it beats `base` on the `focus` world by MORE than SE_RULE standard
    errors in robust AND confirmed mode and is not more than SE_RULE SE worse on any guard cell (the D-1 stress and the
    observed mixes). Decided on the statistics as given (duel_matrix writes them unrounded). A candidate with any
    expected cell missing or non-finite never wins."""
    need = expected_cells(focus, guard_rows)
    by = collections.defaultdict(dict)
    for c in cells:
        by[c["policy"]][(c["world"], c["mode"])] = c
    best, why = None, []
    for pol, cs in by.items():
        if pol == base:
            continue
        missing = sorted(need - set(cs))
        bad = sorted(k for k in need & set(cs) if not _finite(cs[k].get("delta")) or not _finite(cs[k].get("se"))
                     or cs[k]["se"] < 0)
        if missing or bad:
            why.append(f"{pol}: incomplete matrix (missing {missing}, non-finite {bad}): no verdict")
            continue
        f = [cs[(focus, m)] for m in ("robust", "confirmed")]
        gain = min(c["delta"] - SE_RULE * c["se"] for c in f)
        worse = [f"{w} ({m}) {cs[(w, m)]['delta']:+.3f}±{cs[(w, m)]['se']:.3f}" for (w, m) in sorted(need)
                 if w in guard_rows and cs[(w, m)]["delta"] < -SE_RULE * cs[(w, m)]["se"]]
        if gain <= 0:
            got = ", ".join("%+.4f±%.4f" % (c["delta"], c["se"]) for c in f)
            why.append(f"{pol}: not more than 2 SE better on {focus} in both modes ({got})")
        elif worse:
            why.append(f"{pol}: 2 SE worse on {'; '.join(worse)}")
        else:
            d = min(c["delta"] for c in f)
            why.append(f"{pol}: WINS {d:+.3f} on {focus}")
            if best is None or d > best[1]:
                best = (pol, d)
    return (best[0] if best else None), why


def params_delta(base: dict, new: dict) -> dict:
    return {k: (base.get(k), new.get(k)) for k in sorted(set(base) | set(new)) if base.get(k) != new.get(k)}


DEPLOYED_PARAMS = ROOT / "docs/duel-lab/duel-params-duels3.json"   # what the factory's duel run reads


def base_params_path(a) -> Path:
    """The deployed Duels III params (or --base-params). No fallback: a missing baseline stops the matrix."""
    p = Path(a.base_params).expanduser() if a.base_params else DEPLOYED_PARAMS
    if not p.exists():
        raise SystemExit(f"baseline params {p} missing: the matrix compares candidates with the DEPLOYED Duels III "
                         "params; pass --base-params FILE only if that is what the duel bot runs")
    return p


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


EXPECTED_DUELS = {1: 34, 2: 68, 3: 68, 4: 34}   # per team: duel_arena.SESSIONS[s]["duels"]
SESSION_TICKS = {1: 16, 2: 16, 3: 12, 4: 12}


def terminal_records(log_rows: list) -> dict:
    """{duel id: status} of our duel bot's `result` events."""
    return {r["duel"]: r.get("status") for r in log_rows if r.get("event") == "result" and r.get("duel") is not None}


def completeness(rows: list, terminal: dict, expected: int) -> tuple:
    """(complete, why): every expected duel finished (deal or no_deal) in its final server file, AND our duel bot's
    log holds a matching terminal record (`result` with the same status) for each. An id that merely appears in the
    log (a duel_new line) is not a completed observation."""
    done = [r for r in rows if r["status"] in ("deal", "no_deal")]
    if len(done) < expected:
        return False, f"{len(done)}/{expected} duels completed ({len(rows) - len(done)} still live)"
    missing = [r["duel"] for r in done if terminal.get(r["duel"]) != r["status"]]
    if missing:
        return False, (f"our duel log has a matching result record for {len(done) - len(missing)}/{len(done)} "
                       f"completed duels (missing {missing[:5]})")
    return True, f"{len(done)}/{expected} duels completed, each with a matching result record in the duel log"


def transcript_history(d: dict) -> dict:
    """A duel's price paths rebuilt from its FINAL server transcript (duel_field_read's shape input): the rival's
    priced messages (consecutive repeats of one offer collapsed) and ours. Complete by construction, unlike the bot
    log, which can miss lines."""
    import duel as dl
    rival = []
    for m in _priced(dl.rival_msgs(d)):
        key = (m.get("tick"), m.get("price"), m.get("days"))
        if not rival or rival[-1][:3] != key:
            rival.append((*key, ""))
    ours = [(m.get("tick"), m.get("price"), m.get("days")) for m in _priced(
        [m for m in d.get("messages") or [] if isinstance(m, dict) and m.get("from") == "you"])]
    return {"rival": rival, "ours": ours}


FACTORY_FLAGS = {"duel_ticks", "late_poll"}   # the factory's command line sets these; flags win over the JSON


def _same(x, y) -> bool:
    if isinstance(x, (list, tuple)) and isinstance(y, (list, tuple)):
        return len(x) == len(y) and all(_same(a, b) for a, b in zip(x, y))
    if _finite(x) and _finite(y):
        return abs(float(x) - float(y)) <= 1e-9
    return x == y


def deployed_check(base: dict, log_rows: list, ids: set) -> tuple:
    """(ok, why): the baseline file's values equal what the duel bot actually ran in this wave: every run_start of
    the runs that logged events for these duels. Keys the factory sets on the command line are skipped."""
    runs = {r.get("run") for r in log_rows if r.get("duel") in ids and r.get("run")}
    starts = [r for r in log_rows if r.get("event") == "run_start" and r.get("run") in runs]
    if not starts:
        return False, "no run_start line for the runs that played this wave: cannot tell what the bot ran"
    diffs, compared, unlogged = [], set(), set()
    for st in starts:
        for k, v in base.items():
            if k in FACTORY_FLAGS:
                continue
            if k not in st:
                unlogged.add(k)
                continue
            compared.add(k)
            if not _same(st[k], v):
                diffs.append(f"{k}: file {v} vs run {st[k]} (run {st.get('run')})")
    if diffs:
        return False, "the baseline file is not what the bot ran: " + "; ".join(diffs[:6])
    if not compared:
        return False, "no baseline value appears in the run_start lines"
    return True, (f"{len(compared)} baseline values match the run_start of {len(starts)} run(s)"
                  + (f"; not logged: {sorted(unlogged)}" if unlogged else ""))


AFTER_MARGIN = 60   # ticks: a score snapshot later than this after the wave may already hold the next wave's points


def realised_per_duel(score_rows: list, t0: int, t1: int, n: int) -> tuple:
    """(duel_points gained over the wave / n, why): the last score row before tick t0 against the first at or after t1,
    which must come within AFTER_MARGIN ticks of t1 (a later one may include the next wave).
    duel_points is read as the sum of per-duel scores in the arena's unit (share of the pie x decay^rounds): Duels I
    gave 16.24 over 34 duels."""
    before = [r for r in score_rows if isinstance(r.get("tick"), int) and r["tick"] < t0]
    after = [r for r in score_rows if isinstance(r.get("tick"), int) and t1 <= r["tick"] <= t1 + AFTER_MARGIN]
    dp = (lambda r: (r.get("score") or {}).get("duel_points"))
    if not before or not after or not _finite(dp(before[-1])) or not _finite(dp(after[0])) or n <= 0:
        return None, f"no score snapshot before the wave and within {AFTER_MARGIN} ticks after it"
    return (dp(after[0]) - dp(before[-1])) / n, f"duel_points {dp(before[-1])} (tick {before[-1]['tick']}) -> " \
                                                f"{dp(after[0])} (tick {after[0]['tick']})"


def matrix_md_value(text: str, world: str = "mix: likely field", mode: str = "robust"):
    """The first policy column of a duel_matrix markdown row, or None."""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == world and cells[1] == mode:
            try:
                return float(cells[2].split()[0])
            except ValueError:
                return None
    return None


def predicted_per_duel(a, base_path: Path | None) -> tuple:
    """(predicted score per duel, deal rate or None, source): WP1's docs/duel-lab/duels3-matrix.md (likely field,
    robust, first column) when it exists, else one arena run of the deployed params on the likely field."""
    md = ROOT / "docs/duel-lab/duels3-matrix.md"
    if md.exists():
        v = matrix_md_value(md.read_text())
        if v is not None:
            return v, None, "docs/duel-lab/duels3-matrix.md (likely field, robust)"
    if base_path is None or a.predict_sessions <= 0:
        return None, None, "no prediction (no duels3-matrix.md; arena run off)"
    import duel_arena as arena
    saved = (arena.PAIR_SEEN, arena.ARENA_DAYS)
    arena.PAIR_SEEN, arena.ARENA_DAYS = 0.0, ""
    try:
        w = arena.FIELD_WEIGHTS
        res = arena.evaluate(json.loads(base_path.read_text()), range(980000, 980000 + a.predict_sessions),
                             a.session, kinds=[k for k in arena.KINDS if w.get(k, 0) > 0], weights=w)
    finally:
        arena.PAIR_SEEN, arena.ARENA_DAYS = saved
    st = arena.summary(res)["all"]
    return st["mean"], st["deal_rate"], f"arena, {base_path.name}, likely field, robust, {a.predict_sessions} sessions"


def cmd_duels(a, events) -> tuple:
    logs = Path(a.logs)
    files = duel_files(logs / "duels", a.session)
    rows = [classify_duel(d) for d in files]
    if not rows:
        return (f"duels session {a.session}: pending / insufficient data: no duel files (server session "
                f"{a.session + DUEL_SESSION_OFFSET})"), [], 0, {}
    ids = {r["duel"] for r in rows}
    log = logs / "duel" / f"{a.date or time.strftime('%Y-%m-%d')}.jsonl"
    raw_log = read_jsonl(log)
    expected = EXPECTED_DUELS.get(a.session, len(rows))
    complete, cwhy = completeness(rows, terminal_records(raw_log), expected)
    s = duel_summary(rows)
    doc = ROOT / "docs/duel-lab/duels3-params.md"
    doc_text = doc.read_text() if doc.exists() else ""
    hits = lever_hits(rows, doc_text)
    tick = max((d.get("deadline_tick") or 0 for d in files), default=0)
    lines = [("complete: " if complete else "PARTIAL: ") + cwhy,
             f"{s['n']} duels, {s['deals']} deals, our surplus {s['surplus']} P; "
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
    extra = {"summary": s, "weights": {}, "hits": [list(h[:5]) for h in hits], "complete": complete}
    if not complete:
        lines.append("=> no field refit, no prediction check and no params recommendation on a partial wave "
                     f"(missing: {cwhy}): rerun when it is complete")
        return (f"duels session {a.session}: PARTIAL ({cwhy}): {s['deals']} deals so far; no params recommendation",
                lines, tick, extra)
    weights = field_weights({d["duel"]: transcript_history(d) for d in files}, {r["duel"]: r["status"] for r in rows})
    extra["weights"] = weights
    lines.append("field refit (duel_field_read shapes of the final transcripts -> arena kinds): " + json.dumps(weights))
    verdict = f"duels session {a.session}: {s['deals']}/{s['n']} deals, {s['surplus']} P"
    # the pitch line: what the lab predicted per duel against what the live wave gave
    base_path = None
    try:
        base_path = base_params_path(a)
    except SystemExit as e:
        lines.append(f"baseline: {e}")
    pred, pred_rate, psrc = predicted_per_duel(a, base_path)
    t1 = tick
    t0 = min((d.get("deadline_tick") or t1 for d in files), default=t1) - SESSION_TICKS.get(a.session, 12)
    real, rsrc = realised_per_duel(read_jsonl(logs / "score.jsonl"), t0, t1, expected)
    extra.update(predicted=pred, realised=real)
    lines.append("pitch: the lab predicted " + (f"{pred:.3f} per duel" if pred is not None else "n/a")
                 + (f" (deal rate {pred_rate:.0%})" if pred_rate is not None else "")
                 + "; the live wave gave " + (f"{real:.3f} per duel" if real is not None else "n/a")
                 + f" (deal rate {s['deals'] / max(1, s['n']):.0%}), field seen {json.dumps(weights)}"
                 + f" [prediction: {psrc}; live: {rsrc}]")
    if a.matrix:
        if not weights:
            lines.append("matrix skipped: no field to refit")
        elif base_path is None:
            lines.append("matrix skipped: no deployed baseline params")
            verdict += "; Final params: no verdict (baseline missing)"
        else:
            base = json.loads(base_path.read_text())
            ok, dwhy = deployed_check(base, raw_log, ids)
            lines.append(f"baseline {base_path.name} vs what the bot ran: {dwhy}")
            if not ok:
                lines.append("=> matrix stopped: the baseline is not proven to be what the duel bot runs")
                verdict += "; Final params: no verdict (baseline does not match the bot's run_start)"
            else:
                keep = contextlib.nullcontext(str(Path(a.out) / f"matrix-s{a.session}"))
                with (keep if a.write else tempfile.TemporaryDirectory(prefix="analyst-")) as out_dir:
                    verdict = run_and_pick(a, base_path, base, hits, weights, Path(out_dir), lines, verdict, extra)
    return verdict, lines, tick, extra


def run_and_pick(a, base_path: Path, base: dict, hits: list, weights: dict, out_dir: Path, lines: list, verdict: str,
                 extra: dict) -> str:
    """Candidates, matrix, 2 SE pick; writes docs/duel-lab/duel-params-final.json only with --write and a winner."""
    import duel_matrix as dm
    out_dir.mkdir(parents=True, exist_ok=True)
    mix_file = out_dir / "field.json"
    mix_file.write_text(json.dumps(weights, indent=1) + "\n")
    extra_c = {}
    for spec in a.candidate:
        n, _, f = spec.partition("=")
        extra_c[n] = json.loads(Path(f).expanduser().read_text())
    cands = candidates_from(base, hits, extra_c)
    if not cands:
        lines.append("matrix: no candidate (no lever has hits, no --candidate): keep")
        return verdict + "; Final params: keep"
    mix_name = f"Duels {'I' * a.session} refit"     # never a named mix's label (main has "Duels II field")
    cells = run_matrix(a, base_path, cands, mix_file, mix_name, out_dir)
    guards = [f"mix: {mix_name}", f"d1: {mix_name}"] + [f"mix: {m}" for m in dm.MIXES]
    win, why = pick_winner(cells, "base", f"mix: {mix_name}", guards)
    lines.append(f"matrix (arena session {a.matrix_session}, {a.sessions} sessions, base {base_path.name}): "
                 + (str(out_dir / "matrix.md") if a.write else "not kept (--no-write)"))
    lines += [f"  {w}" for w in why]
    extra["matrix_why"] = why
    if not win:
        lines.append("=> keep the Duels III params for the Final")
        return verdict + "; Final params: keep"
    new = cands[win]
    target = ROOT / "docs/duel-lab/duel-params-final.json"
    if a.write:
        target.write_text(json.dumps(new, indent=2) + "\n")
    lines.append(f"=> Final params delta {params_delta(base, new)}: "
                 + (f"written to {target.relative_to(ROOT)}" if a.write else "not written (--no-write)")
                 + " (applied only by a human: docs/plans/sunday-analyst.md, 'Applying a change')")
    return verdict + f"; Final params: CHANGE {params_delta(base, new)}"


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
    """{"held": {ref: value}} from logs/state/me.json: the value of the copy we hold NOW (display only: it is not the
    value in force at an earlier settlement)."""
    held = {}
    try:
        for x in json.loads((logs / "state" / "me.json").read_text()).get("assets") or []:
            if x.get("ref") and isinstance(x.get("your_value"), (int, float)):
                held.setdefault(x["ref"], x["your_value"])
    except (OSError, ValueError):
        pass
    return {"held": held}


def bot_threads(logs: Path) -> list:
    """Our dealer bots' finished deals, one per thread: {dealer, thread, ref, side, value, price, ts}. The value is
    the one the bot opened THAT thread with (its valuation in force for that trade); the price is the thread's result."""
    out = []
    for dealer in DEALER_LEVEL:
        d = logs / dealer
        opened, done = {}, {}
        for f in sorted(d.glob("*.jsonl")) if d.exists() else []:
            for r in read_jsonl(f):
                th = r.get("thread")
                if r.get("event") == "open" and th is not None and r.get("item") and \
                        isinstance(r.get("value"), (int, float)):
                    opened[th] = r
                elif r.get("event") == "result" and th is not None and r.get("status") == "deal":
                    done[th] = r
        for th, res in done.items():
            o = opened.get(th)
            if o is not None:
                out.append({"dealer": dealer, "thread": th, "ref": o["item"], "side": o.get("side"),
                            "value": o["value"], "price": res.get("price"), "ts": str(res.get("ts", ""))})
    return sorted(out, key=lambda t: t["ts"])


def bind_values(deals: list, threads: list) -> list:
    """Each settlement gets the value of the bot thread that made it: same dealer, card, side and price, matched one
    to one in order (the n-th such settlement to the n-th such thread result). No matching thread: value None and
    provenance None (a hand trade, an old valuation of another copy, or a log not pushed): unverified."""
    pool = collections.defaultdict(list)
    for t in threads:
        pool[(t["dealer"], t["ref"], t["side"], t["price"])].append(t)
    out = []
    for d in sorted(deals, key=lambda x: (x.get("tick") or 0)):
        q = pool.get((d["dealer"], d["ref"], d["side"], d["price"]))
        t = q.pop(0) if q else None
        out.append(dict(d, value=t["value"] if t else None, provenance=f"thread {t['thread']}" if t else None))
    return out


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


def ladder_slots(deals: list, held: dict | None = None) -> dict:
    """{level: {"deals", "best", "zero", "unverified"}} over deals from bind_values. A deal's gain at our private value:
    buy = value - price, sell = price - value. Only a deal bound to the bot thread that made it has a value in force at
    its settlement: with gain >= 0 it is a CONFIRMED slot ("best", top 3 by gain), below 0 it scored 0 (the value gate,
    "zero"). Anything else is "unverified": never counted as filled, its level stays on the to-do list. held: the
    value of the copy we hold now, shown for unverified deals only."""
    held = held or {}
    out = {lv: {"deals": [], "best": [], "zero": [], "unverified": []} for lv in sorted(set(DEALER_LEVEL.values()))}
    for d in deals:
        v = d.get("value") if d.get("provenance") else None
        d = dict(d, value=v, held=held.get(d["ref"]), gain=None if v is None or d["price"] is None
                 else round((v - d["price"]) if d["side"] == "buy" else (d["price"] - v), 1))
        s = out[d["level"]]
        s["deals"].append(d)
        if d["gain"] is None:
            s["unverified"].append(d)
        elif d["gain"] < 0:
            s["zero"].append(d)
    for lv, s in out.items():
        ok = [d for d in s["deals"] if d not in s["zero"] and d not in s["unverified"]]
        s["best"] = sorted(ok, key=lambda d: -d["gain"])[:SLOTS_PER_LEVEL]
    return out


def cmd_ladder(a, events) -> tuple:
    start, no, name = round_start(events)
    deals = dealer_deals(events, start)
    slots = ladder_slots(bind_values(deals, bot_threads(Path(a.logs))), our_values(Path(a.logs))["held"])
    filled = sum(len(s["best"]) for s in slots.values())
    unver = sum(len(s["unverified"]) for s in slots.values())
    lines = [f"round {no} {name!s} since tick {start}: {len(deals)} dealer deals of ours"]
    names = {v: k for k, v in DEALER_LEVEL.items()}
    todo = []
    for lv, s in slots.items():
        got = len(s["best"])
        lines.append(f"  L{lv} {names[lv]}: {got}/{SLOTS_PER_LEVEL} confirmed slots"
                     + ("".join(f"; {d['side']} {d['ref']} @ {d['price']} (value {_f(d['value'])} from "
                                f"{d['provenance']}, gain {_f(d['gain'])})" for d in s["best"])))
        for d in s["zero"]:
            lines.append(f"    scored 0 (wrong side of value): tick {d['tick']} {d['side']} {d['ref']} @ {d['price']}"
                         f" vs value {_f(d['value'])}")
        for d in s["unverified"]:
            lines.append(f"    unverified: tick {d['tick']} {d['side']} {d['ref']} @ {d['price']} (no bot thread made "
                         f"this trade, so no value in force at the settlement; the copy we hold now is worth "
                         f"{_f(d['held'])}): not counted")
        if got < SLOTS_PER_LEVEL:
            todo.append(f"{SLOTS_PER_LEVEL - got} x L{lv} {names[lv]}"
                        + (f" ({len(s['unverified'])} unverified deal(s) to check)" if s["unverified"] else ""))
    lines.append("left before 14:00: " + (", ".join(todo) if todo else "nothing: 15/15 confirmed")
                 + " (higher levels weigh more; every deal must clear our value)")
    zero = sum(len(s["zero"]) for s in slots.values())
    return (f"ladder: {filled}/15 slots confirmed, {unver} unverified, {zero} deal(s) scored 0", lines,
            last_tick(events), {"filled": filled, "zero": zero, "unverified": unver, "todo": todo})


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

DATA_BRANCHES = ("origin/mini/logs", "origin/main")   # where the Mini pushes bot logs (tools/logs_push.py), then main


def _git(path: Path, *args) -> str:
    import subprocess
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ""


def data_source(logs: Path) -> str:
    """Which branch and commit the --logs checkout holds: "origin/mini/logs, commit 2026-10-04 10:02:11 +0200
    (abc1234)". Read-only git queries; a directory outside git says so."""
    logs = Path(logs).expanduser()
    if not logs.exists() or not _git(logs, "rev-parse", "--is-inside-work-tree"):
        return f"not a git checkout ({logs})"
    refs = _git(logs, "branch", "-r", "--points-at", "HEAD").split()
    branch = next((b for b in DATA_BRANCHES if b in refs), refs[0] if refs else "detached, no remote branch at HEAD")
    return f"{branch}, commit {_git(logs, 'log', '-1', '--format=%ci')} ({_git(logs, 'rev-parse', '--short', 'HEAD')})"


def write_report(out: Path, trigger: str, tick: int, verdict: str, lines: list, source: str = "") -> Path:
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{trigger}-{tick}.md"
    body = [f"# {trigger} at tick {tick}", "", f"_{time.strftime('%Y-%m-%d %H:%M:%S')} local, tools/analyst.py_", "",
            f"_data: {source or 'unknown'}_", "", f"**{verdict}**", ""] + [f"- {l}" if not l.startswith("  ") else f"  - {l.strip()}" for l in lines]
    f.write_text("\n".join(body) + "\n")
    rebuild_latest(out, f)
    return f


def rebuild_latest(out: Path, newest: Path | None = None, write: bool = True) -> str:
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
    if newest is not None:
        src = next((l.strip("_")[6:] for l in newest.read_text().splitlines() if l.startswith("_data: ")), "unknown")
        rows += [f"Logs from: {src} (newest report {newest.name})", ""]
    rows += ["| trigger | report | data | verdict |", "|---|---|---|---|"]
    for trig, f in sorted(per.items()):
        text = f.read_text().splitlines()
        verdict = next((l.strip("*") for l in text if l.startswith("**")), "")
        src = next((l.strip("_")[6:] for l in text if l.startswith("_data: ")), "unknown")
        rows.append(f"| {trig} | {f.name} | {src.replace('|', '/')} | {verdict.replace('|', '/')} |")
    if newest is not None:
        rows += ["", "---", "", newest.read_text()]
    text = "\n".join(rows) + "\n"
    if write:
        (out / "LATEST.md").write_text(text)
    return text


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
    ap.add_argument("--ours-seeds", type=int, default=50, help="bench: paired synthetic seeds for ours vs stall "
                    "when expiries differ (0: none, so never a switch)")
    ap.add_argument("--predict-sessions", type=int, default=60, help="duels: arena sessions for the predicted "
                    "per-duel score when docs/duel-lab/duels3-matrix.md is absent (0: skip)")
    ap.add_argument("--window", type=int, default=40, help="market: ticks an announcement/outreach counts before")
    ap.add_argument("--since-tick", type=int, default=None, help="score: delta against this tick, not the last run")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "latest":
        if not a.write:
            print(rebuild_latest(Path(a.out), write=False) if Path(a.out).is_dir() else "(no reports yet)")
            return 0
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
        print(f"-> {write_report(Path(a.out), trig, tick, verdict, lines, data_source(Path(a.logs)))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
