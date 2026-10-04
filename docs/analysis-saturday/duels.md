# Duels I audit: Team 3 (t03), snapshot 13:25 Sat 3 Oct (tick 630)

Source: Team 3 lunch review, Sat 3 Oct 2026, frozen copy of the Mini at commit fa91372, tick 630.

Read-only audit of `agent/duel.py` against its own Saturday logs. Every line number refers to `agent/duel.py` (1458 lines) in the frozen 13:25 snapshot. Labels: **MEASURED** (the script that produced it is named; all scripts and outputs sit next to this file) or **INFERRED** (reasoning or simulation, not observed on the server).

## 0. Live flag (act before 14:00)

- The running bot was started with `--until 14:00`. The game clock is paused at tick 630 (feed `clock.changed paused` at 13:24:57) with 3 of our duels still live: 2397 (silent rival), 2583 (silent rival) and 2587 (we sell at cost 78, rival at 82 and still conceding). Their deadlines are ticks 632, 635 and 640, so they need about 5 more minutes of play. The `--until` check runs at the top of the loop whether or not the clock is paused: at 14:00 the bot exits, deletes `results/duel.lock`, and any duel still open gets no accept. If the clock has not resumed by about 13:55, extend the run or restart it. MEASURED (results/duel-sat.out tail, logs/feed/feed.jsonl, results/duel.lock).
- The 18:32 estimate for Duels II slides by however long this pause lasts. INFERRED.

## 1. Claims from the previous session

| claim | verdict | evidence |
|---|---|---|
| 34 seen, 31 finished, 25 deals | CONFIRMED exactly: 25 deals + 6 no-deals = 31 finished, 3 live | MEASURED, scorecard.py |
| first three deals +61, +51, +4 | CONFIRMED: 2328 +61, 2329 +51, 2314 +4 (all deadline 475) | MEASURED, scorecard.py |
| "the bot accepts every inside-limit offer in the last ticks" | CONFIRMED: 21/21 of our accepts were endgame-window accepts at 1 to 3 ticks left, 0 early accepts, 0 "instead of sending" accepts, all 21 taken in the late read. No finished duel ended with an inside-limit offer unaccepted | MEASURED, scorecard.py, deep.py |
| duel_points 14.8 | NOT VERIFIABLE here: the last `me.json` in the snapshot is from 10:03 (duel_points 0.0) and the leaderboard has no duel field | logs/state/me.json, logs/score.jsonl |
| negotiating stalled 12:20 to 13:00 | CONFIRMED on the leaderboard: 16.08 at 12:15, then 14.36 to 15.68 until 13:00, 16.86 at 13:05 and flat to 13:25 | MEASURED, score_timeline.py |
| "value decays per tick" (brief) | WRONG: decay is per round of talk. The server's `result` equals surplus x 0.94^rounds in 25/25 deals. Waiting silently costs nothing | MEASURED, scorecard.py |

## 2. Scorecard

Per duel. The rival's limit is never shown, so the pie is unknown. The only estimate is `pairL`: our own limit in the paired duel (ids N and N+1, same item, roles swapped, same rival team). Saturday shows it is a weak estimate (section 5, fix 2), so the soft-pie share column is indicative only (INFERRED). The agreement tick of the 4 deals where the rival accepted our offer is reconstructed from the result timestamp (INFERRED); the other 21 come from our accept events (MEASURED). Source: scorecard.py, make_tables.py.

