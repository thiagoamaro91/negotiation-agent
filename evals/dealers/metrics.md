# Dealer negotiators: metrics, evaluation model, limitations

Flow `dealers`, runner `tools/eval_dealers.py`, tests `tests/test_eval_dealers.py`. Proposal for sign-off: the
metric list, the grading rules and the case set below are what the user signs off. Offline only: no key, no network,
nothing posted; it reads `--logs` (default `logs/`; the committed baseline read `/Volumes/bazaar/logs`, the Mini's
live logs, which have every conversation to tick 1201).

## What is real and what is modelled

Every row carries two metric groups.

| group | where the numbers come from | changes with the config? |
|---|---|---|
| `real_*` | **Audit** of the real conversation: our real offers, the dealer's real offers, the real settlement, graded against our private value. | No. Same value in every variant: the reference line. |
| the rest | **Counterfactual replay**: the real bot code (`abuela.negotiate`, `chato.negotiate`, unchanged, imported) plays the case against a simulated dealer, with the variant's flags. | Yes. These are **modelled** numbers. |

Why a hybrid: dealers react to our offers, so replaying a fixed price path is only valid until our offer differs from
the one really sent. The simulated dealer therefore answers with the **real** dealer's numbers while our offers equal
the real ones (the trace marks each answer `[real]` or `[model]`; `meta.diverged_at` is the first offer that differed).
From there a **dealer model** answers. It is fitted on every other team's conversation in the public feed (1,032
conversations; ours are held out), conditioned on what this conversation revealed: its final offer is taken as its
secret limit `L`, the round it came in as its patience `P`. Where the thread never revealed them, `L` and `P` are drawn
from the class prior, kept consistent with what the thread showed (`L` no better than any price the dealer offered or
settled at; `P` later than every answer that was not a final). Reps differ only in these draws and in the model's
concession draws (common random numbers per case and offer number, so two variants see the same dealer).

Pure audit (a) alone cannot compare configs; a pure model replay (b) alone would replace real answers we have with
modelled ones. The hybrid keeps every real answer that is still valid and models only the rest.

## Cases

22 cases: every conversation Team 3 had with Abuela (10), El Chato (6) and Pilar (6), Friday and Saturday, rebuilt from
`logs/threads/` (complete transcripts, 18 of them) and the public feed (`logs/feed/` + `logs/feed-vm/`, which covers the
laptop recorder's Friday gap) for the 4 no bot saved. Tags: `tags[0]` dealer, then side, real outcome, day (`welcome`
on Abuela's fixed first-deal price). Prices, ticks, cards, limits and statuses only; no dealer or team words anywhere.

Excluded: threads 43 and 1590 (Abuela neighbourhood packs: no per-card private value, and neither bot trades packs).
Out of scope: our 4 Los Pícaros threads (L4, no bot drives it) and team-to-team threads.

**Private value** (the grading limit): buys = book x set multiplier (first copy; the bots only buy cards we do not
hold); sells = the copy's `your_value` in `logs/state/me.json`, else the Chato bot's logged floor minus its +2 margin.
`private_source` says which per case. This is the value the ladder gate uses (analysis-friday/score.md 4a: LAT-06 at 28
against 27.5 scored 0), not the API value the Friday Chato run planned with (it logged limits 30-31 for LAT-06/07).

## Metrics (headline first)

| id | kind | what it measures |
|---|---|---|
| `deal_in_limit` | binary, **headline** | A deal closed on the right side of our private value (buy at or under, sell at or over): a deal the ladder credits. |
| `over_value` | binary, **guardrail, lower is better** | A buy closed above book x set multiplier (first copy), computed by the grader itself from the catalog and the set multipliers, whatever limit the bot was handed. Friday's Chato bought LAT-06/07 above it from a bot limit set above our value (`--cap 30/31`); `real_over_value` catches those (chato-253, chato-275). In the replay it is 0 by construction while the harness hands the bot min(our value, cap): it guards the audit and any future harness mode that uses the bot's own limit rule. Sells: always 0. |
| `range_share` | float 0-1 | Share of the class's reference range captured: (ref_open - price) / (ref_open - ref_best) for a buy, mirrored for a sell, clipped to [0, 1]; 0 without an in-limit deal. ref_open = the class's usual opening; ref_best = 10th percentile (buy) / 90th (sell) of every team's negotiated deal prices in that class. Observable on real and modelled rows alike. |
| `limit_share` | float 0-1 | Modelled rows only. Share of THIS conversation's own range captured: (opening - price) / (opening - L), L its secret limit. The second hypothesis for the ladder formula (if the ladder pays for the share of the dealer's own hidden range, taking his final scores 1). Our Friday ladder increments were near constant per deal (0.020-0.022 at 17, 22, 23 P), which fits this reading better than the reference range. |
| `limit_breach` | binary, **guardrail, must be 0** | A deal on the wrong side of our private value: scores nothing on the ladder and loses value. |
| `missed_ok_offer` | binary, lower is better | No deal although the dealer offered a price inside our private value at some point (we walked, or ran out of rounds). |
| `real_*` | same five | The audit of the real conversation (no `real_limit_share`: a real thread reveals L only when it reached a final). |

Perf fields: `rounds` (our priced offers), `ticks` (open to end), `real_prefix` (dealer answers taken from the real
thread before the model took over).

Left out, with why:
- Surplus in P against our private value: dealer deals do not score at private value (ladder = share of the dealer's
  range); kept in `meta` (private, deal price) for anyone who wants it.
- A per-round cost: dealer value does not decay with rounds (unlike duels); time matters only through the round budget
  and hourly slots, which `rounds`/`ticks` show without scoring.
