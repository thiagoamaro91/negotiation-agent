# W1 · Venue and broker (the Market Test)

**Lever.** Market-making is 30 of the 100 points and every team is at 0. The free stall earns half of the Market Test points; the full points go to the mean of the top three. If the Market Test is most of the 30, a broker that beats the stall is worth up to ~15 points, the largest single lever left.

**Suggested owner.** Hector + Claude (code and simulator tonight), the key holder for the opening call.

## What we know

- From level 2 a team may open a venue: bond 250 P (refunded after closing and a cooldown) plus 20 P. Fees are capped at 10 % and 5 P per card; a fee change takes effect after a public notice. We cannot trade on our own venue with the team key.
- Each Market Test session counts the best venue we have open *during* it, and a round averages its sessions, so the venue has to stay open all weekend: the 250 P bond is parked until Sunday and only the 20 P are spent. Opening before the first test therefore risks 20 P, as long as a broker is ready.
- Friday's first Market Test (game hour 3.0) never ran, so nobody has market points and there is no demand data on team venues yet ([analysis-friday section 4](../analysis-friday/README.md#4-market-test-and-our-own-venue)).
- Sessions (schedule): Sat 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 21:00 (the hard test: firmer, more impatient traders), 22:00; Sun 10:00, 12:00. Each runs 16 ticks with 10 traders (12 in the hard one).
- `kit/starter_broker.py` is the stall's rule: in each bench run, the highest bid against the lowest ask while the bid covers it, at the midpoint. Its docstring: bench traders shade their quotes away from hidden limits; some are patient and some leave soon; most relax their quotes as their patience runs out, and the firm ones never do. The test counts the gains between the true limits, so a broker that estimates those limits, and who is about to leave, beats the stall.
- A match must respect the quotes: `ask <= price` and `price + fee <= bid` (`Broker.match` docstring). We cannot pair offers that do not cross. Our edge is **which** crossing pairs we match and **when**.
- Bench offers arrive in `GET /api/broker/book` as `bench_offers` with string ids (`"b12-7"`, run `b12`); a match pairs two offers of one run. A seller asks `want.cash`, a buyer bids `give.cash`.
- Every venue's public book is readable without a key (`GET /api/venues/{id}/offers`, checked Friday night). Team venues so far: t06, t12, t13 (`board`) and t02 (`auto`), with fees between 0 and 1 %; none had a trade by Friday's close.

## Design

### Opening (09:03, after the +150 P grant)

`tools/open_venue.py` with `plan` and `run` modes:

- `plan` prints the request: name (≤ 40 chars, e.g. `Team 3 · zero fee`), `fee_bps: 0`, `fee_per_card: 0`, `rules: {"mechanism": "board"}`, no rarity, set or level restriction (they only cut traffic), a one-line description.
- `run` sends `POST /api/venues` and writes the returned broker key to `~/.bazaar/broker.env` (mode 600) **without printing it**; it prints the venue id only. The key holder then copies that file to the VM (`~/bazaar/broker.env`, 600). The broker key never passes through a chat or a model.
- Fee 0 %: fees never score, and any fee shrinks the set of pairs that cross (`price + fee <= bid`).

### `agent/broker.py` (runs on the VM)

Modes: `plan --book FILE` (offline, prints the matches it would send for a recorded book), `selftest` (simulator), `run`.

Each loop (twice a second, planning once per book state, like the starter):

1. Read `GET /api/broker/book` and the clock. Append the book to `logs/broker/<date>.jsonl` (the session timeline is our training data).
2. Track every bench trader per run: first tick seen, quote path, side.
3. Estimate each trader's limit and remaining patience from its quote path: a relaxing quote moves towards the limit as patience runs out; a quote that never moves is firm. Priors come from the simulator and are refitted after every real session.
4. Among the pairs that cross **now**, choose the matching with the largest estimated true gain (estimated buyer limit minus estimated seller limit), not the largest quoted spread.
5. Timing: match at once any trader predicted to leave before the next tick; hold a crossing pair only when both traders are predicted to stay and a better partner is likely to cross soon.
6. Fallback: when a run has no history yet, or anything in the estimator throws, use the stall's rule for that tick. We never do worse than the stall because of a bug.
7. Teams' real offers on our venue: cross them card by card as `starter_broker.public_plan` does (lowest ask against highest bid for the same card, different makers, at the midpoint).
8. Price inside `[ask, bid - fee]`: the midpoint. The price moves gains between the two traders; it does not change the total the test scores.

Heartbeat file every loop; the brain page shows its age, and an alert goes out (Telegram, as Thiago's Mac Mini tunnel already does) if it stops during a session. `tools/run_brain.sh` gets a `broker` window with the same restart loop as the recorder. On a `board` venue nothing matches without our broker, so supervision is not optional.

### `tools/bench_sim.py` (the lab)

Synthetic runs: limits for buyers and sellers, shading per trader, arrival tick, patience, relaxing or firm type; a hard mix with more firm and less patient traders. Efficiency = realised gains between true limits / the best possible matching on true limits. It compares the stall's rule with our policy over many seeds and mixes, and reports the mean and the worst decile per mix.

After every real session: replay our recorded book through both policies, read our `bench_efficiency` from `/api/me` (through the relay) and the market column of every team on the leaderboard, and refit the priors.

## Done when

- Tonight: the simulator shows our policy clearly above the stall on the standard mix and never below it on the hard mix; unit tests prove we never send a price outside `[ask, bid - fee]`, never pair offers from different runs or the same maker, and survive refused matches.
- 09:10: `agent/broker.py run` reads our real book on the VM.
- After 10:00: our first `bench_efficiency` is recorded next to the stall's replay.

## Gate

Open the venue (270 P) only if the simulator says we beat the stall. If not, we keep the free stall and spend the cash on trades.

## Risks

| Risk | What we do |
|---|---|
| Broker down during a session: 0 for that session | Supervised restart on the VM, heartbeat alert, stall fallback inside the broker |
| The simulator's traders are not the real ones | Record every real session, replay, refit before the next one |
| The broker key leaks | Written to a 600 file by the opening script, never printed or pasted |
| 250 P parked all weekend | It is the price of the lever; the bond comes back after closing, only 20 P are spent |
