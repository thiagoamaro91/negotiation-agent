#!/usr/bin/env python3
"""List cases where the dealer dropped more than our last step; list Chato counterparties."""
import json, os, collections
S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = json.load(open(os.path.join(S, 'out/dealers_scripts/threads_merged.json')))
kinds = collections.Counter()
for r in R:
    if r['side'] != 'buy': continue
    last_bid = None; last_ask = None; step = None; changed = False; nconc = 0
    for (tick, mid, who, price, fin) in r['events']:
        if price is None: continue
        if who == 'T':
            step = price - last_bid if last_bid is not None else None
            last_bid = price; changed = True
        else:
            if last_ask is not None and changed:
                drop = last_ask - price
                if step is not None and drop > max(step, 1) and not fin:
                    kinds[(r['dealer'], 'concession#%d' % (nconc + 1), 'step<=0' if step <= 0 else 'step>0')] += 1
                    print(r['dealer'], r['thread'], r.get('rarity'), 'concession#', nconc + 1, 'step', step, 'drop', drop, 'asks', r['dealer_seq'], 'bids', r['team_seq'])
                if drop > 0: nconc += 1
                changed = False
            last_ask = price
print(kinds)
ch = sorted({r['team'] for r in R if r['dealer'] == 'chato'})
print('teams with chato threads', ch, len(ch))
print('first chato thread tick per team', sorted((min(r['open_tick'] for r in R if r['dealer']=='chato' and r['team']==t), t) for t in ch))
