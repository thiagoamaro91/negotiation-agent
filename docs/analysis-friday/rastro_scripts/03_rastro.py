# Main El Rastro analysis: team-to-team settlements joined to listings, 3-way count,
# TTL, cancellations, standing book at close, buyers, fee payer.
import json, collections, re, statistics as stt
S='/private/tmp/claude-501/-Users-thiago-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Claude-career-hackathon-madrid-2026/5087e5e9-260f-4d88-acb2-fb3eb898bdc9/scratchpad/snap'
BOOK={'common':10,'uncommon':25,'rare':70,'epic':180,'legendary':450}
ev=[json.loads(l) for l in open(S+'/logs/feed/feed.jsonl')]
listed=[e for e in ev if e['type']=='offer.listed']
canc=[e for e in ev if e['type']=='offer.cancelled']
st=[e['payload'] for e in ev if e['type']=='settlement']
T=re.compile(r'^t\d\d$')
# ---- 3-way count
a=[s for s in st if s['venue']=='rastro']
b=[s for s in st if all(T.match(p) for p in s['parties'])]
print('COUNT (a) venue==rastro:',len(a),' (b) both parties team ids:',len(b),' same set:',{x['settlement'] for x in a}=={x['settlement'] for x in b})
sn=[json.loads(l) for l in open(S+'/logs/feed/snapshots.jsonl')]
vc=[(s['tick'],v['trades'],v['volume']) for s in sn if s['what']=='venues' for v in s['body']['venues'] if v['venue']=='rastro']
print('(c) rastro venue counter (tick,trades,volume):',vc)
w=[x for x in a if 134<=x['tick']<=155]
print('feed rastro settlements ticks 134-155:',len(w),'volume',sum(x['price'] for x in w))
w2=[x for x in a if 47<=x['tick']<134]
print('feed rastro settlements ticks 47-133:',len(w2),'volume',sum(x['price'] for x in w2))
# ---- listing index by asset id
offers={}
for e in listed:
    o=e['payload']['offer']; offers[o['id']]=o
by_asset=collections.defaultdict(list)
for o in offers.values():
    for x in o['give']['assets']: by_asset[x['id']].append(o)
cancelled={e['payload']['offer']:e['tick'] for e in canc}
# ---- TTL
ttl=collections.Counter(o['expires_tick']-o['created_tick'] for o in offers.values())
print('TTL distribution (expires-created):',ttl.most_common())
# ---- listing kinds
kinds=collections.Counter(('sell' if o['give']['assets'] and o['want']['cash'] and not o['want']['assets'] and not o['want']['types'] else 'buy' if o['give']['cash'] and not o['give']['assets'] else 'swap/other') for o in offers.values())
print('listing kinds:',kinds)
print('listing makers:',collections.Counter(o['maker'] for o in offers.values()).most_common())
# ---- joined trade table
rows=[]
for s in sorted(a,key=lambda x:x['tick']):
    it=s['items'][0]; seller=it['frm']; buyer=it['to']
    cands=[o for o in by_asset.get(it['id'],[]) if o['maker']==seller and o['created_tick']<=s['tick']]
    bids=[o for o in offers.values() if o['maker']==buyer and ('card:'+it['ref']) in o['want']['types'] and o['created_tick']<=s['tick']]
    maker='seller' if cands else ('buyer(bid)' if bids else '?')
    if not cands: cands=bids
    lst=max(cands,key=lambda o:o['created_tick']) if cands else None
    first=min(cands,key=lambda o:o['created_tick']) if cands else None
    rows.append(dict(sn=s['settlement'],tick=s['tick'],ref=it['ref'],rar=it['rarity'],set=it['set'],seller=seller,buyer=buyer,price=s['price'],fee=s['fee'],
        book=BOOK[it['rarity']],list_ask=(lst['want']['cash'] or lst['give']['cash']) if lst else None,first_ask=(first['want']['cash'] or first['give']['cash']) if first else None,
        n_listings=len(cands),list_tick=lst['created_tick'] if lst else None,first_tick=first['created_tick'] if first else None,
        maker=maker))
