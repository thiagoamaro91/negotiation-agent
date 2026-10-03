# Duels I: tuned params for agent/duel.py

Built 2026-10-03 03:00-03:45 with `tools/duel_arena.py` and `tools/duel_tune.py` against agent/duel.py on main
(0289293), which already encodes the Friday duel analysis. duel.py is unchanged; these are `--params` files.

## Recommendation

| file | what it changes from duel.py's defaults | load it |
|---|---|---|
| `docs/duel-lab/duel-params-duels1-safe.json` | silent rival: one offer at 20% of the clock (not 50%) keeping 75% of the soft pie (not 50%), plus the last chance to a rival that never spoke (free while it stays silent); early accept at 0.9 of the soft pie (not 0.85) | **Duels I, 11:15** |
| `docs/duel-lab/duel-params-duels1.json` | the safe changes, plus accept window 2 ticks (not 3) counting only duels with the same deadline (near_ticks 0, not 2), and up to 3 messages with a 1.15 last chance (not 2 and 1.08) | once one of our deadline-1 accepts is seen to settle |

```
mkdir -p results && cp docs/duel-lab/duel-params-duels1-safe.json results/duel-params.json
python3 agent/duel.py watch --once --params results/duel-params.json      # read-only check against the live clock
python3 agent/duel.py run --until 12:30 --params results/duel-params.json  # after the yes in the team chat
```

Switching to the tuned file mid-session is a restart with the other `--params` (duel.py's `sync_state` picks up
what we already said).

Held-out simulation (300 fresh sessions of 34 duels, all eleven rival kinds), the real Friday rival paths, and
duel.py's own selftest simulation (Thiago's archetypes, 3000 duels):

| | duel.py defaults | safe | tuned |
|---|---|---|---|
| mean score per duel, held-out | 0.354 | 0.363 (+2.5%) | 0.374 (+5.6%) |
| Friday replay (8 real rival paths) | 0.381 | 0.379 | 0.379 |
| duel.py selftest value | 0.492 | 0.493 | 0.504 |
| if an accept at deadline-1 never settles | 0.317 | 0.317 | 0.298 |

Stress, mean score per duel (150 fresh sessions, one change to the rival model at a time):

| variant | duel.py defaults | safe | tuned |
|---|---|---|---|
| as modelled | 0.345 | 0.354 | **0.365** |
| rounds = min(our msgs, theirs) | 0.345 | 0.354 | **0.365** |
| accept slot busy 15% of ticks | 0.338 | 0.346 | **0.348** |
| 80% of rivals never accept ours | 0.341 | 0.346 | **0.356** |
| 20% of rivals never accept ours | 0.348 | 0.362 | **0.373** |
| paired limit noisier (+-8%, +-6 P) | 0.341 | 0.347 | **0.358** |
| firmer field (hardliner, llm, tft, cycler) | 0.319 | 0.327 | **0.337** |
| Friday archetypes only | 0.339 | 0.342 | **0.351** |
| we also see the rival's last-tick message | 0.365 | 0.374 | **0.388** |
| an accept at deadline-1 does not settle | 0.317 | **0.317** | 0.298 |

Where the gain comes from (one change at a time, held-out set; "tuned set" = the full set the search ended on,
in the generated section below):

| param | default -> tuned | alone on top of the defaults | removed from the tuned set | hurts if D-1 accepts never settle |
|---|---|---|---|---|
| accept_any_ticks | 3 -> 2 | +0.0015 | -0.0103 | yes (-0.021 together with near_ticks) |
| near_ticks | 2 -> 0 | 0.0000 | -0.0059 | yes |
| absent_share | 0.5 -> 0.75 | +0.0014 | -0.0075 | no |
| absent_last | false -> true | +0.0027 | -0.0072 | no |
| absent_at | 0.5 -> 0.2 | +0.0010 | -0.0013 | no |
| early_share | 0.85 -> 0.9 | +0.0016 | -0.0015 | no |
| last_r, max_msgs | 1.08 -> 1.155, 2 -> 3 | +0.0003 | -0.0014 | no |
| ratios, stall_ticks, thin_frac, early_min_pie, pair_sell, window_wait | small moves | under 0.0005 each | under 0.0005 each | - |