| duel | role | item | rival | our limit | pairL | soft pie | status | price | how | agreed at tick (of 16) | surplus | after decay | rounds | soft-pie share | rival first > last | our offers (tick, price) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2314 | seller | El Mesón de la Cava | Verde | 64 | 79 | 15 | deal | 68 | we accepted | 15 | 4 | 3.8 | 1 | 0.267 | 45 > 68 | (4, 100) |
| 2315 | buyer | El Mesón de la Cava | Sol | 79 | 64 | 15 | deal | 72 | we accepted | 14 | 7 | 6.6 | 1 | 0.467 | 96 > 72 | (4, 50) |
| 2328 | seller | Mercado de la Paz | Sol | 91 | 146 | 55 | deal | 152 | we accepted | 13 | 61 | 61.0 | 0 | 1.109 | 114 > 152 | - |
| 2329 | buyer | Mercado de la Paz | Verde | 146 | 91 | 55 | deal | 95 | we accepted | 14 | 51 | 51.0 | 0 | 0.927 | 129 > 95 | - |
| 2336 | seller | El Mesón de la Cava | Verde | 80 | 135 | 55 | deal | 107 | we accepted | 13 | 27 | 25.4 | 1 | 0.491 | 45 > 107 | (5, 124) |
| 2337 | buyer | El Mesón de la Cava | Verde | 135 | 80 | 55 | deal | 111 | we accepted | 13 | 24 | 24.0 | 0 | 0.436 | 223 > 111 | - |
| 2360 | seller | La Heroína del Dos d | Rojo | 154 | 140 | -14 | deal | 186 | we accepted | 14 | 32 | 32.0 | 0 | - | 93 > 186 | - |
| 2361 | buyer | La Heroína del Dos d | Sol | 140 | 154 | -14 | deal | 106 | we accepted | 14 | 34 | 34.0 | 0 | - | 158 > 106 | - |
| 2368 | seller | Palacio de Cristal | Oro | 78 | 95 | 17 | no_deal | - | - | - | - | 0.0 | 1 | - | 51 > 51 | (4, 121), (14, 85) |
| 2369 | buyer | Palacio de Cristal | Sol | 95 | 78 | 17 | no_deal | - | - | - | - | 0.0 | 0 | - | silent | (4, 77), (14, 87) |
| 2370 | seller | Mercado de la Paz | Noche | 122 | 153 | 31 | no_deal | - | - | - | - | 0.0 | 0 | - | silent | (4, 149), (14, 132) |
| 2371 | buyer | Mercado de la Paz | Azul | 153 | 122 | 31 | deal | 83 | we accepted | 13 | 70 | 70.0 | 0 | 2.258 | 97 > 83 | - |
| 2384 | seller | Café en Goya | Verde | 75 | 174 | 99 | deal | 92 | we accepted | 14 | 17 | 17.0 | 0 | 0.172 | 74 > 92 | - |
| 2385 | buyer | Café en Goya | Rojo | 174 | 75 | 99 | deal | 140 | we accepted | 14 | 34 | 34.0 | 0 | 0.343 | 164 > 140 | - |
| 2394 | seller | La Heroína del Dos d | Azul | 99 | 138 | 39 | deal | 109 | we accepted | 15 | 10 | 10.0 | 0 | 0.256 | 76 > 109 | - |
| 2395 | buyer | La Heroína del Dos d | Noche | 138 | 99 | 39 | deal | 127 | we accepted | 14 | 11 | 11.0 | 0 | 0.282 | 176 > 127 | - |
| 2396 | seller | El Mesón de la Cava | Sol | 136 | 111 | -25 | no_deal | - | - | - | - | 0.0 | 0 | - | silent | (4, 166), (14, 147) |
| 2397 | buyer | El Mesón de la Cava | Noche | 111 | 136 | -25 | live | - | - | - | - | - | 0 | - | silent | (4, 90) |
| 2398 | buyer | Café en Goya | Sol | 151 | 53 | 98 | deal | 127 | we accepted | 13 | 24 | 22.6 | 1 | 0.245 | 156 > 127 | (6, 97) |
| 2399 | seller | Café en Goya | Plata | 53 | 151 | 98 | deal | 66 | we accepted | 13 | 13 | 12.2 | 1 | 0.133 | 52 > 66 | (6, 83) |
| 2412 | seller | El Mesón de la Cava | Noche | 99 | 50 | -49 | deal | 115 | we accepted | 15 | 16 | 16.0 | 0 | - | 86 > 115 | - |
| 2413 | buyer | El Mesón de la Cava | Verde | 50 | 99 | -49 | no_deal | - | - | - | - | 0.0 | 0 | - | silent | (4, 40), (14, 46) |
| 2436 | seller | Mercado de la Paz | Sol | 96 | 181 | 85 | deal | 118 | rival accepted ours | 14 (inferred) | 22 | 22.0 | 0 | 0.259 | silent | (4, 118), (14, 104) |
| 2437 | buyer | Mercado de la Paz | Rojo | 181 | 96 | 85 | deal | 148 | rival accepted ours | 12 (inferred) | 33 | 33.0 | 0 | 0.388 | silent | (4, 148) |
| 2458 | seller | Café en Goya | Azul | 87 | 165 | 78 | deal | 101 | we accepted | 13 | 14 | 13.2 | 1 | 0.179 | 60 > 101 | (12, 135) |
| 2459 | buyer | Café en Goya | Azul | 165 | 87 | 78 | deal | 130 | we accepted | 13 | 35 | 35.0 | 0 | 0.449 | 174 > 130 | - |
| 2498 | seller | El Mesón de la Cava | Verde | 51 | 125 | 74 | deal | 56 | rival accepted ours | 15 (inferred) | 5 | 4.4 | 2 | 0.068 | 39 > 39 | (4, 80), (14, 56) |
| 2499 | buyer | El Mesón de la Cava | Noche | 125 | 51 | 74 | deal | 115 | rival accepted ours | 15 (inferred) | 10 | 8.8 | 2 | 0.135 | 157 > 157 | (4, 80), (14, 115) |
| 2500 | seller | La Heroína del Dos d | Rojo | 135 | 120 | -15 | deal | 166 | we accepted | 14 | 31 | 31.0 | 0 | - | 136 > 166 | - |
| 2501 | buyer | La Heroína del Dos d | Azul | 120 | 135 | -15 | deal | 102 | we accepted | 14 | 18 | 18.0 | 0 | - | 120 > 102 | - |
| 2582 | seller | Palacio de Cristal | Plata | 79 | 56 | -23 | no_deal | - | - | - | - | 0.0 | 0 | - | silent | (4, 97), (14, 86) |
| 2583 | buyer | Palacio de Cristal | Rojo | 56 | 79 | -23 | live | - | - | - | - | - | 0 | - | silent | (4, 45) |
| 2586 | buyer | El Mesón de la Cava | Rojo | 129 | 78 | 51 | deal | 104 | we accepted | 14 | 25 | 25.0 | 0 | 0.49 | 137 > 104 | - |
| 2587 | seller | El Mesón de la Cava | Noche | 78 | 129 | 51 | live | - | - | - | - | - | 0 | - | 50 > 53 | - |

