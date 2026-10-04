# Analyst on duty: latest

```
TRIGGER 15:10 close read-out (Bazaar closed tick 2816; logs from origin/mini/logs at 14:59)
VERDICT Final score 34.19 rank 4 (negotiating 26.04 + market 8.15; leader t05 37.73, t12 34.51 above, gap 0.32). Grand Final 25/34 deals, 657.3 P, 0.360 per duel (lab 0.420; delivery days cost 79.2 P). Ladder R3 11/15 confirmed, 0 unverified (Banco 0/3, Chato 2/3). v20: 32 listings by 3 teams, 0 trades. Market Tests: 85% / 73% / 72% of best (100% / 92% / 100% of quote ceiling), stall all day
PROPOSE nothing (game over); pitch numbers in logs/analyst/pitch-numbers.md
NEEDS YES none (PR #91 carries the day's reports, findings and pitch numbers for review/merge)
PR https://github.com/thiagoamaro91/negotiation-agent/pull/91
ORGANISERS: feed#117797 tick 2798 announcement "Scores freeze at 15:00. Thank you, Madrid."
ORGANISERS: feed#118049 tick 2816 announcement "The Bazaar has closed. Gracias!"
```

Logs from: origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143) (newest report duels-4-2680.md)

| trigger | report | data | verdict |
|---|---|---|---|
| bench-b121 | bench-b121-1705.md | origin/mini/logs, commit 2026-10-04 10:22:44 +0200 (3111129) | bench b121: stall behaved |
| bench-b138 | bench-b138-1788.md | origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) | bench b138: something is wrong: 1 read errors during the session |
| bench-b156 | bench-b156-2269.md | origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143) | bench b156: something is wrong: 13 read errors during the session |
| duels-3 | duels-3-2069.md | origin/mini/logs, commit 2026-10-04 12:12:32 +0200 (3f913b1) | duels session 3: 55/68 deals, 1475.4 P; Final params: keep |
| duels-4 | duels-4-2680.md | origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143) | duels session 4: 25/34 deals, 657.3 P |
| ladder | ladder-2816.md | origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143) | ladder: 11/15 slots confirmed, 0 unverified, 0 deal(s) scored 0 |
| market | market-2816.md | origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143) | market: 0 trade(s) between other teams on v20, 32 listings (0 within 40 ticks of an announcement/outreach) |
| score | score-2802.md | origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143) | score: 34.19 rank 4 (+0.34 since tick 2462) |

---

# duels-4 at tick 2680

_2026-10-04 15:11:03 local, tools/analyst.py_

_data: origin/mini/logs, commit 2026-10-04 14:59:56 +0200 (1328143)_

**duels session 4: 25/34 deals, 657.3 P**

- complete: 34/34 duels completed, each with a matching result record in the duel log
- 34 duels, 25 deals, our surplus 657.3 P; buyer: 13 deals / 4 no-deals, seller: 12 deals / 5 no-deals
- no-deals by cause: early_inside_not_taken 1, inside_not_taken 1, mute 3, no_zone 2, short_of_limit 2
- day term: deals by delivery day d0: 13, d2: 1, d10: 11; days worth -79.2 P to us over all deals
- accepts taken while the rival was still conceding: 22 of 25
- rivals with no-deals: Rival Azul 3, Rival Oro 2, Rival Sol 1, Rival Rojo 1, Rival Plata 1
  - duel 15874 seller vs Rival Azul: mute (best rival offer - P to us, our last offer left us 84 P, rival first priced - ticks before the end)
  - duel 15875 buyer vs Rival Oro: mute (best rival offer - P to us, our last offer left us 24 P, rival first priced - ticks before the end)
  - duel 15958 seller vs Rival Oro: inside_not_taken (best rival offer 12 P to us, our last offer left us 106 P, rival first priced 12 ticks before the end, first inside our limit 2 ticks before the end)
  - duel 16013 seller vs Rival Plata: short_of_limit (best rival offer -1 P to us, our last offer left us 76 P, rival first priced 9 ticks before the end)
  - duel 16084 seller vs Rival Azul: mute (best rival offer - P to us, our last offer left us 68 P, rival first priced - ticks before the end)
  - duel 16085 buyer vs Rival Luna: short_of_limit (best rival offer -14 P to us, our last offer left us 25 P, rival first priced 3 ticks before the end)
  - duel 16088 seller vs Rival Rojo: early_inside_not_taken (best rival offer 34 P to us, our last offer left us 61 P, rival first priced 12 ticks before the end, first inside our limit 7 ticks before the end)
- levers (WP1 doc read):
  - accept-while-conceding (hold for deadline-1, F1) -> hold_while_conceding True: would touch 22 duel(s) [15878, 15879, 15900, 15901, 15904, 15905, 15908, 15909] (named in the WP1 doc)
  - last chance to a silent rival (F2) -> silent_last_margin +0.05: would touch 3 duel(s) [15874, 15875, 16084] (named in the WP1 doc)
  - last-chance ticks -> last_chance_ticks +1: would touch 2 duel(s) [16013, 16085] (named in the WP1 doc)
  - accept window (a rival offer inside our limit went untaken) -> accept_any_ticks +1: would touch 1 duel(s) [15958] (named in the WP1 doc)
  - early accept (a rich offer before the last ticks; duel.py accepts early only with the paired limit, off since Duels I: needs code, not params) -> no knob : would touch 1 duel(s) [16088] (named in the WP1 doc)
- field refit (duel_field_read shapes of the final transcripts -> arena kinds): {"absent": 3, "linear": 17, "fast": 7, "tft": 3, "steady": 1, "oneshot": 3}
- pitch: the lab predicted 0.420 per duel; the live wave gave 0.360 per duel (deal rate 74%), field seen {"absent": 3, "linear": 17, "fast": 7, "tft": 3, "steady": 1, "oneshot": 3} [prediction: docs/duel-lab/duels3-matrix.md (likely field, robust); live: duel_points 27.94 (tick 2578) -> 40.19 (tick 2697)]

