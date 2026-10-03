# Win plan: why Team 3 is low and how we climb (Sat 3 Oct 2026)

Written by the `bazaar-strategy` session with Thiago at 11:47 to 12:15 Madrid (ticks 430 to 470).
Ranked moves agreed by Thiago at about 12:08. Move 2 detail corrected at 12:20 with the conductor's holdings check.
Red-teamed at 12:45 (no BLOCKER; 4 MAJOR fixed in place). Section 5 lists the corrections; where they differ from earlier text the corrected rows below win.
SUPERSEDED at 15:35 by plan v2.1 in section 6 (after three data analyses across all 18 teams and a review by the `thiago-air-review` session). Where section 6 differs from earlier sections it wins.
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
| t03 (us) after tick 520 (during Duels I) | 19.29 | 15.68 | 3.61 | | `/api/leaderboard` and DASH as re-read by the red-team verifier |
| t01 after tick 520 | 25.95 | 18.45 | | | same |

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
- Abuela paid other teams 17 (e18805) and 15 (e21830) for uncommons at other ticks after longer haggles; her opening (12) is below Chato's (13). So this is not a like-for-like proof that Chato was the wrong buyer.
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
| 1 | Verify the PR #22 broker fix at the 13:52 Market Test by THAT SESSION's efficiency from `tools/bench_check.py` against the free-stall level. Do not judge it by the leaderboard market reaching 7.5: market is a round average and the bad session at ticks 441 to 457 stays in it (`kit/RULES.md` "the round averages its sessions"). Ask now (not after the test) whether v20 can switch to `auto` and whether closing it restores a free stall (`kit/RULES.md`: "Every team without a venue then gets a free starter stall"); act on it only if the session itself is below stall | Each session at stall level or better instead of near zero; up to about +7.5 on the market part if the broker beats the stall | 0 P | Each bad session stays in today's average | Conductor + broker owner (`tools/bench_check.py`) |
| 2 | Fill all three Doña Pilar slots today after Duels I. Each dealer gives every team the same allotment per hour (`kit/RULES.md` "Dealers"). Slots 1 and 2: MAL-06 and MAL-08 single copies with a floor of 18 each (our value is 17.5; she paid t08 only 17 for MAL-06 at tick 510 per `/api/feed`). Treat each of the first three deals per dealer as final: Friday's data fits "the first three gated deals count about the same" as well as "best three by share" (section 5). Slot 3 preferred: buy a first copy we lack in a low-multiplier set (likely MAL-07; worth 17.5) from another team at 17 or less and resell it to Pilar at 18 or more. Slot 3 fallback (manual exception that needs Thiago's yes): a second copy of a Salamanca uncommon bought from Abuela and resold to Pilar in the Salamanca fever (hours 9.15 to 11.15; about 16:00 to 18:00) only if a probe at 16:00 shows her fever bid above the Abuela price; `agent/abuela.py` skips held cards so it cannot do this. Never buy a Salamanca second copy from another team (a team trade at about 20 for a copy worth about 8 scores about -12 surplus) | Large but not sized: no team has three level-3 deals yet | 0 P for slots 1 and 2; slot 3 about 15 to 17 P out and 18 or more back | She is stingy; live prices since 12:21 were 17 to 20 for uncommons outside her loved sets and 24 for SAL-08 before the fever (`/api/feed` ticks 508 to 513); no Pilar bot yet (a `--dealer` option for `agent/chato.py` is proposed) | Conductor |
| 3 | Copy Team 1: trades with other teams. Buy missing commons cheaply (our Lavapiés commons are worth 16 and Salamanca commons 13; t15 sold commons at 5 to 7 and t18 at 9 to 10 per FEED). Sell spare commons (worth about 4 to us) at 7 to 9. Prefer 0-fee venues over El Rastro (5 % + 1 P). Fund it with Pilar cash | About 0.5 to 1.5 per good buy at Friday's rate (FRI score.md:51) | Small budget from cash 95 + Pilar income | Low | Conductor (market desk with a small budget) |
| 4 | Duels: keep the bot as it is. For Duels II trade delivery days for price (the pie grows when each side gets the issue it cares about) | Not sized until Duels I scores | 0 P | Low | Duel bot owner |
| 5 | Third Chato slot: the Salamanca uncommon buy is withdrawn (we hold SAL-06 / SAL-07 / SAL-08; a second copy is worth about 8 and fails the gate). No uncommon we lack clears the gate at his 26 to 33 asks. Only a rare we lack does: LAV-09 with `--cap 88` (worth 112 to us) and only if cash is 120 or more after the Pilar sales; otherwise on Sunday with the 150 P allowance | Small to medium | About 88 P | Cash for move 3 | Conductor |

