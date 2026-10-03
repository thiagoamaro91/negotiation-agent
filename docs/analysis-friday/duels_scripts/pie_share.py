"""Soft-mirror pie: share of (pairL - L) captured by the rival's LAST standing offer (INFERENCE: assumes rival limit ~ pairL)."""
from common import duels, partner_id, rival_msgs, surplus
D = duels()
hits, n = [], 0
for did, d in D.items():
    rm = rival_msgs(d)
    if not rm:
        continue
    L, pl = d["your_limit"], D[partner_id(did)]["your_limit"]
    last = d["rival_offer"]["price"] if d.get("rival_offer") else rm[-1]["price"]
    pie = surplus(d["role"], L, pl)
    sh = surplus(d["role"], L, last) / pie if pie else float("nan")
    n += 1
    hits.append(sh >= 0.85)
    print(f"duel {did:4d} {d['role']:6s} L {L:4d} pairL {pl:4d} mirrored pie {pie:4d} last {last:4d} share {sh:6.2f} {d['status']}")
print(f"last offer >= 0.85 x mirrored pie: {sum(hits)}/{n}")
ratios = sorted(round(max(D[a]['your_limit'], D[a+1]['your_limit'])/min(D[a]['your_limit'], D[a+1]['your_limit']), 3) for a in D if a % 2)
print(f"our pair value/cost ratios: {ratios}; below 1.55 (current anchor R): {sum(r < 1.55 for r in ratios)}/{len(ratios)}")
