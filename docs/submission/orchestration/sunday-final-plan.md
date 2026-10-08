# Bazaar final day: the plan to win (written Sun 4 Oct, 11:50)

## Status at 12:00

- **Conductor is running.** One Opus session on the Mini, tab `bazaar-final-conductor`, started 11:55, transcript growing at 11:58. Handoff: `~/.claude/handoffs/2026-10-04_bazaar-final-conductor.md`, also on the team bus (message 5978770498) so Hector's Claude can take over.
- **Artifact page is built, not yet published.** The publish is refused while plan mode is on. Approving this prompt turns plan mode off; the only step left is publishing the page and handing you the link for Hector.
- **Hector's session has not answered** the two bus messages yet.

## Context

Board at 11:14: **us 30.47 (rank 5)**. Rank 1 is +4.4 away, rank 3 is +1.9.
Cash 355 P scores nothing at 15:00. The shop bond holds another 250 P.

| Wall time (live schedule, re-read after any pause) | Event |
|---|---|
| ~11:50 | Duels III ends; dealer bots can run |
| ~12:37 to 12:41 | Last Market Test (shop open, broker untouched, no other bot runs 12:30 to 12:45) |
| ~14:00 | All dealers close, Grand Final duels, team-only trading |
| ~14:59 | Scores freeze |
| 16:00 | /submit closes (judges = 40 of 100 points) |

## Who runs it (token plan)

- **Fable stops after this plan.** It is not needed to conduct: the hard part was working out the scoring, and that is done.
- **Conductor: ONE Opus session on the Mini** (kickoff skill), no parallel lanes, haiku only for log extraction. Yesterday's burn was 3 to 4 parallel Opus lanes.
- **Scripts first:** in its first 20 minutes the conductor queues the dealer runs, the desk restart and the 14:00 cash-floor flip on the Mini. The bots use no model, so the plan keeps running if tokens run out.
- **Fallback:** the handoff goes into the repo (`docs/plans/sunday-final-handoff.md`) and on the team bus, so Hector's Claude can take over mid-flight.
- **No human gates.** Approving this plan authorises every in-game move inside the value rules (buys, sells, desk restart, packs, shop). This replaces "nothing of ours spends until Hector says so". The conductor reports by Telegram at checkpoints. Only things outside the game stay with Thiago and Hector: messages to people, keys, new public services.
- **Fable's remaining budget goes to the pitch at 15:00** (40 points), if any is left.

## What the data says

1. **Team trades are the lever.** Our private value minus price, page bonus INCLUDED, capped at 50 per trade. Today's SAL-10 and MAL-07 buys sum to exactly 56.5 = 50 + 6.5. One capped trade moved us about +1.0.
2. **The fourth page is worth it one way:** dealer buys under value for six cards, the LAST card from a team (+50).
3. **Bot deals:** best three per dealer per day; a better one replaces the worst. About 0.15 to 0.5 each. Never offsets a bad team trade.
4. **Banco: no.** Four deals in the whole game: -5.54, -2.45, -0.11, +0.14. Nobody is ahead of us there.
5. **Duplicates:** sell above the spare's value (25% of book x multiplier). Holding scores zero.
6. **The shop:** we cannot trade in our own shop. It scores when two OTHER teams trade there. Team 9 leads the market column (13.29): Team 6 and Team 5 park their bids in other teams' zero-fee shops, and one legendary at 380 crossed there.

## Buy list (where our points are)

| Card | Worth to us | Source | Price | Gain |
|---|---|---|---|---|
| RET-02 | 9 | Abuela | 8 or less | Abuela slot |
| RET-06, 07, 08 | 22.5 | Abuela 22 or less; Team 2 listed RET-07 at 14 | under 22.5 | Abuela slot, small team gain |
| RET-09, RET-10 | 63 | Picaros | 61 or less, `--step 1` | Picaros slot 3 + upgrade |
| **RET-01, the closer** | about 68 as last card | **Team 2** relists it at 8 on El Rastro (holds 2) | 8 plus fee | **+50** |
| SAL-11 epic | 234 | **Team 4** asked 220; Teams 2, 13, 17, 8 hold one | 184 or less for +50; 220 is +14 | up to +50 |
| LAT-11 epic | 198 | Picaros about 145 (4 left) | 150 or less | Picaros slot only, low priority |

**Closer rule:** RET-01 is excluded from EVERY buyer (desk, Abuela `--only`, clearing book) until `me.json` shows El Retiro at 9 of 10 and the live value of RET-01 reads about 68. Then one targeted bid: `agent/market_desk.py --page RET-01:16`. If another RET card ends up last, that card is the closer and must come from a team. RET page total about 220 P.

## Sell list (thin: team prices for commons and uncommons are 8 to 20 P)

