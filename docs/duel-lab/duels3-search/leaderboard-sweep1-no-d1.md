# Duels III overnight search: leaderboard

Refreshed 2026-10-04 00:39 UTC. Candidates scored: 123 on train (200 sessions x 3 worlds), 12 on select (600 sessions x 4 worlds), 0 on TEST (2000 sessions x 4 worlds). Deltas are each candidate minus the incumbent on the same sessions (mean score per duel: share of the pie x 0.9^rounds, 0 without a deal), ± one SE unless marked 2 SE.

**Acceptance rule.** A candidate replaces the incumbent (`docs/duel-lab/duel-params-duels3.json`) only if,
on the TEST seeds (900000..): (1) it beats the incumbent in the main world (Duels III, Duels II field refit plus
self-play) by more than 2 SE of the paired per-session difference; (2) it is not worse than the incumbent by more
than 2 SE against any rival type, both in `tools/duel_matrix.py --session 3` (17 rival rows) and in our own
per-type split of the main world (which adds the self-play rival); (3) in the D-1 stress (an accept sent with one
tick left never settles, 15 s ticks) its mean is no more than 0.03 below the incumbent's; (4)
`python3 agent/duel.py selftest --params <file>` passes. Otherwise it stays here as "not better".

Worlds: **main** = Duels III (68 duels, 12 ticks, decay 0.10, 4 at once), the Duels II field refit (68 real duels: linear 28, oneshot 11, steady 8, fast 8, tft 5, absent 5, silent 3) plus a copy of duel.py with the incumbent params at weight 8 (10.5 %); **drift** = main with 20 % of the mix moved to deadline-concede and mute (silent, absent) rivals; **final** = the Grand Final's single round (34 duels); **D-1** = main where an accept at deadline-1 never settles. Training objective = 0.6 main + 0.2 drift + 0.2 final.

## Best on select (seeds 500000.., 600 sessions)

| # | candidate | what it changes | objective Δ | main | drift | final | D-1 | train objective |
|---|---|---|---|---|---|---|---|---|
| 1 | H F1 hold, silent wait `f985969202` | hold_while_conceding=True, hold_counter=False | +0.0139 ±0.0003 | +0.0150 ±0.0005 | +0.0097 ±0.0005 | +0.0146 ±0.0006 | -0.1097 ±0.0011 | +0.0146 ±0.0007 |
| 2 | S window_retry=0 `e44c1a376d` | window_retry=0 | +0.0127 ±0.0003 | +0.0141 ±0.0004 | +0.0078 ±0.0005 | +0.0131 ±0.0006 | -0.1157 ±0.0011 | +0.0125 ±0.0007 |
| 3 | S accept_any_ticks=3 `eff5b6a76f` | accept_any_ticks=3 | +0.0091 ±0.0004 | +0.0092 ±0.0005 | +0.0079 ±0.0005 | +0.0100 ±0.0007 | -0.0170 ±0.0009 | +0.0088 ±0.0008 |
| 4 | S accept_any_ticks=4 `6bc71ed0cb` | accept_any_ticks=4 | +0.0062 ±0.0003 | +0.0064 ±0.0004 | +0.0054 ±0.0004 | +0.0064 ±0.0006 | -0.0031 ±0.0006 | +0.0060 ±0.0006 |
| 5 | H-d endgame accept 5 / last chance 3 `153f0980b2` | last_chance_ticks=3, accept_any_ticks=5 | +0.0039 ±0.0003 | +0.0035 ±0.0004 | +0.0045 ±0.0004 | +0.0045 ±0.0006 | -0.0025 ±0.0005 | +0.0041 ±0.0005 |
| 6 | S accept_any_ticks=5 `ae03640e6a` | accept_any_ticks=5 | +0.0037 ±0.0003 | +0.0037 ±0.0003 | +0.0033 ±0.0003 | +0.0042 ±0.0004 | +0.0027 ±0.0004 | +0.0040 ±0.0004 |
| 7 | S min_surplus=5 `8c107e1e23` | min_surplus=5 | +0.0017 ±0.0003 | +0.0020 ±0.0004 | +0.0006 ±0.0004 | +0.0022 ±0.0005 | +0.0011 ±0.0004 | +0.0014 ±0.0005 |
| 8 | S min_surplus=3 `4b8c53769a` | min_surplus=3 | +0.0014 ±0.0002 | +0.0015 ±0.0003 | +0.0007 ±0.0003 | +0.0019 ±0.0003 | +0.0005 ±0.0003 | +0.0015 ±0.0004 |
| 9 | S min_surplus=2 `3dd1326d15` | min_surplus=2 | +0.0009 ±0.0002 | +0.0010 ±0.0002 | +0.0004 ±0.0002 | +0.0010 ±0.0002 | +0.0006 ±0.0002 | +0.0007 ±0.0003 |
| 10 | S prem1=0.0 `eb35b5dbbb` | days_premium=[1.33, 0] | +0.0008 ±0.0002 | +0.0010 ±0.0003 | +0.0001 ±0.0003 | +0.0010 ±0.0003 | +0.0011 ±0.0003 | +0.0014 ±0.0004 |
| 11 | S floor=1.35 `9a729a3b77` | ratios=[1.624, 1.35] | +0.0003 ±0.0002 | +0.0003 ±0.0002 | +0.0008 ±0.0002 | -0.0000 ±0.0003 | +0.0002 ±0.0002 | +0.0007 ±0.0003 |
| 12 | S prem1=0.3 `7271ce29c1` | days_premium=[1.33, 0.3] | +0.0002 ±0.0001 | +0.0002 ±0.0001 | +0.0002 ±0.0001 | +0.0002 ±0.0002 | +0.0003 ±0.0001 | +0.0006 ±0.0002 |

