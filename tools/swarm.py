#!/usr/bin/env python3
"""Swarm view: one event stream for every agent of Team 3, drawn live as a graph. Keyless; never calls the game.

The key machine (the Mac Mini) is the single source of truth. Everything the team's agents write already lands
there, so this folds those files into one stream and serves a page that draws it:

  <live>/agents.log, agents-mini.log    Claude conductor and lanes (agents_feed.py): "HH:MM:SS [lane] says|does: ..."
  <live>/decisions.jsonl                decisions the lanes log, each with its why
  <repo>/logs/<bot>/<date>.jsonl        Python bots through agent/runlog.py (duel, broker, dealers, announce, ...)
  <live>/score.state.json               the score after each live.py read (plus score.view.log once, for history)
  issue #25 through `gh`                the team bus between the three accounts

into <out>/swarm-events.jsonl, one event per line:
  {"id", "ts", "src", "dst", "kind", "text", "why", "source", "highlight"}

Text written by other teams, rivals or dealers never enters the stream (it is game data, not ours to replay):
their events keep only numbers. Anything that looks like a key is redacted.

usage (on the Mini, where <live> is ~/bazaar-live and <repo> is this checkout):
  SWARM_TOKEN=<16+ chars> python3 tools/swarm.py run         # fold every 5 s, serve http://127.0.0.1:8777/?t=<token>
  tailscale serve --bg --https=8443 8777                      # private view for the tailnet only (never funnel it)
  python3 tools/swarm.py fold                                 # fold once and exit
  python3 tools/swarm.py plan                                 # fold once into memory, print counts, write nothing
  python3 tools/swarm.py serve --public --port 8778           # second, read-only view for a public link (no folding);
  tailscale funnel --bg 8778                                  # shows only what is already on public boards
The private view always needs SWARM_TOKEN; nothing listens on a wildcard address (0.0.0.0 would include the LAN).
development on another machine, against the Mini's shares (read-only there, so --out must be local):
  python3 tools/swarm.py run --live /Volumes/bazaar-live --repo /Volumes/bazaar --out /tmp/swarm
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redaction  # noqa: E402  (one scrubber for everything shown on a page: tk-/bk_/adm_ with - and _ variants)

HERE = Path(__file__).resolve().parent
PAGE = HERE / "swarm.html"
BUS_REPO = "thiagoamaro91/negotiation-agent"
BUS_ISSUE = 25
EVENTS = "swarm-events.jsonl"
STATE = "swarm-state.json"
TEXT = 220
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
AGENT_LINE = re.compile(r"^(\d\d):(\d\d):(\d\d) \[([^\]]+)\] (says|does): (.*)$")
MESSAGE_TO = re.compile(r"^message to ([\w.-]+): (.*)$")
BUS_HEADER = re.compile(r"<!-- team-bus (\{.*?\}) -->", re.S)

# Nodes the page knows by name. Anything else that shows up (a new lane, a new bus session) is added on the fly.
NODES = {
    "thiago": {"label": "Thiago", "layer": "people"},
    "hector": {"label": "Hector", "layer": "people"},
    "member3": {"label": "Teammate", "layer": "people"},
    "conductor": {"label": "Conductor f7", "layer": "claude", "where": "Thiago's Air", "note": "handed over to f8 at 18:34"},
    "thiago-air-f8": {"label": "Conductor f8", "layer": "claude", "where": "Thiago's Air", "note": "in charge since 18:34"},
    "mini-conductor": {"label": "Mini conductor", "layer": "claude", "where": "Mac Mini"},
    "bus": {"label": "Team bus #25", "layer": "hub"},
    "duel": {"label": "Duel bot", "layer": "bots", "where": "Mac Mini"},
    "broker": {"label": "Broker v20", "layer": "bots", "where": "Mac Mini"},
    "dealer-bots": {"label": "Dealer bots", "layer": "bots", "where": "Mac Mini"},
    "announce": {"label": "Announcer", "layer": "bots", "where": "Mac Mini"},
    "market-desk": {"label": "Market desk", "layer": "bots", "where": "Mac Mini"},
    "rastro-seller": {"label": "Rastro seller", "layer": "bots", "where": "Mac Mini"},
    "lease": {"label": "Lease", "layer": "bots", "where": "Mac Mini"},
    "concierge": {"label": "Concierge", "layer": "bots", "where": "Mac Mini"},
    "recorder": {"label": "Feed recorder", "layer": "bots", "where": "Mac Mini"},
    "live-views": {"label": "Live views (live.py)", "layer": "bots", "where": "Mac Mini"},
    "teams": {"label": "Other teams", "layer": "world"},
    "dealers": {"label": "Dealers", "layer": "world"},
    "rastro": {"label": "El Rastro", "layer": "world"},
    "bench": {"label": "Market Test", "layer": "world"},
    "game": {"label": "Scoreboard", "layer": "world"},
}
ALIASES = {"team-lead": "conductor", "thiago-air-f7": "conductor", "thiago-mini-conductor": "mini-conductor",
           "bazaar-pr-steward": "thiago-air-prsteward"}
PEOPLE = {"thiagoamaro91": "thiago", "hector14mv": "hector", "former-teammate": "member3",
          "thiago": "thiago", "hector": "hector", "member3": "member3"}
DECISION_LANES = {"trades": "lane-c-trades", "ladder": "lane-d-ladder", "duel": "lane-duel", "market": "lane-market",
                  "conductor": "conductor"}
# Rows logged with lane "conductor" belong to whoever conducted at that moment.
HANDOFFS = [("2026-10-03T18:34:16+02:00", "conductor", "thiago-air-f8")]
BOT_DIRS = {"duel": "duel", "broker": "broker", "announce": "announce", "rastro": "rastro-seller",
            "market": "market-desk", "lease": "lease", "concierge": "concierge",
            "abuela": "dealer-bots", "chato": "dealer-bots", "pilar": "dealer-bots", "picaros": "dealer-bots",
            "taller": "dealer-bots"}
DEALER_WORDS = ("pilar", "chato", "picaros", "pícaros", "abuela", "taller", "workshop", "ernesto")

# Where each agent gets the data it decides with, read from the code (agent/*.py, tools/*.py, ~/bazaar-live/live.py)
# and the lanes' own transcripts. kind: "live" should be fresh; "config" is set by hand; a "snapshot" is a photo that
# goes stale unless someone retakes it. fresh: the file whose age tells how fresh the source is (live: or repo: path).
DATA = {
    "d-me": {"label": "Account /api/me", "kind": "live", "key": "team", "fresh": "live:score.state.json",
             "readers": ["dealer-bots", "rastro-seller", "market-desk", "lane-c-trades", "lane-d-ladder", "conductor",
                         "thiago-air-f8", "live-views"]},
    "d-value": {"label": "Private value /api/me/value", "kind": "live", "key": "team", "fresh": None,
                "readers": ["dealer-bots", "market-desk", "lane-c-trades", "lane-d-ladder"]},
    "d-duels": {"label": "Duels /api/duels", "kind": "live", "key": "team", "fresh": "repo:logs/duel/*.jsonl",
                "readers": ["duel", "market-desk"]},
    "d-books": {"label": "Venue books", "kind": "live", "key": None, "fresh": "repo:logs/feed/snapshots.jsonl",
                "readers": ["market-desk", "rastro-seller", "announce", "lane-c-trades"]},
    "d-v20": {"label": "v20 book", "kind": "live", "key": "broker", "fresh": "repo:logs/state/desk-broker.json",
              "readers": ["broker"]},
    "d-feed": {"label": "Public feed", "kind": "live", "key": None, "fresh": "repo:logs/feed/feed.jsonl",
               "readers": ["market-desk", "rastro-seller", "lane-c-trades", "lane-d-ladder"], "writers": ["recorder"]},
    "d-params": {"label": "duel-params.json", "kind": "config", "key": None, "fresh": "repo:results/duel-params.json",
                 "readers": ["duel"]},
    "d-floors": {"label": "rastro_floors.json", "kind": "config", "key": None, "fresh": "repo:agent/rastro_floors.json",
                 "readers": ["rastro-seller", "market-desk"]},
    "d-snap": {"label": "me.json snapshot", "kind": "snapshot", "key": None, "fresh": "repo:logs/state/me.json",
               "readers": ["market-desk"]},
    "d-decisions": {"label": "decisions.jsonl", "kind": "live", "key": None, "fresh": "live:decisions.jsonl",
                    "readers": ["conductor", "thiago-air-f8"],
                    "writers": ["lane-c-trades", "lane-d-ladder", "conductor", "thiago-air-f8"]},
}
# A lane's own words say when it reads data ("Watch cash for 7 minutes", "Final API read for the report").
READ_VERB = re.compile(r"^(?:\w+: )?(read|check|show|list|look|watch|find|inspect|rebuild|final api read|wait|review)\b", re.I)
READ_TOPICS = [("d-me", re.compile(r"\b(cash|state|holdings|spares|api read|score|ladder points|account)\b", re.I)),
               ("d-books", re.compile(r"\b(offers?|bids?|asks?|book|listings?)\b", re.I)),
               ("d-feed", re.compile(r"\bfeed\b", re.I)),
               ("d-decisions", re.compile(r"\bdecisions?\b", re.I))]
READ_GAP = 60.0  # at most one read per source and reader per minute: the broker alone reads its book every tick


def redact(s) -> str:
    return redaction.SECRET.sub("<redacted>", str(s))


def clip(s, n: int = TEXT) -> str:
    s = " ".join(redact(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def to_local_iso(ts) -> str | None:
    """Any timestamp the sources use (naive local, offset, Z, epoch) as local ISO with offset."""
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            t = dt.datetime.fromtimestamp(float(ts), LOCAL_TZ)
        else:
            t = dt.datetime.fromisoformat(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(ts).replace("Z", "+00:00")))
            t = t.replace(tzinfo=LOCAL_TZ) if t.tzinfo is None else t.astimezone(LOCAL_TZ)
        return t.isoformat(timespec="seconds")
    except (ValueError, OSError, OverflowError):
        return None


def node_id(name) -> str:
    name = str(name or "").strip()
    name = name.split("/")[0]  # "lane-d-ladder/Explore" is the ladder lane's own helper
    if name in ALIASES:
        return ALIASES[name]
    if name.startswith("bazaar-"):  # SendMessage names of Thiago's Air sessions; the bus calls them thiago-air-*
        return "thiago-air-" + name[len("bazaar-"):]
    return name


def event(source: str, key: str, ts, src, dst, kind: str, text: str, why=None, highlight=None) -> dict | None:
    iso = to_local_iso(ts)
    if iso is None or not src:
        return None
    ev = {"id": hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16], "ts": iso, "src": src, "dst": dst or None,
          "kind": kind, "text": clip(text), "why": clip(why) if why else None, "source": source}
    if highlight:
        ev["highlight"] = clip(highlight, 160)
    return ev


# ---------- agents.log (Claude lanes) ----------

def agents_event(source: str, key: str, day: dt.date, line: str) -> dict | None:
    m = AGENT_LINE.match(ANSI.sub("", line).rstrip())
    if not m:
        return None
    h, mi, s, lane, verb, text = m.groups()
    if lane == "feeder":
        return None
    ts = dt.datetime(day.year, day.month, day.day, int(h), int(mi), int(s), tzinfo=LOCAL_TZ)
    src = node_id(lane)
    sub = lane.split("/", 1)[1] + ": " if "/" in lane else ""
    if verb == "says":
        return event(source, key, ts, src, None, "say", sub + text)
    msg = MESSAGE_TO.match(text)
    if msg:
        return event(source, key, ts, src, node_id(msg.group(1)), "msg", sub + msg.group(2))
    return event(source, key, ts, src, None, "act", sub + text)


def lane_reads(ev: dict) -> list:
    if not ev or ev["kind"] != "act" or not READ_VERB.match(ev["text"]):
        return []
    return [dict(ev, id=hashlib.sha1((ev["id"] + did).encode()).hexdigest()[:16], src=did, dst=ev["src"], kind="read")
            for did, pat in READ_TOPICS if pat.search(ev["text"])]


def _secs(line: str):
    m = AGENT_LINE.match(ANSI.sub("", line))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


def first_day(lines, last_day: dt.date) -> dt.date:
    """agents.log carries no date. Walk back from the day the file was last written, one day per midnight crossed."""
    crossings, last = 0, None
    for line in lines:
        s = _secs(line)
        if s is None:
            continue
        if last is not None and s < last - 6 * 3600:
            crossings += 1
        last = s
    return last_day - dt.timedelta(days=crossings)


# ---------- decisions.jsonl ----------

def counterparty_node(cp, venue, why="") -> str:
    cp = str(cp or "").lower()
    if any(w in cp for w in DEALER_WORDS):
        return "dealers"
    if re.match(r"^t\d\d\b", cp) or re.match(r"^m[0-9a-f]{6,}", cp):
        return "teams"
    if any(w in str(why).lower() for w in DEALER_WORDS[:5]):
        return "dealers"
    if str(venue or "").lower() == "rastro":
        return "rastro"
    return "teams" if venue else "game"


def decision_lane(lane, iso: str) -> str:
    who = DECISION_LANES.get(str(lane), f"lane-{lane}")
    for at, old, new in HANDOFFS:
        if who == old and iso >= at:
            who = new
    return who


def decision_event(source: str, key: str, r: dict) -> dict | None:
    iso = to_local_iso(r.get("ts"))
    if iso is None or "test" in str(r.get("lane") or ""):
        return None
    action, card, price, result = r.get("action"), r.get("card"), r.get("price"), str(r.get("result") or "")
    text = " ".join(str(x) for x in (action, card, f"at {price}" if price is not None else None,
                                     f"with {r['counterparty']}" if r.get("counterparty") else None,
                                     f"on {r['venue']}" if r.get("venue") else None) if x)
    if result:
        text += f" → {result}"
    why = str(r.get("why") or "")
    page = "page complete" in result.lower() or (result.upper().startswith("FILLED") and "complete" in why.lower())
    hl = f"{card} completes a page" if page else None
    ev = event(source, key, iso, decision_lane(r.get("lane"), iso),
               counterparty_node(r.get("counterparty"), r.get("venue"), why), "decision", text, why, hl)
    if ev and action in PUBLIC_DECISIONS and result.lower().startswith("posted"):
        ev["posted"] = True  # the post went through: it is on a public board now
    return ev


# ---------- bot logs (agent/runlog.py) ----------

def bot_event(source: str, key: str, folder: str, r: dict) -> dict | None:
    node, ev, ts = BOT_DIRS.get(folder), r.get("event"), r.get("ts")
    if not node or not ev:
        return None
    why = r.get("why") if isinstance(r.get("why"), str) else r.get("reason") if isinstance(r.get("reason"), str) else None
    E = lambda dst, kind, text, w=why, src=node: event(source, key, ts, src, dst, kind, text, w)  # noqa: E731
    if ev in ("run_start", "run_end", "stopped"):
        return E(None, "life", f"{folder}: {ev.replace('_', ' ')}" + (f" ({r['mode']})" if r.get("mode") else ""))
    if node == "duel":
        d, price = r.get("duel"), r.get("price")
        if ev == "duel_new":
            return E("teams", "duel", f"duel {d} opens: {r.get('role')}, {r.get('item')}, limit {r.get('limit')}")
        if ev == "say":
            return E("teams", "offer", f"duel {d}: offers {price}" + (f", {r['days']} days" if r.get("days") else ""),
                     r.get("step"))
        if ev == "rival":
            offer = r.get("offer") if isinstance(r.get("offer"), dict) else {}
            return E("duel", "read", f"duel {d}: reads the rival's offer, {offer.get('price')}", None, "d-duels")
        if ev == "hold":
            return E("duel", "read", f"duel {d}: reads the duel and holds", None, "d-duels")
        if ev == "accept":
            resp = r.get("resp") if isinstance(r.get("resp"), dict) else {}
            return E("teams", "deal", f"duel {d}: accepts {resp.get('price', price)}")
        if ev == "result":
            return E("teams", "result", f"duel {d}: {r.get('status')} at {price}, our surplus {r.get('our_surplus')}")
        return None  # the rival's words never enter
    if node == "broker":
        if ev == "book":
            book = r.get("book") if isinstance(r.get("book"), dict) else {}
            n = len(book.get("offers") or []) + len(book.get("bench_offers") or [])
            return E("broker", "read", f"reads the v20 book, {n} offers", None, "d-v20")
        if ev == "matched":
            return E("bench", "match", f"crosses {r.get('sell')} with {r.get('buy')} at {r.get('price')}")
        if ev == "dropped":
            m = r.get("match") or [None, None, None]
            return E("bench", "skip", f"drops {m[0]} / {m[1]} at {m[2] if len(m) > 2 else '?'}")
        if ev == "bench_run_end":
            return E("bench", "result", f"Market Test {r.get('bench_run')} ends, {r.get('matched', 0)} crossed")
        if ev == "read_error":
            return E(None, "error", "read error", str(r.get("error") or "")[:80])
        return None
    if node == "dealer-bots":
        thread, price = r.get("thread"), r.get("price")
        if ev == "open":
            return E("dealers", "msg", f"{folder}: opens thread {thread}, {r.get('side')} {r.get('item')}")
        if ev == "say":
            return E("dealers", "offer", f"{folder}: we say {price}")
        if ev == "her":
            return E(node, "offer", f"{folder} answers {price}" + (" (final)" if r.get("final") else ""), None, "dealers")
        if ev == "accept":
            return E("dealers", "deal", f"{folder}: accepts {price}")
        if ev == "result":
            return E("dealers", "result", f"{folder}: {r.get('status')} at {price}")
        if ev == "max_rounds":
            return E("dealers", "skip", f"{folder}: walks away (ours {r.get('ours')}, theirs {r.get('her')})")
        return None
    if node == "announce" and ev == "announce":
        return E("teams", "announce", r.get("text") or "announcement")
    if node == "rastro-seller":
        if ev == "listed":
            e = E("rastro", "offer", f"lists {r.get('card')} at {r.get('price')} (floor {r.get('floor')})")
            if e and r.get("offer") and r.get("mode") == "run":  # plan mode logs "listed" without posting
                e["posted"] = True
            return e
        if ev == "their_message":
            return E(node, "msg", "a message from another team (text not replayed)", None, "teams")
        if ev in ("not_held", "bid_below_floor"):
            return E("rastro", "skip", f"{ev.replace('_', ' ')}: {r.get('card', '')}")
        return None
    if node == "market-desk" and ev == "decision":
        return E("market-desk", "read", f"weighs {r.get('kind')} {r.get('card')} at {r.get('price')} on {r.get('venue')}",
                 None, "d-books")
    if node == "market-desk" and ev == "sent":
        if r.get("op") == "cancel":  # its price is the replacement's, which may never get posted
            return E("rastro", "offer", f"cancels {r.get('kind')} {r.get('card')}")
        price = f" at {r.get('price')}" if r.get("price") is not None else ""
        e = E("rastro", "offer", f"posts {r.get('kind')} {r.get('card')}{price}")
        if e:
            e["posted"] = True  # "sent" is only logged after the post succeeded (agent/market_desk.py)
        return e
    if node == "lease" and ev == "grant":
        desk = BOT_DIRS.get(str(r.get("desk")), str(r.get("desk")))
        return E(desk, "grant", f"grants {r.get('got')}/{r.get('asked')} {r.get('kind')}")
    return None


# ---------- team bus ----------

def bus_events(comments: list) -> list:
    """Bus comments → events. A reply points at the session it answers, so agent-to-agent threads show as edges."""
    sessions, out = {}, []
    for c in comments:
        body = c.get("body") or ""
        m = BUS_HEADER.search(body)
        if not m:
            continue
        try:
            meta = json.loads(m.group(1))
        except ValueError:
            continue
        cid = str(c.get("id") or c.get("url", "").rsplit("-", 1)[-1])
        src = node_id(meta.get("session") or c.get("author", {}).get("login"))
        sessions[cid] = src
        to = [PEOPLE.get(str(t), str(t)) for t in meta.get("to") or []]
        reply = meta.get("reply_to")
        dst = sessions.get(str(reply)) if reply else None
        if dst is None:
            dst = to[0] if len(to) == 1 and to[0] in ("thiago", "hector", "member3") else "bus"
        text = BUS_HEADER.sub("", body).strip()
        text = re.sub(r"^\*\*\w+\*\*[^\n]*\n", "", text).strip()
        ev = event("bus", cid, c.get("createdAt"), src, dst, "bus", f"[{meta.get('kind', 'info')}] {text}")
        if ev:
            ev["person"] = PEOPLE.get(c.get("author", {}).get("login", ""))
            out.append(ev)
    return out


def fetch_bus(timeout: float = 30.0) -> list:
    if not shutil.which("gh"):
        return []
    try:
        p = subprocess.run(["gh", "api", f"repos/{BUS_REPO}/issues/{BUS_ISSUE}/comments", "--paginate",
                            "--jq", ".[] | {id, body, createdAt: .created_at, author: {login: .user.login}}"],
                           capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return []
    if p.returncode != 0:
        return []
    rows = []
    for line in p.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# ---------- score ----------

SCORE_KEYS = ("score", "rank", "neg_points", "pages_complete")


def score_event(source: str, at, s: dict, prev: dict | None) -> dict | None:
    if not isinstance(s, dict) or s.get("score") is None:
        return None
    hl = None
    if prev and prev.get("pages_complete") is not None and (s.get("pages_complete") or 0) > prev["pages_complete"]:
        hl = f"page {s.get('pages_complete')} complete: negotiation points {prev.get('neg_points')} → {s.get('neg_points')}"
    text = f"score {s.get('score')} · rank {s.get('rank')} · negotiation points {s.get('neg_points')}"
    if prev and prev.get("rank") != s.get("rank"):
        text += f" (rank {prev.get('rank')} → {s.get('rank')})"
    ev = event(source, f"{at}|{s.get('score')}|{s.get('rank')}", at, "game", None, "score", text, None, hl)
    if ev:
        ev["score"] = {k: s.get(k) for k in SCORE_KEYS + ("market", "duel_points", "ladder_points", "cash")}
    return ev


def score_view_points(text: str, day: dt.date) -> list:
    """Readings from live.py's score.view.log (terminal output with colours) as dicts with ts."""
    text = re.sub(r"\x1b\[(K|2J|H)", "\n", text)
    text = ANSI.sub("", text)
    pts, cur = [], None
    fields = [("score", r"(?<![a-z_])score ([\d.]+)"), ("rank", r"(?<![a-z_])rank (\d+)"),
              ("market", r"(?<![a-z_])market ([\d.]+)"), ("neg_points", r"neg_points ([\d.]+)"),
              ("duel_points", r"duel_points ([\d.]+)"), ("ladder_points", r"ladder_points ([\d.]+)"),
              ("cash", r"(?<![a-z_])cash (\d+)"), ("pages_complete", r"pages complete (\d+)")]
    for line in text.splitlines():
        m = re.search(r"-------- (\d\d):(\d\d):(\d\d)\s+tick (\d+)", line)
        if m:
            h, mi, s, tick = (int(x) for x in m.groups())
            cur = {"ts": dt.datetime(day.year, day.month, day.day, h, mi, s, tzinfo=LOCAL_TZ).isoformat(), "tick": tick}
            pts.append(cur)
            continue
        if cur is None or "leaderboard" in line or re.match(r"\s*#\d", line):
            continue
        for k, pat in fields:
            if k not in cur:
                mm = re.search(pat, line)
                if mm:
                    cur[k] = float(mm.group(1)) if "." in mm.group(1) else int(mm.group(1))
    return [p for p in pts if "score" in p]


