# Exact feed coverage window: ticks present between 45 and 125.
import json, collections
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
c=collections.Counter(e['tick'] for e in ev if 45<=e['tick']<=125)
print(sorted(c.items()))
print('types ticks 110-118:',collections.Counter(e['type'] for e in ev if 110<=e['tick']<=118))
