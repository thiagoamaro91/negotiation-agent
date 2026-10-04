# Findings

What we have worked out from the public feed and our own deals. These are inferences from data, not published rules: each section says when it was observed. Re-check after a round change. The feed tools (`tools/feed_recorder.py`, `tools/feed_report.py`, data in `logs/feed/`) come with pull request #1.

## Abuela Carmen (level 1 dealer) — Friday 2 Oct, ticks 0–65

- **Welcome price on each team's first deal, no haggling**: pack 17, uncommon 17, common 7; she pays 13 when we sell to her.
- After the first deal: packs open at 30 and close at 19–24; uncommons open at 29 and close at 21–25; commons open at 12 and close at 9–10. She buys commons at 5–6 and uncommons at 13–16.
- Her first reply drops 3–4 P, then she mirrors our step. She gives a final offer after 5–6 replies and accepts ours once it is within 1–2 P of her ask.
- Raising by 2 P per round reached 21–22. Raising by 1 P ran out her patience and ended at 22–24. `agent/abuela.py` uses `STEP = 1` today; `STEP = 2` is worth a try.
- Limits: 8 deals per team per hour, 3 packs per team per hour. She gives some teams free cards.
- Unlocking the next level early needs about 3 **negotiated** deals; deals at her opening price do not count.

## Leaderboard — Friday 2 Oct, ticks 0–65

- The score is **relative** to the other teams: on dealer deals alone the leader was capped at 12.5.
- Packs bought at 21–24 added nothing. Named cards and sales to Abuela did. Accepting her final offer on a pack (t12 at 24) added nothing either.
- **Team-to-team trades move the score most.** One sale of a common for 12 P (tick 40) took t10 from 8.3 to 29.1 and the seller t06 from 12.5 to 18.4. At tick 65 the top three (t13 27.9, t10 24.1, t14 20.6) were the teams that had traded with other teams; we were 13th with 8.33.
- The only rare sold between teams so far went for 65 P (LAT-09, t13 to t14, tick 47).
- The exact ladder formula is still unknown. Record our score after every deal of our own.

## El Rastro (shared market)

- Fee: 5% plus 1 P per card, paid by the side that accepts.
- Commons listed at 10–12 P mostly stayed unsold on Friday.
- Listings expire after 40 ticks by default.

## Where we stand — tick 65

- Our set multipliers and holdings are in `logs/state/me.json`. Lavapiés is our best set (×1.6), Chamberí our worst (×0.5).
- For the Lavapiés page we are missing the two rares, LAV-09 and LAV-10, which Abuela does not sell. On Friday LAV-09 was held by t07 and LAV-10 by t05 and t08. Each is worth 112 to us.
- Our trade currency is LAT-10 (worth 77 to us). Surplus to sell: the Malasaña cards and the spare copies of LAV-01 and LAV-03.
- Nothing in this repo handles team-to-team trades yet: an offer addressed to us waits until someone accepts it by hand.

## What the public feed shows

Every team's structured offers to the dealers (item and price), the dealers' replies with their words, every settlement, El Rastro listings, gifts and announcements. Team words are not published.

## API quirks not in the rules

- `/api/feed` has no paging: `after` and `since` are ignored. Ask for `limit=1000` and dedupe by `id`.
- `/api/cards/{id}` needs a key, unlike the other public reads.
- Keyless reads: 60 per second per address. Keyed calls: 5 per second, burst 20.
- Per tick: 1 accept per team (shared by every agent on the key), 1 message per conversation, 12 new offers. At most 6 open conversations and 30 open offers. Text is capped at 1200 characters.
- On Friday the clock started late (about 20:20 instead of 19:00) and still closed at 23:00.

## Friday night, after close (tick 159)

The full Friday analysis is in [analysis-friday](analysis-friday/README.md). Added here, not covered there:

