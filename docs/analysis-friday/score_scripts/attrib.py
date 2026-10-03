#!/usr/bin/env python3
"""Leaderboard x feed attribution. Read-only on the frozen snapshot.
Usage: python3 attrib.py  (prints everything; run from anywhere)"""
import json, collections, statistics, os
S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(S, 'snap')
DEALERS = {'abuela', 'chato', 'lola', 'paco', 'remedios'}  # any non-tNN party is treated as dealer below

def is_team(x): return isinstance(x, str) and len(x) == 3 and x[0] == 't' and x[1:].isdigit()

# ---- leaderboard snapshots
lb = {}
for l in open(os.path.join(SNAP, 'logs/feed/snapshots.jsonl')):
    r = json.loads(l)
    if r['what'] == 'leaderboard':
        b = r['body']; lb[b['snapshot_tick']] = {t['team']: t for t in b['teams']}
ticks = sorted(lb); teams = sorted(lb[ticks[0]])
print('snapshot ticks:', ticks)

# ---- feed events per team
ev = [json.loads(l) for l in open(os.path.join(SNAP, 'logs/feed/feed.jsonl'))]
cov = sorted({e['tick'] for e in ev})
def covered(a, b):  # feed has events for every tick in (a,b]?  (black hole = 49..118)
    return not any(48 < t < 119 for t in range(a + 1, b + 1))
tev = collections.defaultdict(list)  # team -> [(tick, cat, detail)]
team_trades = []
for e in ev:
    p = e['payload']; ty = e['type']; tk = e['tick']
    if ty == 'settlement':
        parties = p.get('parties', [])
        if p.get('persona') or any(not is_team(x) for x in parties):
            for it in p['items']:
                if is_team(it['to']): tev[it['to']].append((tk, 'dealer_buy', f"{it['ref']}@{p.get('price')} from {it['frm']}"))
                if is_team(it['frm']): tev[it['frm']].append((tk, 'dealer_sell', f"{it['ref']}@{p.get('price')} to {it['to']}"))
        else:
            team_trades.append((tk, p))
            for it in p['items']:
                tev[it['frm']].append((tk, 'team_sell', f"{it['ref']}->{it['to']} @{p.get('price')} {p.get('venue')}"))
                tev[it['to']].append((tk, 'team_buy', f"{it['ref']}<-{it['frm']} @{p.get('price')} {p.get('venue')}"))
    elif ty == 'level.unlocked': tev[p['team']].append((tk, 'level_unlock', p.get('persona')))
    elif ty == 'pack.opened': tev[p['team']].append((tk, 'pack_opened', p.get('pack')))
    elif ty == 'gift.given': tev[p['team']].append((tk, 'gift', ','.join(p.get('cards', []))))
    elif ty == 'venue.opened': tev[p['owner']].append((tk, 'venue_opened', p['venue']))

print('\nteam-to-team settlements in covered feed:', len(team_trades))
for tk, p in team_trades:
    print('  tick', tk, p['venue'], 'price', p.get('price'), 'fee', p.get('fee'), [(i['ref'], i['kind'], i['frm'], i['to']) for i in p['items']])

# ---- per-team trajectory
print('\n== trajectory (score) ==')
print('team ' + ' '.join(f'{t:>6}' for t in ticks))
for tm in teams: print(tm, ' '.join(f"{lb[t][tm]['score']:6.2f}" for t in ticks))
print('\nteams pinned at exactly 12.50 / 30.00 per snapshot:')
for t in ticks:
    print(' ', t, 'at12.5:', [tm for tm in teams if lb[t][tm]['score'] == 12.5], 'at30:', [tm for tm in teams if lb[t][tm]['score'] == 30.0], 'max', max(lb[t][tm]['score'] for tm in teams))

# ---- interval table
rows = []
for a, b in zip(ticks, ticks[1:]):
    for tm in teams:
        d = round(lb[b][tm]['score'] - lb[a][tm]['score'], 2)
        es = [x for x in tev[tm] if a < x[0] <= b]
        boundary = [x for x in tev[tm] if x[0] in (a, b)]
        rows.append(dict(a=a, b=b, team=tm, d=d, prev=lb[a][tm]['score'], ev=es, cats=sorted({x[1] for x in es}),
                         boundary=any(x[0] == b for x in es), covered=covered(a, b),
                         ddeals=lb[b][tm]['deals'] - lb[a][tm]['deals']))
