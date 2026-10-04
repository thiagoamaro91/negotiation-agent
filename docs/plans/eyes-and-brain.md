# W5 · Eyes and brain

**Lever.** Every desk decides on this data, and it is the backbone of the judges' story. Most of it exists in [pull request #3](https://github.com/thiagoamaro91/negotiation-agent/pull/3) and runs on the VM today; this plan is what it still needs for Saturday's 30-second ticks and Sunday's 15-second ones.

**Suggested owner.** Hector + Claude; a former teammate on the analytics.

## What exists (PR #3, live on `fable-vm`)

- `tools/feed_recorder.py`: every public event since Friday 20:41 (3,766 at close), leaderboard snapshots, El Rastro board, levels, dealers and schedule changes. Keyless, under tmux with restart.
- `tools/value_inference.py`: each team's secret set multipliers by Bayes over the 720 permutations, from what they choose, what they shed and the prices they accept.
- `tools/ledger.py`: every team's cash from 400 P through every public movement; exact for us at ticks 72, 93 and 146.
- `tools/market_plan.py`: demand per team and card (value, cash, dealer ceiling, activity), sells, buys and holds with timing.
- `tools/brain.py` + `brain.html`: recomputes in ~2 s on every new event and pushes it to a live page (Tailscale Funnel, token in the link).

## What it needs

0. **Fixes from [analysis-friday section 10](../analysis-friday/README.md#10-héctors-brain-tick-159-data-read-0220-vs-this-analysis)**, which reviewed the brain against the measured data:
   - Dealer prices from measured closes, not 95 % of list: El Chato's rares closed at 82-93, the plan priced them at 73.
   - Score the plan the way the game scores: a page completed from dealers is worth the ladder share of each buy, not its collection value (the "+184 P" line was collection accounting).
   - `likely_buyers` must not show p = 1.0: the inference's own scorecard is a 0.416 hit rate against 0.396 for the naive guess.
   - Share the event store: the VM recorder has no gap (3,770 events, every tick 0-159, 191 settlements), while the laptop recorder lost ticks 49-118. This pull request adds it as `logs/feed-vm/`.
1. **Every venue's book, every tick.** All public books are readable without a key (checked Friday night). The recorder adds `GET /api/venues/{id}/offers` for each open venue to `snapshots.jsonl` when it changes. With the leaderboard's market column after each session, we can study who matches best and why.
2. **Our live account.** `tools/me_relay.py` on the key machine pushes `/api/me` every 20 s. Without it the brain decides on the last snapshot (tick 146 today); a stale inventory is the easiest way to sell what we no longer hold or warn about a card we hold twice.
3. **Calibrated confidence.** Replace the strong / some / weak label with the favourite's probability and the amount of evidence, checked against what each team did next (a reliability table: when we said 70 %, how often was it right?), and always show the naive baseline next to the hit rate. Today "strong" only means the favourite is above 60 %; t01 is "strong" on two data points. For our own team the model gets the least-liked set right (Malasaña) and the favourite wrong (La Latina instead of Lavapiés), because our purchases did not follow our values.
4. **Price index and demand as data for the desks.** Median and range of what each rarity and set traded at between teams, with dealers and per hour, served as JSON (`/data`) so the market desk and `make_floors.py` read the same numbers the page shows.
5. **Session analytics.** After each Market Test: our `bench_efficiency`, the stall replay and every team's market score. After each duel wave: the field's deal rate (public `duel.closed`) and our share per duel.
6. **Desk status on the page.** Heartbeat age, mode (shadow or live), last decision and its reason for each desk; the gates waiting for a yes.
7. **Speed.** The feed will grow several-fold by Sunday. Rebuild only what an event changes, and keep the full recompute as a nightly check.

## Done when

- The page shows our live account and every desk's status before 09:30.
- The reliability table is on the page, and the label requires a minimum of evidence.
- The market desk reads its prices from the brain's JSON.

## Risks

| Risk | What we do |
|---|---|
| The VM falls | Restart loops in tmux; the Mac Mini recorder (with retry and backfill, analysis-friday section 8) is the backup copy; both merge by event id |
| Text from other teams in the data | Treated as data everywhere; never pasted into an agent that holds the key |
| Private values leak | The relay strips any field containing "key"; the page is behind a token; our multipliers stay in the team |