The last row stays at duel.py's defaults in both files: its effect is noise.

## What the numbers rest on

- The rival model is a guess fitted to 8 Friday paths from bots that were not scoring. The gains (+3% to +6%) are
  smaller than the uncertainty in that model. The safe file is chosen because it is never worse than duel.py's
  defaults in any stress row, not because the gain is large.
- The absent-rival gains assume some silent rivals take a good offer (the `silent` kind; none was seen on Friday,
  but no Friday offer to a silent rival was acceptable either). If none does, those messages cost nothing: a
  message to a rival that never spoke costs no round (2/2 on Friday).
- The tuned file's accept window bets that an accept at deadline-1 settles (11 field deals were recorded on the
  deadline tick; unconfirmed). If it does not, it loses about 0.02 per duel against the defaults.
- The biggest lever is not a param: seeing the rival's deadline-1 message before our last accept (a second poll
  late in the final tick) is worth about +0.02 per duel for every params set. That is a loop change for Thiago.

## What to log in Duels I, to refit before Duels II (18:00)

duel.py's run log already has most of it (`rival`, `accept`, `say`, `result`, `duels/duel-N.json`). Per duel we
need: every rival message tick and price; our accept tick, ticks left and whether the result was a deal (answers
the deadline-1 question); `rounds` at the close next to who spoke (rounds rule); deals at OUR price (rivals that
take our offers); the paired limit next to the rival's final price (scale and shift); refused accepts (429s,
another agent on the slot); for Duels II the raw `days_meaning` and `your_days_weight`. After the session: add the
new `logs/duels/duel-*.json` to the Friday replay, refit the rival mix (`WEIGHTS`, `NEVER_TAKES` in
tools/duel_arena.py), and rerun the session-2 tuner with `--start` set to the VM's best_params_duels2.json.

---

## Duel tuning report: Duels I (generated by the search)

Generated 2026-10-03 03:38 by `tools/duel_tune.py` in 10.9 min, 1505 candidates. "tuned" below is the full set the search ended on (listed under What moved), before the ablation above trimmed it to the two committed files. The arena drives agent/duel.py's own decide / set_windows / allocate with the cfg duel.py's make_cfg builds from that file.

Tuning set: 160 simulated sessions (seeds 0..) against steady, fast, cycler, oneshot, llm, absent, hardliner, linear, silent. Held-out: 300 fresh sessions (seeds 500000..) against every kind, including tft and deadline, never seen while tuning. Each session: 34 duels, 16 ticks, decay 0.06, 3 at once, one accept per tick, slot taken by another agent 3% of ticks; half the sessions count rounds as ceil(switches / 2), half as min(our messages, theirs).

### Held-out results

Cells: mean score per duel (share of the pie x decay^rounds; 0 without a deal), deal rate, rounds per deal. `defaults` = agent/duel.py as it is on main (the Friday-analysis behaviour).

