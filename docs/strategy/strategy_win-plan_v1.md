# Win plan: why Team 3 is low and how we climb (Sat 3 Oct 2026)

Written by the `bazaar-strategy` session with Thiago at 11:47 to 12:15 Madrid (ticks 430 to 470).
Ranked moves agreed by Thiago at about 12:08.
`bazaar-strategy` recommends; `bazaar-conductor` executes.
Private values in this file stay inside the team.

## Sources (every number below names one of these)

| Tag | What it is |
|---|---|
| LB430 / LB460 | keyless `GET /api/leaderboard` at tick 430 (11:48) and tick 460 (about 12:04); fields `teams[].score` `negotiating` `market` `deals` `venues[]` |
| SCHED | keyless `GET /api/schedule` at hour 4.99 (11:50); `at_hours` fields |
| FEED | public feed merged by event id from three copies: `logs/feed/feed.jsonl` (stops at tick 205) + `logs/feed-vm/` (Friday) + the Mini's live recorder `~/bazaar/logs/feed/` (to tick 441). Cited as `e<event id>` |
| DASH | `logs/dashboard_history.jsonl` (our score and cash per tick on Saturday) |
| SCORE | `logs/score.jsonl` (our score components) |
| FRI | `docs/analysis-friday/score.md` and `docs/analysis-friday/duels.md` |
| COND | `bazaar-conductor` report at about 12:07 (duel log and broker log on the Mini; PR #22) |

## 1. Where we stand

| Team | Score | Negotiating | Market | Deals | Source |
|---|---|---|---|---|---|
| t03 (us) at tick 430 | 17.76 | 10.26 | 7.5 | 15 | LB430 |
| t03 (us) at tick 460 | 13.87 | 10.26 | 3.61 | 15 | LB460 |
| t01 (the team Thiago meant) | 23.23 | 15.73 | 7.5 | 18 | LB460 |
| t13 (level 3) | 29.88 | 24.39 | 5.49 | 45 | LB460 |
| t14 | 29.05 | 17.19 | 11.86 | 21 | LB460 |

Thiago's "Team 7" was Team 1 on the big screen (confirmed at about 11:55).
At tick 430 we matched Team 1 on market (7.5 each) and nearly on deals (15 against 17): the whole 5.4 gap was negotiating.
At tick 460 we also lost 3.89 on market (section 2.1).

## 2. Diagnosis: where the points leak

### 2.1 The first Market Test on La Celestina failed (biggest single leak)

- Market fell 7.5 to 3.61 between LB430 and LB460. Score 17.76 to 13.87. Rank 13 to 16.
- That test ran ticks 441 to 457 and was v20's first (FEED e22259; v20 `opened_tick` 269 in LB460).
- Cause (COND): the broker dropped every bench pair as `same_maker` because every bench offer has maker "bench". Efficiency 0.449.
- Fixed in PR #22 and live on the Mini since 12:05 (COND). Next test at hour 7.0 (about 13:52; SCHED).
- Why it matters: each Market Test session counts our best open venue and the round averages its sessions (`kit/RULES.md` "Your own market"). A board venue with a broker below the stall scores below 7.5 (t13 sits at 5.49 after 3.33 at LB430). Six more Saturday tests and three Sunday tests are left (SCHED hours 7 / 9 / 11 / 13 / 14.65 hard / 15 and 17 / 19 / 21).

### 2.2 Team 1 beat us with trades between teams; our dealer deals mostly do not count

| | Team-to-team trades | Dealer deals | Source |
|---|---|---|---|
| t01 | 11 (all Saturday; ticks 160 to 386) | 6 (all Abuela) | FEED settlements e10942 to e20548; dealer rows e2244 to e20177 |
| t03 | 2 (one Friday sale; one Saturday buy) | 13 | FEED e9411 / e18652 |

- `deals` on the board counts dealer deals plus team trades: our 13 + 2 = 15 matches LB430.
- Every team trade scores at private values. Dealer deals only score through the best three per level (`kit/RULES.md` "Scoring"). Our fourth and later deals with a dealer add nothing (FRI score.md:54: fifth Abuela deal +0.000).
- Buying from other teams earned more than selling on Friday: intervals with a team buy averaged +5.25 against +1.89 with a team sell (FRI score.md:47).
- Rough rate at Friday's normaliser: about 0.155 points per P of surplus (FRI score.md:51). Saturday's rate is lower because the top three trade more.

### 2.3 No level 3 yet

- Only t13 has a Doña Pilar deal: LAV-08 sold at 19 at tick 326 (FEED e17363). They asked 49 then 42; she opened at 16 and held 16 across 9 threads.
- t13's negotiating jumped 18.33 to 25.50 between ticks 330 and 340. Their MAL-10 team buy at 65 also landed at tick 331 (FEED e17595). So the jump is not all Pilar.
- Higher levels weigh more and a missing slot scores zero (`kit/RULES.md` "Scoring"). Our three level-3 slots are empty.
- Pilar opens to every team at hour 5.508 (about 12:21; SCHED and `/api/levels`).

### 2.4 Weak Chato slots

- Saturday Chato deals: MAL-06 sold at 14 (e16916) and LAV-08 sold at 14 (e20819). Third slot empty.
- In the same window Abuela paid 17 (e18805) and 15 (e21830) for uncommons. So both sales went to the lowest buyer on offer.
- t13 bought LAV-06 and LAV-07 from Chato at 26 against an opening of 33 (e12519 / e13430).

### 2.5 Duels (no leak so far today)

- Friday practice: we closed 0 of 12 while every priced rival offer was already inside our limit (FRI duels.md).
- Duels I today: first three duels all closed (+61 / +51 / +4); the bot accepts every inside-limit offer in the endgame (COND). No fix needed.
- Duels II at hour 11.65 (about 18:30) is 68 duels on price and delivery day (SCHED).

### 2.6 Cash

- Cash 95 at tick 440 (DASH last line).
- The drop from 344 to 74 at tick 270 was the venue bond (DASH lines 35 to 36; v20 `opened_tick` 269). The "keep 280 P" rule in `CLAUDE.md` is already spent on that bond. Do not block small buys on it.
- Sunday allowance: 150 P for everyone at hour 16.7 (SCHED).

## 3. Ranked moves (agreed with Thiago)

Point figures are estimates on today's relative scale. Re-rank after the 13:52 Market Test and after Duels I `duel_points` land in `/api/me`.

| # | Move | Expected points | Cost | Risk | Who |
|---|---|---|---|---|---|
| 1 | Verify the PR #22 broker fix at the 13:52 Market Test. Minimum bar: every tick match every crossing pair within the quotes (what the free stall does). If market does not recover to at least stall level: find out whether v20 can switch to `auto` or whether closing it brings back a free stall (bond back after cooldown). Do not assume either from the rules text | Win back about +3.9 (to 7.5); up to about +7.5 more if the broker beats the stall (full bench points go to the mean of the top three) | 0 P | Each bad session stays in today's average | Conductor + broker owner (`tools/bench_check.py`) |
| 2 | Fill all three Doña Pilar slots after 12:21. Queue the first thread at open (a dealer only pays what it can still afford this hour). Sell only copies where her price beats our private value: spares (valued at 25 %) / Malasaña (x0.7) / Retiro (x0.9). Keep Lavapiés and Salamanca first copies. Open high and come down in big steps | Large but not sized: no team has three level-3 deals yet | 0 P; brings cash in | She is stingy (held 16 for 9 threads); if the private-value gate holds then selling below our value earns nothing (FRI score.md:54) | Conductor |
| 3 | Copy Team 1: trades with other teams. Buy missing commons cheaply (our Lavapiés commons are worth 16 and Salamanca commons 13; t15 sold commons at 5 to 7 and t18 at 9 to 10 per FEED). Sell spare commons (worth about 4 to us) at 7 to 9. Prefer 0-fee venues over El Rastro (5 % + 1 P). Fund it with Pilar cash | About 0.5 to 1.5 per good buy at Friday's rate (FRI score.md:51) | Small budget from cash 95 + Pilar income | Low | Conductor (market desk with a small budget) |
| 4 | Duels: keep the bot as it is. For Duels II trade delivery days for price (the pie grows when each side gets the issue it cares about) | Not sized until Duels I scores | 0 P | Low | Duel bot owner |
| 5 | Third Chato slot: one negotiated uncommon buy at 26 or less where our value is higher (for example a missing Salamanca uncommon worth 32.5 to us). Later deals can replace the two weak sales at 14 | Small to medium | About 26 P | Low | Conductor |

Tonight (before Sunday 09:00):

- Ladder points reset each round: 0.081 at tick 146 (Friday) then 0.02 at tick 196 (Saturday) (SCORE lines 7 to 8).
- Sunday is round 3 with weight 1 like Saturday (SCHED hour 16.65). Final score = (0.5 Friday + Saturday + Sunday) / 2.5.
- Have bots ready from about 09:30 for three Abuela + three Chato + three Pilar deals in the first hours; Duels III (hour 18.65) and the Final duels (hour 21.65); the broker; team trades funded by the 150 P allowance.
- Chamberí is released Sunday (hour 16.65) and is worth only x0.5 to us: our natural stock to sell to dealers and teams.

Parked:

- Getting other teams to trade on La Celestina. One trade on t14's stall (e21781 at tick 418) lifted their market 7.50 to 11.86; one on t17's stall lifted 7.50 to 10.26 (LB460). But t05's lift faded 12.47 back to 7.50 (FEED snapshots). It needs a game message to other teams (operator yes) and should wait until the broker passes a test.

## 4. Brief for `bazaar-conductor`

Thiago agreed this order at about 12:08. First: confirm at the 13:52 Market Test that the PR #22 broker brings market back to at least 7.5; if it does not then find out (from the API or the organisers) whether v20 can go `auto` or whether closing it restores a free stall before the 15:52 test. Second: from 12:21 sell three cards to Doña Pilar to fill the empty level-3 slots; use only copies where her price beats our private value (spares / Malasaña / Retiro) and keep Lavapiés and Salamanca first copies; take live holdings from `/api/me` because `logs/state/me.json` is from tick 196. Third: restart team trading on a small budget funded by the Pilar cash; buy missing commons below our value and sell spare commons above it; prefer 0-fee venues. Fourth: leave the duel bot as it is and report `duel_points` after Duels I. Fifth: one Chato uncommon buy at 26 or less that is worth more to us. Tonight: prepare the Sunday ladder bots (three deals per dealer from about 09:30) because ladder points reset each round. Log any new finding in `docs/findings.md` with its tick.
