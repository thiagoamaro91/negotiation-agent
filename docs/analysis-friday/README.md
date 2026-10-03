# Friday log analysis: what changes for Saturday

Built 2026-10-03 ~01:50 from every log of Friday night: our dealer runs (Abuela 49 events, Chato 50), 10 server-side threads, 18 practice duels, the public feed (2,103 events: 157 dealer threads across all 18 teams, 206 duels, 340 El Rastro listings, 105 settlements), 68 leaderboard snapshots, our score history (repo plus the Mac Mini dashboard), and Jay's and Héctor's branch models. Four analysts each owned one Saturday decision. They all worked from one frozen snapshot and recomputed every number with a script. Full working and scripts: `projects/negotiation-agent/docs/analysis-friday/`. MEASURED = counted in the logs. INFERENCE = our reading of them.

**First move at 09:00:** read `GET /api/schedule` to see whether the clock resumed or jumped, then relist the spares at the prices in section 1. Our Friday listings expire around 09:07 (30 s ticks) or 09:15 (60 s ticks) if the clock resumes, and are already dead if it jumps.

## The five changes that matter most

1. **Duels: accept, don't argue.** We closed 0 of 12 practice duels. In all 8 where the rival named a price, its last offer was already inside our limit: we left on average 32% of our limit on the table. The field closed 47% (96/206). Saturday rule: stay silent while the rival improves, then accept any offer inside our limit in the last 3 ticks. (MEASURED) `agent/duel.py` was drafted after practice, and no duel run log exists for Friday, so the 0/12 came from manual play. The bot already listens silently and accepts inside our limit at the end. What's left is tuning: ACCEPT_ANY_TICKS 2 to 3, the early-accept trigger, the anchor clamp (section 5), and no other agent accepting in a duel wave's last ticks.
2. **Market-making is half the game points, Saturday runs eight Market Tests, and nobody has scored any yet.** Market is 0.00 for all 18 teams, because Friday's first Market Test (hour 3.0) never ran. Saturday's schedule has Market Tests at hours 5, 7, 9, 11, 13, 15, 16 (the "hard" one, 12 traders) and 17. The top two teams already opened venues with 0-1% fees. Our free auto stall earns at most half of each test's points. The bond is refundable (RULES line 70: the 250 comes back after a cooldown when we close), so a venue really costs 20 P, plus 250 parked. Decide on our own venue plus broker right after the grant. (Zero and schedule MEASURED, value INFERENCE)
3. **A spare copy is worth 25% of a first copy to the scorer.** The catalog's `copy_marginals` is [1.0, 0.25, 0.1]. Our LAV-08 spare is worth 10, the MAL-06 spare 4.4, the LAV commons 4. So any spare sale above that is surplus: our MAL-08 sale at 28 scored +23.6 neg_points (28 - 4.4), about +2.9 score. Relist cheaper, and never buy a duplicate. (MEASURED)
4. **El Chato LAV rare after the grant: land it at 82-84, which is a ladder question, not a cash one.** The ladder scores the share of the dealer's price range we capture (best 3 deals per level, higher levels weigh more), and two of our three Chato slots earned zero. Against his 97 opening and ~82 floor, a close at 82-84 captures nearly all of the range, while a close at 93 captures about a quarter. All 7 Chato rares in the field sold for 82-93, never below 82. Bid 60, 64, 68, 72, 76, 78, 80, 82, 84, never in 1 P steps; taking his final up to 93 is the fallback. (Price range MEASURED, bid path and share math INFERENCE)
5. **Buying from other teams scores like selling, but only below our value.** Team-trade surplus is our value minus price minus fee, the mirror of a sale. The biggest jumps on Friday came with team buys (t10 +20.81 for one LAV-02 at 12 P), but they landed early (tick 40), while the normalisers were tiny, and share intervals with dealer deals. The closing book held only one buy worth taking (SAL-05 at 9, +2 P). So: watch for underpriced listings on cards we lack, especially the LAV rares that would complete our first page; no bot needed yet. (MEASURED, confounded)

