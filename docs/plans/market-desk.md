# W3 · Market desk (trades with other teams)

**Lever.** The value we gain in trades with other teams, at our private values, is one of the three parts of the 30 negotiating points. Each component is normalised to the mean of the top three teams; at Friday's normaliser one prima of surplus was worth about 0.155 score ([analysis-friday section 6](../analysis-friday/README.md#6-how-the-score-works-what-friday-taught-us)). Many small trades that each gain a little are worth chasing, as long as each one gains.

**Suggested owner.** Thiago (sell side, his `agent/rastro_seller.py`) + Hector/Claude (buy side and the numbers it reads).

## What we know (Friday, all public settlements)

| Rarity | Dealers paid when buying from teams | Teams paid each other | Dealers charged |
|---|---|---|---|
| Common | Abuela 5-6 (max 13) | 5-12, median 9 | Abuela 7-12 |
| Uncommon | Abuela 13-16, El Chato 13-15 | 12-35, median 26 | Abuela 17-29, El Chato 28-32 |
| Rare | El Chato 46 (one deal) | 53-80, median 70 | El Chato 82-93 |

- Dealers buy at about half the catalogue price, so buying from a team to sell to a dealer almost never pays.
- **Teams sell rares cheaper than El Chato.** A Lavapiés rare bought from a team at 70 scores at our value (112 - 70 - 5 fee = +37); bought from El Chato it only counts on the dealer ladder.
- `your_value` is the marginal value of a copy: our second LAV-08 is worth 10, the first 40 (multiplier 1.6, copy marginals 1 / 0.25 / 0.1). `GET /api/me/value?card=X` gives the value of one more copy. These are the numbers the scorer uses, so we never guess our own side.
- El Rastro charges 5 % + 1 P per card, paid by the side that accepts. Listings expire after at most 30 ticks.
- From [analysis-friday sections 1-2](../analysis-friday/README.md#1-el-rastro-at-0900-relist-the-spares-cheaper): `neg_points` is the raw surplus of team trades at our values (our MAL-08 sale at 28 scored +23.6, about +2.9 score); every repriced sale cleared below its first ask; the closing book held only one clear buy (SAL-05 at 9, +2). The game UI mentions per-trade and per-partner caps on trade surplus (size unknown), so spread trades across partners, and never buy a card we already hold (it arrives worth 25 %).

## Design

### Sell side: `agent/rastro_seller.py` (exists)

It already anchors high, steps down slowly, haggles in team threads, renews before expiry and keeps the lowest-serial copy. At 09:00 it relists the spares at the [analysis-friday prices](../analysis-friday/README.md#1-el-rastro-at-0900-relist-the-spares-cheaper) (LAV-08 spare from 26 to a floor of 22, MAL-06 28 to 20, LAV commons 7-9 to 6, MAL first copies above 17.5). After that, change only where its inputs come from:

- `tools/make_floors.py` writes `agent/rastro_floors.json` from our live account and the brain: every copy beyond the one a page needs, every card of a set we do not collect, with `floor` = our value of that copy + a margin and `start_ask` from the brain's price index for that card.
- Bids on our spares (`--take-bids`) are accepted when `bid - fee >= floor`, as today.

### Buy side: `agent/market_desk.py` (new)

On Friday the good buys were rare, so this starts as **watch and pounce**: the brain's market tape already marks underpriced listings in green, and the desk adds the exact gain and a one-line command for whoever is on duty. The same code runs in shadow all morning; it becomes a bot that accepts by itself only if Saturday's volume (El Retiro, the new packs, 30 s ticks) makes pouncing by hand too slow.

Each tick (or on each event from `/api/events/stream`):

1. Read every venue's public board (El Rastro and the team venues).
2. For each listing that gives one card for cash: `gain = value_of_one_more_copy(card) - price - fee(venue, price)`.
3. Buy when `gain >= max(3, 10 % of value)`, the price is under the dealer's price for that rarity when a dealer sells it this hour, and the caps allow it.
4. Post our own bids (`want: {"cards": [ref]}`) for the cards we want, priced from our value and the brain's price index, renewed and stepped like the seller's listings.
5. Every decision, taken or not, goes to `logs/market/<date>.jsonl` with its numbers, and to the brain page.

Caps (configurable): spend per game hour, total spend per day, maximum price per card (a Lavapiés rare gets its own cap once we know whether the page bonus counts), minimum cash after the trade (the venue bond until it is paid). The only copy of a card on a page we are completing is never sold by either side.

### Modes

`plan` (one pass, read-only), `watch` (shadow: every tick, decides and logs, sends nothing), `run` (live, through the key lease, accepts at the priority below duels and dealer final offers).

## Done when

- A morning of `watch` decisions that the team reads on the brain page and agrees with.
- Then `run` with caps (gate: a yes in the team chat).

## Risks

| Risk | What we do |
|---|---|
| Buying on a stale inventory (the copy we think we lack is already ours) | Re-read `/api/me` and `/api/me/value` before each accept; the relay keeps the brain current |
| A listing whose words and structure disagree | Only the structure counts; mismatches are logged and can be flagged |
| Fees on team venues change | Read the fee from `/api/venues` before each trade |
| Spending the bond money | Cash floor = the bond until the venue is open |
