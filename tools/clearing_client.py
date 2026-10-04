"""Clearing House client: runs on YOUR machine with YOUR key. One file, standard library only. Read it: the key goes
only to the game (BAZAAR_URL, header X-Team-Key); the clearing server receives card refs, asset ids and your
reservation prices, nothing else.

    export BAZAAR_KEY=<your team key>
    python3 clearing_client.py --server https://<clearing> join --team t07 --venue v29 --invite <code>
    python3 clearing_client.py --server https://<clearing> book [--margin 0.15] [--sell-sets MAL,CHA] [--keep LAV-09]
    python3 clearing_client.py --server https://<clearing> plan                     # the proposal: review it
    python3 clearing_client.py --server https://<clearing> vote --ok | --no --why "..." [--trades r1-3]
    python3 clearing_client.py --server https://<clearing> execute [--until 13:50] [--auto-approve] [--dry-run]

book (full, the default): your haves are every duplicate copy (one copy of each card stays), every card of a set
you value below book (your multiplier < 1: you are not collecting it) and every card of --sell-sets, at
min = ceil(your_value * (1 + margin)); your wants are every page card with a value above --floor, held or not, at
max = floor(your_value * (1 - margin)), from GET /api/me/value (which includes page bonuses). A full book is what
lets the matcher find a profitable trade between almost any two teams (multipliers differ per team), which is
what covers every venue. --keep never sells; --no-full keeps only duplicates and missing cards.
execute: every 15 s reads your plan; posts each pending sell exactly once (addressed to the buyer) and reports the
offer id; accepts each buy once the offer id is known, one accept per tick, if you have the cash. --dry-run prints.
The token is kept in ~/.clearing_<team>.json."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

GAME = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai").rstrip("/")


def call(url: str, body=None, key: str | None = None, method: str | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["X-Team-Key"] = key
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
        except Exception:
            err = {"error": str(e.code)}
        err["_status"] = e.code
        return err


def key_or_die() -> str:
    k = os.environ.get("BAZAAR_KEY")
    if not k:
        sys.exit("set BAZAAR_KEY (your team key; it is sent only to the game)")
    return k


def cfg_path(team: str) -> Path:
    return Path.home() / f".clearing_{team}.json"


def load_cfg(a) -> dict:
    cands = [cfg_path(a.team)] if a.team else sorted(Path.home().glob(".clearing_t??.json"))
    for p in cands:
        if p.exists():
            return json.loads(p.read_text())
    sys.exit("no token: run join first")


def cmd_join(a) -> None:
    team = a.team
    if not team:
        me = call(f"{GAME}/api/me", key=key_or_die())
        team = me.get("id") or sys.exit(f"cannot read /api/me: {me}")
    body = {"team": team}
    if a.venue:
        body["venue"] = a.venue
    if a.invite:
        body["invite"] = a.invite
    p = cfg_path(team)
    if p.exists():
        body["token"] = json.loads(p.read_text())["token"]
    r = call(f"{a.server}/api/clearing/join", body)
    if "token" not in r:
        sys.exit(f"join refused: {r}")
    p.write_text(json.dumps({"team": team, "token": r["token"], "server": a.server}))
    print(f"joined as {team} (venue {r.get('venue')}); token saved in {p}")


def cmd_book(a) -> None:
    cfg, key = load_cfg(a), key_or_die()
    me = call(f"{GAME}/api/me", key=key)
    cards = [x for x in me.get("assets") or [] if isinstance(x, dict) and x.get("kind", "card") == "card" and x.get("ref")]
    if not cards and "error" in me:
        sys.exit(f"cannot read /api/me: {me}")
    keep = set((a.keep or "").split(",")) - {""}
    sell_sets = set((a.sell_sets or "").upper().split(",")) - {""}
    held: dict = {}
    for c in cards:
        held.setdefault(c["ref"], []).append(c)
    haves = []
    for ref, copies in held.items():
        if ref in keep:
            continue
        copies = sorted(copies, key=lambda c: (c.get("your_value") or 0, c["id"]))
        book_price = max(1.0, float(copies[-1].get("book") or 0) or 0.0)
        mult = (float(copies[-1].get("your_value") or 0) / book_price) if copies[-1].get("book") else None
        whole_set = ref[:3] in sell_sets or (a.full and mult is not None and mult < 1.0)
        spare = copies if whole_set else copies[:-1]      # one copy of each card stays unless the set is for sale
        for c in spare:
            v = float(c.get("your_value") or 0)
            haves.append({"card": ref, "asset": int(c["id"]), "min": max(1, int(math.ceil(v * (1 + a.margin))))})
    catalog = call(f"{GAME}/api/catalog")
    refs = sorted({c.get("id") for s in (catalog.get("sets") or []) if isinstance(s, dict)
                   for c in (s.get("cards") or []) if isinstance(c, dict) and c.get("id") and c.get("page", True)})
    wants = []
    for ref in refs:
        if (ref in held and not a.full) or ref[:3] in sell_sets:
            continue
        r = call(f"{GAME}/api/me/value?card={ref}", key=key)
        v = r.get("your_value") if isinstance(r, dict) else None
        if isinstance(v, (int, float)) and v >= a.floor:
            wants.append({"card": ref, "max": max(1, int(math.floor(v * (1 - a.margin)))), "qty": 1})
    cash = me.get("cash")
    wants = sorted(wants, key=lambda w: -w["max"])[: a.max_wants]
    if a.dry_run:
        print(json.dumps({"haves": haves, "wants": wants, "cash": cash}, indent=1))
        return
    r = call(f"{cfg['server']}/api/clearing/book", {"token": cfg["token"], "haves": haves, "wants": wants})
    print(f"book sent: {r}  (cash {cash})")


def cmd_plan(a) -> None:
    cfg = load_cfg(a)
    plan = call(f"{cfg['server']}/api/clearing/plan?token={cfg['token']}")
    print(json.dumps(plan, indent=1))
    if plan.get("round_status") == "proposed":
        print("\nThis is a PROPOSAL. Review it, then:  vote --ok   or   vote --no --why \"...\" [--trades r1-3,r1-5]",
              file=sys.stderr)


def cmd_vote(a) -> None:
    cfg = load_cfg(a)
    if a.ok == a.no:
        sys.exit("say --ok or --no")
    body = {"token": cfg["token"], "ok": bool(a.ok)}
    if a.no:
        body["why"] = a.why or "no reason given"
        if a.trades:
            body["trades"] = [x.strip() for x in a.trades.split(",") if x.strip()]
    print(json.dumps(call(f"{cfg['server']}/api/clearing/vote", body), indent=1))


def cmd_execute(a) -> None:
    cfg, key = load_cfg(a), key_or_die()
    posted, accepted, failed, voted = set(), set(), set(), set()
    until = a.until
    while True:
        if until and datetime.now().strftime("%H:%M") >= until:
            print("until reached, stopping")
            return
        plan = call(f"{cfg['server']}/api/clearing/plan?token={cfg['token']}")
        if plan.get("round_status") == "proposed":
            key_v = (plan.get("round"), plan.get("version"))
            mine = [x for x in (plan.get("actions") or []) if x.get("round_status") == "proposed"]
            if mine and plan.get("your_vote") is None:
                if a.auto_approve and key_v not in voted:
                    voted.add(key_v)
                    r = call(f"{cfg['server']}/api/clearing/vote", {"token": cfg["token"], "ok": True})
                    print(f"{datetime.now():%H:%M:%S} proposal r{key_v[0]} v{key_v[1]}: auto-approved -> {r.get('status')}, waiting for {r.get('waiting_for')}")
                elif key_v not in voted:
                    voted.add(key_v)
                    print(f"{datetime.now():%H:%M:%S} proposal r{key_v[0]} v{key_v[1]} needs your vote: run `plan`, then `vote --ok` or `vote --no --why ...`")
                    for x in mine:
                        print(f"   {x['id']} {x['role'].upper()} {x['card']} {x['price']} P on {x['venue']} with {x.get('to') or x.get('from')}")
        acts = [x for x in (plan.get("actions") or []) if x.get("round_status") == "approved"]
        pending = [x for x in acts if x["id"] not in accepted | failed]
        if not pending and plan.get("round"):
            print(f"{datetime.now():%H:%M:%S} nothing pending in round {plan['round']}; waiting for the next run")
        did_accept = False
        for x in pending:
            if x["role"] == "sell" and x["id"] not in posted and x.get("offer") is None:
                body = x["post"]
                print(f"{datetime.now():%H:%M:%S} SELL {x['card']} #{x['asset']} at {x['price']} on {x['venue']} to {x['to']}")
                if a.dry_run:
                    posted.add(x["id"])
                    continue
                r = call(f"{GAME}/api/offers", body, key=key)
                oid = r.get("id") or (r.get("offer") or {}).get("id")
                if oid:
                    posted.add(x["id"])
                    call(f"{cfg['server']}/api/clearing/report", {"token": cfg["token"], "action": x["id"], "offer": int(oid)})
                    print(f"   posted offer {oid}")
                else:
                    print(f"   refused: {r}")
                    if r.get("_status") in (400, 404, 409):
                        failed.add(x["id"])
                        call(f"{cfg['server']}/api/clearing/report",
                             {"token": cfg["token"], "action": x["id"], "status": "failed", "error": str(r.get("error"))})
            elif x["role"] == "sell" and x.get("offer"):
                posted.add(x["id"])
            elif x["role"] == "buy" and x.get("offer") and not did_accept:
                print(f"{datetime.now():%H:%M:%S} BUY  {x['card']} at {x['price']} (+{x.get('fee', 0)} fee) on {x['venue']}: accept offer {x['offer']}")
                if a.dry_run:
                    accepted.add(x["id"])
                    continue
                r = call(f"{GAME}/api/offers/{int(x['offer'])}/accept", {}, key=key)
                if r.get("_status") is None:
                    accepted.add(x["id"])
                    did_accept = True
                    call(f"{cfg['server']}/api/clearing/report", {"token": cfg["token"], "action": x["id"], "status": "accepted"})
                    print(f"   accepted: {r}")
                else:
                    print(f"   refused: {r}")
                    if r.get("_status") in (400, 404) and r.get("error") not in ("rate_limited", "tick_limit"):
                        failed.add(x["id"])
                        call(f"{cfg['server']}/api/clearing/report",
                             {"token": cfg["token"], "action": x["id"], "status": "failed", "error": str(r.get("error"))})
        if a.once:
            return
        time.sleep(a.every)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--server", default=os.environ.get("CLEARING_URL", ""), help="clearing house base URL")
    p.add_argument("--team", default="", help="your team id (t07); read from /api/me if omitted")
    sub = p.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("join")
    j.add_argument("--venue", default="", help="your venue id, so trades can be routed onto it")
    j.add_argument("--invite", default="", help="the invite code Team 3 gave your team")
    j.set_defaults(fn=cmd_join)
    b = sub.add_parser("book")
    b.add_argument("--margin", type=float, default=0.15, help="keep this share of your value on each side")
    b.add_argument("--sell-sets", default="", help="sets to sell entirely, e.g. MAL,CHA")
    b.add_argument("--keep", default="", help="cards never to sell, e.g. LAV-09,LAV-10")
    b.add_argument("--floor", type=float, default=5.0, help="want only cards worth at least this to you")
    b.add_argument("--max-wants", type=int, default=60)
    b.add_argument("--no-full", dest="full", action="store_false",
                   help="only duplicates for sale and missing cards wanted (default: full book, see docstring)")
    b.add_argument("--dry-run", action="store_true")
    b.set_defaults(fn=cmd_book)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    v = sub.add_parser("vote", help="approve or reject the open proposal")
    v.add_argument("--ok", action="store_true")
    v.add_argument("--no", action="store_true")
    v.add_argument("--why", default="")
    v.add_argument("--trades", default="", help="comma-separated action ids to reject (default: all yours)")
    v.set_defaults(fn=cmd_vote)
    e = sub.add_parser("execute")
    e.add_argument("--until", default="", help="HH:MM wall clock stop")
    e.add_argument("--every", type=float, default=15.0)
    e.add_argument("--once", action="store_true")
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("--auto-approve", action="store_true", help="vote OK on every proposal (prices are inside your numbers anyway)")
    e.set_defaults(fn=cmd_execute)
    a = p.parse_args()
    if a.cmd == "join" and not a.server:
        sys.exit("--server is required")
    a.fn(a)


if __name__ == "__main__":
    main()