| total | value |
|---|---|
| duels seen / finished / live | 34 / 31 / 3 |
| deals / no-deals | 25 / 6 |
| deal rate | 80.6% |
| surplus, sum / mean per deal | 628 P / 25.1 P |
| surplus as share of our limit, mean | 0.212 |
| after decay (server `result`), sum | 621.0 P |
| lost to decay | 7.0 P (10 rounds in 8 deals) |
| soft-pie share, mean / median (n 20, pie from pairL, weak) | 0.468 / 0.312 |
| deals by our accept / by rival accepting our offer | 21 / 4 |

Agreement timing: the 25 deals were agreed at tick 12 (1), 13 (8), 14 (11) and 15 (5) of 16 (the 4 rival-accepted ones INFERRED); rounds per deal 0 (17), 1 (6), 2 (2). MEASURED, scorecard.py.

## 3. No-deals: causes

| cause | count | duels |
|---|---|---|
| rival silent the whole duel (no message, no offer); our two offers not accepted | 5 | 2369, 2370, 2396, 2413, 2582 |
| rival never inside our limit (opened 51 against our cost 78 and never moved) | 1 | 2368 |
| we held too long | 0 | - |
| accept lost to one-accept-per-tick or the lock | 0 | 0 refused, 0 accept_skipped, 0 errors in the whole run |
| bot not running, or a bug | 0 | every duel was seen at its first tick (34/34) |

MEASURED, deep.py section C, timing.py. Silent rivals overall: 7 of 31 finished duels. 2 of those 7 accepted our first offer (2436 at 1.23 x cost, 2437 at value / 1.22). The other 5 never accepted our offers at about 1.22 x L and then about 1.08 x L (buyer side: L / 1.22, then L / 1.08). Silence clusters by rival team: 3 pairs had both duels silent and 3 had one (confound.py).

