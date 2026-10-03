"""Live Team 3 dashboard: score and rank, cash, every dealer conversation as a price chart (her line vs ours),
album pages, leaderboard, the El Rastro board with our private value of each listing, our feed, and what fires next.

    python3 tools/dashboard.py              # http://127.0.0.1:8765
    python3 tools/dashboard.py --lan        # also reachable from teammates' laptops, behind a random token
    DASH_TOKEN=... python3 tools/dashboard.py && tailscale funnel --bg 8765   # public HTTPS link, token-gated

The team key stays in this process; the page only ever sees /data. Public data is read without the key, so the
dashboard uses ~0.4 keyed requests per second and leaves the 5 req/s budget to the agents.

La Celestina panel (our own venue and its broker, read-only). It finds our venue keylessly in /api/venues (owner t03,
status open; v20 if none is listed) and reads its live offers from /api/venues/<id>/offers, at most once every 10 s.
The broker's side comes from the files agent/broker.py writes: the heartbeat logs/state/desk-broker.json (stale after
90 s) and the event log logs/broker/<YYYY-MM-DD>.jsonl, where every match the server accepted is a "matched" row
(tick, sell, buy, price, result) resolved against the book rows before it. Those files live under the broker's
checkout, which may not be this one:

    python3 tools/dashboard.py --broker-root ~/bazaar      # or BROKER_ROOT=~/bazaar; default: this repo
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402

PAGE = ROOT / "tools" / "dashboard.html"
HISTORY = ROOT / "logs" / "dashboard_history.jsonl"
STATE: dict = {"data": None, "error": None, "updated": 0.0, "celestina": None}
LOCK = threading.Lock()
TEAM = "t03"

CEL_FALLBACK = "v20"     # our venue's id if /api/venues does not list an open one of ours
CEL_VENUE_EVERY = 10.0   # seconds between keyless reads of /api/venues and our venue's offers
CEL_STALE_AFTER = 90.0   # seconds without a heartbeat before the broker shows as stale
CEL_MATCHES = 10         # matches listed on the panel (the count covers the whole day)
CEL_OFFERS = 20          # offers listed on the panel (the count covers them all)
CEL_ERRORS = ("read_error", "send_error", "bad_book", "error")  # broker.py events that mean something went wrong


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def public(url: str, path: str):
    """Keyless read: does not touch the team key's rate limit."""
    with urllib.request.urlopen(url + path, timeout=10) as r:
        return json.loads(r.read())


def price_of(offer: dict | None):
    if not offer:
        return None
    return (offer.get("want") or {}).get("cash") or (offer.get("give") or {}).get("cash") or None


def refs(side: dict) -> list[str]:
    out = [a.get("ref") for a in side.get("assets") or [] if isinstance(a, dict)]
    out += [t.split(":", 1)[-1] for t in side.get("types") or []]
    return [r for r in out if r]


def feed_line(e: dict) -> str | None:
    p, t = e.get("payload") or {}, e.get("type")
    if t == "settlement":
        items = ", ".join(i.get("ref") or i.get("name") or "?" for i in p.get("items") or []) or "cash"
        parties = " / ".join(p.get("parties") or [])
        return f"{p.get('kind')} {parties}: {items} at {p.get('price')} P"
    if t == "gift.given":
        return f"gift to {p.get('team')}: {', '.join(p.get('cards') or p.get('packs') or [])}"
    if t in ("announcement", "level.announced", "level.activated", "schedule.fired", "set.released", "day.opened",
             "day.closed", "duels.scheduled", "persona.strike", "persona.cooloff", "flag.raised", "egg.found"):
        return p.get("text") or p.get("note") or p.get("name") or t
    if t == "thread.opened" and p.get("team") == TEAM:
        return f"we opened #{p.get('thread')} with {p.get('with')}: {json.dumps(p.get('topic'))}"
    return None


