# Duels III overnight search: leaderboard

Refreshed 2026-10-04 01:27 UTC. Candidates scored: 411 on train (200 sessions x 4 worlds), 27 on select (600 sessions x 4 worlds), 0 on TEST (2000 sessions x 4 worlds). Deltas are each candidate minus the incumbent on the same sessions (mean score per duel: share of the pie x 0.9^rounds, 0 without a deal), ± one SE unless marked 2 SE.

**Acceptance rule.** A candidate replaces the incumbent (`docs/duel-lab/duel-params-duels3.json`) only if,
on the TEST seeds (900000..): (1) it beats the incumbent in the main world (Duels III, Duels II field refit plus
self-play) by more than 2 SE of the paired per-session difference; (2) it is not worse than the incumbent by more
than 2 SE against any rival type, both in `tools/duel_matrix.py --session 3` (17 rival rows) and in our own
per-type split of the main world (which adds the self-play rival); (3) in the D-1 stress (an accept sent with one
tick left never settles, 15 s ticks) its mean is no more than 0.03 below the incumbent's; (4)
`python3 agent/duel.py selftest --params <file>` passes. Otherwise it stays here as "not better".

Worlds: **main** = Duels III (68 duels, 12 ticks, decay 0.10, 4 at once), the Duels II field refit (68 real duels: linear 28, oneshot 11, steady 8, fast 8, tft 5, absent 5, silent 3) plus a copy of duel.py with the incumbent params at weight 8 (10.5 %); **drift** = main with 20 % of the mix moved to deadline-concede and mute (silent, absent) rivals; **final** = the Grand Final's single round (34 duels); **D-1** = main where an accept at deadline-1 never settles. Training objective = 0.5 main + 0.15 drift + 0.15 final + 0.2 D-1 (the D-1 stress is in it because the biggest raw gains of the first sweep all came from accepting at deadline-1); candidates more than 0.03 worse in D-1 are never parents or finalists.

## Best on select (seeds 500000.., 600 sessions)

