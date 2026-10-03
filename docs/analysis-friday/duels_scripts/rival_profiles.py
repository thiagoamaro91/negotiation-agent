"""Do rival aliases map to behaviours? Profile each rival (per alias and per pair = rival team)."""
import re
from collections import defaultdict

from common import duels, partner_id, rival_msgs, surplus

D = duels()


def tpl(text):
    t = re.sub(r"\d+", "N", text)
    return t[:40]


alias = defaultdict(set)
for d in D.values():
    ts = {tpl(m["text"]) for m in d["messages"] if m["from"] != "you"}
    alias[d["rival"]].add((d["duel"], next(iter(sorted(ts))) if ts else "(silent)"))
print("alias -> (duel, first rival text template):")
for a, v in sorted(alias.items()):
    styles = {s for _, s in v}
    print(f"  {a:12s} {len(v)} duels, {len(styles)} distinct styles: {sorted(v)}")

print("\nper duel behaviour (rival prices only, our-favourable step = + ):")
print("duel role rival        n  ticks  repeats  first%L  final%L  final/pairL  steps(+ = toward us)        monotone")
for did, d in D.items():
    rm = rival_msgs(d)
    if not rm:
        continue
    L = d["your_limit"]
    pl = D[partner_id(did)]["your_limit"]
    p = [m["price"] for m in rm]
    sgn = 1 if d["role"] == "seller" else -1  # seller: rival buyer raising is toward us
    steps = [sgn * (b - a) for a, b in zip(p, p[1:])]
    rep = sum(1 for s in steps if s == 0)
    mono = all(s >= 0 for s in steps)
    span = rm[-1]["tick"] - rm[0]["tick"]
    print(f"{did:4d} {d['role']:6s} {d['rival']:11s} {len(p):2d} {span:5d} {rep:7d}  {100*p[0]/L:6.1f}  {100*p[-1]/L:6.1f}  "
          f"{p[-1]/pl:9.3f}   {str(steps):28s} {mono}")

print("\nfinal rival price vs our PAIRED limit (|final/pairL - 1|), duels with >=3 rival prices:")
dev = []
for did, d in D.items():
    rm = rival_msgs(d)
    if len(rm) >= 3:
        pl = D[partner_id(did)]["your_limit"]
        x = rm[-1]["price"] / pl - 1
        dev.append((did, round(x, 3)))
print(f"  {dev}")
print(f"  within +-7%: {sum(abs(x) <= 0.07 for _, x in dev)}/{len(dev)}; crossing the paired limit (rival would breach if exact mirror): "
      f"{[did for did, x in dev if (D[did]['role']=='seller' and x > 0) or (D[did]['role']=='buyer' and x < 0)]}")

print("\nchange-ratio test: |rival-buyer price move| / |rival-seller price move| vs our value/cost in the pair")
for a in sorted({min(x, partner_id(x)) for x in D}):
    da, db = D[a], D[a + 1]
    sell_us = da if da["role"] == "seller" else db  # rival is buyer here
    buy_us = db if sell_us is da else da            # rival is seller here
    rb, rs = rival_msgs(sell_us), rival_msgs(buy_us)
    if len(rb) >= 2 and len(rs) >= 2:
        mb = abs(rb[-1]["price"] - rb[0]["price"])
        ms = abs(rs[-1]["price"] - rs[0]["price"])
        print(f"  {a}/{a+1}: {mb}/{ms} = {mb/ms:.3f}  vs our value/cost {buy_us['your_limit']}/{sell_us['your_limit']} = "
              f"{buy_us['your_limit']/sell_us['your_limit']:.3f}")
