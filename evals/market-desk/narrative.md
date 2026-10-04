# Market desk hill-climb (Saturday night, frozen feed to tick 1200)

| round | change | test Δ P ± 95% CI (cash 60) | test Δ P ± 95% CI (cash 319) | bad (60/319) | breach (60/319) | contested share of Δ (60 / 319) | plausible share of Δ (60 / 319) | verdict |
|---|---|---|---|---|---|---|---|---|
| P0 | baseline: defaults + `--no-team-venues` | test total +3.0 | test total +10.0 | 0/0 | 0/0 | - | - | reference |
| R1a | v1 `--min-cash 100` | +0.0 ± 0.0 | +80.2 ± 96.6 (z +1.6) | 0/0 | 0/0 | - / 86% | - / 14% | reverted (< 2 SE) |
| R1b | v2 `--min-cash 30` | +0.0 ± 0.0 | +69.2 ± 95.0 (z +1.4) | 0/0 | 0/0 | - / 100% | - / 0% | reverted (< 2 SE) |
| R2 | v3 `--team-venues` | +0.0 ± 0.0 | +1.0 ± 2.0 (z +1.0) | 0/0 | 0/0 | - / 0% | - / 0% | reverted (flat) |
| R3 | v4 `--cap-hour 150` | +0.0 ± 0.0 | +0.0 ± 0.0 | 0/0 | 0/0 | - | - | reverted (flat); protocol stops: 3 rounds without a keep |
| C1 | v5 = v2 + `--cap-hour 150` (vs v2) | +0.0 ± 0.0 | +0.0 ± 0.0 | 0/0 | 0/0 | - | - | flat on test (train +51.9 at cash 319) |
| C2 | v6 = v2 + `--team-venues` (vs v2) | +13.2 ± 19.6 (z +1.3) | +13.8 ± 25.0 (z +1.1) | 0/0 | 0/0 | 0% / 93% | 30% / 0% | positive in both worlds, < 2 SE |
| C3 | v7 = v2 + `--bid-step 3 --bid-step-ticks 10` (vs v2) | +0.0 ± 0.0 | +0.0 ± 0.0 | 0/0 | 0/0 | - | - | flat (train −5.5 at 319) |
| Composite | v8 = `--min-cash 30 --cap-hour 150 --team-venues`, picked on TRAIN, one test check (vs baseline) | +13.2 ± 19.6 (z +1.3) | +79.5 ± 96.0 (z +1.6) | 0/0 | 0/0 | 0% / 87% | 30% / 0% | never below baseline in any world or split; < 2 SE |

Setup. Two cash worlds, one flow dir each: `evals/market-desk/` is cash 60 (ledger −90 + Sunday's 150 allowance,
primary) and `evals/market-desk-319/` is cash 319 (account 169 + allowance); every `change.md` names its cash. Both
replay a frozen copy of the share's logs (feed to tick 1200, `me.json` of tick 630) with the grader floor at 0 P
(the bond is paid; the guardrail now means "never overdraw"), so `cash_floor_breach` only fires on a real overdraft.
Split: random, stratified by day, seed 7, 60 train / 40 test (`_state.json`); hypotheses came from train only, and
keep/revert from the paired test Δ. **Read the "test" columns as directional, not as a held-out test.** The cases are
card rows graded from one whole-day replay per variant, with cash, the spend caps and the one accept per tick shared
across the cards of a day, so a train row and a test row of the same day are coupled and the 40 test rows are not 40
independent draws. The paired 95% CIs treat them as independent, so they are narrower than the evidence supports. The earlier cash-355 baseline was moved out of the flow dir (scratchpad) because
its model label differs.

What it says. No single round clears the 2 SE bar, so by the protocol the winner is the Sunday baseline. That verdict
is about evidence, not direction: the test split holds few cases where the desk can act, and the gains come in lumps
of one or two cards. Every change that moved anything moved it upwards in both worlds, and nothing hit a guardrail.
Lowering `--min-cash` is the only change that matters at all: at 280 the desk cannot buy in either world, so team
venues and the hourly cap are invisible until it drops (R2 and R3 flat on the baseline, C1 and C2 live on v2). At
cash 60 the gain comes from team venues (0% contested, 30% from one plausible bid fill); at cash 319 it comes from
two rare buys that another team really took first (87% contested: races we would have to win). Bids add nothing in
the replay: faster stepping is flat, and the LAV-09 / LAV-10 bid churn costs about 0 P here (counterfactuals in
memory, `agent/` untouched: stable ranking 0 P in both worlds; no step reset on repost −7 to +7 P, all on non-LAV
cards), because the replay never shows a seller for those two at our prices. The recommendation is in
`recommended.md`.

## Review corrections (after the adversarial review of this PR)

**Fill evidence for our bids.** `verify_evidence` (tools/eval_market.py) accepted a cash listing addressed to another
team (`to` set) or attached to a thread as proof that our bid would have been filled. Such a listing is not open to our
bid (the desk's own `check_listing` refuses it), so the grader now rejects both. A test fails without the rejection
(`tests/test_eval_market.py`).

The replay was **not rerun** (the frozen copy of the share's logs is not on disk). I regraded from the stored
`results.jsonl` rows instead: the only rows with `plausible_fill` are three single-fill cases (`sat-SAL-02` +4.0,
`sat-RET-08` +5.5, `sat-SAL-09` +11.0 P), the feed shows each of the three listings carries a `to` (t16, t13 and t02 respectively, the SAL-09 one sent to eight teams),
and a rejected fill scores 0, so their surplus goes to 0. Nothing else in those rows changes. Result, paired vs baseline:

| comparison | as graded in the table above | with addressed listings rejected |
|---|---|---|
| cash 60, v8 (and v6 = v2 + team venues), test | +13.2 ± 19.6 P (z +1.3), 30% plausible | **+9.2 ± 18.1 P (z +1.0), 0% plausible** |
| cash 60, v8, train | +45.9 ± 57.0 P | unchanged |
| cash 319, v8, test | +79.5 ± 96.0 P (z +1.6) | unchanged (the same fill is in the baseline too) |
| cash 319, v1 (`--min-cash 100`), test | +80.2 ± 96.6 P (z +1.6) | +69.2 ± 95.0 P (z +1.4) |
| cash 319, v8 test totals: baseline / v8 | +10.0 / +89.5 P | +6.0 / +85.5 P |

So the 30% "inferred share" of the cash 60 gain was one addressed listing and falls to 0%: what is left of the cash 60
gain (+9.2 P, within noise) is team-venue trades with no inferred fill. The verdict does not change (no round clears 2
SE; the baseline is the winner by the protocol) and the cash 60 evidence for v8 is weaker than the table shows. Every
other row of the table is unchanged. The cases and results on disk were not rewritten; this section holds the
corrected numbers.