| # | candidate | what it changes | objective Δ | main | drift | final | D-1 | train objective |
|---|---|---|---|---|---|---|---|---|
| 1 | R5 `93237dd7f5` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, thin_frac=0.17, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253] | +0.0089 ±0.0005 | +0.0097 ±0.0006 | +0.0106 ±0.0006 | +0.0086 ±0.0009 | +0.0060 ±0.0007 | +0.0103 ±0.0009 |
| 2 | R7 `8ff9901062` | ratios=[1.743, 1.306], last_r=1.117, max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, near_ticks=1, thin_frac=0.17, early_share=1, absent_at=0.148, absent_share=0.644, days_cheap=0.135, days_premium=[1.072, 0.253] | +0.0076 ±0.0006 | +0.0085 ±0.0007 | +0.0073 ±0.0007 | +0.0077 ±0.0009 | +0.0058 ±0.0008 | +0.0096 ±0.0009 |
| 3 | R6 `7119809c1e` | ratios=[1.743, 1.306], last_r=1.117, max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, near_ticks=1, thin_frac=0.17, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253] | +0.0076 ±0.0006 | +0.0082 ±0.0006 | +0.0080 ±0.0007 | +0.0077 ±0.0009 | +0.0057 ±0.0007 | +0.0091 ±0.0009 |
| 4 | R5 `1c51ed5da0` | ratios=[1.743, 1.306], max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, stall_ticks=2, thin_frac=0.129, absent_at=0.148, days_premium=[1.072, 0.253], min_surplus=2 | +0.0072 ±0.0005 | +0.0075 ±0.0006 | +0.0078 ±0.0006 | +0.0067 ±0.0009 | +0.0064 ±0.0008 | +0.0080 ±0.0009 |
| 5 | R5 `8cf644380e` | last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.17, absent_at=0.148, days_premium=[1.33, 0.253] | +0.0072 ±0.0005 | +0.0070 ±0.0006 | +0.0058 ±0.0006 | +0.0070 ±0.0008 | +0.0087 ±0.0007 | +0.0081 ±0.0009 |
| 6 | R6 `aa8b331e3a` | ratios=[1.743, 1.306], max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, thin_frac=0.17, absent_at=0.148, days_premium=[1.638, 0.253] | +0.0070 ±0.0005 | +0.0076 ±0.0006 | +0.0083 ±0.0006 | +0.0070 ±0.0008 | +0.0046 ±0.0007 | +0.0083 ±0.0008 |
| 7 | R4 `5226405669` | ratios=[1.743, 1.306], max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, thin_frac=0.17, absent_at=0.148, days_premium=[1.072, 0.253] | +0.0070 ±0.0005 | +0.0076 ±0.0006 | +0.0082 ±0.0006 | +0.0069 ±0.0008 | +0.0046 ±0.0007 | +0.0083 ±0.0008 |
| 8 | R2 `00bfa973ab` | accept_any_ticks=3, thin_frac=0.623, days_cheap=0.117, days_premium=[1.33, 0.365] | +0.0067 ±0.0005 | +0.0124 ±0.0006 | +0.0088 ±0.0006 | +0.0133 ±0.0009 | -0.0141 ±0.0010 | +0.0069 ±0.0009 |
| 9 | R6 `3ba7c0c274` | ratios=[1.743, 1.306], max_msgs=4, last_chance_ticks=3, accept_any_ticks=5, thin_frac=0.17, absent_at=0.148, absent_share=0.61, days_premium=[1.072, 0.253], min_surplus=5 | +0.0066 ±0.0005 | +0.0077 ±0.0006 | +0.0074 ±0.0006 | +0.0065 ±0.0009 | +0.0033 ±0.0007 | +0.0078 ±0.0009 |
| 10 | R2 `bb2e83e65e` | accept_any_ticks=4, thin_frac=0.494, absent_share=0.473, min_surplus=2 | +0.0060 ±0.0004 | +0.0083 ±0.0005 | +0.0068 ±0.0004 | +0.0085 ±0.0007 | -0.0022 ±0.0006 | +0.0064 ±0.0007 |
| 11 | R1 `d69033e0ae` | accept_any_ticks=4, thin_frac=0.494 | +0.0054 ±0.0004 | +0.0076 ±0.0005 | +0.0065 ±0.0004 | +0.0076 ±0.0006 | -0.0025 ±0.0006 | +0.0059 ±0.0007 |
| 12 | R3 `1b4d3506e9` | ratios=[1.624, 1.262], accept_any_ticks=4, thin_frac=0.494, absent_share=0.473, days_premium=[1.33, 0.191], min_surplus=2 | +0.0047 ±0.0004 | +0.0073 ±0.0005 | +0.0045 ±0.0005 | +0.0071 ±0.0007 | -0.0032 ±0.0007 | +0.0053 ±0.0009 |
| 13 | R3 `bc3df6f67d` | last_chance_ticks=3, accept_any_ticks=5, thin_frac=0.17, absent_at=0.148, days_premium=[1.33, 0.253] | +0.0046 ±0.0005 | +0.0051 ±0.0006 | +0.0056 ±0.0006 | +0.0047 ±0.0008 | +0.0024 ±0.0007 | +0.0057 ±0.0008 |
| 14 | R2 `69c037fb25` | accept_any_ticks=4, days_premium=[1.33, 0.381] | +0.0045 ±0.0003 | +0.0065 ±0.0004 | +0.0055 ±0.0004 | +0.0065 ±0.0006 | -0.0030 ±0.0006 | +0.0046 ±0.0006 |
| 15 | S accept_any_ticks=4 `6bc71ed0cb` | accept_any_ticks=4 | +0.0043 ±0.0003 | +0.0064 ±0.0004 | +0.0054 ±0.0004 | +0.0064 ±0.0006 | -0.0031 ±0.0006 | +0.0043 ±0.0006 |
| 16 | S accept_any_ticks=3 `eff5b6a76f` | accept_any_ticks=3 | +0.0039 ±0.0004 | +0.0092 ±0.0005 | +0.0079 ±0.0005 | +0.0100 ±0.0007 | -0.0170 ±0.0009 | +0.0037 ±0.0008 |
| 17 | R2 `3a062140bd` | last_chance_ticks=3, accept_any_ticks=5, days_premium=[1.33, 0.394], min_surplus=4 | +0.0035 ±0.0004 | +0.0048 ±0.0005 | +0.0057 ±0.0005 | +0.0055 ±0.0007 | -0.0027 ±0.0006 | +0.0046 ±0.0006 |
| 18 | S accept_any_ticks=5 `ae03640e6a` | accept_any_ticks=5 | +0.0035 ±0.0003 | +0.0037 ±0.0003 | +0.0033 ±0.0003 | +0.0042 ±0.0004 | +0.0027 ±0.0004 | +0.0036 ±0.0004 |
| 19 | H-d endgame accept 5 / last chance 3 `153f0980b2` | last_chance_ticks=3, accept_any_ticks=5 | +0.0026 ±0.0003 | +0.0035 ±0.0004 | +0.0045 ±0.0004 | +0.0045 ±0.0006 | -0.0025 ±0.0005 | +0.0027 ±0.0005 |
| 20 | S min_surplus=5 `8c107e1e23` | min_surplus=5 | +0.0016 ±0.0003 | +0.0020 ±0.0004 | +0.0006 ±0.0004 | +0.0022 ±0.0005 | +0.0011 ±0.0004 | +0.0014 ±0.0005 |
| 21 | S min_surplus=3 `4b8c53769a` | min_surplus=3 | +0.0013 ±0.0002 | +0.0015 ±0.0003 | +0.0007 ±0.0003 | +0.0019 ±0.0003 | +0.0005 ±0.0003 | +0.0014 ±0.0004 |
| 22 | S prem1=0.0 `eb35b5dbbb` | days_premium=[1.33, 0] | +0.0008 ±0.0002 | +0.0010 ±0.0003 | +0.0001 ±0.0003 | +0.0010 ±0.0003 | +0.0011 ±0.0003 | +0.0015 ±0.0004 |
| 23 | S min_surplus=2 `3dd1326d15` | min_surplus=2 | +0.0008 ±0.0001 | +0.0010 ±0.0002 | +0.0004 ±0.0002 | +0.0010 ±0.0002 | +0.0006 ±0.0002 | +0.0008 ±0.0003 |
| 24 | S prem1=0.2 `3c70dd5e8f` | days_premium=[1.33, 0.2] | +0.0007 ±0.0001 | +0.0008 ±0.0002 | +0.0002 ±0.0002 | +0.0007 ±0.0002 | +0.0008 ±0.0002 | +0.0007 ±0.0003 |
| 25 | S floor=1.35 `9a729a3b77` | ratios=[1.624, 1.35] | +0.0003 ±0.0002 | +0.0003 ±0.0002 | +0.0008 ±0.0002 | -0.0000 ±0.0003 | +0.0002 ±0.0002 | +0.0006 ±0.0003 |