- **The VM recorder has no gap:** 3,770 events with every tick 0-159 and 191 settlements, where the laptop recorder lost ticks 49-118. Committed as `logs/feed-vm/` (feed, leaderboard and board snapshots, changes).
- **Every venue's book is public:** `GET /api/venues/{id}/offers` answers without a key, so we can record how every team's market behaves.
- **The kit says how to beat the free stall** (`kit/starter_broker.py`): the stall matches by quoted price; bench traders quote away from limits they keep hidden, some leave soon, most relax their quotes as their patience runs out, the firm ones never do; the Market Test counts the gains between the true limits. A broker match must still respect the quotes (`ask <= price`, `price + fee <= bid`).
- **Team venue fees move:** t13 went 1 % to 0 % (tick 136) and back to 1 % (tick 147); t06 0.5 % to 0 % (tick 156); t02 announced 0 % for tick 161.
- **The SDK repeats refused writes:** with `wait_on_tick=True` (the default) a write refused with `wait_for_tick` is sent again on the next tick. For `POST /api/duels/{id}/accept` that accepts whatever the rival's standing offer is by then. `duel.py` and `rastro_seller.py` pass `wait_on_tick=False`; `abuela.py` and `chato.py` use the default.
- **Game hours look like wall hours:** the schedule pins Saturday 4.0 to 09:00 and 18.0 to 23:00, Sunday 18.0 to 09:00 and 24.0 to 15:00. Fourteen game hours in fourteen wall hours at 30 s ticks (and six in six at 15 s) only fit if a game hour is a wall hour whatever the tick length. To confirm with `t_hours` at 09:00.

## Saturday, Duels I and midday (ticks ~440-630)

