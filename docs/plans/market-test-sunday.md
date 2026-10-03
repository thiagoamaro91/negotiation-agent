# Market Test, Sunday: which broker policy runs v20

Written 4 Oct, 02:00, lane WP2. **Decision: `stall` in all five tests.** The broker line is the same all day: `agent/broker.py run --policy stall`. There is no policy switch, so no restart is needed.

| Test (wall, approx.) | Mix | Broker line | Why |
|---|---|---|---|
| 09:39 hard | 12 firmer, more impatient traders, 16 ticks | `agent/broker.py run --policy stall` | maxpairs loses on `hard` (-0.0072, z -11.3) |
| 09:49 | standard, 16 ticks | same process | maxpairs loses on `standard` and on all 5 real sessions |
| 10:49 | standard | same process | same |
| 11:49 | standard | same process | same |
| 13:49 | standard | same process | same |

## The hypothesis tested

`maxpairs`: every tick, among the offers whose quotes cross now, the matching with the most pairs. Ties go to the largest sum of (bid - ask). Each pair trades at its midpoint, the quotes are always respected, and the two offers come from one bench run. The idea: firm, impatient traders who are left unmatched by the stall's best-against-best order are lost forever. Example: bids 50 and 40 against asks 45 and 35. The stall makes one pair, maxpairs makes two.

The implementation is exact and lives in `tools/bench_sim.py` (`maxpairs_run`). Neighbourhoods are nested, so n pairs exist iff the n highest bids and the n lowest asks pair in reverse order. A test checks this against an exhaustive max-weight matching with weight BIG + (bid - ask) on 1,500 random books, fees included. When the stall already has the most pairs, maxpairs returns the stall's own plan.

## Decision rule (fixed before the runs)

- Ship maxpairs for the hard test only if it beats the stall on `hard` by more than 2 SE **and** is never worse than the stall beyond noise (95 % CI) in any other scenario.
- Ship it for the standard tests only if it also wins by more than 2 SE on `standard` or on the refit real sessions.
- Otherwise `stall` everywhere.

**Result: it fails at the first step.** On `hard` maxpairs is worse by 11 SE. It is worse beyond noise in 10 of the 12 required scenarios and in all 6 real-session refits. `bad_match` is 0 everywhere.

## Numbers

Each row has 2,000 seeds × 4 sessions, paired: both policies see the same traders. SE = session SD / √n. 95 % CI = 1.96 SE. Efficiency is the true gains realised over the best possible gains.