## Saturday clock

**Update 02:45 (feed + team memo):** Friday actually ran at 60 s ticks (`clock.changed` at 20:41), so one game hour was one wall hour. The organisers' wall plan, as the team memo lists it: 09:00 open + grant; Market Tests at 10:00, 12:00, 14:00, 16:00, 18:00, 20:00 and 22:00, plus the hard one at 21:00; Duels I 11:30; Duels II 18:00; close 23:00. Sunday: 09:00 open + 150 P, Duels III 11:00, Grand Final 14:00 (dealers close), scores freeze 15:00. That plan is exactly the schedule's game hours with hour 4.0 = 09:00 and 60 s ticks (case C). Our Friday listings would then expire around 09:15. The schedule's `tick_seconds: 30` for Saturday would halve every gap (cases A/B below). At 09:00, read `tick_seconds` in `/api/clock` and `now_hours` in `/api/schedule`.

Two cases if the 30 s tick holds, so read `GET /api/schedule` at 09:00 and see which one is live. Saturday ticks are 30 s, so 60 ticks or 30 wall minutes per game hour. Friday closed at 23:00 wall with the clock at hour 2.65 (tick 159), but the organisers' schedule has Saturday opening at hour 4.0 (`day_opens at_hours 4.0, wall 09:00`). So they may jump the clock at the open (case B) instead of resuming it (case A). Both are INFERENCE.

