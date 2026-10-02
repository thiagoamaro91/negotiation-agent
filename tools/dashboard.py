"""Live Team 3 dashboard: score and rank, cash, every dealer conversation as a price chart (her line vs ours),
album pages, leaderboard, the El Rastro board with our private value of each listing, our feed, and what fires next.

    python3 tools/dashboard.py              # http://127.0.0.1:8765
    python3 tools/dashboard.py --lan        # also reachable from teammates' laptops, behind a random token

The team key stays in this process; the page only ever sees /data. Public data is read without the key, so the
dashboard uses ~0.4 keyed requests per second and leaves the 5 req/s budget to the agents.
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
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402

PAGE = ROOT / "tools" / "dashboard.html"
STATE: dict = {"data": None, "error": None, "updated": 0.0}
LOCK = threading.Lock()
TEAM = "t03"


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


def poller(b: Bazaar, url: str, interval: float) -> None:
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
            if token and parse_qs(u.query).get("t", [""])[0] != token:
                return self._send(403, b"forbidden", "text/plain")
            if u.path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/data":
                with LOCK:
                    body = json.dumps({**(STATE["data"] or {}), "error": STATE["error"],
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
    args = ap.parse_args()
    url = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai").rstrip("/")
    b = Bazaar(url, os.environ["BAZAAR_KEY"])
    threading.Thread(target=poller, args=(b, url, args.interval), daemon=True).start()
    token = secrets.token_urlsafe(8) if args.lan else None
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
