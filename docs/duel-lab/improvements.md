# Duels I: code-level improvements to agent/duel.py

Built 2026-10-03 03:50-05:00 on `feat/duel-improve` (on top of PR #9, `feat/duel-lab`). Every change is a flag that
defaults OFF: with no flags, `duel.py` behaves byte for byte as Thiago's (checked: `selftest` output identical with
no flags and with the safe params file; the arena's results identical for three params sets, flags off). The arena
(`tools/duel_arena.py`) is the referee; `tools/duel_ab.py` runs every comparison below.

## Recommendation for Duels I

Turn on three flags, on top of the safe params: **`docs/duel-lab/duel-params-duels1-improved.json`**.

| flag | what it does | held-out gain |
|---|---|---|
| `--late-poll 8 --late-ticks 3` | In a tick where any of our open duels has 3 or fewer ticks left, that tick's accept waits for a **second read of the duels 8 s before the tick ends**, so the rival's message of that tick (its best one, at deadline-1, in 6/8 Friday duels) is seen before our accept. Messages still go out in the first read. | **+0.033** per duel |
| `--slot-demand acceptable` | When the accept window counts how many of our duels need a slot near a shared deadline, it counts only duels whose standing rival offer we would accept now (not silent rivals or offers outside our limit), so the duels that can deal wait for better offers instead of rushing to D-3. | +0.0046 |
| `--last-share 0.3` | With the paired limit visible, the last chance keeps 30% of the soft pie (`L + 0.3 x (pairL - L)`) instead of `1.08 x L`, which on a big pie gave the rival almost all of it. Still capped by `PAIR_SELL` / `PAIR_BUY` and our limit. | +0.0028 |

Together, held-out (300 fresh sessions, all eleven rival kinds): **0.394 per duel vs 0.354 for the safe file (+0.040
+- 0.0015, +11%) and 0.343 for duel.py's defaults (+15%)**. Better than the safe file on every referee and in every
stress row (tables below).

```
mkdir -p results && cp docs/duel-lab/duel-params-duels1-improved.json results/duel-params.json
python3 agent/duel.py watch --params results/duel-params.json            # read-only; the late read runs here too
python3 agent/duel.py run --until 12:30 --params results/duel-params.json  # after the yes in the team chat
```

`late_poll` is in seconds before the tick ends. Saturday's ticks are 30 s (`GET /api/clock`, `days[sat]`), so the
late read happens about 22 s into the tick. If the tick length changes, the wait is capped at one tick, and with
ticks shorter than 8 s the late read simply happens right after the first read.

**Leave off**: `--slot-order` (no effect), `--silent-steps`, `--late-say`, `--anchor-quiet` (each hurt held-out
rivals; removed from duel.py, kept in history), and the deadline-1 bet below until it is confirmed.

**Conditional, after Duels I shows an accept at deadline-1 settling**: add `"accept_any_ticks": 2, "near_ticks": 0`
(+0.0048 +- 0.0011 on top of the improved file, but -0.024 if an accept at deadline-1 never settles). To check it in
the log: an `accept` event with `left=1` followed by a `result` event with `status=deal` for that duel.

### What to watch in the first wave (logs/duel/<date>.jsonl)

- `rival ... late=True`: an offer the late read saw that the first read had missed. **If none appears in a whole
  wave while rivals post at the end, the server shows a message only from the next tick**, and the late read cannot
  gain anything; it costs nothing either (table "Server behaviours" below), so it can stay on.
- `accept ... late=True`: accepts taken in the late read. Next to the `result` they say what the late read earned.
- `error where=late attempt=N`: a read of the late pass failed and was retried. `late_skipped`, or errors on every
  attempt: the late read did not happen, and that tick's accept moves to the next tick's first read. `late_off`: two
  in a row, so the late read switched itself off for the rest of the run (behaviour is then the safe file's, plus
  the other two flags).

## How each change was judged

- **Design set**: arena seeds 0-199, the nine rival kinds the tuner used (steady, fast, cycler, oneshot, llm,
  absent, hardliner, linear, silent). Ideas were shaped here only.
- **Held-out set**: fresh seeds 500000-500299 (300 sessions x 34 duels), all eleven kinds, including tit-for-tat and
  deadline-only, which no change was designed on. A change is kept only if its **paired per-session mean-score
  difference against the current best is more than 2 standard errors above zero**, and it is **not worse than 2 SE
  on tit-for-tat + deadline alone**.
- **Three extra referees**, each must not fall more than 0.01 below the current best: the **Friday replay** (the 8
  real rival price paths of the practice wave), **duel.py's own `simulate()`** (Thiago's archetypes, 3000 duels,
  seed 7, a second and independent rival model), and the **stress where an accept at deadline-1 never settles**
  (held-out seeds).
