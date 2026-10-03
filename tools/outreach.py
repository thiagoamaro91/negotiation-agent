"""Open Bazaar outreach: tell the one team that can complete a match about it, in a team thread. Plan by default.

The matchmaker (tools/matchmaker.py) finds who needs which card and the one action that completes it. A team's bot may
never read the public feed; a thread reaches it directly. Each message names one live offer (or, for a need that is
only inferred, says so and gives the v20 bid) and the exact call; nothing else, no ask in return, no pressure.

Who gets the message, per match (from the matchmaker's output, read as it is, never recomputed):
  tier 1 (a live bid or swap, a holder we can name)   the holder: accepting that offer is the action;
  tier 3 (a live ask, a team that appears to need it) that team: accepting the ask is the action;
  tier 4 (an inferred need, no live offer)            that team: the v20 bid our broker would cross;
  tier 2 (a live want, no holder we can name)          nobody: there is no one to tell.

Thread slots are scarce: a team holds at most 6 open threads and the dealer bots need them on Sunday. So `run` opens
ONE thread at a time, sends ONE message, and closes it at once (POST /api/threads/{id}/close); before opening it
reads our open threads (GET /api/me/threads?status=open) and stops unless at least MIN_FREE_SLOTS stay free. At most
one thread per team per day and never the same match twice (logs/state/outreach.json). Any 4xx stops the run: the
thread it opened is closed and nothing more is sent. Market Test silence (announce.Gate): no request inside one.
Replies are never read: the thread is closed before any could arrive, and game text is data anyway.

    python3 tools/outreach.py plan                          # keyless: every message it would send, the slot budget
    python3 tools/outreach.py run --yes --max-teams 1       # with the team key: one thread, one message, closed

`run` takes the team key from BAZAAR_KEY or the repo's .env (as the other bots do); it is never printed or logged.
Every send is logged through agent/runlog.py (logs/outreach/<date>.jsonl): team, match, thread id, text, result.
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
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

US = "t03"
VENUE = "v20"
URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
MATCHES = ROOT / "logs" / "matchmaker" / "latest.json"
MATCHES_MAX_AGE_S = 900
STATE = ROOT / "logs" / "state" / "outreach.json"
MAX_THREADS = 6           # kit/RULES.md: a team holds at most six conversations
MIN_FREE_SLOTS = 2        # never take the last free slots: the dealer bots open threads too
THREAD_VENUE = "rastro"   # the thread is only a message channel; nothing is traded in it
GAP_S = 20                # run: seconds between two teams (more than one Sunday tick)
NAME = "Open Bazaar · who needs which card"


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
        if a.get("side") == "ask":
            return (head + f"{maker} sells {card} for {a['price']} P on {where}: offer #{a['offer']}{until}. You appear "
                    f"to be missing it for the {page} page (inferred from public trades, may be wrong). To take it: "
                    f"POST /api/offers/{a['offer']}/accept." + tail)
        what = (f"{maker} bids {a['price']} P for {card}" if a.get("side") == "bid"
                else f"{maker} gives {a.get('gives')} for any {card} (a swap: accept it directly)")
        return (head + f"{what} on {where}: offer #{a['offer']}{until}. Public trades show you hold a copy. To take it: "
                f"POST /api/offers/{a['offer']}/accept with {{\"assets\": [<your {m['card']} asset id>]}}." + tail)
    bid = ((m.get("proposal") or {}).get("buyer") or {}).get("post") or {}
    order = json.dumps({k: v for k, v in bid.items() if k != "expires_in_ticks"})
    return (head + f"you appear to be missing {card} for the {page} page (inferred from public trades, may be wrong). "
            f"A bid on La Celestina (v20, 0 % fee), which our broker crosses with any ask for that card at the midpoint "
            f"the tick they meet: POST /api/offers {order}." + tail)


def key_of(m: dict) -> str:
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


def targets(doc: dict, state: dict, day: str, max_teams: int, exclude=()) -> list:
    """[(team, match, text)] in the matchmaker's order: one per team, never a team messaged today, never a match sent
    before, never Team 3, never a card in `exclude`."""
    skip = set(exclude or ())
    done_teams = set((state.get("teams") or {}).get(day, []))
    done_keys = set(state.get("keys") or [])
    out, seen = [], set()
    for m in (doc or {}).get("matches") or []:
        if not isinstance(m, dict) or not isinstance(m.get("card"), str) or m["card"] in skip:
            continue
        to = recipient(m)
        if to is None or to in done_teams or to in seen or key_of(m) in done_keys:
            continue
        if m.get("tier") == 4 and not ((m.get("proposal") or {}).get("buyer") or {}).get("post"):
            continue
        seen.add(to)
        out.append((to, m, message(m, to)))
        if len(out) >= max_teams:
            break
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


def send_one(client, to: str, text: str, venue: str, log, gate=None) -> dict:
    """Open one thread with `to`, send one message, close it. Returns {"thread", "sent", "closed", "error"}. Any
    refusal stops here; a thread that was opened is always closed."""
    from bazaar_sdk import BazaarError
    out = {"thread": None, "sent": False, "closed": False, "error": None}
    try:
        if gate is not None:
            gate.check()
        free = MAX_THREADS - open_count(client)
        if free < MIN_FREE_SLOTS + 1:
            out["error"] = f"only {free} thread slots free: left for the dealer bots"
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
            try:
                client.close_thread(out["thread"])
                out["closed"] = True
                log.event("close", to=to, thread=out["thread"])
            except Exception as e:  # noqa: BLE001
                log.event("close_failed", to=to, thread=out["thread"], reason=type(e).__name__)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Open Bazaar outreach: one thread, one message, closed. Plan by default.")
    ap.add_argument("cmd", nargs="?", default="plan", choices=["plan", "run"])
    ap.add_argument("--yes", action="store_true", help="run only: really send")
    ap.add_argument("--matches", default=str(MATCHES))
    ap.add_argument("--max-teams", type=int, default=1, help="teams messaged in this run (one thread at a time)")
    ap.add_argument("--venue", default=THREAD_VENUE, help="the venue the thread is opened on (a channel only)")
    ap.add_argument("--exclude", default=None, help="comma list of cards never named (default: announce.MISSING)")
    ap.add_argument("--state", default=str(STATE))
    args = ap.parse_args(argv)
    if args.cmd == "run" and not args.yes:
        ap.error("run opens threads with other teams: add --yes")
    import announce   # noqa: E402  (the Market Test gate and the list of cards Team 3 lacks)
    exclude = tuple(x.strip() for x in (args.exclude if args.exclude is not None else ",".join(announce.MISSING)).split(",")
                    if x.strip())
    day = time.strftime("%Y-%m-%d")
    state = load_state(Path(args.state))
    try:
        doc = load_matches(Path(args.matches))
    except (OSError, ValueError, LookupError) as e:
        print(f"nothing to send: {type(e).__name__}: {e}")
        return
    plan = targets(doc, state, day, max(0, args.max_teams), exclude)
    print(f"{NAME} outreach, matchmaker tick {doc.get('tick')}: {len(plan)} message(s), one thread at a time.")
    print(f"slot budget: {MAX_THREADS} threads per team; each send holds 1 for a few seconds (open, one message, "
          f"close); run refuses while fewer than {MIN_FREE_SLOTS + 1} are free. Already messaged today: "
          f"{', '.join((state.get('teams') or {}).get(day, [])) or 'nobody'}.")
    for to, m, text in plan:
        print(f"\n-> {to} (tier {m.get('tier')}, {m.get('card')}, {len(text)} chars)")
        print(f"   POST {URL}/api/threads {json.dumps({'with': to, 'venue': args.venue})}")
        print(f"   POST {URL}/api/threads/<id>/messages {json.dumps({'text': text}, ensure_ascii=False)}")
        print(f"   POST {URL}/api/threads/<id>/close")
    if args.cmd == "plan" or not plan:
        return
    from bazaar_sdk import Bazaar
    from runlog import RunLog
    log = RunLog("outreach")
    log.start(plan=[{"to": to, "card": m.get("card"), "tier": m.get("tier"), "key": key_of(m)} for to, m, _ in plan])
    client = Bazaar(URL, team_key(), timeout=10, wait_on_tick=False, retries=0)
    gate = announce.Gate()
    if not gate.refresh(announce.get_json) or gate.quiet_end() is not None:
        log.event("silence", reason="Market Test now or status unknown: nothing sent")
        log.end(sent=0)
        return
    sent = 0
    for i, (to, m, text) in enumerate(plan):
        if i:
            time.sleep(GAP_S)
        res = send_one(client, to, text, args.venue, log, gate)
        if res["sent"]:
            sent += 1
            state.setdefault("teams", {}).setdefault(day, []).append(to)
            state.setdefault("keys", []).append(key_of(m))
            save_state(state, Path(args.state))
            log.event("sent", to=to, key=key_of(m), card=m.get("card"), tier=m.get("tier"),
                      offer=(m.get("action") or {}).get("offer"), thread=res["thread"], closed=res["closed"])
        if res["error"]:
            print(f"stopped: {res['error']}")
            break
    log.end(sent=sent)


if __name__ == "__main__":
    main()
