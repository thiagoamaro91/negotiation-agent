"""The Clearing House: teams hand in, in private, the cards they would sell (with the least they take) and the cards
they want (with the most they pay); at a set time a matcher pairs every profitable cross and tells each side the one
offer to post and the one offer to accept, spread over the participants' venues so every venue gets trades.

Why. Three things score: the value a team gains in trades with other teams at its private values, the value created
between other teams on a venue, and the Market Test. Most venues have zero trades today. A private book plus a
matcher turns the duplicates every team holds into trades that are profitable for both sides, on venues owned by
neither side, in one scheduled burst instead of hours of threads.

What it never does. It never holds, reads or sends a team key. Each team runs tools/clearing_client.py on its own
machine with its own key; the client sends here only card refs, asset ids and reservation prices. Values are stored
in <store>/state.json and served to nobody: /api/clearing/plan returns a team its own actions (card, price, venue,
counterparty) and nothing about anyone's reservation prices. The public /api/clearing/status shows who joined and
how many cards are in, never prices. No model runs here; every input is validated and nothing posted is interpreted.

Matching (`run`): for each card, every (have, want) pair of different teams with want.max >= have.min + venue fee is
a candidate; candidates are taken greedily by surplus (max - min), each asset and each want once. Price is the
midpoint of [min, max - fee], whole primas, so both sides keep half the surplus. Venue: a participant's open venue
owned by neither side, the one with the fewest trades this round (so the trades spread); else the cheapest other
open venue; else El Rastro. The seller posts the offer addressed `to` the buyer (nobody else can take it); the
buyer accepts it by id. The server watches the public books and the clients' reports to pass the offer id along.

    python3 tools/clearing.py serve --host 0.0.0.0 --port 8790 --store logs/clearing --public-url https://<tunnel> \\
        --admin-token "$CLEARING_ADMIN" [--run-at 12:05,13:20]
    python3 tools/clearing.py run --store logs/clearing            # match now (also POST /api/clearing/run with the admin token)
    python3 tools/clearing.py status --store logs/clearing
    python3 tools/clearing.py selftest                              # no network

Routes (JSON, no auth unless said, CORS open):
    GET  /, /agents.md                 instructions (text/markdown)
    GET  /api/clearing/status          teams joined, cards in, rounds, next run (no prices)
    POST /api/clearing/join            {"team": "t07", "venue": "v29"}        -> {"token": ...}; one token per team
    POST /api/clearing/book            {"token", "haves": [{"card","asset","min"}], "wants": [{"card","max"}]}  replaces
    GET  /api/clearing/plan?token=     the team's actions of the latest round
    POST /api/clearing/report          {"token", "action": id, "offer": id} | {"token", "action": id, "status": "accepted"|"failed", "error": "..."}
    POST /api/clearing/run             {"admin": token}  -> match now
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai").rstrip("/")
TEAM_RE = re.compile(r"^t\d{2}$")
REF_RE = re.compile(r"^[A-Z]{3}-\d{2}$")
VENUE_RE = re.compile(r"^(v\d{2}|rastro)$")
MAX_ITEMS = 60
MAX_BODY = 32_000
OFFER_TTL_TICKS = 80
PUBLIC_PATHS = re.compile(r"^/api/(venues|clock|venues/[A-Za-z0-9_-]{1,40}/offers)$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Refused(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code


# ---------------------------------------------------------------- public reads (keyless only)

def public_get(path: str, timeout: float = 8.0):
    if not PUBLIC_PATHS.match(path):
        raise ValueError(f"not a public path: {path}")
    req = urllib.request.Request(GAME_URL + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fee_of(venue: dict, price: int) -> int:
    bps, per = int(venue.get("fee_bps") or 0), int(venue.get("fee_per_card") or 0)
    return int(math.ceil(price * bps / 10000)) + per


# ---------------------------------------------------------------- validation

def clean_team(x) -> str:
    if not isinstance(x, str) or not TEAM_RE.match(x):
        raise Refused(400, "bad_team", "team must look like t07")
    return x


def clean_ref(x) -> str:
    if not isinstance(x, str) or not REF_RE.match(x):
        raise Refused(400, "bad_card", "card must look like LAV-03")
    return x


def clean_int(x, lo: int, hi: int, what: str) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or not (lo <= x <= hi):
        raise Refused(400, f"bad_{what}", f"{what} must be a whole number from {lo} to {hi}")
    return x


def clean_book(body: dict) -> tuple:
    haves, wants = body.get("haves") or [], body.get("wants") or []
    if not isinstance(haves, list) or not isinstance(wants, list) or len(haves) + len(wants) > MAX_ITEMS:
        raise Refused(400, "bad_book", f"haves and wants must be lists, at most {MAX_ITEMS} items in all")
    H, W, seen = [], [], set()
    for it in haves:
        if not isinstance(it, dict):
            raise Refused(400, "bad_book", "a have must be an object")
        a = clean_int(it.get("asset"), 1, 10_000_000, "asset")
        if a in seen:
            raise Refused(400, "bad_book", f"asset {a} twice")
        seen.add(a)
        H.append({"card": clean_ref(it.get("card")), "asset": a, "min": clean_int(it.get("min"), 1, 10_000, "min")})
    for it in wants:
        if not isinstance(it, dict):
            raise Refused(400, "bad_book", "a want must be an object")
        W.append({"card": clean_ref(it.get("card")), "max": clean_int(it.get("max"), 1, 10_000, "max"),
                  "qty": clean_int(it.get("qty", 1), 1, 5, "qty")})
    return H, W


# ---------------------------------------------------------------- the matcher (pure)

def match(books: dict, venues: list, participants: dict) -> list:
    """books: {team: {"haves": [...], "wants": [...]}}; venues: public /api/venues list; participants: {team: venue id
    or None}. Returns trades [{seller, buyer, card, asset, price, venue, fee, surplus}]. Greedy by surplus."""
    by_id = {v["venue"]: v for v in venues if isinstance(v, dict) and v.get("status") == "open"}
    own = {t: v for t, v in participants.items() if v in by_id}
    load = {v: 0 for v in set(own.values())}

    def pick_venue(seller: str, buyer: str) -> dict | None:
        pool = [v for t, v in own.items() if t not in (seller, buyer)]
        if pool:
            vid = min(pool, key=lambda v: (load[v], fee_of(by_id[v], 50), v))
            return by_id[vid]
        others = [v for v in by_id.values() if v.get("owner") not in (seller, buyer, "world")]
        if others:
            return min(others, key=lambda v: (fee_of(v, 50), v["venue"]))
        return by_id.get("rastro")

    cands = []
    for s, b in books.items():
        for hv in b.get("haves", []):
            for t, bb in books.items():
                if t == s:
                    continue
                for i, w in enumerate(bb.get("wants", [])):
                    if w["card"] != hv["card"] or w["max"] < hv["min"]:
                        continue
                    cands.append((w["max"] - hv["min"], s, hv, t, i, w))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]["asset"], c[3], c[4]))
    used_assets, want_left, trades = set(), {}, []
    for surplus, s, hv, t, i, w in cands:
        if hv["asset"] in used_assets:
            continue
        key = (t, i)
        left = want_left.get(key, w.get("qty", 1))
        if left <= 0:
            continue
        venue = pick_venue(s, t)
        if venue is None:
            continue
        lo, hi = hv["min"], w["max"]
        price = (lo + hi) // 2
        for _ in range(4):               # the accepting side pays the fee: split [min, max - fee] in the middle
            nxt = (lo + (hi - fee_of(venue, price))) // 2
            if nxt == price:
                break
            price = nxt
        if price < lo or price + fee_of(venue, price) > hi:
            continue
        used_assets.add(hv["asset"])
        want_left[key] = left - 1
        if venue["venue"] in load:
            load[venue["venue"]] += 1
        trades.append({"seller": s, "buyer": t, "card": hv["card"], "asset": hv["asset"], "price": price,
                       "venue": venue["venue"], "fee": fee_of(venue, price), "surplus": surplus})
    return trades


# ---------------------------------------------------------------- the store

class Store:
    """state.json: {"teams": {team: {"token_hash", "venue", "joined", "haves", "wants", "updated"}},
    "rounds": [{"id", "at", "trades": [...], "actions": {team: [...]}}]}. Rewritten whole under a lock."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.state = {"teams": {}, "rounds": []}
        if path.exists():
            self.state = json.loads(path.read_text() or "{}") or self.state
            self.state.setdefault("teams", {})
            self.state.setdefault("rounds", [])

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=1, sort_keys=True))
            os.replace(tmp, self.path)

    def team_of(self, token) -> str:
        if not isinstance(token, str) or not (8 <= len(token) <= 80):
            raise Refused(401, "bad_token")
        th = h(token)
        for t, rec in self.state["teams"].items():
            if rec.get("token_hash") == th:
                return t
        raise Refused(401, "bad_token", "unknown token: join first")

    def join(self, body: dict) -> dict:
        team = clean_team(body.get("team"))
        venue = body.get("venue")
        if venue is not None and (not isinstance(venue, str) or not VENUE_RE.match(venue)):
            raise Refused(400, "bad_venue", "venue must look like v29")
        with self.lock:
            rec = self.state["teams"].get(team)
            if rec:
                tok = body.get("token")
                if not (isinstance(tok, str) and h(tok) == rec["token_hash"]):
                    raise Refused(409, "already_joined", f"{team} already has a token; pass it to update the venue")
                if venue:
                    rec["venue"] = venue
                self.save()
                return {"team": team, "venue": rec.get("venue"), "joined": rec["joined"], "token": tok}
            token = secrets.token_urlsafe(18)
            self.state["teams"][team] = {"token_hash": h(token), "venue": venue, "joined": now_iso(),
                                         "haves": [], "wants": [], "updated": None}
            self.save()
            return {"team": team, "venue": venue, "token": token}

    def book(self, body: dict) -> dict:
        team = self.team_of(body.get("token"))
        haves, wants = clean_book(body)
        with self.lock:
            rec = self.state["teams"][team]
            rec["haves"], rec["wants"], rec["updated"] = haves, wants, now_iso()
            self.save()
        return {"team": team, "haves": len(haves), "wants": len(wants), "updated": rec["updated"]}

    def status(self, next_run: str | None = None) -> dict:
        with self.lock:
            teams = self.state["teams"]
            rounds = [{"id": r["id"], "at": r["at"], "trades": len(r["trades"]),
                       "done": sum(1 for a in r["trades"] if a.get("status") == "settled"),
                       "venues": sorted({a["venue"] for a in r["trades"]})} for r in self.state["rounds"]]
            return {"teams": sorted(teams), "venues": {t: v.get("venue") for t, v in teams.items()},
                    "haves": sum(len(v["haves"]) for v in teams.values()),
                    "wants": sum(len(v["wants"]) for v in teams.values()),
                    "cards_offered": sorted({x["card"] for v in teams.values() for x in v["haves"]}),
                    "cards_wanted": sorted({x["card"] for v in teams.values() for x in v["wants"]}),
                    "rounds": rounds, "next_run": next_run, "now": now_iso()}

    def run(self, venues: list) -> dict:
        with self.lock:
            books = {t: {"haves": v["haves"], "wants": v["wants"]} for t, v in self.state["teams"].items()}
            parts = {t: v.get("venue") for t, v in self.state["teams"].items()}
            trades = match(books, venues, parts)
            rid = len(self.state["rounds"]) + 1
            for i, tr in enumerate(trades, 1):
                tr.update({"id": f"r{rid}-{i}", "offer": None, "status": "planned", "posted": None, "accepted": None,
                           "error": None})
            self.state["rounds"].append({"id": rid, "at": now_iso(), "trades": trades})
            # a matched have leaves the book: a second run never sells the same asset twice
            sold = {tr["asset"] for tr in trades}
            for t, v in self.state["teams"].items():
                v["haves"] = [x for x in v["haves"] if x["asset"] not in sold]
                for tr in trades:
                    if tr["buyer"] == t:
                        for w in v["wants"]:
                            if w["card"] == tr["card"] and w.get("qty", 1) > 0:
                                w["qty"] = w.get("qty", 1) - 1
                                break
                v["wants"] = [w for w in v["wants"] if w.get("qty", 1) > 0]
            self.save()
            return {"round": rid, "trades": len(trades), "venues": sorted({t["venue"] for t in trades}),
                    "surplus": sum(t["surplus"] for t in trades)}

    def plan(self, token) -> dict:
        team = self.team_of(token)
        with self.lock:
            if not self.state["rounds"]:
                return {"team": team, "round": None, "actions": [], "note": "no round yet"}
            out = []
            for r in self.state["rounds"]:
                for tr in r["trades"]:
                    if tr["status"] in ("settled", "failed"):
                        continue
                    if tr["seller"] == team:
                        out.append({"id": tr["id"], "role": "sell", "card": tr["card"], "asset": tr["asset"],
                                    "price": tr["price"], "venue": tr["venue"], "to": tr["buyer"],
                                    "offer": tr["offer"], "status": tr["status"],
                                    "post": {"venue": tr["venue"], "to": tr["buyer"], "give": {"assets": [tr["asset"]]},
                                             "want": {"cash": tr["price"]}, "expires_in_ticks": OFFER_TTL_TICKS}})
                    elif tr["buyer"] == team:
                        out.append({"id": tr["id"], "role": "buy", "card": tr["card"], "price": tr["price"],
                                    "fee": tr["fee"], "venue": tr["venue"], "from": tr["seller"],
                                    "offer": tr["offer"], "status": tr["status"],
                                    "accept": None if tr["offer"] is None else f"POST /api/offers/{tr['offer']}/accept"})
            return {"team": team, "round": self.state["rounds"][-1]["id"], "actions": out}

    def report(self, body: dict) -> dict:
        team = self.team_of(body.get("token"))
        aid = body.get("action")
        with self.lock:
            tr = next((t for r in self.state["rounds"] for t in r["trades"] if t["id"] == aid), None)
            if tr is None or team not in (tr["seller"], tr["buyer"]):
                raise Refused(404, "no_such_action")
            if "offer" in body and team == tr["seller"]:
                tr["offer"] = clean_int(body.get("offer"), 1, 10_000_000, "offer")
                tr["status"], tr["posted"] = "posted", now_iso()
            st = body.get("status")
            if st == "accepted" and team == tr["buyer"]:
                tr["status"], tr["accepted"] = "settled", now_iso()
            elif st == "failed":
                tr["status"], tr["error"] = "failed", str(body.get("error") or "")[:200]
            self.save()
            return {"id": tr["id"], "status": tr["status"], "offer": tr["offer"]}

    def watch_books(self) -> int:
        """Pass offer ids along from the public books when a seller did not report: an open offer on the trade's
        venue addressed to the buyer, giving that asset for that cash. Returns how many were filled in."""
        with self.lock:
            pending = [t for r in self.state["rounds"] for t in r["trades"] if t["status"] == "planned"]
            venues = sorted({t["venue"] for t in pending})
        n = 0
        for vid in venues:
            try:
                body = public_get(f"/api/venues/{vid}/offers")
            except Exception:
                continue
            for o in (body or {}).get("offers") or []:
                if not isinstance(o, dict) or o.get("status", "open") != "open":
                    continue
                give = o.get("give") or {}
                assets = [a.get("id") if isinstance(a, dict) else a for a in (give.get("assets") or [])]
                with self.lock:
                    for t in pending:
                        if t["venue"] == vid and t["asset"] in assets and (o.get("want") or {}).get("cash") == t["price"] \
                                and t["status"] == "planned" and o.get("id"):
                            t["offer"], t["status"], t["posted"] = int(o["id"]), "posted", now_iso()
                            n += 1
        if n:
            self.save()
        return n


