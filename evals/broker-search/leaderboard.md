# Broker overnight search: leaderboard

Updated 06:18 Madrid (6600 candidates screened, 75 confirmed runs). Search running (round 1).

**Acceptance rule (fixed at 02:30 Madrid, before the first search run at 02:36).** A candidate is *recommendable for the hard
test* only if it beats `stall` on `hard` by more than 2 SE, AND is not worse than `stall` beyond noise (diff + 1.96 SE
< 0) on ANY other scenario, the five real-session refits included, AND drops no pair the stall would have crossed
(`dropped_vs_stall` = 0: a pair the stall matched in the paired session whose two traders both leave unmatched under the
candidate), AND `bad_match` = 0. It is *recommendable everywhere* only if it also beats `stall` by more than 2 SE on
`standard` and on each of the five refits. Anything else is *not recommended*. Deployment: the policy is fixed when
the broker starts (08:55) and a restart is allowed only between tests (09:49-10:49 is the first long window), so a
hard-test-only candidate could at most run from the 10:49 test on, and the hard test (09:39) itself would run the
stall.

Cells: candidate − stall in efficiency (share of the best possible gains), 95 % CI = ±1.96 SE, on 1,000 `unseen` seeds × 4 sessions per scenario (selection used separate `screen` seeds). `drop` = pairs the stall crossed that the candidate let both traders leave unmatched, summed over the required scenarios; the stall's own count of crossable pairs left unmatched is always 0. `bad` = matches the guard or the engine refused.

