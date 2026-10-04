# Duels III and the Grand Final: parameters (Sunday 4 Oct)

**File: `docs/duel-lab/duel-params-duels3.json`.** The factory starts the bot with it (`tools/factory_sunday.json`,
process `duel`): `agent/duel.py run --params docs/duel-lab/duel-params-duels3.json --duel-ticks 12 --late-poll 4
--idle-ticks ... --until ...`. Flags win over the JSON. The file is the one that played Duels II
(`duel-params-duels2-blend.json`) plus four keys. Decision matrix: [duels3-matrix.md](duels3-matrix.md).

## What the bot will do (12-tick duels, decay 0.10, up to 4 at once)

- **Delivery day.** The file confirms Saturday's direction: `"days_best": "buyer:0,seller:10"`. As a seller we earn
  our weight per delivery day from day 0; as a buyer we pay it per day (the Duels II server's wording and payouts).
  Every accept values the rival's (price, day) that way. When the day is dear for us (10 x weight > 0.174 x our
  limit, most duels), every number we send names our best day: day 10 as a seller, day 0 as a buyer. When the day
  is cheap for us, we give the rival the day it wants and ask our days cost back in price, plus a premium that falls
  from 1.33 x to 0.43 x that cost.
- **With a rival that has not spoken.** We listen to tick 3 (`absent_at` 0.18 of 12 ticks). Then we make one offer
  at the floor ratio: 1.306 x our cost as a seller, our value / 1.306 as a buyer. With 4 ticks left we make the last
  chance at 1.155 (`absent_last`). An offer to a silent rival costs no round until it answers.
- **When we open with a rival that speaks.** We stay silent while it moves toward us (listening is free). We anchor
  at 1.624 only when it has stalled for more than 3 ticks and its offer is below our limit, or thin (under 0.216 of
  what our anchor would bring). We send at most 2 messages. With 4 ticks left the last chance (1.155) goes to a
  stalled rival and, **new (F4, `last_while_moving`), also to a rival still conceding whose offer we would not
  accept**.
- **When we accept.** We take any offer inside our limit worth at least 1 P in the last 6 ticks (half the duel).
  While the rival is still conceding, a lone duel waits for deadline-2 and keeps deadline-1 as the retry. We get one
  accept per tick across all duels: the allocator keeps the biggest surpluses that can all still get a tick. In the
  last 3 ticks the accept waits for the late read, 4 s before the tick ends, so the rival's message of that tick is
  seen first. No early accept: the paired limit is never visible (Duels I and II: 0 of 102).

## What changed versus Duels II, and why

| change | why | measured (arena, Duels II field at the Duels III shape, 1000 fresh sessions) |
|---|---|---|
| `days_best` in the file | The factory passes no `--days-best`. Without it, the bot plays robust mode: it takes every days cost at its worst over best day 0 and best day 10. Under the server's model that refuses many seller deals | robust mode costs **0.044-0.047 a duel** (matrix: 0.313 vs 0.357) |
| F4 `last_while_moving` on (new flag in `agent/duel.py`, default off) | Duels II 5905: the rival conceded 2 P a tick at day 5 and ended 3 P outside our limit; we never spoke. In Duels II, rivals that had spoken took our last chance 10 times out of 21 | **+0.0083 ± 0.0007** a duel; +0.0092 if a deadline-1 accept never settles; positive in all 8 climb worlds |
| `duel_ticks` 12, `late_poll` 4 | Duels III shape; the factory passes both anyway | - |