| rivals | defaults | start | tuned |
|---|---|---|---|
| **all** | 0.343 (60% deals, 0.3 rd) | 0.360 (59% deals, 0.2 rd) | 0.360 (59% deals, 0.2 rd) |
| absent | 0.000 (0% deals, 0.0 rd) | 0.000 (0% deals, 0.0 rd) | 0.000 (0% deals, 0.0 rd) |
| cycler | 0.068 (32% deals, 0.9 rd) | 0.072 (32% deals, 0.5 rd) | 0.072 (32% deals, 0.5 rd) |
| deadline | 0.396 (67% deals, 0.4 rd) | 0.472 (67% deals, 0.5 rd) | 0.472 (67% deals, 0.5 rd) |
| fast | 0.794 (89% deals, 0.1 rd) | 0.799 (89% deals, 0.1 rd) | 0.799 (89% deals, 0.1 rd) |
| hardliner | 0.182 (62% deals, 0.7 rd) | 0.198 (62% deals, 0.1 rd) | 0.198 (62% deals, 0.1 rd) |
| linear | 0.635 (87% deals, 0.0 rd) | 0.657 (86% deals, 0.0 rd) | 0.657 (86% deals, 0.0 rd) |
| llm | 0.544 (87% deals, 0.3 rd) | 0.555 (87% deals, 0.4 rd) | 0.555 (87% deals, 0.4 rd) |
| oneshot | 0.181 (53% deals, 0.9 rd) | 0.197 (49% deals, 0.7 rd) | 0.197 (49% deals, 0.7 rd) |
| silent | 0.302 (62% deals, 0.0 rd) | 0.342 (67% deals, 0.0 rd) | 0.342 (67% deals, 0.0 rd) |
| steady | 0.575 (85% deals, 0.0 rd) | 0.595 (84% deals, 0.0 rd) | 0.595 (84% deals, 0.0 rd) |
| tft | 0.242 (68% deals, 0.8 rd) | 0.242 (67% deals, 0.9 rd) | 0.242 (67% deals, 0.9 rd) |
| worst quartile (all duels) | 0.000 | 0.000 | 0.000 |

Objective (0.75 x mean + 0.25 x worst quartile of per-kind means, absent excluded): defaults 0.2882, start 0.3038, tuned 0.3038.

### What moved

| param | duel.py default | tuned |
|---|---|---|
| last_r | 1.08 | 1.155 (moved) |
| max_msgs | 2 | 3 (moved) |
| last_chance_ticks | 2 | 2 |
| accept_any_ticks | 3 | 2 (moved) |
| near_ticks | 2 | 0 (moved) |
| stall_ticks | 3 | 5 (moved) |
| thin_frac | 0.5 | 0.586 (moved) |
| early_share | 0.85 | 0.898 (moved) |
| early_min_pie | 2 | 3.194 (moved) |
| pair_sell | 0.93 | 0.914 (moved) |
| pair_buy | 1.07 | 1.07 |
| absent_at | 0.5 | 0.18 (moved) |
| absent_share | 0.5 | 0.765 (moved) |
| absent_last | False | True (moved) |
| window_wait | True | False (moved) |
| anchor | 1.55 | 1.567 (moved) |
| floor | 1.22 | 1.22 |

### Two more referees

Friday replay: our policy against the price paths Friday's rival bots really posted (8 closed practice duels; the rivals do not react to us and never accept; the pie is the soft pie from the paired duel). duel.py selftest: `duel.simulate` (Thiago's own rival archetypes, 3000 duels, seed 7), mean value per duel with a zone of agreement.

| policy | Friday replay | duel.py selftest |
|---|---|---|
| defaults | 0.381 | 0.492 |
| start | 0.382 | 0.493 |
| tuned | 0.382 | 0.493 |

### Stress: what if the rival model is wrong

Mean score per duel on 100 more fresh sessions, all rival kinds, one change at a time (best per row in bold):

| variant | defaults | start | tuned |
|---|---|---|---|
| as modelled | 0.355 | **0.379** | **0.379** |
| rounds = min(our msgs, theirs) | 0.355 | **0.379** | **0.379** |
| accept slot busy 15% of ticks | 0.350 | **0.362** | **0.362** |
| 80% of rivals never accept ours | 0.351 | **0.370** | **0.370** |
| 20% of rivals never accept ours | 0.359 | **0.386** | **0.386** |
| paired limit noisier (+-8%, +-6 P) | 0.352 | **0.372** | **0.372** |
| firmer field (hardliner, llm, tft, cycler) | 0.322 | **0.340** | **0.340** |
| Friday archetypes only | 0.336 | **0.349** | **0.349** |
| we also see the rival's last-tick message | 0.377 | **0.403** | **0.403** |
| an accept at deadline-1 does not settle | **0.328** | 0.308 | 0.308 |

### Accepted steps

| gen | held-out objective | held-out mean | paired diff vs previous | Friday replay | selftest | mean if D-1 accepts do not settle |
|---|---|---|---|---|---|---|
| 0 | 0.3038 | 0.3602 | - | 0.382 | 0.493 | 0.290 |
