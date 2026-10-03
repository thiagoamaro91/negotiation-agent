# Dealer config grid (directional)

27 configs = `abuela.cap` {22, 23, 25} x `chato.rare.max_bid` {none, 84, 90} x `chato.rare.step` {1, 2, 4}. The approved
plan had steps {1, 2}; step 4 (the baseline's) was added so the baseline's own Chato setting is in the grid (the
`cap22 / none / 4` row reproduces the baseline exactly: an A/A check). Everything else is the baseline
(`tools/factory_sunday.json`). Each config: 22 cases x 5 dealer-model draws (`--seed 0`, reps 0-4), paired per
(case, rep) with `baseline/` on the same draws; logs = one read-only snapshot of the Mini's logs taken 21:33 on Saturday,
used for the baseline re-grade and every config. Runner: `tools/eval_dealers.py --set abuela.cap=.. --set
chato.rare.max_bid=.. --set chato.rare.step=..`.

Case-level mean +- 95 % CI over the 22 cases; paired delta = mean over cases of (config - baseline), CI over cases.
A/A noise floor (baseline even vs odd reps): `deal_in_limit` +-0.06, `range_share` +-0.05. No train/test split (22
cases; a held-out slice would have no power): **every delta here is directional, none is significant**.

`over RET` (projection, not a graded metric): of the replayed Abuela uncommon conversations (6 cases x 5 draws = 30, welcome
excluded), how many deals closed at a price above our value of RET-07/RET-08, Sunday's Abuela uncommon targets. Those
conversations were for cards worth more to us, so the price was in limit there; for RET-07/08 it would not be.

| config (cap / max-bid / step) | deal_in_limit | range_share | limit_breach | over_value | paired delta deal_in_limit | paired delta range_share | over RET / deals | chato-335 deals (5 draws) |
|---|---|---|---|---|---|---|---|---|
| **baseline** (22 / none / 4) | 0.736 +- 0.176 | 0.546 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.000 +- 0.000 | 0/19 | 88 88 88 - 88 |
| 25 / 84 / 1 | 0.836 +- 0.147 | 0.619 +- 0.138 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 | 77 86 86 - 77 |
| 25 / 84 / 2 | 0.836 +- 0.147 | 0.619 +- 0.138 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 | 77 86 86 - 77 |
| 25 / 90 / 1 | 0.836 +- 0.147 | 0.619 +- 0.138 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 | 77 86 86 - 77 |
| 25 / 90 / 2 | 0.836 +- 0.147 | 0.619 +- 0.138 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 | 77 86 86 - 77 |
| 25 / none / 1 | 0.836 +- 0.147 | 0.619 +- 0.138 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 | 77 86 86 - 77 |
| 25 / none / 2 | 0.836 +- 0.147 | 0.619 +- 0.138 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 | 77 86 86 - 77 |
| 25 / 90 / 4 | 0.836 +- 0.147 | 0.609 +- 0.139 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.062 +- 0.079 | 11/30 | 88 88 88 - 88 |
| 25 / none / 4 | 0.836 +- 0.147 | 0.609 +- 0.139 | 0.000 | 0.000 | +0.100 +- 0.123 | +0.062 +- 0.079 | 11/30 | 88 88 88 - 88 |
| 25 / 84 / 4 | 0.800 +- 0.165 | 0.588 +- 0.149 | 0.000 | 0.000 | +0.064 +- 0.147 | +0.042 +- 0.091 | 11/30 | - - - - - |
| 23 / 84 / 1 | 0.782 +- 0.163 | 0.591 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 | 77 86 86 - 77 |
| 23 / 84 / 2 | 0.782 +- 0.163 | 0.591 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 | 77 86 86 - 77 |
| 23 / 90 / 1 | 0.782 +- 0.163 | 0.591 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 | 77 86 86 - 77 |
| 23 / 90 / 2 | 0.782 +- 0.163 | 0.591 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 | 77 86 86 - 77 |
| 23 / none / 1 | 0.782 +- 0.163 | 0.591 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 | 77 86 86 - 77 |
| 23 / none / 2 | 0.782 +- 0.163 | 0.591 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 | 77 86 86 - 77 |
| 23 / 90 / 4 | 0.782 +- 0.163 | 0.580 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.034 +- 0.067 | 5/24 | 88 88 88 - 88 |
| 23 / none / 4 | 0.782 +- 0.163 | 0.580 +- 0.147 | 0.000 | 0.000 | +0.045 +- 0.089 | +0.034 +- 0.067 | 5/24 | 88 88 88 - 88 |
| 23 / 84 / 4 | 0.745 +- 0.177 | 0.560 +- 0.156 | 0.000 | 0.000 | +0.009 +- 0.117 | +0.014 +- 0.080 | 5/24 | - - - - - |
| 22 / 84 / 1 | 0.736 +- 0.176 | 0.556 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.010 +- 0.020 | 0/19 | 77 86 86 - 77 |
| 22 / 84 / 2 | 0.736 +- 0.176 | 0.556 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.010 +- 0.020 | 0/19 | 77 86 86 - 77 |
| 22 / 90 / 1 | 0.736 +- 0.176 | 0.556 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.010 +- 0.020 | 0/19 | 77 86 86 - 77 |
| 22 / 90 / 2 | 0.736 +- 0.176 | 0.556 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.010 +- 0.020 | 0/19 | 77 86 86 - 77 |
| 22 / none / 1 | 0.736 +- 0.176 | 0.556 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.010 +- 0.020 | 0/19 | 77 86 86 - 77 |
| 22 / none / 2 | 0.736 +- 0.176 | 0.556 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.010 +- 0.020 | 0/19 | 77 86 86 - 77 |
| 22 / 90 / 4 | 0.736 +- 0.176 | 0.546 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.000 +- 0.000 | 0/19 | 88 88 88 - 88 |
| 22 / none / 4 | 0.736 +- 0.176 | 0.546 +- 0.155 | 0.000 | 0.000 | +0.000 +- 0.000 | +0.000 +- 0.000 | 0/19 | 88 88 88 - 88 |
| 22 / 84 / 4 | 0.700 +- 0.187 | 0.526 +- 0.162 | 0.000 | 0.000 | -0.036 +- 0.071 | -0.020 +- 0.040 | 0/19 | - - - - - |

## What moves, and on what evidence

- Only 4 of the 22 cases ever move (`pilar.*`, `chato.uncommon`, `chato.sell` are untouched by these knobs): abuela-105
  (cap >= 23), abuela-117 and abuela-80 (cap 25), chato-335 (any Chato change).
- **Abuela cap: replayed real numbers.** abuela-105 and abuela-117 replay the real thread to the end (no model answer):
  her real final offers were 23 and 25, which cap 22 walks from and cap 23 / 25 take. abuela-80 (cap 25) is modelled.
- **Chato rare: dealer model only.** chato-335 is the only Chato rare case. Steps 1 and 2 leave the real path at our
  2nd offer and the deal is then his drawn limit (no real final exists in that thread); step 4 replays the real path to
  84 and the 88 bid is answered by the model. `--max-bid 84` with step 4 pins at 84 against his real 90 and closes:
  no deal in 5/5 draws. `--max-bid 90` is above `--cap 88`, so it never binds (identical to none). The model is known
  to be optimistic on Chato rares (held-out one-step error 1.71 P on this thread, `metrics.md`) and cannot move his
  limit or patience with the step, so the step 1-2 gain (+0.010 range_share) hinges on the dealer model, not on data.
- `limit_breach` and `over_value` are 0 in every config: the harness hands the bot a limit of min(our value, cap), so
  the replay cannot overpay by construction; `over RET` is where the Sunday risk shows (see `recommended.md`).

