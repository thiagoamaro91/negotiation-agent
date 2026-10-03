#!/usr/bin/env python3
"""Tests for the five OPEN questions. Read-only on the frozen snapshot."""
import json, os, collections
S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(S, 'snap')
BOOK = {'common': 10, 'uncommon': 25, 'rare': 70, 'epic': 180, 'legendary': 450}
MULT = {'LAV': 1.6, 'SAL': 1.3, 'LAT': 1.1, 'RET': 0.9, 'MAL': 0.7, 'CHA': 0.5}

def red(o):
    if isinstance(o, dict): return {k: red(v) for k, v in o.items()}
    if isinstance(o, list): return [red(v) for v in o]
    if isinstance(o, str) and o.startswith('tk-'): return '<REDACTED>'
    return o

lb = {}
for l in open(os.path.join(SNAP, 'logs/feed/snapshots.jsonl')):
    r = json.loads(l)
    if r['what'] == 'leaderboard':
        b = r['body']; lb[b['snapshot_tick']] = {t['team']: t for t in b['teams']}
ticks = sorted(lb)
ev = [json.loads(l) for l in open(os.path.join(SNAP, 'logs/feed/feed.jsonl'))]
dash = [json.loads(l) for l in open(os.path.join(SNAP, 'mini/dashboard_history.jsonl'))]
score = [json.loads(l) for l in open(os.path.join(SNAP, 'logs/score.jsonl'))]
me = red(json.load(open(os.path.join(SNAP, 'logs/state/me.json'))))

print('=== (a) ladder value gate, our team ===')
print('our raw ladder by score.jsonl row: ' + ', '.join(f"t{r['tick']} deals={r['score']['deals']} ladder={r['score']['ladder_points']} neg={r['score']['neg_points']} score={r['score']['score']}" for r in score))
ours = [(e['tick'], e['payload']) for e in ev if e['type'] == 'settlement' and 't03' in e['payload']['parties']]
def dash_at(t):
    c = [d for d in dash if d['tick'] <= t]; return c[-1] if c else None
