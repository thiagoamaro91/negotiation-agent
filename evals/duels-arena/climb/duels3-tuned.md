# Duel tuning report: Duels III

Generated 2026-10-03 22:01 by `tools/duel_tune.py` in 23.7 min, 1025 candidates. Tuned params: `evals/duels-arena/climb/duels3-tuned.json` (a `duel.py --params` file). The arena drives agent/duel.py's own decide / set_windows / allocate with the cfg duel.py's make_cfg builds from that file.

Tuning set: 120 simulated sessions (seeds 0..) against steady, fast, cycler, oneshot, llm, absent, hardliner, linear, silent. Held-out: 240 fresh sessions (seeds 500000..) against every kind, including tft and deadline, never seen while tuning. Each session: 68 duels, 12 ticks, decay 0.1, 4 at once, one accept per tick, slot taken by another agent 3% of ticks; half the sessions count rounds as ceil(switches / 2), half as min(our messages, theirs).

## Held-out results

Cells: mean score per duel (share of the pie x decay^rounds; 0 without a deal), deal rate, rounds per deal. `defaults` = agent/duel.py as it is on main (the Friday-analysis behaviour).

| rivals | defaults | start | tuned |
|---|---|---|---|
| **all** | 0.247 (46% deals, 0.4 rd) | 0.254 (45% deals, 0.3 rd) | 0.251 (48% deals, 0.4 rd) |
| absent | 0.000 (0% deals, 0.0 rd) | 0.000 (0% deals, 0.0 rd) | 0.000 (0% deals, 0.0 rd) |
| cycler | 0.045 (20% deals, 0.9 rd) | 0.046 (20% deals, 0.7 rd) | 0.045 (20% deals, 0.9 rd) |
| deadline | 0.343 (63% deals, 0.6 rd) | 0.365 (64% deals, 0.6 rd) | 0.308 (64% deals, 0.5 rd) |
| fast | 0.580 (74% deals, 0.3 rd) | 0.556 (71% deals, 0.3 rd) | 0.580 (74% deals, 0.3 rd) |
| hardliner | 0.116 (38% deals, 0.3 rd) | 0.119 (37% deals, 0.0 rd) | 0.116 (38% deals, 0.3 rd) |
| linear | 0.452 (70% deals, 0.0 rd) | 0.458 (68% deals, 0.0 rd) | 0.452 (70% deals, 0.0 rd) |
| llm | 0.374 (71% deals, 0.7 rd) | 0.381 (66% deals, 0.6 rd) | 0.371 (70% deals, 0.7 rd) |
| oneshot | 0.094 (36% deals, 0.8 rd) | 0.079 (29% deals, 0.7 rd) | 0.095 (33% deals, 0.8 rd) |
| silent | 0.129 (31% deals, 0.0 rd) | 0.190 (47% deals, 0.0 rd) | 0.182 (46% deals, 0.0 rd) |
| steady | 0.433 (71% deals, 0.0 rd) | 0.449 (68% deals, 0.0 rd) | 0.434 (71% deals, 0.0 rd) |
| tft | 0.229 (62% deals, 1.2 rd) | 0.234 (57% deals, 1.2 rd) | 0.267 (68% deals, 1.3 rd) |
| worst quartile (all duels) | 0.000 | 0.000 | 0.000 |

Objective (0.75 x mean + 0.25 x worst quartile of per-kind means, absent excluded): defaults 0.2024, start 0.2061, tuned 0.2056.

## What moved

| param | duel.py default | tuned |
|---|---|---|
| last_r | 1.08 | 1.114 (moved) |
| max_msgs | 2 | 2 |
| last_chance_ticks | 2 | 3 (moved) |
| accept_any_ticks | 3 | 3 |
| near_ticks | 2 | 3 (moved) |
| stall_ticks | 3 | 3 |
| thin_frac | 0.5 | 0.5 |
| early_share | 0.85 | 0.852 (moved) |
| early_min_pie | 2 | 2 |
| pair_sell | 0.93 | 0.93 |
| pair_buy | 1.07 | 1.07 |
| absent_at | 0.5 | 0.5 |
| absent_share | 0.5 | 0.5 |
| absent_last | False | True (moved) |
| window_wait | True | True |
| days_cheap | 0.1 | 0.1 |
| anchor | 1.55 | 1.55 |
| floor | 1.22 | 1.22 |
| prem0 | 0.8 | 0.737 (moved) |
| prem1 | 0.25 | 0.155 (moved) |

## Stress: what if the rival model is wrong

Mean score per duel on 80 more fresh sessions, all rival kinds, one change at a time (best per row in bold):

| variant | defaults | start | tuned |
|---|---|---|---|
| as modelled | 0.244 | **0.251** | 0.246 |
| rounds = min(our msgs, theirs) | 0.244 | **0.251** | 0.246 |
| accept slot busy 15% of ticks | 0.232 | 0.232 | **0.234** |
| 80% of rivals never accept ours | 0.243 | **0.251** | 0.247 |
| 20% of rivals never accept ours | 0.247 | **0.253** | 0.248 |
| paired limit noisier (+-8%, +-6 P) | 0.243 | **0.251** | 0.244 |
| firmer field (hardliner, llm, tft, cycler) | 0.226 | **0.233** | 0.228 |
| Friday archetypes only | 0.245 | **0.249** | 0.246 |
| we also see the rival's last-tick message | 0.249 | **0.258** | 0.250 |
| an accept at deadline-1 does not settle | 0.191 | 0.164 | **0.203** |
| late read: 40% of rival messages land after it, 15% of reads fail | 0.223 | 0.225 | **0.228** |
| late read: every one fails (falls back to the next tick) | 0.209 | **0.220** | 0.219 |
| paired limit never visible (Duels I: 0/34) | 0.244 | **0.251** | 0.246 |
| Duels I field mix, paired limit never visible | 0.332 | **0.341** | 0.337 |
| Duels I mix, no pair, deadline-1 does not settle | 0.268 | 0.221 | **0.276** |
| Duels I mix, no pair, accept slot busy 15% | 0.316 | 0.313 | **0.321** |

## Accepted steps

| gen | held-out objective | held-out mean | paired diff vs previous | Friday replay | selftest | mean if D-1 accepts do not settle |
|---|---|---|---|---|---|---|
| 0 | 0.2024 | 0.2467 | - | - | - | 0.194 |
| 1 | 0.2044 | 0.2495 | [0.0029, 0.0008] | - | - | 0.205 |
| 4 | 0.2056 | 0.2509 | [0.0013, 0.0004] | - | - | 0.205 |
