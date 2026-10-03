# Broker eval: confirmation run (2026-10-03)

Variant `v1` = `broker.py --policy ours` (BenchPolicy) against `baseline` = `--policy stall`, 50 seeds per synthetic
scenario, 298 shared cases, both runs on the same frozen copy of today's log (`/Volumes/bazaar/logs`, taken at 21:29;
4 real sessions, refit `fitted@5b3f29`). Paired delta v1 - baseline on `bench_score`, 95% CI = 1.96 SE.

| group | n | Δ bench_score | 95% CI | dropped (base → v1) | bad_match |
|---|---|---|---|---|---|
| real (b36, b53, b70, b88) | 4 | 0.000 | identical | 0 → 0 | 0 |
| fitted | 50 | 0.000 | identical | 0 → 0 | 0 |
| fitted_expiry_exact | 50 | +0.030 (SE 0.013) | [+0.004, +0.056] | 0 → 3 | 0 |
| hard_expiry_exact | 49 | +0.017 (SE 0.018) | [-0.018, +0.053] | 0 → 1 | 0 |
| standard / hard / adversarial | 48 / 50 / 47 | 0.000 | identical | 0 → 0 | 0 |
| all | 298 | +0.008 | [+0.001, +0.015] | 0 → 4 | 0 |

**Decision: keep `stall` for Sunday.** The pre-registered rule asked for a paired gain above 2 SE on the scenarios
refit on today's log, no loss beyond noise elsewhere, `bad_match` = 0 and `dropped` not higher. On `fitted` (today's
real conditions) the two policies are identical case for case, so there is no gain to clear; the only gain is on
`fitted_expiry_exact` (+0.030, 2.3 SE), a counterfactual where each offer shows its own expiry, and there `ours` also
leaves 3 crossable pairs unmatched where the stall leaves none (plus 1 on `hard_expiry_exact`), which breaks the
`dropped` guardrail. Nothing got worse and `bad_match` stayed 0. The reason for the tie is in the log: in all four real
sessions today every bench offer carried one and the same expiry, the session end (b36 457, b53 697, b70 937, b88
1177), so BenchPolicy has nothing to wait for and plays the stall's rule. `ours` only becomes worth revisiting if a
Sunday session shows per-offer expiries that differ from the session end, and even then it must stop dropping pairs.
