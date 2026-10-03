#!/usr/bin/env python3
"""Dealer concession analysis over threads.json (+ our own thread files for the feed gap).

Run parse_threads.py first. Prints all tables to stdout (tee to analysis.txt).
"""
import json, os, glob, statistics as st, collections

S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(S, 'snap')
R = json.load(open(os.path.join(S, 'out/dealers_scripts/threads.json')))
cat = json.load(open(os.path.join(SNAP, 'branches/catalog.json')))
cards = {c['id']: dict(set=s['id'], rarity=c['rarity'], book=c['book']) for s in cat['sets'] for c in s['cards']}
DEALERS = {'abuela', 'chato'}
GAP_LO, GAP_HI, FEED_END = 48, 119, 159

# ---- add our own thread files that fall in the feed gap ----
in_feed = {r['thread'] for r in R}
for f in sorted(glob.glob(os.path.join(SNAP, 'logs/threads/thread-*.json'))):
    d = json.load(open(f))
    if d['id'] in in_feed or d['with'] not in DEALERS:
        continue
    topic = d['topic']; side = 'buy' if 'buy' in topic else 'sell'
    (ik, it), = topic[side].items()
    ev = []
    for m in d['messages']:
        o = m.get('offer') or {}
        pr = (o.get('give', {}).get('cash') or 0) or (o.get('want', {}).get('cash') or 0) if o else None
        ev.append((m['tick'], m['id'], 'D' if m['sender'] in DEALERS else 'T', pr, bool(o.get('final'))))
    dseq = [e[3] for e in ev if e[2] == 'D' and e[3] is not None]
    tseq = [e[3] for e in ev if e[2] == 'T' and e[3] is not None]
    settled = [m for m in d['messages'] if (m.get('offer') or {}).get('status') == 'settled']
    rec = dict(thread=d['id'], team=d['team'], dealer=d['with'], side=side, item_kind=ik, item=it,
               open_tick=d['created_tick'], opened_missing=False, source='thread_file', events=ev,
               dealer_seq=dseq, team_seq=tseq, opening=dseq[0] if dseq else None,
               final_offer=next((e[3] for e in ev if e[2] == 'D' and e[4]), None),
               n_team_bids=len(tseq), n_dealer_msgs=len(dseq))
    if ik == 'card':
        rec.update(cards[it])
    else:
        rec.update(set=None, rarity='pack:' + it, book=None)
    if d['status'] == 'deal' and settled:
        o = settled[-1]['offer']
        rec['deal_price'] = (o['give'].get('cash') or 0) or (o['want'].get('cash') or 0)
        rec['outcome'] = 'deal'
        rec['closed_on'] = 'dealer_final' if settled[-1]['sender'] in DEALERS and o.get('final') else (
            'dealer_ask' if settled[-1]['sender'] in DEALERS else 'team_bid_accepted')
        rec['deal_tick'] = settled[-1]['tick']
    else:
        rec['deal_price'] = None
        rec['outcome'] = 'walk_after_final' if rec['final_offer'] is not None else 'no_deal'
    rec['welcome'] = rec['outcome'] == 'deal' and len(dseq) == 1 and not tseq
    R.append(rec)


for r in R:
    r.setdefault('rarity', None); r.setdefault('book', None)
    if r.get('rarity') is None and r.get('item_kind') == 'pack':
        r['rarity'] = 'pack:' + r['item']


def last_tick(r):
    return max((e[0] for e in r['events']), default=r['open_tick'])


def censored(r):
    if r['outcome'] == 'deal':
        return False
    lt = last_tick(r)
    return (GAP_LO - 2 <= lt <= GAP_LO) or lt >= FEED_END - 2


def rounds_to_deal(r):
    """team priced bids before the deal (all bids for deals)."""
    return r['n_team_bids']