## Structured hypotheses (train)

| hypothesis | what it changes | objective Δ | main | drift | final |
|---|---|---|---|---|---|
| H-d endgame accept 5 / last chance 3 | last_chance_ticks=3, accept_any_ticks=5 | +0.0027 ±0.0005 | +0.0042 ±0.0006 | +0.0033 ±0.0007 | +0.0045 ±0.0009 |
| H-a open to a mute rival at tick 1 | absent_at=0.083 | +0.0003 ±0.0010 | -0.0004 ±0.0012 | -0.0002 ±0.0010 | -0.0008 ±0.0016 |
| H-a open at tick 1, mute last chance at L x (1 +- 0.15) | absent_at=0.083, silent_last_margin=0.15 | +0.0001 ±0.0010 | -0.0006 ±0.0012 | +0.0001 ±0.0010 | -0.0011 ±0.0016 |
| H-a open to a mute rival at tick 2 | absent_at=0.167 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 |
| H three-rung ratios | ratios=[1.624, 1.465, 1.306] | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 |
| H three-rung ratios, max_msgs 3 | ratios=[1.624, 1.465, 1.306], max_msgs=3 | -0.0000 ±0.0000 | -0.0000 ±0.0000 | +0.0000 ±0.0000 | -0.0000 ±0.0000 |
| H-a open at tick 2, mute last chance at L x (1 +- 0.15) | absent_at=0.167, silent_last_margin=0.15 | -0.0002 ±0.0001 | -0.0003 ±0.0001 | +0.0004 ±0.0002 | -0.0003 ±0.0002 |
| H three-rung ratios, open at the middle rung | ratios=[1.624, 1.465, 1.306], open_rung=1 | -0.0015 ±0.0002 | -0.0018 ±0.0003 | -0.0010 ±0.0003 | -0.0018 ±0.0004 |
| H-a open at tick 2, mute last chance at L x (1 +- 0.25) | absent_at=0.167, silent_last_margin=0.25 | -0.0023 ±0.0003 | -0.0024 ±0.0003 | -0.0013 ±0.0007 | -0.0027 ±0.0005 |
| H-d endgame accept 8 / last chance 5 | last_chance_ticks=5, accept_any_ticks=8 | -0.0064 ±0.0006 | -0.0066 ±0.0007 | -0.0052 ±0.0006 | -0.0077 ±0.0011 |
| H-a open to a mute rival at tick 4 | absent_at=0.333 | -0.0090 ±0.0005 | -0.0088 ±0.0006 | -0.0080 ±0.0006 | -0.0093 ±0.0008 |
| H-a open at tick 4, mute last chance at L x (1 +- 0.25) | absent_at=0.333, silent_last_margin=0.25 | -0.0115 ±0.0006 | -0.0115 ±0.0007 | -0.0093 ±0.0009 | -0.0120 ±0.0009 |
| H-a open to a mute rival at tick 8 | absent_at=0.667 | -0.0147 ±0.0006 | -0.0144 ±0.0007 | -0.0153 ±0.0008 | -0.0147 ±0.0010 |
| H days_best off (auto) | days_best=None | -0.0545 ±0.0014 | -0.0544 ±0.0017 | -0.0561 ±0.0017 | -0.0539 ±0.0025 |