## 4. Early versus late

| split (by duel start) | duels | deals | deal rate | mean surplus | surplus / our limit | soft-pie share | silent rivals |
|---|---|---|---|---|---|---|---|
| first half, start before tick 533 | 15 | 13 | 0.87 | 27.2 | 0.239 | 0.472 | 2 |
| second half, start from tick 533 | 16 | 12 | 0.75 | 22.9 | 0.183 | 0.464 | 5 |
| start 12:00 to 12:20 | 9 | 9 | 1.00 | 25.7 | 0.248 | 0.514 | 0 |
| start 12:20 to 13:00 | 17 | 13 | 0.76 | 23.4 | 0.191 | 0.435 | 4 |
| start from 13:00 | 5 | 3 | 0.60 | 31.0 | 0.196 | 0.442 | 3 |

MEASURED, deep.py section E (share column INFERRED).

- **The bot did not get worse.** One process with one parameter set ran the whole session from 11:26. With rivals that spoke, it closed 12 of 13 early and 11 of 11 late. MEASURED, confound.py.
- **The rival teams changed, not their tactics.** Each pair is one rival team, so the two halves are different teams, not the same teams adapting. All three fully silent pairs (2396/2397, 2436/2437, 2582/2583) started after tick 520. With rivals that spoke, surplus / L fell from 0.240 to 0.183 (median 0.202 to 0.161). The first half also holds the outlier pair 2328/2329 (112 P). By item, the drop shows in 3 of the 4 items that closed. MEASURED; "later teams were firmer" is INFERRED.
- **The 12:20 to 13:00 stall** lines up with four no-deals (2368, 2369, 2370, 2413) settling in that window while new duels opened. The leaderboard dips when duels open with nothing settling (tick 470: 10.26 to 8.11 with 3 live and 0 settled; tick 500: 16.08 to 14.36) and rises when deals settle. That fits a duel component averaged over duels begun, with live duels counted as zero. MEASURED timeline, INFERRED mechanism (score_timeline.py). The flat 16.86 from tick 590 to 630, while 5 deals and 2 no-deals settled, is unexplained.

## 5. Money left on the table

- **Decay cost 7.0 P of 628 (1.1%)**, all from our own messages sent after a rival message (10 rounds in 8 deals). Waiting silently costs no decay, so there were 0 cases where waiting cost more in decay than it gained. One round costs 8% in Duels II and 10% in Duels III. MEASURED, scorecard.py.
- **One wasted round:** 2458 anchored 135 at tick 12 with the rival stalled at 101, then accepted that same 101 at tick 13 (0.84 P). MEASURED, scorecard.json.
- **Accepting while the rival still conceded:** 16 of our 21 accepts came while the rival had moved within the last 3 ticks. If each rival had kept its recent rate until deadline-1, the upper bound is 146 P (23% of our surplus). INFERRED, deep.py section A. Much of it is bound by the accept slot: 18 of the 21 had another of our duels with a deadline within 2 ticks (some of those neighbours had already settled), and the hold reasons show actual slot-queue waits in 5 duels (2329, 2394, 2395, 2412, 2500). One accept per tick means a cluster of N open duels needs N ticks. MEASURED (deadlines, hold reasons).
- **The recoverable part:** 7 deals were taken at 2 ticks left because window-wait keeps deadline-1 as a retry tick (`allocate`, line 586): 2315, 2360, 2361, 2384, 2385, 2501, 2586. Upper bound for taking them at deadline-1 instead: 29.8 P, about 4.3 P per duel. Three others at 2 ticks left (2329, 2395, 2500) waited for the slot and would not change. INFERRED, fix3.py. Risk evidence: 3 of 3 of our deadline-1 accepts settled (2314, 2394, 2412), with 0 accept_skipped and 0 refused. MEASURED.
- **The late read is load-bearing:** 13 of 21 accepts took an offer that only the late read saw (48 of 227 rival offer changes were first seen there). MEASURED, timing.py.
- **Order inside a cluster:** `allocate` sorts acceptable offers by biggest surplus first (line 590), so in the deadline-475 cluster 2328 (rival rising 4.5 P per tick) went first at 3 ticks left. Taking stalled rivals first and fast movers last is worth a few P per cluster. INFERRED, small.

