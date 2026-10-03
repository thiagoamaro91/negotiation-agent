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

Across all 48 simulator scenarios (`--scenarios all`), maxpairs is worse beyond noise in 42. It is better by more than 2 SE in 4:

- `adversarial` +0.042
- `shade_fix40` +0.0025
- `hard_all0` +0.0027
- `thin_overlap` +0.0016

**Real paths, no simulator.** Nothing was matched in b36 (the guard bug), so every trader's whole quote path is on record. Replaying those paths gives (`bench_sim.py replay --run b36`, limits proxied by the last quote Q, or with unmoved quotes shaded a further 15 % F15):

- stall: 4 matches, 0.980 (Q) / 0.983 (F15). This matches the Saturday audit's replay.
- maxpairs: 5 matches, 0.800 / 0.821.

Recorded books b53 to b104 cannot be replayed this way, because our matches cut the paths short. On those books the stall was already maximal in every state, so maxpairs would have sent exactly the same matches as recorded. All 6 states where the two differ are in b36.

## Why it loses

The stall stops at the first pair where the next-best bid is below the next-best ask, which is the competitive cut on quotes. Every extra pair maxpairs adds therefore comes from traders whose quotes say they should not trade (bid_k < ask_k). They gain on true limits only when shading exceeds that gap:

- On `hard`, the traders it adds gain +4.0 on average, but 33 % of them lose value.
- Worse, they spend resting quotes that a later, better counterpart would have crossed. In b36 at tick 447 it sold the cheap seller (ask 26) to a 31 bidder, so buyer b36-7 had to take the 81 seller one tick later: -37 in total.
- In sessions where the two differ on `hard`, maxpairs makes more matches (+0.78) yet loses 510 times and wins 336.

It wins only when true limits sit far beyond quotes that never relax: shading 40 % or more, or everyone at tick 0 with deep shading (`adversarial`). Even `firm_100` is only +0.0012 (1.9 SE). Saturday's sessions are the opposite regime: fitted shading 0.25–0.38, 0–19 % firm, 83–91 % impatient. That regime cannot be recognised live before a session ends, so no firm-only variant is worth building tonight.

## Caveats

- The simulator is pessimistic in level. On fitted mixes it gives the stall about 0.80, while the real stall scored 0.90–0.97. Read it only for paired differences.
- No hard test has been observed yet. `hard` is the organisers' description, and the hard twists (`hard_all0`, `hard_firm_80`, `hard_shade_40`) go both ways within ±0.003.
- Each seed's 4 sessions are independent draws, and both policies are stateless, so sessions are the sample unit.

## Factory note (for WP5, who owns tools/factory_sunday.json; this lane did not edit it)

- Broker line for all five tests: `["{python}", "-u", "agent/broker.py", "run", "--policy", "stall"]`. This is unchanged from the current file.
- `--policy` is read once at process start (argparse into `Desk`). It cannot change at runtime, and switching would mean a restart, which is forbidden during a test. Run one process for the whole day.
- PR #63 (`fix(broker): 15 s tick pace`) changes timeouts only. Once it merges, update the broker note's "Market audit fix 5 ... is not merged" sentence. The command does not change.

## 15 s pace

Reads happen twice a second and the clock once a second. All counters are in ticks, a heartbeat is written every loop, and a log row every tick. Nothing assumed 30 s except the network settings: a 5 s timeout with one retry plus a backoff of up to 5 s could blind the loop for about 15.5 s, a whole tick. PR #63 fixes that: reads at 3 s with no retry, a backoff of at most 2 s, matches still at 5 s.

Not changed: a match refused for a transient reason is not resent within the same tick. Saturday had 0 refusals in 21 matches.

## Reproduce

```bash
python3 tools/bench_sim.py table --seeds 2000 --procs 8 --scenarios hard,firm_50,firm_80,firm_100,all_impatient,short_patience,imp_70,standard,thin_overlap,wide_overlap,arrive_all0,arrive_late
python3 tools/bench_sim.py refit --log logs/broker/2026-10-03.jsonl --seeds 2000            # pooled; add --runs b53 for one session
python3 tools/bench_sim.py replay --log logs/broker/2026-10-03.jsonl --run b36
```
