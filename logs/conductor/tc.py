"""Conductor helper: thread <id> | flag <message_id> <reason> | value <REF> | score. Reads the key from .env, never prints it."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"], wait_on_tick=False)
cmd = sys.argv[1]
if cmd == "thread":
    t = b.thread(int(sys.argv[2]))
    print({k: t.get(k) for k in ("id", "status", "closed_reason", "with")})
    for m in t.get("messages", []):
        print(json.dumps({k: m.get(k) for k in ("id", "from", "author", "price", "text", "offer", "final")})[:400])
elif cmd == "flag":
    print(b.flag(int(sys.argv[2]), sys.argv[3]))
elif cmd == "value":
    print(b.value(sys.argv[2]))
elif cmd == "score":
    s = b.me()["score"]; print({k: s.get(k) for k in ("score", "rank", "negotiating", "neg_points", "ladder_points", "market", "duel_points")}, "cash", b.me()["cash"])
if cmd == "close":
    print(b.close_thread(int(sys.argv[2])))
