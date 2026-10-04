# Analyst on duty: latest

```
TRIGGER 12:15 Duels III matrix rerun after PR #99 (tick ~2160, logs from origin/mini/logs at 12:12)
VERDICT baseline proven (23 values match run 20261004-104947-a0b5); refit field: base 0.398 per duel (live gave 0.411); hold_while_conceding -0.016 ±0.002 (worse on every mix, -0.105 on D-1 stress), silent_last_margin +0.05 +0.000 ±0.000 -> keep the Duels III params for the Final
PROPOSE nothing: no duel-params-final.json, factory_sunday.json duel params path stays docs/duel-lab/duel-params-duels3.json
NEEDS YES none (do NOT restart the duel window; the Duels III process carries into the Final with the right params)
PR https://github.com/thiagoamaro91/negotiation-agent/pull/91 (reports; #99 merged)
ORGANISERS: nothing new since 12:05 (next: Market Test ~12:37, finale warning ~13:47, stalls close + Final ~13:59)
```

Logs from: origin/mini/logs, commit 2026-10-04 12:12:32 +0200 (3f913b1) (newest report duels-3-2069.md)

| trigger | report | data | verdict |
|---|---|---|---|
| bench-b121 | bench-b121-1705.md | origin/mini/logs, commit 2026-10-04 10:22:44 +0200 (3111129) | bench b121: stall behaved |
| bench-b138 | bench-b138-1788.md | origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) | bench b138: something is wrong: 1 read errors during the session |
| duels-3 | duels-3-2069.md | origin/mini/logs, commit 2026-10-04 12:12:32 +0200 (3f913b1) | duels session 3: 55/68 deals, 1475.4 P; Final params: keep |
| ladder | ladder-2117.md | origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) | ladder: 5/15 slots confirmed, 0 unverified, 0 deal(s) scored 0 |
| market | market-1807.md | origin/mini/logs, commit 2026-10-04 10:44:32 +0200 (2ee165d) | market: 0 trade(s) between other teams on v20, 29 listings (0 within 40 ticks of an announcement/outreach) |
| score | score-1802.md | origin/mini/logs, commit 2026-10-04 10:44:32 +0200 (2ee165d) | score: 29.29 rank 5 (+1.58 since tick 1702) |

---

# duels-3 at tick 2069

_2026-10-04 12:14:18 local, tools/analyst.py_

_data: origin/mini/logs, commit 2026-10-04 12:12:32 +0200 (3f913b1)_

**duels session 3: 55/68 deals, 1475.4 P; Final params: keep**

- complete: 68/68 duels completed, each with a matching result record in the duel log
- 68 duels, 55 deals, our surplus 1475.4 P; buyer: 27 deals / 7 no-deals, seller: 28 deals / 6 no-deals
- no-deals by cause: early_inside_not_taken 2, mute 8, no_zone 3
- day term: deals by delivery day d0: 38, d10: 17; days worth +1.7 P to us over all deals
- accepts taken while the rival was still conceding: 42 of 55
- rivals with no-deals: Rival Azul 5, Rival Oro 3, Rival Noche 2, Rival Sol 1, Rival Rojo 1
  - duel 11090 seller vs Rival Sol: mute (best rival offer - P to us, our last offer left us 67 P, rival first priced - ticks before the end)
  - duel 11091 buyer vs Rival Azul: mute (best rival offer - P to us, our last offer left us 32 P, rival first priced - ticks before the end)
  - duel 11272 seller vs Rival Noche: mute (best rival offer - P to us, our last offer left us 72 P, rival first priced - ticks before the end)
  - duel 11273 buyer vs Rival Oro: mute (best rival offer - P to us, our last offer left us 18 P, rival first priced - ticks before the end)
  - duel 11362 seller vs Rival Oro: mute (best rival offer - P to us, our last offer left us 76 P, rival first priced - ticks before the end)
  - duel 11363 buyer vs Rival Oro: mute (best rival offer - P to us, our last offer left us 10 P, rival first priced - ticks before the end)
  - duel 11468 seller vs Rival Azul: early_inside_not_taken (best rival offer 30 P to us, our last offer left us - P, rival first priced 11 ticks before the end, first inside our limit 11 ticks before the end)
  - duel 11534 seller vs Rival Azul: early_inside_not_taken (best rival offer 12 P to us, our last offer left us 61 P, rival first priced 9 ticks before the end, first inside our limit 9 ticks before the end)
  - duel 11642 seller vs Rival Rojo: mute (best rival offer - P to us, our last offer left us 59 P, rival first priced - ticks before the end)
  - duel 11643 buyer vs Rival Noche: mute (best rival offer - P to us, our last offer left us 28 P, rival first priced - ticks before the end)
- levers (WP1 doc read):
  - accept-while-conceding (hold for deadline-1, F1) -> hold_while_conceding True: would touch 42 duel(s) [11110, 11111, 11132, 11133, 11150, 11176, 11177, 11200] (named in the WP1 doc)
  - last chance to a silent rival (F2) -> silent_last_margin +0.05: would touch 8 duel(s) [11090, 11091, 11272, 11273, 11362, 11363, 11642, 11643] (named in the WP1 doc)
  - early accept (a rich offer before the last ticks; duel.py accepts early only with the paired limit, off since Duels I: needs code, not params) -> no knob : would touch 2 duel(s) [11468, 11534] (named in the WP1 doc)
- field refit (duel_field_read shapes of the final transcripts -> arena kinds): {"absent": 8, "linear": 36, "fast": 11, "oneshot": 11, "steady": 2}
- pitch: the lab predicted 0.420 per duel; the live wave gave 0.411 per duel (deal rate 81%), field seen {"absent": 8, "linear": 36, "fast": 11, "oneshot": 11, "steady": 2} [prediction: docs/duel-lab/duels3-matrix.md (likely field, robust); live: duel_points 0.0 (tick 1822) -> 27.94 (tick 2087)]
- baseline duel-params-duels3.json vs what the bot ran: 23 baseline values match the run_start of 1 run(s)
- matrix (arena session 4, 60 sessions, base duel-params-duels3.json): /home/fable/work/wt-wp10-sunday-analyst/logs/analyst/matrix-s3/matrix.md
  - hold_while_conceding@True: not more than 2 SE better on mix: Duels III refit in both modes (-0.0161±0.0025, -0.0161±0.0025)
  - silent_last_margin@0.05: not more than 2 SE better on mix: Duels III refit in both modes (+0.0000±0.0000, +0.0000±0.0000)
- => keep the Duels III params for the Final