## 6. Two-issue readiness for Duels II (18:32)

### What the code does

- `two_issues` keys on "days" in `issues`. Our utility is the price surplus minus `w x |days - best|` (`days_cost`, `surplus`). An accept needs the price inside our limit and total utility of at least MIN_SURPLUS (`decide`, line 478). Offers name an extreme day and trade days when they are cheap for us (`planned_offer`, lines 330 to 361). The price-only pairL clamps are skipped for two issues (`our_number`, line 378).
- The SDK's `duel_say` sends a top-level "price" plus "offer": {"price", "days"}, never a top-level "days" (kit/bazaar_sdk.py lines 290 to 293). The rules accept price plus days, or both inside "offer". We have never sent this shape to a two-issue session.
- **It has never run against real two-issue data.** All Friday and Saturday duel files have `issues` ["price"]. Only the offline arena has exercised it. MEASURED.
- Offline runs: the two-issue path runs without errors; selftest PASS (price-only, 301 simulated duels and 20,000 fuzzed states, 0 limit violations). Live params, tuned and tuned+10 score 0.267, 0.261 and 0.262 per duel over 100 Duels II sessions, so the arena cannot pick between them. MEASURED in simulation, arena_s2.out, stress_guard.out.

### Risks, ranked

1. **Days direction double-count** (`days_profile`, lines 197 to 225). The negative-weight flip at lines 223 to 224 runs after `days_meaning` has already set the direction. If the server sends signed weights (buyer negative means later costs) together with a meaning string that names the direction, the buyer's best day flips to 10. In simulation the mean score per duel fell from 0.275 to 0.210 (minus 24%), and 543 of 6,800 duels (8%) closed below our true limit. MEASURED in simulation (stress_sign.py). Whether the server signs weights is unknown.
2. **The override is global** (line 210, flag at line 790). `--days-best 0` sets day 0 for the buyer AND the seller, so it cannot correct one role. In the signed-weight world it made things worse: 659 below-limit deals. MEASURED in simulation.
3. **The arena is circular.** It gives the bot `days_meaning` strings written to match the bot's keywords, plus the bot's own convention (tools/duel_arena.py lines 420 to 421 and 462 to 463), so it cannot catch a wrong guess. MEASURED (read). Like-for-like in a world where sellers also want early delivery and the meaning string is neutral: 0.313 with the role default versus 0.365 with the right setting, and 165 of 4,080 deals (4%) below our limit. MEASURED in simulation (stress_two_issue.py).
4. **Message shape:** if the server reads the top-level price first, every priced message is refused with `missing_days`. The bot logs `refused` and stays silent, which loses the deals that come from rivals accepting our offer (4 of 25 on Saturday). INFERRED.
5. **`planned_offer` far-day logic** (lines 349 to 350). If the rival names OUR best day, `far` stays at the opposite day. When days are cheap for us, we then offer the day neither side wants and add a price premium. INFERRED from reading; the arena's rivals never want our day, so this is untested.
6. **pairL parity can flip** and silently switch early accept on. See fix 2.
7. **Weight unit:** the code assumes primas per day (the arena uses 0 to 4 P per day). If the weight is a fraction of price, the cheap/dear split misfires. INFERRED.
8. **Slot pressure:** up to 6 duels at once versus a measured maximum of 3 live per tick in Duels I (concurrency.py). The selftest leaves 15 of 600 acceptable offers unaccepted at 6 concurrent, versus 5 of 600 at 3. MEASURED in simulation.

**Operator check at the first Duels II duels:** read the `duel_new` line of the first buyer AND the first seller duel. Check the raw `days_meaning` and the sign of `days_weight`. If a buyer weight is negative and the meaning says later costs, the bot has flipped the buyer the wrong way: stop it and apply fix 1. Also check the first `say` for `refused` with `missing_days`.

## 7. Tick-rate readiness (Sunday: 15 s ticks, duel_ticks 12, max_concurrent 4)

