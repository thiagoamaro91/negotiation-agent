# Feed coverage: events per 10-tick bucket, settlement-number gaps, rastro trade counter vs feed.
import json, collections
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
b=collections.defaultdict(collections.Counter)
for e in ev: b[e['tick']//10*10][e['type']]+=1
for k in sorted(b): print(k, sum(b[k].values()), {t:b[k][t] for t in ('offer.listed','offer.cancelled','settlement','thread.message')})
st=sorted(e['payload']['settlement'] for e in ev if e['type']=='settlement')
print('settlement numbers', st[0], st[-1], 'present', len(st), 'missing', st[-1]-st[0]+1-len(st))
# which settlement number ranges are missing
miss=[n for n in range(1,st[-1]+1) if n not in set(st)]
rng=[];s=None
for n in miss:
    if s is None: s=p=n
    elif n==p+1: p=n
    else: rng.append((s,p)); s=p=n
if s: rng.append((s,p))
print('missing ranges', rng)
ids=sorted(e['id'] for e in ev); print('feed id range',ids[0],ids[-1])
print('seen_at range by tick: ', [(e['tick'],e['seen_at']) for e in ev[::200]])