# noise: covered intervals, team had no events AND leaderboard deals unchanged
zero = [r for r in rows if r['covered'] and not r['ev'] and r['ddeals'] == 0]
absz = [abs(r['d']) for r in zero]
print(f"\nzero-event team-intervals n={len(zero)}: |delta| median={statistics.median(absz):.2f} p90={sorted(absz)[int(.9*len(absz))]:.2f} max={max(absz):.2f}; signed mean={statistics.mean(r['d'] for r in zero):+.2f}; #>0: {sum(r['d']>0 for r in zero)}")
NOISE = max(absz)
drift = {}
for a, b in zip(ticks, ticks[1:]):
    z = [r['d'] for r in zero if r['a'] == a]
    drift[a] = statistics.median(z) if z else 0.0

# ---- per-category deltas (pure intervals = one category only, covered, events not on boundary tick)
print('\n== avg score delta per event category (pure single-category intervals, covered feed) ==')
cat = collections.defaultdict(list); amb = collections.Counter()
for r in rows:
    if not r['covered']: continue
    if len(r['cats']) == 1:
        cat[r['cats'][0]].append(r)
    elif len(r['cats']) > 1:
        for c in r['cats']: amb[c] += 1
    elif r['ddeals'] > 0:
        cat['deal_not_in_feed'].append(r)
for c, rs in sorted(cat.items(), key=lambda kv: -statistics.mean(x['d'] for x in kv[1])):
    ds = [x['d'] for x in rs]; adj = [x['d'] - drift[x['a']] for x in rs]
    print(f"  {c:16s} n={len(rs):3d} mean={statistics.mean(ds):+6.2f} median={statistics.median(ds):+6.2f} drift-adj mean={statistics.mean(adj):+6.2f} max={max(ds):+6.2f} >noise({NOISE:.2f}):{sum(abs(x)>NOISE for x in ds)} | mixed-interval(AMBIGUOUS) n={amb[c]}")
print('  no-event (drift)  n=%d mean=%+.2f' % (len(zero), statistics.mean(r['d'] for r in zero)))
# any interval containing a team_sell / team_buy (incl. mixed)
for c in ('team_sell', 'team_buy'):
    rs = [r for r in rows if r['covered'] and c in r['cats']]
    if rs: print(f"  ANY-with-{c}: n={len(rs)} mean={statistics.mean(r['d'] for r in rs):+.2f} list=" + '; '.join(f"{r['team']}@{r['a']}->{r['b']}:{r['d']:+.2f}{'' if len(r['cats'])==1 else '(mixed '+'+'.join(r['cats'])+')'}" for r in rs))

# ---- top 5 jump attribution
fin = ticks[-1]
top5 = sorted(teams, key=lambda tm: -lb[fin][tm]['score'])[:5]
print('\n== top-5 jump attribution (|delta| > %.2f, the max zero-event drift) ==' % NOISE)
for tm in top5 + ['t03']:
    print(f" {tm} final {lb[fin][tm]['score']}")
    for r in rows:
        if r['team'] != tm or abs(r['d']) <= NOISE: continue
        if not r['covered']:
            lab = 'AMBIGUOUS(black hole, feed+board missing 49-118)'
        elif not r['ev']:
            lab = 'NO EVENT IN FEED' + (f" (but deals +{r['ddeals']})" if r['ddeals'] else ' -> normalisation drift')
        elif len(r['cats']) == 1 and not r['boundary']:
            lab = r['cats'][0]
        else:
            lab = 'AMBIGUOUS(' + '+'.join(r['cats']) + (', boundary tick' if r['boundary'] else '') + ')'
        print(f"   {r['a']:>3}->{r['b']:<3} {r['d']:+6.2f}  {lab:45s} {[x[1]+':'+x[2] for x in r['ev']][:4]}")

# ---- black hole 45->130 summary per team
print('\n== black hole 45->130: board fields ==')
for tm in sorted(teams, key=lambda tm: -lb[130][tm]['score']):
    x, y = lb[45][tm], lb[130][tm]
    print(f"  {tm} {x['score']:6.2f}->{y['score']:6.2f} deals {x['deals']}->{y['deals']} album {x['album_filled']}->{y['album_filled']} pages {x['pages_complete']}->{y['pages_complete']} lvl {x['level']}->{y['level']} venue {y['venue']}")

# ---- final board + activity counts in covered feed
print('\n== final board + covered-feed activity counts ==')
for tm in sorted(teams, key=lambda tm: -lb[fin][tm]['score']):
    c = collections.Counter(x[1] for x in tev[tm])
    y = lb[fin][tm]
    print(f"  #{y['rank']:>2} {tm} {y['score']:6.2f} deals {y['deals']:>2} album {y['album_filled']} pages {y['pages_complete']} venue {y['venue']} | " + ' '.join(f"{k}={v}" for k, v in sorted(c.items())))
json.dump([{k: v for k, v in r.items()} for r in rows], open(os.path.join(S, 'out/score_scripts/intervals.json'), 'w'), default=str)
