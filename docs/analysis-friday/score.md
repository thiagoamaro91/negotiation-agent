# What moves the Bazaar score: Friday analysis (snapshot 01:16, read-only)

Scripts: `out/score_scripts/attrib.py` (-> attrib.out), `open_q.py` (-> open_q.out), pages check (-> pages.out). Every number below is in those outputs.

## Data limits (read first)
- snapshots.jsonl holds 68 rows but only 13 are leaderboards (12 distinct refresh ticks: 20,25,30,35,40,45,130,135,140,145,150,155). The rest are `rastro` (46) and `venues` (9) snapshots.
- Feed covers ticks 0-48 and 119-159 only (id gap 1928 -> 5801 = recorder down ticks 49-118). Three of our five Abuela deals (LAV-08, SAL-06, SAL-07) are missing from the feed for that reason.
- So every 45->130 jump is AMBIGUOUS (black hole). Board fields (deals, album, pages, venue) are used instead across it.
- Market = 0.00 for all 18 teams in all 12 refreshes (no Market Test ran Friday). Duels were the practice session (does not score; our 18 duel logs: 12 no_deal, 6 live, result sum 0).

## DONE CHECK (t03 trajectory)
0 / 0 / 5.25 / 5.09 / 4.92 / 4.59 | 12.50 / 12.17 / 12.17 / 11.63 / **14.51** / 14.63. The MAL-08 sale to t17 settled tick 147 (rastro, 28 P, fee 3), inside 145->150 (+2.88), then +0.12 at 155. LAT-07 (chato, tick 146) is in the same interval, but the ladder-only teams t01/t02/t09/t16 were flat 145->150 (ladder normaliser constant) and our raw ladder_points stayed 0.081 from tick 146 on, while neg_points went -4.9 -> +18.7. So the +2.88 is the trade, not LAT-07. Parsing verified.