| row | verdict | hard | standard | firm_50 | firm_80 | all_impatient | short_patience | thin_overlap | wide_overlap | arrive_all0 | arrive_late | refit b36 | refit b53 | refit b70 | refit b88 | refit b104 | refit all | drop | bad |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 blind estimates (BenchPolicy, BLIND=policy) `8cfbaa8061` | not recommended | +0.0005 ±0.0010 | +0.0000 ±0.0008 | +0.0006 ±0.0011 | +0.0027 ±0.0011 | +0.0003 ±0.0009 | +0.0006 ±0.0010 | +0.0015 ±0.0008 | -0.0004 ±0.0008 | -0.0002 ±0.0004 | -0.0009 ±0.0009 | -0.0013 ±0.0008 | -0.0008 ±0.0008 | -0.0009 ±0.0008 | -0.0006 ±0.0008 | +0.0001 ±0.0010 | -0.0006 ±0.0009 | 75 | 0 |
| 2 timing rules without expiries `79977000b8` | not recommended | +0.0005 ±0.0006 | +0.0004 ±0.0007 | +0.0007 ±0.0007 | +0.0005 ±0.0005 | +0.0004 ±0.0007 | +0.0009 ±0.0008 | +0.0007 ±0.0007 | +0.0008 ±0.0006 | -0.0001 ±0.0003 | +0.0005 ±0.0008 | -0.0003 ±0.0006 | +0.0002 ±0.0006 | -0.0005 ±0.0006 | -0.0001 ±0.0006 | +0.0005 ±0.0007 | +0.0002 ±0.0005 | 0 | 0 |
| 3 hybrid: stall + leave classifier swap `23548db80f` | not recommended | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0001 ±0.0002 | +0.0000 ±0.0000 | +0.0000 ±0.0001 | +0.0000 ±0.0000 | +0.0001 ±0.0001 | -0.0000 ±0.0001 | -0.0001 ±0.0001 | +0.0000 ±0.0001 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | -0.0001 ±0.0002 | +0.0000 ±0.0000 | +0.0000 ±0.0001 | -0.0000 ±0.0002 | 0 | 0 |
| 3b hybrid: leave classifier inside BenchPolicy `59f17ee96d` | not recommended | +0.0006 ±0.0009 | -0.0004 ±0.0008 | -0.0002 ±0.0010 | +0.0025 ±0.0010 | +0.0001 ±0.0010 | -0.0005 ±0.0010 | +0.0010 ±0.0008 | +0.0005 ±0.0007 | -0.0004 ±0.0005 | -0.0016 ±0.0010 | -0.0016 ±0.0007 | -0.0018 ±0.0008 | -0.0015 ±0.0008 | -0.0013 ±0.0008 | -0.0011 ±0.0010 | -0.0007 ±0.0008 | 35 | 0 |
| ref: broker.py BenchPolicy, its own priors, BLIND=policy | not recommended | +0.0010 ±0.0014 | -0.0015 ±0.0014 | +0.0016 ±0.0016 | +0.0028 ±0.0016 | -0.0001 ±0.0014 | -0.0022 ±0.0015 | +0.0016 ±0.0012 | -0.0012 ±0.0012 | +0.0002 ±0.0006 | -0.0011 ±0.0015 | -0.0054 ±0.0011 | -0.0033 ±0.0012 | -0.0049 ±0.0011 | -0.0033 ±0.0011 | -0.0013 ±0.0013 | -0.0023 ±0.0012 | 45 | 0 |
| ref: WP2's maxpairs (memo: loses) | not recommended | -0.0070 ±0.0017 | -0.0078 ±0.0015 | -0.0053 ±0.0017 | -0.0006 ±0.0018 | -0.0069 ±0.0016 | -0.0091 ±0.0017 | +0.0020 ±0.0011 | -0.0138 ±0.0019 | -0.0070 ±0.0021 | -0.0085 ±0.0017 | -0.0222 ±0.0017 | -0.0132 ±0.0015 | -0.0168 ±0.0015 | -0.0143 ±0.0016 | -0.0081 ±0.0014 | -0.0151 ±0.0016 | 0 | 0 |
| ref: WP2's maxweight (memo: loses) | not recommended | -0.0011 ±0.0014 | -0.0034 ±0.0012 | -0.0012 ±0.0015 | +0.0023 ±0.0016 | -0.0020 ±0.0012 | -0.0038 ±0.0013 | +0.0023 ±0.0010 | -0.0035 ±0.0012 | +0.0076 ±0.0015 | -0.0039 ±0.0014 | -0.0094 ±0.0012 | -0.0065 ±0.0012 | -0.0081 ±0.0011 | -0.0064 ±0.0011 | -0.0048 ±0.0012 | -0.0054 ±0.0011 | 0 | 0 |
| ref: ORACLE: the swap with perfect leave flags | not recommended | -0.0098 ±0.0026 | -0.0079 ±0.0019 | -0.0039 ±0.0017 | -0.0026 ±0.0017 | -0.0175 ±0.0029 | -0.0117 ±0.0025 | +0.0059 ±0.0012 | -0.0070 ±0.0018 | -0.0007 ±0.0004 | -0.0060 ±0.0018 | -0.0259 ±0.0024 | -0.0238 ±0.0025 | -0.0292 ±0.0024 | -0.0280 ±0.0026 | -0.0213 ±0.0024 | -0.0199 ±0.0023 | 12 | 0 |
| ref: ORACLE: BenchPolicy with perfect leave flags | not recommended | +0.0246 ±0.0028 | +0.0328 ±0.0029 | +0.0351 ±0.0030 | +0.0300 ±0.0032 | +0.0194 ±0.0027 | +0.0258 ±0.0030 | +0.0164 ±0.0019 | +0.0431 ±0.0033 | +0.0009 ±0.0008 | +0.0380 ±0.0031 | +0.0292 ±0.0023 | +0.0225 ±0.0024 | +0.0175 ±0.0020 | +0.0229 ±0.0023 | +0.0157 ±0.0021 | +0.0239 ±0.0022 | 370 | 0 |
| ref: ORACLE: BenchPolicy, 5 % of leave flags flipped | not recommended | +0.0044 ±0.0033 | +0.0080 ±0.0036 | +0.0114 ±0.0036 | +0.0080 ±0.0038 | +0.0021 ±0.0035 | +0.0042 ±0.0037 | -0.0066 ±0.0026 | +0.0182 ±0.0040 | -0.0022 ±0.0011 | +0.0147 ±0.0037 | +0.0090 ±0.0027 | +0.0010 ±0.0031 | -0.0035 ±0.0026 | +0.0008 ±0.0029 | -0.0056 ±0.0027 | +0.0027 ±0.0027 | 2397 | 0 |
| ref: ORACLE: BenchPolicy, 15 % of leave flags flipped | not recommended | -0.0237 ±0.0039 | -0.0092 ±0.0036 | -0.0081 ±0.0038 | -0.0066 ±0.0037 | -0.0302 ±0.0044 | -0.0272 ±0.0044 | -0.0231 ±0.0030 | -0.0040 ±0.0041 | -0.0048 ±0.0013 | -0.0078 ±0.0039 | -0.0215 ±0.0032 | -0.0237 ±0.0035 | -0.0341 ±0.0032 | -0.0262 ±0.0034 | -0.0334 ±0.0032 | -0.0257 ±0.0031 | 5063 | 0 |
| ref: ORACLE: BenchPolicy, 30 % of leave flags flipped | not recommended | -0.0403 ±0.0041 | -0.0191 ±0.0036 | -0.0127 ±0.0036 | -0.0138 ±0.0037 | -0.0459 ±0.0046 | -0.0377 ±0.0042 | -0.0242 ±0.0027 | -0.0079 ±0.0038 | -0.0056 ±0.0013 | -0.0178 ±0.0036 | -0.0465 ±0.0034 | -0.0458 ±0.0037 | -0.0585 ±0.0035 | -0.0505 ±0.0037 | -0.0522 ±0.0034 | -0.0488 ±0.0034 | 6988 | 0 |

