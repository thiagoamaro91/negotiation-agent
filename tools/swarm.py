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
  python3 tools/swarm.py run                                  # fold every 5 s and serve http://127.0.0.1:8777
  SWARM_TOKEN=... python3 tools/swarm.py run --host 0.0.0.0   # same, reachable over the tailnet with ?t=<token>
  python3 tools/swarm.py fold                                 # fold once and exit
  python3 tools/swarm.py plan                                 # fold once into memory, print counts, write nothing
development on another machine, against the Mini's shares (read-only there, so --out must be local):
  python3 tools/swarm.py run --live /Volumes/bazaar-live --repo /Volumes/bazaar --out /tmp/swarm
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
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

HERE = Path(__file__).resolve().parent
PAGE = HERE / "swarm.html"
BUS_REPO = "thiagoamaro91/negotiation-agent"
BUS_ISSUE = 25
EVENTS = "swarm-events.jsonl"
STATE = "swarm-state.json"
TEXT = 220
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo

SECRET = re.compile(r"tk-[A-Za-z0-9-]{6,}|bk_[A-Za-z0-9]+|adm_[A-Za-z0-9]+")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
AGENT_LINE = re.compile(r"^(\d\d):(\d\d):(\d\d) \[([^\]]+)\] (says|does): (.*)$")
MESSAGE_TO = re.compile(r"^message to ([\w.-]+): (.*)$")
BUS_HEADER = re.compile(r"<!-- team-bus (\{.*?\}) -->", re.S)

# Nodes the page knows by name. Anything else that shows up (a new lane, a new bus session) is added on the fly.
NODES = {
    "thiago": {"label": "Thiago", "layer": "people"},
    "hector": {"label": "Hector", "layer": "people"},
    "jay": {"label": "Jay", "layer": "people"},
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
    "teams": {"label": "Other teams", "layer": "world"},
    "dealers": {"label": "Dealers", "layer": "world"},
    "rastro": {"label": "El Rastro", "layer": "world"},
    "bench": {"label": "Market Test", "layer": "world"},
    "game": {"label": "Scoreboard", "layer": "world"},
}
ALIASES = {"team-lead": "conductor", "thiago-air-f7": "conductor", "thiago-mini-conductor": "mini-conductor"}
PEOPLE = {"thiagoamaro91": "thiago", "hector14mv": "hector", "jpshankarpurieu2025-rgb": "jay",
          "thiago": "thiago", "hector": "hector", "jay": "jay"}
DECISION_LANES = {"trades": "lane-c-trades", "ladder": "lane-d-ladder", "duel": "lane-duel", "market": "lane-market",
                  "conductor": "conductor"}
# Rows logged with lane "conductor" belong to whoever conducted at that moment.
HANDOFFS = [("2026-10-03T18:34:16+02:00", "conductor", "thiago-air-f8")]
BOT_DIRS = {"duel": "duel", "broker": "broker", "announce": "announce", "rastro": "rastro-seller",
            "market": "market-desk", "lease": "lease", "concierge": "concierge",
            "abuela": "dealer-bots", "chato": "dealer-bots", "pilar": "dealer-bots", "picaros": "dealer-bots",
            "taller": "dealer-bots"}
DEALER_WORDS = ("pilar", "chato", "picaros", "pícaros", "abuela", "taller", "workshop", "ernesto")


def redact(s) -> str:
    return SECRET.sub("<redacted>", str(s))


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
    return ALIASES.get(name, name)


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
    return event(source, key, iso, decision_lane(r.get("lane"), iso),
                 counterparty_node(r.get("counterparty"), r.get("venue"), why), "decision", text, why, hl)


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
        if ev == "accept":
            resp = r.get("resp") if isinstance(r.get("resp"), dict) else {}
            return E("teams", "deal", f"duel {d}: accepts {resp.get('price', price)}")
        if ev == "result":
            return E("teams", "result", f"duel {d}: {r.get('status')} at {price}, our surplus {r.get('our_surplus')}")
        return None  # hold and rival: the rival's words stay out
    if node == "broker":
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
            return E("rastro", "offer", f"lists {r.get('card')} at {r.get('price')} (floor {r.get('floor')})")
        if ev == "their_message":
            return E(node, "msg", "a message from another team (text not replayed)", None, "teams")
        if ev in ("not_held", "bid_below_floor"):
            return E("rastro", "skip", f"{ev.replace('_', ' ')}: {r.get('card', '')}")
        return None
    if node == "market-desk" and ev == "sent":
        return E("rastro", "offer", f"{r.get('op')} {r.get('kind')} {r.get('card')} at {r.get('price')}")
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
            dst = to[0] if len(to) == 1 and to[0] in ("thiago", "hector", "jay") else "bus"
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
        if s and not (prev and all(s.get(k) == prev.get(k) for k in SCORE_KEYS)):
            ev = score_event("score.state.json", snap.get("keyed") or self.now(), s, prev)
            if ev:
                out.append(ev)
                self.st["score_last"] = {k: s.get(k) for k in SCORE_KEYS}
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
        out += self.bots() + self.score() + self.team_bus()
        return sorted(out, key=lambda e: e["ts"])


def out_dir_ok(out: Path) -> bool:
    """The Mini's shares are mounted read-only for everyone but the Mini: never write into /Volumes."""
    return not str(out.resolve()).startswith("/Volumes/")


class Store:
    def __init__(self, out: Path):
        self.out, self.lock, self.events, self.ids = Path(out), threading.Lock(), [], set()
        self.path = self.out / EVENTS
        if self.path.exists():
            for line in self.path.read_text(errors="replace").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("id") not in self.ids:
                    self.ids.add(e.get("id"))
                    self.events.append(e)

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
            tmp = self.out / (STATE + ".tmp")
            tmp.write_text(json.dumps(state))
            os.replace(tmp, self.out / STATE)
        return len(new)

    def since(self, n: int) -> dict:
        with self.lock:
            n = max(0, min(n, len(self.events)))
            return {"events": self.events[n:], "next": len(self.events)}


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


def make_handler(store: Store, live: Path, repo: Path, token: str | None):
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
            if token and q.get("t", [""])[0] != token:
                return self._send(403, b"forbidden\n", "text/plain")
            if u.path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/events":
                try:
                    n = int(q.get("since", ["0"])[0])
                except ValueError:
                    n = 0
                return self._send(200, json.dumps(store.since(n)).encode(), "application/json")
            if u.path == "/meta":
                body = {"nodes": NODES, "now": to_local_iso(time.time()), "events_file": str(store.path),
                        **heartbeats(live, repo)}
                return self._send(200, json.dumps(body).encode(), "application/json")
            return self._send(404, b"not found\n", "text/plain")
    return Handler


def fold_loop(folder: Folder, store: Store, interval: float, stop: threading.Event):
    while not stop.is_set():
        try:
            store.add(folder.fold(), folder.st)
        except Exception as e:  # keep serving whatever we have
            print(f"swarm: fold failed: {e!r} {getattr(e, 'filename', '') or ''}", file=sys.stderr)
        stop.wait(interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "fold", "plan"))
    ap.add_argument("--live", default=os.path.expanduser("~/bazaar-live"))
    ap.add_argument("--repo", default=str(HERE.parent))
    ap.add_argument("--out", default=None, help="where swarm-events.jsonl lives (default: --live)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--no-bus", action="store_true", help="do not read the team bus through gh")
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
    token = os.environ.get("SWARM_TOKEN") or None
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