- The late read is modelled honestly in all three simulators (arena, Friday replay, `simulate()`): one message per
  duel per tick, one accept per team per tick, accepts settle next tick, our message costs a round only when both
  sides have spoken. In the arena 15% of the rival's same-tick messages land after our late read anyway
  (`LATE_MISS`), 3% of late reads fail (`LATE_FAIL`); a failed read moves the accept to the next tick's first read
  and two failures in a row switch the late read off, exactly as duel.py's run loop does.

## Every attempt, kept or rejected

Numbers are held-out mean score per duel. "diff" is the paired difference against the best set at that moment.
Kept changes were re-measured with the final code (the rows marked final); rejected ones were measured with the
experiment code, commit `39a7670` (slot-order, silent-steps, late-say) and `fd80790` (anchor-quiet), which still
reproduce them (`python3 tools/duel_ab.py --base ... --cand '{...}'`).

| # | candidate | against | held-out mean | diff +- SE | diff on tft + deadline | Friday replay | duel.py selftest | D-1 never settles | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | late read, `late_ticks 1` | safe | 0.374 | +0.0201 +- 0.0013 | +0.071 +- 0.007 | 0.379 (+0.000) | 0.498 (+0.006) | 0.315 (+0.001) | passes |
| 1 | late read, `late_ticks 2` | safe | 0.384 | +0.0296 +- 0.0014 | +0.079 +- 0.008 | 0.392 (+0.013) | 0.499 (+0.006) | 0.333 (+0.019) | passes |
| 1 | **late read, `late_ticks 3`** (final) | safe | 0.387 | **+0.0330 +- 0.0015** | +0.086 +- 0.008 | 0.379 (+0.000) | 0.500 (+0.008) | 0.337 (+0.023) | **KEEP** |
| 1 | late read, `late_ticks 4` | safe | 0.386 | +0.0318 +- 0.0014 | +0.075 +- 0.007 | 0.396 (+0.017) | 0.500 (+0.008) | 0.338 (+0.023) | passes, below 3 |
| 2 | `slot_order stalled` / `pace` (design set) | best | - | +0.0002 +- 0.0003 / -0.0003 +- 0.0005 | - | - | - | - | REJECT (no effect) |
| 3 | **`slot_demand spoke`** (final) | 1 | 0.389 | **+0.0020 +- 0.0004** | -0.003 +- 0.002 | 0.518 (+0.139) | 0.503 (+0.003) | 0.337 (-0.000) | **KEEP** |
| 4 | `silent_steps 2` (design set: +0.0089) | 3 | 0.388 | -0.0016 +- 0.0010 | **-0.053 +- 0.005** | 0.518 (+0.000) | 0.511 (+0.008) | 0.340 (+0.004) | REJECT |
| 4 | `silent_steps 4` | 3 | 0.387 | -0.0030 +- 0.0012 | **-0.065 +- 0.006** | 0.518 (+0.000) | 0.511 (+0.007) | 0.340 (+0.003) | REJECT |
| 5 | **`last_share 0.3`** (final) | 3 | 0.392 | **+0.0028 +- 0.0003** | -0.001 +- 0.001 | 0.518 (+0.000) | 0.507 (+0.003) | 0.336 (-0.000) | **KEEP** |
| 5 | `last_share 0.45` (design set best: +0.0066) | 3 | 0.394 | +0.0040 +- 0.0006 | **-0.003 +- 0.001** | 0.518 (+0.000) | 0.510 (+0.007) | 0.337 (-0.000) | REJECT |
| 5 | `last_share 0.55` | 3 | 0.391 | +0.0018 +- 0.0007 | **-0.006 +- 0.002** | 0.518 (+0.000) | 0.510 (+0.006) | 0.336 (-0.000) | REJECT |
| 6 | `late_say` | 5 | 0.392 | -0.0013 +- 0.0003 | -0.005 +- 0.002 | 0.518 (+0.000) | 0.505 (-0.002) | 0.337 (+0.000) | REJECT |
| 7 | `anchor_quiet` (design set: +0.0017) | 5 | 0.388 | -0.0039 +- 0.0007 | **-0.035 +- 0.004** | 0.525 (+0.006) | 0.498 (-0.009) | 0.335 (-0.001) | REJECT |
| 8 | **`slot_demand acceptable`** (final) | 5 | 0.394 | **+0.0026 +- 0.0006** | -0.002 +- 0.002 | 0.518 (+0.000) | 0.508 (+0.002) | 0.336 (-0.000) | **KEEP** |
| 9 | `accept_any_ticks 2, near_ticks 0` (final) | 8 | 0.399 | +0.0048 +- 0.0011 | +0.006 +- 0.004 | 0.518 (+0.000) | 0.513 (+0.004) | **0.312 (-0.024)** | REJECT (conditional) |
| 9 | `window_wait false` | 5 | 0.384 | -0.0089 +- 0.0009 | -0.001 +- 0.003 | 0.518 (+0.000) | 0.497 (-0.010) | 0.338 (+0.002) | REJECT |
| 9 | `stall_ticks 5` (final) | 8 | 0.396 | +0.0019 +- 0.0003 | +0.001 +- 0.001 | 0.518 (+0.000) | 0.505 (-0.003) | 0.337 (+0.001) | passes; not included |