# ---------- public view ----------

PUBLIC_DECISIONS = {"offer", "bid"}  # posts on a public board; accepts and dealer deals stay private
PRIVATE_BITS = re.compile(r"\s*\((?:floor|cap)[^)]*\)|,?\s*our surplus [-\d.]+|,?\s*limit [-\d.]+|\bworth [-\d.]+|"
                          r"\bour value [-\d.]+", re.I)
CARD = re.compile(r"^[A-Z]{3}-\d\d$")


def public_text(e: dict) -> str:
    """Only what already sits on a public board: posts confirmed as made (our listings and bids), crosses on our venue
    during a Market Test, our public announcements, the leaderboard. A price we only planned, a cancellation, a duel or
    a dealer negotiation never shows."""
    kind, src, text = e.get("kind"), e.get("src"), e.get("text") or ""
    if kind == "offer" and src in ("rastro-seller", "market-desk") and e.get("posted"):
        return PRIVATE_BITS.sub("", text).strip()
    if kind in ("match", "result") and src == "broker":
        return text
    if kind == "announce" and src == "announce":
        return text
    if kind == "decision" and e.get("posted"):
        w = text.split()
        if len(w) > 1 and w[0] in PUBLIC_DECISIONS and CARD.match(w[1]):
            return f"{w[0]} {w[1]}"
    return ""


