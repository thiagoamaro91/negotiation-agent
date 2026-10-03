# Map book pseudonyms to team ids via shared offer ids; trace the competing LAV-08@30 listing and t14's LAV-07 bid.
import json, collections
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
offs={e['payload']['offer']['id']:e['payload']['offer'] for e in ev if e['type']=='offer.listed'}
sn=[json.loads(l) for l in open(S+'/logs/feed/snapshots.jsonl')]
mp=collections.defaultdict(collections.Counter)
for s in sn:
    if s['what']!='rastro': continue
    for o in s['body']['offers']:
        if o['id'] in offs: mp[o['maker']][offs[o['id']]['maker']]+=1
print({k:dict(v) for k,v in mp.items()})
for s in sn:
    if s['what']=='rastro' and 148<=s['tick']<=159:
        hit=[(o['id'],o['maker'],o['want']['cash']) for o in s['body']['offers'] for x in o['give']['assets'] if x.get('ref')=='LAV-08']
        print('tick',s['tick'],'LAV-08 on book',hit)
print('LAV-07 bid:',[(o['maker'],o['created_tick'],o['expires_tick'],o['give']['cash']) for o in offs.values() if 'card:LAV-07' in o['want']['types']])
print('rastro settlement ticks >=155:',[(e['tick'],e['payload']['items'][0]['ref'],e['payload']['price']) for e in ev if e['type']=='settlement' and e['payload']['venue']=='rastro' and e['tick']>=155])
