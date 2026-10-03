#!/usr/bin/env python3
"""Summary table: per dealer x rarity buys. Excludes welcome-price deals and censored threads for rates."""
import json, os, statistics as st
S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = json.load(open(os.path.join(S, 'out/dealers_scripts/threads_merged.json')))
W = {'common': 7, 'uncommon': 17, 'pack:sobre_barrio': 17}
def cens(r):
    lt = max((e[0] for e in r['events']), default=r['open_tick'])
    return r['outcome'] != 'deal' and (46 <= lt <= 48 or lt >= 157)
for d, rar in (('abuela','common'),('abuela','uncommon'),('abuela','pack:sobre_barrio'),('chato','uncommon'),('chato','rare'),('chato','pack:sobre_plata')):
    g = [r for r in R if r['dealer']==d and r['side']=='buy' and r.get('rarity')==rar]
    wel = [r for r in g if r['outcome']=='deal' and r['deal_price']==W.get(rar) and r['opening'] in (None, W.get(rar))]
    neg = [r for r in g if r['outcome']=='deal' and r not in wel]
    engaged = [r for r in g if r not in wel and not cens(r) and r['team_seq']]
    walkf = [r for r in engaged if r['outcome']=='walk_after_final']
    left = [r for r in engaged if r['outcome'] in ('no_deal','empty')]
    ops = [r['opening'] for r in g if not r['opened_missing'] and r['opening'] and r['opening'] != W.get(rar)]
    ps = sorted(r['deal_price'] for r in neg)
    rd = [r['n_team_bids'] for r in neg]
    print(f"{d}|{rar}|neg deals {len(neg)} (+{len(wel)} welcome)|open med {st.median(ops) if ops else '-'}|final {ps[0]}/{st.median(ps):g}/{ps[-1]}|bids med {st.median(rd):g}|engaged {len(engaged)}: deal {sum(r['outcome']=='deal' for r in engaged)} walked-after-final {len(walkf)} left-without-final {len(left)}")
