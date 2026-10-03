"""Field-wide practice duels from the public feed (duel.closed), plus the leaderboard fields."""
import json
import os
from collections import Counter, defaultdict

from common import SNAP, feed

ev = feed()
dc = [e for e in ev if e["type"] == "duel.closed"]
keys = Counter(k for e in dc for k in e["payload"])
print(f"duel.closed events: {len(dc)} (unique duel ids {len({e['payload']['duel'] for e in dc})}); payload keys: {dict(keys)}")
sched = [e["payload"] for e in ev if e["type"] == "duels.scheduled"]
print(f"duels.scheduled: {sched}")
st = Counter(e["payload"]["status"] for e in dc)
print(f"status counts: {dict(st)}  deal rate: {st.get('deal', 0)}/{len(dc)} = {st.get('deal', 0)/len(dc):.3f}")

# by deadline wave (closing tick buckets of 12)
wave = defaultdict(Counter)
for e in dc:
    wave[e["tick"]][e["payload"]["status"]] += 1
print("closing tick -> statuses:")
for t in sorted(wave):
    print(f"  {t}: {dict(wave[t])}")
# deals close early (on accept) vs no_deal at deadline
deal_ticks = Counter(e["tick"] for e in dc if e["payload"]["status"] == "deal")
nd_ticks = Counter(e["tick"] for e in dc if e["payload"]["status"] != "deal")
print(f"no_deal closing ticks: {dict(sorted(nd_ticks.items()))}")

# by item
it = defaultdict(Counter)
for e in dc:
    it[e["payload"]["item"]][e["payload"]["status"]] += 1
print("by item:")
for k, v in sorted(it.items()):
    n = sum(v.values())
    print(f"  {k:26s} n={n:3d} deal={v.get('deal',0):3d} ({v.get('deal',0)/n:.2f})")

# pair concordance (odd/odd+1)
by = {e["payload"]["duel"]: e["payload"]["status"] for e in dc}
pairs = Counter()
for a in by:
    if a % 2 == 1 and a + 1 in by:
        pairs[tuple(sorted((by[a] == "deal", by[a + 1] == "deal")))] += 1
n = sum(pairs.values())
p = st.get("deal", 0) / len(dc)
print(f"pairs with both closed: {n}; both deal {pairs[(True, True)]}, split {pairs[(False, True)]}, both no_deal {pairs[(False, False)]}")
print(f"  expected if independent at p={p:.3f}: both deal {n*p*p:.1f}, split {n*2*p*(1-p):.1f}, both no_deal {n*(1-p)**2:.1f}")
ours = {9, 10, 23, 24, 29, 30, 37, 38, 91, 92, 93, 94}
print(f"our closed duels in public feed: {sorted((d, by.get(d)) for d in ours)}")

# leaderboard: is there any duel field? did practice move anything?
rows = [json.loads(l) for l in open(os.path.join(SNAP, "logs", "feed", "snapshots.jsonl"))]
lb = [r for r in rows if r["what"] == "leaderboard"]
tkeys = Counter(k for r in lb for t in r["body"]["teams"] for k in t)
print(f"leaderboard snapshots: {len(lb)}, ticks {lb[0]['tick']}..{lb[-1]['tick']}; team keys: {sorted(tkeys)}")
sc = [json.loads(l) for l in open(os.path.join(SNAP, "logs", "score.jsonl"))]
print("our /api/me duel_points over time: " + ", ".join(f"t{r['tick']}:{r['score'].get('duel_points')}(duels={r.get('duels')})" for r in sc))