| scenario | sessions | stall | maxpairs | ceiling | maxpairs − stall | SE | 95 % CI | z | win / tie / loss | bad_match | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hard | 8000 | 0.814 | 0.807 | 0.904 | -0.0072 | 0.0006 | ±0.0012 | -11.3 | 8.1% / 79.9% / 12.0% | 0 | worse |
| firm_50 | 7996 | 0.873 | 0.869 | 0.953 | -0.0045 | 0.0006 | ±0.0011 | -7.7 | 6.0% / 85.7% / 8.3% | 0 | worse |
| firm_80 | 7997 | 0.841 | 0.840 | 0.929 | -0.0015 | 0.0007 | ±0.0013 | -2.3 | 7.9% / 84.2% / 7.9% | 0 | worse |
| firm_100 | 7999 | 0.826 | 0.827 | 0.915 | +0.0012 | 0.0007 | ±0.0013 | +1.9 | 8.7% / 84.8% / 6.5% | 0 | tie |
| all_impatient | 7996 | 0.815 | 0.808 | 0.887 | -0.0064 | 0.0005 | ±0.0011 | -11.7 | 4.6% / 87.1% / 8.3% | 0 | worse |
| short_patience | 7994 | 0.823 | 0.813 | 0.904 | -0.0096 | 0.0006 | ±0.0012 | -15.2 | 4.3% / 86.1% / 9.6% | 0 | worse |
| imp_70 | 7998 | 0.861 | 0.852 | 0.935 | -0.0090 | 0.0006 | ±0.0012 | -15.2 | 4.7% / 85.2% / 10.1% | 0 | worse |
| standard | 7999 | 0.894 | 0.886 | 0.965 | -0.0082 | 0.0006 | ±0.0011 | -14.5 | 4.7% / 85.7% / 9.7% | 0 | worse |
| thin_overlap | 8000 | 0.935 | 0.936 | 0.983 | +0.0016 | 0.0004 | ±0.0007 | +4.3 | 9.1% / 84.2% / 6.7% | 0 | better |
| wide_overlap | 7995 | 0.888 | 0.875 | 0.967 | -0.0136 | 0.0007 | ±0.0013 | -20.9 | 3.7% / 84.3% / 12.0% | 0 | worse |
| arrive_all0 | 7997 | 0.960 | 0.952 | 0.993 | -0.0074 | 0.0008 | ±0.0015 | -9.9 | 17.9% / 57.3% / 24.8% | 0 | worse |
| arrive_late | 7999 | 0.875 | 0.869 | 0.954 | -0.0064 | 0.0006 | ±0.0011 | -11.4 | 5.1% / 86.1% / 8.8% | 0 | worse |
| refit pooled (5 runs) | 8000 | 0.801 | 0.785 | 0.888 | -0.0162 | 0.0006 | ±0.0011 | -28.1 | 8.4% / 67.6% / 24.0% | 0 | worse |
| refit b36 | 8000 | 0.797 | 0.776 | 0.888 | -0.0210 | 0.0006 | ±0.0012 | -34.7 | 5.8% / 68.4% / 25.7% | 0 | worse |
| refit b53 | 8000 | 0.780 | 0.765 | 0.867 | -0.0147 | 0.0006 | ±0.0011 | -25.8 | 5.8% / 76.0% / 18.2% | 0 | worse |
| refit b70 | 8000 | 0.809 | 0.791 | 0.888 | -0.0181 | 0.0006 | ±0.0011 | -32.2 | 7.8% / 65.3% / 26.9% | 0 | worse |
| refit b88 | 7999 | 0.755 | 0.740 | 0.841 | -0.0147 | 0.0006 | ±0.0011 | -26.3 | 5.4% / 75.9% / 18.7% | 0 | worse |
| refit b104 | 8000 | 0.790 | 0.782 | 0.872 | -0.0079 | 0.0005 | ±0.0010 | -16.0 | 9.3% / 72.6% / 18.0% | 0 | worse |

Across all 48 simulator scenarios (`--scenarios all`), maxpairs is worse beyond noise in 42. It is better by more than 2 SE in these 4:

- `adversarial` +0.042
- `shade_fix40` +0.0025
- `hard_all0` +0.0027
- `thin_overlap` +0.0016

**Real paths, no simulator.** Nothing was matched in b36 (the guard bug), so every trader's whole quote path is on record. Replaying those paths gives (`bench_sim.py replay --run b36`, limits proxied by the last quote Q, or with unmoved quotes shaded a further 15 % F15):

- stall: 4 matches, 0.980 (Q) / 0.983 (F15). This matches the Saturday audit's replay.
- maxpairs: 5 matches, 0.800 / 0.821.

Recorded books b53 to b104 cannot be replayed this way, because our matches cut the paths short. On those books the stall was already maximal in every state, so maxpairs would have sent exactly the same matches as recorded. All 6 states where the two differ are in b36.

## Second candidate: maxweight (independent review)

A reviewer pointed out a counterexample: maximising the count is not maximising surplus. Asks 50 and 65, bids 70 and 55, true values 80 and 55, costs 50 and 65, everyone firm and present for one tick. The stall makes 70×50 and gains 30. Two pairs gain 20.