Tonight (before Sunday 09:00):

- Ladder points reset each round: 0.081 at tick 146 (Friday) then 0.02 at tick 196 (Saturday) (SCORE lines 7 to 8).
- Sunday is round 3 with weight 1 like Saturday (SCHED hour 16.65). Final score = (0.5 Friday + Saturday + Sunday) / 2.5.
- Have bots ready from about 09:30 for three Abuela + three Chato + three Pilar deals in the first hours; Duels III (hour 18.65) and the Final duels (hour 21.65); the broker; team trades funded by the 150 P allowance.
- Chamberí is released Sunday (hour 16.65) and is worth only x0.5 to us: our natural stock to sell to dealers and teams.

Parked:

- Getting other teams to trade on La Celestina. One trade on t14's stall (e21781 at tick 418) lifted their market 7.50 to 11.86; one on t17's stall lifted 7.50 to 10.26 (LB460). But t05's lift faded 12.47 back to 7.50 (leaderboard snapshots in the Mini recorder `~/bazaar/logs/feed/snapshots.jsonl`). It needs a game message to other teams (operator yes) and should wait until the broker passes a test.

## 4. Brief for `bazaar-conductor`

Thiago agreed this order at about 12:08. First: judge the 13:52 Market Test by that session's efficiency from `tools/bench_check.py` against the free-stall level (not by the board reaching 7.5); ask now whether v20 can go `auto` and whether closing it restores a free stall so a decision is ready before the 15:52 test. Second: after Duels I sell three cards to Doña Pilar to fill the empty level-3 slots (the hourly allotment is per team so there is no rush); MAL-06 and MAL-08 first with a floor of 18; for the third prefer a low-multiplier first copy bought from a team at 17 or less (the Abuela second-copy flip is a manual exception that needs Thiago's yes); keep Lavapiés and Salamanca first copies; take live holdings from `/api/me` because `logs/state/me.json` is from tick 196. Third: restart team trading on a small budget funded by the Pilar cash; buy missing commons below our value and sell spare commons above it; prefer 0-fee venues. Fourth: leave the duel bot as it is and report `duel_points` after Duels I. Fifth: Chato only for LAV-09 with `--cap 88` if cash is 120 or more after the Pilar sales. Any dealer bot launch passes `--reserve` (about 40) / `--only` / `--cap` / `--max-deals 1` explicitly. Tonight: prepare the Sunday ladder bots (three deals per dealer from about 09:30) because ladder points reset each round. Log any new finding in `docs/findings.md` with its tick.

## 5. Red-team corrections (12:45)

Run: four blind lenses (premise / sequencing / failure-modes / verification) with refute-first verifiers. No BLOCKER survived. The fixes above come from these four MAJOR findings:

| # | Finding | Fix |
|---|---|---|
| 1 | Move 1 used the board's market reaching 7.5 as the bar; market is a round average so a working broker would read as a failure | Judge the session by `tools/bench_check.py` efficiency against the stall; research the fallback now |
| 2 | Move 5 named SAL-06 as missing; we hold SAL-06 / SAL-07 / SAL-08 (`logs/state/me.json`; ledger ticks 72 / 87 / 128) | Chato SAL buy withdrawn; LAV-09 with `--cap 88` only if cash allows |
| 3 | "Later deals replace weak slots" is unproven: LAV-06 (share 0.0) took ladder 0 to 0.022 at tick 33 while SAL-06 (0.5) and SAL-07 (0.88) added nothing as deals 4 and 5 (SCORE lines 1 to 6 and the ledger) | Treat each of the first three deals per dealer as final; the optional Abuela spare-common sale is dropped |
| 4 | The bots cannot run the slot-3 buys as written: `agent/abuela.py` skips held cards; `agent/chato.py` pays up to full private value without `--cap`; both default `CASH_RESERVE` to 280 (chato.py:41 / abuela.py:41) and skip every buy at 95 P | Explicit `--reserve` / `--only` / `--cap` / `--max-deals 1`; the Abuela flip only by hand as an approved exception |

