# Latest schedule: when the next Market Test (bench) and venue trading start.
import json
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
ch=[json.loads(l) for l in open(S+'/logs/feed/changes.jsonl') if '"schedule"' in l]
last=ch[-1]; print('schedule seen at tick',last['tick'],'now_hours',last['body']['now_hours'])
for u in last['body']['upcoming'][:8]: print('  at_hours',round(u['at_hours'],2),u['action'],u['note'][:70],json.dumps(u.get('params'))[:120])
