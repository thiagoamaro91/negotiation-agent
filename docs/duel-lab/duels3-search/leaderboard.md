# Duels III overnight search: leaderboard

Refreshed 2026-10-04 04:42 UTC. Candidates scored: 1763 on train (200 sessions x 4 worlds), 163 on select (600 sessions x 4 worlds), 12 on TEST (2000 sessions x 4 worlds). Deltas are each candidate minus the incumbent on the same sessions (mean score per duel: share of the pie x 0.9^rounds, 0 without a deal), ± one SE unless marked 2 SE.

**Acceptance rule.** A candidate replaces the incumbent (`docs/duel-lab/duel-params-duels3.json`) only if,
on the TEST seeds (900000..): (1) it beats the incumbent in the main world (Duels III, Duels II field refit plus
self-play) by more than 2 SE of the paired per-session difference; (2) it is not worse than the incumbent by more
than 2 SE against any rival type, both in `tools/duel_matrix.py --session 3` (17 rival rows) and in our own
per-type split of the main world (which adds the self-play rival); (3) in the D-1 stress (an accept sent with one
tick left never settles, 15 s ticks) its mean is no more than 0.03 below the incumbent's; (4)
`python3 agent/duel.py selftest --params <file>` passes. Otherwise it stays here as "not better".

Worlds: **main** = Duels III (68 duels, 12 ticks, decay 0.10, 4 at once), the Duels II field refit (68 real duels: linear 28, oneshot 11, steady 8, fast 8, tft 5, absent 5, silent 3) plus a copy of duel.py with the incumbent params at weight 8 (10.5 %); **drift** = main with 20 % of the mix moved to deadline-concede and mute (silent, absent) rivals; **final** = the Grand Final's single round (34 duels); **D-1** = main where an accept at deadline-1 never settles. Training objective = 0.5 main + 0.15 drift + 0.15 final + 0.2 D-1 (the D-1 stress is in it because the biggest raw gains of the first sweep all came from accepting at deadline-1); candidates more than 0.03 worse in D-1 are never parents or finalists.

## TEST (seeds 900000.., 2000 sessions)

