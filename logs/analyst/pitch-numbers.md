# Pitch numbers (Sunday analyst)

Final set, read at the close (15:10, Bazaar closed at tick 2816; logs from origin/mini/logs at 14:59).

## Final standing

- Score 34.19, rank 4 of 18: negotiating 26.04 + market 8.15 (+ judges later); leader t05 37.73; t12 34.51 just above (gap 0.32); cash 17 P (source: logs/analyst/score-2802.md)
- Inside negotiating at tick 2797: duel_points 40.19, ladder_points 0.371, bench_points 0.5 (source: logs/analyst/score-2802.md)
- Over the Sunday read-outs: rank 5 (27.71, tick 1702) -> 5 (32.23, tick 2282) -> 4 (33.85, tick 2462) -> 4 (34.19, tick 2802)

## Grand Final duels (server session 5, finished tick 2692)

- 25/34 deals (74%), our surplus 657.3 P; buyer 13/17, seller 12/17; duel_points 27.94 -> 40.19 = +12.25, 0.360 per duel (source: logs/analyst/duels-4-2680.md)
- pitch: the lab predicted 0.420 per duel; the live wave gave 0.360 per duel (deal rate 74%), field seen {"absent": 3, "linear": 17, "fast": 7, "tft": 3, "steady": 1, "oneshot": 3}; the delivery-day term cost us 79.2 P over the 25 deals (source: logs/analyst/duels-4-2680.md)
- Sunday duels (Duels III + Final): 80/102 deals, 2132.7 P surplus

## Dealer ladder (Round 3)

- 11/15 slots confirmed, every one bound to the bot thread that made it, 0 unverified, 0 deals that scored 0: Abuela 3/3, Chato 2/3, Pilar 3/3, Picaros 3/3, Banco 0/3 (source: logs/analyst/ladder-2816.md)

## v20 (our venue)

- 32 offers listed on v20 by 3 other teams (t15 16, t13 13, t16 3), 0 settlements between other teams; 28 venue announcements (source: logs/analyst/market-2816.md)

## Duels III (server session 4, read 12:02, logs from origin/mini/logs at 12:01)

- pitch: the lab predicted 0.420 per duel; the live wave gave 0.411 per duel (deal rate 81%), field seen {"absent": 8, "linear": 36, "fast": 11, "oneshot": 11, "steady": 2} [prediction: docs/duel-lab/duels3-matrix.md (likely field, robust); live: duel_points 0.0 (tick 1822) -> 27.94 (tick 2087)] (source: logs/analyst/duels-3-2069.md)
- 55/68 deals, our surplus 1475.4 P; buyer 27/34, seller 28/34; no-deals: 8 mute rivals, 3 no zone, 2 early inside offers not taken (source: logs/analyst/duels-3-2069.md)

## Market Tests (Sunday)

- hard test b121 (ticks 1690-1706): 7 matches, 178 P = 85% of best, 100% of the quote-respecting ceiling (source: logs/analyst/bench-b121-1705.md)
- test b138 (ticks 1774-1790): 4 matches, 97 P = 73% of best, 92% of the quote-respecting ceiling (source: logs/analyst/bench-b138-1788.md)
- Final params check (12:15, after PR #99): the deployed Duels III params match the bot's run_start (23 values); on the Duels III refit the lab gives 0.398 per duel for them (live 0.411). Neither candidate wins: hold_while_conceding -0.016 ±0.002 (worse), silent_last_margin +0.05 +0.000 ±0.000 -> keep the Duels III params for the Final (source: logs/analyst/matrix-s3/matrix.md)
- test b156 (ticks 2254-2270): 7 matches, 101 P = 72% of best, 100% of the quote-respecting ceiling, despite 13 server read timeouts in the window (source: logs/analyst/bench-b156-2269.md)
