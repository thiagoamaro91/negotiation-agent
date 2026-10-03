# Dealer concession model (Abuela L1, El Chato L2), Friday field data

Snapshot: S/snap (copied 01:17, 3 Oct). Scripts: S/out/dealers_scripts/ (run in order: parse_threads.py, analyze.py, analyze2.py, summary_table.py). Raw outputs: analysis.txt, analysis2.txt, summary.txt, threads_merged.json.

## Coverage and caveats (read first)
- feed.jsonl covers ticks 0-48 and 119-159 only. Ticks 49-118 are missing (168 of 273 settlement numbers absent; thread ids 84-~212 absent). The recorder log shows DNS read failures.
- So the field sample is roughly the first game hour plus the last 40 ticks. 174 dealer threads parsed (171 from feed + 3 of ours from thread files), 95/95 dealer settlements in the feed matched to a thread.
- 14 threads were opened inside the gap. Their first observed price is not the true opening, so they are excluded from opening stats but kept for final prices.
- Chato: `persona.open_to_all` fires at tick 158 and the feed ends at 159. Every Chato thread is from early-unlock teams (14 teams had Chato threads, the first at tick 119). Samples: 7 rare buys, 6 uncommon buys, 1 silver pack.
- Walk counting: `thread.closed` appears once only, so walks are inferred. Threads whose last message is at ticks 46-48 or >=157 without a settlement count as censored, not as walks.
- Team words are null in the feed, so only the price sequences can be analysed.

## DONE CHECK (our deals)
| thread | dealer | card | price | source |
|---|---|---|---|---|
| 49 | abuela | LAV-06 | 17 (welcome) | feed |
| 70 | abuela | LAV-07 | 22 (final) | feed |
| 105 | abuela | LAV-08 | 23 (final) | thread file (tick 65, in the feed gap) |
| 117 | abuela | SAL-06 | 25 (final) | thread file (in gap) |
| 150 | abuela | SAL-07 | 22 (final) | thread file (in gap) |
| 234 | chato | SAL-08 | 29 (final) | feed |
| 253 | chato | LAT-06 | 28 (final) | feed |
| 275 | chato | LAT-07 | 29 (final) | feed |
All 8 match our logs. 5 come from the feed; 3 can only come from thread files because of the recorder gap.

## 1. Per dealer per rarity (team buys, welcome-price deals excluded)
| dealer | rarity | neg deals (+welcome) | opening | final min/med/max | team bids med | engaged threads: deal / walked after final / left without final |
|---|---|---|---|---|---|---|
| Abuela | common | 17 (+2 at 7) | 12 | 8/10/12 | 2 | 23: 17/0/6 |
| Abuela | uncommon | 20 (+3 at 17) | 29 | 21/24/25 | 4 | 27: 20/1/6 |
| Abuela | neighbourhood pack | 13 (+7 at 17) | 30 | 19/22/24 | 5 | 26: 13/3/10 |
| Chato | uncommon | 6 | 33 | 28/29/32 | 6 | 7: 6/0/1 |
| Chato | rare | 7 | 97 | 82/91/93 | 4 | 8: 6/0/2 |
| Chato | silver pack | 1 | 188 | 181 | 4 | 1: 1/0/0 |

Welcome price (17 for a pack or uncommon, 7 for a common): there were 12 welcome deals in the field. INFERENCE from the per-team opening sequences (analysis2.txt section B):
- The welcome price shows up on a team's early threads, across kinds, and mostly disappears after the team's first welcome-price deal. This held for t03, t08, t10, t14 and t17: t14 saw a 17 pack (no deal), then a 7 common (deal), then 12s; t17 saw 7, 7 (deal), then 12.
- One exception: t09 still saw 17 on two more pack threads after its tick-3 welcome deal.
- Our pack thread 43 opened at 17 and we did not take it; we then used our welcome on LAV-06 (thread 49). A 17 pack is probably gone for us, but worth one probe.