| candidate | what it changes | TEST Δ main (± 2 SE) | main without self-play (≈) | drift | final | worst rival type Δ | D-1 Δ | matrix | selftest | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| P a39b226003 without prem0 `48b7348218` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0216 ± 0.0008 | +0.0095 ±0.0004 | +0.0181 ±0.0004 | +0.0211 ±0.0006 | absent +0.0000 ±0.0000 | +0.0055 ±0.0005 | fail: fast | fail | **not better** (matrix: fast; selftest fails) |
| C silent_last_margin=0.177 `a39b226003` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0215 ± 0.0008 | +0.0094 ±0.0004 | +0.0181 ±0.0004 | +0.0210 ±0.0006 | absent +0.0000 ±0.0000 | +0.0055 ±0.0005 | - | - | **passes TEST, gates pending (matrix, selftest)** |
| P a39b226003 without early_share `a633db04b4` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0215 ± 0.0008 | +0.0094 ±0.0004 | +0.0181 ±0.0004 | +0.0210 ±0.0006 | absent +0.0000 ±0.0000 | +0.0055 ±0.0005 | - | - | **passes TEST, gates pending (matrix, selftest)** |
| P d4e220bdff without prem0 `9ea8e85e0f` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0215 ± 0.0008 | +0.0091 ±0.0004 | +0.0182 ±0.0004 | +0.0208 ±0.0006 | silent -0.0091 ±0.0021 | +0.0053 ±0.0006 | - | - | **not better** (worse vs silent beyond noise) |
| P a39b226003 without min_surplus `2c4d6a32a0` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0215 ± 0.0008 | +0.0093 ±0.0004 | +0.0179 ±0.0004 | +0.0209 ±0.0005 | absent +0.0000 ±0.0000 | +0.0055 ±0.0005 | fail: fast | pass | **not better** (matrix: fast) |
| C silent_last_margin=0.2 `d4e220bdff` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0214 ± 0.0008 | +0.0090 ±0.0004 | +0.0182 ±0.0004 | +0.0207 ±0.0006 | silent -0.0091 ±0.0021 | +0.0052 ±0.0006 | - | - | **not better** (worse vs silent beyond noise) |
| P a39b226003 without thin_frac `a8ddb5fc8b` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0213 ± 0.0008 | +0.0092 ±0.0004 | +0.0179 ±0.0004 | +0.0208 ±0.0006 | absent +0.0000 ±0.0000 | +0.0055 ±0.0005 | - | - | **passes TEST, gates pending (matrix, selftest)** |
| P a39b226003 pruned `79ceb09a92` | ratios=[1.624, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0212 ± 0.0008 | +0.0091 ±0.0004 | +0.0176 ±0.0004 | +0.0207 ±0.0006 | absent +0.0000 ±0.0000 | +0.0056 ±0.0005 | fail: fast | fail | **not better** (matrix: fast; selftest fails) |
| F 2c4d6a32a0 aa=0.18 acc=5 floor=1.38 last_r=1.155 `dded673c01` | ratios=[1.743, 1.38], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, days_premium=[2.281, 0.253], last_while_moving=True, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0176 ± 0.0007 | +0.0183 ±0.0004 | +0.0148 ±0.0003 | +0.0170 ±0.0005 | fast -0.0021 ±0.0004 | -0.0004 ±0.0005 | - | - | **not better** (worse vs fast beyond noise) |
| C prem1=0 `3623369e38` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_cheap=0.162, days_premium=[0.438, 0], min_surplus=3, silent_last_margin=0.2 | +0.0169 ± 0.0008 | +0.0038 ±0.0004 | +0.0151 ±0.0004 | +0.0162 ±0.0005 | silent -0.0057 ±0.0020 | +0.0163 ±0.0004 | fail: steady, fast, hardliner, linear | fail | **not better** (worse vs steady beyond noise; worse vs silent beyond noise; worse vs linear beyond noise; matrix: steady, fast, hardliner, linear; selftest fails) |
| F 2c4d6a32a0 aa=0.18 acc=6 floor=1.38 last_r=1.155 `ffe21a63bd` | ratios=[1.743, 1.38], max_msgs=4, last_chance_ticks=5, thin_frac=0.266, early_share=1, days_premium=[2.281, 0.253], last_while_moving=True, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0138 ± 0.0006 | +0.0143 ±0.0003 | +0.0117 ±0.0003 | +0.0136 ±0.0004 | fast -0.0011 ±0.0003 | -0.0026 ±0.0005 | fail: fast, cycler, llmfair | pass | **not better** (worse vs fast beyond noise; matrix: fast, cycler, llmfair) |
| F 2c4d6a32a0 aa=0.18 acc=6 floor=1.35 last_r=1.131 `4df2d0e8c2` | ratios=[1.743, 1.35], last_r=1.131, max_msgs=4, last_chance_ticks=5, thin_frac=0.266, early_share=1, days_premium=[2.281, 0.253], last_while_moving=True, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0133 ± 0.0006 | +0.0135 ±0.0003 | +0.0110 ±0.0003 | +0.0131 ±0.0004 | silent -0.0030 ±0.0015 | -0.0026 ±0.0005 | fail: cycler, silent, llmfair | pass | **not better** (worse vs fast beyond noise; matrix: cycler, silent, llmfair) |

- `48b7348218` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0010±0.0012, linear +0.0066±0.0006, oneshot +0.0085±0.0008, self +0.1249±0.0019, silent +0.0011±0.0017, steady +0.0098±0.0013, tft +0.0558±0.0021
- `a39b226003` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0006±0.0012, linear +0.0065±0.0006, oneshot +0.0085±0.0008, self +0.1249±0.0019, silent +0.0011±0.0017, steady +0.0096±0.0013, tft +0.0562±0.0021
- `a633db04b4` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0006±0.0012, linear +0.0065±0.0006, oneshot +0.0085±0.0008, self +0.1249±0.0019, silent +0.0011±0.0017, steady +0.0096±0.0013, tft +0.0562±0.0021
- `9ea8e85e0f` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0010±0.0012, linear +0.0067±0.0006, oneshot +0.0085±0.0008, self +0.1273±0.0019, silent -0.0091±0.0021, steady +0.0097±0.0013, tft +0.0559±0.0021
- `2c4d6a32a0` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0022±0.0011, linear +0.0071±0.0006, oneshot +0.0075±0.0007, self +0.1255±0.0019, silent +0.0011±0.0017, steady +0.0093±0.0013, tft +0.0515±0.0019
- `d4e220bdff` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0006±0.0012, linear +0.0066±0.0006, oneshot +0.0085±0.0008, self +0.1273±0.0019, silent -0.0091±0.0021, steady +0.0096±0.0013, tft +0.0563±0.0021
- `a8ddb5fc8b` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0012±0.0011, linear +0.0060±0.0006, oneshot +0.0085±0.0008, self +0.1249±0.0019, silent +0.0011±0.0017, steady +0.0095±0.0013, tft +0.0548±0.0021
- `79ceb09a92` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0036±0.0011, linear +0.0061±0.0006, oneshot +0.0085±0.0008, self +0.1249±0.0019, silent +0.0011±0.0017, steady +0.0101±0.0013, tft +0.0481±0.0020
- `dded673c01` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast -0.0021±0.0004, linear +0.0264±0.0007, oneshot +0.0006±0.0004, self +0.0116±0.0009, silent +0.0001±0.0016, steady +0.0312±0.0015, tft +0.0533±0.0022
- `3623369e38` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast +0.0028±0.0011, linear -0.0036±0.0006, oneshot +0.0069±0.0007, self +0.1291±0.0019, silent -0.0057±0.0020, steady -0.0025±0.0012, tft +0.0590±0.0021
- `ffe21a63bd` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast -0.0011±0.0003, linear +0.0252±0.0006, oneshot +0.0010±0.0004, self +0.0109±0.0009, silent +0.0001±0.0016, steady +0.0299±0.0015, tft +0.0045±0.0007
- `4df2d0e8c2` per rival type (main world, self = self-play): absent +0.0000±0.0000, fast -0.0022±0.0004, linear +0.0240±0.0006, oneshot +0.0028±0.0005, self +0.0122±0.0010, silent -0.0030±0.0015, steady +0.0284±0.0015, tft +0.0029±0.0008

## Best on select (seeds 500000.., 600 sessions)

| # | candidate | what it changes | objective Δ | main | drift | final | D-1 | train objective |
|---|---|---|---|---|---|---|---|---|
| 1 | P a39b226003 without prem0 `48b7348218` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0175 ±0.0006 | +0.0217 ±0.0007 | +0.0186 ±0.0007 | +0.0209 ±0.0010 | +0.0036 ±0.0010 | - |
| 2 | C silent_last_margin=0.177 `a39b226003` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0175 ±0.0006 | +0.0217 ±0.0007 | +0.0185 ±0.0007 | +0.0209 ±0.0010 | +0.0036 ±0.0010 | +0.0188 ±0.0011 |
| 3 | P a39b226003 without early_share `a633db04b4` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0175 ±0.0006 | +0.0217 ±0.0007 | +0.0185 ±0.0007 | +0.0209 ±0.0010 | +0.0036 ±0.0010 | - |
| 4 | P a39b226003 without thin_frac `a8ddb5fc8b` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0174 ±0.0006 | +0.0216 ±0.0007 | +0.0185 ±0.0007 | +0.0209 ±0.0010 | +0.0036 ±0.0010 | - |
| 5 | P d4e220bdff without prem0 `9ea8e85e0f` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0174 ±0.0006 | +0.0216 ±0.0007 | +0.0187 ±0.0008 | +0.0208 ±0.0010 | +0.0033 ±0.0010 | - |
| 6 | C silent_last_margin=0.2 `d4e220bdff` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0173 ±0.0006 | +0.0216 ±0.0007 | +0.0186 ±0.0008 | +0.0207 ±0.0010 | +0.0032 ±0.0010 | +0.0183 ±0.0011 |
| 7 | P d4e220bdff without early_share `725f416710` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0173 ±0.0006 | +0.0216 ±0.0007 | +0.0186 ±0.0008 | +0.0207 ±0.0010 | +0.0032 ±0.0010 | - |
| 8 | P a39b226003 without anchor `e4f89dc36c` | ratios=[1.624, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0173 ±0.0006 | +0.0214 ±0.0007 | +0.0185 ±0.0007 | +0.0207 ±0.0010 | +0.0035 ±0.0010 | - |
| 9 | P d4e220bdff without thin_frac `68855417bf` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0173 ±0.0006 | +0.0214 ±0.0007 | +0.0186 ±0.0007 | +0.0208 ±0.0010 | +0.0033 ±0.0010 | - |
| 10 | P a39b226003 without min_surplus `2c4d6a32a0` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0173 ±0.0006 | +0.0215 ±0.0007 | +0.0186 ±0.0007 | +0.0203 ±0.0010 | +0.0035 ±0.0010 | - |
| 11 | P a39b226003 pruned `79ceb09a92` | ratios=[1.624, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0172 ±0.0006 | +0.0213 ±0.0007 | +0.0183 ±0.0007 | +0.0208 ±0.0010 | +0.0035 ±0.0010 | - |
| 12 | P a39b226003 without last_r `06193f9c12` | ratios=[1.743, 1.42], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0172 ±0.0006 | +0.0215 ±0.0007 | +0.0186 ±0.0007 | +0.0202 ±0.0010 | +0.0029 ±0.0010 | - |
| 13 | P d4e220bdff without anchor `bcf3a225c9` | ratios=[1.624, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0172 ±0.0006 | +0.0213 ±0.0007 | +0.0186 ±0.0007 | +0.0206 ±0.0010 | +0.0031 ±0.0010 | - |
| 14 | P d4e220bdff pruned `1bd3b1b1bd` | ratios=[1.624, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, absent_at=0.148, days_premium=[1.33, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0171 ±0.0006 | +0.0212 ±0.0007 | +0.0184 ±0.0007 | +0.0207 ±0.0010 | +0.0032 ±0.0009 | - |
| 15 | P d4e220bdff without last_r `31ec79ebd6` | ratios=[1.743, 1.42], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0171 ±0.0006 | +0.0215 ±0.0007 | +0.0187 ±0.0007 | +0.0201 ±0.0010 | +0.0026 ±0.0010 | - |
| 16 | P d4e220bdff without min_surplus `adb048e7f6` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0171 ±0.0006 | +0.0212 ±0.0007 | +0.0188 ±0.0007 | +0.0203 ±0.0010 | +0.0030 ±0.0010 | - |
| 17 | P a39b226003 without prem1 `fff512ce4f` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.432], min_surplus=3, silent_last_margin=0.177, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0170 ±0.0006 | +0.0212 ±0.0007 | +0.0187 ±0.0007 | +0.0203 ±0.0010 | +0.0029 ±0.0010 | - |
| 18 | C floor=1.42 `5fc35825ca` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.15, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0170 ±0.0006 | +0.0213 ±0.0007 | +0.0174 ±0.0007 | +0.0205 ±0.0010 | +0.0034 ±0.0009 | +0.0179 ±0.0011 |
| 19 | P d4e220bdff without prem1 `49acaafda1` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.432], min_surplus=3, silent_last_margin=0.2, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0169 ±0.0006 | +0.0211 ±0.0007 | +0.0185 ±0.0008 | +0.0201 ±0.0010 | +0.0027 ±0.0010 | - |
| 20 | C accept_any_ticks=4 `dd19184b8b` | ratios=[1.743, 1.42], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=4, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.15, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0168 ±0.0006 | +0.0217 ±0.0007 | +0.0178 ±0.0007 | +0.0214 ±0.0010 | +0.0002 ±0.0010 | +0.0185 ±0.0011 |
| 21 | C floor=1.39 `20348e22c3` | ratios=[1.743, 1.39], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.15, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0166 ±0.0006 | +0.0209 ±0.0007 | +0.0170 ±0.0007 | +0.0199 ±0.0010 | +0.0033 ±0.0010 | +0.0182 ±0.0011 |
| 22 | C floor=1.387 `919edc9e68` | ratios=[1.743, 1.387], last_r=1.131, max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_premium=[2.281, 0.253], min_surplus=3, silent_last_margin=0.15, hold_ticks=3, hold_while_conceding=True, hold_counter=False | +0.0166 ±0.0006 | +0.0208 ±0.0007 | +0.0169 ±0.0007 | +0.0198 ±0.0010 | +0.0032 ±0.0010 | +0.0181 ±0.0011 |
| 23 | C prem1=0 `3623369e38` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_cheap=0.162, days_premium=[0.438, 0], min_surplus=3, silent_last_margin=0.2 | +0.0162 ±0.0006 | +0.0167 ±0.0007 | +0.0155 ±0.0007 | +0.0155 ±0.0010 | +0.0161 ±0.0008 | +0.0176 ±0.0011 |
| 24 | C late_ticks=5 `ecbdf5c3af` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.266, early_share=1, absent_at=0.148, days_cheap=0.162, days_premium=[0.438, 0.253], late_ticks=5, min_surplus=3, silent_last_margin=0.2 | +0.0162 ±0.0006 | +0.0165 ±0.0007 | +0.0164 ±0.0008 | +0.0154 ±0.0010 | +0.0157 ±0.0008 | +0.0175 ±0.0012 |
| 25 | C thin_frac=0.5 `4ff147bb63` | ratios=[1.743, 1.435], max_msgs=4, last_chance_ticks=5, accept_any_ticks=5, thin_frac=0.5, early_share=1, absent_at=0.148, days_cheap=0.162, days_premium=[0.438, 0.253], min_surplus=3, silent_last_margin=0.2 | +0.0162 ±0.0006 | +0.0166 ±0.0007 | +0.0164 ±0.0007 | +0.0157 ±0.0010 | +0.0152 ±0.0008 | +0.0175 ±0.0011 |

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

