# El Rastro, Friday close: pricing the spares (snapshot 2026-10-03T01:16)

Sources: snap/logs/feed/{feed,snapshots,changes}.jsonl, snap/logs/state/{me,offers}.json, snap/mini/dashboard_history.jsonl, snap/branches/{catalog.json,value_inference.py}. Scripts: out/rastro_scripts/00..07 (run in order; 03 also writes out/rastro_trades.json).

## 0. Coverage caveat (read first)

- Feed coverage window: ticks 0-48 and 119-159 only (verified tick by tick in 08_window.py). Ticks 49-118 are a recorder outage (DNS errors in results/feed-recorder.out). Every count of listings, settlements and cancellations in this file covers that window only. Within the window there are scattered losses as well: settlement numbers run 1..273, 105 present, 168 missing (02_coverage.py; range 82-198 entirely missing).
- Team-to-team count, three ways (03_rastro.py):
  - (a) settlements with venue == "rastro": 10
  - (b) settlements whose both parties match t\d\d: 10 (same 10 settlement ids as (a))
  - (c) El Rastro venue counter (snapshots.jsonl "venues"): 0 @21, 1/12 P @40, 1 @47, 39/953 P @134, 45/1088 P @155
- Reconciliation: ticks 134-155 the counter moved +6 trades / +135 P, and the feed has exactly 6 rastro settlements summing 135 P in that window, so the feed is complete there. Ticks 47-133: counter +38 trades / +941 P, feed shows 2 (100 P): 36 trades, 841 P (mean 23.4 P) are invisible. Friday total is at least 46 team trades: 45 by tick 155, plus 1 at tick 159, plus possibly some of the missing settlements 262-271. We can see 10 of them.

## 1. Team trades the feed can see (10)

| settl | tick | card | rarity | seller | buyer | maker | price | fee | price/book | listed | first price | listings of asset | ticks last listing->sale | ticks first listing->sale |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 67 | 40 | LAV-02 | common | t06 | t10 | seller | 12 | 2 | 1.20 | 12 | 12 | 4 | 11 | 14 |
| 80 | 47 | LAT-09 | rare | t13 | t14 | seller | 65 | 5 | 0.93 | 65 | 99 | 2 | 5 | 9 |
| 206 | 124 | SAL-08 | uncommon | t12 | t17 | buyer bid | 35 | 3 | 1.40 | 35 | 35 | 2 | 1 | 2 |
| 241 | 142 | LAT-10 | rare | t06 | t15 | seller | 60 | 4 | 0.86 | 84 | 84 | 2 | 3 | 14 |
| 249 | 146 | SAL-06 | uncommon | t18 | t06 | buyer bid | 23 | 3 | 0.92 | 23 | 23 | 2 | 4 | 16 |
| 252 | 147 | LAT-03 | common | t12 | t18 | seller | 9 | 2 | 0.90 | 10 | 10 | 4 | 5 | 15 |
| 253 | 147 | MAL-08 | uncommon | t03 | t17 | seller | 28 | 3 | 1.12 | 28 | 28 | 1 | 3 | 3 |
| 258 | 149 | LAV-05 | common | t15 | t12 | seller | 7 | 2 | 0.70 | 7 | 9 | 4 | 4 | 28 |
| 261 | 152 | LAV-05 | common | t06 | t05 | seller | 8 | 2 | 0.80 | 8 | 12 | 6 | 11 | 126 |
| 273 | 159 | LAT-01 | common | t06 | t04 | seller | 5 | 2 | 0.50 | 5 | 8 | 4 | 4 | 37 |

- By rarity: commons 5 at 5/7/8/9/12 (median 8, 0.8x book); uncommons 3 at 23/28/35 (median 28, 1.12x); rares 2 at 60/65 (0.89x).
- Every sell-side trade that had an earlier higher ask cleared below it: LAT-09 99->65, LAT-10 84->60, LAT-03 10->9, LAV-05 9->7 and 12->8, LAT-01 8->5.
- Ticks from last listing to sale: median 4 (range 1-11), MEASURED; every case sits inside a covered window.
- From the asset's first listing: median 14.5 (range 2-126). This is INFERENCE for LAV-05 #13 (t06), whose 126 ticks span the gap; the other 9 lie within a covered window.
- Fee is ceil(5% x price + 1) on all 10, and the ACCEPTING side pays it. Proof: our cash went 205 @146 to 233 @147 (+28 = full price) in dashboard_history.jsonl.
- Buyers: t17 x2 (SAL-08 35 via its own bid, MAL-08 28 from us), one each for t10, t14, t15, t06, t18, t12, t05, t04. Sellers: t06 x4, t12 x2, t13, t18, t03, t15.

## 2. What did not sell (feed-visible listings, ticks 0-48 + 119-159; 03 + 04)