## One lever at a time (train): best and worst value of each

| lever | incumbent | best value: objective Δ | worst value: objective Δ |
|---|---|---|---|
| accept_any_ticks | 6 | 4: +0.0043 ±0.0006 | 2: -0.0144 ±0.0011 |
| prem1 | 0.432 | 0.0: +0.0015 ±0.0004 | 1.0: -0.0015 ±0.0003 |
| min_surplus | default | 5: +0.0014 ±0.0005 | 2: +0.0008 ±0.0003 |
| floor | 1.306 | 1.35: +0.0006 ±0.0003 | 1.1: -0.0164 ±0.0007 |
| anchor | 1.624 | 2.0: +0.0006 ±0.0002 | 1.35: -0.0032 ±0.0003 |
| thin_frac | 0.216 | 0.5: +0.0004 ±0.0002 | 0.0: -0.0010 ±0.0002 |
| days_cheap | 0.174 | 0.12: +0.0004 ±0.0004 | 0.5: -0.0317 ±0.0011 |
| absent_at | 0.18 | 0.08: +0.0003 ±0.0010 | 0.75: -0.0147 ±0.0006 |
| silent_last_margin | default | 0.1: +0.0002 ±0.0002 | 0.4: -0.0030 ±0.0003 |
| last_chance_ticks | 4 | 6: +0.0001 ±0.0004 | 1: -0.0327 ±0.0010 |
| prem0 | 1.33 | 1.1: +0.0000 ±0.0000 | 0.6: -0.0000 ±0.0001 |
| max_msgs | 2 | 3: -0.0000 ±0.0000 | 1: -0.0150 ±0.0008 |
| near_ticks | -1 | 0: +0.0000 ±0.0000 | 3: +0.0000 ±0.0000 |
| absent_share | 0.608 | 0.3: +0.0000 ±0.0000 | 0.9: +0.0000 ±0.0000 |
| early_share | 99 | 0.7: +0.0000 ±0.0000 | 0.95: +0.0000 ±0.0000 |
| late_ticks | 3 | 4: -0.0003 ±0.0004 | 1: -0.0117 ±0.0004 |
| last_r | 1.155 | 1.1: -0.0009 ±0.0005 | 1.4: -0.0123 ±0.0008 |
| stall_ticks | 3 | 2: -0.0026 ±0.0006 | 6: -0.0062 ±0.0008 |
| absent_last | True | False: -0.0029 ±0.0003 | False: -0.0029 ±0.0003 |
| last_while_moving | True | False: -0.0078 ±0.0006 | False: -0.0078 ±0.0006 |
| hold_counter | default | False: -0.0098 ±0.0006 | False: -0.0098 ±0.0006 |
| slot_demand | acceptable | spoke: -0.0109 ±0.0005 | open: -0.0149 ±0.0006 |
| window_retry | default | 0: -0.0128 ±0.0006 | 3: -0.0373 ±0.0008 |
| hold_ticks | default | 3: -0.0191 ±0.0007 | 4: -0.0192 ±0.0007 |
| hold_while_conceding | default | True: -0.0290 ±0.0008 | True: -0.0290 ±0.0008 |
| window_wait | True | False: -0.0644 ±0.0011 | False: -0.0644 ±0.0011 |

## What lost most (train)

| candidate | what it changes | objective Δ |
|---|---|---|
| R1 | absent_share=0.693, window_wait=False, days_cheap=0.548 | -0.0984 ±0.0015 |
| R1 | last_r=1.393, window_wait=False | -0.0768 ±0.0013 |
| R0 | ratios=[1.542, 1.306], absent_at=0.729, window_wait=False | -0.0764 ±0.0012 |
| R4 | ratios=[1.624, 1.498], last_r=1.243, window_wait=False, late_ticks=1 | -0.0731 ±0.0014 |
| R2 | ratios=[1.624, 1.203], window_wait=False, late_ticks=1, slot_demand=spoke | -0.0723 ±0.0012 |
| R0 | ratios=[1.624, 1.281], window_wait=False, days_premium=[1.33, 0.809], min_surplus=1 | -0.0659 ±0.0012 |
| R1 | near_ticks=1, window_wait=False, late_ticks=2 | -0.0657 ±0.0012 |
| R4 | last_chance_ticks=2, window_wait=False, late_ticks=5, silent_last_margin=0 | -0.0644 ±0.0011 |
| S window_wait=False | window_wait=False | -0.0644 ±0.0011 |
| R1 | window_wait=False, slot_demand=spoke, window_retry=0 | -0.0644 ±0.0011 |

