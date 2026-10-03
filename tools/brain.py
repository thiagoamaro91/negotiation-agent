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
- the team's desks (trading agents): their heartbeats, mode and last decision.
Open pages are told at once (server-sent events on /stream) and fetch the new state. It also keeps a learning curve
(logs/brain/history.jsonl).

    python3 tools/brain.py                    # http://127.0.0.1:8790 ; settings from ~/bazaar/brain.env if present
    python3 tools/brain.py --once             # one refresh into logs/brain/latest.json, then exit
    tools/run_brain.sh                        # on the VM: recorder + brain in tmux, restarted if they die

Settings (environment or the --env file): BRAIN_TOKEN gates every page and read (?t=...); BRAIN_WRITE_TOKEN lets
tools/me_relay.py push our account (POST /ingest/me) from the laptop that holds the team key, so the key never
leaves that laptop, and lets the desks post heartbeats (POST /ingest/desk, header X-Brain-Write, body
{"name", "mode": "shadow"|"live", "tick", "last_decision", "reason"}; 4 KB at most, any field whose name contains
"key" is dropped and key-like values are redacted). BRAIN_PAGE_BONUS=1 counts the page bonus in trade values once the
desk confirms it. The brain itself has no key and never sends anything to the game.
"""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ledger as ledger_mod
import market_plan
import price_index
import value_inference as vi

OUT = vi.ROOT / "logs" / "brain"
PAGE = Path(__file__).resolve().parent / "brain.html"
STATE = {"data": None, "error": None, "updated": 0.0, "version": 0}
COND = threading.Condition()
POKE = threading.Event()        # set by /ingest/me to refresh at once
CHECK_SECONDS = 2.0             # how often the worker looks for new events
MAX_QUIET_SECONDS = 60.0        # refresh at least this often (the live board can change without a feed event)
TAPE_LEN = 60
DEFAULT_ENV = Path.home() / "bazaar" / "brain.env"
DESK_MAX_BYTES = 4096           # a heartbeat is a few lines; anything bigger is refused
DESK_MAX = 24                   # desks remembered at once (the oldest heartbeat is forgotten first)
DESK_TEXT = {"last_decision": 300, "reason": 500}
DESK_NAME = re.compile(r"^[A-Za-z0-9 _.-]{1,40}$")
KEYLIKE = re.compile(r"\b(?:tk|bk|sk)-[A-Za-z0-9-]{6,}")  # team / broker key shapes, redacted if a desk ever echoes one
DESKS: dict = {}
DESK_LOCK = threading.Lock()
LAST_DESK_PUSH = [0.0]
DESK_FILE = OUT / "desks.json"


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
    """Drop every field whose name mentions a key, at any depth, and redact key-shaped strings."""
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items() if "key" not in str(k).lower()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    if isinstance(x, str):
        return KEYLIKE.sub("[redacted]", x)
    return x


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
    plan = market_plan.plan(split)
    rarity, _, _ = price_index.card_kinds(cat)
    snaps = SNAPS.update()
    lb = snaps.body("leaderboard")
    score = {t["team"]: t.get("score") for t in lb.get("teams", [])}
    teams = []
    for t in sorted(by_team):
        r = model.summary(model.posterior(by_team[t]), by_team[t])
        L = led.get(t, {})
        teams.append({
            "team": t, "us": t == vi.US, "score": score.get(t), "rank": None,
            "cash": L.get("cash"), "cash_history": L.get("history", [])[-60:], "trades": L.get("trades"),
            "unlocked": L.get("unlocked"), "venue": L.get("venue"), "bonds": L.get("bonds"),
            "dealer_spent": L.get("dealer_spent"), "known_cards": L.get("known_cards"),
            "expected": {s: round(r["expected"][s], 2) for s in model.in_play},
            "dist": {s: {str(m): round(p, 3) for m, p in r["dist"][s].items()} for s in model.in_play},
            "favourite": r["favourite"], "p_favourite": round(r["p_favourite"], 2),
            "least": r["least"], "p_least": round(r["p_least"], 2), "confidence": r["confidence"],
            "choices": r["choices"], "evidence": len(by_team[t]),
        })
    for i, t in enumerate(sorted((x for x in teams if x["score"] is not None), key=lambda x: -x["score"])):
        t["rank"] = i + 1
    live = vi.ME_LIVE.exists() and json.loads(vi.ME_LIVE.read_text()).get("tick") == me.get("tick")
    data = {
        "tick": events[-1]["tick"], "server_time": time.strftime("%H:%M:%S"),
        "store": {"events": len(events), "api_window": 1000, "first_tick": events[0]["tick"],
                  "last_tick": events[-1]["tick"], "last_seen": events[-1].get("seen_at")},
        "account": {"source": "relay (live)" if live else "snapshot", "tick": me.get("tick"),
                    "age_ticks": events[-1]["tick"] - (me.get("tick") or 0)},
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
        "tape": tape(events, truth, mine, book, marginals), "leaderboard_tick": lb.get("snapshot_tick"),
    }
    data["compute_s"] = round(time.time() - t0, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "latest.json.tmp"
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    tmp.replace(OUT / "latest.json")
    with open(OUT / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"tick": data["tick"], "at": data["server_time"], "events": len(events), "hit": data["model"]["hit"],
                            "n": split["n"], "beliefs": {t["team"]: [t["favourite"], t["p_favourite"]] for t in teams},
                            "cash": {t["team"]: t["cash"] for t in teams}}) + "\n")
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
                   vi.ME_LIVE.stat().st_mtime if vi.ME_LIVE.exists() else 0)
            if sig != last_sig or POKE.is_set() or time.time() - last_at > MAX_QUIET_SECONDS:
                POKE.clear()
                last_sig, last_at = sig, time.time()
                publish(data=refresh(), error=None, updated=time.time())
        except Exception:  # keep serving the last good state
            publish(error=traceback.format_exc(limit=3)[-600:])
        POKE.wait(CHECK_SECONDS)


def valid_account(body: dict) -> bool:
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
            if (u.path not in ("/ingest/me", "/ingest/desk") or not write_token
                    or not hmac.compare_digest(given, write_token.encode())):
                return self._send(403, b"forbidden", "text/plain")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n <= 0 or n > (DESK_MAX_BYTES if u.path == "/ingest/desk" else 512_000):
                return self._send(413, b"too large", "text/plain")
            try:
                body = json.loads(self.rfile.read(n))
            except ValueError:
                return self._send(400, b"bad json", "text/plain")
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
            vi.ME_LIVE.parent.mkdir(parents=True, exist_ok=True)
            tmp = vi.ME_LIVE.with_suffix(".tmp")
            tmp.write_text(json.dumps(body), encoding="utf-8")
            tmp.replace(vi.ME_LIVE)
            POKE.set()
            return self._send(200, b"ok", "text/plain")

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.serve_forever()


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
    load_desks()
    threading.Thread(target=worker, daemon=True).start()
    token = os.environ.get("BRAIN_TOKEN")
    print(f"brain on http://{args.host}:{args.port}/ ({'token required' if token else 'open'}; "
          f"account relay {'on' if os.environ.get('BRAIN_WRITE_TOKEN') else 'off'})", flush=True)
    serve(args.port, args.host, token, os.environ.get("BRAIN_WRITE_TOKEN"))


if __name__ == "__main__":
    main()
