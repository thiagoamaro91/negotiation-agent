# Sunday dealer flags (manual run, game hour ~16.70)

**Recommendation: run the Sunday lines unchanged.** The grid found no config that beats the baseline on evidence
that holds for Sunday's targets: the only real-number gain (a higher Abuela cap) buys RET-07/RET-08 over our value,
and the Chato gains come from the dealer model alone. Results are **directional** (22 cases, no train/test split,
every paired CI includes 0).

Exact commands (the `cmd` of each step in `tools/factory_sunday.json`, `{python}` written as `python3`; no flag changed):

```
# Abuela, slots 1-3 (step r3-slots-1-3)
python3 -u agent/abuela.py run --only RET-07,RET-08,SAL-05 --cap 22 --reserve 20 --max-deals 3

# El Chato, rare slot 1 (step r3-slot-1-rare)
python3 -u agent/chato.py run --only SAL-09 --anchor 60 --step 4 --cap 88 --reserve 40 --max-deals 1 --max-rounds 40
```

Do **not** add `--max-bid` to the Chato line, and do **not** raise Abuela's `--cap` above 22 while RET-07/RET-08 are
the targets.

## Conditional changes (decide at 08:55 with the targets in hand)

| if | then | evidence |
|---|---|---|
| Abuela's uncommon targets change to cards whose book x set multiplier is 23 or more (no RET uncommon) | `--cap 23` | Grid pick for Abuela: paired delta `deal_in_limit` +0.045 +- 0.089, `range_share` +0.034 +- 0.067 (v3). Replayed real numbers: on abuela-105 her real final was 23, which cap 22 walks from. Cap 25 scores higher (+0.100 +- 0.123) but ties with 23 inside +-0.06, and the rule then takes the lower cap. |
| Chato's target is swapped to LAT-09 (the factory todo's alternative) | lower `--cap` to at most floor(book x LAT multiplier) for ladder credit, or accept the buy earns no ladder credit | LAT-09's book x multiplier is below 88: `--cap 88` would let the bot pay over value (the Friday pattern below). SAL-09 and SAL-10 are above 88: fine. |

## Evidence (22 cases x 5 dealer-model draws, paired with the baseline on the same draws)

| variant | config | deal_in_limit | range_share | limit_breach | over_value | paired delta deal_in_limit | paired delta range_share | over RET / deals |
|---|---|---|---|---|---|---|---|---|
| baseline | Sunday lines | 0.736 +- 0.176 | 0.546 +- 0.155 | 0 | 0 | | | 0/19 |
| v1 | Abuela cap 23; Chato step 2, max-bid 84 (the rule's pick) | 0.782 +- 0.163 | 0.591 +- 0.147 | 0 | 0 | +0.045 +- 0.089 | +0.044 +- 0.069 | 5/24 |
| v2 | Abuela cap 25; Chato step 2, max-bid 84 (top delta) | 0.836 +- 0.147 | 0.619 +- 0.138 | 0 | 0 | +0.100 +- 0.123 | +0.073 +- 0.080 | 11/30 |
| v3 | Abuela cap 23 only | 0.782 +- 0.163 | 0.580 +- 0.147 | 0 | 0 | +0.045 +- 0.089 | +0.034 +- 0.067 | 5/24 |

A/A noise floor: `deal_in_limit` +-0.06, `range_share` +-0.05. Full 27-row grid: `grid.md`.

**Why the rule's pick (v1) is not the Sunday line.**

1. *Abuela cap 23/25 fails the over_value guardrail on Sunday's targets.* The gain comes from two replayed real
   conversations (abuela-105, abuela-117): Abuela really names finals of 23 and 25 for uncommons, and a higher cap takes
   them. Those cases were cards worth more to us. RET-07/RET-08 are worth less than 23 to us (book x RET multiplier), so
   the same deals would be over value: in the replay, 5 of 24 Abuela uncommon deals at cap 23 and 11 of 30 at cap 25 close
   above our RET value, against 0 of 19 at cap 22 (`over RET` column). Over value means the ladder credits nothing (the
   Friday LAT-06 deal) and we lose P. The pick rule requires `over_value` not above the baseline, so cap 22 stays.
2. *Every Chato change rests on the dealer model, not on data* (flagged). chato-335 is the only Chato rare case. Steps 1
   and 2 leave the real path at our 2nd offer; the deal is then his drawn limit, because the real thread never revealed a
   final. The step-1/2 gain is +0.010 +- 0.020 `range_share`, inside the noise floor. The model cannot move his limit or
   patience with the step, and it is optimistic on Chato rares (held-out error 1.71 P on this thread). The field data
   points the other way: his 93 closes came from +1 steps, and +4 steps pulled him to 82 (dealer-ladder.md). Keep step 4.
3. *`--max-bid 84` with step 4 loses the deal*: it pins at 84 against his real 90 and closes in 5/5 draws (paired delta
   -0.036). `--max-bid 90` is above `--cap 88` and never binds. The factory todo already says no `--max-bid`.

## REQUIRED fix (separate PR, not done here): where the bot's limit comes from

Friday's two over-value Chato buys (LAT-06 at 28, LAT-07 at 29; `real_over_value` = 2/22 cases, chato-253 and chato-275)
were not negotiation errors. The bot's limit was set above our value:

- `build_plan` in `agent/chato.py` (buys, around line 462) and `agent/abuela.py` (around line 348) set the limit to
  `min(API /value your_value, --cap)`. Neither clips it to book x set multiplier, the value the ladder grades against.
- The run's `--cap 30` / `--cap 31` (bot logs for threads 234/253/275) were both above that value, and the API value was
  at least as high (the logged limit equals the cap). Nothing refused or warned.
- Fix: in both `build_plan`s, clip the buy limit to floor(book x affinity[set]) (first copy). Refuse, or at least print
  in `plan`, any `--cap` above it, and log both numbers at `open`. Until that lands, every manual `--cap` must be at or
  under the target's book x multiplier (Sunday: 22 for RET-07/08 holds; 88 for SAL-09 holds; 88 for LAT-09 does not).
- The eval cannot see this class of error in its replay. The harness hands the bot min(our value, cap), so modelled
  `over_value` is 0 by construction; it fires only on the real audit (`real_over_value`). A harness mode that uses the
  bot's own limit rule is a follow-up.

## Method

`tools/eval_dealers.py` grid (`--set abuela.cap`, `--set chato.rare.max_bid`, `--set chato.rare.step`). Cap {22, 23, 25}
x max-bid {none, 84, 90} x step {1, 2, 4}; step 4 was added to the approved {1, 2} so the baseline's own Chato
setting is in the grid. 5 draws per case, `--seed 0`, all runs on one read-only snapshot of the Mini's logs
(Saturday 21:33). The baseline was re-graded in place on the same snapshot: every earlier metric is identical row for
row, and only `over_value` / `real_over_value` were added. Pick rule: highest paired delta on `deal_in_limit` (then
`range_share`) with `limit_breach` = 0 and `over_value` not above the baseline; ties within +-0.06 go to the lower cap /
lower max-bid.
