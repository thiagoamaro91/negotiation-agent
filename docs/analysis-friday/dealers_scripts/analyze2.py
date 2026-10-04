#!/usr/bin/env python3
"""Second pass: welcome reclass, closed_on effect, packs, gifts, unlocks, a former teammate checks.
Needs threads_merged.json from analyze.py."""
import json, os, statistics as st, collections

S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(S, 'snap')
R = json.load(open(os.path.join(S, 'out/dealers_scripts/threads_merged.json')))
WELCOME = {'common': 7, 'uncommon': 17, 'pack:sobre_barrio': 17}
for r in R:
    w = WELCOME.get(r.get('rarity'))
    r['welcome2'] = (r['outcome'] == 'deal' and r['dealer'] == 'abuela' and r['side'] == 'buy' and w is not None
                     and r['deal_price'] == w and (r['opening'] in (None, w)))


def q(xs):
    xs = sorted(xs)
    return f"n={len(xs)} {xs[0]}/{st.median(xs):g}/{xs[-1]}" if xs else 'n=0'


print('== A. Abuela/Chato negotiated buys: price by how the deal closed (welcome-price deals removed) ==')
for d in ('abuela', 'chato'):
    for rar in ('common', 'uncommon', 'pack:sobre_barrio', 'rare'):
        g = [r for r in R if r['dealer'] == d and r['side'] == 'buy' and r.get('rarity') == rar and r['outcome'] == 'deal' and not r['welcome2']]
        if not g:
            continue
        by = collections.defaultdict(list)
        for r in g:
            by[r.get('closed_on')].append(r['deal_price'])
        print(f" {d} {rar} all {q([r['deal_price'] for r in g])} | " + ' | '.join(f"{k}: {q(v)}" for k, v in sorted(by.items(), key=lambda x: str(x[0]))))
        # first bid % and mean step vs price
        rows = []
        for r in g:
            b = r['team_seq']
            if not b or not r['opening'] or r['opened_missing']:
                continue
            steps = [y - x for x, y in zip(b, b[1:])]
            rows.append((r['deal_price'], round(100 * b[0] / r['opening']), round(st.mean(steps), 1) if steps else 0, len(b), b[-1], r.get('closed_on')))
        if len(rows) >= 4:
            lo = [x for x in rows if x[0] <= st.median([y[0] for y in rows])]
            hi = [x for x in rows if x[0] > st.median([y[0] for y in rows])]
            for name, part in (('<=median', lo), ('>median', hi)):
                if part:
                    print(f"    {name}: n={len(part)} first_bid% med {st.median([x[1] for x in part]):g} mean_step med {st.median([x[2] for x in part]):g} nbids med {st.median([x[3] for x in part]):g} last_bid med {st.median([x[4] for x in part]):g}")

print('\n== B. Welcome-price deals (Abuela opening at 17/7) ==')
for r in R:
    if r['welcome2']:
        print(f"  th {r['thread']} {r['team']} {r['item']} {r['rarity']} price {r['deal_price']} tick {r['open_tick']}")
first_contact = collections.defaultdict(list)
for r in sorted(R, key=lambda r: r['thread']):
    if r['dealer'] == 'abuela' and r['side'] == 'buy' and r['opening'] is not None and not r['opened_missing']:
        first_contact[(r['team'], r['rarity'])].append((r['thread'], r['opening']))
print('  per team x rarity: sequence of Abuela openings (shows whether 17/7 is only the first contact)')
for k, v in sorted(first_contact.items(), key=lambda x: (x[0][0], str(x[0][1]))):
    print('   ', k, v)

# ---- feed events for packs, gifts, unlocks ----
ev = [json.loads(l) for l in open(os.path.join(SNAP, 'logs/feed/feed.jsonl'))]
ev.sort(key=lambda e: e['id'])
print('\n== C. Pack settlements and pack.opened ==')
packs = []
for e in ev:
    p = e['payload'] if isinstance(e['payload'], dict) else {}
    if e['type'] == 'settlement':
        for it in p.get('items', []):
            if it.get('kind') == 'pack':
                packs.append((e['tick'], p.get('persona') or p.get('venue'), it['to'], it['ref'], p.get('price')))
    if e['type'] == 'pack.opened':
        packs.append((e['tick'], 'OPENED', p.get('team'), p.get('pack'), p.get('best')))
