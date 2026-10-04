# Saturday lunch review: why Team 3 is 16th and what to change

Source: Team 3 lunch review, Sat 3 Oct 2026, frozen copy of the Mini at commit fa91372, tick 630.

Written Sat 3 Oct 2026, 14:15 Madrid, with the game clock paused at tick 630 (game hour 6.575). Sources: a frozen key-free copy of the Mac Mini taken at 13:25 (commit `fa91372`), three analysts (duels, market, dealers and trades), one Codex adversarial code review, and the handoffs of the strategy and conductor tabs. Each line is tagged MEASURED or INFERRED. Private values in this note stay inside the team.

## The answer in four lines

1. We never did the one thing that scores on negotiating: buying from other teams, above all the buy that completes a page. The top five made 20 team buys on Saturday. We made 1. We have 0 pages.
2. On market we opened our own venue, its broker scored zero in its first test, and no other team has ever traded on it. A team that did nothing has 7.5. We have 3.61.
3. The duel bot is fine: 25 deals from 31 duels, zero bot faults.
4. The bots that score on the 60 visible points ran with defaults that blocked them: a reserve that skipped every buy, a bid cap that walked away from a deal inside our limit, a seller with 232 listings and no fill. The dashboard, concierge, website and bus serve the Judges' 40 and the team's coordination, not the board.

## Where the points are

| | Us | Free default | Leaders | What closes the gap |
|---|---|---|---|---|
| Market | 3.61 | 7.50 | 12.50 (t12) | Stall-level tests bring us to about 6.5 today. Above that only other teams' trades on our venue count, up to +5 |
| Negotiating | 16.86 | | 21.73 (t18) | One page completed by a team buy moved rivals +4.5 to +7.2 |
| Total | 20.48, rank 16 | | 30.77 (t14) | Both together put us near 28 to 30 |

## Market (30 points)

- MEASURED: the failed test (run b36, ticks 441 to 457) scored 0, not 0.449. The broker sent no matches for 16 ticks. 0.449 was the average of that zero and the earlier free-stall session at 0.899.
- MEASURED: the fixed broker replays that book exactly like the free stall: the same 4 pairs at the same ticks. Codex found no defect in it either.
- MEASURED: no policy could have beaten the stall on that book. In simulation, any deployable smarter policy scores 0.0 to 0.4 points below the stall. Stop work on a smarter broker.
- INFERRED, fits 294 leaderboard readings within 0.002: market = 15 x bench + V. Bench is half our efficiency relative to the stall. V is up to 5 points for value created by other teams trading on our venue, measured against the top three venues.
- INFERRED: matching the stall in all six remaining Saturday tests brings market to about 6.5. One more dead test costs about 0.94.
- MEASURED: 16 of the 17 trades on team venues were a team accepting a listed offer. Announcements bring nothing: four venues posted 16 to 33 each and have zero trades.
- MEASURED: the market leaders cross-list. t05 posted 131 listings on t10's venue and t10 posted 53 back. t06 and t12 do the same. INFERRED: arranged.
- MEASURED: our SAL-01 purchase on t10's venue gave t10 about 4.3 points.
- INFERRED from the fitted formula: one typical third-party trade is worth about 1.5 points, a strong one 2.5 to 3.5. Surplus counts, volume does not, a bad trade subtracts.
- MEASURED: t13 has 11 swap offers open on our venue, addressed to other teams, expiring around tick 686.
- Rules: never close the venue. The free stalls were handed out once at tick 201, so closing scores zero per test.

## Negotiating (30 points)

### Duels (the bot is not the problem)

- MEASURED: Duels I so far: 34 seen, 31 finished, 25 deals, 6 no-deals, 3 frozen by the pause. Surplus 628 P. No-deals: 5 rivals that never spoke, 1 never inside our limit, 0 bot faults.
- MEASURED: decay cost 7 P of 628. It is charged per round of talk, not per tick.
- MEASURED: all 21 of our accepts came in the last 3 ticks, 13 of them on an offer only the late read saw.
- MEASURED: Codex found four defects, all reproduced offline, none seen on Saturday: an accept race (the accept call cannot pin an offer), an allocator that keeps the small deal when slots run out, a skipped accept that wastes the tick's one slot, and a duel length fixed at 16 ticks.
- RISK for Duels II: the delivery-days logic has never run on real data, and the local arena cannot catch a wrong guess. If the server signs the day weights, simulation shows 24 % less duel score and 8 % of deals below our real limit.
- Hector's session owns the duel bot and is fixing all of this in one pull request, due 16:30.

### Dealer ladder

- MEASURED: Abuela 3 of 3 slots, good prices. Chato 2 weak slots (two sells at 14) and 1 empty. Pilar 0 of 3.
- MEASURED: Chato's ceiling for uncommons is 14. Pilar paid 17 to 25 and teams paid 20 for the same cards. We sold two uncommons to the lowest buyer.
- MEASURED: the Chato LAV-09 no-deal was a bot defect. Pinned at its bid cap of 84 the bot went silent against his non-final 90, with our limit at 93, and the round budget closed the thread. Another team got 84 accepted on the same ladder.
- MEASURED: Pilar concedes by time, not by our step. Her finals were 19 to 21 on long threads and 17 on short ones. The armed Pilar run uses a step of 2 and 12 rounds, which can close before her final.
- MEASURED: both dealer bots default to a 280 P reserve, which silently skips every buy at our cash of 169.
- MEASURED: a dealer run already in flight ignores the duel lock, and both bots let the kit resend a refused accept.

