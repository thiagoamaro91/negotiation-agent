"""Team 3's market brain: one always-on, keyless process that turns the recorded feed into what to do next.

It runs next to tools/feed_recorder.py (same clone, same logs/feed/) and, as soon as new events land, recomputes:
- every team's inferred set multipliers (tools/value_inference.py), and how well the model predicts the next choice;
- every team's cash and known cards (tools/ledger.py), checked against our own account;
- the market plan with timing (tools/market_plan.py): what to sell to and buy from teams (scored at our private
  values) and which dealer deals fill the ladder (an estimated share of the dealer's range);
- dealer closes and a team-to-team price index (tools/price_index.py), every venue's fee, mechanism and open book;
- how far to trust the inference: hit rate next to the naive baseline, a reliability table, the confidence labels;
- a live tape of the market (every listing, bid and deal, with the real team behind each pseudonym), flagging the
  offers that are an opportunity for us at our private values;
- the team's desks (trading agents): their heartbeats, mode and last decision;
- our own account from the key machine's files (tools/team_relay.py, keyless): cash checked against the ledger, cards
  with our values, pages, the live score, every bot decision on the tape, and how close the inference gets to our
  real multipliers (the one team whose truth we know), replayed over the weekend.
Open pages are told at once (server-sent events on /stream) and fetch the new state. It also keeps a learning curve
(logs/brain/history.jsonl).

    python3 tools/brain.py                    # http://127.0.0.1:8790 ; settings from ~/bazaar/brain.env if present
    python3 tools/brain.py --once             # one refresh into logs/brain/latest.json, then exit
    tools/run_brain.sh                        # on the VM: recorder + brain in tmux, restarted if they die

Settings (environment or the --env file): BRAIN_TOKEN gates every page and read (?t=...) and is required: the server
refuses to start without it; BRAIN_WRITE_TOKEN lets
tools/me_relay.py push our account (POST /ingest/me) from the laptop that holds the team key, so the key never
leaves that laptop, and lets the desks post heartbeats (POST /ingest/desk, header X-Brain-Write, body
{"name", "mode": "shadow"|"live", "tick", "last_decision", "reason"}; 4 KB at most, any field whose name contains
"key" is dropped and key-like values are redacted). BRAIN_PAGE_BONUS=1 counts the page bonus in trade values once the
desk confirms it. POST /ingest/team (same header, 1 MB at most) takes tools/team_relay.py's bundle: our account,
the live score, decisions.jsonl and the desk files, scrubbed again here. The brain itself has no key and never sends
anything to the game.
"""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import re
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import decks as decks_mod
import ledger as ledger_mod
import market_plan
import price_index
import redaction
import value_inference as vi

OUT = vi.ROOT / "logs" / "brain"
PAGE = Path(__file__).resolve().parent / "brain.html"
STATE = {"data": None, "error": None, "updated": 0.0, "version": 0}
COND = threading.Condition()
POKE = threading.Event()        # set by /ingest/me to refresh at once
CHECK_SECONDS = 2.0             # how often the worker looks for new events
MAX_QUIET_SECONDS = 60.0        # refresh at least this often (the live board can change without a feed event)
TAPE_LEN = 100
DEFAULT_ENV = Path.home() / "bazaar" / "brain.env"
DESK_MAX_BYTES = 4096           # a heartbeat is a few lines; anything bigger is refused
DESK_MAX = 24                   # desks remembered at once (the oldest heartbeat is forgotten first)
DESK_TEXT = {"last_decision": 300, "reason": 500}
DESK_NAME = re.compile(r"^[A-Za-z0-9 _.-]{1,40}$")
DESKS: dict = {}
DESK_LOCK = threading.Lock()
LAST_DESK_PUSH = [0.0]
DESK_FILE = OUT / "desks.json"
TEAM_LIVE = vi.ROOT / "logs" / "state" / "team_live.json"   # tools/team_relay.py's last bundle
SCORE_FIELDS = ("score", "rank", "negotiating", "market", "neg_points", "duel_points", "ladder_points",
                "bench_efficiency", "deals", "pages_complete", "album_filled", "cash", "tick")
SET_FIELD = re.compile(r"set_[A-Z]{3}")   # live-score page counts per set (set_LAV ...)
SET_ID = re.compile(r"[A-Z]{3}")
TEAM_MAX_BYTES = 1_000_000
TEAM_STALE_SECONDS = 180    # the relay sends every 20 s; older than this and the page says so
DECISIONS_ON_TAPE = 40      # our latest decisions merged into the market tape
TRUTH_POINTS = 60           # points kept on the inference-vs-truth curve


def load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


class Snapshots:
    """The recorder's snapshots.jsonl read incrementally (it grows with every book change): the latest leaderboard,
    venue list, El Rastro board and every venue's book, without re-reading the file on each refresh."""

    def __init__(self, path: Path):
        self.path, self.offset, self.latest, self.books = path, 0, {}, {}

    def update(self) -> "Snapshots":
        if not self.path.exists():
            return self
        size = self.path.stat().st_size
        if size < self.offset:  # rotated or truncated: start again
            self.offset, self.latest, self.books = 0, {}, {}
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # only whole lines; a half-written one waits for the next round
        for line in chunk[:end].splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("what") == "book" and isinstance(row.get("venue"), str):
                self.books[row["venue"]] = row
            elif row.get("what"):
                self.latest[row["what"]] = row
        self.offset += end
        return self

    def body(self, what: str) -> dict:
        return (self.latest.get(what) or {}).get("body") or {}