Ablation of the final set (each flag removed from the improved file): without the late read -0.033 +- 0.0015;
`slot_demand open` -0.0045 +- 0.0007; without `last_share` -0.0033 +- 0.0004. Order matters for one step:
`slot_demand acceptable` straight on top of the late read (without `last_share`) is +0.0042 +- 0.0007 overall but
-0.0062 +- 0.0026 on tit-for-tat + deadline (2.4 SE, a reject by the rule); reached through `spoke` and
`last_share`, each step passes. Its total cost on those two kinds is -0.0044 +- 0.0026 (1.7 SE). If Thiago prefers
the stricter reading, use `"slot_demand": "spoke"`: 0.392 instead of 0.394, same Friday replay.

### 1. Late read (`--late-poll`, `--late-ticks`): kept

The lab's biggest lever, now as code. Each tick, `run` reads the duels once at the start of the tick (about 0.4 s
after it changes) and acts. Rivals post during the tick, so the rival's best offer at deadline-1 was never seen
before our last accept. With the flag:

- `late_due()`: the tick gets a second read when one of our open duels has `late_ticks` or fewer ticks left.
- `allocate(..., late=False)`: in such a tick the first read accepts nothing (the chosen accept is marked `late`);
  messages still go out in the first read.
- `late_pass()`: sleeps until `late_poll` seconds before the tick ends, re-reads the clock (skips if the tick is
  over or paused) and the duels (retried after 1 s while 2 s of the tick remain), decides again on fresh data,
  `allocate(..., late=True)` and accepts (the usual re-read and offer-id check right before the POST). It logs
  the rival offers it saw that the first read missed.
- Safety: a late read that did not happen makes the next tick accept in its first read (no chain of held ticks);
  `LATE_MAX_FAILS` (2) failures in a row set `late_poll` to 0 for the rest of the run; the wait is capped at one
  tick even if `next_tick_in` is wrong.

`late_ticks 3` won on the design set (D-1 only +0.009, D-1 and D-2 +0.019, last 3 ticks +0.023, then flat to 16).
The last three ticks are where the accept window lives, so every window accept sees the rival's same-tick message.

### 2. Accept-slot allocation: `--slot-demand` kept, `--slot-order` rejected

`set_windows` and the `window_wait` rule count the duels that need an accept slot near a shared deadline. Thiago's
code counts every open duel; a silent rival (4 of 12 closed Friday duels) or an offer outside our limit never needs
one, but it made the other duels accept at D-3 instead of waiting. `spoke` counts only rivals that spoke;
`acceptable` only standing offers we would accept now. On the Friday replay `spoke` alone moves 0.379 to 0.493
(0.518 with the late read): the practice waves had up to 6 duels per deadline, several with absent rivals.

`--slot-order stalled | pace` changed which acceptable duel takes the tick's one accept (the rival that stopped
moving first, or the one that gains us least per tick of waiting): no measurable effect (+0.0002, -0.0003). Removed.

### 3. Last-chance number (`--last-share`): kept at 0.3