| game hour | event | case A: resumes at 2.65 | case B: jumps to 4.0 | our move |
|---|---|---|---|---|
| open | doors open | 09:00 | 09:00 | relist the spares at once (section 1), in both cases |
| tick 174-175 | our Friday El Rastro listings expire | ~09:07 | already dead at the open (tick jumps to 240) | |
| 3.0 | Market Test #1 (10 traders, 16 ticks) | ~09:10 | skipped, or fired as a catch-up | the free auto stall runs it for us (no venue; cash 233 < 270) |
| 4.0 | Round 2 "Saturday · Gran Vía" starts (weight 1, twice Friday's 0.5), El Retiro set released | ~09:40 | 09:00 | |
| 4.05 | grant: +150 P and a neighbourhood pack each | ~09:42 | ~09:01 | Chato rare (section 3), venue decision (section 4) |
| 5.0 | Market Test #2 | ~10:10 | ~09:30 | own venue + broker, if chosen |
| 6.5 | Duels I (price only, 16 ticks, decay 0.06, max 3 at once) | ~10:55 | ~10:15 | duel bot with the section 5 settings |
| 7, 9, 11 | Market Tests | | | venue running |
| 13.0 | Duels II (price + days, 2 rounds, 16 ticks, decay 0.08, max 6) and a Market Test | | | two-issue duel logic needed |
| 15, 16, 17 | Market Tests (16 = "The hard Market Test", 12 traders) | | | |

In case B the venue decision and the duel bot must be ready about 40 minutes earlier: by 09:30 and 10:15.

## 1. El Rastro at 09:00: relist the spares cheaper

List them rather than accepting bids: the side that accepts pays the fee, ceil(5% x price + 1).

| card | value to us (first copy / this spare) | listed now | start | then | floor |
|---|---|---|---|---|---|
| LAV-08 | 40 / 10 | 40 | 26 | 24 | 22 |
| MAL-06 | 17.5 / 4.4 | 28 | 28 | 24 | 20 |
| LAV-01 | 16 / 4 | not listed | 9 | | 6 |
| LAV-03 | 16 / 4 | not listed | 7 | | 6 |
| LAV-05 | 16 / 4 | not listed | 8 | | 6 |
| MAL-06 (2nd copy, after the spare sells) and MAL-08 (our last copy) | 17.5 each (first copies) | not listed | 28 | 24 | 21 |

Selling MAL first copies (added 02:30 from Héctor's brain): MAL is our lowest album multiplier (x0.7) and its page is nobody's target, so any sale above 17.5 is surplus at our private values (MAL-08 at 24 = +6.5). The MAL commons MAL-01/02 (worth 7) barely pay: the market asks 9 for them.

Evidence (MEASURED unless marked):
- LAV-08 at 40 sat unsold for 14 ticks with zero bids, and t06's LAV-08 at 30 also went unsold over ticks 149-158, so start at 26, not 36 (revised 02:45; Héctor's brain lists it straight at 24). The team memo's point decides it: Abuela sells LAV uncommons at a negotiated 21-25, with a per-team hourly allotment (RULES lines 42, 48), so a team pays more than that only to skip the haggle or when its allotment is used up. A three-step ladder costs about 6 minutes at 30 s ticks. After the fee, a buyer with LAV x1.6 gains at most about 37, so 40 needs a team completing its page. Likely LAV buyers: t14 (bid 55 for LAV-07), t05, t07 (INFERENCE from price over book).
- MAL-06: t17 paid 28 for our MAL-08. Skip 25: that step reaches no new buyer tier, and t17's MAL-07 listed at 25 competes. Likely buyers: t12, t17.
- Commons clear at 5-12, median 8 (n=5). Abuela pays 5-6 for commons as a fallback.
- Every repriced sale cleared below its first ask (99 to 65, 84 to 60, 12 to 8, 8 to 5), with a median of 4 ticks from the last relist to the sale.
- In the visible window only 1 of 24 uncommon asks sold on the ask; 2 of the 3 uncommon sales were sellers hitting buyer bids. There were zero team-to-team negotiation threads on Friday.
- Friday's two OPEN items: lower LAV-08's start, YES (to 26); lower the commons floor to 6-7, YES (6).

## 2. Buying on El Rastro: watch and pounce

What we are missing (album at tick 146; LAV 8/10, SAL 4/10, LAT 5/10, MAL 4/10):
- LAV-09, LAV-10: rares, 112 each to us.
- SAL-01, 02, 04, 05: commons, 13. SAL-09, 10: rares, 91.
- LAT-02, 03, 05: commons, 11. LAT-08: uncommon, 27.5. LAT-09: rare, 77.
- MAL-03, 04, 05: commons, 7. MAL-07: uncommon, 17.5. MAL-09, 10: rares, 49.
- El Retiro (x0.9) arrives at hour 4.0.

Rule: take a sell listing for a card we do NOT own when price + fee comes in at least about 2-3 P under our value. Examples: a SAL common at 8-9 or less, a LAT common at 7 or less, LAT-08 at 22 or less, a LAV rare at 100 or less. Spread the buys across sellers, because the UI mentions per-trade and per-partner caps on trade surplus (their size is unknown). Never buy a card we already hold: it arrives worth 25%.

The closing book (tick 159, 41 sell offers; surplus = our value - ask - fee) had only one clear buy: SAL-05 at 9 (+2). Héctor's tape adds SAL-04 at 9 from t07 (+2). Next best: LAT-05 at 8 (+1) and three at 0 (LAT-05 at 9 twice). Everything else on cards we lack was negative: SAL-02 at 12, LAT-02/03/05 at 10, LAT-08 at 30, all MAL listings. So this is a watch-and-pounce lever, not a bot to build tonight.

Evidence: team buys came before the largest jumps (t10 +20.81, t05 +7.79, t15 +4.73), but those landed early, while the normalisers were small, and share intervals with dealer deals. Surplus is worth about 0.155 score per P at Friday's normaliser (our sale: +23.6 P gave +2.88). All of the top five teams have completed an album page; we have none. INFERENCE: completing LAV with LAV-09/10 may add the 25% page bonus, which would explain why t14 and t05 bid above 1.6x book. Caveat: the feed outage hides 36-38 of about 46 team trades, so this lever's ranking rests on 7 buys. If it becomes a bot: `rastro_seller.py` has the listing side, and Héctor's PR #3 market brain may already cover the buy-side valuation.

## 3. Dealers after the grant

**El Chato, rare** (field: 7 deals, min/median/max 82/91/93; he opens at 97):
- Bid 60, 64, 68, 72, 76, 78, 80, 82, 84. The target is a close at 82-84, which fills a zero-credit L2 ladder slot at nearly the full share of his range; his final up to 93 for LAV (worth 112) is the fallback. Buy a SAL rare (worth 91) only at 84 or less.
- Héctor's brain prices this buy at 73 (it assumes dealers close at 95% of list). The field never saw a Chato rare under 82, so plan cash for 82-93.
- Why: t04 got 82 by opening at about 47% of his ask and climbing in +2 steps (thread 243). +4 steps pulled his ask from 97 to 82 in 7 messages (thread 298, cut off by the feed end). The 93 deals came from +1 steps or from taking his ask. He drops by no more than our last step (exceeded 1 of 48 times).
- LAV-10 sold to three different teams, so his stock looks per team (INFERENCE).
- Use this buy as the ladder test: read ladder_points before and after. If it rises, the "price below our value" gate holds.

**El Chato, uncommon:** finals 28-32 and nobody went below 28 (n=6); his price is set by his patience (he holds 33 for 3 messages). We already own every LAV and SAL uncommon, and LAT-08 (worth 27.5) can never clear a 28 final, so: no Chato uncommons.

**Abuela:** her Friday ladder slots are full (best 3 per level; our 5th deal added +0.000). If the best-3 resets on Saturday (likely, given that each day is a round; ask the desk), we need 3 fresh Abuela deals at a high share of her range: missing first copies such as SAL-01/02/04/05, closed at her floor (8 for commons), not at the 10 the brain plans. If we do buy, faster steps beat our crawl: t06 (11, 15, 17, 20, 21) and t13 (11, 13, 15, 19, 20, 21) both closed uncommons at 21, while our +1 crawls drew 22-25. Her first drop is a fixed 3-5 P whatever we open at, and after that she mirrors our step size. Caps: common 10, uncommon 23, pack 21 (the field's lowest pack was 19).

**Selling to dealers** pays at private values only for CHA cards (Abuela pays 13-16 for uncommons). But RULES line 118 scores the ladder on the share of the dealer's range we capture, for buys AND sells. So a spare sold to a dealer at the top of its buy range may fill a ladder slot (INFERENCE; test it with one LAV common spare to Abuela if Saturday's slots reset). Dealer stock is per team per hour (RULES lines 42, 48; the team memo lists Abuela at 3/hour and Chato at 2/hour). Level 2 unlock = 3 Abuela deals (`why: "3 deals with abuela"`, MEASURED).

## 4. Market Test and our own venue

- Saturday's schedule has eight Market Tests: hours 5, 7, 9, 11, 13, 15, 16 ("The hard Market Test", 12 traders) and 17, each with 10 synthetic traders over 16 ticks, plus whatever hour 3.0 does at the open. Market-making is 30 of the 60 game points, and Saturday weighs twice Friday.
- Four team venues opened Friday: t06 (board, 0.5% then 0%), t12 (board, 0%), t13 (board, 1%), t02 (auto, 0%). All four had 0 trades, because venue trading and the first Market Test start at hour 3.0 and Friday never got there. So there is no demand data yet.
- Our cash is 233, under the 270 needed (bond 250 + 20), until the grant at 4.05. About 37 P of spare sales would get us there sooner.
- Every team without a venue gets the free auto stall from hour 3.0. It earns at most half the Market Test points, with no bond. Our own venue only pays off with a board-type broker that matches better than the stall's midpoint.
- Owner decision right after the grant: open a board venue before the hour-5.0 test, yes or no. It depends on whether a broker is ready; Héctor's `market_plan.py` (PR #3) is the nearest candidate. With eight tests on Saturday, a broker that starts at hour 7 still catches seven of them.

## 5. Duels I settings (price only, 16 ticks per duel, decay 0.06, up to 3 at once; confirmed in the schedule)

**Mirror hypothesis: KILLED** in its "the rival's price reveals our limit" form: the rival's first price equalled our limit in 1/12 duels, its final price in 0/12. A looser version holds. Duels come in pairs (ids N and N+1, same item, roles swapped, same rival team), and the rival's final price landed within +-7% of our limit in the paired duel in 6 of 8. The rules digest says limits get "a secret scale and shift per duel", which predicts exactly that. So use the paired limit as a soft estimate of the rival's limit, never as a cap. Leave `--mirror` off.

| setting | value | basis |
|---|---|---|
| default stance | silent while the rival moves toward us | MEASURED: rival talk and waiting cost 0 rounds; rival offers improved to the end in 8/8, with the best offer at deadline-1 in 6/8 |
| speak only when | the rival is silent or has not moved for 3+ ticks | MEASURED: each of our messages after a rival message cost a round (5/5) |
| accept window | in the last 3 ticks, accept any offer strictly inside our limit (at least 1 P surplus), most urgent duel first | INFERENCE |
| early accept | before the window, when the rival's surplus is at least 0.85 x (paired limit - our limit) and that gap is above 2 P | INFERENCE |
| max messages | 2 per duel | INFERENCE |
| opening anchor (only if we must speak) | seller: min(1.55 x limit, 0.93 x paired limit). Buyer: max(limit / 1.55, 1.07 x paired limit). Clamp inside our limit | INFERENCE: 1.55 overshot the likely rival limit in 5/9 pairs |
| absent rival (4/12 on Friday) | one early offer at our limit + 0.5 x (paired limit - our limit) | INFERENCE; opening to a silent rival cost 0 rounds (2/2) |
| walk | never accept outside our limit; no messages in the last 3 ticks except one final offer at deadline-2 to a stuck rival | rules |

**Accept-slot collision:** RULES.md line 109 says "per tick your team may accept one offer", and up to 3 duels can share a deadline. So no other agent on our key (Abuela, Chato, the El Rastro seller) should accept anything in a duel wave's last 3 ticks. Whether duel accepts count toward that limit is unconfirmed: ask the desk.

**Rival bots:** the names (Oro, Luna, Rojo, Sol) do not map to behaviour; behaviour clusters by rival team. The types seen: steady conceder, fast conceder, cycler, one-shot, an LLM that waits for our concession, and absent. Practice duels did not score (duel_points 0.0 everywhere).

## 6. How the score works (what Friday taught us)

- **Normalisation is top-3** (CONFIRMED): each component is scaled to the mean of the top three teams, then capped. t06 stayed pinned at 12.50 while other teams moved.
- **Friday points carry over** (RULES text; the data cannot test it until Saturday): rounds are averaged, with Friday weighted 0.5 and Saturday 1, so Saturday counts twice as much.
- **neg_points** is the raw P of surplus from team trades, valued at our private values with duplicates at 25%. This reproduces collection_value 544.2 exactly, and the MAL-08 sale decodes as 28 - 4.375 = +23.625 (observed +23.6). The early -4.9 is unexplained: it appeared between ticks 94 and 146 with no team trade. Desk question.
- **Ladder:** best 3 deals per level; Abuela capped at 0.062 after 3-4 deals. The value gate is PARTIAL: SAL-08 at 29 (worth 32.5) moved us from 11.45 to 12.50, while LAT-06 at 28 (worth 27.5) left us flat. Confound: SAL-08 was also our first level-2 deal.
- **Timing:** on the live board, early events look bigger while the normalisers are small: first dealer deals at ticks 25-30 showed +3 to +5, and after tick 130 a deal showed +1 or 0. But RULES line 125 says a round counts in full once its day is over, so the final round score covers the whole day. Moving early only changes the live board, not the final score (corrected 02:30).
- **Cash has no end value:** cash is not a score term, so anything unspent at the Sunday 15:00 freeze is worth nothing. The venue bond comes back when we close the venue.
- **Rounds and the ladder:** each day is a round and rounds are averaged, which leans toward the best-3 ladder slots resetting on Saturday (INFERENCE, ask the desk). If they reset, Saturday needs 3 Abuela + 3 Chato deals at a high share of each range.
- **Drift:** idle teams drift down about 0.22 per refresh, so any move under about 1.3 is noise.
- **Top teams vs us:** they had 5 deals each by tick 45 (we had 1) and 15-24 by the close (we had 9). All of the top five have a complete page, and the top two opened venues.

## 7. Teammates' models

- **Jay's Abuela memory** (`memory-system` branch). Holds: the 17/7 welcome prices, her 29/30/12 openings, the pack low of 19, selling commons at 5-6, and the unlock at 3 deals. Fails: "lowest uncommon is 22" (two deals closed at 21) and "commons final at 9" (one closed at 8, and 7 of 17 at 8-9). His pack ceiling of 22 is too high; aim for 19.
- **Héctor's value_inference** (PR #3): 146 of 148 price floors fit some valid multiplier ordering, but that is a consistency check (nothing contradicts it), not an accuracy check. The accuracy number is the brain's own scorecard in section 10: 0.416 hit rate against 0.396 for the naive guess. The two outliers (t14's LAV-07 bid of 55, t05's LAV-09 bid of 125) fit if page completion is driving them.

## 8. Ops fixes before 09:00

- The feed recorder lost ticks 49-118 to DNS errors on the laptop: 168 of 273 settlements and every leaderboard refresh between ticks 48 and 134 are missing. Move it to the Mac Mini, whose dashboard history did cover ticks 75-159, and add retry plus backfill.
- `logs/state/me.json` is from tick 146 (before the MAL-08 sale); refresh it with `tools/snapshot.py` at 09:00.

## 9. Questions for the organisers' desk

1. Where does a negative team-trade value (-4.9 neg_points) come from before any team trade?
2. Ladder: are the best-3 slots per day or cumulative? Does credit need a price below our private value, or does only the first deal per level count?
3. How big are the per-trade and per-counterparty caps on team-trade surplus?
4. When do Saturday's Market Tests fire given Friday's late clock, and when do venues and the free stall go live?
5. Does a duel accept count toward the one-accept-per-tick team limit? Does an accept at deadline-1 settle in time?

## 10. Héctor's brain (tick-159 data, read 02:20) vs this analysis

Source: Héctor's live brain page (`/data` and `/history` JSON). It runs value inference, a team ledger and a timed buy/sell plan.

**Where it is right and adds something:**
- **Complete event store.** Its per-team trade counts sum to 92 = 2 x 46, matching El Rastro's own trade counter, so it holds the 36-38 trades our recorder lost. Its `/stream` replays no backlog, so ask Héctor for the store file. That would firm up lever 5 (7 buys today) and the uncommon clearing price (n=3).
- **Ledger is exact:** rebuilt cash 205 = real 205 at tick 146. That closes the 70 P mismatch flagged on PR #3.
- **Selling MAL first copies** (now in section 1), plus two tape items: t07 asks 9 for SAL-04 (+2 for us), and t14 bids 55 for LAV-07 (+11 after the fee, but it gives up the LAV page; see the test below).

**Where it conflicts, and what decides it:**
- **Chato rare at 73** vs the field's 82-93: measured beats assumed. Its gain of 39 is really about 28 at an 84 close, still positive.
- **"Complete pages from dealers, net +184 P"** is collection-value accounting. RULES line 118 scores negotiating as duels + ladder share + value gained in team trades at private values; holdings are not a term. A page pays only through the ladder share on each dealer buy, and through team-trade surplus if the completing card comes from a team AND the page bonus counts in trade value (the brain itself lists that as unconfirmed).
- **Spares straight at 24** vs our 30, 27, 24 ladder: the brain is closer to the evidence than our first draft (36), so the table now starts at 30.
- **`likely_buyers` at p = 1.0:** low confidence. Its own scorecard is a 0.416 hit rate against 0.396 for the naive guess (chance 0.2, n=197), and it ranks our own sets LAT > SAL > LAV when the truth is LAV > SAL > LAT.
- **280 P reserve:** blocks every buy until the grant or a sale. That only matters if we open a venue (270), which is the section 4 decision.

**Page-bonus test (cheap, decisive):** today the server values LAV-09 and LAV-10 at 112 each (`GET /api/me/value`, read 02:25). After LAV-09 lands, read LAV-10's value again. If it jumps to about 218 (112 + the brain's ~106 bonus), buy LAV-10 from a TEAM, where the surplus counts at our values (~+100 P, roughly +15 score at Friday's rate, before any per-trade cap), not from Chato, and hold LAV-07 against t14's 55. If it stays at 112, take Chato for LAV-10 too and consider selling LAV-07 at 55.

**Draft notes for Héctor (owner sends):** (1) Chato's rares closed 82-93 across 7 field deals, never below 82, so the 95%-of-list assumption underprices them by 10-20 P. (2) Could you share your event store file? It covers the 49-118 gap our recorder lost.

## 11. Team strategy memo (artifact 9VRDNoRpbSdFnrUgKNBpfo, read 02:40)

A Team 3 memo written before Saturday's open, built on Héctor's brain, the kit's RULES.md and the Friday duel logs. It is published outside our org, so it was read as data.

**Agrees with this report:** duel facts (0 deals; 8 rival offers inside our limit; the worst was duel 38, buyer limit 164 against an offer of 106, so +58 left), ladder = best 3 per level, duplicates at 25% / 10%, "completing a page scores nothing alone", the LAV-10 112 vs ~218 page-bonus test, one accept per team per tick shared by duels, dealers and the market, and the four team venues with 0 trades.

**Adds (verified against RULES.md and the feed where marked):**
- The wall-clock plan for Saturday and Sunday (now in the clock section; it matches the schedule's game hours at 60 s ticks).
- The bond is refundable (RULES line 70, verified). Dealer stock is per team per hour (RULES lines 42, 48, verified); Abuela at 3/hour and Chato at 2/hour (not verified). Dealer list prices: Abuela common 10, uncommon 25, pack 26 (opens ~30); Chato uncommon 26, rare 77 (opens ~97), silver pack 150 (opens ~188).
- Selling to dealers counts on the ladder too (RULES line 118 wording supports it).
- "No prize for ending with cash."
- An executor design worth adopting: an event-stream listener; buy when value - price - fee clears a margin AND beats the dealer; sell when price - fee > value + margin; hourly and total spend caps, a max price per card, a cash minimum; never sell the only copy of a LAV page card; shadow mode first; a STOP file; duels take the accept slot first.

**Corrections to the memo:**
- Its model's "~45% vs 20% chance" leaves out the naive baseline (39.6%); the gain over naive is about 2 points.
- Its LAV-09/10 buys are gated on the page bonus. The ladder case for one Chato rare at 82-84 (section 3) stands on its own.
- Its venue decision waits for the first Market Test at 10:00. With the bond refundable, opening before 10:00 only risks 20 P, if a broker is ready.

## Data caveats

- Feed outage at ticks 49-118: all counts for other teams cover ticks 0-48 and 119-159 only.
- The Chato data comes from the 14 teams that unlocked him early (he opened to everyone at tick 158).
- The duel stats come from practice. Saturday's scored rivals may behave differently: 4 of 18 practice rivals never showed up.
- Rules source of truth: the rules anchor note (vault, career/hackathon-madrid-2026/hackathon-madrid_bazaar-rules_v1.md).
