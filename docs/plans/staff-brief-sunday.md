# Staff brief: Sunday 4 Oct 2026 (organisers' slides)

Source: "The Bazaar - Sunday.pdf", 11 slides from the organisers (host: Luis Morales, AI Engineer, Causa Prima), received 09:54 Madrid. Transcribed in full below; our takeaways first.

## What it means for us (Team 3)

1. **Cash held at 15:00 scores nothing.** Spend it on value-creating deals before the freeze. The 40 P reserve and the dealer cash floors only protect the next deal; they are not worth keeping at the end.
2. **The Grand Final (about 14:15) is market-making time.** Dealers close their stalls; every trade after that is between teams, and "this is the hour a good market matters most". Keep La Celestina (v20) open, the broker running, and the v20 pitch out before then.
3. **Market-making = value created between two other teams on our venue.** The organisers' own hint: "Find the trade El Rastro misses: the missing card, the last card of a page." Saturday: 89 trades on El Rastro vs 41 on all team markets together.
4. **A value-destroying trade on our venue no longer hurts us** (Team 12's bug fix: it is the seller's loss, never the market's).
5. **Don Ernesto's Gold pack (about 380 P) is not worth it:** pack pulls score nothing ("luck"). Only buy a card through a deal.
6. **"A card counts by the deal that brought it, never by sitting in your album. Never sell below your value."** Holding spares scores nothing by itself; a spare only scores when it is traded above its value to us.
7. **Duels: no deal scores zero.** Concede the delivery day you care little about for a better price (Duels III issues: price + delivery day).
8. **Ticks are 15 s** (Saturday 30 s): offers, dealer replies and duel clocks move twice as fast.
9. **Submission closes 16:00** (needs the team key: Thiago enters it, never a model). Judges are 40 points.

## Timeline (organisers' times, Madrid)

| Time | Event |
|---|---|
| 09:00-15:00 | Sunday play |
| 09:20 | Market opens, round 3 starts: one tick every 15 s (twice Saturday's pace). +150 primas. Don Ernesto opens to every team. Chamberí arrives |
| 10:00 | "Inside Luis's brain", a talk. Two Market Tests run at about 10:30 |
| about 11:15 | Duels III: price + delivery day, shorter clock, harder decay |
| 13:00 | Lunch; the market keeps running |
| about 14:15 | The Grand Final; warning on the big screen first |
| 15:00 | The market stops, scores freeze |
| 15:00-16:00 | Prepare the pitch and upload; /submit closes at 16:00 |
| 16:00-17:00 | Presentations in ranking order: top 3 teams 5 min, all others 3 min |
| 17:00-17:30 | Jury deliberations |
| 17:30 | Winners announced |
| 18:00 | Photo and networking |

Our live `/api/schedule` (game hours, read 09:50): hard Market Test 14.65, Market Test 15.0, Duels III 15.367, Market Test 17.0, Grand Final duels 18.367. The bots follow the live schedule, not this table.

## Slides, transcribed

**1. Sunday: one last round.** Final day, Madrid, Sun 4 Oct 2026, 15-second ticks, pitches 16:00. "Today counts in full: 40 % of the server score is still to play."

**2. Today at a glance.** The timeline above.

**3. Where we stand: Saturday in six numbers.** 78 % of Duels II ended in a deal. 14 epics changed hands after payday. 7 team markets rebuilt in two hours. 1 legendary found: La Chulapa Dorada. 89 : 41 trades on El Rastro vs all team markets ("room to grow"). 40 % of the server score is still to play.

**4. What changes today.**
- Chamberí arrives: a new neighbourhood joins the album; new cards, new pages to complete, new duplicates to trade.
- Don Ernesto, for everyone: his vault opens to every team. Gold pack from about 380 P, always an epic or a legendary.
- +150 primas: the Sunday allowance, on top of last night's 400. Cash you still hold at 15:00 scores nothing.
- Twice as fast: one tick every 15 s (Saturday 30 s). Offers, dealer replies and duel clocks move twice as fast: check your agent keeps up.

**5. About 14:15, the last hour: the Grand Final.** The dealers close their stalls. From then on, every trade is between teams. El Rastro and your own markets stay open. This is the hour a good market matters most. One last duel wave, live on the big screen. 15:00: the market stops, scores freeze. Keep your agent running until the end.

**6. Three things to remember: how to score today.**
- Collect by negotiating: a card counts by the deal that brought it, never by sitting in your album. Never sell below your value.
- Close your duels: no deal scores zero. Give up the delivery day you care little about for a better price.
- Make trades happen: a market scores when two other teams gain on it. Find the trade El Rastro misses: the missing card, the last card of a page.

**7. Bug bounty.** Thank you, Team 12 (Issam, Ivor and Ouadie) found a real scoring bug and wrote it up with ticks, settlement ids and numbers. Fixed overnight: a trade that destroys value is the seller's loss, never the market's. A bounty is on its way.

**8. Show us what you built: submit your project.** Link at the bottom of the game board ("Submit your project"). Pick your team, enter your team key (tk-...). Add your code, your Claude artifacts, how your agent works, and later your slides. Save early, edit until 16:00. The judges: 40 points, ideas and craft. They read your submission. Tell them what you built, why, and what you'd do with one more day.

**9. After the game: the afternoon.** 15:00 the market stops. 15-16 prepare your pitch and upload; /submit closes at 16:00. 16-17 presentations in ranking order (top 3 teams 5 min, all others 3 min). 17-17:30 jury deliberations. 17:30 winners announced. 18:00 photo and networking.

**10. What makes a good pitch (3 or 5 minutes).**
1. How did you approach the challenge? Your first idea, and what changed it.
2. What did you build? Your agent, your market, your tools. Show it, don't list it.
3. Why did you build it that way? The decision you'd defend in front of the judges.
4. What did you learn? Technically, and about negotiation and marketplaces.

**11. Doors open, round 3 starts now.** "Last day. Make it count. Happy hacking!" Big screen and server: bazaar.causaprima.ai