print('\nTEAM TRADES (feed-visible)')
print('| settl | tick | card | rarity | seller | buyer | maker | price | fee | price/book | listed price | first price | listings | ticks listing->sale | ticks first listing->sale |')
for r in rows:
    print(f"| {r['sn']} | {r['tick']} | {r['ref']} | {r['rar']} | {r['seller']} | {r['buyer']} | {r['maker']} | {r['price']} | {r['fee']} | {r['price']/r['book']:.2f} | {r['list_ask']} | {r['first_ask']} | {r['n_listings']} | {r['tick']-r['list_tick'] if r['list_tick'] is not None else '?'} | {r['tick']-r['first_tick'] if r['first_tick'] is not None else '?'} |")
for rar in ('common','uncommon','rare'):
    p=[r['price'] for r in rows if r['rar']==rar]
    if p: print('rarity',rar,'n',len(p),'prices',sorted(p),'median',stt.median(p),'price/book median',round(stt.median(p)/BOOK[rar],2))
print('buyers:',collections.Counter(r['buyer'] for r in rows).most_common())
print('sellers:',collections.Counter(r['seller'] for r in rows).most_common())
print('buyer x set:',collections.Counter((r['buyer'],r['set'],r['rar']) for r in rows))
# fee rule check
print('fee == ceil(0.05*price+1)?', all(r['fee']==-(-(0.05*r['price']+1)//1) for r in rows), [(r['price'],r['fee']) for r in rows])
# ---- listings outcome (feed-visible): sold / cancelled / standing at 159 / unknown
book159=[s for s in sn if s['what']=='rastro' and s['tick']==159][0]['body']['offers']
open159={o['id'] for o in book159}
sold_assets={(r['ref'],r['seller']) for r in rows}
sold_offer_ids=set()
for r in rows:
    for o in by_asset.get(next(s['items'][0]['id'] for s in a if s['settlement']==r['sn']),[]):
        if o['maker']==r['seller'] and o['created_tick']==r['list_tick']: sold_offer_ids.add(o['id'])
outc=collections.Counter(); outc_r=collections.defaultdict(list)
for o in offers.values():
    if not o['give']['assets'] or not o['want']['cash'] or 'rarity' not in o['give']['assets'][0]: continue
    rar=o['give']['assets'][0]['rarity']; ask=o['want']['cash']
    if o['id'] in sold_offer_ids: k='sold'
    elif o['id'] in cancelled: k='cancelled'
    elif o['id'] in open159: k='open@159'
    elif o['expires_tick']<=159: k='expired_or_unseen'
    else: k='gone_unseen'
    outc[(k,rar)]+=1; outc_r[(k,rar)].append(ask/BOOK[rar])
print('\nSELL-LISTING OUTCOMES (feed-visible listings):')
for k in sorted(outc): 
    v=outc_r[k]; print(k,outc[k],'ask/book median',round(stt.median(v),2),'min',round(min(v),2),'max',round(max(v),2))
# cancelled: re-list behaviour (same asset relisted at lower price?)
rel=[]
for aid,os in by_asset.items():
    os=sorted(os,key=lambda o:o['created_tick'])
    for x,y in zip(os,os[1:]):
        if x['maker']==y['maker']: rel.append(y['want']['cash']-x['want']['cash'])
print('relist price changes (same asset same maker): n',len(rel),collections.Counter(rel).most_common(8))
# ---- standing book at Friday close (tick 159)
print('\nBOOK AT TICK 159: n offers',len(book159))
g=collections.defaultdict(list)
for o in book159:
    if o['give']['assets'] and o['want']['cash'] and not o['want']['assets'] and 'rarity' in o['give']['assets'][0]:
        x=o['give']['assets'][0]; g[(x['rarity'],x['set'])].append((o['want']['cash'],159-o['created_tick'],o['maker'],x['ref']))
    else: g[('non-sell','')].append((json.dumps(o['give'])[:80],json.dumps(o['want'])[:80],o['maker']))
for k in sorted(g): print(k,len(g[k]),sorted(g[k])[:30])
print('makers at 159:',collections.Counter(o['maker'] for o in book159).most_common())
json.dump(rows,open(S.replace('/snap','/out')+'/rastro_trades.json','w'),indent=1)