for x in packs:
    print('  ', x)
opened = [x for x in packs if x[1] == 'OPENED']
best = collections.Counter(json.dumps(x[4]) if not isinstance(x[4], str) else x[4] for x in opened)
print('  opened n', len(opened), 'best field values:', best.most_common(10))

print('\n== D. Gifts ==')
sett_ticks = collections.defaultdict(list)
for e in ev:
    p = e['payload'] if isinstance(e['payload'], dict) else {}
    if e['type'] == 'settlement' and p.get('persona'):
        for x in p['parties']:
            if x != p['persona']:
                sett_ticks[x].append((e['tick'], p['persona'], p.get('price')))
for e in ev:
    p = e['payload'] if isinstance(e['payload'], dict) else {}
    if e['type'] == 'gift.given':
        near = [s for s in sett_ticks[p['team']] if 0 <= e['tick'] - s[0] <= 3]
        print(f"  tick {e['tick']} actor {e['actor']} {p['team']} cash {p['cash']} packs {p['packs']} cards {p['cards']} reason {p.get('reason')} | settlement with dealer within 3 ticks before: {near}")

print('\n== E. level.unlocked ==')
for e in ev:
    p = e['payload'] if isinstance(e['payload'], dict) else {}
    if e['type'] in ('level.unlocked', 'persona.open_to_all'):
        print('  ', e['tick'], e['type'], json.dumps(p))

# which Abuela deals did unlocked teams have before unlocking (feed-visible only)
unl = {e['payload']['team']: e['tick'] for e in ev if e['type'] == 'level.unlocked'}
for t, tk in unl.items():
    ds = [(r['thread'], r['item'], r['deal_price'], 'WELCOME' if r['welcome2'] else '', r.get('deal_tick')) for r in R
          if r['team'] == t and r['dealer'] == 'abuela' and r['outcome'] == 'deal' and (r.get('deal_tick') or 0) <= tk]
    print(f"   {t} unlocked tick {tk}: abuela deals visible before: {ds}")

print('\n== F. Chato prices vs list (list from rules anchor: unc 26, rare 77, silver 150) ==')
for rar, lst in (('uncommon', 26), ('rare', 77), ('pack:sobre_plata', 150)):
    ps = [r['deal_price'] for r in R if r['dealer'] == 'chato' and r['side'] == 'buy' and r.get('rarity') == rar and r['outcome'] == 'deal']
    if ps:
        print(f"  {rar}: deals {sorted(ps)} min/list {min(ps)/lst:.3f} open/list {97/77 if rar=='rare' else (33/26 if rar=='uncommon' else 188/150):.3f}")
print('  Abuela list (anchor): unc 25, pack 26, common 10')
for rar, lst in (('uncommon', 25), ('pack:sobre_barrio', 26), ('common', 10)):
    ps = [r['deal_price'] for r in R if r['dealer'] == 'abuela' and r['side'] == 'buy' and r.get('rarity') == rar and r['outcome'] == 'deal' and not r['welcome2']]
    print(f"  {rar}: min {min(ps)} min/list {min(ps)/lst:.2f} median/list {st.median(ps)/lst:.2f}")

print('\n== G. A former teammate claims check ==')
ab = [r for r in R if r['dealer'] == 'abuela']
for rar in ('uncommon', 'pack:sobre_barrio', 'common'):
    g = [r for r in ab if r['side'] == 'buy' and r.get('rarity') == rar]
    neg = [r for r in g if r['outcome'] == 'deal' and not r['welcome2']]
    ops = [r['opening'] for r in g if r['opening'] and not r['opened_missing'] and r['opening'] > WELCOME[rar]]
    fins = [r['final_offer'] for r in g if r['final_offer'] is not None and r['final_offer'] > WELCOME[rar]]
    acc = [r['deal_price'] for r in neg if r.get('closed_on') == 'team_bid_accepted']
    print(f"  {rar}: standard opening values {collections.Counter(ops)} | finals {sorted(fins)} | team bids accepted at {sorted(acc)} | negotiated deal prices {sorted(r['deal_price'] for r in neg)}")
sells = [r for r in ab if r['side'] == 'sell' and r['outcome'] == 'deal']
print('  abuela sell deals (rarity, price, tick):', sorted((r.get('rarity'), r['deal_price'], r['open_tick']) for r in sells))
