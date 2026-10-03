# Venue roster and traffic over time from snapshots.jsonl ('venues' entries) + feed venue events.
import json
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
sn=[json.loads(l) for l in open(S+'/logs/feed/snapshots.jsonl')]
for s in sn:
    if s['what']=='venues':
        print('tick',s['tick'])
        for v in s['body']['venues']:
            print('  ',v['venue'],v['owner'],repr(v['name']),'mech',v['rules'].get('mechanism'),'fee',v['fee_bps'],v['fee_per_card'],'starter',v['starter'],'trades',v['trades'],'vol',v['volume'],'traders',v['traders'],'pairs',v['pairs'],'opened',v['opened_tick'],'status',v['status'],'pending',v['pending_fee'])
# last leaderboard: venue column + market score
lb=[s for s in sn if s['what']=='leaderboard'][-1]
print('leaderboard tick',lb['body']['tick'])
for t in lb['body']['teams']:
    print('  ',t['team'],'score',t['score'],'neg',t['negotiating'],'mkt',t['market'],'venue',t['venue'],'lvl',t['level'],'deals',t['deals'],'rank',t['rank'])