- **Selling to a dealer fills a ladder slot,** the same as buying from one (Chato sells at 14, Saturday morning).
- **Ladder value gate:** a dealer deal on the wrong side of our private value earns no ladder credit, however much of the dealer's range it captures (Friday data, [analysis-friday/score.md](analysis-friday/score.md) section 4a: LAT-06 at 28 against a value of 27.5 scored +0). Every dealer sell floor must sit above our value.
- **Market Test bench offers all carry maker `"bench"`** (tick ~442). A broker that drops same-maker pairs drops every bench pair: the 11:50 test scored efficiency 0.449 against the stall's ~0.9 for that reason (fixed in PR #22).
- **Duels need no cash:** Duels I ran with 95 P in hand, and bids are not escrowed.
- **Duels I (t03, to tick 630):** 31 finished, 25 deals, duel_points 16.24. All 21 of our accepts came with 1-3 ticks left; 5 of the 6 no-deals were rivals who never spoke, while our last offer stayed short of our limit. Summary on the bus (#5968797627).
- **The clock can pause mid-duel** (`/api/clock` `paused: true` at tick 630, ~13:25). `results/duel.lock` is refreshed per tick, so it goes stale during a pause while duels are still live. A dealer bot gated only on the lock would start inside the duel window: gate on `paused` and on unfinished duels too.

## Sunday 01:30, ladder value measured (ticks 160 to 1445)

Method and tables in [plans/ladder-sunday.md](plans/ladder-sunday.md). From the board and the 470 Saturday dealer settlements, single deals only (no duel result, no other event of that team in the 10-tick interval):

- **Board change after a deal in a team's first three with a dealer (an association, not verified credit):** Abuela about 1.2, Pilar 0.8, Pícaros 0.6, El Chato 0.3. **After the first three, later deals were followed by about 0** (median 0.00 to 0.07); a 4th only helps when it beats one of the first three.
- **Level 5 is unmeasured:** the three Ernesto sales (t08 tick 1083, t16 1110, t06 1226, epics at 116 to 120) moved +0.14, -5.54 and -2.45, all below what the card was worth to the seller.
- **A page completed by a dealer buy was not followed by a page-bonus-sized change** (-0.17 to +0.83, n=10); one completed by a team trade was (+1.6 to +4.7; our LAT-09 at 88: +3.10).
- **The ladder value gate is now enforced in code** (`agent/dealer_client.py`): buy limits are clipped to floor(book x our set multiplier), sell floors to the value of the copy given up, a `--cap` or `--floor` on the wrong side is refused, and every priced message and accept re-prices the card from a fresh `/api/me` read (other bots trade the same cards mid-thread).
- **`tools/value_inference.py teams` shows CHA as the least liked set of 14 of 18 teams because of an artifact:** t07 opened ten threads for CHA-06 at tick 1074 to 1077, so CHA entered the softmax before it was released. Elimination cannot name the CHA fans (its top pick is right 21 % against 17 % for chance); the first CHA buyers on Sunday can.

## Saturday evening: every team's cash (ticks 630-1243)

What `tools/ledger.py` needed to rebuild all 18 teams' cash from the public feed (PRs #42, #52, #53, #55):

- **The payday came only in words.** At tick 1201 the organisers' `announcement` said "Payday in Madrid: every team gets 400 primas", with no `schedule.fired` grant. Without it, five teams appear to buy epics and rares they could not afford (t05 paid Picaros 128 P for RET-11 at tick 1209). The ledger now reads it. Watch for the Sunday allowance arriving the same way.
- **Who paid the fee.** The feed has no "offer filled" event: a filled offer just leaves the board without an `offer.cancelled`. An offer accepted on its last tick settles on the next tick. With an ask and a bid both standing, the settled price says which one was taken (t16 sold LAT-09 into our 88 P bid at tick 724 while its own ask stood at 135, so the 6 P fee was t16's).
- **Card-for-card swaps on El Rastro carry a fee** (2 P each, 8 swaps by tick 1201), paid by the side that took the listing.
- **Counters to check against:** El Rastro's `/api/venues` totals restart each round. From tick 160 they equal the feed exactly (208 P of fees, 71 trades, 1,843 P of volume at tick 1060). Team venues had charged no fee by then.
- **How exact it is:** of 153 team settlements to tick 1201, only two fees stay unknown (tick 78, 3 P between t04 and t15; tick 939, 2 P between t14 and t16). The page shows them as ± on those teams' cash. Team 3's rebuilt cash matches every real `/api/me` reading up to tick 1186. The Mini's live score reader (`score.state.json`) stopped at tick 1186 (20:07).
- **The value inference misreads page-completion buying as taste.** On our own account (tick 961) it ranks La Latina first (1.44) and Lavapiés third (1.17), against a true 1.6 for Lavapiés, because we were buying the last cards of pages. Read other teams' labels with that in mind.

## Open questions for the organisers

- The judges' criteria (40 of the 100 points).
- Whether Friday's late start shifts the schedule.
- When level 2 opens (`/api/levels` was still empty at tick 65).
- Whether dealers' true limits are revealed after the Market Test.
- Whether the one-accept-per-tick limit also covers duel accepts.
- How the 30 negotiating points split between duels, the dealer ladder and team trades.

## Asset ids, decks, cash and our own inference — Saturday 3 Oct, ticks 630–1243

- **Every card copy is one asset id, minted in order.** Starter hands are blocks of 15 ids per team in join order (t01 1–15, t02 16–30, t03 31–45). A pack mints its cards as consecutive ids, and the `best` card that `pack.opened` shows is the last slot, so it places the whole block. Listings name the maker's assets and settlements move them. `tools/decks.py` rebuilds every team's deck this way. Checked against our own account at tick 630: 35 cards rebuilt vs 35 real, 32 copies placed by id, 0 wrong, 16/16 names right. Gifts, eggs and Workshop cards carry a name but no id, and the Workshop never says which three commons it burned.
- **`GET /api/cards/{id}` needs the team key** (401 without it). Any team with a key can census every deck, ours included (`tools/census.py`, #57). The Sunday top-up list comes from `python3 tools/decks.py moved --base <census>` (#58, #59).
- **The value inference, tested on the one team whose multipliers we know (ours).** From our own public moves it orders 70 % of set pairs right (a uniform prior gets 50 %), with a mean error of 0.20 per multiplier against 0.28 for the prior. It still ranks LAT first and LAV third, while the truth is LAV > SAL > LAT: completing La Latina opportunistically hides our real favourite. Treat every other team's inferred favourite as a hint (`/data` → `truth` on the brain).
- **Cash is public except where the feed is silent.** Rebuilt from the public feed, our cash matched every real reading we have (11 of 11, through tick 1186). Three traps:
  - Package trades with cash (cards + 38 P for LAV-10, tick 844) need the matching listing to tell which way the cash went.
  - The fee is paid by whoever accepts, and the feed does not say who that was. Settle it by the price: did the trade close at the ask or at the bid?
  - The 400 P "Payday in Madrid" at tick 1201 came only as an `announcement`, with no `schedule.fired` (#52).

  For other teams a few fees stay ambiguous (`cash_unsure`, ±2–3 P), and a private cash event would not show at all.
- **Gifts follow easter eggs too.** Abuela gave us SAL-03 at tick 1077, right after the "chulapa dorada" egg message.

## Sunday morning: the clock and the new wall times (ticks 1445-1720)

- **Sunday started 20 minutes late.** The clock stayed paused at tick 1445 after `day.opened` and ran from 09:20 (`clock.changed` paused false, 15 s ticks). Round 3 started at tick 1446 with `"reset": false`; the 150 P allowance fired as a `schedule.fired` grant at tick 1448 (not only in words, unlike Saturday's payday).
- **At 15 s ticks one game hour is one wall hour (240 ticks).** Measured from the VM recorder's `seen_at`: tick 1546 = 09:40, 1626 = 10:00, 1706 = 10:20 (40 ticks and 0.1667 h per 10 min). Game 14.65 (the hard Market Test) started at tick 1690, about 10:16.
- **Wall times from `/api/schedule` at tick 1720, if nothing else pauses:** Market Test (15.0) about 10:37; Duels III (15.367) about 10:59; Market Test (17.0) about 12:37; finale warning about 13:47; stalls close and the Grand Final at about 13:59; freeze warning about 14:53; **scores freeze about 14:59** (19.367); the Bazaar closes at 15:00. Only two Market Tests remain after the hard one, not four.
- **Hard Market Test (session 7 / b121, ticks 1690-1706):** 24 bench offers, every per-offer expiry equal to the session end (1706), as on Saturday. Our broker on `stall` matched 7 pairs, 178 P = 85 % of the revealed-limit best (209 P) and 100 % of the quote-respecting ceiling; the `ours` replay was identical.

## Duels III (server session 4, ticks ~1822-2074, read 12:02)

- **Complete 68/68**, `duels.finished` session 4 at tick 2074 (11:52). 55 deals (buyer 27/34, seller 28/34), our surplus 1475.4 P; duel_points went 0.0 (tick 1822) -> 27.94 (tick 2087): 0.411 per duel against the lab's 0.420.
- **`duel_points` restarts each round in `score.jsonl`:** it read 43.37 at tick 1445 (Round 2) and 0.0 at tick 1783 (Round 3), although `round.started` round 3 said `"reset": false`.
- **The Duels III field, refit from the final transcripts:** linear 36, fast 11, one-shot 11, absent 8, steady 2. No-deals: 8 rivals who never priced, 3 with no zone, 2 where a rival offer inside our limit came 9-11 ticks before the end and we did not take it (duels 11468, 11534: an early accept needs code, not params).
- **No dealer deals of ours during the wave** (ladder unchanged at 5/15 from tick 1809 to 2117).
- **The server slowed down around midday (tick ~2230-2290, 12:31-12:43).** Our broker logged 38 read timeouts in 12 minutes (26 on `GET /api/clock`, 12 on `GET /api/broker/book`), all single misses (`in_a_row` 1, once 2), against 1 timeout during the 10:37 test. The 12:37 Market Test (b156) still had a book row for every tick and lost no match (7 matches, 100 % of the quote-respecting ceiling), so the retry-next-tick handling held.

## Sunday final hours (bazaar-final-conductor, 4 Oct)

- Tick ~2100 (12:02): a correct flag on a Picaros bait-and-switch message (words name the card we asked for, the
  structured offer gives a different one) scored +10 neg_points at once. Only the first 3 flags of the day scored;
  7 further correct flags (ticks ~2190) were accepted (`flagged: true`) and scored 0.
- Tick ~2420 (13:19): a +50 capped team trade (RET-07 page closer at about 30 vs live value 82.1) moved the board about +1.27.
- tools/factory.py keepers match a running copy by command-line substring: any shell whose command line contains
  `agent/market_desk.py run` (a wait loop) blocks the desk relaunch ("another copy runs outside the factory").

## Grand Final and the close (ticks 2578-2816)

- **Grand Final (server session 5, finished tick 2692, 14:28):** 34/34 complete, 25 deals (buyer 13/17, seller 12/17), our surplus 657.3 P; duel_points 27.94 -> 40.19, 0.360 per duel against the lab's 0.420 and Duels III's 0.411. The delivery-day term cost us 79.2 P over the 25 deals (11 deals at day 10), where in Duels III it was worth +1.7 P. The Final field read linear 17, fast 7, tit-for-tat 3, one-shot 3, absent 3, steady 1.
- **The Bazaar closed at tick 2816 (t 19.3417, 15:00), before the schedule's 19.367 freeze.** The organisers' 14:55 announcement said "Scores freeze at 15:00". Final board read at tick 2802: t03 34.19, rank 4 (leader t05 37.73).
