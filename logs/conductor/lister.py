"""Last-hour El Rastro lister: spare copies (and MAL singles from 13:55) at a price that nets our value + 50 after
the house fee (5 % + 1 P), so every sale scores the full +50 whoever buys. Relists as listings expire. Until HH:MM."""
import json, math, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar, BazaarError
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"], wait_on_tick=False)
UNTIL = sys.argv[1] if len(sys.argv) > 1 else "14:58"
MAL_FROM = "13:55"
COMPLETE = {"LAV", "LAT", "SAL", "RET"}
def hm(): return time.strftime("%H:%M")
def price_for(value): return int(math.ceil((value + 51) / 0.95))
mine = {}   # asset id -> offer id
while hm() < UNTIL:
    try:
        me = b.me()
        assets = [a for a in me["assets"] if a.get("kind", "card") == "card"]
        by_ref = {}
        for a in assets:
            by_ref.setdefault(a["ref"], []).append(a)
        targets = []
        for ref, cps in by_ref.items():
            cps = sorted(cps, key=lambda a: (a.get("your_value") or 0, a["id"]))
            if len(cps) >= 2:
                targets += cps[:-1]                      # spares only, the best copy stays
            elif ref.startswith("MAL") and hm() >= MAL_FROM:
                targets += cps                            # MAL page will not complete: singles may go
        open_ids = {o["id"]: o for o in (b.my_offers().get("offers") or []) if o.get("status") in ("open", "queued")}
        for a in targets:
            if a["ref"][:3] in COMPLETE and len(by_ref[a["ref"]]) < 2:
                continue
            oid = mine.get(a["id"])
            if oid in open_ids:
                continue
            p = price_for(float(a.get("your_value") or 0))
            try:
                r = b.list_offer(give={"assets": [a["id"]]}, want={"cash": p}, venue="rastro", expires_in_ticks=30)
                mine[a["id"]] = r.get("id") or (r.get("offer") or {}).get("id")
                print(time.strftime("%T"), "listed", a["ref"], a["id"], "at", p, "value", a.get("your_value"), "offer", mine[a["id"]], flush=True)
            except BazaarError as e:
                print(time.strftime("%T"), "refused", a["ref"], a["id"], e.code, e.message, flush=True)
            time.sleep(1)
    except Exception as e:
        print(time.strftime("%T"), "error", type(e).__name__, str(e)[:200], flush=True)
    time.sleep(60)
print(time.strftime("%T"), "lister done", flush=True)