## 2. Chato rares, every thread
| th | team | card | Chato asks | team bids | result |
|---|---|---|---|---|---|
| 219 | t14 | LAV-10 | 92,91 (gap open) | none | final 91, deal 91 |
| 223 | t12 | MAL-09 | 96,95,92,90 (gap open) | 82,84 | final 90, deal 90 |
| 243 | t04 | LAV-10 | 97,96,95,92,90,88,86,84 | 46,60,66,72,74,76,78,80,82 | **he accepted our bid of 82** (9 bids, ticks 124-140) |
| 246 | t14 | LAV-09 | 97,97,96,95,94,93 | 72,73,74,75,76 (+1 steps) | final 93, deal 93 |
| 255 | t12 | MAL-10 | 97,97,95,93 | 46,68,83,89 | bid 89 accepted |
| 263 | t07 | LAV-10 | 97,96,95,93,91 | 68,82,88,90,91 | bid 91 accepted |
| 289 | t05 | LAV-09 | 97,97,95,93 | 70,73,76 | took his ask of 93 |
| 248 | t08 | MAL-09 | 97,97,96 | 63,67 | no deal |
| 286 | t04 | LAV-09 | 97,96,95,93,91,89,87 | 60,62,...,72 (+2) | no deal, no final (left at ask 87) |
| 298 | t07 | LAT-10 | 97,97,96,94,90,86,82 | 58,62,66,70,74,78 (+4) | censored at feed end, ask 82 vs bid 78 |
No team got a rare below 82. The 82 deal came from steady +2 steps reaching 82 before his patience ran out. Th 298 shows that +4 steps get his ask down to 82 by his 7th message with no final yet.

## 3. Who beat the field typical price
- Abuela uncommon at 21: t06 LAV-06 bids 11,15,17,20,21 against asks 29,25,23,22, and she accepted our bid. t13 MAL-06 bids 11,13,15,19,20,21, also accepted. Both opened at 38% of her ask, used 2-4 P steps, and reached 20-21 by the 5th-6th bid.
- Our +1 crawl (11..14-16) never reached her limit, so her patience ended first and her finals landed at 22-25.
- Abuela pack at 19: t17 (10,11,16,18,19), t09 (13,15,16,17,18,19) and t12 (9,11,13,15,17,18, then final 19). Opened at 30-43%, reached 18-19 by bid 5-6.
- Commons at 8-9: t10 bid 4,6,7,8 and got 8 accepted.
- Chato uncommon at 28: t03 LAT-06 (13 then +1 x7, final 28) and t14 LAV-06 (22 then +1, bid 28 accepted). Teams that opened at 70-85% paid 31-32. No uncommon went below 28.
- Chato rare: see section 2. The low end (82, 89) came from accepted team bids; the high end (93) came from +1 steps or from taking his ask.

## 4. Does our step size change his concession? Yes: both dealers mirror our step, up to a cap
Non-final dealer drop vs our preceding step:
- Abuela uncommon: step 1 gives mean 0.89; step 2 gives 1.64; step 3 gives 1.5; step 4 gives 2.67.
- Abuela pack: step 1 gives 1.17; step 2 gives 1.68; step 4 gives 4.33.
- Abuela's drop exceeded our step in 17 of 137 cases, 13 were her first concession (29 to 25/26, 30 to 25/26) and 4 her second (2 P). That first drop does not depend on how high we open: 3-5 P whether the first bid was 10% or 66% of her ask.
- Chato rare: step 1 gives 1.33; step 2 gives 1.8; step 4 gives 2.67; step 6 gives 1.75. Steps of 14 and 22 got 1 and 0.
- Chato uncommon: holds 33 for his first 3 messages, then 1 per our +1.
- Chato's drop exceeded our step in only 1 of 48 cases ("small steps earn small steps" is confirmed).
- A bigger step makes him drop faster per round, but only up to about 2-4 P. Big jumps just give away our own room.
- The final offer comes when his patience runs out. Paths that crawl in 1 P steps (rares, where 1 P is under 2% of the 70 book) drew early high finals: 93 in th 246.

## 5. Selling to dealers
| dealer | rarity | price paid by dealer |
|---|---|---|
| Abuela | common | 5-6 in 10 of 13 deals; spikes 13 (ticks 0, 28) and 23 (t08 LAT-05, tick 37) |
| Abuela | uncommon | 13-16 (5 deals) |
| Chato | uncommon | 13-15 (3 deals; he opens at 13 and his final is 15-16) |
| Chato | rare | 46 (t13 LAT-09, 1 deal) |

To us: CHA (x0.5) uncommon = 12.5 and CHA rare = 35, so a dealer sale beats our value only for CHA (Abuela at 14-16, Chato rare at 46, +11). MAL rare = 49 > 46, so no. Everything else is below our value. INFERENCE: sells probably count as "deals" for the level unlock. t16 unlocked Chato at tick 132, the same tick as its SAL-06 sell to Abuela at 14, but its other deals fall in the feed gap.

