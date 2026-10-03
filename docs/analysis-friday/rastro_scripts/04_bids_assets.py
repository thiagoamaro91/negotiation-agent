# Bids (buy orders) by card/team, unique-asset sell outcomes, competition for our spares, fee payer check.
import json, collections, statistics as stt
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
BOOK={'common':10,'uncommon':25,'rare':70,'epic':180,'legendary':450}
cat=json.load(open(S+'/branches/catalog.json'))
cards=cat['cards'] if isinstance(cat,dict) and 'cards' in cat else cat
rar={c['ref']:c['rarity'] for c in cards} if isinstance(cards,list) else {}
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
offs={e['payload']['offer']['id']:e['payload']['offer'] for e in ev if e['type']=='offer.listed'}
st=[e['payload'] for e in ev if e['type']=='settlement' and e['payload']['venue']=='rastro']
# ---- bids
bids=[o for o in offs.values() if o['give']['cash'] and not o['give']['assets']]
byc=collections.defaultdict(list)
for o in bids:
    for t in o['want']['types']: byc[t.split(':')[1]].append((o['give']['cash'],o['maker'],o['created_tick']))
print('BIDS by card (max bid, n, distinct teams, prices):')
for c in sorted(byc,key=lambda c:(rar.get(c,''),c)):
    v=byc[c]; print(f"  {c} {rar.get(c)} max {max(x[0] for x in v)} n {len(v)} teams {sorted(set(x[1] for x in v))} prices {sorted(set(x[0] for x in v))}")
print('bid makers:',collections.Counter(o['maker'] for o in bids).most_common())
print('bid team x set:',sorted(collections.Counter((o['maker'],t.split(':')[1][:3]) for o in bids for t in o['want']['types']).items()))
# ---- unique asset outcomes for sell listings
sold={(s['items'][0]['id']) for s in st}
book159=[json.loads(l) for l in open(S+'/logs/feed/snapshots.jsonl')]
b159=[s for s in book159 if s['what']=='rastro' and s['tick']==159][0]['body']['offers']
open_assets={x['id'] for o in b159 for x in o['give']['assets']}
ua=collections.defaultdict(list)
for o in offs.values():
    if o['give']['assets'] and o['want']['cash'] and 'rarity' in o['give']['assets'][0]:
        x=o['give']['assets'][0]; ua[(o['maker'],x['id'],x['ref'],x['rarity'])].append((o['created_tick'],o['want']['cash']))
oc=collections.Counter(); asks=collections.defaultdict(list)
for (m,aid,ref,r),v in ua.items():
    k='sold' if aid in sold else 'open@159' if aid in open_assets else 'unsold/withdrawn'
    oc[(r,k)]+=1; asks[(r,k)].append(min(p for _,p in v))
print('UNIQUE ASSETS listed for cash (feed-visible):',len(ua))
for k in sorted(oc): print('  ',k,oc[k],'lowest ask seen: median',stt.median(asks[k]),'range',min(asks[k]),max(asks[k]))
# ---- competition for our spares on the book over time (ticks 134-159)
sn=[s for s in book159 if s['what']=='rastro']
for ref in ('LAV-08','MAL-06','MAL-08','MAL-07','LAV-01','LAV-03','LAV-05'):
    seen={}
    for s in sn:
        for o in s['body']['offers']:
            for x in o['give']['assets']:
                if x.get('ref')==ref: seen[o['id']]=(o['maker'],o['want']['cash'],o['created_tick'],o['expires_tick'])
    print('book history',ref,sorted(set(seen.values()),key=lambda x:x[2]))
# ---- fee payer: our cash around our sale at tick 147
for l in open(S+'/mini/dashboard_history.jsonl'):
    d=json.loads(l)
    if 140<=d['tick']<=152: print('dash',d['tick'],'cash',d['cash'],'score',d['score'])