## TEST: holdout runs (2,000 `holdout` seeds: the best member of each family, chosen on its unseen run, plus any candidate the unseen run called recommendable)

| row | verdict | hard | standard | firm_50 | firm_80 | all_impatient | short_patience | thin_overlap | wide_overlap | arrive_all0 | arrive_late | refit b36 | refit b53 | refit b70 | refit b88 | refit b104 | refit all | drop | bad |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| blind_est `8cfbaa8061` | not recommended | +0.0006 ±0.0007 | -0.0002 ±0.0006 | +0.0004 ±0.0007 | +0.0019 ±0.0007 | -0.0001 ±0.0007 | +0.0009 ±0.0007 | +0.0013 ±0.0005 | +0.0001 ±0.0005 | -0.0003 ±0.0003 | -0.0004 ±0.0006 | -0.0010 ±0.0006 | -0.0001 ±0.0006 | -0.0009 ±0.0007 | -0.0006 ±0.0006 | +0.0000 ±0.0007 | -0.0010 ±0.0006 | 126 | 0 |
| timing `79977000b8` | recommendable for the hard test | +0.0009 ±0.0005 | +0.0006 ±0.0005 | +0.0009 ±0.0005 | +0.0007 ±0.0004 | +0.0002 ±0.0005 | +0.0008 ±0.0005 | +0.0008 ±0.0004 | +0.0001 ±0.0004 | -0.0001 ±0.0002 | +0.0005 ±0.0006 | -0.0002 ±0.0004 | -0.0001 ±0.0004 | -0.0001 ±0.0004 | -0.0003 ±0.0005 | +0.0002 ±0.0004 | +0.0006 ±0.0003 | 0 | 0 |
| hybrid `23548db80f` | not recommended | -0.0000 ±0.0000 | -0.0000 ±0.0000 | -0.0000 ±0.0001 | +0.0000 ±0.0000 | +0.0001 ±0.0001 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | -0.0001 ±0.0001 | +0.0000 ±0.0001 | +0.0000 ±0.0000 | +0.0000 ±0.0000 | -0.0000 ±0.0002 | -0.0000 ±0.0000 | -0.0001 ±0.0001 | -0.0000 ±0.0001 | 0 | 0 |
| hybrid_est `59f17ee96d` | not recommended | +0.0008 ±0.0007 | -0.0005 ±0.0006 | +0.0002 ±0.0006 | +0.0014 ±0.0007 | -0.0006 ±0.0007 | +0.0000 ±0.0006 | +0.0004 ±0.0005 | -0.0002 ±0.0005 | -0.0001 ±0.0003 | -0.0002 ±0.0006 | -0.0013 ±0.0005 | -0.0011 ±0.0006 | -0.0018 ±0.0006 | -0.0015 ±0.0005 | -0.0011 ±0.0006 | -0.0013 ±0.0005 | 60 | 0 |

