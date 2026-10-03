# duels-arena: metrics

`agent/duel.py` against `tools/duel_arena.py`'s synthetic rivals, on TEST seeds (900000..900099 since the
2026-10-03 climb; the first version used 500000..500049, which is duel_tune's SELECTION set, so it moved). Split:
TRAIN = seeds 0.. (duel_tune tunes there), SELECTION = 500000.. (duel_tune / duel_ab gate), TEST = 900000.. (this
eval; duel_tune's stress uses 800000..800079). Rivals here DO react to our offers and accept them. Defaults (all in
`_state.json` under `arena`):

- **Format: arena session 3 = Duels III** (price + delivery day, 12 ticks, decay 0.10, 4 duels at once, 68 duels),
  because the baseline is the file Sunday runs and Sunday's sessions are Duels III and the Final (same format).
- **Every rival kind** (steady, fast, cycler, oneshot, llm, absent, hardliner, linear, tft, deadline, silent) at the
  arena's own weights (`--weights all`).
- **Paired limit hidden** (`--pair-seen 0`): Duels I found it in 0 of 34 duels. The baseline ignores it anyway
  (`early_share 99` switches the paired limit off), but a params file that trusts it would look better than it is
  with the arena's default of 1.0.

One case = one duel (100 sessions x 68 = 6,800 cases; the tables below are from the first, 50-session version), `tags[0]` = rival kind. Why a duel and not a session: the
score is per duel, a rival kind is per duel (a session mixes all of them), and a trace is readable per duel. Duels
of one session are not independent (they share the accept slot, and the two duels of a pair share a rival team), so
the runner also prints a CI clustered by session; that is the one to quote. A session costs about 0.05 s, so the
case count is set by the size of the report, not by time: 50 sessions bring the clustered CI to +-0.016.

## Known limitation of this flow

- The rivals are a model fitted to Friday's paths (and Saturday's mix as an option), not the field. A gain here is a
  gain against those archetypes; check that it does not cost on the two real flows.
- The days model: every side's best day is the role default (buyer 0, seller 10), days wording neutral, so the bot
  runs in its robust two-issue mode (it never assumes a direction it has not confirmed).
- Accepts at deadline-1 settle; another agent never takes our accept slot (`slot_busy` 0); the late read fails 3%
  of the time and misses 15% of rival messages, as the arena models it.

## Metrics (per case; `_state.json` is the contract)

| id | kind | what it measures |
|---|---|---|
| `score` | float, headline | The rules' duel score, as `duel_arena.score_deal` computes it: share of the best joint pie over days 0-10 (price surplus minus our days cost) x (1 - decay)^rounds; a deal outside our limit scores the negative share, floored at -1; no deal 0. |
| `deal` | 0/1 | A deal was reached (by us accepting, or by the rival accepting our offer: tag `by:us` / `by:them`). |
| `missed_ok_offer` | 0/1, lower is better | The policy saw a rival offer worth at least 1 P to us (true surplus, days included) and still ended with no deal. |
| `limit_breach` | 0/1, must be 0 | We sent, or a deal closed at, a price past our own limit. |

No `vs_real`: there is no real counterpart. Perf fields: `surplus_P`, `rounds`, `deal_tick`, `msgs_sent`,
`best_offer_score` (the best rival offer when we never speak, taken silently: a reference, not a ceiling, since
talking can draw a better offer or an accept).

The 0/1 metrics are declared `kind: float` so that `score` is the report's headline column (the builder picks the
first `binary` metric); the runner prints Wilson intervals for them. Decision for sign-off.

## Considered and left out

- The tuner's objective (mean blended with the worst quartile of per-kind means): useful for search, hard to read
  per case; the per-kind breakdown in the runner output shows the same weakness.
- Stress variants (rounds rule `min`, slot busy, deadline-1 not settling, firmer field): `duel_arena.py --stress`
  already prints them; adding them as flows would multiply the report without new cases.
- Absent rivals as cases: kept (532 of 3,400) even though nothing can be won there: they price what a message to a
  silent rival costs, and a variant that breaches or wastes rounds there shows up.
- Days-specific grades (did we give away the day the rival cares about): folded into `score` through the joint pie.

## Harness checks (scratch runs, not in this directory)

| policy | score | deal | missed_ok | breach |
|---|---|---|---|---|
| baseline (duel.py + duels2-final) | 0.256 +- 0.016 (clustered) | 47.5% | 2.2% | 0 |
| oracle (best slot-feasible silent accepts, planned from a silent pass) | 0.236 | 37.6% | 4.2% | 0 |
| null | 0.000 | 0 | 41.6% | 0 |
| reckless | -0.508 | 83.7% | 0.3% | 100% |

Here the oracle is a *silent* oracle: it may beat any silent policy, not one that talks. The baseline beats it
(0.256 vs 0.236) on rivals that accept our offers (silent 0.193 vs 0, tft, steady); that is the point of speaking.
Run-to-run noise is zero (same seeds, same worlds).

## Noise

**At 100 test sessions (900000..)**: baseline 0.254 +- 0.009 clustered by session (+- 0.008 per duel, sd 0.320,
unpaired floor 0.011). Paired per-session difference between two params files: SE 0.0010-0.0013 for the one-lever
changes of the climb (keep rule: diff > 2 SE, i.e. about +0.0025). Rerunning the same file gives a diff of exactly 0.

First version (50 sessions, 500000..):

Mean 0.256: +- 0.011 per duel (n = 3,400, sd 0.321), +- 0.016 clustered by session (the honest CI). Two params files
run on the same seeds see the same worlds, so their paired per-session difference has no run noise; its floor is
1.96 x sd(per-session difference) / sqrt(50), well under the unpaired 0.015-0.023.