### Team trades and pages (the real gap)

- MEASURED: Saturday team buys: t01 8, t14 6, t13 3, t05 2, t18 1. Us 1.
- MEASURED: three teams completed a page with a team buy and their negotiating jumped +5.83, +4.49 and +7.17. Two teams completed a page through Chato and moved +0.10 and +0.31.
- INFERRED: the page bonus sits inside the private value of the completing card. A team trade scores it as surplus. A dealer buy scores only ladder share and throws the bonus away. t18 paid 49 P for a common, which only a bonus explains.
- MEASURED: we hold 8 of 10 in Latina (missing LAT-03 and LAT-09) and 8 of 10 in Lavapiés (missing LAV-09 and LAV-10). Live values at tick 630: LAT-03 11, LAT-09 77, LAV-09 112, LAV-10 112.
- MEASURED: the El Rastro seller made 232 listings and 0 fills. Commons have no buyers above 5.

## Decisions for you and Hector, ranked

| # | Decision | Cost | Why |
|---|---|---|---|
| 1 | Run the 7 P test: buy LAT-03 on El Rastro (offers 9118 at 6 or 9025 at 7, both expire at tick 656), then read the value of LAT-09 | 7 P | If LAT-09 jumps from 77 to about 150, the page bonus is confirmed and pages become the top lever |
| 2 | If confirmed, complete Latina: bid for LAT-09 from a team (it trades at 64 to 70) | about 70 to 90 P | Expected surplus about +60 |
| 3 | Complete Lavapiés: LAV-09 from Chato (fills his empty slot), then LAV-10 from a team as the last card | about 86 P, then 90 to 95 P | Expected surplus about +120 on the last card. May need Sunday's 150 P |
| 4 | Fill the three Pilar slots with MAL-08, MAL-07 and MAL-06 at floor 18, using a slow opening (anchor 27, step 1, 40 rounds) | brings in about 57 P | Three empty level-3 slots, and cash for the pages |
| 5 | Agree a cross-listing swap with one or two teams in the room: they list on our venue, we list on theirs | none | The only path to the 5 venue points. Teams with a dead board venue (t13, t04, t08, t01) have the same problem |
| 6 | Ask the organisers two things: can our venue switch to automatic matching, and does the 23:00 close move with the lunch pause or is the day compressed | none | The first removes the risk of a dead broker process. The second decides whether tests get dropped (the zero then weighs more) and whether Duels II still runs tonight |
| 7 | Stop selling uncommons to Chato, and stop buying on rivals' venues unless it is part of a swap | none | Both gave points away |

## What I would deploy while the clock is paused

Nothing below has been deployed. Each item needs a yes.

1. Dealer bot fixes (this session's pull request): the Chato bid-cap deadlock, the duel lock checked before every accept, no resend of refused writes, waits that do not burn rounds while the clock is paused, a sane reserve default, Pilar's slow defaults.
2. Hector's duel pull request: the delivery-days fixes first, then the four Codex defects.
3. A broker watchdog that alerts when pairs are dropped or nothing is matched during a test.
4. The Pilar command change (decision 4).

## Checks at the first Duels II duel

- Read the first buyer and the first seller duel: the raw days meaning text and the sign of the day weight.
- Read the first message we send: if it is refused for missing days, the payload fix is needed at once.

## Sunday: six hours at 15-second ticks

- Duel bot: duel length 12, late read at 4 seconds, a fresh run for the Final, a stop time per session.
- Broker: two timeouts cut (2.5 seconds, no retries) so one hung call does not eat a tick.
- Seller: step-down cadence doubled in ticks, or it drops prices twice as fast. Idle team threads close after 5 minutes instead of 10.
- Dealer bots: tick-driven, so they are fine once the fixes above land. None of them checks that the doors are open, so do not start them before 09:00.
- Ladder points reset each round, so Sunday needs three deals per dealer again in the first hours.
- A launcher that starts everything in order with explicit flags is the next thing this session builds.

## Who is doing what

- This session: the dealer and seller pull request, the broker watchdog, the Sunday launcher, the shared analysis docs.
- Hector's session: the duel bot pull request and the Duels II parameters, the broker policy call.
- Mini conductor: every live process. It relaunched the duel bot at 14:00 with a 15:30 stop so the three frozen duels keep their bot.
- Strategy tab: the timed plan, and three field-level miners.

## Where the detail is

Files in this folder:

- `duels.md`: Duels I audit of the duel bot, with the per-duel scorecard in `duels_scorecard.json`.
- `market.md`: market audit of our venue, the broker and the desk.
- `dealers.md`: audit of dealers, the El Rastro seller and team trades, with command tables for today and Sunday.
- `dealer-bots_flags-and-timing.md`: helper audit of timing, command-line flags and behaviour locations for the dealer bots.
- `codex-code-audit.md`: Codex adversarial code review of the bots.