# ---------------------------------------------------------------- La Celestina: our venue and its broker (pure parts)

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _owner(v: dict):
    for k in ("owner", "owner_team", "team", "team_id"):
        o = v.get(k)
        if isinstance(o, dict):
            o = o.get("id") or o.get("team")
        if o:
            return str(o)
    return None


def find_our_venue(venues, team: str = TEAM, fallback: str = CEL_FALLBACK) -> dict:
    """Our venue from /api/venues: the open one `team` owns, else any it owns, else the fallback id alone."""
    if isinstance(venues, dict):
        venues = venues.get("venues") or venues.get("items") or []
    ours = [v for v in venues or [] if isinstance(v, dict) and _owner(v) == team]
    pick = next((v for v in ours if str(v.get("status") or "").lower() == "open"), ours[0] if ours else None)
    if pick is None:
        return {"id": fallback, "name": None, "status": None, "fee_bps": None, "fee_per_card": None,
                "mechanism": None, "listed": False}
    rules = pick.get("rules") if isinstance(pick.get("rules"), dict) else {}
    return {"id": str(pick.get("id") or fallback), "name": pick.get("name"), "status": pick.get("status"),
            "fee_bps": pick.get("fee_bps"), "fee_per_card": pick.get("fee_per_card"),
            "mechanism": rules.get("mechanism") or pick.get("mechanism"), "listed": True}


def side_text(side) -> str:
    """One side of an offer in a few words: "LAV-09", "40 P", "LAV-09 + 5 P"; "-" when empty."""
    if not isinstance(side, dict):
        return "-"
    parts = refs(side)
    if _num(side.get("cash")) and side["cash"]:
        parts.append(f"{side['cash']} P")
    return " + ".join(str(p) for p in parts) or "-"


def offer_rows(board, limit: int = CEL_OFFERS) -> dict:
    """The live offers on a venue (GET /api/venues/<id>/offers), as rows for the panel."""
    offers = board.get("offers", []) if isinstance(board, dict) else board
    rows = []
    for o in offers or []:
        if not isinstance(o, dict):
            continue
        give, want = (o.get(k) if isinstance(o.get(k), dict) else {} for k in ("give", "want"))
        rows.append({"id": o.get("id"), "maker": o.get("maker"), "gives": side_text(give), "wants": side_text(want),
                     "price": want.get("cash") or give.get("cash") or None, "expires": o.get("expires_tick")})
    return {"count": len(rows), "rows": rows[:limit]}


def heartbeat_view(hb, now: float, stale_after: float = CEL_STALE_AFTER) -> dict:
    """The broker's heartbeat (logs/state/desk-broker.json) as the panel shows it: alive, stale or missing."""
    if not isinstance(hb, dict):
        return {"state": "missing"}
    age = round(max(0.0, now - hb["epoch"]), 1) if _num(hb.get("epoch")) else None
    last = hb.get("last_decision") if isinstance(hb.get("last_decision"), dict) else {}
    out = {"state": "alive" if age is not None and age <= stale_after else "stale", "age": age,
           "decision_tick": last.get("tick"), "decision_matches": len(last.get("matches") or [])}
    for k in ("tick", "policy", "mode", "what", "time", "reads", "read_errors_in_a_row", "sent", "accepted",
              "refused", "dropped"):
        out[k] = hb.get(k)
    return out


def new_log_state() -> dict:
    return {"offers": {}, "matches": [], "count": 0, "refused": 0, "dropped": 0, "errors": 0, "would": 0,
            "books": 0, "run_start": None, "last_error": None}


def _is_bench(offer_id) -> bool:
    s = str(offer_id)
    return s.startswith("b") and "-" in s  # bench ids look like "b12-7"; public offers have numeric ids