**Messages and the tick budget** (review of #72). With F4, several duels can take a message in the same tick. The
run loop takes the tick's accept first. Each message then goes once, with no client retries, and its timeout is
capped so it ends 1 s before the tick ends, or 5 s before when the tick has a late read. After that point nothing
more is sent this tick (`say_budget` in the log), and the next tick decides again on fresh duels.

Where F4 loses (matrix): `llmfair` rivals alone -0.014, light day weights (0-1 P/day) -0.008. Neither matches the
Duels II field (real weights 0.6-8.9 P/day). On the Duels II replay F4 is neutral (rivals there never accept, so a
last chance cannot convert). On the Duels I replay it costs 2.9 P of 558. A paced variant tested offline cut both
losses by about a third: the last chance goes only if the rival's recent pace will not reach our limit by the
deadline. It is not shipped (more code, the same gain in the Duels II field).

## Operator checks (Sunday)

- On the first buyer and the first seller `duel_new` line of `logs/duel/<date>.jsonl`, `days_meaning` must read as
  on Saturday: the seller line "each delivery day adds this much cash to your side", the buyer line "each delivery
  day costs you this much cash". **If either reads otherwise, delete the `days_best` line from the params file and
  restart the duel process.** Robust mode never deals below our limit, whatever the wording. In the matrix, if the
  direction flipped, this file would score 0.318 against robust mode's 0.398.
- Also watch for `accept_mismatch`, `bad_duel`, `late_failed` / `late_off` (see duels2-params.md), and
  `say_budget` (a message dropped for lack of time: fine now and then; in every tick it means the server is slow).

## Known gap: the accept race (inherited, not fixed)

`POST /api/duels/{id}/accept` names no offer: the server accepts whatever stands when the POST lands. Right before
the POST the bot re-reads the duel and compares the offer's id AND its terms (`fresh_check`). A worse replacement is
skipped, and the tick's accept goes to the next candidate. What no client-side guard can close is the gap between
that re-read and the POST landing, a fraction of a second. If the rival replaces its offer inside that gap, the
accept takes the new terms. Example: a buyer approves (90, day 0), the rival posts (110, day 10), and the deal
settles at -40 P for us. A rival can post once per tick, and with the late read our accept goes 4 s before the tick
ends. The bot logs it afterwards as `accept_mismatch`, once from the POST response and once with where=settled from the
result. Saturday had one, and it went our way (5667: approved 102 / day 0, settled 87 / day 10, worth 53.7 P
instead of 27). **Operator check:** grep `accept_mismatch` after each wave. If one shows a loss, tell the team; the
fix would be on the server side (an offer id on the accept).

## What Duels II showed (the field we refit on)

Sources: `logs/duels/` server session 3 (our 68 duels, Saturday 21:16-23:00) and `logs/duel/2026-10-03.jsonl`
(`tools/duel_field_read.py --log logs/duel/2026-10-03.jsonl --since 21:16`). The run played the blend with
`--days-best buyer:0,seller:10`. Duels II: 16 ticks, decay 0.08, 6 at once.

| | number |
|---|---|
| duels / deals / sum of results | 68 / 57 / 1493.9 P (26.2 P per deal, 22.0 per duel) |
| deals closed by our accept / by the rival taking our offer | 43 / 14 |
| rounds per deal | 0: 23, 1: 24, 2: 10 |
| **rivals that never spoke** | **8 / 68 (12 %)**: 3 took our first offer, 5 never took anything |
| rivals that spoke first at tick 0 / 1 / 2 / 3 / later | 32 / 9 / 8 / 10 / 1 (of 60) |
| **rivals still conceding in the last 4 ticks** (last move at tick 12-15 of 16) | **27 / 68 (40 %)**; in the last 3 ticks 18 (26 %); never conceded 12 of 60 |
| our accepts, tick of the duel | 10: 14, 11: 4, 12: 3, 13: 5, 14: 13, 15 (deadline-1): 4. All four deadline-1 accepts settled (30 s ticks) |
| **our last offer still short of our limit** | in **all 47** duels where we spoke; in the no-deals, 9 to 46 P of surplus left |
| shapes (field read) | every tick 28, oneshot 11, jump and hold 8, stepped 8, silent 8, reactive 5 |
| **our day weights**, P/day | **buyers 1.23-8.91** (median 3.5, mean 4.1); **sellers 0.58-6.24** (median 2.3, mean 2.6) |
| the rival's day | rival buyers (best day 0) ended on day 0 in 22 of 31, on our day 10 in 4, on day 5 or 3 in 5; rival sellers (best day 10) moved to our day 0 in 13 of 29, kept day 10 in 12, day 5 in 2, other 2 |
| deal days | sold at day 0: 19 of 30, day 10: 6, day 5: 4, day 3: 1; bought at day 0: 17 of 27, day 10: 8, other: 2 |

**Where the 11 no-deals were lost** (7 as buyer, 4 as seller):

| duels | what happened |
|---|---|
| 5760, 5761, 6009, 6152, 6153 | the rival never spoke and never took our two offers (tick 3 at the floor ratio, tick 12 the last chance) |
| 5695, 6008 | one-shot rivals whose one number was outside our limit (-95 P and -3 P for us); our two offers were not taken |
| 5787 | the rival conceded every tick but stayed 15 P outside our limit; our last chance at tick 12 was not taken |
| 5789 | the rival seller held day 10 (42 P of days cost for us) and stalled 24 P outside our limit; our last chance went at tick 15, too late |
| 5905 | the rival conceded 2 P a tick at day 5 and ended 3 P outside our limit; **we never spoke** (the last chance only went to a stalled or silent rival: F4) |
| 5644 | the rival opened at 110 / day 10 (+69 P for us), then fell to 84 and to 72 / day 0 while we waited for the accept window. Our window accept lost the one accept per tick to other duels (before the 21:30 seller hot patch, the bot also valued day 10 at 0) |

## The arena refit (`tools/duel_arena.py --weights duels2`)

- **Rival mix** `DUELS2_WEIGHTS`: linear 28, steady 8, fast 8, oneshot 11, tft 5, silent 3, absent 5.
- **Day weights** `DUELS2_DAYS_W`: each side's weight is drawn from the 34 real weights of its role. The draw is
  the empirical quantile, so buyers care more than sellers.
- **The rival's day** `DUELS2_DMODE` (by the rival's role): rival buyers keep their best day 22 : flex 4 : mid 5;
  rival sellers best 12 : flex 13 : mid 2 : random 2.
