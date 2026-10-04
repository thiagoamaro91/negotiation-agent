# Judges' story v3 (Team 3)

Owner: Thiago (speaks). Drafted Sunday 4 Oct, 02:30 Madrid, lane WP6, from Thiago's v2 ([`judges-story_draft_v2.md`](judges-story_draft_v2.md)): the beat structure and the "do not say" list stay. Internal: this file names numbers, sources and team ids for the team; only the quoted script is meant for the judges. Companions: [`judges-evidence_v3.md`](judges-evidence_v3.md) (screens) and [`judges-rehearsal_v3.md`](judges-rehearsal_v3.md) (07:00 note).

## 0. The one fact at 14:50, and which version to read

```bash
python3 tools/pitch_numbers.py --live      # prints VERSION A or VERSION B, then the five numbers of section 5
```

- **Version A** ("the network worked"): at least one settlement on our venue v20 between two distinct teams, neither of them us, **and** the keyless `GET /api/leaderboard` row for v20 showing at least one trade. The tool reads `logs/feed/feed.jsonl` (the recorder's copy, merged with `logs/feed-vm/` for the stretches it missed; `--feed DIR` for another clone) and, with `--live`, the leaderboard. Put that settlement on screen.
- **Version B** (honest): anything else. No trade on v20, a trade we were part of, a Market Test bench pair: all B.
- Saturday close (tick 1445): **B**. 0 settlements on v20 between other teams; 2 other teams posted 29 offers there; leaderboard v20 row `trades 0, pairs 0`.
- If the feed and the leaderboard disagree, or the leaderboard cannot be read, the tool itself prints **B** (without `--live` it never prints A). A wrong A is a false adoption claim in front of the people who run the game's server.

The two versions differ in one paragraph only (marked **[NETWORK]** in section 3).

## 1. Who judges, and what they will hear through

Causa Prima, the organisers. Their product is an agent-to-agent network for B2B finance: buyer-side and supplier-side agents negotiate invoices, disputes, payment terms and early-payment discounts, and settle automatically. Their own lines: "Where buyer and supplier finally meet", "End the chase between companies", "Agents do the work. You get the money. In seconds." Founders from Taulia (SAP's early-payment business) and Finoa. They designed this game, so they know its rules better than we do; they will hear every claim against their own server's data.

What that means for the pitch:

- They built the game as a model of their network: a neutral venue, private valuations, settlement by structure. Speak to that thesis once (hook and close), in plain terms. Do not explain their business to them.
- They know the real numbers on every venue. Volume, adoption or rank we do not have would be checked in their heads within a second. Version B is a strong pitch; a stretched version A is not.
- Judges are 40 of 100 points, "your ideas and your craft" (`kit/RULES.md` line 120). Each beat below is tagged **Idea** or **Craft**.
- Pitch slot: about 15:00, after the 14:39 freeze (`docs/plans/sunday-night-handoff.md` on PR #66, line 57). Format still unconfirmed: v2 section 1's questions for the organisers stand.

## 2. The angle in one line

**Their network needs two things to work: agents you can trust with money, and a neutral place where agents meet. We built both inside the game, and we can show where each one held and where it did not.**

The spine is the game's own rule, "words persuade, structure binds" (`kit/RULES.md` line 11): no model output moves a prima, every decision is logged with its reason, and text from other teams is data, so prompt injection has nothing to grab. v2's "where is the AI?" answer stays: Claude did the work (research, code, reviews, overnight analysis); in the market, code decides every number.

## 3. The 3-minute script

Spoken pace about 150 words a minute. Version B is 445 words (about 2:58); version A is 447 words (about 2:59). Times are cumulative and follow version B. Thiago speaks; Hector drives the screens (cues in the evidence file).

**0:00 to 0:22 · Hook (Idea)**

> Every company has two teams chasing each other: one chasing payment, one chasing terms. You're building the network where their agents meet and settle. The Bazaar is that problem in miniature: hidden values, and lying is legal. We built both halves: agents we trust with money, and a place where other teams' agents meet.

**0:22 to 0:43 · The problem (Idea)**

> The game has one rule: words persuade, structure binds. Dealers bluff. Prompt injection is part of the game. Your network has the same shape: a note on an invoice can say anything; only the fields settle. So the question was never "can an AI haggle?". It was: what do you let it touch?

**0:43 to 1:07 · Our answer (Idea)**

> Our answer: the AI does the work, the structure holds the money. Claude did the research, the code, the reviews, the overnight analysis. In the market, no model output moves a prima: code checks every offer's structure against our own numbers, and logs why. El Chato wanted 90 for a rare we wanted. Our ladder stopped at 84. No deal.

**1:07 to 2:20 · How it runs (Craft)**

> First, we see everything: two public recorders, merged, twenty-eight thousand events by Saturday night. From those alone we rebuild every team's cash: on our own account, twelve readings out of twelve, to the prima.
>
> Then we read the other side: Bayes over the 720 ways each team's values can be shuffled. Honestly, it beats chance, but not "they'll do what they did last time". That gap is the real work of an agent negotiating terms.

**[NETWORK], version B (honest)**

> And we opened a venue of our own: La Celestina. Zero fee, a broker that crosses bids and asks every tick, and announcements telling the market which bids waited where. Two other teams posted offers there. No trade between them settled. A network is easy to open and hard to fill.

**[NETWORK], version A (the network worked)**

> And we opened a venue of our own: La Celestina. Zero fee, a broker that crosses bids and asks every tick, and announcements telling the market which bids waited where. Today one trade between two other teams settled there: [card] for [price] primas, and neither side was us. That settlement is on screen.

**How it runs, last paragraph (both versions)**

> Then we test before we trust. We bet that matching more pairs would beat the simple rule in the Market Test. We wrote the decision rule first, ran eight thousand sessions a scenario, and our idea lost: eleven standard errors on the hard test, and in simulations fitted to all five recorded sessions. We kept the simple rule.

**2:20 to 2:44 · The team behind it (Craft)**

> We're three people, Jay, Hector and me, running Claude sessions like a trading firm: a conductor, a pull-request steward, overnight analysts, one on duty today. Our rule: every new guard ships with a planted bug its test must catch. An audit found our broker's timeouts were sized for thirty-second ticks. Today's ticks are fifteen. Caught before the doors opened.

**2:44 to 2:58 · Close (Idea)**

> "Agents do the work. You get the money." This weekend taught us what goes in between: the agents do the work, and structure holds the money. Words persuade. Structure binds. We built for the structure.

### Version A, the bracket rules

- Fill the brackets only from `tools/pitch_numbers.py` (it prints tick, cards and price for each qualifying settlement). Never name the two teams.
- Two or more trades: "Today [N] trades between other teams settled there, the first one [card] for [price] primas, and neither side was us."
- Say "settled", not "we matched them": on a board venue the broker or either team can make the cross, and the feed does not always say which. Check the broker log (`logs/broker/<date>.jsonl`, a `matched` line at that tick) before saying "our broker matched it".
- No other volume words in version A either: no "liquidity", "growing", "adoption", "traction".

### Lines that may change at 14:50 (besides the version)

| Line | Keep it when | Otherwise |
|---|---|---|
| "two public recorders, merged, twenty-eight thousand events by Saturday night" | Always true (28,274 at tick 1445: our recorder's 26,615 plus 1,659 events from the VM recorder's copy of the Friday stretch ours lost, ticks 49 to 118; `tools/ledger.py` `GAP_SOURCES` merges the same copy). If number 3 of section 5 is over 30,000, say "over thirty thousand by now" instead | |
| "twelve readings out of twelve" | Number 4 shows every reading matching | Say "[k] readings out of [n]", or cut the sentence if any reading is off by more than the fee rounding |
| "it beats chance, but not 'they'll do what they did last time'" | `python3 tools/value_inference.py check`, section 3 line: "top pick right" above chance and below "repeat its favourite" (21.2 % vs 17 % chance, 22.8 % repeat, Saturday close) | If it now beats "repeat its favourite": "it beats chance and it beats 'they'll do what they did last time', by a little" |
| "Two other teams posted offers there" (B) | Number 2 says 2 teams | Say the count number 2 prints ("Three other teams ...") |
| "An audit found ... Caught before the doors opened" | Always true: the Saturday lunch audit found it (`docs/analysis-saturday/market.md` section 7, branch `docs/analysis-saturday`), PR #63 carries the fix | Do not upgrade it to "fixed" unless PR #63 is merged and the Mini pulled it before 09:00 |

## 4. The 60-second fallback

About 150 words. Use it if the slot is short or the screen is lost. One sentence changes between the versions.

> Every company has two teams chasing each other, one chasing payment, one chasing terms. You're building the network where their agents meet. The Bazaar is that problem in miniature: hidden values, and lying is legal. Its rule is ours: words persuade, structure binds. So Claude did the work, research, code, reviews, overnight analysis, but in the market no model output can move a prima: code checks every offer's structure against our own numbers and logs why. We rebuilt every team's cash from public events alone; on our own account it matched twelve readings out of twelve. We opened a zero-fee venue for other teams' agents. **[B]** Two teams posted there; no trade between them settled. **[A]** Today two other teams settled a trade there. And we killed our own best idea for the Market Test with eight thousand simulated sessions before it could cost us. Words persuade. Structure binds. We built for the structure.

## 5. The five numbers to refresh at 14:50

All five print from `python3 tools/pitch_numbers.py --live` (read-only, keyless; run it on the Mini, whose `logs/feed/` is the live recorder, or pass `--feed`).

| # | Number | Saturday close (tick 1445) | Source | Used where |
|---|---|---|---|---|
| 1 | Trades on v20 between two other teams (**the A/B fact**) | 0 | `logs/feed/feed.jsonl` settlements with `venue` v20 and two `tNN` parties other than t03; `GET /api/leaderboard` v20 row | Version choice; [NETWORK] |
| 2 | Other teams that posted on v20, and their offers | 2 teams, 29 offers | `logs/feed/feed.jsonl` `offer.listed` on v20, makers `tNN` other than t03 | [NETWORK] B |
| 3 | Public events recorded, two recorder copies merged | 28,274 (ticks 0 to 1445, deduplicated by id: 26,615 from our recorder, 1,659 more from the VM copy of Friday's lost ticks 49 to 118) | `logs/feed/feed.jsonl` + `logs/feed-vm/feed.jsonl` (`logs/feed-vm/README.md`) | "How it runs", first line |
| 4 | Ledger readings that match our real cash | 12 of 12, ticks 33 to 1445 | `python3 tools/ledger.py --json`, `check_history` (real cash from `logs/score.jsonl` and the Mini's `/api/me` readings) | "twelve readings out of twelve" |
| 5 | Pull requests merged | 56 (Sunday 02:30) | `gh pr list --repo thiagoamaro91/negotiation-agent --state merged` | Back pocket only ("how did three people build this?") |

Fixed numbers (no refresh): 720 permutations (`tools/value_inference.py` docstring: six multipliers shuffled); 8,000 sessions per scenario and 11 standard errors (`docs/plans/market-test-sunday.md` on PR #65: hard, 2,000 seeds x 4 sessions, z -11.3); five recorded sessions (b36, b53, b70, b88, b104, same memo, "refit" rows: simulations fitted to each recorded session, not replays; only b36 has a recorded-path replay, 0.800 against 0.980, and the memo says the four others would have produced exactly the same matches under either policy); 84 and 90 (`logs/threads/thread-00335.json`, El Chato LAV-09, Saturday ticks 171 to 178).

## 6. Back pocket for questions

Answer in two or three sentences, then stop. Each answer names its source so a judge who opens the repo finds the same thing.

- **"Where is the AI?"** Claude did the work of a small firm: the research, every line of code, the reviews, the overnight analysis, and the Sunday operations, as a team of sessions (a conductor, a pull-request steward, analysts, an analyst on duty today). In the market the bots are deterministic on purpose: they speak in template lines Claude wrote (`agent/abuela.py`, `agent/chato.py`, `line()`), and no model call sits on the money path, so nothing a counterparty types can change a number. That is the design we would want in your network too: the model drafts and explains, the structure settles.
- **"Did prompt injection hit you?"** Nothing we can show moved us, and by construction it could not: our bots never read other teams' words as instructions; they read the structured offer, and every number comes from code. Say "the design makes it pointless"; do **not** say "we blocked attacks" (we have no counted attempts to show). Our duel book even fingerprints rival bots by their message template (`docs/duel-lab/duel-book.md`): their words are data about them, never orders to us.
- **"How do you read other teams' values?"** Every team gets the same six multipliers, shuffled: 720 possibilities. Each public move is evidence: choosing a set, shedding one, a price paid is a floor on its value. Bayes does the rest (`tools/value_inference.py`). Honest result over the weekend: its top pick for a team's next choice is right 21 % of the time, against 17 % for chance and 23 % for "repeat their favourite" (`value_inference.py check`, 539 choices). Where it misled us: it reads page-completion buying as taste. That is the AP/AR lesson: behaviour reflects constraints, not only preferences.
- **"How do you know other teams' cash?"** Rebuilt from public events alone (`tools/ledger.py`): dealer settlements, team trades with who paid the fee, venue bonds, grants. Checked against our own account at every real reading we have: 12 of 12. Three traps we had to solve: package trades with cash, a fee the feed does not attribute, a 400 P payday that came only as an announcement (`docs/findings.md`, PR #61). That is reconciliation from a public event stream, which is most of what a finance agent does before it negotiates.
- **"How do you stop a runaway bot?"** Layers, each with its limits said plainly. Caps that can only lower our limit (`agent/abuela.py`, `agent/chato.py`). The accept slot: the server itself allows one accept per team per tick; the market desk takes a lease before it accepts (`agent/lease.py`); the duel bot writes a local lock file while a duel is live (`agent/duel.py` calls it a stopgap), and the dealer bots check it before every accept and defer (`agent/dealer_client.py`, `guarded_accept`). The lock is a file on one machine, so it only covers bots run from that checkout. The Sunday factory gates every **launch** on the game clock, the doors and the duel waves, and restarts bots under watch (`tools/factory.py`, `docs/plans/sunday-runbook.md`); stopping a running bot is one command (`tmux kill-window`). Do not say "global kill switch" or "one lease for every bot": neither exists.
- **"What did you get wrong?"** Three, all on record. Our own broker scored 0 in a Saturday Market Test because it refused every bench pair, all of which carry the same maker (`docs/findings.md`, fixed in PR #22). Our duel model priced delivery days wrong for sellers until three of the server's own results showed it (PR #54, patched live during Duels II). And the Market Test idea we liked best lost in simulation, so we did not ship it (PR #65).
- **"What would you build next?"** Close the gap the inference showed: an agent that reads a counterparty's constraints (cash, what it must complete, its deadlines) as well as its taste. In your terms: a buyer agent that knows a supplier's cash position from the events it can see, and offers an early-payment discount when, and only when, the supplier needs the cash. And La Celestina's lesson for a network: liquidity comes from telling each agent exactly what it is missing and where it is, not from a lower fee: 16 of the 19 open venues charge 0 % (`GET /api/venues`, Sunday 02:45).
- **"Did the duel lab work live?"** Duels II: 57 deals in 68 duels (`logs/duels/`, session 3). The arena is refit after each wave from the real duels (Friday practice, Duels I, Duels II, then III and the Final today). Sunday's duels have two issues, price and delivery day: the same shape as trading price against payment date. Fill the Duels III and Final count from `logs/duels/` at 14:50 if asked; never quote a share of the pie we have not computed.
- **"How did three people build this in a weekend?"** [Number 5] pull requests merged since Friday night, each with its tests in its description; tonight's carry a mutation matrix (PR #63: 6 of 6 planted bugs caught, PR #65: 8 of 8). Claude sessions wrote and reviewed them; people decided what merged.
- **"Why does your score look like that?"** Do not argue the score. "The leaderboard is the game's verdict on the trading. We came to show you how we built it." Never cite our rank as an achievement.

## 7. Do not say, do not show (v2's list, updated)

Kept from v2:

- Any private value: what a card is worth to us, our set multipliers, our caps or max bids beyond what the market already saw (84 is public in the feed; the cap behind it is not). This includes the inference's ranking of our own sets (`value_inference.py check` section 1, PR #61's wording): it names our order.
- Cash floor numbers.
- Our score or rank as an achievement.
- Team names, or any name from the threat map, or that the map came from LinkedIn profiles. Do not name teams at all, including the two that posted on v20 or the parties of a version A trade. "Two other teams" is the most we say.
- "Other teams are allowed to inject us". Say "prompt injection is part of the game".
- "The bot walked away" from El Chato. Say "our ladder stopped at 84, he stayed at 90, no deal".
- "His final offer was 90". It was not marked final.

New in v3:

- No "every public event" or "from one recorder": our own recorder lost Friday ticks 49 to 118; the count is two copies merged.
- **No volume, adoption or liquidity claim for v20 unless version A**, and in A only the settled trade(s) the tool printed. Not "teams use La Celestina", not "our network", not "traction". v20's leaderboard row is public: the judges can read `trades` and `pairs` themselves.
- No caps, max bids or `--cap`/`--max-bid` values from the factory lines or `evals/dealers/recommended.md`.
- No "273 tests" or any test count from a machine we have not checked. On the VM this branch runs 994 tests with `TZ=Europe/Madrid` and fails only the 5 known ones (2 encode the duel model PR #54 replaced); in UTC 4 more fail on time zone alone. Quote the rule instead ("every new guard ships with a planted bug its test must catch"), with PR #63's 6 of 6 and PR #65's 8 of 8 as the proof if asked.
- No "the inference knows every team's values". It is a hint that beats chance.
- No "max pairs lost everywhere", and no "lost on five real sessions". It lost beyond noise in 42 of 48 simulated scenarios and in simulations fitted to all five recorded sessions; on the one recorded-path replay (b36) it scored 0.800 against the stall's 0.980; on the other four recorded books it would have sent exactly the stall's matches; it won in 4 scenarios (one of them the adversarial mix). Say "lost on the hard test by eleven standard errors, and in simulations fitted to all five recorded sessions".
- No "we fixed the broker's pace" unless PR #63 is merged and the Mini pulled it before 09:00. "Caught before the doors opened" is the safe line.
- No claim that another team used, read or visited La Celestina's agent API (`/agents.md`, `/api/match`). Its access log counts **requests**, and the team in `/api/match?team=` is whatever the caller typed, so it proves nothing about who called. At most: "the API answered [N] requests" (`python3 tools/celestina.py visits --access-log FILE`), never "teams" or "visits".
- No "Causa Prima's network works like ours". Say what we built and let them draw the line.
- No hype words: "revolutionary", "game-changing", "fully autonomous", "AGI", "seamless".

## 8. What changed from v2, and why

- **Hook.** v2 opened on the threat map ("more than half of today's top eight"). It needs a re-score against a personal-data file at 14:50 and it does not speak to the judges' thesis. v3 opens on their problem (two teams chasing each other) and the game as its miniature. The threat map line can come back in Q&A if they ask how we prepared, under v2's rules.
- **New beat in "How it runs": the network.** La Celestina is one paragraph, in two versions, decided by section 0's fact.
- **The counterparty brain and the ledger** come in, each with its honest number (21 % vs 17 % vs 23 %; 12 of 12).
- **The killed darling** (PR #65) replaces v2's "+11 % in simulation" duel lab line: the simulation number was never confirmed live, and refusing our own idea with a pre-registered rule is the stronger craft story.
- **Abuela 29 to 22 is out of the script** (word budget); it stays in the rehearsal note as a back-pocket anecdote.
- **107 of 108** planted bugs is out of the script; it was Saturday morning's figure across five PRs. The rule ("every guard ships with a planted bug its test must catch") replaces it.
- **"18 minutes"** (PR #11 to #12) is replaced by the 15 s pace catch (PR #63), the same lesson ("the scariest agent in a market is your own") on a fresher, Sunday-specific bug. The PR #11/#12 story stays in the rehearsal note.
