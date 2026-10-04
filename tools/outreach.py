"""Open Bazaar outreach: tell the one team that can complete a match about it, in a team thread. Plan by default.

The matchmaker (tools/matchmaker.py) finds who needs which card and the one action that completes it. A team's bot may
never read the public feed; a thread reaches it directly. Each message names one live offer (or, for a need that is
only inferred, says so and gives the v20 bid) and the exact call; nothing else, no ask in return, no pressure.

Who gets the message, per match (from the matchmaker's output, read as it is, never recomputed):
  tier 1 (a live bid or swap, a holder we can name)   the holder: accepting that offer is the action;
  tier 3 (a live ask, a team that appears to need it) that team: accepting the ask is the action;
  tier 4 (an inferred need, no live offer)            that team: the v20 bid our broker would cross;
  tier 2 (a live want, no holder we can name)          nobody: there is no one to tell.
A match whose offer stands off our venue (El Rastro, another team's) keeps its action: the counterparty is there, so a
v20 order would not cross. It gets one short line more, while it fits in MAX_CHARS: next time, the same trade on
La Celestina costs no fee. A message never names a venue as a condition of anything.

--pitch (off by default): the slots a run has left after the matches go to active teams that were never pitched, one
message each, once per game: La Celestina's fee next to El Rastro's, the exact v20 orders, and what our broker crosses
(agent/broker.py crosses teams' public v20 offers card by card on every book it reads, with any --policy). It never
names a card, a price or anything about Team 3's album. --pitch-reciprocity adds one line about Team 3's own buying:
enable it ONLY while the trade desk runs without --no-team-venues (it is false otherwise, and a false line is a bad
faith flag); it states a standing price rule, never "trade on ours and we trade on yours".

Thread slots are scarce: a team holds at most 6 open threads and the dealer bots need them on Sunday. So `run` opens
ONE thread at a time, sends ONE message, and closes it at once (POST /api/threads/{id}/close); before opening it
reads our open threads (GET /api/me/threads?status=open) and opens only if RESERVE_SLOTS stay free once it is open.
A thread it could not close stops the run and is closed first next time (logs/state/outreach.json "unclosed").
Before every send: a fresh Market Test status (announce.Gate.known), no silence now or within NEAR_SILENCE_TICKS
ticks, and the named offer re-read in its venue's current book (announce.still_live). No write at all inside a
silence, the close included. At most one thread per team per day, never the same match twice. Any refusal stops.
Replies are never read: the thread is closed before any could arrive, and game text is data anyway.

    python3 tools/outreach.py plan                          # keyless: every message it would send, the slot budget
    python3 tools/outreach.py run --yes --max-teams 1       # with the team key: one thread, one message, closed

`run` takes the team key from BAZAAR_KEY or the repo's .env (as the other bots do); it is never printed or logged.
Every send is logged through agent/runlog.py (logs/outreach/<date>.jsonl): team, match, thread id, text, result.
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
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

US = "t03"
VENUE = "v20"
URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
MATCHES = ROOT / "logs" / "matchmaker" / "latest.json"
MATCHES_MAX_AGE_S = 900
STATE = ROOT / "logs" / "state" / "outreach.json"
MAX_THREADS = 6           # kit/RULES.md: a team holds at most six conversations
RESERVE_SLOTS = 3         # free thread slots left for the dealer bots AFTER our thread is open
NEAR_SILENCE_TICKS = 2    # no thread is opened within this many ticks of a Market Test silence
THREAD_VENUE = "rastro"   # the thread is only a message channel; nothing is traded in it
GAP_S = 20                # run: seconds between two teams (more than one Sunday tick)
NAME = "Open Bazaar · who needs which card"
ACCOUNT_DIR = ROOT / "logs" / "state"   # --exclude-from default: our account snapshots (me*.json, the highest tick wins)
MIN_P = 0.8               # an inferred need is messaged only from this p_missing (announce.MIN_P_ANNOUNCE)
MAX_CHARS = 1200          # the server keeps 1,200 characters of a message (announce.MAX_CHARS)
RASTRO_FEE = "5 % + 1 P a card"   # El Rastro's fee, paid by the taker (kit/RULES.md)
V20_LINE = (" Next time, the same trade costs no fee on La Celestina (v20, 0 % fee; El Rastro charges the taker "
            + RASTRO_FEE + "): post your offer with \"venue\": \"v20\" and our broker crosses it with an opposite "
            "offer for the same card from another team when the prices meet.")
PITCH_KEY = "pitch:"      # state["keys"] entry of a team pitched once (never again in the game)
PITCH_ASK = '{"venue": "v20", "give": {"assets": [<your asset id>]}, "want": {"cash": <your price>}}'
PITCH_BID = '{"venue": "v20", "give": {"cash": <your price>}, "want": {"cards": ["<card ref>"]}}'
RECIPROCITY_LINE = (" Team 3's own buying desk reads team venues too and takes a buy where its all-in cost (price + "
                    "fee) is lowest, so a fair ask on your venue is weighed exactly like one on El Rastro.")


def _team(t) -> bool:
    return isinstance(t, str) and t[:1] == "t" and t[1:].isdigit() and t != US


def recipient(m: dict) -> str | None:
    """The one team that can complete this match by acting, or None."""
    a = m.get("action") if isinstance(m.get("action"), dict) else None
    tier = m.get("tier")
    if tier == 1 and a and a.get("side") in ("bid", "swap"):
        who = [t for t in a.get("who") or [] if _team(t) and t != a.get("maker")]
        return who[0] if who else None
    if tier in (3, 4) and _team(m.get("team")):
        return m["team"]
    return None


def message(m: dict, to: str) -> str:
    """The text for `to`: the offer, the one call, and how sure we are. Public data only, no ask in return."""
    card = m["card"] + (f" ({m['card_name']})" if m.get("card_name") else "")
    page = m.get("set_name") or m.get("set") or "its"
    a = m.get("action") if isinstance(m.get("action"), dict) else None
    head = f"{NAME}, from Team 3's La Celestina (public game data only, no reply needed): "
    tail = " Check your own value first. We will not message you again today."
    if a:
        where = "La Celestina (v20, 0 % fee)" if a.get("venue") == VENUE else (
            "El Rastro" if a.get("venue") in (None, "rastro") else a.get("venue"))
        until = f", open until tick {a['expires_tick']}" if isinstance(a.get("expires_tick"), int) else ""
        maker = a.get("maker_name") or a.get("maker")
        extra = V20_LINE if a.get("venue") != VENUE else ""
        if a.get("side") == "ask":
            body = (head + f"{maker} sells {card} for {a['price']} P on {where}: offer #{a['offer']}{until}. You appear "
                    f"to be missing it for the {page} page (inferred from public trades, may be wrong). To take it: "
                    f"POST /api/offers/{a['offer']}/accept.")
            return fit(body, extra, tail)
        what = (f"{maker} bids {a['price']} P for {card}" if a.get("side") == "bid"
                else f"{maker} gives {a.get('gives')} for any {card} (a swap: accept it directly)")
        held = next((h.get("as_of") for h in m.get("holders") or [] if isinstance(h, dict) and h.get("team") == to), None)
        seen = (f"Public trades showed you holding a copy at tick {held} (reconstructed, may have changed)."
                if isinstance(held, int) else "If you hold a copy:")
        body = (head + f"{what} on {where}: offer #{a['offer']}{until}. {seen} To take it: "
                f"POST /api/offers/{a['offer']}/accept with {{\"assets\": [<your {m['card']} asset id>]}}.")
        return fit(body, extra if a.get("side") != "swap" else "", tail)
    bid = ((m.get("proposal") or {}).get("buyer") or {}).get("post") or {}
    order = json.dumps({k: v for k, v in bid.items() if k != "expires_in_ticks"})
    from announce import BROKER_TERMS
    return (head + f"you appear to be missing {card} for the {page} page (inferred from public trades, may be wrong). "
            f"A bid on La Celestina (v20, 0 % fee; El Rastro charges the taker {RASTRO_FEE}): POST /api/offers "
            f"{order}; there {BROKER_TERMS}." + tail)


def fit(body: str, extra: str, tail: str) -> str:
    """body + extra + tail when it fits in MAX_CHARS, else body + tail: the optional line is dropped whole, never the
    offer or its call cut."""
    return body + extra + tail if len(body) + len(extra) + len(tail) <= MAX_CHARS else body + tail


def pitch_message(reciprocity: bool = False) -> str:
    """The one-time venue pitch: our fee next to El Rastro's, the exact v20 orders, what our broker crosses. No card,
    no price, nothing about Team 3's album, no ask in return."""
    from announce import BROKER_TERMS
    text = (f"{NAME}, from Team 3 (public game data only, no reply needed): La Celestina (v20) is a board venue with "
            f"0 % fee and 0 P a card; El Rastro charges the taker {RASTRO_FEE}. There {BROKER_TERMS}, on every book it "
            f"reads. To sell a spare there: POST /api/offers {PITCH_ASK}. To bid for a card you need: POST /api/offers "
            f"{PITCH_BID}. Only trades you want at your own price: check your own value first."
            + (RECIPROCITY_LINE if reciprocity else "") + " We will not send this again.")
    return text[:MAX_CHARS]


