"""Mirror hypothesis tests on our 18 practice duels.

H_reveal : the rival's first / repeated / final price equals our your_limit in the SAME duel.
H_same   : the rival's limit equals our limit in the same duel (implies zero pie: buyer value == seller cost).
H_pair   : the rival's limit equals OUR limit in the PAIRED duel (ids odd/odd+1, same item, roles swapped).
           Rival limits are never shown, so H_pair is only testable by consistency: a limit-respecting rival
           never bids above its value / asks below its cost.
"""
import re
from collections import Counter

from common import duels, partner_id, rival_msgs

D = duels()
rows = []
print("duel role  L  pairL | rival first mode(xN) final | first/L  first==L anyprice==L | H_pair viol | H_same viol")
for did, d in D.items():
    rm = rival_msgs(d)
    p = D.get(partner_id(did))
    pairL = p["your_limit"] if p and p["item"] == d["item"] and p["role"] != d["role"] else None
    if not rm:
        print(f"{did:4d} {d['role']:6s} {d['your_limit']:4d} {pairL} | no rival prices")
        continue
    prices = [m["price"] for m in rm]
    L = d["your_limit"]
    first, final = prices[0], prices[-1]
    mode, n = Counter(prices).most_common(1)[0]
    # rival role is the opposite of ours
    if d["role"] == "seller":  # rival is buyer; H_pair: rival value = pairL; violation if bid > pairL
        hp = [x for x in prices if pairL is not None and x > pairL]
        hs = [x for x in prices if x > L]  # H_same: rival value = L
        margin = 1 - first / pairL  # how far below its (mirrored) value the rival buyer opened
    else:  # rival is seller; H_pair: rival cost = pairL; violation if ask < pairL
        hp = [x for x in prices if pairL is not None and x < pairL]
        hs = [x for x in prices if x < L]
        margin = first / pairL - 1
    r = dict(duel=did, role=d["role"], L=L, pairL=pairL, rival=d["rival"], first=first, mode=mode, mode_n=n,
             final=final, n=len(prices), first_over_L=round(first / L, 3), first_eq_L=first == L,
             any_eq_L=L in prices, near_L=abs(first - L) <= 2, hp_viol=len(hp), hs_viol=len(hs),
             pair_margin=round(margin, 3))
    rows.append(r)
    print(f"{did:4d} {d['role']:6s} {L:4d} {pairL:4d} | {d['rival']:11s} {first:4d} {mode:4d}(x{n}) {final:4d} | "
          f"{first/L:5.3f} {str(first==L):5s} {str(L in prices):5s} | {len(hp)}/{len(prices)} | {len(hs)}/{len(prices)}"
          f" | open margin vs pairL {margin:+.3f}")

print()
k = len(rows)
print(f"duels with rival prices: {k} of {len(D)}")
print(f"H_reveal: first price == our limit: {sum(r['first_eq_L'] for r in rows)}/{k}; "
      f"any rival price == our limit: {sum(r['any_eq_L'] for r in rows)}/{k}; "
      f"first within +-2 of limit: {sum(r['near_L'] for r in rows)}/{k}; "
      f"mode == limit: {sum(r['mode']==r['L'] for r in rows)}/{k}; final == limit: {sum(r['final']==r['L'] for r in rows)}/{k}")
fol = [r["first_over_L"] for r in rows]
print(f"  rival first / our limit: min {min(fol)} max {max(fol)} mean {sum(fol)/k:.3f}")
print(f"H_same: duels with >=1 rival price across our own limit (would breach a rival limit equal to ours): "
      f"{sum(r['hs_viol']>0 for r in rows)}/{k}")
print(f"H_pair: duels with >=1 rival price that would breach the mirrored limit: "
      f"{sum(r['hp_viol']>0 for r in rows)}/{k} -> {[r['duel'] for r in rows if r['hp_viol']]}")

# pair-level view
pairs = sorted({min(d, partner_id(d)) for d in D})
print("\npair  item                    our cost  our value  value>cost  same-rival-template  both-sides-priced  H_pair-viol")


def template(d):
    return {re.sub(r"\d+", "N", m["text"]) for m in d["messages"] if m["from"] != "you"}


nz = 0
pv = 0
both = 0
same_tpl = 0
for a in pairs:
    da, db = D[a], D[a + 1]
    sell = da if da["role"] == "seller" else db
    buy = db if sell is da else da
    t_a, t_b = template(da), template(db)
    shared = bool(t_a & t_b)
    priced = bool(rival_msgs(da)) and bool(rival_msgs(db))
    viol = any(r["hp_viol"] for r in rows if r["duel"] in (a, a + 1))
    nz += buy["your_limit"] > sell["your_limit"]
    pv += viol
    both += priced
    same_tpl += shared
    print(f"{a}/{a+1}  {da['item']:22s} {sell['your_limit']:8d} {buy['your_limit']:10d}  {str(buy['your_limit'] > sell['your_limit']):10s} "
          f"{str(shared):20s} {str(priced):18s} {viol}")
print(f"\npairs: {len(pairs)}; our value > our cost in {nz}/{len(pairs)}; both duels priced by rival in {both}; "
      f"identical rival text template across the pair in {same_tpl}/{len(pairs)}; pairs with an H_pair violation: {pv}")

# symmetric-margin check on pairs priced on both sides
print("\nopening margin vs mirrored limit (rival buyer: 1-first/value, rival seller: first/cost-1):")
for a in pairs:
    ra = [r for r in rows if r["duel"] in (a, a + 1)]
    if len(ra) == 2:
        print(f"  {a}/{a+1}: " + ", ".join(f"duel {r['duel']} rival-{'buyer' if r['role']=='seller' else 'seller'} {r['pair_margin']:+.3f}" for r in ra))
