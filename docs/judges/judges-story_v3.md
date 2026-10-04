# Judges' story v3 (Team 3)

Owner: Thiago (speaks). Drafted Sunday 4 Oct, 02:30 Madrid, lane WP6, from Thiago's v2 ([`judges-story_draft_v2.md`](judges-story_draft_v2.md)): the beat structure and the "do not say" list stay. Internal: this file names numbers, sources and team ids for the team; only the quoted script is meant for the judges. Companions: [`judges-evidence_v3.md`](judges-evidence_v3.md) (screens) and [`judges-rehearsal_v3.md`](judges-rehearsal_v3.md) (07:00 note).

## 0. The one fact at 14:50, and which version to read

```bash
python3 tools/pitch_numbers.py --live      # prints VERSION A, B-UNCONFIRMED or B, then the five numbers of section 5
```

- **Version A** ("the network worked"): at least one settlement on our venue v20 between two distinct teams, neither of them us, **and** the keyless `GET /api/leaderboard` row for v20 showing at least one trade. The tool reads `logs/feed/feed.jsonl` (the recorder's copy, merged with `logs/feed-vm/` for the stretches it missed; `--feed DIR` for another clone) and, with `--live`, the leaderboard. Put that settlement on screen.
- **Version B-UNCONFIRMED**: the feed and the leaderboard do not agree (the feed shows such a settlement and the leaderboard says 0 or did not answer, or the leaderboard counts a trade the feed does not show). Read version B with its **unconfirmed** outcome sentence (section 3). Never say that no trade settled.
- **Version B** (honest): no such settlement in the feed and no leaderboard count against it. A trade we were part of, a Market Test bench pair or a dealer never counts.
- Saturday close (tick 1445): **B**. 0 settlements on v20 between other teams; 2 other teams posted 29 offers there; leaderboard v20 row `trades 0, pairs 0`.
- The tool decides between the three itself (without `--live` it never prints A). A wrong A is a false adoption claim in front of the people who run the game's server; a wrong "no trade settled" is a false claim too, which is why the third state exists.

The two versions differ in one paragraph only (marked **[NETWORK]** in section 3).

## 1. Who judges, and what they will hear through

Causa Prima, the organisers. Their product is an agent-to-agent network for B2B finance: buyer-side and supplier-side agents negotiate invoices, disputes, payment terms and early-payment discounts, and settle automatically. Their own lines: "Where buyer and supplier finally meet", "End the chase between companies", "Agents do the work. You get the money. In seconds." Founders from Taulia (SAP's early-payment business) and Finoa. They designed this game, so they know its rules better than we do; they will hear every claim against their own server's data.

What that means for the pitch:

- They built the game as a model of their network: a neutral venue, private valuations, settlement by structure. Speak to that thesis once (hook and close), in plain terms. Do not explain their business to them.
- They know the real numbers on every venue. Volume, adoption or rank we do not have would be checked in their heads within a second. Version B is a strong pitch; a stretched version A is not.
- Judges are 40 of 100 points, "your ideas and your craft" (`kit/RULES.md` line 120). Each beat below is tagged **Idea** or **Craft**.
- Archived early-Sunday rehearsal plan; its predicted freeze time and shutdown checklist were superseded. Use the final submission timeline for actual events.

## 2. The angle in one line

**Their network needs two things to work: agents you can trust with money, and a neutral place where agents meet. We built both inside the game, and we can show where each one held and where it did not.**

The spine is the game's own rule, "words persuade, structure binds" (`kit/RULES.md` line 11): no model output moves a prima, every decision is logged with its reason, and text from other teams is data, so prompt injection has nothing to grab. v2's "where is the AI?" answer stays: Claude did the work (research, code, reviews, overnight analysis); in the market, code decides every number.

## 3. The script (under 4 minutes)

Spoken pace about 150 words a minute. Limit: 4:00. With every bracket in, the longest 07:00 result wording and the optional demo: version B 572 words (about 3:49), B-UNCONFIRMED 586 (3:54), A 574 (3:50), plus up to 5 seconds while the demo runs. With no bracket, no lab sentence and no demo, B is 469 words (3:08). Times are cumulative and follow version B with every bracket in. Thiago speaks; Hector drives the screens (cues in the evidence file).

**Bracket markers.** `[if merged #NN: ...]` is said only if that pull request is on `main` by 08:00 **and** what it adds ran on Sunday (Hector confirms at 14:50 from the factory status screenshot or the PR); otherwise drop the bracket and read on. `[if served: ...]` is said only if La Celestina's public page and API are served on Sunday behind a tunnel Thiago said yes to (evidence file). `[07:00: ...]` is filled by Thiago at 07:00 from the file named in section 3a; `[optional demo]` follows section 3b.

**0:00 · Hook (Idea)**

> Every company has two teams chasing each other: one chasing payment, one chasing terms. You're building the network where their agents meet and settle. The Bazaar is that problem in miniature: hidden values, and lying is legal. We built both halves: agents we trust with money, and a place where other teams' agents meet.

**0:22 · The problem (Idea)**

> The game has one rule: words persuade, structure binds. Dealers bluff; prompt injection is part of the game. Your network has the same shape: a note on an invoice can say anything; only the fields settle. So: what do you let an AI touch?

**0:39 · Our answer (Idea)**

> Our answer: the AI does the work, the structure holds the money. Claude did the research, the code, the reviews, the overnight analysis. In the market, no model output moves a prima: code checks every offer's structure against our own numbers, and logs why. El Chato wanted 90 for a rare we wanted. Our ladder stopped at 84. No deal.

**1:03 · How it runs (Craft)**

> We see everything: two public recorders, merged, twenty-eight thousand events by Saturday night. From those alone we rebuild every team's cash: on our own account, twelve readings out of twelve, to the prima. And we read the other side: Bayes over the 720 ways each team's values can be shuffled. Honestly, it beats chance, but not "they'll do what they did last time".

**1:28 · The network (both versions)**

> And we opened a venue of our own, La Celestina: zero fee, a broker that crosses bids and asks every tick[if served: , and a keyless API giving any team's agent a fair price and the exact order to post]. [if merged #67: Today it also tells teams which card they appear to be missing, and who holds it.] A neutral party, helping both sides meet.

**1:53 · [NETWORK], version B (honest)**

> Two other teams posted offers there. No trade between them settled. A network is easy to open and hard to fill.

**1:53 · [NETWORK], version B, when the tool prints B-UNCONFIRMED**

> Two other teams posted offers there. Our records and the public board don't yet agree on a trade between them, so we don't count one. A network is easy to open and hard to fill.

**1:53 · [NETWORK], version A (the network worked)**

> Today one trade between two other teams settled there: [card] for [price] primas, and neither side was us. That settlement is on screen.

**2:01 · When it broke (Craft)**

> Our worst failure: Saturday at 10:22 our trade desk stopped, and nobody restarted it. From midday to evening another team offered us, by name, the one card that would finish an album page: twelve offers. With the desk off, no bot of ours even read them, and the page stayed incomplete. An offer is worth nothing if nothing is listening. Today one command starts our bots and a watchdog says which one is down[if merged #70: , the desk included]. [if merged #71: And an analyst on duty reads every Market Test and duel wave as it lands.]

**2:38 · Test before trust (Craft)**

> We bet more pairs per tick would beat the simple Market Test rule. We wrote the decision rule first, ran eight thousand sessions a scenario, and lost: eleven standard errors on the hard test, and in simulations fitted to all five recorded sessions. Simple rule kept. Overnight, two searches ran: [07:00: duel strategies scored] duel strategies against rivals refit from Saturday's duels, [07:00: broker policies screened] broker policies against those five sessions. [07:00: result line.] A duel feature that won in simulation we switched off: a reviewer reproduced a slow-server race that could lose a whole duel.

**3:18 · [optional demo] (Craft, about 10 seconds with the run)**

> These numbers are not slides. Hector? [Hector runs `python3 tools/pitch_numbers.py --live --stage`; it prints within 5 seconds.] These five verification figures come from our recorded data, computed now.

**3:25 · The team behind it (Craft)**

> We're three people, a former teammate, Hector and me, running Claude sessions like a trading firm: a conductor, a pull-request steward, overnight analysts[if merged #71: , one on duty today].

**3:35 · Close (Idea), ends about 3:49**

> "Agents do the work. You get the money." This weekend taught us what goes in between: the agents do the work, and structure holds the money. Words persuade. Structure binds. We built for the structure.

### 3a. The 07:00 fill for the overnight lab

Thiago fills the three `[07:00: ...]` brackets from the two interim reports written at 06:45. Every number comes from these files; nothing is rounded up.

| Bracket | File (branch until merged) | What to read | If the file is missing or unclear |
|---|---|---|---|
| duel strategies scored | `docs/duel-lab/duels3-search/leaderboard.md` (branch `vm/wp10-duel-search`) | The "Candidates scored: N on train" line (123 at 00:54 UTC) | Say "over a hundred" only if N ≥ 100; else cut the whole "Overnight, two searches ran ..." sentence |
| broker policies screened | `evals/broker-search/leaderboard.md` (branch `vm/wp11-broker-search`; **not written yet at 03:10**: only the lab code is on the branch) | The count of policies screened | Cut "and [M] broker policies against those five sessions" |
| result line | Each file's own verdict line (the TEST result against its acceptance rule) | One wording per file, and only the one its verdict line supports: (a) the file says no candidate passed its acceptance rule on TEST: "No candidate beat the current settings on the held-out test." (b) it says a candidate passed every rule and was deployed (in `docs/duel-lab/duel-params-duels3.json` or the broker line on `main` by 08:00): "One candidate passed every test: [what it changes in plain words], [gain from the TEST row] per duel." (c) it says a candidate passed but nothing was deployed (frozen at 08:00): "One passed the test, too late to deploy before the freeze." Quote the verdict line's wording to Hector at 07:00 so he can check it | **No default.** If a file has no TEST verdict line, or is missing, say nothing about that search's result: cut the result sentence (and, if both are missing, the whole "Overnight, two searches ran ..." sentence). Never quote a train or selection gain as a result |

The F4 sentence ("almost a point of the pie per duel ... switched off") is on `main` and needs no fill: `docs/duel-lab/duels3-params.md` lines 8 to 11 (+0.0083 ± 0.0007 a duel in the arena; off because the review reproduced a slow message costing another duel's late accept, test `SundaySlowServer`). The score per duel is the share of the pie times the round decay, so +0.0083 is 0.83 % of the pie: say "almost a point of the pie", never "almost one percent more money".

### 3b. The optional demo

Only if the slot is at least 4 minutes **and** the rehearsal at 07:00 runs it under 25 seconds. `python3 tools/pitch_numbers.py --live --stage` on the demo laptop after `git pull` (keyless, read-only; `--stage` drops the team ids so nothing on screen names a team). It prints the verdict line and the five numbers. If it errors, hangs past 5 seconds or prints anything unexpected: Hector says "we'll skip that", Thiago reads on. Never debug on stage. `tools/factory.py plan` is **not** a live demo: its command lines carry caps and reserves (evidence file, "Never on screen").

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
| "Saturday at 10:22 our trade desk stopped ... twelve offers ... no bot of ours even read them, and the page stayed incomplete" | Always true: `logs/market/2026-10-03.jsonl` ends at tick 266 (10:22:12); the feed has 12 offers of that card addressed to us by one team, ticks 533 to 1108 (12:36 to 19:29), three for cash (105, 80, 67 P), the rest swaps; our own bids for it were 68 P (tick 750) and 73 P (tick 758); none of the 12 was accepted and the page stayed incomplete (`logs/state/me.json`) | If a Sunday buy completed the page, add nothing: the Saturday loss stands, and naming the card is out (section 7) |
| "[if merged #70: , the desk included]" | PR #70 merged by 08:00 and `factory.py status` showed `market_desk RUNNING` on Sunday | Drop the bracket. On `main` today `market_desk` is `"enabled": false` in `tools/factory_sunday.json` |
| Every `[if merged #71: ...]` (the "When it broke" sentence, the team beat's "one on duty today", the "Where is the AI?" answer) | PR #71 merged and the analyst session ran at least one trigger (`logs/analyst/LATEST.md` exists on the VM) | Drop all three brackets: the sentences read on without them ("... overnight analysts.") |
| "[if merged #67: Today it also tells teams ...]" | PR #67 merged and `announce.py --variant missing` or Celestina `/api/missing` ran on Sunday | Drop the bracket. Never say how many teams read it (section 7) |
| "[if served: , and a keyless API ...]" | Celestina's public side served behind a tunnel on Sunday (Thiago's yes) | Drop the bracket: the sentence still stands on the broker alone |
| "Today one command starts our bots and a watchdog says which one is down" | Always true: `tools/factory.py up --yes` and `status --notify` (on `main` since Saturday 14:47, commit 4e3553b) | |

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

- **"Where is the AI?"** Claude did the work of a small firm: the research, every line of code, the reviews, the overnight analysis, and the Sunday operations, as a team of sessions (a conductor, a pull-request steward, analysts[if merged #71: , an analyst on duty today]). In the market the bots are deterministic on purpose: they speak in template lines Claude wrote (`agent/abuela.py`, `agent/chato.py`, `line()`), and no model call sits on the money path, so nothing a counterparty types can change a number. That is the design we would want in your network too: the model drafts and explains, the structure settles.
- **"Did prompt injection hit you?"** Nothing we can show moved us, and by construction it could not: our bots never read other teams' words as instructions; they read the structured offer, and every number comes from code. Say "the design makes it pointless"; do **not** say "we blocked attacks" (we have no counted attempts to show). Our duel book even fingerprints rival bots by their message template (`docs/duel-lab/duel-book.md`): their words are data about them, never orders to us.
- **"How do you read other teams' values?"** Every team gets the same six multipliers, shuffled: 720 possibilities. Each public move is evidence: choosing a set, shedding one, a price paid is a floor on its value. Bayes does the rest (`tools/value_inference.py`). Honest result over the weekend: its top pick for a team's next choice is right 21 % of the time, against 17 % for chance and 23 % for "repeat their favourite" (`value_inference.py check`, 539 choices). Where it misled us: it reads page-completion buying as taste. That is the AP/AR lesson: behaviour reflects constraints, not only preferences.
- **"How do you know other teams' cash?"** Rebuilt from public events alone (`tools/ledger.py`): dealer settlements, team trades with who paid the fee, venue bonds, grants. Checked against our own account at every real reading we have: 12 of 12. Three traps we had to solve: package trades with cash, a fee the feed does not attribute, a 400 P payday that came only as an announcement (`docs/findings.md`, PR #61). That is reconciliation from a public event stream, which is most of what a finance agent does before it negotiates.
- **"How do you stop a runaway bot?"** Layers, each with its limits said plainly. Caps that can only lower our limit (`agent/abuela.py`, `agent/chato.py`). The accept slot: the server itself allows one accept per team per tick; the market desk takes a lease before it accepts (`agent/lease.py`); the duel bot writes a local lock file while a duel is live (`agent/duel.py` calls it a stopgap), and the dealer bots check it before every accept and defer (`agent/dealer_client.py`, `guarded_accept`). The lock is a file on one machine, so it only covers bots run from that checkout. The Sunday factory gates every **launch** on the game clock, the doors and the duel waves, and restarts bots under watch (`tools/factory.py`, `docs/plans/sunday-runbook.md`); stopping a running bot is one command (`tmux kill-window`). Do not say "global kill switch" or "one lease for every bot": neither exists.
- **"Tell us more about the desk that stopped."** The market desk's log ends at tick 266, Saturday 10:22 (`logs/market/2026-10-03.jsonl`); no restart followed. The factory that now starts and watches every bot was built that same afternoon (commit 4e3553b, 14:47), but the desk was left out of it, off by default. So the honest post-mortem is ownership, not tooling: nobody owned "is anything listening for offers addressed to us". Do not claim the desk would have bought the card, nor that inactivity alone cost the page: whether the desk accepts offers addressed to us is not shown anywhere we can point at, **and our cash was short of the asks at the time** (rebuilt by `tools/ledger.py`; the figures stay off stage). If pressed: "we missed them, and we could not have paid that day anyway; the lesson is that we did not even know".
- **"What else did your reviews catch?"** Saturday's lunch audit found the broker's timeouts were sized for 30-second ticks: 5 s on a read with one retry, about 10.5 s blind on one bad read, most of a 15-second Sunday tick, and the hard Market Test's traders can stay a single tick (`docs/analysis-saturday/market.md` section 7; fix in PR #63, 6 of 6 planted bugs caught). And the duel feature switched off for Sunday: in the arena it is worth +0.0083 a duel (almost a point of the pie), but a reviewer reproduced, through the real kit client, a slow message landing in the next tick and costing another duel's late accept (`docs/duel-lab/duels3-params.md` lines 8 to 11, test `SundaySlowServer`).
- **"What did you get wrong?"** Four, all on record. The desk that stopped (above). Our own broker scored 0 in a Saturday Market Test because it refused every bench pair, all of which carry the same maker (`docs/findings.md`, fixed in PR #22). Our duel model priced delivery days wrong for sellers until three of the server's own results showed it (PR #54, patched live during Duels II). And the Market Test idea we liked best lost in simulation, so we did not ship it (PR #65).
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
- No "273 tests" or any test count from a machine we have not checked. On the VM this branch (with `main` at a304c4d merged in) runs 1,216 tests with `TZ=Europe/Madrid`: 4 failures, 3 of the known pre-existing ones plus the intermittent `test_celestina.AccessLogTest`; in UTC more fail on time zone alone. Quote the rule instead ("every new guard ships with a planted bug its test must catch"), with PR #63's 6 of 6 and PR #65's 8 of 8 as the proof if asked.
- No "the inference knows every team's values". It is a hint that beats chance.
- No "max pairs lost everywhere", and no "lost on five real sessions". It lost beyond noise in 42 of 48 simulated scenarios and in simulations fitted to all five recorded sessions; on the one recorded-path replay (b36) it scored 0.800 against the stall's 0.980; on the other four recorded books it would have sent exactly the stall's matches; it won in 4 scenarios (one of them the adversarial mix). Say "lost on the hard test by eleven standard errors, and in simulations fitted to all five recorded sessions".
- No "we fixed the broker's pace" unless the Mini pulled PR #63 (merged Sunday night) before 09:00. "An audit caught it before Sunday" is the safe line (Q&A only now).
- **The incident beat:** never name the card, its set or page, the team that offered it, or the prices (105, 80, 67, our 68 and 73). "The one card that would finish an album page" and "another team" are the most we say. Not "we lost it because nothing was listening" (cash was short of the asks too), not "the desk would have bought it", not "we fixed it that night" (the factory dates from Saturday afternoon and the desk was left out of it), not "the analyst / the desk ran today" unless its bracket's condition held.
- **The overnight lab:** no result sentence without the TEST verdict line it comes from (section 3a); never a selection-set or train-set gain as a result; never a broker-search number before `evals/broker-search/leaderboard.md` exists. "Almost a point of the pie" (F4) is a simulation number for a feature that is off; say "in simulation" if it is asked about.
- **The demo:** only `python3 tools/pitch_numbers.py --live --stage` (no team ids, 5-second deadline). Say "these five verification figures come from our recorded data", never "every figure in this talk" or "from the public record" (the ledger check uses our own account readings; the searches, simulations and inference are not in it). Never `factory.py plan` (caps and reserves in its command lines), never the tool without `--stage`.
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
- **"18 minutes"** (PR #11 to #12) was replaced by the 15 s pace catch (PR #63) in round 1; pass 2 moved the 15 s catch to Q&A to make room. The PR #11/#12 story stays in the rehearsal note.

### Round 3 (Sunday 03:40, second adversarial review)

- Incident: no causal claim; facts only (desk off, twelve offers unread by any bot of ours, page incomplete) and the general lesson. Cash shortfall goes to Q&A, figures off stage.
- Version B has a third state, B-UNCONFIRMED, with its own outcome sentence; the tool prints it.
- Every analyst-on-duty mention (script team beat, Q&A) is behind `[if merged #71]`.
- Lab result: no default verdict; one wording per file, tied to its TEST verdict line; a third wording for "passed, not deployed"; cut if missing.
- Demo: "these five verification figures come from our recorded data"; the tool now has a 5-second deadline with `--stage`.

### Pass 2 (Sunday 03:15, orchestrator's four additions)

- **In:** (1) the incident as a beat ("When it broke"), told as what the logs show: the desk stopped, twelve offers went unread by any bot of ours, the page stayed incomplete (round 3: no sole-cause claim, our cash was short of the asks too); the fixes are on `main` (factory, watchdog) or bracketed `[if merged #70]`, `[if merged #71]`. Not "fixed in hours": the factory was built that afternoon but without the desk. (2) The overnight lab, with `[07:00: ...]` brackets filled from the two 06:45 reports (section 3a) and the F4 switch-off from `main`. (3) An optional 10-second demo, `pitch_numbers.py --live --stage` only; `factory.py plan` is refused (caps in its output). (4) The public-good sentence on La Celestina, with the API `[if served]` and the missing-card notices `[if merged #67]`.
- **Cut to stay under 4:00:** the "so the question was never 'can an AI haggle?'" line (now "So: what do you let an AI touch?"); "That gap is the real work of an agent negotiating terms"; the announcements clause of the venue paragraph; the version A/B paragraphs now carry only the outcome; the planted-bug rule and the 15 s pace catch moved to Q&A; the F4 gain moved to Q&A.
- **Length (round 3, current):** see the first line of section 3: B 572 words (3:49), B-UNCONFIRMED 586 (3:54), A 574 (3:50) with every bracket, the longest lab wording and the demo; 469 (3:08) with none.
