# Analyst on duty: latest

```
TRIGGER 12:05 Duels III read-out (68/68 complete, duels.finished tick 2074; tick 2117, logs from origin/mini/logs at 12:01)
VERDICT 55/68 deals, 1475.4 P surplus; pitch: lab 0.420 per duel, live 0.411 (deal rate 81%), field linear 36 / fast 11 / oneshot 11 / absent 8 / steady 2. Matrix REFUSED: baseline check saw days_best "buyer:0,seller:10" vs run "buyer:0,seller:10;robust" (the tag agent/duel.py make_cfg adds when days_confirmed is false; every other key matched). No Final params yet. Ladder 5/15 unchanged; no new Market Test since b138 (next ~12:37)
PROPOSE merge PR #99 (tools/analyst.py: deployed_check strips make_cfg's ";robust" tag only when the run logged days_confirmed false; +1 test, 91 OK, mutation-checked); then I rerun `duels --session 3 --matrix` and it writes docs/duel-lab/duel-params-final.json only if a candidate passes 2 SE (levers on record: hold_while_conceding 42 duels, silent_last_margin +0.05 8 duels)
NEEDS YES a human merges #99 by ~12:50 so a winning params file can be applied before the keeper relaunches ~13:49 (the Duels III process runs --until 15:05 and stays alive into the Final: any new params need `tmux kill-window -t factory:duel` + `up --yes`, docs/plans/sunday-analyst.md "Applying a change"). No merge = Final runs duel-params-duels3.json, which is fine
PR https://github.com/thiagoamaro91/negotiation-agent/pull/99 (fix) ; https://github.com/thiagoamaro91/negotiation-agent/pull/91 (reports)
ORGANISERS: nothing new since 10:46 (Duels III finished tick 2074 ~11:52; next: Market Test ~12:37, finale warning ~13:47, stalls close + Final ~13:59)
```

Logs from: origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) (newest report bench-b138-1788.md)

| trigger | report | data | verdict |
|---|---|---|---|
| bench-b121 | bench-b121-1705.md | origin/mini/logs, commit 2026-10-04 10:22:44 +0200 (3111129) | bench b121: stall behaved |
| bench-b138 | bench-b138-1788.md | origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) | bench b138: something is wrong: 1 read errors during the session |
| duels-3 | duels-3-2069.md | origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) | duels session 3: 55/68 deals, 1475.4 P; Final params: no verdict (baseline does not match the bot's run_start) |
| ladder | ladder-2117.md | origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e) | ladder: 5/15 slots confirmed, 0 unverified, 0 deal(s) scored 0 |
| market | market-1807.md | origin/mini/logs, commit 2026-10-04 10:44:32 +0200 (2ee165d) | market: 0 trade(s) between other teams on v20, 29 listings (0 within 40 ticks of an announcement/outreach) |
| score | score-1802.md | origin/mini/logs, commit 2026-10-04 10:44:32 +0200 (2ee165d) | score: 29.29 rank 5 (+1.58 since tick 1702) |

---

# bench-b138 at tick 1788

_2026-10-04 12:03:55 local, tools/analyst.py_

_data: origin/mini/logs, commit 2026-10-04 12:01:32 +0200 (58e345e)_

**bench b138: something is wrong: 1 read errors during the session**

- session b138 (feed bench session 8, ticks 1774-1790; recorded 1775-1788, 18 book states, 10 buyers / 10 sellers)
- efficiency proxy (revealed limits): live 97 P = 73% of best 133 P (92% of the quote-respecting ceiling 106 P); stall replay 97 P = 73%; `--policy ours` replay 97 P = 73%
- matches: live 4, stall replay 4, ours replay 4; live vs replay pairs agree 1.00; crossable pairs the replay leaves 0
- dropped by our guard: 0; refused/send errors: 0; read errors in the window: 1
- book change -> match sent: median 0 tick(s), max 0 over 4 matches
- expiries: 20/20 offers show one, 1 distinct [1790], session end 1790, 0 earlier than the end
- => per-offer expiries all at the session end (as on Saturday): keep `--policy stall`.
- official bench_points around the session (score.jsonl): before (1743, 0.5), after (1822, 0.5)