- **Duels II replay** (`duels2_replay`): the real (price, day) paths on the real timeline. Rivals do not react or
  accept, so the replay shows what waiting costs and never what a message wins. The blend scores 1204 P on the 60
  scored duels (the real run made 1415.5 P, including the 14 deals where the rival took our offer).
- **The day term.** Over 13,600 arena duels it adds 4.0 P on average to a 49.6 P price pie (7 %), and only in 29 %
  of duels (when the seller's weight is the larger). Day 0 is the jointly best day in 71 %. With real weights drawn
  independently, the seller cares more in 29 % of pairs. Holding day 10 as a seller is worth 10 x our weight to us
  (25.8 P on average) only when the buyer accepts it, and rival buyers kept day 0 in 22 of 31 duels.
- **Calibration gaps (known, not fixed).** We replayed the blend in the refit world at Duels II's shape (16 ticks).
  Deal rate: 65 % in the arena vs 84 % real. Seller deals at day 10: 3 % vs 20 %. Buyer deals at day 0: 26 % vs 63 %.
  Rival takes our offer: 12 % vs 25 % of deals. 0-round deals: 78 % vs 40 %. The arena's rivals concede to the end
  more smoothly than the real ones, so the bot rarely speaks there. Treat arena deltas as directions with sizes, not
  forecasts.

## Hypotheses (a) to (e)

600 fresh sessions per cell (seeds 900000..), each a one-lever change on the blend; delta vs the blend with 95 % CI.
Every cell also has the accept slot taken by another agent in 3 % of ticks (`slot_busy` 0.03, the tuner's
assumption); the "slot busy 15 %" column raises that to 15 %. The matrix uses a free slot (0 %), so its numbers
differ slightly.
**Bold** = better beyond the CI, _italic_ = worse. Kept only if better beyond noise in the Duels II field AND no
world worse beyond noise. Climb script: `docs/duel-lab/duels3-lab/climb3.py` (`hyp`: this table; `eval`: the
1000-session rows, with `TEST0=1100000`; `coord`: the search below).

| change | Duels II field | ... D-1 never settles | ... slot busy 15 % | Duels I mix | likely field |
|---|---|---|---|---|---|
| (a) `absent_at` 0 (offer to a silent rival at tick 0) | _-0.0060_ ±0.0017 | **+0.0032** ±0.0018 | _-0.0033_ ±0.0017 | _-0.0326_ ±0.0017 | _-0.0358_ ±0.0018 |
| (a) `absent_at` 0.09 (tick 2) | **+0.0019** ±0.0011 | **+0.0040** ±0.0012 | **+0.0021** ±0.0012 | _-0.0095_ ±0.0010 | _-0.0063_ ±0.0010 |
| (a) `absent_at` 0.3 (tick 4) | _-0.0010_ ±0.0002 | _-0.0009_ ±0.0002 | _-0.0010_ ±0.0002 | _-0.0002_ ±0.0001 | +0.0000 ±0.0000 |
| (a) open at the anchor at tick 0 | **+0.0042** ±0.0016 | **+0.0072** ±0.0019 | **+0.0056** ±0.0016 | _-0.0152_ ±0.0014 | _-0.0160_ ±0.0015 |
| (a) `absent_last` off | _-0.0035_ ±0.0005 | _-0.0033_ ±0.0005 | _-0.0035_ ±0.0005 | _-0.0049_ ±0.0006 | _-0.0050_ ±0.0007 |
| (a) `silent_last_margin` 0.1 | **+0.0005** ±0.0003 | **+0.0004** ±0.0003 | **+0.0005** ±0.0003 | **+0.0010** ±0.0004 | **+0.0010** ±0.0004 |
| (b) `last_chance_ticks` 1 | _-0.0259_ ±0.0012 | _-0.0192_ ±0.0012 | _-0.0252_ ±0.0012 | _-0.0157_ ±0.0010 | _-0.0370_ ±0.0017 |
| (b) `last_chance_ticks` 2 (the evals' v1 lever) | _-0.0029_ ±0.0007 | _-0.0209_ ±0.0013 | _-0.0031_ ±0.0008 | _-0.0014_ ±0.0005 | **+0.0036** ±0.0008 |
| (b) `last_chance_ticks` 3 | -0.0002 ±0.0005 | _-0.0025_ ±0.0008 | _-0.0010_ ±0.0006 | -0.0001 ±0.0004 | +0.0002 ±0.0006 |
| (b) `last_chance_ticks` 6 | +0.0003 ±0.0005 | **+0.0023** ±0.0008 | +0.0003 ±0.0006 | **+0.0007** ±0.0004 | **+0.0012** ±0.0008 |
| (b) `last_r` 1.12 | +0.0001 ±0.0005 | +0.0003 ±0.0005 | +0.0002 ±0.0005 | **+0.0008** ±0.0005 | +0.0001 ±0.0007 |
| (c) accept at once (window 12, no wait) | _-0.1525_ ±0.0023 | _-0.1206_ ±0.0022 | _-0.1367_ ±0.0022 | _-0.1637_ ±0.0025 | _-0.1615_ ±0.0025 |
| (c) `window_wait` off | _-0.0688_ ±0.0014 | _-0.0373_ ±0.0016 | _-0.0549_ ±0.0015 | _-0.0725_ ±0.0016 | _-0.0732_ ±0.0016 |
| (c) `accept_any_ticks` 4 | **+0.0046** ±0.0009 | _-0.0058_ ±0.0013 | +0.0010 ±0.0011 | **+0.0021** ±0.0008 | **+0.0053** ±0.0010 |
| (c) `accept_any_ticks` 8 | _-0.0063_ ±0.0007 | _-0.0051_ ±0.0007 | _-0.0059_ ±0.0008 | _-0.0052_ ±0.0007 | _-0.0081_ ±0.0011 |
| (c) `window_retry` 0 | **+0.0099** ±0.0011 | _-0.1190_ ±0.0022 | _-0.0082_ ±0.0015 | **+0.0090** ±0.0011 | **+0.0118** ±0.0014 |
| (c) `hold_while_conceding` (F1) | _-0.0170_ ±0.0013 | _-0.1057_ ±0.0022 | _-0.0263_ ±0.0015 | _-0.0182_ ±0.0013 | _-0.0094_ ±0.0015 |
| (c) F1 without the counter | **+0.0118** ±0.0011 | _-0.1124_ ±0.0022 | _-0.0049_ ±0.0014 | **+0.0110** ±0.0011 | **+0.0144** ±0.0013 |
| (c) `stall_ticks` 2 | **+0.0054** ±0.0009 | **+0.0085** ±0.0012 | **+0.0060** ±0.0010 | **+0.0012** ±0.0009 | _-0.0028_ ±0.0010 |
| (d) `days_cheap` 0 (always hold our best day) | _-0.0026_ ±0.0005 | _-0.0027_ ±0.0005 | _-0.0029_ ±0.0005 | _-0.0029_ ±0.0006 | _-0.0056_ ±0.0009 |
| (d) `days_cheap` 0.1 | _-0.0015_ ±0.0004 | _-0.0016_ ±0.0005 | _-0.0016_ ±0.0005 | -0.0001 ±0.0005 | -0.0005 ±0.0007 |
| (d) `days_cheap` 0.25 | _-0.0019_ ±0.0006 | _-0.0014_ ±0.0006 | _-0.0016_ ±0.0006 | _-0.0027_ ±0.0006 | _-0.0043_ ±0.0009 |
| (d) `days_cheap` 0.5 | _-0.0190_ ±0.0012 | _-0.0156_ ±0.0012 | _-0.0183_ ±0.0012 | _-0.0085_ ±0.0008 | _-0.0162_ ±0.0013 |
| (d) `days_premium` [0.6, 0.2] | **+0.0003** ±0.0002 | **+0.0005** ±0.0003 | +0.0002 ±0.0003 | +0.0001 ±0.0003 | +0.0002 ±0.0005 |
| `ratios` [2.0, 1.4] | +0.0000 ±0.0004 | _-0.0006_ ±0.0005 | -0.0000 ±0.0004 | **+0.0008** ±0.0004 | -0.0000 ±0.0008 |
| `late_poll` 0 (no late read) | _-0.0211_ ±0.0008 | _-0.0132_ ±0.0011 | _-0.0190_ ±0.0009 | _-0.0212_ ±0.0008 | _-0.0301_ ±0.0010 |
| **F4 `last_while_moving`** (1000 sessions from 1100000) | **+0.0083** ±0.0007 | **+0.0092** ±0.0008 | **+0.0080** ±0.0007 | **+0.0037** ±0.0006 | **+0.0014** ±0.0008 |
| v1 from the evals climb (final + `last_chance_ticks` 2; file `duels3-lab/v1-evals.json`) | -0.0010 ±0.0017 | _-0.0859_ ±0.0025 | _-0.0188_ ±0.0019 | _-0.0052_ ±0.0015 | -0.0006 ±0.0022 |

Answers:

- **(a) Mute rival.** Opening at tick 0 (anchor or floor) costs a round with every rival that speaks at tick 0:
  32 of 60 in Duels II. On the Duels II replay `absent_at` 0 alone loses 52.5 P of 1204 (21 duels each lose 8 %),
  and in the Duels I mix and the likely field it loses 0.015 to 0.036. Silence costs 100 % of the pie only with a
  rival that would have taken an early offer. Duels II had 8 silent rivals; the 3 that dealt took our tick-3 offer
  (2) or the tick-12 last chance (1). Tick 3 (the blend) stays. `silent_last_margin` 0.1 clears the bar by +0.0005,
  but it is left out: real silent no-deals refused 1.08 x L in Duels I too, so they look like dead bots, and 5917
  took our 1.155 last chance (64 P at day 10), where 1.10 would have given away 4 P.
- **(b) Last-chance timing.** 4 ticks left stays. 2 ticks loses 0.021 when a deadline-1 accept never settles,
  and 1 tick loses 0.016 to 0.037 everywhere. The gain is in who gets the last chance (F4), not when. **v1** (the
  evals climb's file, `last_chance_ticks` 2 plus the Duels II final's window `accept_any_ticks 2, near_ticks 0`)
  depends on the slot. Over seeds 1100000-1100999 in the Duels II field it is +0.0031 ± 0.0012 against the blend
  with a free accept slot and -0.0020 ± 0.0013 with the slot busy 3 % of ticks. Either way it loses 0.084 when a
  deadline-1 accept never settles: rejected on that stress. Reproduce: `python3
  docs/duel-lab/duels3-lab/paired_v1.py`. (The shipped file: +0.0082 and +0.0083 there.)
- **(c) Accept while the rival concedes, or wait.** Wait: accepting at once loses 0.15, and turning off the window
  wait loses 0.07. The levers that wait longer (`window_retry` 0, F1 without the counter, `accept_any_ticks` 3-4)
  gain up to +0.012 when deadline-1 settles. They lose 0.006 to 0.12 when it does not, and on the Duels II replay a
  4-tick window loses 32 P (slot clashes: 5644, 5645). The blend's 6-tick window stays.
- **(d) Days.** The blend already plays it right: `days_cheap` 0.174 beats every other value tried, and "always ask
  for our best day" (`days_cheap` 0) loses 0.003 to 0.006. The day term adds 7 % to the pie, in 29 % of duels.
  Buyers' weights are larger, so day 0 is usually the efficient day. Rival buyers kept day 0 in 22 of 31 duels,
  while rival sellers gave us day 0 in 13 of 29. The real lever was the days direction itself: confirming it in the
  file is worth 0.044-0.047 a duel.
- **(e) Deadline-1 stress.** The shipped file gains +0.0092 there (it never relies on a deadline-1 accept).
  Everything that bets on deadline-1 is out.

## The search, and why its winner is not shipped

A coordinate search from the blend (300 tune sessions, `climb3.py coord`) moved `absent_at` 0, `ratios` [2.0, 1.4],
`max_msgs` 3, `accept_any_ticks` 4 and `thin_frac` 0.5. In the Duels II field family it scored +0.015. It lost 0.011
in the Duels I mix, 0.018 to 0.023 in the likely field, and 110 P (-9 %) on the Duels II replay, mostly from
`absent_at` 0. That move opens with our best day at tick 0: deals at our best day double (sellers at day 10 from 3 %
to 13 %, buyers at day 0 from 23 % to 50 %), but rounds per deal go from 0.2 to 1.1. Not shipped: its gain depends
on how the arena's flex rivals follow our first day.

## Reproduce

```bash
python3 tools/duel_arena.py --session 3 --weights duels2 --days-mode buyer:0,seller:10 --slot-busy 0.03 \
    --params docs/duel-lab/duel-params-duels2-blend.json --params docs/duel-lab/duel-params-duels3.json
python3 tools/duel_matrix.py --session 3 --sessions 200 --seed0 970000 --params blend=<blend + days_best> \
    --params duels3=docs/duel-lab/duel-params-duels3.json --params v1=<evals v1 + days_best> \
    --out-md docs/duel-lab/duels3-matrix.md
python3 agent/duel.py selftest --params docs/duel-lab/duel-params-duels3.json     # SELFTEST PASS
```