def pitch_targets(doc: dict, state: dict, day: str, n: int, taken=(), reciprocity: bool = False) -> list:
    """[(team, pitch, text)] for up to n active teams: never Team 3, never a team messaged today or taken by this run,
    never a team pitched before (once per game). Most recent mover first."""
    teams = (doc or {}).get("teams") if isinstance((doc or {}).get("teams"), dict) else {}
    done = set((state.get("teams") or {}).get(day, [])) | set(taken)
    keys = set(state.get("keys") or [])
    rows = [(t, v) for t, v in teams.items() if _team(t) and isinstance(v, dict) and v.get("active") is not False
            and t not in done and PITCH_KEY + t not in keys]
    rows.sort(key=lambda r: (-(r[1].get("last_move_tick") if isinstance(r[1].get("last_move_tick"), int) else -1), r[0]))
    text = pitch_message(reciprocity)
    return [(t, {"pitch": True, "team": t, "card": None, "tier": "pitch", "action": None}, text)
            for t, _ in rows[:max(0, n)]]


def key_of(m: dict) -> str:
    if m.get("pitch"):
        return PITCH_KEY + str(m.get("team"))
    a = m.get("action") or {}
    return f"{m.get('team')}:{m.get('card')}:{a.get('offer') or VENUE}"


def load_state(path: Path | None = None) -> dict:
    try:
        s = json.loads((path or STATE).read_text())
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)


