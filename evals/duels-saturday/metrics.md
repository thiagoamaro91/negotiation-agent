# duels-saturday: metrics

Saturday's real duels replayed through `agent/duel.py` with `tools/duel_arena.duels1_replay`, on the real tick
timeline (duels overlap as they did, so they share the team's one accept per tick). One case = one duel; `tags[0]`
is the server session (`s2-duels-i` = Duels I, 16 ticks, decay 0.06). Any later price-only session found under
`--logs <dir>/duels/` is picked up and tagged by session; a two-issue session (Duels II onward) is listed as
excluded, because `duels1_replay` is price-only (it drops the rival's day) and would score it wrong.

At 20:51 on Saturday the logs hold Duels I only (Duels II had not started): 34 duels, 25 cases, 9 excluded
(listed in `cases.md`): 2 still `live` with no rival price (the clock stopped before their deadline), 7 where the
rival never posted a price (5 no-deals, and 2436/2437 where a silent rival took our offer: replay rivals never
accept, so nothing can happen there). Runner: `tools/eval_duels.py --flow duels-saturday --logs /Volumes/bazaar/logs`.

## Known limitation of this replay (read before trusting a number)

- **Rivals are fixed price paths and never accept.** Where we really accepted, the rival's path ends there, so
  waiting longer than we did finds nothing better: this replay can only show what waiting COSTS, never what it
  gains. Two real deals (2498/2499, tag `real:rival_took_ours`) came from the rival taking our last-chance offer;
  the replay cannot reproduce them, so their `vs_real` (-0.086 / -0.070) is an artifact of the model.
- **The pie is unknown** (the paired limit was never found in Duels I, 0/34), so `score` here is our surplus /
  our limit x (1 - decay)^rounds, the arena's Duels I proxy, not the rules' share of the pie. It is comparable
  between policies on these cases, not with the Friday or arena numbers.

## Metrics (per case; `_state.json` is the contract)

| id | kind | what it measures |
|---|---|---|
| `score` | float, headline | Surplus / our limit x (1 - decay)^rounds (as `duels1_replay` computes it), 0 for no deal, clipped to [-1, 1]. |
| `deal` | 0/1 | A deal was reached. |
| `missed_ok_offer` | 0/1, lower is better | The policy saw a rival offer worth at least 1 P and still ended with no deal. |
| `limit_breach` | 0/1, must be 0 | We sent, or a deal closed at, a price past our own limit. |
| `vs_real` | float | Replayed `score` minus the real one (server `result` / our limit; `result` is surplus x decay, in P). |

Perf fields: `surplus_P`, `rounds`, `deal_tick`, `msgs_sent`, `best_offer_score` (best rival offer taken silently:
the per-case ceiling), `real_result_P`, `vs_real_P` (replayed result minus server result, primas). Cases also carry
`real_closed_by` (us: we took the rival's price; rival: it took ours).

The 0/1 metrics are declared `kind: float` so that `score` is the report's headline column (the builder picks the
first `binary` metric); the runner prints Wilson intervals for them. Decision for sign-off.

## Considered and left out

- The rules' share of the pie: the rival's limit is unknown in Duels I; inventing a pie would add a model error
  larger than most policy differences (the surplus / limit proxy keeps the ranking honest).
- Score of the excluded no-price duels: rivals never accept in this replay, so every policy would score 0 there.
- Rounds and message count as graded metrics: priced into `score`; kept as perf fields.
- Accept-path re-read and `accept_mismatch`: live I/O only.
- The real run's own decisions (`logs/duel/2026-10-03.jsonl`): used only to read duel lengths (`total_ticks`); the
  real outcome comes from the server's duel files.

## Harness checks (scratch runs, not in this directory)

| policy | score | deal | missed_ok | breach | vs_real |
|---|---|---|---|---|---|
| baseline (duel.py + duels2-final) | 0.188 +- 0.059 | 21/25 | 1/25 | 0/25 | -0.008 |
| oracle (best slot-feasible silent accepts) | 0.192 | 22/25 | 0/25 | 0/25 | -0.004 |
| null | 0.000 | 0/25 | 22/25 | 0/25 | -0.196 |
| reckless | -0.137 | 25/25 | 0/25 | 25/25 | -0.333 |

The oracle equals the unconstrained ceiling (mean `best_offer_score` 0.1925): 3 duels never had an in-limit offer.
Run-to-run noise is zero (deterministic).

## Noise

Mean score 0.188 +- 0.059 (95% CI, n = 25, per-case sd 0.151). The baseline is already within 0.004 of the oracle
here, so this flow mostly guards against regressions (a lost slot or a missed in-limit offer shows as a whole case
going to 0). Unrelated policies need a gap of about 0.084 to clear case sampling; a paired gap needs
1.96 x sd(per-case difference) / sqrt(25). One duel losing a 0.15 deal moves the mean by 0.006.
