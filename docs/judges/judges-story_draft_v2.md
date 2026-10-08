# Judges' story, draft v2

Owner: Thiago. Status: v2, Saturday 3 Oct 11:50 (v1 approved by Thiago in the pitch tab, PR #17). Internal: this file names numbers and sources for the team; the spoken script is the only part meant for judges.

## What changed in v2

- Privacy: no cap or cash-floor figures anywhere (steward's pass on PR #17).
- Hook: "six of today's top eight" became "more than half of today's top eight": the board moved to 5 of 8 at 11:46.
- New beat line: our own market, La Celestina, opened 10:23 (the market-making third of the score was missing from v1).
- Section 9: ready-to-use Duels I lines, to swap in once the results are in (after ~13:35).
- Evidence: two new screens (La Celestina panel now, live Duels panel from ~12:45).

## 1. What we know about judging

| Known | Source |
|---|---|
| Judges are 40 of the 100 points: "your ideas and your craft". Nothing else in the kit. | `kit/RULES.md` line 120 |
| The public leaderboard only shows the 60 game points. | vault `career/hackathon-madrid-2026/hackathon-madrid_bazaar-rules_v1.md` |
| The game freezes Sunday 15:00; the event runs until Sunday 18:00. Pitches probably fall in that gap, but no source says so. | `GET /api/schedule`; luma.com/claude-dyek |
| The event page says "more information will be provided soon about speakers, prizes and other details". No judges, rubric or format published. | luma.com/claude-dyek (read 3 Oct) |
| The Sunday Grand Final duels run "on the big screen". | `GET /api/schedule` |

Our working assumption until the desk answers: a short live talk (3 minutes) with a screen, then questions. Map every beat to the only two words we have: **Idea** or **Craft**.

### Unknown, ask the organisers (in person, today)

1. Format: live talk, demo, slides, repo review, or a mix? How long, and is there Q&A?
2. When: between the 15:00 freeze and 18:00 on Sunday, or earlier? Does every team present, or only a top N?
3. Who judges: organisers, Anthropic, sponsors?
4. Criteria behind "ideas and craft", and their weights. Does use of Claude count on its own?
5. Is there a submission (repo link, video, form) and a deadline?
6. Do judges see the 60 game points before they score?
7. If we present before 15:00 Sunday, can we show live screens of a game still running? (Changes what we can show; see the evidence checklist.)

## 2. The angle in one line

**Would you hand an AI your wallet in a market where lying is legal? We would, if the AI does the work and the code holds the wallet.**

Built on the game's own rule ("words persuade, structure binds", `kit/RULES.md` line 11) and on a fact judges may not expect: no model call sits on our money path. Claude researched, built, reviewed and tuned everything; in the market, code decides every number. Say that out loud before anyone asks "where is the AI?".

**Decision for Thiago before v1 is final:** this contradicts the team's written principle ("the model writes the words", in `CLAUDE.md`, `docs/plans/HANDOFF.md` and `docs/plans/judges.md`). The truth in the code is stronger: the bots speak in template lines that Claude wrote, and no model call runs in `agent/`. It is also a bet at a Claude hackathon: a judge could hear "they did not use AI in the agent". Tell Hector and a former teammate before the pitch either way.

## 3. The 3-minute script

Spoken pace about 150 words a minute. Total 444 words, about 2:58 spoken, which leaves a few seconds of air. Times are cumulative.

**0:00 to 0:25 · Hook (Idea)** · about 60 words

> [Line removed after the event.]

**0:25 to 0:45 · The problem (Idea)** · about 55 words

> The Bazaar has one rule: words persuade, structure binds. Anyone can say anything. Dealers bluff. Prompt injection is part of the game. So the real question this weekend was never "can an AI haggle?". It was: would you hand an AI your wallet, in a market where lying is legal?

**0:45 to 1:05 · Our answer (Idea)** · about 50 words

> Our answer: give the AI the work, not the wallet. Claude did the work of a small trading firm: the research, the code, the reviews, the overnight analysis. But out in the market, no model output can move a single prima. Code decides every number.

**1:05 to 2:05 · How it runs (Craft)** · about 150 words

> Separate bots, one job each: the dealers, the public market, the duels. Always on, day and night. And this morning we opened our own market, La Celestina: it finds your missing card.
>
> First, we see everything. We record every public event from minute one. Friday alone: 3,770 events, every tick, no gaps.
>
> Then code sets the price. With Abuela, our bot is lovely: she likes kindness. She opened at 29. We closed at 22.
>
> And code holds the line. El Chato wanted 90 for a rare we really wanted. Our ladder climbed in fixed steps and stopped at 84. He stayed at 90. No deal. Code doesn't get emotional about a card it wants. That's the hardest thing to teach a salesperson.
>
> Then we learn. In Friday's practice duels our bot only watched. Replaying them, in eight out of eight the other side had already offered a deal we should have taken. So overnight Hector built a duel lab. In simulation it captures 11 percent more per duel.

**2:05 to 2:40 · The team behind it (Craft)** · about 80 words

> We're three people: a former teammate, Hector and me, running a set of Claude sessions like a team. One conducts the trading, one reviews and merges every pull request, others crunch the data overnight. We plant bugs on purpose to test our tests: 107 out of 108 caught. And this morning our own market bot got merged with a default that was too aggressive. Our second review caught it, and the fix merged 18 minutes later. The scariest agent in a market is your own.

**2:40 to 3:00 · Close (Idea)** · about 40 words

> So, would we give an AI our wallet in a market where lying is legal? Yes. As long as the AI does the work and the code holds the wallet. Words persuade. Structure binds. We built for the structure.

## 4. The 60-second fallback

About 135 words. Use it if the slot is short or we lose the screen.

> Would you hand an AI your wallet in a market where lying is legal? That's this game: words persuade, structure binds, and prompt injection is part of the game. Our answer: give the AI the work, not the wallet. Claude did the work of a small trading firm: research, code, reviews, overnight analysis. But in the market, code decides every number. This morning El Chato wanted 90 for a rare we really wanted. Our ladder stopped at 84. He stayed at 90. No deal. Friday's practice duels showed we'd left about a third of the value on the table, so overnight we built a lab that captures 11 percent more, in simulation. Three people, a team of Claude sessions, 107 of 108 planted bugs caught. Words persuade. Structure binds. We built for the structure.

## 5. The three strongest anecdotes

1. **The walk-away (discipline).** El Chato, LAV-09, Saturday ticks 171 to 178. Our bids 60, 64, 68, 72, 76, 80, 84. His asks 97, 97, 97, 97, 96, 94, 90. We stopped at 84 and the run ended without a deal (`max_rounds`, both offers expired). Careful: his 90 was **not** marked as his final offer, and the bot takes a dealer's final offer up to a cap we set before the conversation starts, so this is not a walk-away. Say "our ladder stopped at 84, he stayed at 90, no deal"; never "his final was 90" or "the bot walked away". Source: `logs/chato/2026-10-03.jsonl`, `logs/threads/thread-00335.json`.
2. **Watching taught us to accept (learning).** Friday's practice round was watch-only, so we closed 0 of 12 by design. In all 8 duels where the rival named a price, its last offer was already inside our limit: on average 32 % of our limit left on the table. Hector's overnight lab tuned the bot: 0.394 per duel against 0.354 for the safe settings, +11 %, in simulation (300 held-out sessions). Not yet a live result: update after Duels I. Source: `docs/analysis-friday/README.md` line 9, `docs/duel-lab/improvements.md` lines 18 to 19, PR #10.
3. **Our own bot was the risk (honesty).** PR #11 (market desk swaps) merged 09:42 Madrid with swaps on by default. A second, post-merge safety review flagged it and PR #12 made swaps opt-in, merged 09:59. Eighteen minutes merge to merge; the live desk kept the old defaults until its restart, so say "the fix merged in 18 minutes", not "we fixed it in 18 minutes". Source: `gh pr view 11` and `gh pr view 12` (`mergedAt` 07:42:00Z and 07:59:57Z).

Runner-up, if a judge asks for a market story: our MAL-08 spare sold at 28 P on El Rastro in 3 ticks and gave Friday's biggest score jump (11.63 to 14.63), while another team's copy at 38 sat unsold for 21 ticks. Source: `docs/analysis-friday/rastro.md` lines 50 and 56, `docs/analysis-friday/score.md` line 12.

## 6. The five numbers we quote

| # | Number | What it says | Source | Refresh? |
|---|---|---|---|---|
| 1 | [Row removed after the event.] |   |   |   |
| 2 | **3,770 events, no gaps** | We see the whole game | `logs/feed-vm/README.md` line 5; `docs/findings.md` (Friday night section) | No (Friday figure) |
| 3 | **29 to 22**, and **84 vs 90** | Code sets the price and holds the line | `logs/threads/thread-00362.json` (Abuela LAT-08: asks 29, 26, 24, 24, 23, 22 final); `logs/chato/2026-10-03.jsonl`, `logs/threads/thread-00335.json` | No |
| 4 | **8 of 8**, then **+11 % in simulation** | We learn from what we see | `docs/analysis-friday/README.md` line 9; `docs/duel-lab/improvements.md` lines 18 to 19 | Yes, swap in the live Duels I result if it is good |
| 5 | **107 of 108** planted bugs caught; fix in **18 minutes** | Craft and control | `docs/plans/HANDOFF.md` lines 17 to 22 (#5 31/31, #8 5/5, #6 38/39, #7 18/18, #9 15/15); PR #11 and #12 `mergedAt` | No |

La Celestina: our venue v20, "La Celestina · finds your missing card", board mechanism (our own broker matches), 0 % fee, opened tick 269 (Sat 10:23). Source: commit 98f4b72, `GET /api/venues`. It had 0 trades at 11:46: do not claim volume.

Other numbers in the script: "0 of 12" duels (`docs/analysis-friday/README.md` line 9); "32 %", said as "about a third" (same line); "three people" (`CLAUDE.md`, first paragraph); 11 percent baseline is the safe file, not the defaults (+15 % against defaults, same `improvements.md` lines).

## 7. Back pocket for questions

- **"Where is the AI in your agent?"** No model call touches money. Claude wrote the code and the lines, ran the research, the reviews and the overnight analysis (four analyst sessions, one per Saturday decision: vault `career/context_hackathon-madrid-build-day-2.md` § Overnight analysis). The bots in the market are deterministic on purpose: nothing a rival types can change a number. Source: `agent/abuela.py` and `agent/chato.py` use template lines (`line()`, line 94 and 101); no API client in `agent/`.
- **"Did anyone try prompt injection on you?"** Not that we have seen: zero injection phrasing and zero text-vs-structure mismatches in our 13 threads. Say the design makes it pointless; do **not** claim we blocked attacks.
- **"How do you read other teams' values?"** Bayes over the 720 shuffles of set multipliers, from what each team buys, sells and accepts. Be honest: today its top pick is right 36 % of the time against 32 % for "repeat their favourite" (`python3 tools/value_inference.py check`). It is a working instrument, not a headline.
- **"How do you stop a runaway bot?"** Code caps that can only lower our limit (`agent/abuela.py` line 159, `agent/chato.py` line 179); the server enforces one accept per team per tick; the desk uses a local lease (`agent/lease.py`); the duel bot writes a separate local lock that the desk and dealer guards check (`agent/duel.py` line 136); a STOP file for the market desk. Do not say "global kill switch": the dealer bots ignore STOP.
- **"Would you have paid 90?"** Do not answer with a number. The bot only takes a dealer's final offer up to a cap we set before the conversation starts. What the code guarantees is that we never bid against ourselves and never climb past the ladder we set before the conversation.
- **"Which bug did your tests miss?"** The market desk ignoring the STOP file (PR #6, 38 of 39). It is not a global kill switch either; say so before they find it.
- **"Did the duel lab work live?"** Answer with the Duels I result once we have it; until then it is a simulation number.

## 8. Do not say, do not show

- Any private value: what a card is worth to us, our set multipliers, our caps or max bids beyond what the market already saw (84 is public in the feed; the cap behind it is not).
- Cash floor numbers (internal, and the docs and the live bots disagree: confusing on stage).
- "273 tests green" from a laptop that is behind `origin/main` (it shows 266 with 2 failures). Quote 107 of 108 instead.
- Our score or rank as an achievement: it moves every few minutes, and Saturday's 383 P cash was an organiser grant that never counts.
- [Line removed after the event.]
- "Other teams are allowed to inject us". The rules only say injection against dealers is allowed; say "prompt injection is part of the game".
- "The bot walked away" from El Chato (see anecdote 1).
- "His final offer was 90". It was not marked final.

## 9. Duels I swap-in (after ~13:35)

Duels I (price only, one round-robin) starts about 12:00 and finishes around 13:35. When the results are in, replace the last two sentences of the "Then we learn" paragraph with one of these. Fill the brackets only from `GET /api/me` or `logs/duels/`, and add the source to section 6 row 4.

- **If the live result is good:**
  > So overnight Hector built a duel lab. In simulation it promised 11 percent more per duel. In this afternoon's live duels we took [X] percent of the pie, against [Y] for the field.
- **If it is flat or worse:**
  > So overnight Hector built a duel lab. In simulation it captures 11 percent more per duel. The live duels said we still had work to do, and that is what tonight is for.

Either way, say "in simulation" next to the 11 percent.