- Ladder points themselves: the formula is unknown and best-three-per-level is a portfolio effect across cases, not a
  per-case grade.
- Welcome-price and slot-unlock credit: the rules say an opening-price deal does not unlock; whether it scores is
  unmeasured. The one welcome case (abuela-49) is graded like any deal and tagged `welcome`.
- Cooloffs, spam and words: the model has no text and no memory across conversations.
- Took-final as a metric: in this model, taking his final is the best a policy can do (L = final); it is visible in
  `meta.deal_by`.

## The dealer model and how well it holds (`python3 tools/eval_dealers.py --validate --logs <dir>`)

Per class (dealer, side, rarity; Pilar split by her favourite sets SAL/RET): the dealer's move toward us when answering
our i-th offer after we moved s P (empirical, median or a draw, backing off to coarser cells under 5 samples);
`L` = final offers, `P` = our offer count at the final, `tol` = the gap at which a dealer still accepted our offer.
He accepts our offer when it is past `L` and within `tol` of his new price (or he is out of patience), names `L` as his
final at offer `P`, walks if we answer a final with another offer, ignores a repeated price, and his offers lapse
after 4 ticks.

One-step accuracy of the dealer's next counter (median drop vs "he holds his price"), run on the Mini logs at tick 1201:

| set | answers | MAE model | MAE hold | exact |
|---|---|---|---|---|
| other teams (in sample) | 2,819 | 0.22 P | 0.83 P | 79 % |
| ours, held out | 88 | 0.39 P | 0.77 P | 72 % |
| ours, chato.buy.rare (thread 335) | 7 | 1.71 P | 1.00 P | 29 % |

Harness fidelity (the bot with the flags it really ran, against the real dealer path only): 15 of 16 bot-run
conversations replayed exactly (same offers, same deal). The exception is chato-335: today's `chato.py` with that run's
flags (`--max-bid 84 --cap 93`) takes his 90 through the stall rule added in d8a5ded; the Saturday code closed at
max_rounds. pilar-870 counts as exact on outcome only: the real bot never spoke (clock pause), the replay opens at 28.

Closed-loop fidelity (same bots and flags, model only, with the conversation's revealed L/P): deal/no-deal agrees on
15/16, end price MAE 0.00 P over 14 deals. Partly circular (L and P come from the same thread); it checks the
mechanics, not the counterfactual.

## Baseline (the settings Sunday would run)

From `tools/factory_sunday.json` (dealer steps are off there); per section, as `BASELINE` in the runner:
`abuela` cap 22 (step 1, anchor 0.40 x her ask, 40 rounds: module defaults, the bot has no flags for them);
`chato.rare` anchor 60, step 4, cap 88, no max-bid, 40 rounds; `chato.uncommon` and `chato.sell` the bot's defaults
(Sunday runs neither); `pilar.sell` floor = ceil(private value) (Sunday's --floor 18 / 23), step 1, 40 rounds, first
ask by the bot's rule max(1.25 x her bid, floor + 9) (Sunday wrote 27 / 30; the rule gives 27 / 32). Cash never binds.

Baseline, 22 cases x 5 reps, case-level mean +- 95 % CI over cases:
`deal_in_limit` 0.736 +- 0.176, `range_share` 0.546 +- 0.155, `limit_share` 0.681 +- 0.174, `limit_breach` 0.000,
`over_value` 0.000; real audit: `real_deal_in_limit` 0.727 +- 0.190, `real_range_share` 0.525 +- 0.162,
`real_limit_breach` 0.091 and `real_over_value` 0.091 (the same 2 cases, chato-253 and chato-275). Re-graded in place
on Saturday 21:33 (read-only snapshot of the Mini's logs) when `over_value` was added: every earlier metric is identical
row for row.
Noise floor (A/A, even vs odd reps, paired over the 22 cases): `deal_in_limit` +-0.06, `range_share` +-0.05. Compare
configs with the paired per-case delta (the report's), not the overlapping unpaired intervals.

Harness checks (`--policy`, written outside evals/): ORACLE (takes L when inside our value) 0.845 deal_in_limit,
limit_share 0.845 (= its deal rate: every deal at L); NULL 0 deals; RECKLESS limit_breach 0.500.

## Config grid (Saturday night)

`grid.md` (27 configs: Abuela cap x Chato rare max-bid x step, paired with the baseline) and `recommended.md` (the
Sunday flags and why). Variants v1-v3 are the grid's top configs; all deltas are directional.

## Limitations

- The harness hands a buying bot min(our value, cap) as its limit; the real bots use min(API value, `--cap`), which
  can sit above our value (the Friday Chato buys). The replay cannot reproduce that overpay; `real_over_value` and the
  `over RET` projection in `grid.md` are where it shows. Fixing the bots' limit source is a separate, required PR.

- 22 cases, one Chato rare: a change to `chato.rare` is judged on a single conversation. The feed holds 101 other-team
  Chato rare conversations that could become modelled-only cases (v2 of the case set).
- L fixed per conversation and P counted in our offers, whatever we do: a different step or anchor cannot move the
  dealer's limit or his patience. The Friday analysis suggests 1 P crawls draw earlier finals; untested here.
- Saturday's Chato held his opening longer for us than the field (held-out error above). The model concedes faster than
  he did on rares: optimistic for `chato.rare`.
- Dealer versions changed during Saturday (Chato v2 tick 463, v3 583; Pilar v2 939; Abuela v2 979); the model pools
  them.
- Private values at the time of each conversation are reconstructed (pack contents are not in the feed); sells after
  the `me.json` snapshot use its values.
- The bots' accept guard, duel lock, clock pauses and refusals are not exercised (the sim never refuses or pauses);
  `tests/test_dealer_*` cover those.