## 6. Packs
- Abuela neighbourhood pack: welcome 17, then opens at 30. Negotiated 19-24 (median 22).
- Catalog expected book is 33.8 (2 commons + a common or uncommon). `pack.opened.best` is null in 28/29 openings because no rare is possible.
- Chato silver pack: 1 deal (t08, 181 against an ask of 188). It produced a rare, MAL-09.
- Several teams opened `sobre_bienvenida` at ticks 124-152 with no dealer settlement, which looks like an organiser grant.

## 7. Gifts
- 16 gifts, all from Abuela, each a single card (14 commons, 2 LAT-06 uncommons). None from Chato.
- 10 came in ticks 4-40 (first hour) and 6 in ticks 129-157. The 5 teams with two gifts got one in each window.
- 5 of 16 came within 3 ticks after an Abuela settlement; ours (tick 40, LAV-02) came mid-thread before the LAV-07 deal. Gifts are not scored (RULES).

## Dealer-side ladder evidence (not settled here)
- RULES line 118 defines the ladder as "share of each dealer's price range you captured: your best three deals per level count".
- Chato's lowest prices sit at about list x 1.07 (uncommon 28 = 26 x 1.077; rare 82 = 77 x 1.065), and his opening is list x 1.26. That suggests a floor near 28 / 82 (INFERENCE, 2 rarities only).
- Under a range reading, LAT-06 at 28 is at the floor yet scored 0. The private-value gate stays the better explanation; it is for the scoring analyst.

## Bid schedule for Saturday
| dealer | kind | open bid | steps | aim | walk-away cap |
|---|---|---|---|---|---|
| Abuela | common (LAV 16 / SAL 13 / LAT 11 only; RET 9 borderline; MAL 7, CHA 5 never) | 4-5 | +2,+1,+1 | 8-9 | min(private value, 10) |
| Abuela | uncommon (LAV 40 / SAL 32.5 / LAT 27.5; RET 22.5 borderline; MAL 17.5, CHA 12.5 never) | 11 | +4,+2,+3,+1 (11,15,17,20,21) | 21, or her final at 22 | min(private value, 23) |
| Abuela | neighbourhood pack (no per-card private value; EV is about 34 book) | 10 | +3,+2,+2,+1 to 18-19 | 19 | 21 |
| Chato | uncommon (LAV/SAL only) | 22 | +1 | 28 | 29; LAT/RET/MAL/CHA = don't buy |
| Chato | rare (LAV 112; SAL 91 only if <= 84) | 60 | +4 to 76, then +2 (60,64,68,72,76,78,80,82) | 82-84 | own bids max 84; accept his final <= 93 for LAV |
| Abuela welcome | any | take it at 17/7 on the first thread of each kind | - | - | - |

## Jay's lessons, checked
- Welcome 17 for uncommons and packs, 7 for commons: HOLDS (12 field welcome deals at 17/7).
- Openings 29 / 30 / 12: HOLDS (25/25, 24/24, 22/22 standard openings).
- "Final lands at 23" for uncommons and packs: ROUGHLY. Uncommon finals were 22,22,22,22,23,24,25; pack finals 19-24 (median 22).
- "Lowest accepted uncommon bid 22": FAILS. The field had two accepted bids at 21 (t06, t13).
- Pack lowest accepted 19: HOLDS (3 deals at 19). His pack "probe 21 / ceiling 22" is too high; aim 19.
- Commons final 9 / lowest 9: FAILS. One accepted at 8, and 7 of 17 negotiated common deals were at 8-9.
- Sell commons at 5-6: HOLDS for 10 of 13. His "best price 16" is an uncommon (t12 LAV-06), not a common; common spikes went to 13 and 23.
- "Welcome deals never count": CONSISTENT with RULES (an opening-price deal does not count), not tested here.
- Unlock "3 needed (ASSUMED)": now MEASURED. `level.unlocked.why` = "3 deals with abuela" for t02, t04, t08, t16. Sells counted (t16), and whether a welcome counts is unknown (gap).
- His grades for our threads 105 and 117 as "bad" (23 and 25 vs 22 elsewhere): FAIR. The field reached 21-22 with faster steps.

## Open questions
1. Does Chato's rare floor sit below 82? Th 298 (ask 82 vs bid 78 with +4 steps) was cut off by the feed end. Saturday's first rare thread will tell.
2. Does a welcome or sell deal count toward ladder credit, or only toward the unlock?
3. Hourly stock: will Chato still have LAV rares (LAV-09/10) on Saturday, and is it 1 per team per hour?
4. What happened in hour 1 (ticks 49-118)? The missing third of the data could shift the Abuela medians by 1 P.
5. Does walking from Chato (memory 0.9, strictness 0.85) cost a cooloff before we can reopen on the same card?