def q(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return '-'
    return f"{xs[0]}/{st.median(xs):g}/{xs[-1]}"


def med(xs):
    xs = [x for x in xs if x is not None]
    return f"{st.median(xs):g}" if xs else '-'


print('== 0. Coverage ==')
print('records', len(R), 'from thread files', sum(r.get('source') == 'thread_file' for r in R))
print('feed gap ticks 49-118; feed end tick 159; Chato open_to_all tick 158')

# ---- DONE CHECK: our deals ----
print('\n== DONE CHECK: our (t03) deals ==')
for r in sorted(R, key=lambda r: r['thread']):
    if r['team'] == 't03' and r['outcome'] == 'deal':
        print(f"  thread {r['thread']} {r['dealer']} {r['item']} price {r['deal_price']} src {r.get('source','feed')} closed_on {r.get('closed_on')}")

# ---- 1. per dealer x side x rarity ----
print('\n== 1. Per dealer x side x rarity (field, all teams) ==')
print('dealer|side|rarity|threads|deals|welcome|negotiated|walk_after_final|no_deal|censored|opening med (min-max)|final deal min/med/max (negotiated)|welcome prices|team bids to deal med|dealer final offer min/med/max')
groups = collections.defaultdict(list)
for r in R:
    groups[(r['dealer'], r['side'], r['rarity'])].append(r)
for k in sorted(groups, key=lambda k: (str(k[0]), str(k[1]), str(k[2]))):
    g = groups[k]
    deals = [r for r in g if r['outcome'] == 'deal']
    wel = [r for r in deals if r['welcome']]
    neg = [r for r in deals if not r['welcome']]
    unc = [r for r in g if not censored(r)]
    walks = [r for r in unc if r['outcome'] == 'walk_after_final']
    nod = [r for r in unc if r['outcome'] in ('no_deal', 'empty')]
    cens = [r for r in g if censored(r)]
    ops = [r['opening'] for r in g if not r['opened_missing'] and r['opening'] is not None and r['first_sender' if 'first_sender' in r else 'dealer'] is not None]
    # opening = first dealer price; exclude threads opened in gap
    ops = [r['opening'] for r in g if not r['opened_missing'] and r['opening'] is not None]
    rng = f"{min(ops)}-{max(ops)}" if ops else '-'
    print(f"{k[0]}|{k[1]}|{k[2]}|{len(g)}|{len(deals)}|{len(wel)}|{len(neg)}|{len(walks)}|{len(nod)}|{len(cens)}|{med(ops)} ({rng})|{q([r['deal_price'] for r in neg])}|{sorted(r['deal_price'] for r in wel)}|{med([rounds_to_deal(r) for r in neg])}|{q([r['final_offer'] for r in g])}")

# ---- 2. Chato rares, every thread ----
print('\n== 2. Chato rare threads (all teams) ==')
for r in sorted(R, key=lambda r: r['thread']):
    if r['dealer'] == 'chato' and r['rarity'] == 'rare':
        print(f"  th {r['thread']} {r['team']} {r['side']} {r['item']} open_tick {r['open_tick']} last {last_tick(r)} dealer {r['dealer_seq']} team {r['team_seq']} final {r['final_offer']} -> {r['outcome']} {r.get('deal_price')} {r.get('closed_on','')} cens={censored(r)} gapopen={r['opened_missing']}")

# ---- all chato buy uncommon threads ----
print('\n== 2b. Chato uncommon buy threads ==')
for r in sorted(R, key=lambda r: r['thread']):
    if r['dealer'] == 'chato' and r['rarity'] == 'uncommon' and r['side'] == 'buy':
        b = r['team_seq']; op = r['opening']
        print(f"  th {r['thread']} {r['team']} {r['item']} dealer {r['dealer_seq']} team {b} final {r['final_offer']} -> {r['outcome']} {r.get('deal_price')} {r.get('closed_on','')} cens={censored(r)}")

# ---- 3. below-median negotiated deals ----
print('\n== 3. Deals at or below group median (negotiated buys) ==')
for k in sorted(groups, key=lambda k: (str(k[0]), str(k[1]), str(k[2]))):
    if k[1] != 'buy':
        continue
    neg = [r for r in groups[k] if r['outcome'] == 'deal' and not r['welcome']]
    if len(neg) < 2:
        continue
    m = st.median([r['deal_price'] for r in neg])
    print(f" {k} median {m:g} n {len(neg)}")
    for r in sorted(neg, key=lambda r: r['deal_price']):
        b = r['team_seq']; op = r['opening']
        steps = [y - x for x, y in zip(b, b[1:])]
        pct = f"{100*b[0]/op:.0f}%" if b and op else '-'
        tag = 'LOW' if r['deal_price'] < m else ('MED' if r['deal_price'] == m else 'high')
        print(f"   {tag} th {r['thread']} {r['team']} {r['item']} price {r['deal_price']} open {op} first_bid {b[0] if b else '-'} ({pct}) steps {steps} nbids {len(b)} closed_on {r.get('closed_on')} dealer {r['dealer_seq']}")

# ---- 4. step-size response ----
print('\n== 4. Dealer concession vs team step ==')
pairs = collections.defaultdict(list)  # dealer -> (team_step, dealer_drop, rarity)
viol = collections.Counter(); tot = collections.Counter()
for r in R:
    if r['side'] != 'buy':
        continue
    last_bid = prev_bid = None; last_ask = None; step = None; bid_changed = False
    for (tick, mid, who, price, fin) in r['events']:
        if price is None:
            continue
        if who == 'T':
            if last_bid is not None:
                step = price - last_bid
            else:
                step = None
            last_bid = price; bid_changed = True
        else:
            if last_ask is not None and bid_changed:
                drop = last_ask - price
                pairs[r['dealer']].append((step, drop, r['rarity'], fin, r['thread']))
                if step is not None:
                    tot[r['dealer']] += 1
                    if drop > max(step, 1) and not fin:
                        viol[r['dealer']] += 1
                bid_changed = False
            last_ask = price
for d, ps in pairs.items():
    tab = collections.defaultdict(list)
    for s, dr, rar, fin, th in ps:
        if fin:
            continue
        tab[(rar, s)].append(dr)
    print(f" {d}: non-final concessions, (rarity, team_step) -> dealer drops [n, mean, list]")
    for kk in sorted(tab, key=lambda x: (str(x[0]), -999 if x[1] is None else x[1])):
        v = tab[kk]
        print(f"   {kk}: n={len(v)} mean={st.mean(v):.2f} {sorted(v)[:15]}")
    print(f"   drops larger than team step (non-final): {viol[d]} of {tot[d]}")

# first concession vs opening bid %
print('\n== 4b. First dealer concession vs first team bid as % of opening (buys) ==')
for d in ('abuela', 'chato'):
    rows = []
    for r in R:
        if r['dealer'] != d or r['side'] != 'buy' or r['opened_missing'] or not r['team_seq'] or not r['opening']:
            continue
        ds = r['dealer_seq']
        first_drop = next((ds[0] - x for x in ds[1:] if x != ds[0]), 0)
        rows.append((str(r['rarity']), round(100 * r['team_seq'][0] / r['opening']), first_drop, r['thread'], r['opening']))
    rows.sort()
    for row in rows:
        print('  ', d, row)

# Chato final vs path
print('\n== 4c. Final offer vs path (buys with a final) ==')
for r in sorted(R, key=lambda r: (r['dealer'], str(r['rarity']), r['thread'])):
    if r['side'] == 'buy' and r['final_offer'] is not None:
        b = r['team_seq']
        print(f"  {r['dealer']} {r['rarity']} th {r['thread']} {r['team']} open {r['opening']} final {r['final_offer']} final/open {r['final_offer']/r['opening'] if r['opening'] else 0:.2f} nbids {len(b)} first {b[0] if b else '-'} last {b[-1] if b else '-'} -> {r['outcome']}")

# ---- 5. sell side ----
print('\n== 5. Sell side (team sells to dealer) ==')
for r in sorted(R, key=lambda r: r['thread']):
    if r['side'] == 'sell':
        print(f"  {r['dealer']} th {r['thread']} {r['team']} tick {r['open_tick']} {r['item']} {r['rarity']} book {r.get('book')} dealer_bids {r['dealer_seq']} team_asks {r['team_seq']} final {r['final_offer']} -> {r['outcome']} {r.get('deal_price')}")

json.dump(R, open(os.path.join(S, 'out/dealers_scripts/threads_merged.json'), 'w'), indent=1)
