#!/usr/bin/env python3
"""Parse feed.jsonl dealer threads into one record per thread.

Output: out/dealers_scripts/threads.json (list of dicts).
Each record: thread, team, dealer, side (buy/sell), item_kind (card/pack), item,
rarity, set, book, opening (dealer first ask/bid), dealer_seq, team_seq,
events (ordered list of (tick, msg_id, sender, price, final)), final_offer,
deal_price, deal_tick, outcome (deal/walk/open/abandoned), rounds.
"""
import json, os, collections

S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(S, 'snap')
FEED = os.path.join(SNAP, 'logs/feed/feed.jsonl')
CAT = os.path.join(SNAP, 'branches/catalog.json')
OUT = os.path.join(S, 'out/dealers_scripts/threads.json')

DEALERS = {'abuela', 'chato'}

cat = json.load(open(CAT))
cards = {}
for st in cat['sets']:
    for c in st['cards']:
        cards[c['id']] = dict(set=st['id'], rarity=c['rarity'], book=c['book'])

events = [json.loads(l) for l in open(FEED)]
events.sort(key=lambda e: e['id'])

threads = {}
msgs = collections.defaultdict(list)
settlements = []
closed = {}
for e in events:
    p = e['payload'] if isinstance(e['payload'], dict) else {}
    if e['type'] == 'thread.opened' and p.get('kind') == 'persona':
        threads[p['thread']] = dict(thread=p['thread'], team=p['team'], dealer=p['with'],
                                    topic=p['topic'], open_tick=e['tick'], open_id=e['id'])
    elif e['type'] == 'thread.message' and p.get('kind') == 'persona':
        msgs[p['thread']].append((e['id'], e['tick'], p))
    elif e['type'] == 'settlement':
        settlements.append((e['id'], e['tick'], p))
    elif e['type'] == 'thread.closed':
        closed[p['thread']] = p.get('reason')

# threads seen only via messages (opened before recorder started?)
for tid, ml in msgs.items():
    if tid not in threads:
        p = ml[0][2]
        threads[tid] = dict(thread=tid, team=p['team'], dealer=p['with'], topic=None,
                            open_tick=ml[0][1], open_id=None, opened_missing=True)


def offer_price(o, sender_is_dealer, side):
    """Cash price of an offer (cash moving between team and dealer)."""
    g = o.get('give', {}).get('cash', 0) or 0
    w = o.get('want', {}).get('cash', 0) or 0
    return g if g else w


def item_of(o):
    ts = (o.get('give', {}).get('types') or []) + (o.get('want', {}).get('types') or [])
    a = (o.get('give', {}).get('assets') or []) + (o.get('want', {}).get('assets') or [])
    return ts, a


# index settlements by (team, dealer)
sett_by_pair = collections.defaultdict(list)
for sid, tick, p in settlements:
    parties = p.get('parties') or []
    d = p.get('persona')
    if d in DEALERS:
        team = [x for x in parties if x != d][0]
        sett_by_pair[(team, d)].append((sid, tick, p))