So a second candidate was tested. `maxweight` (`bench_sim.maxweight_plan`) is a max-weight matching over the pairs that cross now, with pair weight = bid/(1-0.15) - ask×(1-0.15). That is the estimated true surplus under the policy's own firm-shade prior; only positive pairs count. It ran on **unseen seeds**: each seed is `random.Random("unseen:<scenario>:<seed>")`, 1,000 seeds × 4 sessions, which the table above never drew. `bad_match` is 0. To reproduce, run `python3 tools/bench_sim.py candidate --policy maxweight --seeds 1000 --scenarios <list> --refit-runs all,b36,b53,b70,b88,b104`. Results, maxweight − stall:

| scenario | sessions | Δ | SE | z |
|---|---|---|---|---|
| hard | 4000 | -0.0011 | 0.0007 | -1.5 |
| standard | 3999 | -0.0034 | 0.0006 | -5.5 |
| firm_100 | 4000 | +0.0060 | 0.0008 | +7.1 |
| all_impatient | 3999 | -0.0020 | 0.0006 | -3.3 |
| short_patience | 3998 | -0.0038 | 0.0007 | -5.7 |
| wide_overlap | 3997 | -0.0035 | 0.0006 | -6.0 |
| thin_overlap | 4000 | +0.0023 | 0.0005 | +4.4 |
| arrive_all0 | 3999 | +0.0076 | 0.0007 | +10.1 |
| arrive_late | 3996 | -0.0039 | 0.0007 | -5.6 |
| shade_40 | 4000 | -0.0005 | 0.0006 | -0.8 |
| concede_late | 3994 | -0.0015 | 0.0007 | -2.2 |
| refit pooled / b36 / b53 / b70 / b88 / b104 | 4000 each | -0.0054 / -0.0094 / -0.0065 / -0.0081 / -0.0064 / -0.0048 | 0.0006 | -9.4 to -15.6 |

Under the same rule, maxweight does not ship either. It does not beat the stall on hard (it is -1.5 SE), and it is worse beyond noise on `standard` and on every real-session refit. Of the scenarios tested, it wins by more than 2 SE in three: `firm_100` +0.0060, `thin_overlap` +0.0023 and `arrive_all0` +0.0076.

**Settlement stress (not simulated).** The simulator settles a match inside the tick it is sent. If the real venue settles on the next tick, a match sent at tick t to a trader who leaves at t can be lost. That cost can fall on either policy. Take asks 35 and 45 and bids 50 and 40, with true limits equal to the quotes, and suppose only the 50-bidder leaves before settlement. The stall's one pair (50×35) is lost and it gets 0. maxpairs keeps 40×35 and gets 5. The effect of next-tick settlement is therefore unknown until the order of settlement and expiry is verified on the real venue. The exception fallback cannot catch a policy that is valid but economically worse; only the decision rule above can, and it says stall.

## Why it loses

The stall stops at the first pair where the next-best bid is below the next-best ask, which is the competitive cut on quotes. maxpairs goes past that cut. Every pair it executes respects the quotes, so its true surplus is never negative: value ≥ bid ≥ ask ≥ cost. In the task's example, it makes 50×45 and 40×35, which gain 15 and 5 on quotes, where the stall makes one pair worth 30.

The loss comes from **displacement**. To reach the extra pair, maxpairs re-pairs the book. It spends the cheap seller and the high bidder on lower-surplus pairs, and it uses up resting quotes that a better counterpart arriving later would have crossed. In b36 at tick 447 it sold the cheap seller (ask 26) to a 31 bidder, so buyer b36-7 had to take the 81 seller one tick later: -37 in total against the stall's path.

Two counterfactual marginal contributions describe the added traders. These are not executed trades. The first is the buyers' true values minus the sellers' true costs for the offers maxpairs matches and the stall does not, in that tick. On `hard` this is +4.0 on average and negative 33 % of the time (diagnostic sample: seeds 0–999, 4,000 sessions). The second is the matches it adds per session: +0.78 among the sessions where the two differ. In that sample maxpairs loses 510 sessions and wins 336. In the 8,000-session table run it loses about 959 sessions (12.0 %) and wins about 648 (8.1 %).

