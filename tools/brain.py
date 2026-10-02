"""Team 3's market brain: one always-on, keyless process that turns the recorded feed into what to do next.

It runs next to tools/feed_recorder.py (same clone, same logs/feed/) and, whenever new events land, recomputes:
- every team's inferred set multipliers (tools/value_inference.py), and how well the model predicts the next choice;
- every team's cash and known cards (tools/ledger.py), checked against our own account;
- the market plan with timing (tools/market_plan.py): what to sell, buy and hold, at what price and when;
- the El Rastro board with makers translated from pseudonyms to teams, and the leaderboard.
It keeps a learning curve (logs/brain/history.jsonl: hit rate, evidence, beliefs per refresh) and serves a page.

    python3 tools/brain.py                         # http://127.0.0.1:8790 (BRAIN_TOKEN=... gates it with ?t=)
    python3 tools/brain.py --once                  # one refresh into logs/brain/latest.json, then exit
    ssh -N -L 8790:127.0.0.1:8790 fable-vm         # from a laptop, when the brain runs on the VM

No key, no sends: it only reads public data and our private values (logs/state/me.json). Anything that moves cards
or primas is done by a person (or an agent with the key) after a yes in the team chat.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ledger as ledger_mod
import market_plan
import value_inference as vi

OUT = vi.ROOT / "logs" / "brain"
PAGE = Path(__file__).resolve().parent / "brain.html"
STATE = {"data": None, "error": None, "updated": 0.0, "busy": False}
LOCK = threading.Lock()
REFRESH_SECONDS = 10.0


def leaderboard() -> dict:
    snaps = [s for s in vi.rows("snapshots.jsonl") if s.get("what") == "leaderboard"]
    return snaps[-1]["body"] if snaps else {}


def refresh() -> dict:
    t0 = time.time()
    model, by_team, events, book = vi.load()
    schedule = vi.public("schedule", True)
    led = ledger_mod.build(events, schedule)
    chk = ledger_mod.check_us(led)
    split = model.time_split(by_team)
    me = json.loads(vi.ME.read_text())
    truth = me.get("affinity", {})
    ours = model.summary(model.posterior(by_team.get(vi.US, [])))
    plan = market_plan.plan()
    lb = leaderboard()
    rank = {t["team"]: t for t in lb.get("teams", [])}
    teams = []
    for t in sorted(by_team):
        r = model.summary(model.posterior(by_team[t]))
        L = led.get(t, {})
        teams.append({
            "team": t, "us": t == vi.US, "score": (rank.get(t) or {}).get("score"), "rank": None,
            "cash": L.get("cash"), "cash_history": L.get("history", [])[-60:], "trades": L.get("trades"),
            "unlocked": L.get("unlocked"), "venue": L.get("venue"), "bonds": L.get("bonds"),
            "dealer_spent": L.get("dealer_spent"), "known_cards": L.get("known_cards"),
            "expected": {s: round(r["expected"][s], 2) for s in model.in_play},
            "dist": {s: {str(m): round(p, 3) for m, p in r["dist"][s].items()} for s in model.in_play},
            "favourite": r["favourite"], "p_favourite": round(r["p_favourite"], 2),
            "least": r["least"], "p_least": round(r["p_least"], 2), "confidence": r["confidence"],
            "evidence": len(by_team[t]),
        })
    for i, t in enumerate(sorted((x for x in teams if x["score"] is not None), key=lambda x: -x["score"])):
        t["rank"] = i + 1
    stored = len(events)
    data = {
        "tick": events[-1]["tick"], "server_time": time.strftime("%H:%M:%S"), "compute_s": None,
        "store": {"events": stored, "api_window": 1000, "first_tick": events[0]["tick"], "last_tick": events[-1]["tick"],
                  "last_seen": events[-1].get("seen_at")},
        "model": {"hit": round(split["hit"], 3), "naive": round(split["naive_hit"], 3), "n": split["n"],
                  "chance": round(1 / len(model.in_play), 3), "loss": round(split["loss"], 3),
                  "uniform_loss": round(split["uniform_loss"], 3), "beta_choose": model.beta_choose, "beta_shed": model.beta_shed,
                  "us": {s: {"inferred": round(ours["expected"][s], 2), "true": truth.get(s)} for s in model.in_play}},
        "ledger_check": chk, "teams": teams, "plan": plan, "in_play": model.in_play,
        "leaderboard_tick": lb.get("snapshot_tick"),
    }
    data["compute_s"] = round(time.time() - t0, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(data, default=str), encoding="utf-8")
    with open(OUT / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"tick": data["tick"], "at": data["server_time"], "events": stored, "hit": data["model"]["hit"],
                            "n": split["n"], "beliefs": {t["team"]: [t["favourite"], t["p_favourite"]] for t in teams},
                            "cash": {t["team"]: t["cash"] for t in teams}}) + "\n")
    return data


def worker() -> None:
    last_size = -1
    while True:
        try:
            size = (vi.FEED / "feed.jsonl").stat().st_size
            if size != last_size:
                last_size = size
                data = refresh()
                with LOCK:
                    STATE.update(data=data, error=None, updated=time.time())
        except Exception:  # keep serving the last good state
            with LOCK:
                STATE["error"] = traceback.format_exc(limit=3)[-600:]
        time.sleep(REFRESH_SECONDS)


def serve(port: int, host: str, token: str | None) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
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
                                       "age": round(time.time() - STATE["updated"], 1) if STATE["updated"] else None},
                                      default=str)
                return self._send(200, body.encode(), "application/json")
            if u.path == "/history":
                path = OUT / "history.jsonl"
                rows = path.read_text(encoding="utf-8").splitlines()[-500:] if path.exists() else []
                return self._send(200, ("[" + ",".join(rows) + "]").encode(), "application/json")
            return self._send(404, b"not found", "text/plain")

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="Team 3's market brain (keyless, plans only).")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if args.once:
        d = refresh()
        print(f"tick {d['tick']}: {d['store']['events']} events, model hit {d['model']['hit']:.0%}, "
              f"ledger check {d['ledger_check']}, {len(d['plan']['sells'])} sells, {len(d['plan']['buys'])} buys, "
              f"{d['compute_s']} s")
        return
    threading.Thread(target=worker, daemon=True).start()
    token = os.environ.get("BRAIN_TOKEN")
    print(f"brain: http://{args.host}:{args.port}/" + (f"?t={token}" if token else ""), flush=True)
    serve(args.port, args.host, token)


if __name__ == "__main__":
    main()