def confident(m: dict, teams: dict, min_p: float = MIN_P) -> bool:
    """A live want always; an inference (tier 3-4) only at p_missing >= min_p, from a deck that fits the leaderboard."""
    if m.get("inferred") is False and (m.get("tier") or 0) < 3:
        return True
    pm = m.get("p_missing")
    real = isinstance(pm, (int, float)) and not isinstance(pm, bool) and math.isfinite(pm) and 0 <= pm <= 1
    return real and pm >= min_p and (teams.get(m.get("team")) or {}).get("consistent") is not False


def targets(doc: dict, state: dict, day: str, max_teams: int, exclude=(), min_p: float = MIN_P) -> list:
    """[(team, match, text)] in the matchmaker's order: one per team, never a team messaged today, never a match sent
    before, never Team 3, never a card in `exclude` (the card, or the one a swap gives), never an unconfident
    inference (confident())."""
    skip = exclude if hasattr(exclude, "allow") else set(exclude or ())   # a matchmaker.Exclusion keeps its rule
    teams = (doc or {}).get("teams") if isinstance((doc or {}).get("teams"), dict) else {}
    done_teams = set((state.get("teams") or {}).get(day, []))
    done_keys = set(state.get("keys") or [])
    out, seen = [], set()
    for m in (doc or {}).get("matches") or []:
        if not isinstance(m, dict) or not isinstance(m.get("card"), str) or m["card"] in skip:
            continue
        if (isinstance(m.get("action"), dict) and m["action"].get("gives") in skip) or not confident(m, teams, min_p):
            continue
        if len(out) >= max_teams:
            break
        to = recipient(m)
        if to is None or to in done_teams or to in seen or key_of(m) in done_keys:
            continue
        if m.get("tier") == 4 and not ((m.get("proposal") or {}).get("buyer") or {}).get("post"):
            continue
        seen.add(to)
        out.append((to, m, message(m, to)))
    return out


def load_matches(path: Path, now: float | None = None) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    at = doc.get("generated_at") if isinstance(doc, dict) else None
    if not isinstance(at, (int, float)) or (now if now is not None else time.time()) - at > MATCHES_MAX_AGE_S:
        raise LookupError("the matchmaker output is missing its time or is stale")
    return doc