def match_row(row: dict, offers: dict) -> dict:
    """A "matched" event of agent/broker.py (tick, sell, buy, price, result) with its card and its two sides, read
    from the last book the broker logged before it (the book it planned the match on)."""
    sell_id, buy_id = row.get("sell"), row.get("buy")
    s, b = offers.get(str(sell_id)) or {}, offers.get(str(buy_id)) or {}
    s_give = s.get("give") if isinstance(s.get("give"), dict) else {}
    b_want = b.get("want") if isinstance(b.get("want"), dict) else {}
    bench = _is_bench(sell_id)
    card = next(iter(refs(s_give) or refs(b_want)), None)
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    return {"tick": row.get("tick"), "time": str(row.get("ts") or "")[11:19], "price": row.get("price"),
            "card": card, "bench": bench, "bench_run": str(sell_id).split("-")[0] if bench else None,
            "sell": sell_id, "buy": buy_id, "seller": s.get("maker") or ("bench" if bench else None),
            "buyer": b.get("maker") or ("bench" if bench else None), "status": result.get("status")}


def fold_broker_log(st: dict, lines, keep: int = CEL_MATCHES) -> dict:
    """Adds lines of logs/broker/<date>.jsonl to the running summary `st` (from new_log_state()). Only "matched"
    counts as a match: the server accepted it. watch mode's "WOULD" rows are counted apart, never as matches."""
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ev = row.get("event")
        if ev == "book":
            book = row.get("book") if isinstance(row.get("book"), dict) else {}
            st["offers"] = {str(o["id"]): o for kind in ("offers", "bench_offers") for o in book.get(kind) or []
                            if isinstance(o, dict) and "id" in o}
            st["books"] += 1
        elif ev == "matched":
            st["count"] += 1
            st["matches"].append(match_row(row, st["offers"]))
            del st["matches"][:-keep]
        elif ev == "WOULD":
            st["would"] += 1
        elif ev == "refused":
            st["refused"] += 1
        elif ev == "dropped":
            st["dropped"] += 1
        elif ev in CEL_ERRORS:
            st["errors"] += 1
            st["last_error"] = {"tick": row.get("tick"), "time": str(row.get("ts") or "")[11:19], "event": ev,
                                "error": str(row.get("error") or row.get("kind") or "")[:160]}
        elif ev == "run_start":
            st["run_start"] = {"time": str(row.get("ts") or "")[11:19], "mode": row.get("mode"),
                               "policy": row.get("policy")}
    return st


def log_view(st: dict) -> dict:
    """The running summary without the book it keeps for lookups, newest match first."""
    return {**{k: v for k, v in st.items() if k != "offers"}, "matches": st["matches"][::-1]}


def summarize_broker_log(lines, keep: int = CEL_MATCHES) -> dict:
    return log_view(fold_broker_log(new_log_state(), lines, keep))


# ---------------------------------------------------------------- La Celestina: files and keyless reads

class BrokerLogTail:
    """Follows logs/broker/<today>.jsonl: reads only the bytes added since the last poll, whole lines only, and
    starts over on a new day's file or a file that shrank."""

    CHUNK = 16 << 20  # at most 16 MB per poll, so a long day's first read does not stall the page

    def __init__(self):
        self.path, self.pos, self.state = None, 0, new_log_state()

    def read(self, path: Path) -> dict:
        if path != self.path:
            self.path, self.pos, self.state = path, 0, new_log_state()
        try:
            size = path.stat().st_size
        except OSError:
            return {"exists": False, **log_view(self.state)}
        if size < self.pos:
            self.pos, self.state = 0, new_log_state()
        if size > self.pos:
            with path.open("rb") as f:
                f.seek(self.pos)
                chunk = f.read(min(size - self.pos, self.CHUNK))
            end = chunk.rfind(b"\n")
            if end >= 0:
                self.pos += end + 1
                fold_broker_log(self.state, chunk[:end + 1].decode("utf-8", "replace").splitlines())
        return {"exists": True, **log_view(self.state)}


