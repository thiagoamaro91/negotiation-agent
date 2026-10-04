"""Flag Picaros bait-and-switch messages after the fact: every 'mismatch' in logs/<dealer>/<date>.jsonl (buy side)
whose words name the card we asked for and not the card the structure gives. Same check as chato.flag_switch.
Flagged message ids are kept in logs/conductor/flagged.json so nothing is flagged twice. --dry prints only."""
import json, sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "kit")]
sys.argv, dry = [sys.argv[0]], "--dry" in sys.argv
spec = importlib.util.spec_from_file_location("chato", ROOT / "agent" / "chato.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = {}; exec((ROOT / "logs/conductor/tc.py").read_text().split("cmd = sys.argv[1]")[0].replace("Path(__file__)", f'Path("{ROOT}/logs/conductor/tc.py")'), g)
b = g["b"]
store = ROOT / "logs/conductor/flagged.json"
done = set(json.loads(store.read_text())) if store.exists() else set()
m._FLAGGED.update(done)
results = []
m.log = lambda ev, **k: results.append((ev, k))
if dry:
    b.flag = lambda mid, r: {"dry": True, "message": mid, "reason": r}
seen = set()
for dealer in ("picaros", "chato", "abuela", "pilar"):
    p = ROOT / "logs" / dealer / "2026-10-04.jsonl"
    if not p.exists():
        continue
    runs = {}
    for line in p.open():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") == "open":
            runs[e.get("thread")] = (e.get("side"), e.get("item"))
        if e.get("event") != "mismatch":
            continue
        o, tid = e.get("offer") or {}, e.get("thread")
        side, item = runs.get(tid, (None, None))
        if side != "buy" or not item or o.get("id") in seen:
            continue
        seen.add(o.get("id"))
        m.flag_switch(b, b.thread(int(tid)), o, item)
for ev, k in results:
    print(ev, json.dumps(k, ensure_ascii=False)[:250])
    if ev == "flagged" and not dry:
        done.add(k.get("message"))
if not dry:
    store.write_text(json.dumps(sorted(x for x in done if x is not None)))