| setting | where | derived or fixed | at 15 s |
|---|---|---|---|
| poll between ticks | line 907: min(10, max(0.5, next_tick_in + 0.4)) | derived from next_tick_in | OK |
| retry after a clock error | line 904: sleep 5 s | fixed | a third of a tick, OK |
| tick end for the late read | `tick_left`, lines 678 to 684 | derived from tick_seconds (falls back to 30) | OK |
| late read time | `late_poll` 8 s in the params file, used at line 698 | fixed seconds, tuned for 30 s ticks | reads 7 s into a 15 s tick and misses rivals that post later: set 4 |
| late read retries | lines 707 to 715: 1 s sleeps, stop with under 2 s left | fixed | OK |
| late read kill switch | lines 1045 to 1046: 2 failed late reads in a row set `late_poll` to 0 for the rest of the run, never re-enabled | fixed | sharper at 15 s, because almost every tick gets a late read |
| lock expiry | `write_lock`, lines 617 to 631: lock_ticks 3 x max(5, tick_seconds) | derived | 45 s, OK |
| gap between POSTs | post_gap 0.25 s | fixed | 4 duels fit in 5 requests per second |
| duel length | `duel_ticks` 16 default (line 134), used by `DuelState.total` (line 406) | fixed by param | MUST be 12. At 16 the bot thinks each duel began 4 ticks early, so `absent_from` (line 491) fires on the first tick with the live absent_at 0.2, and at real tick 5 of 12 with the tuned 0.552 |
| accept window, stall, last chance | accept_any_ticks, stall_ticks, last_chance_ticks | tick counts | scale with the clock; the arena's session 3 models 12-tick duels |
| `--until` | lines 875 to 878 | wall clock, per run | must cover each session |
| `--idle-ticks` 40 | line 941 | tick count | 40 x 15 s is 10 min, so the run exits between Duels III (hour 18.65) and the Final (hour 21.65): start a fresh run for the Final |

Measured at 30 s: first reads 30 s apart (median), late accepts 21 s after the first read (range 18 to 22), every duel seen at its first tick. MEASURED, timing.py. Verdict: it works at 15 s with three param changes (duel_ticks 12, late_poll 4, a fresh run for the Final). INFERRED; it has never run at 15 s.

## 8. Ranked fixes

| # | change | evidence | expected effect | risk |
|---|---|---|---|---|
| 1 | `days_profile` (lines 197 to 225): apply the negative-weight flip (lines 223 to 224) only when `days_meaning` matched no keyword, and make `--days-best` role-aware (line 210 and the flag at line 790), for example "buyer:0,seller:10" | stress_sign.py, stress_two_issue.py; no real two-issue data yet | protects about 24% of the duel score across Duels II, III and the Final (170 duels) if the server signs weights; zero effect if the current guess is right | low: two small edits, selftest covers it |
| 2 | Add "early_share": 99 to the Duels II params file (no code). Optional: make `mirror_limit` (line 303) check both neighbours, for logging only | Friday pairs were (odd, odd+1); all Saturday pairs were (even, even+1), so pairL was found 0/34 times and early accept never fired. If Duels II parity flips, early accept switches on with an estimate that matched the deal price within 7% in only 2 of 25 Saturday deals. Replaying Duels I with pairL found: minus 20 P (2328 minus 6, 2371 minus 14). Arena with Saturday-like noise: 0.2589 versus 0.2636 with early accept off | avoids about minus 20 P per 34 duels if the parity flips. The pin is partial: the thin-anchor test in `decide` still uses the same pie as its reference (`ref = pie`, line 502), so one anchor message can still go out against a bad estimate | none: it never fired on Saturday |
| 3 | `allocate` line 586: behind a flag, hold while `tight < left` instead of `left - 1`, so a lone duel whose rival still concedes takes deadline-1 | 7 deals (2315, 2360, 2361, 2384, 2385, 2501, 2586); 3 of 3 deadline-1 accepts settled; fix3.py | up to plus 29.8 P per 34 duels (upper bound, about 4.3 P per affected duel) | medium: no retry tick. Pays only if fewer than 14.6% of deadline-1 accepts fail at the upper bound, 7.8% if rivals deliver half that |
| 4 | Sunday params: "duel_ticks": 12 and "late_poll": 4; a fresh run for the Final; `--until` per session | lines 406, 491, 698, 941; 13 of 21 accepts depended on the late read | keeps the late-read gain and the listen-first opening at 15 s | low |
| 5 | Watch the first Duels II `say` for `refused` / `missing_days`; if it appears, send top-level "days" as well on the say path (line 1026) | kit lines 290 to 293 | protects the deals rivals make by accepting our offer (4 of 25 on Saturday) | low |
| 6 | `planned_offer` lines 349 to 350: when the rival gives a day, set `far` to it, even when it equals our best day | read only | removes an offer that destroys value; size unknown on the real field | low |
| 7 | Rivals that never spoke: a deeper last chance (last_r 1.08 down to about 1.04) | 5 silent no-deals; 2 of 7 silent rivals accepted our first offer | a few P per converted duel, possibly 0 if those bots are dead | low |
| 8 | `decide` line 497: no anchor within one tick of the accept window | 2458 | about 0.8 P per case at 6% decay, more at 8 to 10% | low |