def public_view(e: dict) -> dict:
    """Who talked to whom and when, plus public_text. Never a why, a highlight (they come from our holdings), a value,
    a floor or limit, cash, a negotiation term, or the text of a message, a bus post or a lane's thought."""
    out = {k: e[k] for k in ("id", "ts", "src", "dst", "kind", "source") if k in e}
    out["why"] = None
    if e.get("kind") == "score":
        s = e.get("score") or {}
        out["score"] = {"score": s.get("score"), "rank": s.get("rank")}
        out["text"] = f"score {s.get('score')} · rank {s.get('rank')}"
    else:
        out["text"] = public_text(e)
    return out


# ---------- folding ----------

class Folder:
    """Reads every source from where it stopped last time and returns the new events. State lives in swarm-state.json."""

    def __init__(self, live: Path, repo: Path, state: dict | None = None, bus: bool = True, now=time.time):
        self.live, self.repo, self.bus, self.now = Path(live), Path(repo), bus, now
        self.st = state or {}
        self.st.setdefault("offsets", {})
        self.st.setdefault("days", {})
        self.st.setdefault("bus_seen", [])
        self.last_bus = 0.0

    def _new_lines(self, path: Path):
        """Complete lines added since the last call, with the byte offset each one starts at."""
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            return []
        off = self.st["offsets"].get(key, 0)
        if size < off:
            off = 0  # truncated or replaced
        if size == off:
            return []
        with open(path, "rb") as f:
            f.seek(off)
            chunk = f.read(size - off)
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        out, pos = [], off
        for raw in chunk[: end + 1].split(b"\n")[:-1]:
            out.append((pos, raw.decode("utf-8", "replace")))
            pos += len(raw) + 1
        self.st["offsets"][key] = off + end + 1
        return out

    def agents(self, name: str) -> list:
        path = self.live / name
        lines = self._new_lines(path)
        if not lines:
            return []
        days = self.st["days"]
        if name not in days:
            mday = dt.datetime.fromtimestamp(path.stat().st_mtime, LOCAL_TZ).date()
            days[name] = {"day": first_day([l for _, l in lines], mday).isoformat(), "last": None}
        d = days[name]
        day, last, out = dt.date.fromisoformat(d["day"]), d["last"], []
        for off, line in lines:
            s = _secs(line)
            if s is None:
                continue
            if last is not None and s < last - 6 * 3600:
                day += dt.timedelta(days=1)
            last = s
            ev = agents_event(name, str(off), day, line)
            if ev:
                out.append(ev)
                out += lane_reads(ev)
        d["day"], d["last"] = day.isoformat(), last
        return out

    def jsonl(self, path: Path, make) -> list:
        out = []
        for off, line in self._new_lines(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                ev = make(f"{path.parent.name}/{path.name}", str(off), r)
                if ev:
                    out.append(ev)
        return out

    def bots(self) -> list:
        out = []
        for folder in BOT_DIRS:
            for p in sorted(glob.glob(str(self.repo / "logs" / folder / "20??-??-??.jsonl"))):
                out += self.jsonl(Path(p), lambda src, key, r, f=folder: bot_event(src, key, f, r))
        return out

    def score(self) -> list:
        out = []
        if not self.st.get("score_history"):
            self.st["score_history"] = True
            prev = None
            hist = self.repo / "logs" / "score.jsonl"
            if hist.exists():
                for line in hist.read_text(errors="replace").splitlines():
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    s = dict(r.get("score") or {}, cash=r.get("cash"))
                    ev = score_event("score.jsonl", r.get("ts"), s, prev)
                    if ev:
                        out.append(ev)
                        prev = s
            view = self.live / "score.view.log"
            if view.exists():
                day = dt.datetime.fromtimestamp(view.stat().st_mtime, LOCAL_TZ).date()
                for p in score_view_points(view.read_text(errors="replace"), day):
                    rd = event("score.view.log", f"read|{p['ts']}", p["ts"], "d-me", "live-views", "read",
                               f"reads /api/me: score {p.get('score')}")
                    if rd:
                        out.append(rd)
                    if prev and all(p.get(k) == prev.get(k) for k in SCORE_KEYS):
                        continue
                    ev = score_event("score.view.log", p["ts"], p, prev)
                    if ev:
                        out.append(ev)
                        prev = p
            if prev:
                self.st["score_last"] = {k: prev.get(k) for k in SCORE_KEYS}
        try:
            snap = json.loads((self.live / "score.state.json").read_text())
        except (OSError, ValueError):
            return out
        s, prev = snap.get("prev") or {}, self.st.get("score_last")
        if snap.get("keyed") and snap.get("keyed") != self.st.get("score_keyed"):
            self.st["score_keyed"] = snap.get("keyed")
            rd = event("score.state.json", f"read|{snap.get('keyed')}", snap.get("keyed"), "d-me", "live-views", "read",
                       f"reads /api/me: score {s.get('score')}")
            if rd:
                out.append(rd)
        if s and not (prev and all(s.get(k) == prev.get(k) for k in SCORE_KEYS)):
            ev = score_event("score.state.json", snap.get("keyed") or self.now(), s, prev)
            if ev:
                out.append(ev)
                self.st["score_last"] = {k: s.get(k) for k in SCORE_KEYS}
        return out

    def feed(self) -> list:
        out = []
        for off, line in self._new_lines(self.repo / "logs" / "feed" / "feed.jsonl"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ev = event("feed.jsonl", str(off), r.get("seen_at"), "recorder", "d-feed", "collect", f"records {r.get('type')}")
            if ev:
                out.append(ev)
        return out

    def updates(self) -> list:
        """A hand-set file or a snapshot that changes (new duel params, new floors, a fresh me.json) is news."""
        out, seen = [], self.st.setdefault("mtimes", {})
        for did, d in DATA.items():
            if d["kind"] == "live" or not d["fresh"]:
                continue
            base, pat = d["fresh"].split(":", 1)
            path = (self.live if base == "live" else self.repo) / pat
            try:
                mt = path.stat().st_mtime
            except OSError:
                continue
            if seen.get(did) != mt:
                seen[did] = mt
                ev = event("mtime", f"{did}|{mt}", mt, did, None, "update", f"{d['label']} changed")
                if ev:
                    out.append(ev)
        return out

    def throttle(self, evs: list) -> list:
        last, out = self.st.setdefault("last_read", {}), []
        for e in evs:
            if e["kind"] in ("read", "collect"):
                k, t = f"{e['src']}>{e['dst']}", dt.datetime.fromisoformat(e["ts"]).timestamp()
                if t - last.get(k, 0) < READ_GAP:
                    continue
                last[k] = t
            out.append(e)
        return out

    def team_bus(self, every: float = 60.0) -> list:
        if not self.bus or self.now() - self.last_bus < every:
            return []
        self.last_bus = self.now()
        seen = set(self.st["bus_seen"])
        new = [e for e in bus_events(fetch_bus()) if e["id"] not in seen]
        self.st["bus_seen"] = sorted(seen | {e["id"] for e in new})
        return new

    def fold(self) -> list:
        out = self.agents("agents.log") + self.agents("agents-mini.log")
        out += self.jsonl(self.live / "decisions.jsonl", decision_event)
        out += self.bots() + self.score() + self.feed() + self.updates() + self.team_bus()
        return self.throttle(sorted(out, key=lambda e: e["ts"]))


def out_dir_ok(out: Path) -> bool:
    """The Mini's shares are mounted read-only for everyone but the Mini: never write into /Volumes."""
    return not str(out.resolve()).startswith("/Volumes/")


class Store:
    def __init__(self, out: Path, public: bool = False):
        self.out, self.lock, self.events, self.ids = Path(out), threading.Lock(), [], set()
        self.path, self.public, self.off = self.out / EVENTS, public, 0
        self.refresh()

    def refresh(self) -> int:
        """Pick up lines another process appended (serve mode reads the file the run process writes). One lock covers
        read, dedupe and cursor, so two requests at once cannot both advance the cursor over the same bytes."""
        with self.lock:
            try:
                size = self.path.stat().st_size
            except OSError:
                return 0
            if size <= self.off:
                return 0
            with open(self.path, "rb") as f:
                f.seek(self.off)
                chunk = f.read(size - self.off)
            end = chunk.rfind(b"\n")
            if end < 0:
                return 0
            new = []
            for line in chunk[: end + 1].decode("utf-8", "replace").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("id") not in self.ids:
                    self.ids.add(e.get("id"))
                    new.append(public_view(e) if self.public else e)
            self.events.extend(new)
            self.off += end + 1
            return len(new)

    def state(self) -> dict:
        try:
            return json.loads((self.out / STATE).read_text())
        except (OSError, ValueError):
            return {}

    def add(self, evs: list, state: dict) -> int:
        new = [e for e in evs if e["id"] not in self.ids]
        with self.lock:
            if new:
                with open(self.path, "a") as f:
                    for e in new:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
                for e in new:
                    self.ids.add(e["id"])
                self.events.extend(new)
                self.off = self.path.stat().st_size
            tmp = self.out / (STATE + ".tmp")
            tmp.write_text(json.dumps(state))
            os.replace(tmp, self.out / STATE)
        return len(new)

    def since(self, n: int) -> dict:
        with self.lock:
            n = max(0, min(n, len(self.events)))
            return {"events": self.events[n:], "next": len(self.events)}


def data_sources(live: Path, repo: Path, now: float) -> dict:
    out = {}
    for did, d in DATA.items():
        mt = None
        if d["fresh"]:
            base, pat = d["fresh"].split(":", 1)
            paths = glob.glob(str((live if base == "live" else repo) / pat))
            mts = [os.path.getmtime(p) for p in paths if os.path.exists(p)]
            mt = max(mts) if mts else None
        out[did] = dict(d, fresh_at=to_local_iso(mt) if mt else None, age_s=round(now - mt) if mt else None)
    return out


def heartbeats(live: Path, repo: Path) -> dict:
    hb = {}
    for p in glob.glob(str(repo / "logs" / "state" / "desk-*.json")):
        try:
            d = json.loads(Path(p).read_text())
        except (OSError, ValueError):
            continue
        name = Path(p).stem.replace("desk-", "")
        hb[BOT_DIRS.get(name, name)] = {"tick": d.get("tick"), "time": to_local_iso(d.get("time")),
                                        "mode": d.get("mode")}
    files = {}
    for name in ("agents.log", "agents-mini.log", "decisions.jsonl", "score.state.json"):
        try:
            files[name] = to_local_iso((live / name).stat().st_mtime)
        except OSError:
            files[name] = None
    return {"desks": hb, "files": files, "duel_lock": (repo / "results" / "duel.lock").exists(),
            "stop": (repo / "logs" / "state" / "STOP").exists()}


def make_handler(store: Store, live: Path, repo: Path, token: str | None, serving_only: bool = False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if token and not hmac.compare_digest(q.get("t", [""])[0].encode(), token.encode()):
                return self._send(403, b"forbidden\n", "text/plain")
            if u.path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/events":
                try:
                    n = int(q.get("since", ["0"])[0])
                except ValueError:
                    n = 0
                if serving_only:
                    store.refresh()
                return self._send(200, json.dumps(store.since(n)).encode(), "application/json")
            if u.path == "/meta":
                body = {"nodes": NODES, "now": to_local_iso(time.time()), "public": store.public,
                        "events_file": EVENTS if store.public else str(store.path),
                        "data": data_sources(live, repo, time.time()), **heartbeats(live, repo)}
                return self._send(200, json.dumps(body).encode(), "application/json")
            return self._send(404, b"not found\n", "text/plain")
    return Handler


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def bind_problem(host: str, token: str | None, public: bool) -> str | None:
    """Why a server must not start, or None. The private view shows whys, values and cash: always behind a token.
    Nothing listens on a wildcard address; expose a port with `tailscale serve` (tailnet) or `funnel` (public)."""
    if host in ("", "0.0.0.0", "::", "*"):
        return f"refusing to listen on {host or 'every interface'}: use 127.0.0.1 with tailscale serve/funnel, or the tailnet IP"
    if token is not None and len(token) < 16:
        return "SWARM_TOKEN must be at least 16 characters"
    if not public and not token:
        return "the private view needs SWARM_TOKEN (it shows decisions' whys, private values and cash)"
    if host not in LOOPBACK and not token:
        return f"refusing to listen on {host} without SWARM_TOKEN"
    return None


def fold_loop(folder: Folder, store: Store, interval: float, stop: threading.Event):
    while not stop.is_set():
        try:
            store.add(folder.fold(), folder.st)
        except Exception as e:  # keep serving whatever we have
            print(f"swarm: fold failed: {e!r} {getattr(e, 'filename', '') or ''}", file=sys.stderr)
        stop.wait(interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "fold", "plan", "serve"))
    ap.add_argument("--live", default=os.path.expanduser("~/bazaar-live"))
    ap.add_argument("--repo", default=str(HERE.parent))
    ap.add_argument("--out", default=None, help="where swarm-events.jsonl lives (default: --live)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--no-bus", action="store_true", help="do not read the team bus through gh")
    ap.add_argument("--public", action="store_true", help="serve: strip private values, whys and internal texts")
    a = ap.parse_args(argv)
    live, repo = Path(a.live).expanduser(), Path(a.repo).expanduser()
    out = Path(a.out).expanduser() if a.out else live
    if a.cmd == "plan":
        evs = Folder(live, repo, {}, bus=not a.no_bus).fold()
        kinds, srcs = {}, {}
        for e in evs:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            srcs[e["src"]] = srcs.get(e["src"], 0) + 1
        print(json.dumps({"events": len(evs), "kinds": kinds, "sources": srcs,
                          "first": evs[0]["ts"] if evs else None, "last": evs[-1]["ts"] if evs else None}, indent=1))
        return 0
    if a.public and a.cmd != "serve":
        print("swarm: --public only goes with serve (a second, read-only view of the same file)", file=sys.stderr)
        return 2
    token = os.environ.get("SWARM_TOKEN") or None
    if a.cmd in ("run", "serve"):
        why = bind_problem(a.host, token, a.public)
        if why:
            print(f"swarm: {why}", file=sys.stderr)
            return 2
    if a.cmd == "serve":
        store = Store(out, public=a.public)
        srv = ThreadingHTTPServer((a.host, a.port), make_handler(store, live, repo, token, serving_only=True))
        print(f"swarm: serving {'PUBLIC ' if a.public else ''}view of {store.path} on http://{a.host}:{a.port}/")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if not out_dir_ok(out):
        print(f"swarm: refusing to write into {out}; pass --out to a local folder", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out)
    folder = Folder(live, repo, store.state(), bus=not a.no_bus)
    if a.cmd == "fold":
        print(f"swarm: {store.add(folder.fold(), folder.st)} new events → {store.path}")
        return 0
    stop = threading.Event()
    threading.Thread(target=fold_loop, args=(folder, store, a.interval, stop), daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(store, live, repo, token))
    print(f"swarm: serving http://{a.host}:{a.port}/" + ("?t=<SWARM_TOKEN>" if token else "") + f"  events → {store.path}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