class Celestina:
    """The La Celestina panel: our venue and its live offers (keyless, at most every CEL_VENUE_EVERY s), the broker's
    heartbeat and today's matches (files under broker_root, which agent/broker.py writes)."""

    def __init__(self, url: str, broker_root: Path, team: str = TEAM):
        self.url, self.root, self.team = url, Path(broker_root), team
        self.venue = find_our_venue([], team)
        self.offers = None
        self.venue_at = 0.0
        self.venue_error = self.offers_error = None
        self.tail = BrokerLogTail()

    def refresh_venue(self, now: float) -> None:
        if now - self.venue_at < CEL_VENUE_EVERY:
            return
        self.venue_at = now
        try:
            self.venue, self.venue_error = find_our_venue(public(self.url, "/api/venues"), self.team), None
        except Exception as e:  # keep the last venue we saw (or v20) and still read its offers
            self.venue_error = repr(e)[:200]
        try:
            board = public(self.url, f"/api/venues/{quote(str(self.venue['id']), safe='')}/offers")
            self.offers, self.offers_error = offer_rows(board), None
        except Exception as e:
            self.offers_error = repr(e)[:200]

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        self.refresh_venue(now)
        hb_path = self.root / "logs" / "state" / "desk-broker.json"
        try:
            hb = json.loads(hb_path.read_text())
        except (OSError, ValueError):
            hb = None
        log_path = self.root / "logs" / "broker" / (time.strftime("%Y-%m-%d", time.localtime(now)) + ".jsonl")
        return {"venue": self.venue, "venue_error": self.venue_error, "offers": self.offers,
                "offers_error": self.offers_error, "venue_age": round(now - self.venue_at, 1),
                "broker": heartbeat_view(hb, now), "log": {"file": log_path.name, **self.tail.read(log_path)},
                "stale_after": CEL_STALE_AFTER}