def team_key() -> str:
    """BAZAAR_KEY from the environment or the repo's .env. Returned, never printed."""
    key = os.environ.get("BAZAAR_KEY", "").strip()
    if not key:
        try:
            for line in (ROOT / ".env").read_text().splitlines():
                if line.strip().startswith("BAZAAR_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    if not key:
        raise SystemExit("no team key: set BAZAAR_KEY (never paste it into a chat)")
    return key


def open_count(client) -> int:
    body = client.my_threads(status="open") or {}
    rows = body.get("threads") if isinstance(body, dict) else body
    return len([t for t in rows or [] if isinstance(t, dict) and t.get("status", "open") == "open"])


def close_thread_safely(client, tid, log, gate=None) -> bool:
    """Close one of our threads, never inside a Market Test silence. True when it is closed."""
    if gate is not None and gate.quiet_end() is not None:
        log.event("close_deferred", thread=tid, reason="Market Test silence")
        return False
    try:
        client.close_thread(tid)
        log.event("close", thread=tid)
        return True
    except Exception as e:  # noqa: BLE001
        log.event("close_failed", thread=tid, reason=type(e).__name__)
        return False


def send_one(client, to: str, text: str, venue: str, log, gate=None) -> dict:
    """Open one thread with `to`, send one message, close it. Returns {"thread", "sent", "closed", "error"}. It opens
    only while RESERVE_SLOTS slots stay free once our thread is open. Any refusal stops here; the thread it opened is
    closed, except inside a Market Test silence (no write then): the caller records it and closes it first next time."""
    from bazaar_sdk import BazaarError
    out = {"thread": None, "sent": False, "closed": False, "error": None}
    try:
        if gate is not None:
            gate.check()
        free_after = MAX_THREADS - open_count(client) - 1
        if free_after < RESERVE_SLOTS:
            out["error"] = f"{free_after} thread slots would stay free: {RESERVE_SLOTS} are kept for the dealer bots"
            return out
        if gate is not None:
            gate.check()
        th = client.open_thread(to, venue=venue)
        out["thread"] = (th or {}).get("id")   # the SDK answers the thread itself (agent/abuela.py: th["id"])
        log.event("open", to=to, thread=out["thread"], venue=venue)
        if gate is not None:
            gate.check()
        client.say(out["thread"], text)
        out["sent"] = True
        log.event("say", to=to, thread=out["thread"], text=text)
    except BazaarError as e:
        out["error"] = f"{e.status} {e.code}"
        log.event("refused", to=to, thread=out["thread"], status=e.status, code=e.code)
    except Exception as e:  # noqa: BLE001 — Silenced or a network failure: stop, close what we opened
        out["error"] = type(e).__name__
        log.event("stopped", to=to, thread=out["thread"], reason=type(e).__name__)
    finally:
        if out["thread"] is not None:
            out["closed"] = close_thread_safely(client, out["thread"], log, gate)
            if not out["closed"] and not out["error"]:
                out["error"] = "the thread could not be closed"
    return out


def status_fresh(gate) -> bool:
    """A Market Test status read less than STATUS_MAX_AGE_S ago (announce.Gate.known), refreshed when it is not."""
    import announce
    if not gate.known():
        gate.refresh(announce.get_json)
    return gate.known()


def near_silence(gate, now: float, tick_s: float) -> bool:
    """A Market Test silence now or starting within NEAR_SILENCE_TICKS ticks."""
    return any(start - NEAR_SILENCE_TICKS * tick_s <= now < end for start, end in gate.windows)


def offer_stands(m: dict, get, gate=None) -> bool:
    """The named live offer, re-read in its venue's current book (announce.still_live), or True for a match that names
    no offer (an inferred need: the message carries a v20 bid, nothing to re-read). The silence gate is asked right
    before each of the two reads; Silenced propagates (the caller stops)."""
    import announce
    a = m.get("action")
    if not isinstance(a, dict):
        return True
    venue = a.get("venue") or "rastro"
    try:
        if gate is not None:
            gate.check()
        book = [dict(o, venue=venue) for o in get(f"{URL}/api/venues/{venue}/offers").get("offers") or []]
        if gate is not None:
            gate.check()
        tick = get(f"{URL}/api/clock").get("tick")
    except announce.Silenced:
        raise
    except Exception:  # noqa: BLE001
        return False
    return announce.still_live(a, m["card"], {venue: book}, tick if isinstance(tick, int) else None)


def recover(client, state: dict, state_path: Path, log, gate) -> str | None:
    """Close every thread an earlier run left open, before anything else and whatever the matches say. None when
    none is left open; else why it stopped (nothing else may be sent then)."""
    for tid in list(state.get("unclosed") or []):
        if not close_thread_safely(client, tid, log, gate):
            return f"thread {tid} from an earlier run is still open: nothing sent"
        state["unclosed"].remove(tid)
        save_state(state, state_path)
    return None


def lacking(args, doc: dict, fallback) -> set:
    """The page cards we lack, from our freshest TRUSTED account snapshot (matchmaker.exclude_state, aged against the
    matchmaker's tick). Fails closed: without --exclude-from or a trusted file, every page card (plus `fallback`,
    which only ever adds). LookupError without a catalog (nothing is sent then). Printed as a count, never the cards."""
    import matchmaker      # noqa: E402  (keyless)
    import value_inference  # noqa: E402
    try:
        cat = value_inference.catalog()
    except (OSError, ValueError) as e:
        raise LookupError(f"no catalog ({type(e).__name__}): no message without the list of cards we lack")
    tick = (doc or {}).get("tick")
    st = matchmaker.exclude_state([x for x in (args.exclude_from or "").split(",") if x.strip()], cat, fallback,
                                  args.exclude_max_age_min,
                                  now_tick=tick if isinstance(tick, int) and not isinstance(tick, bool) else None)
    print(st["line"])
    return st["cards"]          # a matchmaker.Exclusion: untrusted -> only epic and legendary cards pass


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Open Bazaar outreach: one thread, one message, closed. Plan by default.")
    ap.add_argument("cmd", nargs="?", default="plan", choices=["plan", "run"])
    ap.add_argument("--yes", action="store_true", help="run only: really send")
    ap.add_argument("--matches", default=str(MATCHES))
    ap.add_argument("--max-teams", type=int, default=1, help="teams messaged in this run (one thread at a time); "
                                                             "0 = run does nothing at all")
    ap.add_argument("--venue", default=THREAD_VENUE, help="the venue the thread is opened on (a channel only)")
    ap.add_argument("--exclude", default=None, help="comma list of cards never named, added to --exclude-from's")
    ap.add_argument("--exclude-from", default=str(ACCOUNT_DIR),
                    help="our account snapshots (files, or a directory of me*.json; the highest tick wins): every page "
                         "card we lack is never named; missing/foreign -> announce.MISSING, stale -> both")
    ap.add_argument("--exclude-max-age-min", type=float, default=60.0)
    ap.add_argument("--min-p", type=float, default=MIN_P, help="lowest p_missing at which an inferred need is messaged")
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--pitch", action="store_true",
                    help="fill the slots left after the matches with the one-time La Celestina pitch (active teams)")
    ap.add_argument("--pitch-reciprocity", action="store_true",
                    help="add the line about Team 3's own buying to the pitch: ONLY while the trade desk runs "
                         "without --no-team-venues (the line is false otherwise)")
    args = ap.parse_args(argv)
    if args.cmd == "run" and not args.yes:
        ap.error("run opens threads with other teams: add --yes")
    if args.pitch_reciprocity and not args.pitch:
        ap.error("--pitch-reciprocity only changes the --pitch message: add --pitch")
    import announce   # noqa: E402  (the Market Test gate and the list of cards Team 3 lacks)
    exclude = tuple(x.strip() for x in (args.exclude or "").split(",") if x.strip())
    day = time.strftime("%Y-%m-%d")
    state_path = Path(args.state)
    state = load_state(state_path)
    if args.cmd == "run" and args.max_teams <= 0:
        print("--max-teams 0: nothing sent, nothing read")
        return
    session = {}

    def connect():
        """The key, the log and the gate, once, for run only."""
        if not session:
            from bazaar_sdk import Bazaar
            from runlog import RunLog
            session["log"] = RunLog("outreach")
            session["log"].start(unclosed=list(state.get("unclosed") or []))
            session["client"] = Bazaar(URL, team_key(), timeout=10, wait_on_tick=False, retries=0)
            session["gate"] = announce.Gate()
        return session["client"], session["log"], session["gate"]

    def stop(reason: str, sent: int = 0) -> None:
        print(f"stopped: {reason}")
        if session:
            session["log"].event("stopped", reason=reason)
            session["log"].end(sent=sent)

    if args.cmd == "run" and state.get("unclosed"):   # recovery first, whatever the matches say
        client, log, gate = connect()
        if not status_fresh(gate) or gate.quiet_end() is not None:
            return stop("Market Test now or status unknown: an earlier thread stays open, nothing sent")
        why = recover(client, state, state_path, log, gate)
        if why:
            return stop(why)
    try:
        doc = load_matches(Path(args.matches))
    except (OSError, ValueError, LookupError) as e:
        print(f"nothing to send: {type(e).__name__}: {e}")
        return stop("no fresh matches") if session else None
    try:
        exclude = lacking(args, doc, announce.MISSING) | set(exclude)
    except LookupError as e:
        print(f"nothing to send: {e}")
        return stop("no catalog") if session else None
    plan = targets(doc, state, day, max(0, args.max_teams), exclude, args.min_p)
    if args.pitch:
        plan += pitch_targets(doc, state, day, max(0, args.max_teams) - len(plan), [to for to, _, _ in plan],
                              args.pitch_reciprocity)
    print(f"{NAME} outreach, matchmaker tick {doc.get('tick')}: {len(plan)} message(s), one thread at a time.")
    print(f"slot budget: {MAX_THREADS} threads per team; each send holds 1 for a few seconds (open, one message, "
          f"close); run opens only while {RESERVE_SLOTS} stay free for the dealer bots once it is open. Already "
          f"messaged today: {', '.join((state.get('teams') or {}).get(day, [])) or 'nobody'}. Threads left open by an "
          f"earlier run: {', '.join(map(str, state.get('unclosed') or [])) or 'none'}.")
    for to, m, text in plan:
        print(f"\n-> {to} (tier {m.get('tier')}, {m.get('card')}, {len(text)} chars)")
        print(f"   POST {URL}/api/threads {json.dumps({'with': to, 'venue': args.venue})}")
        print(f"   POST {URL}/api/threads/<id>/messages {json.dumps({'text': text}, ensure_ascii=False)}")
        print(f"   POST {URL}/api/threads/<id>/close")
    if args.cmd == "plan":
        return
    if not plan:
        return stop("no match to send") if session else None
    client, log, gate = connect()
    log.event("plan", plan=[{"to": to, "card": m.get("card"), "tier": m.get("tier"), "key": key_of(m)}
                            for to, m, _ in plan])
    sent = 0
    try:
        if not status_fresh(gate) or gate.quiet_end() is not None:   # the silence check right before the read
            return stop("Market Test now or status unknown: nothing sent")
        tick_s = float(announce.get_json(f"{URL}/api/clock").get("tick_seconds") or 60.0)
    except announce.Silenced:
        return stop("Market Test silence")
    except Exception:  # noqa: BLE001
        tick_s = 60.0
    for i, (to, m, text) in enumerate(plan):
        if i:
            time.sleep(GAP_S)
        try:
            if not status_fresh(gate):
                return stop("Market Test status unknown or stale", sent)
            if near_silence(gate, time.time(), tick_s):
                return stop(f"a Market Test silence is on or starts within {NEAR_SILENCE_TICKS} ticks", sent)
            if not offer_stands(m, announce.get_json, gate):
                log.event("skipped", to=to, key=key_of(m), reason="the named offer no longer stands as it was")
                continue
        except announce.Silenced:
            return stop("Market Test silence", sent)
        res = send_one(client, to, text, args.venue, log, gate)
        if res["thread"] is not None and not res["closed"]:
            state.setdefault("unclosed", []).append(res["thread"])
            save_state(state, state_path)
        if res["sent"]:
            sent += 1
            state.setdefault("teams", {}).setdefault(day, []).append(to)
            state.setdefault("keys", []).append(key_of(m))
            save_state(state, state_path)
            log.event("sent", to=to, key=key_of(m), card=m.get("card"), tier=m.get("tier"),
                      offer=(m.get("action") or {}).get("offer"), thread=res["thread"], closed=res["closed"])
        if res["error"]:
            return stop(res["error"], sent)
    log.end(sent=sent)


if __name__ == "__main__":
    main()