used_sett = set()
records = []
for tid in sorted(threads):
    t = threads[tid]
    if t['dealer'] not in DEALERS:
        continue
    topic = t.get('topic') or {}
    side = 'buy' if 'buy' in topic else ('sell' if 'sell' in topic else None)
    item_kind = item = None
    if side:
        tv = topic[side]
        if len(tv) == 1 and 'assets' not in tv:
            (item_kind, item), = tv.items()
        # else generic topic like {rarity, set}: infer item from offers below
    ml = sorted(msgs.get(tid, []), key=lambda x: x[0])
    seq = []
    for mid, tick, p in ml:
        o = p.get('offer')
        if not o:
            seq.append(dict(id=mid, tick=tick, sender=p['sender'], price=None, final=False,
                            text=p.get('text')))
            continue
        if item is None:
            ts, a = item_of(o)
            if ts or a:
                if ts:
                    k, v = ts[0].split(':', 1)
                else:
                    k, v = a[0].get('kind'), a[0].get('ref')
                item_kind, item = k, v
                # infer side: dealer gives card -> team buys
                gi = (o.get('give', {}).get('types') or []) + (o.get('give', {}).get('assets') or [])
                wi = (o.get('want', {}).get('types') or []) + (o.get('want', {}).get('assets') or [])
                if p['sender'] in DEALERS:
                    side = 'buy' if gi else 'sell'
                else:
                    side = 'buy' if wi else 'sell'
        seq.append(dict(id=mid, tick=tick, sender=p['sender'], price=offer_price(o, p['sender'] in DEALERS, side),
                        final=bool(o.get('final')), offer_id=o.get('id'), text=p.get('text')))
    rec = dict(thread=tid, team=t['team'], dealer=t['dealer'], side=side, item_kind=item_kind, item=item,
               open_tick=t['open_tick'], opened_missing=t.get('opened_missing', False),
               closed_reason=closed.get(tid))
    if item_kind == 'card' and item in cards:
        rec.update(cards[item])
    elif item_kind == 'pack':
        rec.update(set=None, rarity='pack:' + item, book=None)
    d_prices = [m for m in seq if m['sender'] in DEALERS and m['price'] is not None]
    t_prices = [m for m in seq if m['sender'] not in DEALERS and m['price'] is not None]
    rec['dealer_seq'] = [m['price'] for m in d_prices]
    rec['team_seq'] = [m['price'] for m in t_prices]
    rec['events'] = [(m['tick'], m['id'], 'D' if m['sender'] in DEALERS else 'T', m['price'], m['final']) for m in seq]
    rec['dealer_texts'] = [m['text'] for m in seq if m['sender'] in DEALERS]
    rec['opening'] = d_prices[0]['price'] if d_prices else None
    rec['first_sender'] = seq[0]['sender'] if seq else None
    rec['final_offer'] = next((m['price'] for m in d_prices if m['final']), None)
    rec['final_tick'] = next((m['tick'] for m in d_prices if m['final']), None)
    # match settlement: same team/dealer, item ref equals, tick >= first msg tick, within thread lifetime
    first_tick = seq[0]['tick'] if seq else t['open_tick']
    last_tick = seq[-1]['tick'] if seq else t['open_tick']
    deal = None
    for sid, tick, p in sett_by_pair.get((t['team'], t['dealer']), []):
        if sid in used_sett:
            continue
        refs = [it.get('ref') for it in p.get('items', [])]
        if item in refs and first_tick <= tick <= last_tick + 3:
            deal = (sid, tick, p)
            break
    if deal:
        used_sett.add(deal[0])
        rec['deal_price'] = deal[2].get('price')
        rec['deal_tick'] = deal[1]
        rec['deal_items'] = [(it.get('ref'), it.get('frm'), it.get('to')) for it in deal[2]['items']]
        rec['outcome'] = 'deal'
        # who closed: equal to final offer, to a dealer ask, or a team bid?
        dp = rec['deal_price']
        if rec['final_offer'] is not None and dp == rec['final_offer']:
            rec['closed_on'] = 'dealer_final'
        elif dp in rec['dealer_seq'] and (not rec['team_seq'] or dp != rec['team_seq'][-1]):
            rec['closed_on'] = 'dealer_ask'
        elif rec['team_seq'] and dp == rec['team_seq'][-1]:
            rec['closed_on'] = 'team_bid_accepted'
        else:
            rec['closed_on'] = 'other'
    else:
        rec['deal_price'] = None
        if rec['final_offer'] is not None:
            rec['outcome'] = 'walk_after_final'
        elif not seq:
            rec['outcome'] = 'empty'
        else:
            rec['outcome'] = 'no_deal'
    # rounds = number of team priced messages up to the deal (or all)
    rec['n_team_bids'] = len(t_prices)
    rec['n_dealer_msgs'] = len(d_prices)
    rec['welcome'] = (len(d_prices) == 1 and len(t_prices) == 0 and rec['outcome'] == 'deal')
    records.append(rec)

unmatched = [(sid, tick, p) for k, v in sett_by_pair.items() for (sid, tick, p) in v if sid not in used_sett]
json.dump(records, open(OUT, 'w'), indent=1)
print('threads', len(records), 'deals', sum(r['outcome'] == 'deal' for r in records))
print('dealer settlements total', sum(len(v) for v in sett_by_pair.values()), 'unmatched', len(unmatched))
for sid, tick, p in unmatched[:20]:
    print('  UNMATCHED', sid, tick, p.get('parties'), p.get('price'), [(i.get('ref'), i.get('frm'), i.get('to')) for i in p['items']])
print('threads w/o thread.opened in feed:', sum(r['opened_missing'] for r in records))
print('non-dealer settlements:', sum(1 for s in settlements if s[2].get('persona') not in DEALERS))