Observed winners, beyond 2 SE:

- `adversarial` +0.042: shading up to 40 %, 60 % firm, concede late and only to 60 %, everyone at tick 0.
- `hard_all0` +0.0027
- `shade_fix40` +0.0025
- `thin_overlap` +0.0016: staggered arrivals, 25 % firm, shading at most 30 %, buyers' values 45–80 against sellers' costs 20–55.

`firm_100` is +0.0012 (1.9 SE). A reading, not a measurement: what these winners share is that most traders are in the money, either because shading is deep and never relaxes or because the value and cost ranges barely compete, so a displaced pair rarely costs a better one. Saturday's sessions look like none of them: fitted shading 0.25–0.38, 0–19 % firm, 83–91 % impatient, overlapping value and cost ranges. None of the winning conditions can be recognised live before a session ends, so no variant is worth building tonight.

## Caveats

- The simulator is pessimistic in level. On fitted mixes it gives the stall about 0.80, while the real stall scored 0.90–0.97. Read it only for paired differences.
- No hard test has been observed yet. `hard` is the organisers' description, and the hard twists (`hard_all0`, `hard_firm_80`, `hard_shade_40`) go both ways within ±0.003.
- Each seed's 4 sessions are independent draws, and both policies are stateless, so sessions are the sample unit.

## Factory note (for WP5, who owns tools/factory_sunday.json; this lane did not edit it)

- Broker line for all five tests: `["{python}", "-u", "agent/broker.py", "run", "--policy", "stall"]`. This is unchanged from the current file.
- `--policy` is read once at process start (argparse into `Desk`). It cannot change at runtime, and switching would mean a restart, which is forbidden during a test. Run one process for the whole day.
- PR #63 (`fix(broker): 15 s tick pace`) changes timeouts and the per-loop read budget only. Once it merges, update the broker note's "Market audit fix 5 ... is not merged" sentence. The command does not change.

## 15 s pace

Reads happen twice a second and the clock once a second. All counters are in ticks, a heartbeat is written every loop, and a log row every tick. Nothing assumed 30 s except the network settings and the read count per loop:

- A 5 s timeout with one retry, plus a backoff of up to 5 s, could blind the loop for about 15.5 s, a whole tick.
- A changed book could cost three reads before its matches went out.

PR #63 sets reads to 4 s with no retry. That figure is above Saturday's measured request time per loop: p50 0.18 s, p99 0.47 s over 1,172 windows. The PR also caps the backoff at 2 s, keeps matches at 5 s, and limits a loop to two reads before it sends once it has spent more than 1 s on reads. Guarantee:

- A failed read costs at most 4 s plus the backoff.
- With reads answering in r seconds, a changed book's matches leave at most max(2r, 1 + r) after the loop starts.

Not bounded (inherited, not changed):

- Several slow matches in a row can still use up a tick without a fresh book read. `MATCH_TIMEOUT` is per request, not a deadline for the batch.
- A match refused for a transient reason is not resent within the same tick. Saturday had 0 refusals in 21 matches.

## Reproduce

```bash
python3 tools/bench_sim.py table --seeds 2000 --procs 8 --scenarios hard,firm_50,firm_80,firm_100,all_impatient,short_patience,imp_70,standard,thin_overlap,wide_overlap,arrive_all0,arrive_late
python3 tools/bench_sim.py refit --log logs/broker/2026-10-03.jsonl --seeds 2000            # pooled; add --runs b53 for one session
python3 tools/bench_sim.py replay --log logs/broker/2026-10-03.jsonl --run b36
python3 tools/bench_sim.py candidate --policy maxweight --seeds 1000 --scenarios hard,standard,firm_100,all_impatient,short_patience,wide_overlap,thin_overlap,arrive_all0,arrive_late,shade_40,concede_late --refit-runs all,b36,b53,b70,b88,b104
```