## 1. Trajectory and final order (tick 155)
t13 30.00, t12 27.87, t17 22.08, t10 20.79, t05 20.03, t04 19.89, t18 19.19, t14 18.09, t08 17.65, **t03 14.63 (#10)**, t06 12.14, t15 10.35, t09 9.54, t07 8.98, t01 8.34, t16 6.86, t02 6.84, t11 0.00.
All of it is Negotiating (market 0). t13 has been pinned at exactly 30.00 for six straight refreshes (130-155).
Max score was exactly 12.50 at ticks 20-35 (before the first team-to-team trade at tick 40); ties at 12.50: t06+t13 (t20), t05+t06 (t30).

## 2. Top-5 jump attribution (|delta| > 1.32 = max zero-event drift)
| team | interval | delta | preceding events | verdict |
|---|---|---|---|---|
| t13 | 35->40 | +1.57 | Abuela buy MAL-06@21 | dealer deal |
| t13 | 45->130 | +19.10 | sold rare LAT-09 to t14 @65 (t47), page 0->1, venue v03, deals 5->22 | AMBIGUOUS (black hole) |
| t12 | 30->35 | +3.74 | sold LAV-06@16 to Abuela | dealer sell |
| t12 | 45->130 | +18.23 | sold SAL-08 to t17 @35 (t124), Chato MAL-09@90, deals 5->17, venue v02 | AMBIGUOUS |
| t17 | 25->30 | +4.12 | 2 Abuela buys + gift (boundary tick) | AMBIGUOUS (dealer) |
| t17 | 35->40 | +2.30 | Abuela pack@19 | dealer deal |
| t17 | 45->130 | +10.84 | bought SAL-08 from t12 @35, page 0->1 | AMBIGUOUS |
| t10 | 20->25 | +3.08 | Abuela LAV-06@24 | dealer deal |
| t10 | 35->40 | +20.81 | bought LAV-02 from t06 @12 + Abuela LAV-07@24 | AMBIGUOUS, but a dealer buy averages +1.7: the trade is ~+19 |
| t10 | 45->130 | -7.45 | deals 5->16, page 0->1 | AMBIGUOUS (normaliser caught up) |
| t05 | 20->25, 25->30 | +3.12, +2.80 | Abuela LAV-05@9, LAV-02@9 | dealer deal |
| t05 | 150->155 | +7.79 | Chato LAV-09@93 + bought LAV-05 from t06 @8, page 0->1 | AMBIGUOUS (trade+dealer) |
| t03 | 25->30 | +5.25 | Abuela LAV-06@17 (first deal) | dealer deal |
| t03 | 145->150 | +2.88 | MAL-08 spare sold @28 (+ LAT-07, ladder 0) | team trade |

## 3. Average score delta per event type (pure single-category intervals, covered feed)
| category | n | mean | median | drift-adj mean | mixed (AMBIGUOUS) n |
|---|---|---|---|---|---|
| team_sell | 4 | +2.01 | +0.75 | +2.14 | 3 |
| dealer_buy | 22 | +1.71 | +2.06 | +1.97 | 14 |
| dealer_sell | 14 | +1.30 | 0.00 | +1.44 | 1 |
| team_buy | 1 | +0.67 | | | 6 |
| pack_opened | 5 | -0.10 | 0.00 | -0.03 | 9 |
| gift | 3 | -0.17 | | -0.05 | 4 |
| no event (drift) | 113 | -0.22 | | | |
Any interval containing a team_buy (incl. mixed): n=7, mean +5.25 (t10 +20.81, t05 +7.79, t15 +4.73 ...). Containing a team_sell: n=7, mean +1.89.
Page completion 0->1 in covered intervals: t12 +1.02, t07 +1.08, t15 +4.73, t08 -5.65, t05 +7.79 (no album term in the score; pages act through trade value).
Level unlock: 6 feed events, none in a pure interval (n=0). Venue opened: market stays 0.00 for everyone.

Per-unit conversion at the current normalisers (ours, MEASURED): one gated ladder deal ~0.02 raw = 12.5*0.02/0.0871 = ~2.9 pts while it fills one of the best-3 slots; team surplus 18.7 P -> +2.88..3.00 pts = ~0.155 pts per P of surplus.

## 4. OPEN questions
(a) Ladder value gate: CONFIRMED for us. Abuela 5 deals, all priced below single-copy value: ladder 0.022 / 0.042 / 0.062 / 0.062 (5th deal +0.000, best-3 cap). Chato: all three threads opened at 33; SAL-08@29 (value 32.5, PASS) -> board 11.45 -> 12.50; LAT-06@28 (value 27.5, FAIL) -> board 12.17 -> 12.17 with ladder-only t01/t02/t09/t16 also flat (normaliser constant), so +0 ladder although 28 captured MORE of Chato's range than 29. Range-share alone cannot give that. LAT-07@29 FAIL -> ladder stayed 0.081. Other teams: UNTESTABLE beyond a sanity filter: zero dealer buys in the feed above book x 1.6 (the only certain fails). Verdict overall PARTIAL (confirmed on t03, n=8; not testable on others).
(b) neg_points -4.9: PARTIAL. The unit is raw P at private values, and duplicates are marked at 25%: me.json your_value LAV-01 4.0/16, LAV-08 10/40, MAL-08 4.4/17.5 (ratio 0.250); collection_value 544.2 = first copy full + extra copies 25% exactly. The sale decodes exactly: 28 - 4.375 = 23.625 = observed +23.6. The -4.9 onset (between tick 94 and 146, no team trade, deals 5->8) is NOT explained: tested chato surplus +1.5, chato losses -2.0, LAV-08 dup buy -13, practice duels 0. Desk question.
(c) Normalisation: CONFIRMED top-3 (mean, capped at 1). Tick 30->35: t06 stays pinned 12.50 with no event and no deal change, yet the one-deal baseline drops 5.25 -> 5.09 (-3.0%) and t05 12.50 -> 12.46 with no event. Under top-1 the max (t06) did not move, so nobody's score could fall. t09 jumped 6.30 -> 11.20 into the top three in that interval, which raises a top-3 mean. Ties at 12.50 (t20, t30) are the same fingerprint. Matches the UI text quoted in the rules anchor.
(d) Best-3 reset per day: UNTESTABLE (one day of data).
(e) Friday weight: CONFIRMED by RULES.md text (rounds averaged, Friday counts half, a new round grows in by share of day played); snapshot shows round 1 weight 0.5, phase 0.646 at close. UNTESTABLE from data until Saturday refreshes exist. Implication: Saturday weighs 2x Friday; Friday points carry but shrink as Saturday's phase grows.

## 5. Top teams vs us
- Traded with other teams early: t10 (tick 40), t13 (tick 47, a rare for 65). Our only trade was tick 147.
- 5/5 of the top five have a complete page (we have 0). It does not score directly; it lifts the private value of the completing card, so the trade that completes a page carries big surplus.
- More deals by tick 45 (top five 5 each vs our 1) and 15-24 by close vs our 9: they filled ladder slots and bought trade inventory earlier.
- Top 2 (t13, t12) opened venues (v03 1% then 0%, v02 0%) before the Market Test; market still 0, so this is positioning for Saturday.

## Inferences (not measured)
- Ladder part caps at 12.5 (max 12.50 exactly, ticks 20-35, before any team trade; we hit exactly 12.50 at t130 with no trade).
- Friday live weights look like ladder 12.5 + team trades 17.5 (t13 = 30.00 x6, market 0, duels unscored). Alternative: trade part uncapped and the total clipped at 30.

## Addenda (after review)
- (a) rider: the discriminating evidence is n=2 at Chato (SAL-08 pass credited, LAT-06 fail flat); the five Abuela deals all passed, so they measure the best-3 cap, not the gate. LAT-07's zero is inferred (no ladder reading between LAT-06 and LAT-07 settling). Confound: SAL-08 was deal #1 at level 2, the fails were #2 and #3, so "only the first deal per level counts" also fits Chato (Abuela's three credited deals argue against it). Saturday test: one below-value Chato buy (LAV uncommon <= 39 or SAL uncommon <= 32), read ladder_points before and after.
- Buy side beats sell side: any interval with a team_buy averages +5.25 (n=7) vs team_sell +1.89 (n=7). We only sold.
- t10 @ tick 40 check of the 12.5 + 17.5 inference: ladder part 8.04..12.50, so trade part 16.63..21.09; consistent with a 17.5 cap but not decisive.
- Venue: 250 bond + 20 P (RULES.md); our cash 233 at close, so a venue needs ~37 P more first. Free stall earns at most half the bench points.
- Per-event averages are confounded by timing (normalisers were small early: a first dealer deal at tick 25-30 gave +3 to +5; at tick 130+ +1 or 0) and by drift (median zero-event delta -0.22).
- Gap check (conductor heads-up, gap_check.out): snapshots.jsonl has the same hole, no rows of any kind between tick 48 and tick 134 (leaderboard refresh 45 -> 130, wall 21:04 -> 22:34). Feed has 105 of 273 settlement numbers (168 missing). dashboard_history covers ticks 75-159 for t03 only, so other teams' 45->130 jumps stay AMBIGUOUS; ours inside the gap: 12.11 flat ticks 75-100 (deals 4->5, 5th Abuela deal +0), drift to 11.45 by 125.