def build(b: Bazaar, url: str, catalog: dict, history: list) -> dict:
    me = b.me()
    threads = b.my_threads().get("threads", [])
    clock = public(url, "/api/clock")
    lb = public(url, "/api/leaderboard")
    sched = public(url, "/api/schedule")
    board = public(url, "/api/venues/rastro/offers")
    feed = public(url, "/api/feed?limit=300")
    dealers = public(url, "/api/dealers")
    levels = public(url, "/api/levels")

    cards = {c["id"]: {**c, "set": s["id"]} for s in catalog["sets"] for c in s["cards"]}
    aff = me.get("affinity") or {}
    held: dict[str, int] = {}
    for a in me.get("assets") or []:
        if a.get("kind") == "card":
            held[a["ref"]] = held.get(a["ref"], 0) + 1
    marg = (catalog.get("values") or {}).get("copy_marginals") or [1.0, 0.25, 0.1]

    def est_value(ref: str) -> float | None:
        c = cards.get(ref)
        if not c:
            return None
        k = held.get(ref, 0)
        return round(c["book"] * aff.get(c["set"], 1.0) * marg[min(k, len(marg) - 1)], 1)

    convs = []
    for t in sorted(threads, key=lambda x: -x["id"])[:10]:
        msgs = []
        for m in t.get("messages") or []:
            o = m.get("offer")
            msgs.append({"tick": m.get("tick"), "who": "us" if m.get("sender") == TEAM else "them",
                         "price": price_of(o), "final": bool((o or {}).get("final")), "text": m.get("text") or ""})
        convs.append({"id": t["id"], "with": t.get("with"), "kind": t.get("kind"), "topic": t.get("topic"),
                      "status": t.get("status"), "reason": t.get("closed_reason"), "created": t.get("created_tick"),
                      "messages": msgs})

    listings = []
    offers = board.get("offers", board) if isinstance(board, dict) else board
    fee_bps, fee_card = 500, 1
    for o in offers or []:
        give, want = o.get("give") or {}, o.get("want") or {}
        g, w = refs(give), refs(want)
        row = {"id": o["id"], "maker": o.get("maker"), "give": g, "give_cash": give.get("cash") or 0,
               "want": w, "want_cash": want.get("cash") or 0, "expires": o.get("expires_tick")}
        if len(g) == 1 and want.get("cash"):  # someone sells one card for cash: is it worth it to us?
            v = est_value(g[0])
            cost = want["cash"] + math.ceil(fee_bps * want["cash"] / 10000) + fee_card
            row.update(kind="sell", card=g[0], value=v, cost=cost, gain=None if v is None else round(v - cost, 1))
        elif len(w) == 1 and give.get("cash"):  # someone wants a card: what would handing over our last copy cost us?
            n, c = held.get(w[0], 0), cards.get(w[0])
            loss = round(c["book"] * aff.get(c["set"], 1.0) * marg[min(n - 1, len(marg) - 1)], 1) if n and c else None
            row.update(kind="buy", card=w[0], have=n, value=loss,
                       gain=None if loss is None else round(give["cash"] - loss, 1))
        listings.append(row)

    s = me.get("score") or {}
    point = {"t": time.strftime("%H:%M:%S"), "tick": me.get("tick"), "score": s.get("score"), "rank": s.get("rank"),
             "neg": s.get("negotiating"), "mkt": s.get("market"), "cash": me.get("cash")}
    if not history or history[-1]["tick"] != point["tick"] or history[-1]["score"] != point["score"]:
        history.append(point)
        del history[:-400]
        HISTORY.parent.mkdir(exist_ok=True)
        with HISTORY.open("a") as f:  # survives restarts of the dashboard
            f.write(json.dumps(point) + "\n")

    album = []
    for st in catalog["sets"]:
        page = [c for c in st["cards"] if c.get("page")]
        extra = [c for c in st["cards"] if not c.get("page")]
        album.append({"set": st["id"], "name": st["name"], "released": st["released"], "aff": aff.get(st["id"]),
                      "cards": [{"id": c["id"], "rarity": c["rarity"], "name": c["name"], "n": held.get(c["id"], 0)}
                                for c in page + extra]})

    now_h = sched.get("now_hours") or 0
    upcoming = [{"in_min": round((u["at_hours"] - now_h) * 60), "note": u.get("note"), "action": u.get("action")}
                for u in (sched.get("upcoming") or []) if u.get("at_hours", 0) >= now_h][:6]

    events = [{"tick": e.get("tick"), "type": e.get("type"), "text": feed_line(e),
               "ours": TEAM in json.dumps(e.get("payload") or {})}
              for e in (feed.get("events") or [])]
    events = [e for e in events if e["text"]][-40:][::-1]

    return {
        "me": {"name": me.get("name"), "cash": me.get("cash"), "level": me.get("level"), "unlocked": me.get("unlocked"),
               "score": s, "collection_value": me.get("collection_value"), "affinity": aff,
               "pages_complete": s.get("pages_complete"), "album_filled": (me.get("album") or {}).get("filled"),
               "album_slots": (me.get("album") or {}).get("slots")},
        "clock": {k: clock.get(k) for k in ("tick", "tick_seconds", "next_tick_in", "paused", "doors", "closes",
                                            "round_name", "today_name", "limits")},
        "leaderboard": [{k: t.get(k) for k in ("rank", "team", "name", "score", "negotiating", "market", "deals",
                                               "album_filled", "level")} for t in lb.get("teams") or []],
        "dealers": [{k: d.get(k) for k in ("id", "name", "level", "status", "title")}
                    for d in dealers.get("personas") or dealers.get("dealers") or []],
        "levels": levels.get("levels") or [],
        "conversations": convs, "listings": listings, "album": album, "upcoming": upcoming, "feed": events,
        "history": history, "reserve": 280, "server_time": time.strftime("%H:%M:%S"),
    }


