# Test value_inference.py's central assumption: "a price a team paid or bid for one card is a FLOOR: multiplier >= price/book".
# Floors from: card purchases in settlements (dealer + team) and rastro buy orders. Check (1) floors above the max
# multiplier 1.6, (2) per team, is there ANY assignment of the six shuffled multipliers that satisfies all its floors?
import json, collections, itertools
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
BOOK={'common':10,'uncommon':25,'rare':70,'epic':180,'legendary':450}
MULTS=(1.6,1.3,1.1,0.9,0.7,0.5)
cat=json.load(open(S+'/branches/catalog.json'))
def walk(o):
    if isinstance(o,dict):
        if 'ref' in o and 'rarity' in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)
RAR={c['id']:c['rarity'] for st_ in cat['sets'] for c in st_['cards']}
MINT={c['id']:c['minted'] for st_ in cat['sets'] for c in st_['cards']}
print('catalog values',cat['values'])
print('minted:',{k:MINT[k] for k in ('LAV-08','MAL-06','MAL-07','MAL-08','LAV-01','LAV-03','LAV-05','LAV-06','LAV-07')})
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
fl=[]  # (team,set,ref,price,ratio,source)
for e in ev:
    p=e['payload']
    if e['type']=='settlement':
        cardsin=[i for i in p['items'] if i['kind']=='card']
        if len(p['items'])==1 and cardsin and p['price']:
            i=cardsin[0]; fl.append((i['to'],i['set'],i['ref'],p['price'],p['price']/BOOK[i['rarity']],'paid-'+('team' if p['venue'] else 'dealer')))
    if e['type']=='offer.listed':
        o=p['offer']
        if o['give']['cash'] and not o['give']['assets'] and len(o['want']['types'])==1:
            ref=o['want']['types'][0].split(':')[1]
            if ref in RAR: fl.append((o['maker'],ref[:3],ref,o['give']['cash'],o['give']['cash']/BOOK[RAR[ref]],'bid'))
fl=[f for f in fl if f[0].startswith('t')]
print('floors',len(fl),collections.Counter(f[5] for f in fl))
over=[f for f in fl if f[4]>1.6+1e-9]
print('floors above 1.6 (no multiplier can explain):',len(over),'of',len(fl),f'= {len(over)/len(fl):.0%}',sorted(over,key=lambda f:-f[4])[:8])
mx=collections.defaultdict(dict)
for t,s,ref,pr,r,src in fl: mx[t][s]=max(mx[t].get(s,0),r)
bad=[]
for t in sorted(mx):
    sets=list(mx[t]); ok=any(all(perm[i]>=mx[t][s]-1e-9 for i,s in enumerate(sets)) for perm in itertools.permutations(MULTS,len(sets)))
    if not ok: bad.append(t)
    print(t,{s:round(v,2) for s,v in sorted(mx[t].items())},'feasible' if ok else 'INFEASIBLE')
print('teams with infeasible floors:',len(bad),'of',len(mx),bad)
# our own truth: t03 floors vs our real multipliers
print('t03 floors vs truth LAV1.6 SAL1.3 LAT1.1 MAL0.7:',{s:round(v,2) for s,v in mx.get('t03',{}).items()})
print('t03 floor violations:',[(f[2],f[3],round(f[4],2),f[5]) for f in fl if f[0]=='t03' and f[4]>{'LAV':1.6,'SAL':1.3,'LAT':1.1,'MAL':0.7,'RET':0.9,'CHA':0.5}[f[1]]+1e-9])