**Param set for 18:32.** The team's own rule (docs/duel-lab/duels2-params.md) picks tuned+10 when (1) a deadline-1 accept settled and (2) the late read works. Both are MEASURED true: 3 of 3 and 13 of 21. The arena cannot separate the three sets (within 0.006 per duel). Add fix 2's "early_share": 99. Duels I ran at most 3 live duels per tick and took 171 ticks for 34 duels. 68 duels at up to 6 live is about the same number of ticks if the server fills 6 slots, so roughly 18:32 to 20:00 at 30 s ticks. INFERRED. `--until 21:00` covers that unless the pause or the concurrency differ; `--until 23:00` costs nothing.

## 9. Not verifiable from the snapshot

- duel_points (the claimed 14.8) and the true per-duel pie share. Poll `/api/me` every tick during Duels II and log the duel_points change at each settlement; that makes per-duel share measurable.
- Whether the server signs `your_days_weight`, and its `days_meaning` wording: visible only in the first Duels II duel.

## 10. Scripts and outputs (this folder)

| script | output | answers |
|---|---|---|
| scorecard.py | scorecard.out, scorecard.json | per-duel table, totals, decay check, pairL parity |
| make_tables.py | tables.md | the tables in section 2 |
| deep.py | deep.out | accept timing, hold reasons, no-deal causes, halves, pairL as an estimate |
| confound.py | confound.out | silence by pair, halves by item |
| clusters_pairl.py | clusters_pairl.out | deadline clusters, pairL counterfactual |
| fix3.py | fix3.out | deadline-1 subset and break-even |
| score_timeline.py | score_timeline.out | leaderboard negotiating against settlements |
| timing.py | timing.out | in-tick timing, late-read usage, refusals |
| concurrency.py | concurrency.out | live duels per tick |
| stress_two_issue.py | stress_two_issue.out | days convention and pairL stress (arena, offline) |
| stress_guard.py | stress_guard.out | worst-case days guard, param-set comparison |
| stress_sign.py | stress_sign.out | signed-weight double flip |
| codex_check.py | codex_check.out | the four Codex findings, teammate claims, F3 context |
| tools/duel_arena.py (sandbox copy) | arena_s2.out | Duels II arena, three param sets |

The arena and selftest ran on a scratch copy (`sandbox/`, snapshot without logs or .env). Nothing under the snapshot was modified, and no network or key was used.

## 11. Done check

- 25 deals + 6 no-deals = 31 finished, plus 3 live = 34 seen. That matches the claimed 34 seen, 31 finished and 25 deals. MEASURED.
- scorecard.py re-run from a clean shell (env -i, system Python 3.9.6) reproduces scorecard.out byte for byte; make_tables.py reproduces tables.md; the other analysis scripts run clean on the same interpreter. MEASURED.

## 12. Codex findings (verified offline, codex_check.py)

Each finding was reproduced by importing `duel.py` from the scratch copy and driving it with a fake server object (no network, no key). Saturday columns come from the decision log. MEASURED unless marked.