def celestina_step(cel: Celestina) -> None:
    """The La Celestina panel, apart from build(): a key or server error up there must not blank our venue."""
    try:
        snap = cel.snapshot()
    except Exception as e:
        snap = {"error": repr(e)[:300]}
    with LOCK:
        STATE["celestina"] = snap


def poller(b: Bazaar | None, url: str, interval: float, cel: Celestina | None = None) -> None:
    if b is None:  # no team key: only the keyless La Celestina panel runs
        with LOCK:
            STATE["error"] = "no BAZAAR_KEY: keyed panels are off, La Celestina only"
        while True:
            if cel is not None:
                celestina_step(cel)
            time.sleep(interval)
    catalog, cat_at, history = None, 0.0, []
    score_log = ROOT / "logs" / "score.jsonl"
    if score_log.exists():
        for line in score_log.read_text().splitlines():
            try:
                r = json.loads(line)
                history.append({"t": r["ts"][11:19], "tick": r.get("tick"), "score": r["score"].get("score"),
                                "rank": r["score"].get("rank"), "neg": r["score"].get("negotiating"),
                                "mkt": r["score"].get("market"), "cash": r.get("cash")})
            except Exception:
                pass
    if HISTORY.exists():
        for line in HISTORY.read_text().splitlines()[-400:]:
            try:
                history.append(json.loads(line))
            except Exception:
                pass
    history.sort(key=lambda p: (p.get("tick") or 0))
    while True:
        try:
            if catalog is None or time.time() - cat_at > 300:
                catalog, cat_at = public(url, "/api/catalog"), time.time()
            data = build(b, url, catalog, history)
            with LOCK:
                STATE.update(data=data, error=None, updated=time.time())
        except BazaarError as e:
            with LOCK:
                STATE["error"] = f"{e.code}: {e.message}"
        except Exception as e:  # keep the dashboard alive through restarts and timeouts
            with LOCK:
                STATE["error"] = repr(e)[:300]
        if cel is not None:
            celestina_step(cel)
        time.sleep(interval)


def serve(port: int, token: str | None, host: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if token and parse_qs(u.query).get("t", [""])[0] != token:
                return self._send(403, b"forbidden", "text/plain")
            if u.path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/data":
                with LOCK:
                    body = json.dumps({**(STATE["data"] or {}), "error": STATE["error"], "celestina": STATE["celestina"],
                                       "age": round(time.time() - STATE["updated"], 1) if STATE["updated"] else None})
                return self._send(200, body.encode(), "application/json")
            return self._send(404, b"not found", "text/plain")

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces, behind a random token")
    ap.add_argument("--interval", type=float, default=4.0)
    ap.add_argument("--broker-root", default=os.environ.get("BROKER_ROOT") or str(ROOT),
                    help="checkout whose logs/ the broker writes (heartbeat, event log); env BROKER_ROOT; "
                         "default: this repo")
    args = ap.parse_args()
    url = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai").rstrip("/")
    key = os.environ.get("BAZAAR_KEY", "").strip()
    b = Bazaar(url, key) if key else None
    broker_root = Path(args.broker_root).expanduser().resolve()
    print(f"La Celestina: broker files under {broker_root}/logs", flush=True)
    cel = Celestina(url, broker_root)
    threading.Thread(target=poller, args=(b, url, args.interval, cel), daemon=True).start()
    # DASH_TOKEN (in .env) keeps the shared link stable across restarts, e.g. behind `tailscale funnel 8765`
    token = os.environ.get("DASH_TOKEN") or (secrets.token_urlsafe(8) if args.lan else None)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print(f"dashboard: http://127.0.0.1:{args.port}/" + (f"?t={token}" if token else ""), flush=True)
    if args.lan:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = "<this-mac-ip>"
        print(f"teammates:  http://{ip}:{args.port}/?t={token}", flush=True)
    serve(args.port, token, host)


if __name__ == "__main__":
    main()
