# Market desk eval: metrics (proposal, awaiting sign-off)

What is graded: `agent/market_desk.py` `decide`, replayed over the recorded public feed by `tools/market_replay.py`
and wrapped by `tools/eval_market.py`. The score it serves is the third part of the negotiating score: "the value you
gained in trades with other teams, at your private values" (kit/RULES.md, Scoring).

## Case unit

One case = one (day, card) opportunity window. A card is a case on a day when, at some tick of that day, the board
held an offer a team in our seat could structurally take (a one-card listing for cash, or a cash bid for one card;
not ours, not on our own venue, addressed to nobody or to us, not a thread offer), or when another team sold that
card alone for cash on a venue that day. The whole day is replayed once per variant (cash, the spend caps and the one
accept per tick couple the cards), and each case is graded from that replay. Days are independent: each starts from
`--cash` and an empty spend ledger.

Why not the alternatives: a whole-day replay as one case gives one number and no signal on where the desk gains or
loses; one case per tick gives thousands of near-identical rows; one case per offer splits a single decision (take
one of three asks for the same card) across rows.

`tags[0]` is the day; then `buy` (listings seen) and/or `sell` (bids seen), the set, the rarity, and `real-trade` /
`no-real-trade` (whether another team really sold that card that day).

Left out of the case list (counted over Friday and Saturday to tick 1200, by offer): offers addressed to another team
(1,426), card-for-card swaps (465; the desk's swap modes are off by default and Sunday's config does not turn them
on), our own offers (289), offers on our own venues (29: the server refuses them), and malformed or bundle offers
(11). Cards outside the catalog are dropped.

## Metrics (grade dict, headline first)

| id | kind | meaning |
|---|---|---|
| `surplus_P` | float, higher is better | **Headline.** Sum over the case's trades of: buy = value of one more copy − price − fee; sale = price − fee − value of the copy we give up; filled bid = value − price (the seller pays the fee). Our values and the fees are recomputed by the grader (book × set multiplier × copy marginal 1 / 0.25 / 0.1; fee = ceil(price × bps / 10000) + per-card fee of that venue at that tick), never read from the desk's own records. A filled bid whose evidence the grader cannot re-verify counts 0. |
| `bad_trade` | 0/1, must be 0 | Guardrail: any trade in the case with negative surplus (bought above our value after the fee, sold below our copy's value after the fee). |
| `missed_good` | 0/1 | The policy traded nothing on this card that day, while at some tick an offer for it was in the money by at least `--missed-min` (3 P) with room: for a buy, cash after it would stay at or above `--floor` (280 P); for a sale, we held two or more copies. The worst miss and the desk's own reason for skipping it are in the row's `meta.missed`. |
| `cash_floor_breach` | 0/1 | A buy or bid fill in this case left the simulated cash below `--floor` (team rule: 280 P). The grader's floor is fixed, so a variant that lowers `--min-cash` shows up here on purpose. |
| `plausible_fill` | 0/1, honesty flag | The case's surplus includes a filled bid. Fills are inferred by the replay's evidence rule (another team sold the card at or under what our bid nets the seller, or listed it at or under that), re-checked by the grader (a cash ask of at least 1 P, nothing else wanted, open to everyone: a listing addressed to a team or attached to a thread is not evidence). Evidence, not proof: nobody really accepted our bid. |
| `contested` | 0/1, honesty flag | A listing or bid we took was really taken by another team later. The replay assumes we were first; in the game we would have had to win that race. |

All 0/1 metrics are declared `"kind": "float"` with `"values": "0/1"` in `_state.json` so the lite report's primary
metric is `surplus_P` (it picks the first `binary` one); the runner's printed CIs still treat them as rates (Wilson).

Per-row `meta` also carries every trade with the grader's numbers, the best opportunity seen with room
(`best_opportunity`), the desk's own claimed gain and the grader-minus-desk difference (should be 0; a non-zero value
means the desk and the grader disagree on a fee or a value), and `rejected_fills`.

