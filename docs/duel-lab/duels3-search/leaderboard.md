# Duels III overnight search: leaderboard

Refreshed 2026-10-04 02:53 UTC. Candidates scored: 1273 on train (200 sessions x 4 worlds), 64 on select (600 sessions x 4 worlds), 0 on TEST (2000 sessions x 4 worlds). Deltas are each candidate minus the incumbent on the same sessions (mean score per duel: share of the pie x 0.9^rounds, 0 without a deal), ± one SE unless marked 2 SE.

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
| 1 | R28 `7113ff9297` | ratios=[1.743, 1.357], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0149 ±0.0006 | +0.0192 ±0.0007 | +0.0139 ±0.0007 | +0.0182 ±0.0010 | +0.0025 ±0.0010 | +0.0160 ±0.0011 |
| 2 | R30 `ab1329ca80` | ratios=[1.898, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_cheap=0.131, days_premium=[0.438, 0.253], min_surplus=4, hold_ticks=4, hold_counter=False, hold_while_conceding=True | +0.0147 ±0.0006 | +0.0165 ±0.0007 | +0.0127 ±0.0007 | +0.0159 ±0.0010 | +0.0110 ±0.0008 | +0.0171 ±0.0011 |
| 3 | R27 `e1b40961b1` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.253], min_surplus=4, hold_ticks=4, hold_counter=False, hold_while_conceding=True | +0.0145 ±0.0006 | +0.0159 ±0.0007 | +0.0135 ±0.0007 | +0.0152 ±0.0010 | +0.0112 ±0.0008 | +0.0167 ±0.0011 |
| 4 | R31 `d4c17f0b6a` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=4, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.253], min_surplus=4, hold_ticks=4, hold_counter=False, hold_while_conceding=True | +0.0142 ±0.0006 | +0.0166 ±0.0007 | +0.0137 ±0.0007 | +0.0160 ±0.0010 | +0.0074 ±0.0008 | +0.0165 ±0.0011 |
| 5 | R31 `d60b2ebaf8` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_cheap=0.162, days_premium=[0.438, 0.253], min_surplus=3 | +0.0141 ±0.0006 | +0.0147 ±0.0007 | +0.0128 ±0.0007 | +0.0138 ±0.0009 | +0.0138 ±0.0007 | +0.0159 ±0.0011 |
| 6 | R26 `ce98b4a804` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.253], min_surplus=3 | +0.0139 ±0.0005 | +0.0145 ±0.0006 | +0.0125 ±0.0007 | +0.0134 ±0.0009 | +0.0137 ±0.0007 | +0.0155 ±0.0011 |
| 7 | R28 `4acbe7ddef` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=4, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.253], late_ticks=4, min_surplus=3 | +0.0139 ±0.0006 | +0.0158 ±0.0007 | +0.0132 ±0.0008 | +0.0151 ±0.0009 | +0.0086 ±0.0009 | +0.0159 ±0.0012 |
| 8 | R29 `d74bc900bb` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.436], min_surplus=3 | +0.0138 ±0.0005 | +0.0144 ±0.0006 | +0.0125 ±0.0006 | +0.0135 ±0.0009 | +0.0134 ±0.0007 | +0.0154 ±0.0011 |
| 9 | R29 `5a4b49ecfe` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.253], min_surplus=4, hold_ticks=4, hold_counter=False, hold_while_conceding=False | +0.0135 ±0.0006 | +0.0140 ±0.0007 | +0.0123 ±0.0007 | +0.0127 ±0.0009 | +0.0135 ±0.0007 | +0.0155 ±0.0011 |
| 10 | R30 `4c4c6c2cb6` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[0.438, 0.253], min_surplus=4, hold_ticks=4, hold_counter=True, hold_while_conceding=False | +0.0135 ±0.0006 | +0.0140 ±0.0007 | +0.0123 ±0.0007 | +0.0127 ±0.0009 | +0.0135 ±0.0007 | +0.0155 ±0.0011 |
| 11 | R22 `d1980b0dea` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253], min_surplus=3 | +0.0133 ±0.0005 | +0.0139 ±0.0006 | +0.0117 ±0.0006 | +0.0124 ±0.0009 | +0.0135 ±0.0007 | +0.0143 ±0.0011 |
| 12 | R26 `ce1c03eea3` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0 | +0.0132 ±0.0005 | +0.0138 ±0.0006 | +0.0116 ±0.0006 | +0.0123 ±0.0009 | +0.0135 ±0.0007 | +0.0143 ±0.0011 |
| 13 | R27 `58cdf5dee5` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, near_ticks=1, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.386], late_ticks=4 | +0.0130 ±0.0005 | +0.0132 ±0.0006 | +0.0117 ±0.0006 | +0.0123 ±0.0009 | +0.0141 ±0.0008 | +0.0135 ±0.0010 |
| 14 | R21 `41e7c69579` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, near_ticks=3, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.434], min_surplus=4, hold_ticks=2 | +0.0126 ±0.0006 | +0.0132 ±0.0007 | +0.0113 ±0.0006 | +0.0113 ±0.0009 | +0.0131 ±0.0007 | +0.0135 ±0.0011 |
| 15 | R25 `4e4c8ed8bc` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, near_ticks=3, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.191, 0.434], min_surplus=4, hold_ticks=2 | +0.0126 ±0.0006 | +0.0132 ±0.0007 | +0.0113 ±0.0006 | +0.0113 ±0.0009 | +0.0131 ±0.0007 | +0.0135 ±0.0011 |
| 16 | R18 `b3deb87a59` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.386] | +0.0124 ±0.0005 | +0.0125 ±0.0006 | +0.0114 ±0.0006 | +0.0114 ±0.0009 | +0.0136 ±0.0007 | +0.0132 ±0.0010 |
| 17 | R16 `bf19c6f8d0` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253] | +0.0124 ±0.0005 | +0.0125 ±0.0006 | +0.0114 ±0.0006 | +0.0115 ±0.0009 | +0.0135 ±0.0007 | +0.0132 ±0.0010 |
| 18 | R18 `7b6a9952c3` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, near_ticks=0, thin_frac=0.194, early_share=1, absent_at=0.148, absent_share=0.655, days_premium=[1.072, 0.253] | +0.0124 ±0.0005 | +0.0125 ±0.0006 | +0.0114 ±0.0006 | +0.0115 ±0.0009 | +0.0135 ±0.0007 | +0.0132 ±0.0010 |
| 19 | R19 `3a1f6125fc` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, near_ticks=1, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.434] | +0.0124 ±0.0005 | +0.0125 ±0.0006 | +0.0116 ±0.0006 | +0.0112 ±0.0009 | +0.0134 ±0.0007 | +0.0131 ±0.0010 |
| 20 | R21 `736d1e4e4e` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.194, early_share=1, absent_at=0.148, absent_share=0.449, days_premium=[1.139, 0.253] | +0.0123 ±0.0005 | +0.0124 ±0.0006 | +0.0114 ±0.0006 | +0.0115 ±0.0009 | +0.0135 ±0.0007 | +0.0132 ±0.0010 |
| 21 | R23 `7cdf320288` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, near_ticks=3, thin_frac=0.194, early_share=1, absent_at=0.148, absent_share=0.449, days_premium=[1.139, 0.253] | +0.0123 ±0.0005 | +0.0124 ±0.0006 | +0.0114 ±0.0006 | +0.0115 ±0.0009 | +0.0135 ±0.0007 | +0.0132 ±0.0010 |
| 22 | R18 `92582151a7` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.304, early_share=1, absent_at=0.121, absent_share=0.474, days_cheap=0.099, days_premium=[1.072, 0.253] | +0.0122 ±0.0006 | +0.0128 ±0.0007 | +0.0097 ±0.0007 | +0.0117 ±0.0010 | +0.0130 ±0.0007 | +0.0130 ±0.0009 |
| 23 | R19 `ecca82e8ad` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.288, early_share=0.899, absent_at=0.121, absent_share=0.474, days_cheap=0.099, days_premium=[1.072, 0.253] | +0.0121 ±0.0006 | +0.0127 ±0.0007 | +0.0097 ±0.0007 | +0.0117 ±0.0010 | +0.0129 ±0.0007 | +0.0131 ±0.0009 |
| 24 | R26 `979e76552e` | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=4, near_ticks=2, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253] | +0.0121 ±0.0005 | +0.0135 ±0.0006 | +0.0121 ±0.0006 | +0.0127 ±0.0009 | +0.0083 ±0.0008 | +0.0135 ±0.0010 |
| 25 | R23 `a39766fdae` | ratios=[1.743, 1.515], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.194, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253], min_surplus=1 | +0.0112 ±0.0005 | +0.0115 ±0.0006 | +0.0104 ±0.0006 | +0.0112 ±0.0009 | +0.0110 ±0.0007 | +0.0132 ±0.0010 |

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
| R27 | ratios=[1.624, 1.253], last_chance_ticks=1, window_wait=False | -0.0971 ±0.0015 |
| R10 | accept_any_ticks=1, stall_ticks=1 | -0.0939 ±0.0018 |
| R29 | ratios=[1.743, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=10, near_ticks=1, thin_frac=0.194, early_share=1, absent_at=0.258, window_wait=False, days_premium=[1.072, 0.386], late_ticks=4, hold_while_conceding=True | -0.0877 ±0.0015 |
| R16 | max_msgs=1, window_wait=False | -0.0791 ±0.0013 |
| R1 | last_r=1.393, window_wait=False | -0.0768 ±0.0013 |
| R0 | ratios=[1.542, 1.306], absent_at=0.729, window_wait=False | -0.0764 ±0.0012 |
| R26 | ratios=[1.589, 1.357], max_msgs=4, last_chance_ticks=5, accept_any_ticks=1, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[1.072, 0.253], min_surplus=3, hold_while_conceding=True | -0.0733 ±0.0019 |
| R4 | ratios=[1.624, 1.498], last_r=1.243, window_wait=False, late_ticks=1 | -0.0731 ±0.0014 |
| R19 | window_wait=False, days_cheap=0.008, last_while_moving=False | -0.0729 ±0.0013 |