## Best members (parameters, and why the rule says what it says)

- **1 blind estimates (BenchPolicy, BLIND=policy)**: 1650 screened, 428 passed the first screen step, 20 confirmed.
  best `8cfbaa8061` {"expiry_margin": 1, "firm_shade": 0.028, "first_shade": 0.053, "future": 0.483, "imp": [2, 4], "imp_share": 0.982, "min_edge": 0.5, "pat": [7, 14], "slope": "prior", "smax": 0.112}: not recommended (hard +0.0005 is not > 2 SE (0.0010); worse beyond noise on arrive_late, refit b36, refit b53, refit b70; drops pairs the stall crossed on hard, standard, firm_50, all_impatient, short_patience, thin_overlap, wide_overlap, arrive_all0, arrive_late, refit b36, refit b53, refit b70, refit b88, refit b104)
- **2 timing rules without expiries**: 1650 screened, 607 passed the first screen step, 12 confirmed.
  best `79977000b8` {"delta": 0.099, "end_margin": 1, "hi": 0.5, "lo": 0.0, "max_swaps": 1, "mech": "second", "refill": false, "rho_fast": 0.09, "rho_slow": 0.09, "sides": "buy", "u_firm": 1.0, "u_first": 1.0}: not recommended (hard +0.0005 is not > 2 SE (0.0006))
- **3 hybrid: stall + leave classifier swap**: 1650 screened, 516 passed the first screen step, 18 confirmed.
  best `23548db80f` {"delta": 0.149, "hi": 0.86, "lo": 0.163, "max_swaps": 3, "model": "sim", "refill": true, "sides": "sell"}: not recommended (hard +0.0000 is not > 2 SE (0.0000))
- **3b hybrid: leave classifier inside BenchPolicy**: 1650 screened, 280 passed the first screen step, 13 confirmed.
  best `59f17ee96d` {"firm_shade": 0.034, "first_shade": 0.03, "future": 1.105, "leave_scale": 2.083, "min_edge": 0.0, "model": "sim_hard", "smax": 0.156}: not recommended (hard +0.0006 is not > 2 SE (0.0009); worse beyond noise on arrive_late, refit b36, refit b53, refit b70, refit b88, refit b104; drops pairs the stall crossed on standard, all_impatient, short_patience, thin_overlap, arrive_all0, refit b36, refit b53, refit b70, refit b88, refit b104)

## Every confirmed run