The last chance (D-2, to a stalled rival with no acceptable offer, and to a rival that never spoke with
`absent_last`) was `1.08 x L`: on a pie of 50% of L it leaves the rival about 85% of it. A share of the soft pie
adapts to the pie's size. 0.3 is the largest share that does not cost tit-for-tat + deadline rivals more than 2 SE;
0.45 was best on the design set but hurt them.

### 4. Silent-rival ladder (`--silent-steps`): rejected

Messages to a rival that never spoke cost no round, so step from the absent-rival offer down to the last chance in
N extra offers. +0.009 on the design set (the `silent` kind accepts the first good-enough step), but deadline-only
rivals (silent until the end, then one number near their limit) take our falling offers instead of posting their own:
-0.053 on them. A textbook case for the held-out kinds.

### 5. Messages wait for the late read too (`--late-say`): rejected

In a duel's last ticks, decide the message after the rival's same-tick message. -0.0013 overall, -0.005 on
tit-for-tat + deadline: a rival that posts at D-2 now looks "moving" and no longer gets our last chance.

### 6. Anchor only a rival that went quiet (`--anchor-quiet`): rejected

Per-kind probe on the design set: anchors cost hardliner (+0.008 without), cycler (+0.006) and steady (+0.004)
rivals, which keep posting and never react, and pay against llm (-0.008) and oneshot (-0.005), which wait for us.
So: anchor only a rival that has posted nothing for more than `stall_ticks` ticks. +0.0017 on the design set,
-0.0039 held-out, -0.035 on tit-for-tat: that bot also keeps posting and never moves, but it needs our anchor to
measure the step of our next message. The held-out kinds caught it.

## Server behaviours the gains rest on (unconfirmed), both cases measured

Held-out seeds, improved file vs safe file:

| assumption | if wrong | improved vs safe |
|---|---|---|
| (none) | - | 0.3943 vs 0.3539 (+0.0404 +- 0.0015) |
| GET /api/duels shows a rival's message as soon as it is posted, not from the next tick | the late read sees nothing new | 0.3607 vs 0.3539 (+0.0068 +- 0.0006, the other two flags; the late read only moves accepts later in the tick) |
| an accept at deadline-1 settles (11 Friday field deals were recorded on the deadline tick) | D-1 accepts are lost | 0.3359 vs 0.3141 (+0.022): the improved set still keeps deadline-1 as a retry |
| the late read happens (network, timing) | every late read fails | 0.3548 vs 0.3539 (+0.0009 +- 0.0008; it switches itself off after two) |
| both of the last two wrong at once | - | 0.3069 vs 0.3141 (-0.007) |
| both "same-tick messages" and "deadline-1 settles" wrong at once | - | 0.3100 vs 0.3141 (-0.004) |
| an accept late in a tick settles like one at its start | - | not testable offline; the run log shows it (`accept ... late=True`, then `result`) |

## Stress: what if the rival model is wrong

Mean score per duel on 150 more fresh sessions (seeds 700000..), all rival kinds, one change at a time (best per
row in bold). "safe + late read" is the safe file with only `--late-poll 8 --late-ticks 3`.

| variant | duel.py defaults | safe | safe + late read | improved |
|---|---|---|---|---|
| as modelled | 0.354 | 0.359 | 0.389 | **0.399** |
| rounds = min(our msgs, theirs) | 0.354 | 0.359 | 0.389 | **0.399** |
| accept slot busy 15% of ticks | 0.346 | 0.348 | 0.376 | **0.382** |
| 80% of rivals never accept ours | 0.350 | 0.352 | 0.385 | **0.394** |
| 20% of rivals never accept ours | 0.357 | 0.366 | 0.392 | **0.404** |
| paired limit noisier (+-8%, +-6 P) | 0.349 | 0.355 | 0.384 | **0.393** |
| firmer field (hardliner, llm, tft, cycler) | 0.336 | 0.345 | 0.372 | **0.379** |
| Friday archetypes only | 0.337 | 0.341 | 0.359 | **0.367** |
| we also see the rival's last-tick message | 0.371 | 0.377 | 0.392 | **0.401** |
| an accept at deadline-1 does not settle | 0.317 | 0.313 | 0.339 | **0.341** |
| late read: 40% of rival messages land after it, 15% of reads fail | 0.354 | 0.359 | 0.370 | **0.378** |
| late read: every one fails (it switches itself off) | 0.354 | 0.359 | 0.354 | **0.363** |