## Structured hypotheses (train)

| hypothesis | what it changes | objective Δ | main | drift | final |
|---|---|---|---|---|---|
| H-d endgame accept 5 / last chance 3 | last_chance_ticks=3, accept_any_ticks=5 | +0.0041 ±0.0005 | +0.0042 ±0.0006 | +0.0033 ±0.0007 | +0.0045 ±0.0009 |
| H-a open to a mute rival at tick 2 | absent_at=0.167 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 |
| H three-rung ratios | ratios=[1.624, 1.465, 1.306] | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 |
| H three-rung ratios, max_msgs 3 | ratios=[1.624, 1.465, 1.306], max_msgs=3 | -0.0000 ±0.0000 | -0.0000 ±0.0000 | +0.0000 ±0.0000 | -0.0000 ±0.0000 |
| H-a open at tick 2, mute last chance at L x (1 +- 0.15) | absent_at=0.167, silent_last_margin=0.15 | -0.0001 ±0.0001 | -0.0003 ±0.0001 | +0.0004 ±0.0002 | -0.0003 ±0.0002 |
| H-a open to a mute rival at tick 1 | absent_at=0.083 | -0.0004 ±0.0010 | -0.0004 ±0.0012 | -0.0002 ±0.0010 | -0.0008 ±0.0016 |
| H-a open at tick 1, mute last chance at L x (1 +- 0.15) | absent_at=0.083, silent_last_margin=0.15 | -0.0006 ±0.0010 | -0.0006 ±0.0012 | +0.0001 ±0.0010 | -0.0011 ±0.0016 |
| H three-rung ratios, open at the middle rung | ratios=[1.624, 1.465, 1.306], open_rung=1 | -0.0016 ±0.0003 | -0.0018 ±0.0003 | -0.0010 ±0.0003 | -0.0018 ±0.0004 |
| H-a open at tick 2, mute last chance at L x (1 +- 0.25) | absent_at=0.167, silent_last_margin=0.25 | -0.0022 ±0.0003 | -0.0024 ±0.0003 | -0.0013 ±0.0007 | -0.0027 ±0.0005 |
| H-d endgame accept 8 / last chance 5 | last_chance_ticks=5, accept_any_ticks=8 | -0.0065 ±0.0006 | -0.0066 ±0.0007 | -0.0052 ±0.0006 | -0.0077 ±0.0011 |
| H-a open to a mute rival at tick 4 | absent_at=0.333 | -0.0088 ±0.0005 | -0.0088 ±0.0006 | -0.0080 ±0.0006 | -0.0093 ±0.0008 |
| H-a open at tick 4, mute last chance at L x (1 +- 0.25) | absent_at=0.333, silent_last_margin=0.25 | -0.0112 ±0.0006 | -0.0115 ±0.0007 | -0.0093 ±0.0009 | -0.0120 ±0.0009 |
| H-a open to a mute rival at tick 8 | absent_at=0.667 | -0.0146 ±0.0006 | -0.0144 ±0.0007 | -0.0153 ±0.0008 | -0.0147 ±0.0010 |
| H days_best off (auto) | days_best=None | -0.0547 ±0.0015 | -0.0544 ±0.0017 | -0.0561 ±0.0017 | -0.0539 ±0.0025 |

