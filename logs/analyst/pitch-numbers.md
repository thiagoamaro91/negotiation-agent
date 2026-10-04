# Pitch numbers (Sunday analyst)

Filled at each trigger; the final set is written at the freeze read.

## Duels III (server session 4, read 12:02, logs from origin/mini/logs at 12:01)

- pitch: the lab predicted 0.420 per duel; the live wave gave 0.411 per duel (deal rate 81%), field seen {"absent": 8, "linear": 36, "fast": 11, "oneshot": 11, "steady": 2} [prediction: docs/duel-lab/duels3-matrix.md (likely field, robust); live: duel_points 0.0 (tick 1822) -> 27.94 (tick 2087)] (source: logs/analyst/duels-3-2069.md)
- 55/68 deals, our surplus 1475.4 P; buyer 27/34, seller 28/34; no-deals: 8 mute rivals, 3 no zone, 2 early inside offers not taken (source: logs/analyst/duels-3-2069.md)

## Market Tests (Sunday)

- hard test b121 (ticks 1690-1706): 7 matches, 178 P = 85% of best, 100% of the quote-respecting ceiling (source: logs/analyst/bench-b121-1705.md)
- test b138 (ticks 1774-1790): 4 matches, 97 P = 73% of best, 92% of the quote-respecting ceiling (source: logs/analyst/bench-b138-1788.md)
- Final params check (12:15, after PR #99): the deployed Duels III params match the bot's run_start (23 values); on the Duels III refit the lab gives 0.398 per duel for them (live 0.411). Neither candidate wins: hold_while_conceding -0.016 ±0.002 (worse), silent_last_margin +0.05 +0.000 ±0.000 -> keep the Duels III params for the Final (source: logs/analyst/matrix-s3/matrix.md)
- test b156 (ticks 2254-2270): 7 matches, 101 P = 72% of best, 100% of the quote-respecting ceiling, despite 13 server read timeouts in the window (source: logs/analyst/bench-b156-2269.md)