## Criteria considered and left out

- **Dealer trades and dealer prices.** They count on the dealer ladder, not in team-trade surplus; the desk does not
  trade with dealers.
- **Market-making points** (trades on our venue, the Market Test). Another eval (broker) covers them.
- **Number of trades or volume.** The rules say activity never scores; trades are only shown as a perf column.
- **Page bonus.** Unconfirmed whether trades score it, so the grader leaves it out and never counts selling a last
  copy as an opportunity (that is where the bonus would bite).
- **Hold-value / end-of-day mark-to-market.** A card bought counts its value at the moment it arrives, as the scorer
  does; whether we later sell it is a separate trade.
- **Fees we pay as a cost of their own.** Already inside surplus (net of fees); a separate fee metric would double
  count.
- **Per-trade or per-partner surplus caps.** The game UI hints at them, size unknown; not modelled.
- **An LLM judge.** Every quantity here is a number from structure; nothing needs a judgement call.
- **Partner spread** (trades per partner). The desk caps it itself (`--partner-hour`); the grader does not reward it
  until the scorer's per-partner cap is known.

## Harness checks (run with `--policy` and `--out-root`, never into evals/)

- `oracle`: each tick takes the best offer with gain > 0 at our values whose buy keeps cash at or above the floor
  (never a last copy), any venue but ours. Greedy and myopic, so a reference, not a bound: it can spend its 75 P of
  room on small gains and then miss a large one. It must show `bad_trade` 0, `cash_floor_breach` 0 and `missed_good`
  near 0.
- `null`: never trades. `surplus_P` must be 0 everywhere; `missed_good` marks every case with a real opportunity.
- `reckless`: accepts the first offer it can pay for, every tick, no value check. It must light `bad_trade` and
  `cash_floor_breach`.
- `tests/test_eval_market.py` checks the same on a synthetic day, and each grader piece was mutation-checked once
  (break it, see the test go red, restore).

## Noise and comparing configs

The replay is deterministic: reps only confirm it (`--reps 2` prints "every rep graded the same"). The noise is which
cases the market offered, so compare two configs with the paired per-case delta (`--compare baseline v1`), which
cancels every case the change did not touch. The runner also prints the unpaired threshold. Compare only runs over the
same frozen feed: the model label carries `feed<=t<last tick>`, and a variant directory refuses rows from another
label.

## Limitations of the replay

- Other teams do not react to us: a listing we take is gone for them, but nobody reprices, re-lists or answers our
  bids differently because we are there.
- Pack contents are not public: cards we pulled from packs count as held from the tick their id first appears.
  Holdings come from `logs/state/me.json` moved backwards and forwards by our public settlements; a gap between the
  snapshot and the replayed tick can misstate what we hold.
- Filled bids are plausible, not observed (see `plausible_fill`); taken listings can be races we would lose (see
  `contested`).
- Each day starts from `--cash` (default 355 P), not the team's real cash, and without the previous day's simulated
  trades. With the real cash on Saturday afternoon (169 P) and the default `--min-cash 280`, the desk could not buy or
  bid at all.
- Offer text never enters the replay; only structure. A listing whose words and structure disagree is graded on its
  structure, as the desk reads it.
- Wrapper fixes over the replay (no change to tools/market_replay.py): per-tick venue fees and owners from the feed
  (the replay passes El Rastro only, so team venues looked house-run and `--no-team-venues` had no effect), released
  sets from the feed (the replay hard-codes Friday's four, so no El Retiro bids), and game hours from the feed's clock
  (the replay's tick / 60 makes the hourly caps half as tight on Saturday's 30 s ticks).
- The replay's own fill evidence rule counts a listing that wants cash 0 (a card-for-card swap with cash on the give
  side) as an ask at 0; the grader rejects such fills. Worth fixing in tools/market_replay.py.