Refuted: dealer accepts do not steal the broker's Market Test matches (the broker uses its own key); the per-team hourly allotment line is in `kit/RULES.md`.

## 6. Plan v2.1 (Sat 15:35; posted on the team bus as #5969671390)

Built from three analyses across all 18 teams (points per action / market and venues / Duels I) and reviewed by `thiago-air-review` (full reports on branch `docs/analysis-saturday`). Times checked against `/api/schedule` at tick 639 (hour 6.65).

### What points are worth (board points; Saturday windows)

| Action | Board points | Source |
|---|---|---|
| First trade between two other teams on your venue | +2.8 to +5.0 | t05 tick 311 / t14 tick 418 / t17 tick 433 |
| Each Market Test at stall level instead of broken | about +0.9 | fit that reproduces our 3.61 and t08 / t13 |
| Sale to Pilar (L3) | about +1.2 | t14 tick 511 / t04 tick 527 |
| Duels | 40 % of negotiating | every team rescaled to 0.60x at ticks 460 to 470 |
| Team trade | median about +0.35; a rare sold +1.4 to +1.9 | our MAL-10 at 74 (tick 585) gave +2.92 |
| Dealer deals past the first three | 0 to -1.9 | t12 ticks 194 / 200; t16 ticks 201 / 206 |
| Completing a page with a team buy | +4.5 to +7.2 negotiating for three rivals | page bonus confirmed: LAT-09 value 77.0 to 149.9 after LAT-03 (bus #5969658274) |

### Clock

- Saturday closes at game hour 14.088 (23:00). Tonight: Market Tests at 7.0 / 9.0 / 11.0 / 13.0; Salamanca fever 9.15 to 11.15; Duels II at 11.65 (about 20:34).
- Sunday 09:00 is hour 14.088 and the morning is still round 2: tests at 14.65 and 15.0 count for Saturday. Round 3 starts at 16.65 (about 11:34); the 150 P arrives at 16.7.
- The 21.0 test and the Final duels (21.65) fall after Sunday's close unless the organisers re-time them.

### Ranked moves

| # | Move | Who |
|---|---|---|
| 1 | Complete pages with TEAM buys. Latina (9 of 10): LAT-09 from a team (trades at 64 to 70; about +65 surplus at 85). Lavapiés: LAV-09 from Chato first (value 112; fills his slot 3) then LAV-10 from a team as the last card (about 218). Rule: any source for the second-to-last card; a team for the last one. Each spend needs Hector's yes | Hector decides; conductor executes |
| 2 | Broker: v20 stays on policy stall; read the log for matched and dropped right after hour 7.0 (first live match POST); judge by session efficiency. Four sessions tonight take market to about 5.9. No work on beating the stall | Mini conductor |
| 3 | Pilar: Hector's session's run (bus #5969014885): MAL-07 (held) and asset 44 with floor 18 / anchor 27 / step 1 / max 40 rounds / resume thread 870; then RET-06; then MAL-06. First three deals per dealer are final | Mini conductor |
| 4 | Team trades: buy below our value on El Rastro by default (a buy on a rival's venue gives its owner venue points: our SAL-01 buy gave t10 about +4.3); stop selling spare commons (232 listings and 0 fills) | Mini conductor |
| 5 | Venue traffic: ads alone bring nothing (v03 / v06 / v05 / v19 posted 16 to 33 announcements with 0 trades). The top venues have cross-listing (t05 put 131 listings on t10's venue and t10 put 53 back). Thiago and Hector agree a cross-listing swap with another team in the room; ads for live v20 offers only as a cheap extra with Hector's yes | Thiago and Hector |
| 6 | Duels: no `agent/duel.py` changes tonight (PR #33 not mergeable); tuning through params only after #33 merges; set `--until` past the Duels II end. Duels I: 25 deals of 31 finished plus duel 2587 after the resume | Duel bot owner |

Standing dealer rules: targeted single deals; explicit `--reserve` / `--only` / `--cap` / `--max-deals 1`; never `--max-bid` below `--cap` (the bot goes silent and walks from in-limit deals); start a dealer run only with the clock running and no live duel; never pay above our private value; no dealer deals past the first three. PRs #35 and #34 are in fix rounds and not yet available.

Sunday: before hour 16.65 finish round 2 (Pilar / Chato slot 3 / page buys / the two carried tests). Round 3 ladder deals start at 16.65.
