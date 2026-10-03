# Profile settlement / listing payload variants in the frozen feed.
import json, collections
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
st=[e for e in ev if e['type']=='settlement']
c=collections.Counter((e['payload'].get('kind'), e['payload'].get('venue'), e['payload'].get('persona') is not None) for e in st)
print('settlement (kind, venue, has_persona):', c)
print('settlement keys:', collections.Counter(tuple(sorted(e['payload'])) for e in st))
for e in st:
    p=e['payload']
    if p.get('persona') is None:
        print(json.dumps(p))
print('--- listed venues', collections.Counter(e['payload'].get('venue') for e in ev if e['type']=='offer.listed'))
print('--- cancelled venues', collections.Counter(e['payload'].get('venue') for e in ev if e['type']=='offer.cancelled'))
for t in ('venue.opened','venue.fee_announced','venue.fee_changed','venue.announcement','announcement','level.unlocked','schedule.fired','clock.changed'):
    for e in ev:
        if e['type']==t: print(e['tick'], t, json.dumps(e['payload'])[:300])
# thread.opened kinds
print('thread.opened kinds', collections.Counter((e['payload'].get('kind'), e['payload'].get('with') if e['payload'].get('kind')!='persona' else 'persona') for e in ev if e['type']=='thread.opened'))