| Our card | Floor | Best outlet | Gain |
|---|---|---|---|
| spare LAV-10 rare | 28 | Pilar 50 to 56 (12 teams already hold it, no team needs it) | Pilar slot 3 |
| spare LAT-07 | 6.9 | Chato about 14 (Team 5 bids only 9) | first Chato slot |
| MAL-06, MAL-04 | 17.5, 7 | **Team 6** has live bids for both: ask 28 and 12 on El Rastro | +10, +5 |
| MAL-07 | 17.5 | **Team 6** at 28; **Team 5** needs it for its Malasana page but sits right above us: only at 68 (our full +50) | +10 or +50 |
| spare LAV-03, LAV-05 | 4 | Abuela 6, Picaros 5 | slots |

- **Rivals rule:** Teams 12, 10, 18 and 5 get a trade only when our side scores the full +50.
- **Last hour (14:00 to 14:59):** every team is dumping cash. All spares and Malasana singles go on El Rastro at our value plus 50. It costs nothing and each hit is +50.

## Shop: Hector's Clearing House puts other teams' trades on La Celestina [Hector leads]

**Status 11:50:** asked Hector's session on the team bus (messages 5978615063 and 5978659628): no answer yet. Pull request #96 is open, no clearing server runs on the Mini, the first run was planned for 12:10. The conductor's first action is a bus read; it adopts Hector's run times and answers.

Hector's idea: teams privately hand in what they sell (minimum) and want (maximum); a matcher pairs every profitable cross at the midpoint on a shop owned by neither side. What our plan gives it:
- **Our book** (the two lists above), without RET-01.
- **The pairs we already know between other teams:** Team 6 bids for LAT-11, MAL-11, LAT-09, MAL-06, MAL-07, LAT-03, MAL-04; Team 5 for LAT-06, LAT-07, LAT-08. Holders: LAT-11 Team 16 (asks 248), Teams 4, 14, 7; MAL-11 Team 12; LAT-09 Team 1; spares of MAL-07, MAL-04, LAT-03 Team 1; spare LAT-06 Team 16; LAT-08 Teams 9, 17. **Biggest pair: Team 6 x Team 16 on LAT-11.** Holders are said in person only, never posted.
- **One matcher rule:** every cross where neither side is our team goes on v20, biggest first.

Recruiting pitch for Thiago and Hector in the room: zero fee against El Rastro's 5% + 1 P, both sides keep half the gain, and cash is worthless at 15:00.

**Shop stays open by default.** The rules say a closed shop "keeps nothing" for a session it misses. The conductor closes v20 only if all three hold at 13:30: the schedule shows no market session left, v20 still has zero trades in `me.json` and the feed, and Hector's session reports no team committed. Then: proper close, never "replace"; 250 P returns 5 minutes later (20 ticks, measured) and goes to the buy list.

## Cash order for the end

1. Team trades with gain (the lists above). From 14:00 the desk runs with `--min-cash 0` and takes any team ask under our live value, best gain first.
2. Dealer buys under value that improve a top-three slot (LAT-11 at Picaros).
3. **Packs, last resort:** only at or under the pack's live value to us (`/api/me/value`), before 14:00, Chato's silver first (also a Chato slot); pulls go on El Rastro for the last hour. A pack ABOVE value is a wrong-side dealer deal; those cost teams 0.1 to 5.5 points this weekend, so idle cash beats it.

## Other lines
- Desk restart after Duels III: drop `--no-bids`, `--cap-hour 250 --cap-day 600 --min-cash 40`, RET-01 protected (check what `--protect` covers first). Never restart broker or duel bot.
- Duel lock: `results/duel.lock` was absent at 11:45 while a late duel settled. The conductor checks the lock path once; desk accepts pause from 14:00 until the Final wave ends.
- Flag test after the Picaros buys: one clear bad-faith line, read `neg_points` before and after, repeat only if it moves.
- Judges [Thiago]: first /submit save by 13:00. Include the reverse-engineered scoring with the evidence table.

## Verification
- Before and after every deal: `neg_points`, `ladder_points`, `negotiating` (Mini `logs/state/me.json`, `logs/score.jsonl`). A line whose deal lowers the score stops.
- Duels at 12:00 and 13:30: deals, no-deals, surplus from `logs/duel/2026-10-04.jsonl`.
- Telegram to Thiago at 12:45, 13:30, 14:05, 14:30, 14:55: score, rank, cash, three lines.

## Honest ceiling
Ladder +1 to +1.5, RET closer about +1, SAL-11 up to +1, sells +0.3 to +1. That is top three. First place needs other teams' trades on v20 (Hector's lane) or a strong Final duel wave. Unverified: whether the 50 cap is per trade or per team per day; how the shop column weighs big against many trades.