SNAPS = Snapshots(vi.FEED / "snapshots.jsonl")


def open_offers(body) -> int | None:
    offers = body.get("offers", body) if isinstance(body, dict) else body
    if not isinstance(offers, list):
        return None
    return sum(1 for o in offers if isinstance(o, dict) and o.get("status") in (None, "open"))


def venues_panel(snaps: Snapshots, events: list) -> list:
    """Every venue: owner, fee, mechanism, open offers on its public book (recorder) and trades (its own counter, and
    the settlements the feed shows on it)."""
    settled = {}
    for e in events:
        if e["type"] == "settlement" and not e["payload"].get("persona") and e["payload"].get("venue"):
            settled[e["payload"]["venue"]] = settled.get(e["payload"]["venue"], 0) + 1
    out = []
    for v in snaps.body("venues").get("venues", []) if isinstance(snaps.body("venues"), dict) else []:
        if not isinstance(v, dict):
            continue
        vid = v.get("venue")
        book = snaps.books.get(vid) if vid != "rastro" else snaps.latest.get("rastro")
        out.append({"venue": vid, "name": v.get("name"), "owner": v.get("owner"), "status": v.get("status"),
                    "fee_bps": v.get("fee_bps"), "fee_per_card": v.get("fee_per_card"),
                    "mechanism": (v.get("rules") or {}).get("mechanism") or ("house" if v.get("house") else None),
                    "pending_fee": v.get("pending_fee"), "trades": v.get("trades"), "volume": v.get("volume"),
                    "feed_trades": settled.get(vid, 0), "open_offers": open_offers(book["body"]) if book else None,
                    "book_tick": book.get("tick") if book else None, "opened_tick": v.get("opened_tick")})
    out.sort(key=lambda v: (v["venue"] != "rastro", -(v["trades"] or 0)))
    return out


# ---------------------------------------------------------------- desks (the team's trading agents)

def scrub(x):
    """Drop every field named like a key, token or secret, at any depth, and redact credential-shaped strings
    (tools/redaction.py: team tk-, broker bk_, admin adm_)."""
    return redaction.scrub(x)


def valid_desk(body) -> dict | None:
    """A desk heartbeat, cleaned: {name, mode, tick, last_decision, reason}; None if it is not one. Unknown fields are
    dropped; text is cut to its limit (it is shown on the page, escaped, never run)."""
    if not isinstance(body, dict):
        return None
    body = scrub(body)
    name, mode, tick = body.get("name"), body.get("mode"), body.get("tick")
    if not isinstance(name, str) or not DESK_NAME.match(name) or mode not in ("shadow", "live"):
        return None
    if tick is not None and (isinstance(tick, bool) or not isinstance(tick, int) or tick < 0):
        return None
    out = {"name": name, "mode": mode, "tick": tick}
    for field, limit in DESK_TEXT.items():
        v = body.get(field)
        if v is not None and not isinstance(v, str):
            return None
        out[field] = (v or "")[:limit]
    return out


def record_desk(desk: dict, now: float | None = None) -> None:
    with DESK_LOCK:
        DESKS[desk["name"]] = {**desk, "received": now if now is not None else time.time()}
        while len(DESKS) > DESK_MAX:
            del DESKS[min(DESKS, key=lambda k: DESKS[k]["received"])]
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            tmp = DESK_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(DESKS), encoding="utf-8")
            tmp.replace(DESK_FILE)
        except OSError:
            pass