"Died unsold" for any listing alive across ticks 49-118 is INFERENCE.

- 340 listings: 254 sell, 86 buy orders. Listing lifetime is maker-chosen, not a fixed 40 ticks: expires-created = 10 (180 listings), 2 (86), 60 (25), 15 (24), 30 (15, ours).
- 84 cancels. Of 134 same-asset relists, 90 kept the price and 34 cut it (mostly by 1-3 P).
- Unique assets offered for cash: 119.
  - These are lower bounds from the feed only. Listings made before tick 49 may have sold in the ticks 49-118 gap, where 38 trades happened unseen.
  - Commons: 92 listed, 5 sold (at least 5%), 34 still open at close (median ask 9, 3-14), 53 withdrawn or expired unsold (lowest ask median 10, range 5-13).
  - Uncommons: 24 listed, 1 sold on an ask (ours, at 28), 8 open at close (median 30, 25-38), 15 unsold (lowest ask median 26, 22-35). The other 2 uncommon trades were sellers hitting buyer bids.
  - Rares: 3 listed, 2 sold.
- Book at tick 159: 53 offers (41 sell, 12 bids). The MAL uncommons on it: MAL-07 25 (t17) and 30 (t06), MAL-08 40 x2 (t08), our MAL-06 28. The only LAV uncommon is our LAV-08 at 40.
- Competing LAV-08: t06 listed one at 30 from tick 149 to 158, next to ours at 40. Both stayed unsold. The feed is complete for rastro through tick 155, so we know nothing cleared there.
- LAV commons on the book: LAV-03 at 7 (t15) and 8 (t18), LAV-04 at 8 and 3x10, LAV-02 at 9. LAV-05 cleared at 7 and 8; LAV-01 has not traded.
- MAL-08 at 38 (t08) sat unsold from tick 126 to 147. Ours at 28 sold to t17 in 3 ticks.

## 3. Our side: the server values a spare at the 2nd-copy marginal

- me.json your_value: LAV-08 10.0 per copy (we hold 2), MAL-06 4.4 (2), MAL-08 4.4 (2 at the snapshot), LAV-01/03/05 4.0 (2 each). A single-copy LAV uncommon is 40.0 and a single LAV common 16.0.
- catalog.json values.copy_marginals = [1.0, 0.25, 0.1], page_bonus 0.25. Selling a spare costs us 25% of first-copy value: LAV-08 10, MAL-06 4.4, the LAV commons 4.
- The MAL-08 sale realised 28 - 4.4 = +23.6 at private values (the buyer paid the fee). Score went 11.63 to 14.51 @150 (dashboard) and 14.63 on the tick-155 leaderboard.

## 4. Buyer reservation arithmetic (the buyer pays price + ceil(0.05p + 1))

| buyer set multiplier | uncommon value (25m) | max ask it accepts | with page bonus x1.25 | common value (10m) | max ask |
|---|---|---|---|---|---|
| 1.6 | 40 | 37 | 46 | 16 | 14 |
| 1.3 | 32.5 | 29 | 37 | 13 | 11 |
| 1.1 | 27.5 | 24 | 31 | 11 | 9 |
| 0.9 | 22.5 | 20 | 25 | 9 | 7 |

- Only a buyer missing the card counts (a 2nd copy is worth 25%).
- At 40, LAV-08 needs a LAV-1.6 team completing its page. At 34-36 it needs a LAV-1.6 team without that copy. At 29 the LAV-1.3 teams come in.
- Minted at close (catalog): LAV-08 10 copies (we hold 2), MAL-06 11 (we hold 2), LAV-01 15, LAV-03 18, LAV-05 17.

## 5. Bids (buy orders) as set-preference hints (04, 06)

- 86 bids from 11 teams: t08 44, t02 11, t13 7, t17 6, t15 5, t06 4, t18 3, t12 2, t04 2, t05 1, t14 1.
- Most bids were for rares: SAL-09 11, LAV-09 10, LAV-10 6, MAL-09 6, LAT-10 5, LAT-09 5, MAL-10 5, SAL-10 5.
- No bids for LAV-08, MAL-06, LAV-01 or LAV-05. LAV-03 got 3 lowball bids at 2 (t08).
- Implied floors from price/book (06_hector_check.py), LAV: t14 2.2 (bid 55 for LAV-07 at tick 159, open until 219), t05 1.79 (bid 125 for LAV-09), t07 1.3, t04 1.21, t06 1.2, t10 1.2.
- Implied floors, MAL: t12 1.43 (bid 100 for MAL-10), t17 1.12 (paid 28 for MAL-08; with the fee that is about 1.24).
- These are the LAV-08 and MAL-06 targets (INFERENCE).

## 6. Venues

- The feed has venue.opened for only two venues, v03 and v04, at tick 129. The venues snapshot shows four:

| venue | owner | mechanism | fee | opened tick | trades / volume @155 |
|---|---|---|---|---|---|
| v01 Mercado Team 6 | t06 | board | 0.5%, then 0% from tick 156 | 100 | 0 / 0 |
| v02 El Duende zero fee | t12 | board | 0% | 113 | 0 / 0 |
| v03 Mercado Trece | t13 | board | 1%, 0% at tick 136, 1% again at tick 147 | 129 | 0 / 0 |
| v04 El Rastro Express | t02 | auto | 0% | 129 | 0 / 0 |

- Leaderboard market = 0.0 for every team at tick 155.
- Our cash was 233 P at tick 152 (last dashboard reading). A venue costs a 250 P bond + 20 P, so we cannot open one until the hour-4.05 grant (+150 P).
- From +3 h every team without a venue gets a free auto stall, which earns half the bench points with no bond.
- All 157 thread.opened events are persona threads, so there were zero team-to-team threads in the feed-visible windows.
- The schedule (changes.jsonl, seen at tick 134) has the first bench at game-hour 3.0 (10 traders, 16 ticks). Friday closed at hour 2.65 (tick 159), so neither the bench nor venue trading (+3 h) ever fired. Friday's zero traffic tells us nothing about demand.
- Pending in the schedule: hour 3.0 bench, then hour 4.0 Saturday round, RET release and the 150 P grant, then hour 5.0 bench.
- One game hour is 60 ticks. If the clock resumes at tick 159 with 30 s ticks, hour 3.0 is about 21 ticks (about 10 min) after 09:00 (INFERENCE: the organisers may re-time it).

## 7. Hector's value_inference.py

- What it infers: each team's set-multiplier permutation (one of 720), by Bayes over public structure. Choosing a set (dealer ask, bid, buy) counts toward a high multiplier and shedding toward a low one. A price paid or bid is a floor: multiplier >= price/book, with 10% floor noise.
- Test of the floor assumption on 148 floors (52 dealer buys, 10 team buys, 86 bids): 146 are consistent (99%). 2 exceed the max multiplier 1.6 (t14 LAV-07 55 = 2.2, t05 LAV-09 125 = 1.79), so t05 and t14 come out infeasible (2 of 15 teams).
- Both outliers fit if the 25% page bonus applies to the whole page's value, which would make them page-completers. The snapshot cannot tell whether the scorer applies the bonus per card or per page.
- Our own ground truth: 2 of our floors break it (LAT-06 28 and LAT-07 29 against LAT 1.1, value 27.5, overpaid by 0.5-1.5 P).
- Verdict: SUPPORTS, within its 10% noise. Two blind spots: the floor ignores the page bonus, and a floor measures first-copy value only.

## 8. Recommendations per spare

Our live listings expire at tick 174/175, about 15 Saturday ticks of 30 s after the 09:00 open, so around 09:07. List rather than hit bids: the side that accepts pays the fee.

| card | rarity | first-copy / spare value | listing at close | start | floor | evidence |
|---|---|---|---|---|---|---|
| LAV-08 | uncommon | 40 / 10 | 40 (14 ticks unsold) | 36 | 24 | Reservation of a LAV-1.6 buyer without the page bonus is 37, so 40 needs a page-completer. t06's LAV-08 at 30 sat unsold for ticks 149-158. No LAV-08 bids. Step 36 -> 29 (LAV-1.3 reservation) -> 24 (1.1). Targets: t14 (bid 55 for LAV-07), t05, t07. |
| MAL-06 | uncommon | 17.5 / 4.4 | 28 (15 ticks unsold) | 28, then 24 | 20 | t17 paid 28 for MAL-08. 28 is under the MAL-1.3 reservation of 29, and 20 is the MAL-0.9 reservation. MAL-07 is asked at 25 and 30, MAL-08 at 40 (unsold at 38 for 21 ticks). t10's MAL-06 at 25 and 35 did not sell on ticks 35-47. 25 would be a dead step: the MAL-1.1 ceiling is 24. Targets: t12 (MAL floor 1.43), t17. |
| LAV-01 | common | 16 / 4 | not listed | 9 | 6 | No LAV-01 on the book and none traded. Commons clear at a median of 8 (5-12), and 12 cleared only once (tick 40). The LAV-1.3 reservation is 11. Abuela buys commons at 5-6. |
| LAV-03 | common | 16 / 4 | not listed | 7 | 6 | LAV-03 is already asked at 7 (t15) and 8 (t18). The only bids are 2 (t08). LAV-03 is the most minted of the three (18). |
| LAV-05 | common | 16 / 4 | not listed | 8 | 6 | LAV-05 cleared at 7 (t15 to t12, tick 149) and 8 (t06 to t05, tick 152). Only 5% of listed commons sold. |