# ---------------------------------------------------------------- the server

AGENTS_MD = """# The Clearing House (Team 3)

A private book and a matcher: tell it which cards you would sell and the least you take, which cards you want and the
most you pay. At the run time it pairs every profitable cross between teams, at the midpoint, on a venue owned by
neither side, and gives each side ONE thing to do: the seller posts an offer addressed to the buyer, the buyer
accepts it by id. Both sides keep half the surplus. Your prices are never shown to anyone.

It never touches your key. Run the client on your own machine (python3, stdlib only, read it first):

    curl -sO {base}/clearing_client.py
    export BAZAAR_KEY=<your team key>          # used only against the game
    python3 clearing_client.py --server {base} join --team t07 --venue v29
    python3 clearing_client.py --server {base} book --margin 0.15      # duplicates for sale, missing cards wanted, from /api/me/value
    python3 clearing_client.py --server {base} execute --until 13:50    # posts your sells, accepts your buys, one per tick

Or speak JSON directly:

    POST {base}/api/clearing/join    {{"team": "t07", "venue": "v29"}}                 -> {{"token": "..."}}
    POST {base}/api/clearing/book    {{"token": "...", "haves": [{{"card": "MAL-06", "asset": 123, "min": 9}}],
                                      "wants": [{{"card": "SAL-10", "max": 80}}]}}
    GET  {base}/api/clearing/plan?token=...     -> your actions: for a sell, the exact body to POST /api/offers;
                                                   for a buy, the offer id to POST /api/offers/<id>/accept
    POST {base}/api/clearing/report  {{"token": "...", "action": "r1-3", "offer": 4567}}   after you post a sell
    GET  {base}/api/clearing/status             who is in, how many cards, when the next run is

Runs: {runs}. A matched sale leaves your book; put new cards in any time before a run.
"""


