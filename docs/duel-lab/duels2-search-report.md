# Duel tuning report: Duels II

Generated 2026-10-03 08:29 by `tools/duel_tune.py` in 421.0 min, 9313 candidates. Tuned params: `/home/fable/lab/duel/best_params_duels2.json` (a `duel.py --params` file). The arena drives agent/duel.py's own decide / set_windows / allocate with the cfg duel.py's make_cfg builds from that file.

Tuning set: 200 simulated sessions (seeds 0..) against steady, fast, cycler, oneshot, llm, absent, hardliner, linear, silent. Held-out: 400 fresh sessions (seeds 500000..) against every kind, including tft and deadline, never seen while tuning. Each session: 68 duels, 16 ticks, decay 0.08, 6 at once, one accept per tick, slot taken by another agent 3% of ticks; half the sessions count rounds as ceil(switches / 2), half as min(our messages, theirs).

## Held-out results

Cells: mean score per duel (share of the pie x decay^rounds; 0 without a deal), deal rate, rounds per deal. `defaults` = agent/duel.py as it is on main (the Friday-analysis behaviour).

| rivals | defaults | tuned |
|---|---|---|
| **all** | 0.217 (45% deals, 0.4 rd) | 0.236 (48% deals, 0.4 rd) |
| absent | 0.000 (0% deals, 0.0 rd) | 0.000 (0% deals, 0.0 rd) |
| cycler | 0.032 (16% deals, 1.0 rd) | 0.032 (16% deals, 0.7 rd) |
| deadline | 0.335 (58% deals, 0.5 rd) | 0.266 (60% deals, 0.4 rd) |
| fast | 0.596 (77% deals, 0.3 rd) | 0.580 (75% deals, 0.3 rd) |
| hardliner | 0.072 (35% deals, 0.7 rd) | 0.086 (34% deals, 0.4 rd) |
| linear | 0.360 (70% deals, 0.0 rd) | 0.394 (68% deals, 0.0 rd) |
| llm | 0.380 (71% deals, 0.7 rd) | 0.383 (71% deals, 0.8 rd) |
| oneshot | 0.095 (36% deals, 0.9 rd) | 0.094 (35% deals, 0.9 rd) |
| silent | 0.180 (40% deals, 0.0 rd) | 0.244 (56% deals, 0.0 rd) |
| steady | 0.321 (69% deals, 0.1 rd) | 0.357 (67% deals, 0.0 rd) |
| tft | 0.153 (50% deals, 1.1 rd) | 0.299 (73% deals, 1.4 rd) |
| worst quartile (all duels) | 0.000 | 0.000 |

Objective (0.75 x mean + 0.25 x worst quartile of per-kind means, absent excluded): defaults 0.1759, tuned 0.1916.

## What moved

| param | duel.py default | tuned |
|---|---|---|
| last_r | 1.08 | 1.103 (moved) |
| max_msgs | 2 | 2 |
| last_chance_ticks | 2 | 4 (moved) |
| accept_any_ticks | 3 | 2 (moved) |
| near_ticks | 2 | 0 (moved) |
| stall_ticks | 3 | 4 (moved) |
| thin_frac | 0.5 | 0.5 |
| early_share | 0.85 | 0.85 |
| early_min_pie | 2 | 5.373 (moved) |
| pair_sell | 0.93 | 0.965 (moved) |
| pair_buy | 1.07 | 1.07 |
| absent_at | 0.5 | 0.552 (moved) |
| absent_share | 0.5 | 0.371 (moved) |
| absent_last | False | True (moved) |
| window_wait | True | True |
| days_cheap | 0.1 | 0.153 (moved) |
| anchor | 1.55 | 1.55 |
| floor | 1.22 | 1.277 (moved) |
| prem0 | 0.8 | 0.629 (moved) |
| prem1 | 0.25 | 0.087 (moved) |

## Stress: what if the rival model is wrong

Mean score per duel on 133 more fresh sessions, all rival kinds, one change at a time (best per row in bold):

| variant | defaults | tuned |
|---|---|---|
| as modelled | 0.217 | **0.241** |
| rounds = min(our msgs, theirs) | 0.216 | **0.241** |
| accept slot busy 15% of ticks | 0.215 | **0.227** |
| 80% of rivals never accept ours | 0.212 | **0.239** |
| 20% of rivals never accept ours | 0.221 | **0.245** |
| paired limit noisier (+-8%, +-6 P) | 0.216 | **0.240** |
| firmer field (hardliner, llm, tft, cycler) | 0.196 | **0.221** |
| Friday archetypes only | 0.220 | **0.230** |
| we also see the rival's last-tick message | 0.236 | **0.251** |
| an accept at deadline-1 does not settle | 0.197 | **0.205** |

## Accepted steps

| gen | held-out objective | held-out mean | paired diff vs previous | Friday replay | selftest | mean if D-1 accepts do not settle |
|---|---|---|---|---|---|---|
| 0 | 0.1759 | 0.2171 | - | - | - | 0.195 |
| 1 | 0.1829 | 0.2253 | [0.0082, 0.0006] | - | - | 0.188 |
| 3 | 0.1907 | 0.2347 | [0.0094, 0.0008] | - | - | 0.185 |
| 8 | 0.1916 | 0.2358 | [0.0011, 0.0004] | - | - | 0.194 |