| # | finding | verdict | offline repro | Saturday logs | fix |
|---|---|---|---|---|---|
| 1 | Accept race: the bot re-reads, approves, then POSTs accept; a replaced offer is accepted as it stands | CONFIRMED in both paths (main loop lines 996 to 1005, `late_pass` lines 744 to 749). `duel_accept(duel_id)` takes no offer id or price (kit/bazaar_sdk.py line 296) and RULES line 91 has no body for the accept, so the call cannot pin an offer | buyer limit 100, weight 3: approved (90, day 0), server accepted (99, day 10), true surplus -29, bot logged a normal `accept` | not observed: in 21 of 21 accepts the server's response price equalled the approved price | Prefer accepting an offer the rival posted in the current tick: one message per conversation per tick (RULES line 109) means it cannot be replaced before the tick ends (INFERRED). Compare the response price and days with the approved offer and raise an alarm on a mismatch |
| 2 | Allocator picks the small deal and lets the big one expire | CONFIRMED (`allocate` lines 589 to 593) whenever more duels need the slot than ticks remain | both at deadline-1, surplus 50 and 5: accepts the 5, the 50 expires. Three at deadline-2 (50, 30, 5): takes the 5 first, so the 50 expires next tick. With enough ticks (both at deadline-2) it is correct | not observed: at most 2 acceptable duels competed in any tick, and none at deadline-1. Up to 6 live duels in Duels II makes it likelier | when duels outnumber ticks left, keep the highest-surplus set that fits (greedy by surplus into the latest free tick) and accept the one that must go now |
| 3 | `late_pass` skip wastes the tick's accept | CONFIRMED (line 746, same pattern at line 1001): a changed offer id logs `accept_skipped`, and the duels the allocator held stay held | two acceptable duels at deadline-1, the chosen rival IMPROVES its offer: 0 accepts sent, both expire. At 2 ticks left the tick's accept is wasted | not observed: 0 `accept_skipped` events | on a changed id, re-run `decide` on the fresh offer and accept it if still acceptable; otherwise fall through to the next queued duel |
| 4 | Duration defaults to 16 ticks | CONFIRMED: `DuelState.total` (line 406) uses `cfg.duel_ticks` (default 16, line 134). Nothing reads the duration from the payload (it has no start tick) or from `/api/schedule`. The live params file does not set it, and both Duels II tuned files hard-code 16 | a 12-tick duel seen at its first tick, rival not yet spoken: with 16 the bot places the start 4 ticks early and sends its absent-rival offer (122 against cost 100) at real tick 0; with 12 it listens | not applicable: Duels I and II are 16-tick sessions (34 of 34 duels seen with 16 ticks). It bites on Sunday (Duels III and Final, 12 ticks) | "duel_ticks": 12 in the Sunday params, or read `duel_ticks` from the schedule; the feed's `duels.scheduled` event carries it (16 for Duels I) |

**Teammate claims and proposals**

- "3 of 3 deadline-minus-1 accepts settled": SUPPORTED (2314, 2394, 2412 all deals).
- "48 late=True lines": SUPPORTED for rival lines (48). All late=True lines total 69, because the 21 accepts are tagged too.
- F1, hold while the rival still concedes: SUPPORTED in part. 16 of 21 accepts came while the rival was still conceding, but the safe gain is lone duels moving to deadline-1 (7 duels, at most 30 P). Holding inside a deadline cluster makes Codex findings 2 and 3 bite: fix those first.
- F2, a last offer to silent rivals strictly inside our limit: WEAK support. The 5 silent no-deals never accepted 1.08 x L, and 2 of 7 silent rivals took our first offer. Upside is a few P per converted duel. In two-issue sessions "inside" must use surplus after days cost, not price alone.
- F3, open at rung 1 with both issues: NO direct data (Saturday was price-only and we never opened to a rival that spoke). 17 of 25 deals came at 0 rounds with the bot silent. 10 of 25 deals closed better than a 1.22 opening and 2 of 25 better than a 1.55 opening; an opening is a standing offer the rival can accept at once, so an opening at 1.22 would have capped those 10.
