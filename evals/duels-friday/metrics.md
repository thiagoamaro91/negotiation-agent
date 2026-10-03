# duels-friday: metrics

Friday's practice duels (server session 1, 34 duels, 12 ticks, decay 0.06) replayed through `agent/duel.py` with
`tools/duel_arena.friday_replay`. One case = one duel. 18 cases; 16 excluded (10 where the rival never posted a price,
6 whose soft pie is under 3 P), listed at the end of `cases.md`. Runner: `tools/eval_duels.py --flow duels-friday`.

## Known limitation of this replay (read before trusting a number)

- **Rivals are fixed price paths.** They post exactly what Friday's bots posted, never react to what we say, and
  never accept our offer. So this replay can only show how well we *take* what was offered and what waiting or
  talking *costs*; it cannot show that an anchor or a last-chance offer would have been accepted.
- **The pie is soft.** The rival's limit is unknown; the pie is |our limit in the paired duel - our limit| (Friday:
  the rival's final landed within 7% of that in 6/8). Two duels (99/100) got rival offers far beyond it: their raw
  share is 2.06 / 1.78, clipped to 1 here (a share above 1 is impossible when the rival stays inside its own limit).
- Friday's real outcome is 0 deals in all 18 (we closed nothing that day), so `vs_real` equals `score` here.
- The waves are replayed as they were: duels sharing a deadline compete for the team's one accept per tick, and
  unscored duels of the same wave still take part (they hold slots).

## Metrics (per case; `_state.json` is the contract)

| id | kind | what it measures |
|---|---|---|
| `score` | float, headline | The rules' duel score as the arena computes it: our surplus / soft pie x (1 - decay)^rounds, 0 for no deal, clipped to [-1, 1]. |
| `deal` | 0/1 | A deal was reached. |
| `missed_ok_offer` | 0/1, lower is better | The policy *saw* a rival offer worth at least 1 P to us (inside our limit) and still ended with no deal. The costliest failure. |
| `limit_breach` | 0/1, must be 0 | We sent, or a deal closed at, a price past our own limit. Guardrail. |
| `vs_real` | float | Our replayed `score` minus the score of what really happened (server `result` / soft pie; 0 for no deal). |

Perf fields (in each row, not graded): `surplus_P` (deal surplus before decay), `rounds`, `deal_tick` (ticks from
the duel's start), `msgs_sent`, `best_offer_score` (the best rival offer taken silently, unconstrained: the
per-case ceiling), `real_result_P`, `vs_real_P`.

**Why the 0/1 metrics are declared `kind: float` (scale 1).** The report builder makes the first `binary` metric
its headline column; the game pays `score`, so `score` must be the headline. The runner prints Wilson intervals for
them (`"rate": true`). Decision for sign-off.

## Considered and left out

- Share without decay: `score` already contains it; share alone rewards slow talk.
- Rounds as a graded metric: priced into `score` through decay; kept as a perf field.
- Worst-quartile score (the tuner's objective): unstable at 18 cases; the per-role breakdown shows the spread.
- Surplus in primas as headline: not comparable across items with different limits (kept as `surplus_P`).
- An LLM judge of our message wording: words never bind (rules: "structure binds"); the code decides numbers.
- Accept-path re-read / `accept_mismatch`: needs live I/O between re-read and POST; not modelled offline.
- Deadline-1 accepts that fail to settle: the replay assumes they settle (11 field deals were recorded at the
  deadline tick); the arena's stress table covers the other case.

## Harness checks (scratch runs, not in this directory)

| policy | score | deal | missed_ok | breach |
|---|---|---|---|---|
| baseline (duel.py + duels2-final) | 0.459 +- 0.155 | 16/18 | 2/18 | 0/18 |
| oracle (best slot-feasible silent accepts) | 0.494 | 18/18 | 0/18 | 0/18 |
| null (never speaks or accepts) | 0.000 | 0/18 | 18/18 | 0/18 |
| reckless (opens past limit, accepts anything) | 0.091 | 18/18 | 0/18 | 18/18 |

Mean `best_offer_score` (unconstrained ceiling) is 0.521; the oracle reaches 0.494 because duels ending together
share one accept per tick. Run-to-run noise is zero (deterministic; `--reps 2` gives identical rows).

## Noise

Mean score 0.459 +- 0.155 (95% CI, n = 18, per-case sd 0.336). Comparing two params files on these same 18 cases,
the replay adds no noise, so any paired difference is real *on these duels*; whether it generalises is bounded by
case sampling: unrelated policies would need a gap of about 0.22 to clear it, and a paired gap needs
1.96 x sd(per-case difference) / sqrt(18). One duel moving by 0.5 moves the mean by 0.028.