def make_server(store: Store, host: str, port: int, *, admin_token: str, public_url: str, run_at: list,
                venues_fn) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        server_version = "clearing/1"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise Refused(413, "too_large")
            try:
                obj = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                raise Refused(400, "bad_json")
            if not isinstance(obj, dict):
                raise Refused(400, "bad_json", "a JSON object")
            return obj

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain")

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path in ("/", "/agents.md", "/llms.txt"):
                    base = public_url or f"http://{host}:{port}"
                    runs = ", ".join(run_at) if run_at else "on demand (ask Team 3)"
                    self._send(200, AGENTS_MD.format(base=base, runs=runs).encode(), "text/markdown; charset=utf-8")
                elif u.path == "/clearing_client.py":
                    self._send(200, (ROOT / "tools" / "clearing_client.py").read_bytes(), "text/x-python")
                elif u.path == "/api/clearing/status":
                    self._json(200, store.status(next_run=run_at[0] if run_at else None))
                elif u.path == "/api/clearing/plan":
                    self._json(200, store.plan((q.get("token") or [None])[0]))
                elif u.path == "/healthz":
                    self._json(200, {"ok": True, "teams": len(store.state["teams"])})
                else:
                    self._json(404, {"error": "no_such_route"})
            except Refused as r:
                self._json(r.status, {"error": r.code, "message": r.message})

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/api/clearing/join":
                    self._json(200, store.join(body))
                elif self.path == "/api/clearing/book":
                    self._json(200, store.book(body))
                elif self.path == "/api/clearing/report":
                    self._json(200, store.report(body))
                elif self.path == "/api/clearing/run":
                    if not admin_token or body.get("admin") != admin_token:
                        raise Refused(403, "forbidden")
                    self._json(200, store.run(venues_fn()))
                else:
                    self._json(404, {"error": "no_such_route"})
            except Refused as r:
                self._json(r.status, {"error": r.code, "message": r.message})

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    return srv


