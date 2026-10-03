# W6 · Dealer ladder

**Lever.** Cheap points. The ladder scores the share of each dealer's price range we capture; only our best three deals per level count, a missing one counts as zero, and higher levels weigh more. Our `ladder_points` were 0.081 at tick 146: near nothing.

**Suggested owner.** Thiago (`agent/abuela.py`, `agent/chato.py`).

## What we know ([findings](../findings.md), [analysis-friday section 3](../analysis-friday/README.md#3-dealers-after-the-grant), [dealers.md](../analysis-friday/dealers.md))

- **Abuela (level 1):** our Friday slots are full (the 5th deal added nothing). Faster steps beat our 1 P crawl: t06 (11, 15, 17, 20, 21) and t13 (11, 13, 15, 19, 20, 21) closed uncommons at 21. Her first drop is a fixed 3-5 P, then she mirrors our step. Caps: common 10 (floor 8), uncommon 23, pack 21 (the field's lowest pack was 19). She buys commons at 5-6 and uncommons at 13-16.
- **El Chato (level 2):** rares never sold below 82 (82-93, he opens at 97); t04 got 82 opening at about 47 % of his ask with +2 steps; +4 steps pulled him from 97 to 82 in 7 messages; the 93 closes came from +1 steps. Two of our three Chato slots earned zero. His uncommons never closed under 28, so no Chato uncommons for us.
- The ladder covers buys **and** sells (share of the dealer's range), so a spare sold to Abuela at the top of her buy range may fill a slot.
- A dealer deal does not score at our private value. Buying a card worth 112 to us at 93 is a poor ladder deal even though it is "cheap" for us.
- New levels are announced in `/api/levels` before they open; teams that earned them get a head start.

## Plan

1. **Three good deals per dealer, every day.** If the ladder counts per round (to confirm with the organisers), Saturday and Sunday each need their own three. The cheapest items haggle as well as the dear ones: three commons from Abuela near 9 may be worth as much ladder as three packs.
2. **Measure the formula.** Run `tools/snapshot.py` after every dealer deal and log `ladder_points` next to the price and the dealer's opening ask. Two or three deals tell us how the share is computed.
3. **El Chato only when no team sells it cheaper.** The market desk ([W3](market-desk.md)) checks every board first; then El Chato with Thiago's ladder (60, 64, 68, 72, 76, 78, 80, 82, 84, never 1 P steps), aiming at 82-84, which captures nearly his whole range; his final offer up to 88 as the fallback. Read `ladder_points` before and after: it is also our test of how the ladder share works.
4. **Be first on every new level.** The recorder logs `/api/levels` changes; whoever is on duty reads the new level's `how` line and we meet its unlock condition early.

## Done when

- Three ladder deals with each dealer on Saturday, each logged with the score before and after.

## Risks

| Risk | What we do |
|---|---|
| A cooloff for tricks or repeated words | Every message carries a new price; no tricks with dealers |
| Two people talking to the same dealer | One process per dealer, through the key lease |
