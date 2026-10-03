"""Our 18 practice duels: outcomes, rounds vs who spoke, and the silent-accept counterfactual."""
from common import duels, our_msgs, rival_msgs, surplus

D = duels()
closed = [d for d in D.values() if d["status"] != "live"]
live = [d for d in D.values() if d["status"] == "live"]
deals = [d for d in closed if d["status"] == "deal"]
print(f"duels: {len(D)}  closed: {len(closed)}  live at snapshot: {len(live)}  deals: {len(deals)}  "
      f"statuses: {sorted({d['status'] for d in D.values()})}")
print(f"results of closed duels: {sorted({d['result'] for d in closed})}")

print("\nrounds vs who spoke:")
combo = {}
for d in D.values():
    key = (len(our_msgs(d)) > 0, len([m for m in d['messages'] if m['from'] != 'you']) > 0)
    combo.setdefault(key, []).append((d["duel"], d["rounds"]))
for (we, they), v in sorted(combo.items()):
    print(f"  we spoke={we!s:5s} rival spoke={they!s:5s}: {len(v)} duels, rounds={sorted({r for _, r in v})} {[x for x, _ in v]}")

print("\nour own messages: count per duel, our opening as multiple of limit")
for d in D.values():
    for m in our_msgs(d):
        print(f"  duel {d['duel']} {d['role']} limit {d['your_limit']} sent {m['price']} at tick {m['tick']} "
              f"(x{m['price']/d['your_limit']:.3f}, {d['deadline_tick']-m['tick']} ticks before deadline)")

print("\nsilent-accept counterfactual (closed duels): best rival price inside our limit, and the last standing offer")
print("duel role  L   best  surplus%L  tick-to-deadline | last  surplus%L | rounds if accepted silently")
tot_best = tot_last = n_acc_last = n_acc_best = 0
by_last_tick = 0
for d in closed:
    rm = rival_msgs(d)
    if not rm:
        print(f"{d['duel']:4d} {d['role']:6s} {d['your_limit']:4d}  no rival offer (rival silent)")
        continue
    L = d["your_limit"]
    best = max(rm, key=lambda m: surplus(d["role"], L, m["price"]))
    last = d["rival_offer"]["price"] if d.get("rival_offer") else rm[-1]["price"]
    sb, sl = surplus(d["role"], L, best["price"]), surplus(d["role"], L, last)
    if sb > 0:
        n_acc_best += 1
        tot_best += sb / L
    if sl > 0:
        n_acc_last += 1
        tot_last += sl / L
    if best["tick"] == rm[-1]["tick"]:
        by_last_tick += 1
    print(f"{d['duel']:4d} {d['role']:6s} {L:4d} {best['price']:5d} {100*sb/L:8.1f}% {d['deadline_tick']-best['tick']:6d} | "
          f"{last:5d} {100*sl/L:8.1f}% | {d['rounds'] if not our_msgs(d) else 'n/a (we spoke)'}")
priced = [d for d in closed if rival_msgs(d)]
print(f"\nclosed duels with a rival price: {len(priced)}/{len(closed)}; an offer inside our limit existed in "
      f"{n_acc_best}/{len(priced)}; last standing offer inside our limit in {n_acc_last}/{len(priced)}")
print(f"mean surplus of last standing offer (when inside): {100*tot_last/max(1,n_acc_last):.1f}% of limit; "
      f"best offer came on the rival's last message in {by_last_tick}/{len(priced)}")

print("\nlive duels at snapshot: rival standing offer vs our limit")
for d in live:
    ro = d.get("rival_offer")
    if ro:
        s = surplus(d["role"], d["your_limit"], ro["price"])
        print(f"  {d['duel']} {d['role']} L {d['your_limit']} rival {ro['price']} surplus {s:+d} ({100*s/d['your_limit']:+.1f}%), "
              f"our offer {d['your_offer']['price'] if d['your_offer'] else None}, rounds {d['rounds']}")
    else:
        print(f"  {d['duel']} {d['role']} L {d['your_limit']} no rival offer, rounds {d['rounds']}")
