# Findings

What we have worked out from the public feed and our own deals. These are inferences from data, not published rules: each section says when it was observed. Re-check after a round change. The feed tools (`tools/feed_recorder.py`, `tools/feed_report.py`, data in `logs/feed/`) come with pull request #1.

## Abuela Carmen (level 1 dealer) — Friday 2 Oct, ticks 0–65

- **Welcome price on each team's first deal, no haggling**: pack 17, uncommon 17, common 7; she pays 13 when we sell to her.
- After the first deal: packs open at 30 and close at 19–24; uncommons open at 29 and close at 21–25; commons open at 12 and close at 9–10. She buys commons at 5–6 and uncommons at 13–16.
- Her first reply drops 3–4 P, then she mirrors our step. She gives a final offer after 5–6 replies and accepts ours once it is within 1–2 P of her ask.
- Raising by 2 P per round reached 21–22. Raising by 1 P ran out her patience and ended at 22–24. `agent/abuela.py` uses `STEP = 1` today; `STEP = 2` is worth a try.
- Limits: 8 deals per team per hour, 3 packs per team per hour. She gives some teams free cards.
- Unlocking the next level early needs about 3 **negotiated** deals; deals at her opening price do not count.

## Leaderboard — Friday 2 Oct, ticks 0–65

- The score is **relative** to the other teams: on dealer deals alone the leader was capped at 12.5.
- Packs bought at 21–24 added nothing. Named cards and sales to Abuela did. Accepting her final offer on a pack (t12 at 24) added nothing either.
- **Team-to-team trades move the score most.** One sale of a common for 12 P (tick 40) took t10 from 8.3 to 29.1 and the seller t06 from 12.5 to 18.4. At tick 65 the top three (t13 27.9, t10 24.1, t14 20.6) were the teams that had traded with other teams; we were 13th with 8.33.
- The only rare sold between teams so far went for 65 P (LAT-09, t13 to t14, tick 47).
- The exact ladder formula is still unknown. Record our score after every deal of our own.

## El Rastro (shared market)

- Fee: 5% plus 1 P per card, paid by the side that accepts.
- Commons listed at 10–12 P mostly stayed unsold on Friday.
- Listings expire after 40 ticks by default.

## Where we stand — tick 65

- Our set multipliers and holdings are in `logs/state/me.json`. Lavapiés is our best set (×1.6), Chamberí our worst (×0.5).
- For the Lavapiés page we are missing the two rares, LAV-09 and LAV-10, which Abuela does not sell. On Friday LAV-09 was held by t07 and LAV-10 by t05 and t08. Each is worth 112 to us.
- Our trade currency is LAT-10 (worth 77 to us). Surplus to sell: the Malasaña cards and the spare copies of LAV-01 and LAV-03.
- Nothing in this repo handles team-to-team trades yet: an offer addressed to us waits until someone accepts it by hand.

## What the public feed shows

Every team's structured offers to the dealers (item and price), the dealers' replies with their words, every settlement, El Rastro listings, gifts and announcements. Team words are not published.

## API quirks not in the rules

- `/api/feed` has no paging: `after` and `since` are ignored. Ask for `limit=1000` and dedupe by `id`.
- `/api/cards/{id}` needs a key, unlike the other public reads.
- Keyless reads: 60 per second per address. Keyed calls: 5 per second, burst 20.
- Per tick: 1 accept per team (shared by every agent on the key), 1 message per conversation, 12 new offers. At most 6 open conversations and 30 open offers. Text is capped at 1200 characters.
- On Friday the clock started late (about 20:20 instead of 19:00) and still closed at 23:00.

## Friday night, after close (tick 159)

The full Friday analysis is in [analysis-friday](analysis-friday/README.md). Added here, not covered there:

- **The VM recorder has no gap:** 3,770 events with every tick 0-159 and 191 settlements, where the laptop recorder lost ticks 49-118. Committed as `logs/feed-vm/` (feed, leaderboard and board snapshots, changes).
- **Every venue's book is public:** `GET /api/venues/{id}/offers` answers without a key, so we can record how every team's market behaves.
- **The kit says how to beat the free stall** (`kit/starter_broker.py`): the stall matches by quoted price; bench traders quote away from limits they keep hidden, some leave soon, most relax their quotes as their patience runs out, the firm ones never do; the Market Test counts the gains between the true limits. A broker match must still respect the quotes (`ask <= price`, `price + fee <= bid`).
- **Team venue fees move:** t13 went 1 % to 0 % (tick 136) and back to 1 % (tick 147); t06 0.5 % to 0 % (tick 156); t02 announced 0 % for tick 161.
- **The SDK repeats refused writes:** with `wait_on_tick=True` (the default) a write refused with `wait_for_tick` is sent again on the next tick. For `POST /api/duels/{id}/accept` that accepts whatever the rival's standing offer is by then. `duel.py` and `rastro_seller.py` pass `wait_on_tick=False`; `abuela.py` and `chato.py` use the default.
- **Game hours look like wall hours:** the schedule pins Saturday 4.0 to 09:00 and 18.0 to 23:00, Sunday 18.0 to 09:00 and 24.0 to 15:00. Fourteen game hours in fourteen wall hours at 30 s ticks (and six in six at 15 s) only fit if a game hour is a wall hour whatever the tick length. To confirm with `t_hours` at 09:00.

## Saturday, Duels I and midday (ticks ~440-630)

- **Selling to a dealer fills a ladder slot,** the same as buying from one (Chato sells at 14, Saturday morning).
- **Ladder value gate:** a dealer deal on the wrong side of our private value earns no ladder credit, however much of the dealer's range it captures (Friday data, [analysis-friday/score.md](analysis-friday/score.md) section 4a: LAT-06 at 28 against a value of 27.5 scored +0). Every dealer sell floor must sit above our value.
- **Market Test bench offers all carry maker `"bench"`** (tick ~442). A broker that drops same-maker pairs drops every bench pair: the 11:50 test scored efficiency 0.449 against the stall's ~0.9 for that reason (fixed in PR #22).
- **Duels need no cash:** Duels I ran with 95 P in hand, and bids are not escrowed.
- **Duels I (t03, to tick 630):** 31 finished, 25 deals, duel_points 16.24. All 21 of our accepts came with 1-3 ticks left; 5 of the 6 no-deals were rivals who never spoke, while our last offer stayed short of our limit. Summary on the bus (#5968797627).
- **The clock can pause mid-duel** (`/api/clock` `paused: true` at tick 630, ~13:25). `results/duel.lock` is refreshed per tick, so it goes stale during a pause while duels are still live. A dealer bot gated only on the lock would start inside the duel window: gate on `paused` and on unfinished duels too.

## Saturday evening: every team's cash (ticks 630-1243)

What `tools/ledger.py` needed to rebuild all 18 teams' cash from the public feed (PRs #42, #52, #53, #55):

- **The payday came only in words.** At tick 1201 the organisers' `announcement` said "Payday in Madrid: every team gets 400 primas", with no `schedule.fired` grant. Without it, five teams appear to buy epics and rares they could not afford (t05 paid Picaros 128 P for RET-11 at tick 1209). The ledger now reads it. Watch for the Sunday allowance arriving the same way.
- **Who paid the fee.** The feed has no "offer filled" event: a filled offer just leaves the board without an `offer.cancelled`. An offer accepted on its last tick settles on the next tick. With an ask and a bid both standing, the settled price says which one was taken (t16 sold LAT-09 into our 88 P bid at tick 724 while its own ask stood at 135, so the 6 P fee was t16's).
- **Card-for-card swaps on El Rastro carry a fee** (2 P each, 8 swaps by tick 1201), paid by the side that took the listing.
- **Counters to check against:** El Rastro's `/api/venues` totals restart each round. From tick 160 they equal the feed exactly (208 P of fees, 71 trades, 1,843 P of volume at tick 1060). Team venues had charged no fee by then.
- **How exact it is:** of 153 team settlements to tick 1201, only two fees stay unknown (tick 78, 3 P between t04 and t15; tick 939, 2 P between t14 and t16). The page shows them as ± on those teams' cash. Team 3's rebuilt cash matches every real `/api/me` reading up to tick 1186. The Mini's live score reader (`score.state.json`) stopped at tick 1186 (20:07).
- **The value inference misreads page-completion buying as taste.** On our own account (tick 961) it ranks La Latina first (1.44) and Lavapiés third (1.17), against a true 1.6 for Lavapiés, because we were buying the last cards of pages. Read other teams' labels with that in mind.

## Open questions for the organisers

- The judges' criteria (40 of the 100 points).
- Whether Friday's late start shifts the schedule.
- When level 2 opens (`/api/levels` was still empty at tick 65).
- Whether dealers' true limits are revealed after the Market Test.
- Whether the one-accept-per-tick limit also covers duel accepts.
- How the 30 negotiating points split between duels, the dealer ladder and team trades.