| row | prefix | verdict | hard | standard | refits (min z) | worst z | drop |
|---|---|---|---|---|---|---|---|
| ref: broker.py BenchPolicy, its own priors, BLIND=policy | unseen | not recommended | +0.0010 ±0.0014 | -0.0015 ±0.0014 | -9.2 | refit b36 -9.2 | 45 |
| ref: WP2's maxpairs (memo: loses) | unseen | not recommended | -0.0070 ±0.0017 | -0.0078 ±0.0015 | -25.1 | refit b36 -25.1 | 0 |
| ref: WP2's maxweight (memo: loses) | unseen | not recommended | -0.0011 ±0.0014 | -0.0034 ±0.0012 | -15.6 | refit b36 -15.6 | 0 |
| ref: ORACLE: the swap with perfect leave flags | unseen | not recommended | -0.0098 ±0.0026 | -0.0079 ±0.0019 | -24.0 | refit b70 -24.0 | 12 |
| ref: ORACLE: BenchPolicy with perfect leave flags | unseen | not recommended | +0.0246 ±0.0028 | +0.0328 ±0.0029 | +14.5 | arrive_all0 +2.0 | 370 |
| blind_est `7be9a116cc` | unseen | not recommended | -0.0006 ±0.0015 | -0.0021 ±0.0014 | -11.8 | refit b70 -11.8 | 137 |
| blind_est `cd41a037b1` | unseen | not recommended | -0.0017 ±0.0015 | -0.0024 ±0.0014 | -11.2 | refit b36 -11.2 | 165 |
| timing `13f8f6e0bf` | unseen | not recommended | +0.0005 ±0.0009 | -0.0012 ±0.0011 | -6.5 | refit b70 -6.5 | 0 |
| timing `6c79de3a60` | unseen | not recommended | +0.0007 ±0.0009 | -0.0011 ±0.0010 | -5.0 | refit b70 -5.0 | 0 |
| hybrid `9182bc3bf6` | unseen | not recommended | -0.0001 ±0.0004 | +0.0002 ±0.0002 | -3.4 | refit b70 -3.4 | 0 |
| ref: ORACLE: BenchPolicy, 5 % of leave flags flipped | unseen | not recommended | +0.0044 ±0.0033 | +0.0080 ±0.0036 | -4.1 | thin_overlap -4.9 | 2397 |
| ref: ORACLE: BenchPolicy, 15 % of leave flags flipped | unseen | not recommended | -0.0237 ±0.0039 | -0.0092 ±0.0036 | -20.9 | refit b70 -20.9 | 5063 |
| ref: ORACLE: BenchPolicy, 30 % of leave flags flipped | unseen | not recommended | -0.0403 ±0.0041 | -0.0191 ±0.0036 | -32.6 | refit b70 -32.6 | 6988 |
| blind_est `ac4302f9b5` | unseen | not recommended | -0.0016 ±0.0014 | -0.0021 ±0.0012 | -7.5 | refit b36 -7.5 | 46 |
| hybrid `23548db80f` | unseen | not recommended | +0.0000 ±0.0000 | +0.0000 ±0.0000 | -1.2 | arrive_all0 -1.4 | 0 |
| hybrid_est `7e0567b528` | unseen | not recommended | +0.0003 ±0.0009 | -0.0006 ±0.0008 | -4.4 | refit b53 -4.4 | 50 |
| hybrid_est `09525746aa` | unseen | not recommended | +0.0004 ±0.0009 | -0.0006 ±0.0008 | -4.3 | refit b53 -4.3 | 29 |
| blind_est `9592aa5d33` | unseen | not recommended | +0.0008 ±0.0013 | -0.0009 ±0.0013 | -7.1 | refit b70 -7.1 | 143 |
| blind_est `371e674338` | unseen | not recommended | +0.0015 ±0.0013 | -0.0006 ±0.0013 | -5.5 | refit b36 -5.5 | 6 |
| timing `79977000b8` | unseen | not recommended | +0.0005 ±0.0006 | +0.0004 ±0.0007 | -1.6 | refit b70 -1.6 | 0 |
| timing `6705720858` | unseen | not recommended | +0.0003 ±0.0007 | -0.0006 ±0.0009 | -2.1 | refit b36 -2.1 | 0 |
| hybrid `829d2ec987` | unseen | not recommended | -0.0000 ±0.0001 | +0.0001 ±0.0001 | -1.3 | arrive_late -1.7 | 0 |
| hybrid_est `59f17ee96d` | unseen | not recommended | +0.0006 ±0.0009 | -0.0004 ±0.0008 | -4.3 | refit b53 -4.3 | 35 |
| blind_est `e78f8ac1e0` | unseen | not recommended | +0.0000 ±0.0010 | -0.0001 ±0.0009 | -4.8 | refit b36 -4.8 | 59 |
| timing `98843e6e09` | unseen | not recommended | +0.0004 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| timing `01c892e083` | unseen | not recommended | +0.0004 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| hybrid `a26534ea8e` | unseen | not recommended | -0.0003 ±0.0004 | +0.0001 ±0.0003 | -2.8 | refit b53 -2.8 | 0 |
| hybrid `5da90bb76c` | unseen | not recommended | -0.0003 ±0.0004 | +0.0001 ±0.0003 | -2.8 | refit b53 -2.8 | 0 |
| hybrid_est `21d96eb77e` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 55 |
| hybrid_est `874fb2e590` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 44 |
| blind_est `6111527c53` | unseen | not recommended | +0.0007 ±0.0010 | +0.0003 ±0.0008 | -3.2 | refit b36 -3.2 | 93 |
| blind_est `8cfbaa8061` | unseen | not recommended | +0.0005 ±0.0010 | +0.0000 ±0.0008 | -3.1 | refit b36 -3.1 | 75 |
| timing `d94a93b0b0` | unseen | not recommended | +0.0003 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| timing `979c2f8c84` | unseen | not recommended | +0.0003 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| hybrid `38dfd1617b` | unseen | not recommended | -0.0003 ±0.0004 | +0.0002 ±0.0003 | -3.1 | refit b53 -3.1 | 0 |
| hybrid `258517f2f6` | unseen | not recommended | -0.0003 ±0.0004 | +0.0002 ±0.0003 | -3.1 | refit b53 -3.1 | 0 |
| hybrid_est `6c07e02227` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 40 |
| hybrid_est `080bb2ca01` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 42 |
| blind_est `a3be137238` | unseen | not recommended | +0.0003 ±0.0008 | +0.0002 ±0.0007 | -3.3 | refit b53 -3.3 | 12 |
| blind_est `83fa4184f4` | unseen | not recommended | +0.0006 ±0.0008 | +0.0000 ±0.0008 | -3.3 | refit b53 -3.3 | 14 |
| hybrid `91ebeb69c9` | unseen | not recommended | -0.0003 ±0.0004 | +0.0002 ±0.0003 | -3.0 | refit b53 -3.0 | 0 |
| hybrid `3740c77fb7` | unseen | not recommended | -0.0003 ±0.0004 | +0.0002 ±0.0003 | -3.0 | refit b53 -3.0 | 0 |
| hybrid_est `82e4b68c64` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 45 |
| hybrid_est `067931350b` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 44 |
| blind_est `bd70b5777a` | unseen | not recommended | +0.0006 ±0.0008 | +0.0001 ±0.0007 | -3.3 | refit b53 -3.3 | 16 |
| blind_est `503fc5060f` | unseen | not recommended | +0.0006 ±0.0008 | +0.0001 ±0.0007 | -3.3 | refit b53 -3.3 | 16 |
| timing `7d1d53e0e9` | unseen | not recommended | +0.0003 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| timing `bab31303c7` | unseen | not recommended | +0.0003 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| hybrid `dadc98c6cf` | unseen | not recommended | -0.0005 ±0.0004 | -0.0000 ±0.0004 | -4.7 | refit b53 -4.7 | 0 |
| hybrid `08af022b1f` | unseen | not recommended | -0.0005 ±0.0004 | -0.0000 ±0.0004 | -4.7 | refit b53 -4.7 | 0 |
| hybrid_est `176cf025c5` | unseen | not recommended | +0.0000 ±0.0009 | -0.0007 ±0.0008 | -4.5 | refit b53 -4.5 | 46 |
| blind_est `889d63bd3b` | unseen | not recommended | +0.0006 ±0.0008 | +0.0001 ±0.0007 | -3.3 | refit b53 -3.3 | 17 |
| blind_est `ca49cd5747` | unseen | not recommended | +0.0007 ±0.0008 | +0.0001 ±0.0008 | -3.2 | refit b53 -3.2 | 100 |
| hybrid `bfe2012c13` | unseen | not recommended | -0.0005 ±0.0004 | -0.0000 ±0.0004 | -4.7 | refit b53 -4.7 | 0 |
| hybrid `c89e30cf50` | unseen | not recommended | -0.0005 ±0.0004 | -0.0000 ±0.0004 | -4.7 | refit b53 -4.7 | 0 |
| hybrid_est `3ca1ced03f` | unseen | not recommended | +0.0001 ±0.0009 | -0.0007 ±0.0008 | -4.4 | refit b53 -4.4 | 41 |
| blind_est `aa89b1e54e` | unseen | not recommended | +0.0005 ±0.0009 | +0.0006 ±0.0009 | -3.1 | refit b53 -3.1 | 128 |
| blind_est `b814cf06fd` | unseen | not recommended | +0.0007 ±0.0008 | +0.0001 ±0.0008 | -3.1 | refit b53 -3.1 | 103 |
| hybrid `f338cc24c5` | unseen | not recommended | -0.0004 ±0.0004 | -0.0000 ±0.0004 | -4.0 | refit b53 -4.0 | 0 |
| hybrid `b97678f035` | unseen | not recommended | -0.0004 ±0.0004 | -0.0000 ±0.0004 | -4.0 | refit b53 -4.0 | 0 |
| blind_est `731b769e68` | unseen | not recommended | +0.0001 ±0.0012 | +0.0015 ±0.0011 | -3.0 | refit b53 -3.0 | 272 |
| blind_est `ed8226db16` | unseen | not recommended | +0.0006 ±0.0008 | +0.0001 ±0.0007 | -3.5 | refit b53 -3.5 | 14 |
| hybrid `bf28b79902` | unseen | not recommended | -0.0004 ±0.0004 | +0.0001 ±0.0004 | -3.8 | refit b53 -3.8 | 0 |
| blind_est `8cfbaa8061` | holdout | not recommended | +0.0006 ±0.0007 | -0.0002 ±0.0006 | -3.3 | refit b36 -3.3 | 126 |
| timing `79977000b8` | holdout | recommendable for the hard test | +0.0009 ±0.0005 | +0.0006 ±0.0005 | -1.2 | refit b88 -1.2 | 0 |
| hybrid `23548db80f` | holdout | not recommended | -0.0000 ±0.0000 | -0.0000 ±0.0000 | -1.8 | refit b104 -1.8 | 0 |
| hybrid_est `59f17ee96d` | holdout | not recommended | +0.0008 ±0.0007 | -0.0005 ±0.0006 | -5.4 | refit b88 -5.4 | 60 |
| blind_est `48eb53f02c` | unseen | not recommended | +0.0006 ±0.0008 | +0.0001 ±0.0007 | -3.5 | refit b53 -3.5 | 14 |
| blind_est `a3a884b6a8` | unseen | not recommended | +0.0006 ±0.0008 | +0.0001 ±0.0007 | -3.5 | refit b53 -3.5 | 14 |
| timing `128e30a01a` | unseen | not recommended | +0.0003 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| timing `fa05894ef2` | unseen | not recommended | +0.0003 ±0.0006 | -0.0002 ±0.0008 | -1.2 | refit b70 -1.2 | 0 |
| hybrid `127f017d7d` | unseen | not recommended | -0.0004 ±0.0004 | +0.0000 ±0.0004 | -4.5 | refit b53 -4.5 | 0 |
| hybrid `a95a32a127` | unseen | not recommended | -0.0004 ±0.0004 | -0.0000 ±0.0004 | -4.0 | refit b53 -4.0 | 0 |
| hybrid_est `dc89066586` | unseen | not recommended | +0.0001 ±0.0009 | -0.0006 ±0.0008 | -4.4 | refit b53 -4.4 | 43 |
| hybrid_est `a3401b3e7f` | unseen | not recommended | +0.0001 ±0.0009 | -0.0006 ±0.0008 | -4.4 | refit b53 -4.4 | 46 |