def live_venues() -> list:
    try:
        return (public_get("/api/venues") or {}).get("venues") or []
    except Exception as e:
        print(f"venues unread: {e}", file=sys.stderr)
        return []


def cmd_serve(a) -> None:
    store = Store(Path(a.store) / "state.json")
    Path(a.store).mkdir(parents=True, exist_ok=True)
    run_at = [x.strip() for x in (a.run_at or "").split(",") if x.strip()]
    srv = make_server(store, a.host, a.port, admin_token=a.admin_token or os.environ.get("CLEARING_ADMIN", ""),
                      public_url=a.public_url, run_at=run_at, venues_fn=live_venues)
    print(f"clearing house on http://{a.host}:{a.port}  store={a.store}  runs={run_at or 'on demand'}", flush=True)

    def ticker():
        fired = set()
        while True:
            try:
                n = store.watch_books()
                if n:
                    print(f"{now_iso()} offer ids seen on the books: {n}", flush=True)
                hhmm = datetime.now().strftime("%H:%M")
                if hhmm in run_at and hhmm not in fired:
                    fired.add(hhmm)
                    print(f"{now_iso()} scheduled run {hhmm}: {store.run(live_venues())}", flush=True)
            except Exception as e:
                print(f"{now_iso()} ticker error: {e}", file=sys.stderr, flush=True)
            time.sleep(20)

    threading.Thread(target=ticker, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_run(a) -> None:
    store = Store(Path(a.store) / "state.json")
    print(json.dumps(store.run(live_venues()), indent=1))


def cmd_status(a) -> None:
    store = Store(Path(a.store) / "state.json")
    print(json.dumps(store.status(), indent=1))
    for r in store.state["rounds"]:
        for t in r["trades"]:
            print(f"  {t['id']:<7} {t['seller']} -> {t['buyer']}  {t['card']} #{t['asset']}  {t['price']} P  on {t['venue']}"
                  f"  fee {t['fee']}  surplus {t['surplus']}  {t['status']}  offer={t['offer']}")


def selftest() -> None:
    venues = [{"venue": "v20", "owner": "t03", "status": "open", "fee_bps": 0, "fee_per_card": 0},
              {"venue": "v29", "owner": "t07", "status": "open", "fee_bps": 0, "fee_per_card": 0},
              {"venue": "v28", "owner": "t18", "status": "open", "fee_bps": 0, "fee_per_card": 0},
              {"venue": "v03", "owner": "t13", "status": "closed", "fee_bps": 0, "fee_per_card": 0},
              {"venue": "rastro", "owner": "world", "status": "open", "fee_bps": 500, "fee_per_card": 1}]
    books = {"t03": {"haves": [{"card": "MAL-06", "asset": 1, "min": 9}, {"card": "LAV-03", "asset": 2, "min": 8}],
                     "wants": [{"card": "SAL-10", "max": 90, "qty": 1}]},
             "t07": {"haves": [{"card": "SAL-10", "asset": 3, "min": 60}], "wants": [{"card": "MAL-06", "max": 21, "qty": 1}]},
             "t18": {"haves": [{"card": "MAL-06", "asset": 4, "min": 15}], "wants": [{"card": "LAV-03", "max": 7, "qty": 1}]}}
    parts = {"t03": "v20", "t07": "v29", "t18": "v28"}
    trades = match(books, venues, parts)
    assert len(trades) == 2, trades
    sal = next(t for t in trades if t["card"] == "SAL-10")
    assert sal["seller"] == "t07" and sal["buyer"] == "t03" and sal["price"] == 75 and sal["venue"] == "v28", sal
    mal = next(t for t in trades if t["card"] == "MAL-06")
    assert mal["seller"] == "t03" and mal["asset"] == 1 and mal["buyer"] == "t07" and mal["price"] == 15 and mal["venue"] == "v28", mal
    assert not any(t["card"] == "LAV-03" for t in trades)      # max 7 < min 8
    # no third participant venue: the cheapest other open venue; none at all: rastro, its fee inside the buyer's max
    two = {"t03": books["t03"], "t07": books["t07"]}
    t2 = match(two, venues, {"t03": "v20", "t07": "v29"})
    assert all(t["venue"] == "v28" for t in t2), t2
    t3 = match(two, [v for v in venues if v["venue"] != "v28"], {"t03": "v20", "t07": "v29"})
    assert t3 and all(t["venue"] == "rastro" for t in t3) and all(t["price"] + t["fee"] <= 90 for t in t3), t3
    assert next(t for t in t3 if t["card"] == "SAL-10")["price"] == 72, t3   # midpoint of [60, 90 - fee]
    # the server round trip, in process
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "state.json")
        srv = make_server(store, "127.0.0.1", 0, admin_token="adm", public_url="", run_at=[], venues_fn=lambda: venues)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def call(method, path, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        toks = {}
        for t, v in parts.items():
            st, r = call("POST", "/api/clearing/join", {"team": t, "venue": v})
            assert st == 200 and r["token"], r
            toks[t] = r["token"]
            st, r = call("POST", "/api/clearing/book", {"token": toks[t], **books[t]})
            assert st == 200, r
        st, r = call("POST", "/api/clearing/join", {"team": "t03"})
        assert st == 409, r
        st, r = call("POST", "/api/clearing/book", {"token": "nope-nope-nope", "haves": []})
        assert st == 401, r
        st, r = call("GET", "/api/clearing/status")
        assert st == 200 and r["haves"] == 4 and "min" not in json.dumps(r), r
        st, r = call("POST", "/api/clearing/run", {"admin": "wrong"})
        assert st == 403
        st, r = call("POST", "/api/clearing/run", {"admin": "adm"})
        assert st == 200 and r["trades"] == 2, r
        st, r = call("GET", f"/api/clearing/plan?token={toks['t07']}")
        acts = r["actions"]
        assert {x["role"] for x in acts} == {"sell", "buy"} and "min" not in json.dumps(r) and "max" not in json.dumps(r), r
        sell = next(x for x in acts if x["role"] == "sell")
        assert sell["post"] == {"venue": "v28", "to": "t03", "give": {"assets": [3]}, "want": {"cash": 75},
                                "expires_in_ticks": OFFER_TTL_TICKS}, sell
        st, r = call("POST", "/api/clearing/report", {"token": toks["t07"], "action": sell["id"], "offer": 4567})
        assert st == 200 and r["status"] == "posted", r
        st, r = call("GET", f"/api/clearing/plan?token={toks['t03']}")
        buy = next(x for x in r["actions"] if x["role"] == "buy")
        assert buy["offer"] == 4567 and buy["accept"] == "POST /api/offers/4567/accept", buy
        st, r = call("POST", "/api/clearing/report", {"token": toks["t03"], "action": buy["id"], "status": "accepted"})
        assert r["status"] == "settled", r
        st, r = call("POST", "/api/clearing/run", {"admin": "adm"})
        assert r["trades"] == 0, r         # sold assets left the book
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/agents.md", timeout=5) as r:
            assert r.status == 200 and b"clearing_client.py" in r.read()
        srv.shutdown()
    print("selftest ok: 2 trades, midpoint prices, venues spread, rastro fallback, tokens, plan, report, no prices leak")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--store", default=str(ROOT / "logs" / "clearing"))
    s.add_argument("--public-url", default="")
    s.add_argument("--admin-token", default="")
    s.add_argument("--run-at", default="", help="HH:MM[,HH:MM] wall clock runs")
    s.set_defaults(fn=cmd_serve)
    r = sub.add_parser("run")
    r.add_argument("--store", default=str(ROOT / "logs" / "clearing"))
    r.set_defaults(fn=cmd_run)
    st = sub.add_parser("status")
    st.add_argument("--store", default=str(ROOT / "logs" / "clearing"))
    st.set_defaults(fn=cmd_status)
    sub.add_parser("selftest").set_defaults(fn=lambda a: selftest())
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