## One lever at a time (train): best and worst value of each

| lever | incumbent | best value: objective Δ | worst value: objective Δ |
|---|---|---|---|
| hold_counter | default | False: +0.0146 ±0.0007 | False: +0.0146 ±0.0007 |
| window_retry | default | 0: +0.0125 ±0.0007 | 3: -0.0410 ±0.0008 |
| accept_any_ticks | 6 | 3: +0.0088 ±0.0008 | 9: -0.0068 ±0.0005 |
| min_surplus | default | 3: +0.0015 ±0.0004 | 2: +0.0007 ±0.0003 |
| prem1 | 0.432 | 0.0: +0.0014 ±0.0004 | 1.0: -0.0015 ±0.0003 |
| floor | 1.306 | 1.35: +0.0007 ±0.0003 | 1.1: -0.0167 ±0.0007 |
| anchor | 1.624 | 1.85: +0.0005 ±0.0001 | 1.35: -0.0033 ±0.0003 |
| thin_frac | 0.216 | 0.5: +0.0004 ±0.0002 | 0.0: -0.0011 ±0.0002 |
| days_cheap | 0.174 | 0.12: +0.0002 ±0.0004 | 0.5: -0.0324 ±0.0011 |
| last_chance_ticks | 4 | 3: +0.0002 ±0.0004 | 1: -0.0335 ±0.0010 |
| silent_last_margin | default | 0.1: +0.0001 ±0.0002 | 0.4: -0.0030 ±0.0004 |
| prem0 | 1.33 | 1.1: +0.0000 ±0.0000 | 0.6: -0.0000 ±0.0000 |
| absent_at | 0.18 | 0.25: +0.0000 ±0.0000 | 0.75: -0.0146 ±0.0006 |
| max_msgs | 2 | 3: -0.0000 ±0.0000 | 1: -0.0150 ±0.0008 |
| near_ticks | -1 | 0: +0.0000 ±0.0000 | 3: +0.0000 ±0.0000 |
| absent_share | 0.608 | 0.3: +0.0000 ±0.0000 | 0.9: +0.0000 ±0.0000 |
| early_share | 99 | 0.7: +0.0000 ±0.0000 | 0.95: +0.0000 ±0.0000 |
| late_ticks | 3 | 4: -0.0003 ±0.0004 | 1: -0.0113 ±0.0004 |
| last_r | 1.155 | 1.1: -0.0012 ±0.0005 | 1.4: -0.0118 ±0.0008 |
| stall_ticks | 3 | 4: -0.0024 ±0.0005 | 1: -0.0061 ±0.0008 |
| absent_last | True | False: -0.0029 ±0.0003 | False: -0.0029 ±0.0003 |
| last_while_moving | True | False: -0.0072 ±0.0006 | False: -0.0072 ±0.0006 |
| hold_while_conceding | default | True: -0.0108 ±0.0008 | True: -0.0108 ±0.0008 |
| slot_demand | acceptable | spoke: -0.0124 ±0.0006 | open: -0.0167 ±0.0006 |
| hold_ticks | default | 3: -0.0173 ±0.0007 | 4: -0.0196 ±0.0007 |
| window_wait | True | False: -0.0681 ±0.0012 | False: -0.0681 ±0.0012 |

## What lost most (train)

| candidate | what it changes | objective Δ |
|---|---|---|
| S window_wait=False | window_wait=False | -0.0681 ±0.0012 |
| H days_best off (auto) | days_best=None | -0.0547 ±0.0015 |
| S window_retry=3 | window_retry=3 | -0.0410 ±0.0008 |
| S last_chance_ticks=1 | last_chance_ticks=1 | -0.0335 ±0.0010 |
| S days_cheap=0.5 | days_cheap=0.5 | -0.0324 ±0.0011 |
| S hold_ticks=4 | hold_ticks=4, hold_while_conceding=True | -0.0196 ±0.0007 |
| S window_retry=2 | window_retry=2 | -0.0177 ±0.0005 |
| S hold_ticks=3 | hold_ticks=3, hold_while_conceding=True | -0.0173 ±0.0007 |
| S floor=1.1 | ratios=[1.624, 1.1] | -0.0167 ±0.0007 |
| S slot_demand=open | slot_demand=open | -0.0167 ±0.0006 |