## Held-out by rival kind

Cells: mean score per duel (deal rate, rounds per deal). tft and deadline were never used to design anything.

| rivals | duel.py defaults | safe | improved |
|---|---|---|---|
| **all** | 0.343 (60% deals, 0.3 rd) | 0.354 (61% deals, 0.3 rd) | **0.394 (64% deals, 0.3 rd)** |
| absent | 0.000 (0% deals) | 0.000 (0% deals) | 0.000 (0% deals) |
| cycler | 0.069 (32% deals, 0.9 rd) | 0.069 (32% deals, 0.9 rd) | 0.092 (38% deals, 0.9 rd) |
| deadline | 0.402 (68% deals, 0.4 rd) | 0.475 (69% deals, 0.5 rd) | 0.583 (83% deals, 0.6 rd) |
| fast | 0.793 (89% deals, 0.1 rd) | 0.802 (89% deals, 0.1 rd) | 0.802 (89% deals, 0.1 rd) |
| hardliner | 0.181 (63% deals, 0.7 rd) | 0.181 (63% deals, 0.7 rd) | 0.225 (68% deals, 0.7 rd) |
| linear | 0.636 (87% deals, 0.0 rd) | 0.642 (87% deals, 0.0 rd) | 0.701 (89% deals, 0.0 rd) |
| llm | 0.542 (87% deals, 0.3 rd) | 0.543 (87% deals, 0.3 rd) | 0.562 (88% deals, 0.3 rd) |
| oneshot | 0.181 (53% deals, 0.9 rd) | 0.186 (53% deals, 0.8 rd) | 0.196 (52% deals, 0.7 rd) |
| silent | 0.302 (62% deals, 0.0 rd) | 0.340 (76% deals, 0.0 rd) | 0.372 (75% deals, 0.0 rd) |
| steady | 0.577 (86% deals, 0.0 rd) | 0.579 (86% deals, 0.0 rd) | 0.666 (89% deals, 0.0 rd) |
| tft | 0.244 (69% deals, 0.8 rd) | 0.245 (69% deals, 0.8 rd) | 0.295 (77% deals, 0.9 rd) |

Friday replay (8 closed practice duels, real rival paths, rivals never accept, soft pie): defaults 0.381, safe
0.379, improved **0.518** (9: 0.79, 10: 0.71, 29: 0.04, 30: 0.24, 37: 0.30, 38: 0.53, 93: 0.69, 94: 0.85).

duel.py `selftest` (value per duel with a zone of agreement): `--n 1000` defaults 0.497, safe 0.498, improved 0.520;
`--n 3000` improved 0.507; PASS with 0 violations in every case, also with only `--late-poll 8 --late-ticks 3`.

## Tests

`python3 -m unittest discover tests` (35 tests). `tests/test_duel_improve.py` covers the flags' pure parts and drives
duel.py's real `run` loop end to end against a fake server on a virtual clock (no network, no key; `load_env` is
replaced so `.env` is never read): without the flag we accept what stood at the start of the tick; with it the late
read takes the offer the rival posted 5 s into the same tick, about 8 s before the tick ends, and logs it; a failed
read is retried in the tick, falls back to the next tick's first read, and two in a row switch it off. Each of these
tests was checked to fail when its feature is broken (deferral, slot demand, last share, switch-off, retry,
fallback).

## Risks

- The rival model is a guess fitted to 8 Friday paths. The late read's gain does not depend much on it (it only
  needs rivals whose last messages are their best, as in 6/8 Friday duels), but it does depend on the server
  showing same-tick messages: the first wave's `rival ... late=True` lines answer that.
- The late read holds a tick's accept for about 20 s. A late read that fails at deadline-1 loses that duel's
  accept (priced in the arena at 3% of reads; retries make it rarer). If the box running duel.py is slow or its
  network flaky, turn it off (`--late-poll 0`) and keep the other two flags.
- The run loop sleeps inside the tick during the late read; one process per team still holds (it is the same
  process). The duel.lock is refreshed at the start of every tick and lasts 3 ticks, so it covers the wait.
- `slot_demand acceptable` costs tit-for-tat + deadline rivals -0.004 +- 0.003 in the model (not significant);
  `spoke` is the stricter choice.
