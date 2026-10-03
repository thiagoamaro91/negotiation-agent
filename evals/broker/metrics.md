# Broker eval: metrics (proposed, awaiting sign-off)

Flow `broker`, runner `tools/eval_broker.py`. The Market Test scores "the share of the possible gains you realise"
between the bench traders' TRUE limits (kit/RULES.md, "Your own market"); every metric below is computed by code, per
case, from the matches the policy's code path (`agent/broker.py` `plan_book`: policy + guard + safety net) would send.

## Metrics (headline first)

| id | kind | what | real cases | synthetic cases |
|---|---|---|---|---|
| `bench_score` | float 0-1, higher | The Market Test's own metric: realised gains / best possible gains (max-weight matching on limits, ignoring time: bench_sim's A8 denominator). | on REVEALED limits (a buyer's highest bid seen, a seller's lowest ask seen) | on true limits |
| `surplus_captured` | float 0-1, higher | Realised gains / the quote-respecting ceiling (max-weight matching over pairs that ever crossed while both were on the book). 1.0 = nothing reachable was left; the ORACLE scores exactly 1. | ceiling on the recorded book | `bench_sim.ceiling_gain` |
| `dropped` | count, lower | Guardrail: crossable pairs left unmatched at session end (the most disjoint pairs that crossed on a book the policy saw, with neither offer ever matched). The stall's rule can never leave one; a waiting policy can. | yes | yes |
| `bad_match` | 0/1, must be 0 | Guardrail: the policy proposed any match the server would refuse (not crossing, price outside `[ask, bid - fee]`, offer reused, two runs, not a seller and a buyer) or one with a negative gain at the limits. Declared `float` in `_state.json` only so the lite report keeps `bench_score` as its headline (it picks the first binary metric). | yes | yes |
| `live_agree` | float 0-1 | Real only: Jaccard overlap of the replay's pairs with the pairs the live broker matched (its `matched` log events). A replay-fidelity check: the stall replay must give 1.0 wherever the live broker ran the stall without faults. | yes | n/a |
| `vs_live` | float, higher | Real only: (replay gains - live broker's gains) / best, on revealed limits: what the policy would have added to what really happened. | yes | n/a |

Perf fields: `latency_s`, `matches`, `ticks`, `guard_dropped` (matches the guard dropped before sending).

## Considered and LEFT OUT

- **bench_points as a grade**: the points depend on the stall's score and the mean of the top three venues in the same
  session, which we cannot see; `score.jsonl` is attached to real cases as `meta` (`bench_points_before/after`) only.
  Today it is attributable to one session at most (b36: 0.5 before, 0.241 after; the log stops at tick 630).
- **Per-trader surplus split / price**: the price moves gains between buyer and seller, not the total the test scores.
- **Matches count**: activity never scores (RULES "What never counts"); kept as a perf field only.
- **Public (team) offers on our venue**: not part of the Market Test, and their text is game text; out of scope.
- **Refusals by the live server (races, settling)**: the offline engine has no races; covered by tests/test_broker.py.
- **An LLM judge**: every quantity here is numeric; a judge would add noise, not information.
- **Efficiency on true limits for real cases**: true limits are hidden; revealed limits are the best lower bound.

## Limitations

- **Real cases barely discriminate.** On revealed limits the stall already sits at the recorded ceiling
  (`surplus_captured` 1.0; the ORACLE scores the same 0.811). b53/b70/b88 were recorded under the live stall, so the
  books are censored by its own matches: an offer it matched vanishes, and a policy that waits sees it "leave". The
  assumption that offers do not react to our matches (they only leave the book) hides any counterfactual quote path.
  Use the real group as a fidelity and regression check (`live_agree`, `bad_match`, `dropped`); compare policies on
  the synthetic group.
- **Revealed limits understate gains** for traders matched on first sight (one quote seen, shading unknown).
- **Synthetic traders are bench_sim's model** (A1-A9: uniform limits, linear shading, patience mix, exogenous quotes),
  refitted on one day of 4 sessions (80 offers). The refit is rough by design; its `expiry` reading is corrected from
  `early` to `end` because every real run shows one expiry for all its offers (bench_sim's fit counts distinct
  expiries across runs). The `fitted*` case ids carry a hash of the fitted knobs, so a new log makes new cases.
- **Today every real expiry equals the session end**, so BenchPolicy is blind and plays the stall's exact rule on the
  real and `fitted` cases: a v1 can only differ on `*_expiry_exact` and the other lab scenarios.
- **Noise.** Policies are deterministic (reps add nothing). Baseline bench_score: synthetic 0.812 +- 0.050 (n=35),
  real 0.811 +- 0.134 (n=4). Paired floor: oracle - stall on the synthetic group is +0.104 +- 0.036 (sd of the
  per-case delta 0.11), so at 6 seeds per scenario a v1 must move bench_score by about 0.04 to clear noise; run
  `--seeds 50` (about 300 sessions, about 1 s) for a floor near +-0.012.
- One case (`syn-adversarial-s1`) is excluded: no pair ever crosses, so there is nothing to grade.