def load_desks() -> None:
    try:
        saved = json.loads(DESK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for d in saved.values() if isinstance(saved, dict) else []:
        clean = valid_desk(d)
        if clean and isinstance(d.get("received"), (int, float)):
            DESKS[clean["name"]] = {**clean, "received": d["received"]}


def desk_rows(now: float | None = None) -> list:
    now = now if now is not None else time.time()
    with DESK_LOCK:
        rows = [{**d, "age_s": round(now - d["received"], 1)} for d in DESKS.values()]
    return sorted(rows, key=lambda d: d["age_s"])


# ---------------------------------------------------------------- our own team (tools/team_relay.py)

def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def desk_from_file(d) -> dict | None:
    """A key-machine desk file (logs/state/desk-<name>.json) as a heartbeat named mini-<name>; None if it is not one."""
    if not isinstance(d, dict):
        return None
    name = d.get("agent") or d.get("desk") or d.get("name")
    last, reason, tick = d.get("last_decision"), d.get("reason") or d.get("what") or "", d.get("tick")
    if isinstance(last, (dict, list)):
        last = json.dumps(last, ensure_ascii=False)
    return valid_desk({"name": f"mini-{name}" if isinstance(name, str) else "", "tick": tick if isinstance(tick, int)
                       and not isinstance(tick, bool) and tick >= 0 else None,
                       "mode": "live" if d.get("mode") in ("run", "live") else "shadow",
                       "last_decision": last if isinstance(last, str) else None,
                       "reason": reason if isinstance(reason, str) else json.dumps(reason)})


def valid_team(body, received: float | None = None) -> dict | None:
    """tools/team_relay.py's bundle, scrubbed again and cut down to what the brain shows; None if it is not one.
    `received` is when it arrived (now by default)."""
    if not isinstance(body, dict) or body.get("kind") != "team":
        return None
    body = scrub(body)
    rows = lambda name, n: [r for r in body.get(name) or [] if isinstance(r, dict)][-n:] \
        if isinstance(body.get(name), list) else []
    me, st = body.get("me"), body.get("score_state")
    desks = []
    for d in rows("desks", DESK_MAX):
        desk = desk_from_file(d)
        if desk:
            at = d.get("epoch") if finite(d.get("epoch")) else d.get("_mtime")
            desks.append({**desk, "at": at if finite(at) else None})
    if isinstance(me, dict):  # only numbers where numbers go: the page renders these
        me = {**me, "affinity": {k: v for k, v in (me.get("affinity") or {}).items()
                                 if isinstance(k, str) and SET_ID.fullmatch(k) and finite(v)}
              if isinstance(me.get("affinity"), dict) else me.get("affinity")}
    prev = st.get("prev") if isinstance(st, dict) else None
    st = {"prev": {k: v for k, v in prev.items() if (k in SCORE_FIELDS or SET_FIELD.fullmatch(str(k))) and finite(v)}} \
        if isinstance(prev, dict) else None
    return {"kind": "team", "at": body["at"] if finite(body.get("at")) else None,
            "received": received if finite(received) else time.time(),
            "files": {str(k)[:80]: v for k, v in (body.get("files") or {}).items() if finite(v)}
            if isinstance(body.get("files"), dict) else {},
            "me": me if valid_account(me) else None, "score_state": st,
            "decisions": rows("decisions", 400), "score_rows": rows("score_rows", 200), "desks": desks}


ACCOUNT_LOCK = threading.Lock()   # the account's freshness check and its replacement happen as one step


def write_json(path: Path, obj) -> None:
    """Atomic replace through a temporary file of its own, so concurrent writers never share one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj))
    os.replace(tmp, path)


def write_account(me: dict, only_if_fresher: bool) -> bool:
    """Replace the relayed account; with `only_if_fresher`, only by a strictly later tick. Locked across writers."""
    with ACCOUNT_LOCK:
        if only_if_fresher:
            try:
                have = json.loads(vi.ME_LIVE.read_text(encoding="utf-8")).get("tick")
            except (OSError, ValueError):
                have = None
            if isinstance(have, int) and me["tick"] <= have:
                return False
        write_json(vi.ME_LIVE, me)
        return True


ASSET_REF = re.compile(r"\b([A-Z]{3}-\d{2}) #(\d+)")


def conversions(decisions: list) -> list:
    """The Workshop conversions our bots logged: the public feed says only "turned three common cards into X", so the
    burned copies stay in our holdings until the next account snapshot. A `convert` decision names them ("burned
    spares LAV-01 #41, ...") and the card it got ("got LAV-06 #1001")."""
    out = []
    for d in decisions:
        tick = d.get("tick")
        if d.get("action") != "convert" or not isinstance(tick, int) or isinstance(tick, bool):
            continue
        burned = sorted(({"id": int(i), "ref": ref} for ref, i in set(ASSET_REF.findall(str(d.get("why") or "")))),
                        key=lambda b: b["id"])
        got = [{"id": int(i), "ref": ref} for ref, i in ASSET_REF.findall(str(d.get("result") or ""))]
        if burned or got:
            out.append({"tick": tick, "card": d.get("card"), "burned": burned, "got": got})
    return out


def remember_conversions(found: list) -> list:
    """Every conversion ever relayed, kept in vi.CONVERSIONS (the relay sends only the latest decisions, so an old one
    would otherwise fall out of the window and its burned copies come back). vi.load_me() attaches the ones after the
    account's tick."""
    try:
        kept = json.loads(vi.CONVERSIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = []
    def key(c: dict) -> tuple:
        ids = lambda xs: tuple(x.get("id") if isinstance(x, dict) else x for x in xs or [])
        return c.get("tick"), ids(c.get("burned")), ids(c.get("got"))

    seen = {key(c) for c in kept}
    new = [c for c in found if key(c) not in seen]
    if new:
        kept = sorted(kept + new, key=lambda c: c.get("tick") or 0)
        write_json(vi.CONVERSIONS, kept)
    return kept


def absorb(team: dict) -> None:
    """The bundle's account becomes the relayed account unless the one we have is fresher, and its Workshop
    conversions are remembered; its desk files become heartbeats, aged by the file's own time (a desk that stopped
    writing shows its real silence)."""
    remember_conversions(conversions(team.get("decisions") or []))
    me = team.get("me")
    if me:
        write_account({**me, "source": "team relay"}, only_if_fresher=True)
    for d in team.get("desks") or []:
        record_desk({k: v for k, v in d.items() if k != "at"}, now=d.get("at"))


def store_team(team: dict) -> None:
    """POST /ingest/team: keep the bundle (desks go to the desk table) and absorb it."""
    write_json(TEAM_LIVE, {k: v for k, v in team.items() if k != "desks"})
    absorb(team)


def load_team() -> dict | None:
    """The last bundle: posted to /ingest/team, or written straight to TEAM_LIVE by `team_relay.py --out` on the same
    machine (then it is absorbed here)."""
    try:
        raw = json.loads(TEAM_LIVE.read_text(encoding="utf-8"))
        mtime = TEAM_LIVE.stat().st_mtime
    except (OSError, ValueError):
        return None
    team = valid_team(raw, raw.get("received") if isinstance(raw, dict) and finite(raw.get("received")) else mtime)
    if team:
        absorb(team)
    return team


def decision_rows(decisions: list) -> list:
    """decisions.jsonl as tape rows, oldest first; a row without a tick takes the one before it (file order is time)."""
    out, last = [], None
    for d in decisions:
        lane = str(d.get("lane") or "")
        if not lane or lane.endswith("-test"):
            continue
        tick = d.get("tick") if isinstance(d.get("tick"), int) and not isinstance(d.get("tick"), bool) \
            and d["tick"] > 0 else last
        last = tick
        price, who = d.get("price"), d.get("dealer") or d.get("counterparty") or d.get("venue")
        text = " ".join(str(x) for x in (d.get("action"), d.get("card")) if x)
        if finite(price) and price:
            text += f" at {price} P"
        if who:
            text += f" · {who}"
        row = {"kind": "decision", "tick": tick, "lane": lane, "text": text, "teams": [vi.US], "ours": True,
               "id": f"d:{d.get('ts')}:{lane}:{d.get('action')}:{d.get('card')}",
               "why": str(d.get("why") or "")[:400], "result": str(d.get("result") or "")[:240]}
        if finite(d.get("surplus")):
            row["surplus"] = d["surplus"]
        out.append(row)
    return out


def merge_tape(market: list, decisions: list) -> list:
    """The market tape (newest first) with our latest decisions slotted in by tick; a decision older than the market
    rows lands at the bottom, so the page's "decisions" filter always has the latest ones."""
    return sorted(market + decisions[-DECISIONS_ON_TAPE:][::-1], key=lambda r: -(r["tick"] or 0))


def our_account(me: dict, mine, led: dict, team: dict | None, book: dict, rarity: dict, marginals: list,
                 in_play: list, last_tick: int) -> dict:
    """Our cash (live score reading, checked against the ledger at that tick), score, cards with our values, pages."""
    aff = me.get("affinity") or {}
    st = ((team or {}).get("score_state") or {}).get("prev") or {}
    hist = led.get(vi.US, {}).get("history", [])
    rows = [{"tick": me.get("tick"), "cash": me.get("cash"), "what": "account"}]
    rows += [{"tick": r.get("tick"), "cash": r.get("cash"), "what": "score log"} for r in (team or {}).get("score_rows") or []]
    rows.append({"tick": st.get("tick"), "cash": st.get("cash"), "what": "live score"})
    checks, seen = [], set()
    for r in rows:
        if not (isinstance(r["tick"], int) and finite(r["cash"])) or r["tick"] in seen:
            continue
        seen.add(r["tick"])
        rebuilt = ledger_mod.cash_at(hist, r["tick"])
        checks.append({**r, "rebuilt": rebuilt, "ok": rebuilt == r["cash"], "ahead": r["tick"] > last_tick})
    checks.sort(key=lambda c: c["tick"])
    api_value = {}
    for a in me.get("assets") or []:
        if a.get("kind") == "card" and finite(a.get("your_value")):
            api_value[a["ref"]] = max(api_value.get(a["ref"], 0), a["your_value"])
    cards = []
    for ref, n in sorted(mine.items()):
        if n <= 0 or ref not in book:
            continue
        m = aff.get(vi.set_of(ref))
        cards.append({"ref": ref, "set": vi.set_of(ref), "n": n, "rarity": rarity.get(ref), "book": book[ref],
                      "values": [round(market_plan.copy_value(book[ref], m, i, marginals), 1) for i in range(n)] if m else [],
                      "api_value": api_value.get(ref)})
    pages = []
    for s in sorted({c["set"] for c in cards} | set(in_play), key=lambda s: -(aff.get(s) or 0)):
        held = [f"{s}-{i:02d}" for i in range(1, 11) if mine.get(f"{s}-{i:02d}", 0) > 0]
        pages.append({"set": s, "mult": aff.get(s), "held": len(held), "of": 10,
                      "missing": [f"{s}-{i:02d}" for i in range(1, 11) if f"{s}-{i:02d}" not in held],
                      "live": st.get(f"set_{s}")})
    score = {k: st.get(k) for k in ("score", "rank", "negotiating", "market", "neg_points", "duel_points",
                                    "ladder_points", "bench_efficiency", "deals", "pages_complete", "album_filled")}
    files = (team or {}).get("files") or {}
    now = time.time()
    cash = choose_cash(me, st, hist, led.get(vi.US, {}).get("cash"), last_tick)
    live_file = files.get("score.state.json")
    return {"account_tick": me.get("tick"), "account_source": me.get("source") or "snapshot",
            "live_tick": st.get("tick"), **cash,
            "ledger_cash": led.get(vi.US, {}).get("cash"), "score": score, "cards": cards, "pages": pages,
            "checks": checks[-12:], "copies": sum(c["n"] for c in cards),
            "relay": {"age_s": round(now - team["received"], 1) if team and finite(team.get("received")) else None,
                      "files_age_s": {k: round(now - v) for k, v in files.items()},
                      "live_score_age_s": round(now - live_file) if finite(live_file) else None,
                      "decisions": len((team or {}).get("decisions") or [])}}


def choose_cash(me: dict, st: dict, hist: list, ledger_now, last_tick: int) -> dict:
    """Our cash now: the freshest real reading (the account snapshot or the live score reader, by tick). When the
    rebuilt ledger agrees with that reading at its tick and the feed has moved on, the ledger's latest value is fresher
    still; otherwise the reading stands. `cash_stale` says how many ticks the reading is behind the feed."""
    readings = [{"tick": r["tick"], "cash": r["cash"], "what": r["what"]}
                for r in ({"tick": me.get("tick"), "cash": me.get("cash"), "what": "account"},
                          {"tick": st.get("tick"), "cash": st.get("cash"), "what": "live score"})
                if isinstance(r["tick"], int) and not isinstance(r["tick"], bool) and finite(r["cash"])]
    if not readings:
        return {"cash": ledger_now, "cash_source": "ledger", "cash_tick": last_tick, "cash_stale": None}
    fresh = max(readings, key=lambda r: r["tick"])
    behind = last_tick - fresh["tick"]
    if behind > 0 and ledger_now is not None and ledger_mod.cash_at(hist, fresh["tick"]) == fresh["cash"]:
        return {"cash": ledger_now, "cash_source": f"ledger (agrees with the {fresh['what']} at t{fresh['tick']})",
                "cash_tick": last_tick, "cash_stale": 0}
    return {"cash": fresh["cash"], "cash_source": f"{fresh['what']} at t{fresh['tick']}", "cash_tick": fresh["tick"],
            "cash_stale": max(behind, 0)}


def deck_vs_real(events: list, cat: dict, team: dict | None) -> dict | None:
    """The deck rebuild (tools/decks.py) checked on the one deck we know: ours, at the tick of our last raw account
    snapshot (the relayed one, else logs/state/me.json)."""
    me = (team or {}).get("me")
    if not me:
        try:
            me = json.loads(vi.ME.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    rebuilt = decks_mod.build(events, cat, upto=me.get("tick")).get(vi.US)
    return {"tick": me.get("tick"), **decks_mod.check(rebuilt, me.get("assets") or [])} if rebuilt else None


TRUTH_CACHE: dict = {}


def inference_vs_truth(model, evs: list, truth: dict) -> dict | None:
    """How close the inference gets to our real multipliers, replayed over our own public evidence: after each tick
    with new evidence, the mean error per set, the share of set pairs put in the right order, the probability on each
    true multiplier and on our true favourite. The prior (no evidence) is the baseline."""
    sets = [s for s in model.in_play if finite(truth.get(s))]
    if len(sets) < 2:
        return None
    evs = sorted(evs, key=lambda e: e["tick"])
    key = (tuple(sets), tuple(truth.get(s) for s in sets), len(evs), evs[-1]["tick"] if evs else None)
    if key in TRUTH_CACHE:
        return TRUTH_CACHE[key]
    fav = max(sets, key=lambda s: truth[s])
    pairs = [(a, b) for i, a in enumerate(sets) for b in sets[i + 1:] if truth[a] != truth[b]]

    def score(post: list, tick, n: int) -> dict:
        exp = {s: sum(w * p[s] for w, p in zip(post, model.perms)) for s in sets}
        p_true = {s: sum(w for w, p in zip(post, model.perms) if p[s] == truth[s]) for s in sets}
        top = model.p_top(post)
        ok = sum(0.5 if abs(exp[a] - exp[b]) < 1e-9 else float((exp[a] - exp[b]) * (truth[a] - truth[b]) > 0)
                 for a, b in pairs)  # a tie is a coin flip: the prior scores 50 %
        return {"tick": tick, "n": n, "mae": round(sum(abs(exp[s] - truth[s]) for s in sets) / len(sets), 3),
                "pairs": round(ok / len(pairs), 3) if pairs else None,
                "p_true": round(sum(p_true.values()) / len(sets), 3), "p_fav": round(top.get(fav, 0.0), 3),
                "fav_ok": max(top, key=top.get) == fav, "exp": {s: round(exp[s], 2) for s in sets},
                "p_each": {s: round(p_true[s], 3) for s in sets}}

    prior = score([1 / len(model.perms)] * len(model.perms), None, 0)
    ends = [k for k in range(len(evs)) if k == len(evs) - 1 or evs[k + 1]["tick"] != evs[k]["tick"]]
    if len(ends) > TRUTH_POINTS:  # keep evenly spaced points, always the last one
        step = len(ends) / TRUTH_POINTS
        ends = sorted({ends[int(i * step)] for i in range(TRUTH_POINTS)} | {ends[-1]})
    logp, points, done = [0.0] * len(model.perms), [], 0
    for k, (ev, w) in enumerate(zip(evs, model.weights(evs))):
        for i in range(len(model.perms)):
            logp[i] += w * model.loglik(ev, i)
        if done < len(ends) and k == ends[done]:
            done += 1
            points.append({x: v for x, v in score(model._normalise(logp), ev["tick"], k + 1).items()
                           if x not in ("exp", "p_each")})
    final = score(model._normalise(logp), evs[-1]["tick"], len(evs)) if evs else prior
    rank = lambda vals: {s: 1 + sum(vals[t] > vals[s] for t in sets) for s in sets}
    r_inf, r_true = rank(final["exp"]), rank(truth)
    out = {"sets": [{"set": s, "true": truth[s], "inferred": final["exp"][s], "p_true": final["p_each"][s],
                     "rank_true": r_true[s], "rank_inferred": r_inf[s]} for s in sorted(sets, key=lambda s: -truth[s])],
           "favourite": fav, "now": {k: v for k, v in final.items() if k not in ("exp", "p_each")},
           "prior": {k: v for k, v in prior.items() if k not in ("exp", "p_each")}, "curve": points,
           "evidence": len(evs), "pairs_total": len(pairs)}
    TRUTH_CACHE.clear()
    TRUTH_CACHE[key] = out
    return out


def tape(events: list, ours: dict, mine, book: dict, marginals: list) -> list:
    """The latest market moves in plain words, newest first; an offer we could take with a gain is an opportunity."""
    def keep(ref: str) -> float:
        return market_plan.copy_value(book[ref], ours[vi.set_of(ref)], mine[ref] - 1, marginals)

    def get(ref: str) -> float:
        return market_plan.copy_value(book[ref], ours[vi.set_of(ref)], max(mine[ref], 0), marginals)

    out = []
    for e in reversed(events):
        p, kind = e["payload"], e["type"]
        row = None
        if kind == "settlement":
            items = p.get("items") or []
            refs = ", ".join(i.get("ref") or i.get("name") or "?" for i in items)
            dealer = p.get("persona")
            if dealer and items:
                i = items[0]
                row = ({"kind": "dealer", "text": f"{i.get('to')} bought {refs} from {dealer} for {p.get('price')} P"}
                       if i.get("frm") == dealer else
                       {"kind": "dealer", "text": f"{i.get('frm')} sold {refs} to {dealer} for {p.get('price')} P"})
            elif items:
                row = {"kind": "trade", "text": f"{items[0].get('frm')} → {items[0].get('to')}: {refs} for {p.get('price')} P"}
            if row:
                row["teams"] = sorted({x for i in items for x in (i.get("frm"), i.get("to")) if x})
                one = items[0] if len(items) == 1 else {}
                ref, price = one.get("ref"), p.get("price") or 0
                if ref in book and vi.set_of(ref) in ours:  # our own closed deals that lost value (copy counts as of now)
                    if one.get("to") == vi.US and price > keep(ref) + 0.5:
                        row["warning"] = f"we paid {price} P for a copy worth ~{keep(ref):.0f} P to us"
                    elif one.get("frm") == vi.US and price + 0.5 < get(ref):
                        row["warning"] = f"we sold for {price} P a copy worth ~{get(ref):.0f} P to us"
        elif kind == "offer.listed" and isinstance(p.get("offer"), dict):
            o = p["offer"]
            give, want, maker = o.get("give") or {}, o.get("want") or {}, o.get("maker")
            gives = [a.get("ref") for a in give.get("assets") or [] if isinstance(a, dict)]
            wants = vi.card_types(want)
            to = f" (to {o['to']})" if o.get("to") else ""
            if len(gives) == 1 and want.get("cash") and not wants:
                price, ref = want["cash"], gives[0]
                row = {"kind": "ask", "text": f"{maker} sells {ref} at {price} P{to}", "ref": ref, "price": price}
                if maker == vi.US and ref in book and mine[ref] > 0 and price < keep(ref):
                    row["warning"] = f"we sell below our value ({keep(ref):.0f} P)"
                if ref in book and vi.set_of(ref) in ours and o.get("to") in (None, vi.US) and maker != vi.US:
                    g = get(ref) - price - market_plan.fee(price)
                    if g >= market_plan.MIN_GAIN:
                        row["opportunity"] = f"buy: +{g:.0f} P at our values"
            elif len(wants) == 1 and give.get("cash") and not gives:
                price, ref = give["cash"], wants[0]
                row = {"kind": "bid", "text": f"{maker} bids {price} P for {ref}{to}", "ref": ref, "price": price}
                if maker == vi.US and ref in book and price > get(ref):
                    row["warning"] = f"we bid above our value ({get(ref):.0f} P)"
                if ref in book and mine[ref] > 0 and o.get("to") in (None, vi.US) and maker != vi.US:
                    g = price - market_plan.fee(price) - keep(ref)
                    if g >= market_plan.MIN_GAIN:
                        row["opportunity"] = f"sell: +{g:.0f} P at our values"
            elif gives or wants:
                row = {"kind": "swap", "text": f"{maker} offers {', '.join(gives) or str(give.get('cash', 0)) + ' P'} "
                                               f"for {', '.join(wants) or str(want.get('cash', 0)) + ' P'}{to}"}
            if row:
                row["teams"] = [maker]
        elif kind in ("venue.opened", "level.unlocked", "level.activated", "gift.given", "announcement", "day.opened",
                      "duels.scheduled", "set.released"):
            text = {"venue.opened": lambda: f"{p.get('owner')} opened venue {p.get('name')} (fee {p.get('fee_bps')} bps)",
                    "level.unlocked": lambda: f"{p.get('team')} unlocked {p.get('persona_name') or p.get('persona')}",
                    "gift.given": lambda: f"{p.get('team')} got a gift: {', '.join(p.get('cards') or p.get('packs') or [])}"
                                          + (f" {p['cash']} P" if p.get("cash") else "")}.get(kind)
            row = {"kind": "news", "text": text() if text else (p.get("text") or p.get("name") or p.get("note") or kind)}
            row["teams"] = [x for x in (p.get("team"), p.get("owner")) if x]
        if row:
            row.update(tick=e["tick"], id=e["id"], ours=vi.US in row.get("teams", []))
            out.append(row)
            if len(out) >= TAPE_LEN:
                break
    return out


def refresh() -> dict:
    t0 = time.time()
    try:  # GET /api/catalog (keyless) every cycle, so a newly released set (El Retiro) is picked up
        vi.catalog(refresh=True)
    except Exception:  # noqa: BLE001  unreachable or bad body: the cached logs/public/catalog.json stays
        pass
    team = load_team()  # first: a fresher account in it becomes the one load_me() and the plan read
    model, by_team, events, book = vi.load()
    cat = vi.catalog()
    marginals = cat["values"]["copy_marginals"]
    schedule = vi.public("schedule", True)
    led = ledger_mod.build(events, schedule)
    chk = ledger_mod.check_us(led)
    split = model.time_split(by_team)
    me = vi.load_me()
    truth = me.get("affinity", {})
    mine = vi.our_cards(me, events)
    ours = model.summary(model.posterior(by_team.get(vi.US, [])), by_team.get(vi.US, []))
    st_now = ((team or {}).get("score_state") or {}).get("prev") or {}
    cash_now = choose_cash(me, st_now, led.get(vi.US, {}).get("history", []), led.get(vi.US, {}).get("cash"),
                           events[-1]["tick"])
    plan = market_plan.plan(split, cash_reading=cash_now)  # the page's cash and the plan's funding are one reading
    rarity, _, _ = price_index.card_kinds(cat)
    snaps = SNAPS.update()
    lb = snaps.body("leaderboard")
    score = {t["team"]: t.get("score") for t in lb.get("teams", [])}
    album = {t["team"]: {k: t.get(k) for k in ("album_filled", "album_slots", "pages_complete")} for t in lb.get("teams", [])}
    deck = decks_mod.build(events, cat)
    deck_check = deck_vs_real(events, cat, team)
    teams = []
    for t in sorted(by_team):
        r = model.summary(model.posterior(by_team[t]), by_team[t])
        L = led.get(t, {})
        teams.append({
            "team": t, "us": t == vi.US, "score": score.get(t), "rank": None,
            "cash": L.get("cash"), "cash_unsure": L.get("cash_unsure") or 0, "cash_history": L.get("history", [])[-60:],
            "trades": L.get("trades"),
            "unlocked": L.get("unlocked"), "venue": L.get("venue"), "bonds": L.get("bonds"),
            "dealer_spent": L.get("dealer_spent"), "known_cards": L.get("known_cards"),
            "deck": {k: v for k, v in deck.get(t, {}).items() if k != "ids"}, "album": album.get(t),
            "expected": {s: round(r["expected"][s], 2) for s in model.in_play},
            "dist": {s: {str(m): round(p, 3) for m, p in r["dist"][s].items()} for s in model.in_play},
            "favourite": r["favourite"], "p_favourite": round(r["p_favourite"], 2),
            "least": r["least"], "p_least": round(r["p_least"], 2), "confidence": r["confidence"],
            "choices": r["choices"], "evidence": len(by_team[t]),
        })
    for i, t in enumerate(sorted((x for x in teams if x["score"] is not None), key=lambda x: -x["score"])):
        t["rank"] = i + 1
    us = our_account(me, mine, led, team, book, rarity, marginals, model.in_play, events[-1]["tick"])
    truth_panel = inference_vs_truth(model, by_team.get(vi.US, []), truth)
    live = vi.ME_LIVE.exists() and json.loads(vi.ME_LIVE.read_text()).get("tick") == me.get("tick")
    data = {
        "tick": events[-1]["tick"], "server_time": time.strftime("%H:%M:%S"),
        "store": {"events": len(events), "api_window": 1000, "first_tick": events[0]["tick"],
                  "last_tick": events[-1]["tick"], "last_seen": events[-1].get("seen_at")},
        "account": {"source": (me.get("source") or "relay (live)") if live else "snapshot", "tick": me.get("tick"),
                    "age_ticks": events[-1]["tick"] - (me.get("tick") or 0)},
        "us": us, "truth": truth_panel, "deck_check": deck_check,
        "model": {"hit": round(split["hit"], 3), "naive": round(split["naive_hit"], 3), "n": split["n"],
                  "chance": round(1 / len(model.in_play), 3), "loss": round(split["loss"], 3),
                  "uniform_loss": round(split["uniform_loss"], 3), "beta_choose": model.beta_choose,
                  "beta_shed": model.beta_shed, "reliability": split["reliability"], "by_label": split["by_label"],
                  "shrink": split["shrink"], "shrunk_loss": round(split["shrunk_loss"], 3),
                  "labels": {"strong": {"p": vi.STRONG_P, "choices": vi.STRONG_CHOICES},
                             "some": {"p": vi.SOME_P, "choices": vi.SOME_CHOICES}},
                  "us": {s: {"inferred": round(ours["expected"][s], 2), "true": truth.get(s)} for s in model.in_play}},
        "ledger_check": chk, "teams": teams, "plan": plan, "in_play": model.in_play,
        "prices": {"dealers": plan.pop("dealer_prices"), "teams": price_index.team_index(events, rarity)},
        "venues": venues_panel(snaps, events),
        "tape": merge_tape(tape(events, truth, mine, book, marginals), decision_rows((team or {}).get("decisions") or [])),
        "leaderboard_tick": lb.get("snapshot_tick"),
    }
    data["compute_s"] = round(time.time() - t0, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "latest.json.tmp"
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    tmp.replace(OUT / "latest.json")
    with open(OUT / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"tick": data["tick"], "at": data["server_time"], "events": len(events), "hit": data["model"]["hit"],
                            "n": split["n"], "beliefs": {t["team"]: [t["favourite"], t["p_favourite"]] for t in teams},
                            "cash": {t["team"]: t["cash"] for t in teams},
                            "truth": {k: (truth_panel or {}).get("now", {}).get(k) for k in ("mae", "pairs", "p_fav")}}) + "\n")
    return data


def publish(**kw) -> None:
    with COND:
        STATE.update(**kw)
        STATE["version"] += 1
        COND.notify_all()


def worker() -> None:
    last_sig, last_at = None, 0.0
    while True:
        try:
            feed = vi.FEED / "feed.jsonl"
            sig = (feed.stat().st_size if feed.exists() else 0,
                   vi.ME_LIVE.stat().st_mtime if vi.ME_LIVE.exists() else 0,
                   TEAM_LIVE.stat().st_mtime if TEAM_LIVE.exists() else 0)
            if sig != last_sig or POKE.is_set() or time.time() - last_at > MAX_QUIET_SECONDS:
                POKE.clear()
                last_sig, last_at = sig, time.time()
                publish(data=refresh(), error=None, updated=time.time())
        except Exception:  # keep serving the last good state
            publish(error=traceback.format_exc(limit=3)[-600:])
        POKE.wait(CHECK_SECONDS)


def valid_account(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("affinity"), dict) and isinstance(body.get("assets"), list)
            and isinstance(body.get("cash"), (int, float)) and math.isfinite(body["cash"]) and isinstance(body.get("tick"), int))


def serve(port: int, host: str, token: str | None, write_token: str | None) -> None:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, u) -> bool:
            return not token or hmac.compare_digest(parse_qs(u.query).get("t", [""])[0].encode(), token.encode())

        def do_GET(self):
            u = urlparse(self.path)
            if not self._allowed(u):
                return self._send(403, b"forbidden", "text/plain")
            if u.path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/data":
                with COND:
                    body = json.dumps({**(STATE["data"] or {}), "error": STATE["error"], "version": STATE["version"],
                                       "age": round(time.time() - STATE["updated"], 1) if STATE["updated"] else None,
                                       "desks": desk_rows()},
                                      default=str)
                return self._send(200, body.encode(), "application/json")
            if u.path == "/history":
                path = OUT / "history.jsonl"
                rows = path.read_text(encoding="utf-8").splitlines()[-500:] if path.exists() else []
                return self._send(200, ("[" + ",".join(rows) + "]").encode(), "application/json")
            if u.path == "/stream":  # server-sent events: one line per new state, a comment every 20 s to keep it open
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                seen = -1
                try:
                    while True:
                        with COND:
                            if STATE["version"] == seen:
                                COND.wait(20)
                            v = STATE["version"]
                        self.wfile.write((f"data: {v}\n\n" if v != seen else ": ping\n\n").encode())
                        self.wfile.flush()
                        seen = v
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            given = (self.headers.get("X-Brain-Write") or "").encode()
            if (u.path not in ("/ingest/me", "/ingest/desk", "/ingest/team") or not write_token
                    or not hmac.compare_digest(given, write_token.encode())):
                return self._send(403, b"forbidden", "text/plain")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            limit = {"/ingest/desk": DESK_MAX_BYTES, "/ingest/team": TEAM_MAX_BYTES}.get(u.path, 512_000)
            if n <= 0 or n > limit:
                return self._send(413, b"too large", "text/plain")
            try:
                body = json.loads(self.rfile.read(n))
            except ValueError:
                return self._send(400, b"bad json", "text/plain")
            if u.path == "/ingest/team":
                team = valid_team(body)
                if team is None:
                    return self._send(400, b"not a team bundle", "text/plain")
                store_team(team)
                POKE.set()
                return self._send(200, b"ok", "text/plain")
            if u.path == "/ingest/desk":
                desk = valid_desk(body)
                if desk is None:
                    return self._send(400, b"not a desk heartbeat", "text/plain")
                record_desk(desk)
                if time.time() - LAST_DESK_PUSH[0] >= 2.0:  # open pages refetch, at most every 2 s however many desks
                    LAST_DESK_PUSH[0] = time.time()
                    publish()
                return self._send(200, b"ok", "text/plain")
            if not valid_account(body):
                return self._send(400, b"not an account", "text/plain")
            write_account(body, only_if_fresher=False)  # the keyed relay reads /api/me now: always the freshest
            POKE.set()
            return self._send(200, b"ok", "text/plain")

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.serve_forever()


def require_token(token: str | None) -> str:
    """The page shows our plan, cash and holdings: the server never starts open."""
    if not (token or "").strip():
        raise SystemExit("brain: BRAIN_TOKEN is unset or empty; refusing to start an open page. Set it in the "
                         "environment or the --env file (~/bazaar/brain.env), e.g. BRAIN_TOKEN=$(openssl rand -hex 16)")
    return token.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Team 3's market brain (keyless, plans only).")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV, help="KEY=VALUE file with BRAIN_TOKEN / BRAIN_WRITE_TOKEN")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    load_env(args.env)
    if args.once:
        d = refresh()
        print(f"tick {d['tick']}: {d['store']['events']} events, model hit {d['model']['hit']:.0%} "
              f"(naive {d['model']['naive']:.0%}, keep {d['model']['shrink']:.0%} of the confidence), "
              f"ledger check {d['ledger_check']}, {len(d['plan']['sells'])} sells, {len(d['plan']['buys'])} buys, "
              f"{len(d['plan']['dealer'])} dealer rows, {len(d['venues'])} venues, "
              f"{sum(1 for r in d['tape'] if r.get('opportunity'))} opportunities on the tape, {d['compute_s']} s")
        return
    token = require_token(os.environ.get("BRAIN_TOKEN"))
    load_desks()
    threading.Thread(target=worker, daemon=True).start()
    print(f"brain on http://{args.host}:{args.port}/ ({'token required' if token else 'open'}; "
          f"account relay {'on' if os.environ.get('BRAIN_WRITE_TOKEN') else 'off'})", flush=True)
    serve(args.port, args.host, token, os.environ.get("BRAIN_WRITE_TOKEN"))


if __name__ == "__main__":
    main()