for tk, p in ours:
    it = p['items'][0]; s = it['ref'][:3]
    nxt = 5 * ((tk // 5) + 1)
    pre, post = dash_at(tk - 1), dash_at(nxt)
    rar = 'uncommon' if int(it['ref'][4:]) in (6, 7, 8) else ('common' if int(it['ref'][4:]) <= 5 else 'rare')
    val = BOOK[rar] * MULT[s]
    others = ([tm for tm in lb[nxt] if tm != 't03' and lb[nxt][tm]['score'] != lb[nxt - 5][tm]['score']] if (nxt in lb and nxt - 5 in lb) else None)
    flat_ladder_only = ([tm for tm in ('t01','t02','t09','t16') if lb[nxt][tm]['score'] == lb[nxt - 5][tm]['score']] if others is not None else None)
    print(f"  tick {tk} {it['ref']} {it['frm']}->{it['to']} @{p['price']} single-copy value {val:.1f} gate={'PASS' if (it['to']=='t03' and val>p['price']) else ('n/a' if it['to']!='t03' else 'FAIL')} | board {pre and pre['score']} (t{pre and pre['tick']}) -> {post and post['score']} (t{post and post['tick']}); other teams moved: {len(others) if others is not None else 'no full board'}; ladder-only teams t01/t02/t09/t16 flat: {flat_ladder_only}")
print('  me.json your_value for chato buys:', {a['ref']: a['your_value'] for a in me['assets'] if a['ref'] in ('SAL-08', 'LAT-06', 'LAT-07')})

print('\n  other teams: dealer buys priced above book x 1.6 (fail the gate for ANY multiplier):')
n = 0
for e in ev:
    p = e['payload']
    if e['type'] != 'settlement' or not p.get('persona'): continue
    for it in p['items']:
        if it['kind'] != 'card' or not it['to'].startswith('t'): continue
        num = int(it['ref'][4:]); rar = 'common' if num <= 5 else 'uncommon' if num <= 8 else 'rare' if num <= 10 else 'epic' if num == 11 else 'legendary'
        if p['price'] > BOOK[rar] * 1.6:
            n += 1; print(f"    tick {e['tick']} {it['to']} {it['ref']}({rar}) @{p['price']} > {BOOK[rar]*1.6:.0f}")
print(f'    count={n}')

print('\n=== (b) neg_points decode ===')
dup = collections.Counter(a['ref'] for a in me['assets'])
for ref in ('LAV-01', 'LAV-08', 'MAL-08', 'MAL-06', 'LAV-06'):
    a = [x for x in me['assets'] if x['ref'] == ref][0]
    s = ref[:3]; num = int(ref[4:]); rar = 'common' if num <= 5 else 'uncommon'
    print(f"  {ref} copies={dup[ref]} your_value={a['your_value']} single={BOOK[rar]*MULT[s]:.2f} ratio={a['your_value']/(BOOK[rar]*MULT[s]):.3f}")
full = sum(a['your_value'] for a in me['assets'])
adj = sum(a['your_value'] * (4 if False else 1) for a in me['assets'])
first_full = 0.0; seen = set()
for a in me['assets']:
    s = a['ref'][:3]; num = int(a['ref'][4:]); rar = 'common' if num <= 5 else 'uncommon' if num <= 8 else 'rare'
    single = BOOK[rar] * MULT[s]
    first_full += single if a['ref'] not in seen else single * 0.25
    seen.add(a['ref'])
print(f"  collection_value={me['collection_value']} sum(your_value)={full:.1f} model(first copy full, extra copies 25%)={first_full:.1f}")
sale = 28; spare = 17.5 * 0.25
print(f"  MAL-08 spare sale: price {sale} - spare value {spare:.3f} = {sale-spare:.3f}; observed neg_points change = {18.7-(-4.9):.1f}")
print(f"  neg_points history: 0.0 at ticks 33..94 (deals 1..5), -4.9 at tick 146 (deals 8)")
chato = [(29, 32.5), (28, 27.5), (29, 27.5)]
print('  candidate (i) sum(value-price) chato:', sum(v - p for p, v in chato), '(ii) losses only:', sum(min(0, v - p) for p, v in chato))
print('  candidate (iii) LAV-08 bought @23 from abuela while already holding one: dup value 10 - 23 =', 10 - 23)
duel_res = []
for f in os.listdir(os.path.join(SNAP, 'logs/duels')):
    d = json.load(open(os.path.join(SNAP, 'logs/duels', f))); duel_res.append((d.get('status'), d.get('result')))
print('  our practice duels:', collections.Counter(s for s, _ in duel_res), 'sum result =', sum(r or 0 for _, r in duel_res))

print('\n=== (c) normalisation: top-1 vs top-3 ===')
for a, b in zip(ticks, ticks[1:]):
    if b > 45: break
    one = [tm for tm in lb[a] if lb[a][tm]['deals'] == 1 and lb[b][tm]['deals'] == 1 and lb[a][tm]['score'] > 0]
    base = [(lb[a][tm]['score'], lb[b][tm]['score']) for tm in one]
    pinned_a = [tm for tm in lb[a] if lb[a][tm]['score'] == 12.5]
    print(f"  {a}->{b}: one-deal baseline {sorted(set(base))} pinned@{a}={pinned_a} pinned@{b}={[tm for tm in lb[b] if lb[b][tm]['score']==12.5]}")
for tm in ('t05', 't06'):
    es = [(e['tick'], e['type'], json.dumps(e['payload'].get('items', e['payload'].get('cards', '')))[:90]) for e in ev if 30 < e['tick'] <= 35 and tm in json.dumps(e['payload']) and e['type'] in ('settlement', 'gift.given', 'pack.opened', 'level.unlocked')]
    print(f"  {tm} 30->35 score {lb[30][tm]['score']}->{lb[35][tm]['score']} deals {lb[30][tm]['deals']}->{lb[35][tm]['deals']} events in (30,35]: {es}")
# implied normaliser from our own raw ladder (dashboard reads board refreshes)
print('  our implied ladder normaliser m = 12.5*ladder/score:')
for t, lad in ((30, .022), (35, .022), (40, .022), (45, .022)):  # LAV-07 settled tick 46, after the t45 refresh
    print(f"    t{t}: score {lb[t]['t03']['score']} ladder {lad} -> m={12.5*lad/lb[t]['t03']['score']:.4f}")
for d in dash:
    if d['tick'] in (125, 130, 135, 145):
        lad = .062 if d['tick'] < 128 else .081
        print(f"    t{d['tick']}: score {d['score']} ladder {lad} -> m={12.5*lad/d['score']:.4f}{' (capped: ladder>=m)' if d['score']==12.5 else ''}")

print('\n=== (d) best-3 reset per day: only Friday data (one day) -> untestable')
print('=== (e) round weights in snapshot body:')
for l in open(os.path.join(SNAP, 'logs/feed/snapshots.jsonl')):
    r = json.loads(l)
    if r['what'] == 'leaderboard': last = r['body']
print('   rounds =', last['rounds'], 'weights =', last['weights'])
print('   changes.jsonl kinds:', collections.Counter(json.loads(l).get('what', json.loads(l).get('type', '?')) for l in open(os.path.join(SNAP, 'logs/feed/changes.jsonl'))))
