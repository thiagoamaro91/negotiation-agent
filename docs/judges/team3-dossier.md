# Team 3 (t03) · The Bazaar · Cromos de Madrid — submission dossier

**Audience:** the judges and the agents that read for them. **Scoring category:** Judges, 40 of 100 points, "ideas and craft" (`kit/RULES.md` line 120).
**Written:** Sunday 4 October 2026, after the 14:59 freeze. **Authors:** Hector Moyano's Claude sessions, compiled for Thiago Amaro (team lead, repo owner). Team: Thiago Amaro, Hector Moyano, Jay Shankarpure.
**Repo:** `thiagoamaro91/negotiation-agent`, `main` at `3358e4c`. **Rule for this document:** every claim carries its evidence (a path, a pull request, a log line or a public API call). Where a figure is a recollection and not a record, it says so. Nothing here is rounded up.

---

## 0. Machine summary

```json
{
  "team": "t03",
  "final_board": {
    "source": "GET https://bazaar.causaprima.ai/api/leaderboard (frozen, tick 2797) and logs/score.jsonl on branch mini/logs",
    "negotiating": {"points": 26.04, "of": 30, "rank_among_18": 1, "runner_up": {"team": "t05", "points": 24.64}},
    "market": {"points": 8.15, "of": 30},
    "overall": {"points": 34.19, "rank_among_18": 4},
    "deals_settled": 50,
    "deals_of_top5_teams": {"t05": 74, "t10": 77, "t12": 82, "t03": 50, "t18": 57},
    "pages_complete": 4, "pages": ["La Latina", "Lavapiés", "Salamanca", "El Retiro"], "album_filled": "43/60", "dealer_level": 5, "badges": ["Sharp ear"]
  },
  "negotiation_breakdown": {"duel_points": 40.19, "neg_points_team_trades": 136.5, "ladder_points": 0.371},
  "clearing_house_sunday": {
    "idea_to_live_minutes": 28, "built_reviewed_deployed_run_hours": 3,
    "teams_in_game": 18, "teams_excluded_by_us": 7, "teams_invited": 13, "teams_joined": 6, "teams_with_books": 5,
    "same_card_pairs": 40, "pairs_with_buyer_max_at_or_above_seller_min": 0, "trades_executed": 0, "primas_moved": 0, "keys_shared": 0,
    "idea_to_first_external_team_joined_minutes": 93, "invite_codes_minted": 13,
    "safety_nets_that_fired": 2, "live_defects_found_by_other_teams_agents": 3, "codex_review_rounds_across_4_prs": 12, "codex_review_rounds_on_pr_96_before_merge": 5,
    "source": "docs/judges/clearing-house.md, docs/judges/clearing-house-status.json, PRs #96 #101 #102 #103, team bus issue #25 (13:00 to 13:51)"
  },
  "duels": {
    "saturday": {"duels": 100, "deals": 83, "our_surplus_sum": 2170, "source": "logs/duel/2026-10-03.jsonl (branch mini/logs)"},
    "sunday":   {"duels": 102, "deals": 80, "our_surplus_sum": 2276, "source": "logs/duel/2026-10-04.jsonl (branch mini/logs)"},
    "total":    {"duels": 202, "deals": 163, "deal_rate": 0.81}
  },
  "engineering": {
    "commits_on_main": 464, "pull_requests_merged": 99, "pull_requests_opened": 104,
    "python_lines_tools_and_agents": 38072, "test_lines": 23651, "test_functions": 1709, "test_files": 84,
    "docs_markdown_files": 56, "public_feed_events_recorded": 40919,
    "independent_review_engine": "OpenAI Codex (GPT-6.1 Sol) on every non-trivial PR; merges only on SHIP or SHIP WITH FIXES over the exact head"
  },
  "ai_in_the_money_path": "none: every prima moved by deterministic code with hard limits; Claude did research, code, reviews, analysis and orchestration",
  "money_safety_record": {"keys_held_outside_the_mini_after_sat_11:17": 0, "clearing_house_primas_moved": 0, "model_outputs_that_moved_a_prima": 0}
}
```

---

## 1. The headline: first in Negotiating, with the fewest deals of the top five

| Team | Negotiating /30 | Market /30 | Overall | Rank | Deals |
|---|---|---|---|---|---|
| **t03 (us)** | **26.04** | 8.15 | 34.19 | 4 | **50** |
| t05 | 24.64 | 13.08 | 37.73 | 1 | 74 |
| t10 | 23.49 | 12.26 | 35.76 | 2 | 77 |
| t12 | 23.07 | 11.44 | 34.51 | 3 | 82 |
| t18 | 23.27 | 9.00 | 32.27 | 5 | 57 |

Source: `GET /api/leaderboard`, frozen snapshot (tick 2797); our own row also in `logs/score.jsonl` (branch `mini/logs`, last rows 14:40 to 14:55).

Why this matters to the people who built the game: Negotiating is the category closest to Causa Prima's own product, agents that negotiate terms with other agents and settle by structure. We scored the most negotiation value of the eighteen teams while settling fewer deals than any other team in the top five. The points came from **quality per deal**, not volume: 163 duel agreements out of 202 (81 %) with a surplus-maximising bot tuned in our own arena, four album pages completed by buying the last card from other teams (the page bonus only pays when the closing card comes from a team, not a dealer; measured, section 7), and a dealer ladder where every buy limit and sell floor was clipped to our private value in code.

The second headline is Sunday afternoon (section 1b): **a third of the market agreed, in under three hours, to hand its private order books to a mechanism we designed**, because the mechanism could prove it would never move anyone's money outside their own numbers. It found no trade that benefited both sides and said so. That is the behaviour a clearing network needs before anyone trusts it with real invoices.

---

## 1b. Sunday: six teams agreed to one fair mechanism in three hours

**The feat.** Between 10:50 and 13:43 on the last day, with the stalls closing at 13:56, Team 3 designed, built, reviewed, deployed and ran a private clearing house, and persuaded five other teams, competitors in a game where lying is legal, to hand it their private sell minimums and buy maximums. Six of eighteen teams joined (t03, t07, t13, t14, t15, t16); five sent books. No pact, no reciprocity, no pressure: Hector's standing rule was that the mechanism had to win on merit (section 3, point 4).

**How it was done, hour by hour** (server membership record for join times; conversation times are the operator's recollection). Hector recruited every team **in person, in the room**: a short bilingual message carrying the tunnel URL and `/agents.md` ("have your agent read it and tell you whether it is worth it"), then a per-team invite code spoken aloud or typed by him on that team's laptop. The teams' own agents read `/agents.md` and advised their humans. The explainer page went public around 12:00 and the full source went up as a public gist around 12:15 on Hector's instruction ("open-source everything except the passwords"). Idea 10:50 → PR open 11:07 → live behind a tunnel ~11:18 → first external team in at 12:23 (t13, 1 h 33 min from idea) → t07 12:52 → t16 ~13:00 → t15 13:05 (four minutes after saying yes) → t03 13:11 from the Mini through Thiago's conductor on the bus → t14 13:13 (book 13:22). A seventh team (t06) asked to join at 13:18, was accepted, and did not complete before the round. Thirteen invite codes minted; six teams in; stalls closed at 13:56.

**Why teams said yes.** The invitation did not ask for trust; it removed the need for it. What each team was shown, in person and on a bilingual explainer page with an animated walkthrough of the five steps (private books → matching at the midpoint → one trade per venue → everyone's OK → execution by your own client):

- **Your key never leaves your laptop.** The client is one standard-library Python file; the server holds no key. Teams were told to read it before running it, and the server serves its own source for audit (`tools/clearing.py`, `tools/clearing_client.py`, PR #96; public gist handed out with the invite code).
- **Nobody sees your prices.** Public status shows teams and counts only; a team's plan shows only its own actions. Reservation prices are never served.
- **Nothing executes for you.** A run is a proposal. Your client signs a SHA-256 of exactly what it read and votes OK or NOT OK with a reason; a NOT OK vetoes those pairs. Only your own client posts or accepts, and only after re-checking the game's public feed, your stored limits and your live cash reserve. Ctrl-C stops it.
- **A round for everyone or no round.** The matcher first gives every participant's venue one trade (never a venue owned by either side), then spreads the rest to the venue that has hosted the least value today. If any venue would host nothing, the round is held. Fairness was a constraint in the allocator, not a promise.
- **Guest list by fairness, not by advantage.** We excluded seven teams ourselves: the top four and the two within two points of us (direct rivals), plus one with a suspicious back-and-forth on the public feed (later admitted after Hector's yes). Thirteen invited, each with its own invite code minted per team.

**The rules, and who set them.** Every design rule came from Hector, in the room, as teams raised doubts: one password per team so a code cannot be shared (11:4x); open-source everything except the passwords (12:1x); if not everyone benefits, the round does not start, and allocation by phases and by value hosted (12:3x); every team reviews its proposal and answers OK or NOT OK with a reason (12:4x); a hash so nobody can back out of what they approved (12:5x); no round executes without his OK (13:0x). Other teams contributed verifications, not rules. Codex contributed twelve review rounds across the four PRs (5 on #96, 1 on #101, 3 on #102, 3 on #103): fee read from the game not the plan, cash reserve, quantity cap, approval kept locally, nonce in the hash, settled-only public ledger, counts-only public status.

**Who found what: other teams' agents audited our client, and we hardened it on the spot.**
- About 12:05, before most teams were in, one team (unnamed here) had its agent read `clearing_client.py` and sent Hector a precise objection: `execute` posted whatever offer body the server returned and accepted whatever offer id the server named, without checking contents, so a malicious or buggy server could sell any of our cards to anyone, and an accept could hand over a card the offer "wanted". Their closing line: "It's the same trick we closed today with Pícaros." They added that they did not assume bad intent. **They were right.** Fix: `check_sell` / `check_buy` (commit `73d3c28`, served within about fifteen minutes, operator's recollection): the client now acts only on offers that match exactly one of its own listed copies, for plain cash, at or above its own stored minimum, addressed to the buyer the plan names; and accepts only after re-reading the offer from the game and re-checking price, fee, its own value and its cash reserve.
- About 13:00, Team 13, already in with its book sent and `execute` running, reported that the hardened buyer could never verify a sale: addressed offers never appear in a venue's public book (they had checked: 110 public offers across all venues, 0 addressed), so every buy would wait forever. They pointed at the public feed, whose `offer.listed` events carry `to`, `give` and `want`. Fix: commit `5f26b90` (~13:03, about ten minutes), verified against our recorded feed (2,679 `offer.listed` events addressed to a team).
- 12:44, Team 7 hit the published join command failing on `--team` (a parser-root flag; found by Codex in review the same minute and confirmed by Team 7's experience; commit `28a1c5a`). A second stumble for Team 7 was a hand-typed invite code with an "I" next to an "l"; resolved by copy-and-paste. Team 7 took about thirty minutes from invitation to join; Team 13 about five; Team 15 about four from its yes.
- Thiago's planning session on the other account read the client code independently and found that the default book would have listed our own Retiro page cards for sale; the Mini conductor joined with `--keep` (bus, 12:17 and 13:10).

The system was reviewed by four parties who did not write it before it touched anyone's money: Codex (twelve rounds), two other teams' agents, and the other half of our own team. One team's security objection became the client's core guarantee within the hour.

**What the mechanism did when it mattered.** Books landed at 12:55 (t07), 13:10 (t03), 13:19 (t13, t15), 13:22 (t14); t16 joined but never sent one. 13:33, five books in: **held, zero crosses**. Of 51 same-card pairs (40 in the later export, after the one approved trade consumed a copy), none had a buyer's max at or above a seller's min at the default 15 % margins. Teams re-sent their books with zero margin (t03 13:36, t13 13:41); at 13:42 a forced run found two candidates and proposed one, with zero surplus; both clients auto-approved it at 13:42:29 and 13:42:32; **the seller's own client refused to post** because the price was below the minimum it had stored locally (server record: `failed: client refused`). Hector's call at 13:4x, with stalls closing in a quarter of an hour: stop everything and tell the judges why it did not work, rather than manufacture a trade. He had already declined, on the fair-play rule, the idea of creating an artificial cross to put value on our venue. Server stopped at 13:43. Primas moved: 0. Trades executed: 0. Keys shared: 0. A disclosure we got wrong (a zero-surplus price row on the status page revealed two reservation prices by inference; the commitment hash was brute-forceable from an export) was found in review of the write-up and fixed in PR #103 the same afternoon.

**Why zero is the right answer, and what it taught.** The teams that joined were the teams like us: the same spare neighbourhoods (Chamberí, Malasaña, Salamanca commons on both sides of every book), the same wants. The heterogeneous teams, the ones who value what we have and have what we want, were the leaders we chose not to invite. Liquidity needs heterogeneity. In a game whose fair-play rule voids deals that feed another team, a clearing house that answers "there is no value to share" is the correct behaviour, and it answered it twice: once in the allocator and once in the seller's own client. With one more hour: start at 10:00, invite the heterogeneous teams, add card-for-card swaps and three-way cycles, where the surplus between similar teams hides.

**Evidence.** `docs/judges/clearing-house.md` (full account, time-stamped, recollections marked); `docs/judges/clearing-house-status.json` (operator export of the live server's state with every price removed: per-team venues, book counts and timestamps, votes, the `failed: client refused` row); PRs #96, #101, #102, #103, #104 and their review threads; team bus issue #25 from 11:07 (announcement) to 13:51 (Hector asks that the Clearing House goes into the presentation); the explainer page (bilingual, Hector's, shared with the teams); a live team tracker shared with Thiago and Jay with each team's status (pending / talking / thinking / yes / in / no / excluded) and a server-fed strip of who was actually in.

---

## 2. How to verify any claim in this document

- **Code and docs:** paths are relative to the repo root on `main` (`3358e4c`). Pull requests are `thiagoamaro91/negotiation-agent#N`.
- **Live logs:** the bots ran on one machine (Thiago's Mac mini). Their logs are pushed to branch `mini/logs` every 10 minutes (`tools/logs_push.py`, PR #66): `logs/duel/*.jsonl`, `logs/broker/*.jsonl`, `logs/chato/*.jsonl`, `logs/market/*.jsonl`, `logs/score.jsonl`, `logs/state/me.json`.
- **Public feed:** `logs/feed/feed.jsonl` is our recording of the organisers' public event stream (40,919 events), gap-filled from a second recorder on a VM (`logs/feed-vm/`). `python3 tools/feed_report.py board|haggles|trades|prices` reproduces every table in `docs/findings.md`.
- **The five pitch numbers:** `python3 tools/pitch_numbers.py --live --stage` (keyless, read-only, 5-second deadline) recomputes them from the recorded data.
- **Reviews:** every Codex review verdict is quoted in the PR thread; the merge rule is in `CLAUDE.md` and `docs/plans/HANDOFF.md`.
- **Team bus:** issue #25 holds every message between our Claude sessions (signed `FROM: <session> | TO: <session>`, enforced by `tools/bus.py` since PR #46).

Nothing in this document contains a key, a token, a cap, a cash reserve or a private multiplier. Our true valuations are still ours.

---

## 3. The thesis we built against

The game's one rule is *"words persuade, structure binds"* (`kit/RULES.md` line 11): no text moves a prima, only a structured offer accepted by the other side, and prompt injection between teams is legal. Causa Prima's network has the same shape: a note on an invoice can say anything; only the fields settle.

So the design question we answered all weekend was: **what do you let an AI touch when money is on the line?** Our answer, held from Friday night to the Sunday freeze:

1. **AI does the work; code holds the money.** Claude (and Codex as an independent second engine) wrote the code, ran the analyses, reviewed every PR, orchestrated the night shifts. In the market, no model output ever moved a prima: every bot decides in deterministic Python against our own numbers and logs *why* (`agent/*.py`, decision lines in `logs/*/`). This is also why our evals are offline and keyless (section 5, C4).
2. **Other teams' text is data.** Every message from a dealer or a team is parsed for structure and never executed as an instruction (`CLAUDE.md`, "untrusted text" rule; `tools/redaction.py` scrubs anything that looks like a credential before it is logged or posted).
3. **Trust needs an audit trail.** Two public recorders, a ledger that rebuilds every team's cash from public events, a swarm view that shows which agent read what and when, a bus where every session signs its messages.
4. **A neutral venue earns traffic by being useful, not by pacts.** Hector's rule, Saturday 17:40: no reciprocal deals between teams, no pressure, no injection bait. La Celestina and the Clearing House give honest, useful information to other teams' agents and win on merit or not at all.

---

## 4. What we built (Ideas)

Each item: what it is, why it exists, where it is, what it did. **I** = idea, **C** = craft (section 5).

### I1 · Market brain: Bayesian inference of every team's private values (Friday night)
- **What.** `tools/value_inference.py` infers each team's secret neighbourhood multipliers by Bayes over the 720 permutations of the six multiplier values, from three public signals: which cards a team chooses to buy (the k-th pick from the same neighbourhood weighted 1/k), which it lets go, and the price floors it reveals. `tools/ledger.py` rebuilds all 18 teams' cash from 400 P using every public event (dealer and team deals, fees ceil(5 %)+1 paid by the acceptor, stall deposits, gifts, grants, the 400 P payday). `tools/market_plan.py` turns that into a timed plan: probability of sale × gain × round weight, per offer, per team. `tools/brain.py` + `brain.html` recompute everything in about 2 seconds per new event and push it to a live page over SSE.
- **Why.** Negotiation value is scored at private values; the team that knows the other side's values first negotiates best.
- **Evidence.** PRs #3, #5, #43, #51; tests `tests/test_value_inference.py`, `tests/test_ledger*.py` (mutation-checked). Ledger exact on our own account at 12 of 12 readings (`docs/findings.md`, "Saturday evening: every team's cash"). Inference: correct ordering of our own sets at tick 96; temporal test ~45 % vs 20 % chance, honest reliability line printed by `value_inference.py check` ("beats chance, not repeat"). Known limit, recorded: buying to complete a page reads as preference and biases the inference (`docs/findings.md`, Saturday asset-ids section).

### I2 · The duel bot and its arena (Saturday to Sunday)
- **What.** `agent/duel.py` negotiates two-issue duels (price and delivery day) against other teams' agents with 12 to 15-second ticks. `tools/duel_arena.py` is a faithful offline replica of the server's referee (payoff = surplus × 0.92^rounds; seller earns +w per delivery day from day 0, buyer pays it: confirmed against server results 5626, 5675, 5692 and fixed by PR #54 in a live hot patch). `tools/duel_tune.py` and `docs/duel-lab/duels3-search/` searched thousands of parameter sets against rival profiles refit from the real duel logs; `tools/duel_matrix.py` is the decision matrix (train / selection / held-out test seeds, scenario-by-rival-style).
- **Why.** Duels were the largest single component of our negotiation score (40.19 duel points).
- **What it did.** Saturday: 100 duels, 83 deals, surplus 2,170. Sunday: 102 duels, 80 deals, surplus 2,276 (`logs/duel/2026-10-0{3,4}.jsonl`). Duels II alone: 68 duels, 57 deals (seller 30/34, buyer 27/34).
- **Evidence.** PRs #9, #10, #30, #33, #47, #54, #72, #76, #78; `docs/duel-lab/duel-book.md` (every rival's style), `duels2-matrix.md`, `duels3-matrix.md`, `duels3-params.md`. Two-topic "robust mode" (only accept or propose if it pays whether the rival's best day is 0 or 10) shipped by default in #33 after three adversarial review rounds.

### I3 · La Celestina: a venue for other teams' agents (Saturday)
- **What.** Our own venue v20, zero fee, with `agent/broker.py` crossing bids and asks every tick, a keyless agent-facing page and API (`tools/celestina.py`: `/agents.md`, `/api/match?team=tNN`, `/api/v20`, `/api/fair/REF`, `/api/missing`), a concierge "wants / haves" board folded in (PR #32), and an announcer (`tools/announce.py`) that posts the live book with the exact order another agent needs to send, honest fee lines, and (Sunday) which card each team appears to be missing and who holds it (`tools/matchmaker.py`, PR #67, #73, #74).
- **Why.** The Market category paid for value created *between other teams* on your venue. Organisers' Sunday hint, recorded Saturday 20:46: zero-fee venues do not attract traffic; finding the missing card does.
- **Design rule.** Everything served to other agents is read-only, keyless, scrubbed of our values, and built so that a bot that follows it is better off (`tools/redaction.py`; public view tests in `tests/test_celestina.py`, `tests/test_announce*.py`).
- **Evidence.** PRs #15, #20, #27, #31, #32, #44, #45, #49, #67, #73, #74, #85, #86, #89. Honest outcome (section 8): two other teams posted 29 offers on v20; no trade between two other teams settled there. `docs/judges/judges-story_v3.md` section 0 defines the three-state truth test we built so the pitch could never overclaim.

### I4 · The Clearing House: a private order book with a matcher across venues (Sunday, built in under three hours)
- **What.** `tools/clearing.py` (server, keyless) + `tools/clearing_client.py` (one standard-library file any team runs on its own laptop with its own key). Teams hand in, privately, what they would sell with their minimum and what they want with their maximum. A greedy matcher pairs same-card bids where max ≥ min, prices at the midpoint net of venue fee, and assigns venues so every participant's venue hosts a trade. A run is only a proposal: each team's client signs a SHA-256 of exactly what it read; a NOT OK vetoes; only with every OK does anything execute, and it is each team's **own** client that posts, after re-checking the game's public feed, its own stored limits, its own live cash reserve. The server is never trusted with a key or a decision.
- **Why.** Hector's idea at 10:50 Sunday: teams low in the table all had spares nobody traded; pool them privately, place the trades on every member's venue, split the surplus. It is a miniature of a multilateral clearing network, the thing Causa Prima's product needs at scale.
- **What happened.** Section 1b: six of eighteen teams joined, zero crosses, zero primas moved, two safety nets fired, two live defects found by other teams and fixed in minutes.
- **Evidence.** PRs #96 (five adversarial review rounds, merged 13:07), #101, #102, #103 (privacy: settled-only public ledger, per-round salted commitments), #104; `docs/judges/clearing-house.md`; `docs/judges/clearing-house-status.json`; public gist of the code handed to teams in person.

### I4b · Dealer deceit detection: Los Pícaros' bait-and-switch (Sunday)
- **What.** Los Pícaros (a level-4 dealer) change the card after agreeing a price. The game rewards a team that flags the switch correctly (+10 negotiation points per correct flag, capped at three). The Mini conductor found it on Sunday morning; `agent/chato.py` was changed to detect the switched item automatically, flag it, and keep countering instead of walking away. Three correct flags: +30 negotiation points (bus, 12:04 and 12:47).
- **Why it matters.** It is the game's own test of whether an agent checks the structure of a deal against what was negotiated, the exact failure mode of an invoice whose line items drift from the agreed terms.

### I5 · Swarm view: one event stream for every agent (Saturday night)
- **What.** `tools/swarm.py` + `swarm.html`: every bot, lane and conductor session appends to one JSONL stream; the page shows the live graph of who is running, what each agent **read** (broker book, rival state, `/api/me`, the feed) with freshness, and a Saturday replay. A `serve --public` mode strips every "why", value, floor, limit and internal text so a link could be shown to judges without leaking strategy.
- **Why.** Hector and Thiago could not tell on Saturday whether the agents were coordinating. The map (verified against code and logs) found that the market desk had stopped at 10:23 and that the duel lock covered only the Mini's bots, which became fixes.
- **Evidence.** PR #48 (27 tests; Codex findings fixed: mandatory token on the private view, nothing on 0.0.0.0, cursor lock, cancellations without price).

### I6 · Team bus: signed messages between Claude sessions across two GitHub accounts
- **What.** `tools/bus.py` over issue #25. Each session posts `FROM: <session name> (<id>) | TO: <session>`; the tool refuses unsigned writes (PR #46, #50). Sessions on Hector's Mac, Thiago's Air and the VM handed over the key lease, decisions, incident reports and verdicts through it.
- **Evidence.** PRs #26, #46, #50; the issue itself.

### I7 · The factory: one command starts the whole team of bots, with gates and a watchdog (Saturday night → Sunday)
- **What.** `tools/factory.py` + `tools/factory_sunday.json`: launches broker, duellist, dealer bots, announcer, matchmaker, outreach, log pusher and watchdog in tmux windows, each with a keeper that restarts it, a per-bot lock, game-time gates read from `/api/schedule` (duel waves, Market Test silences), crash-loop alerts at three failures, and `status` / `plan` views. Thiago's Mini ran it from 08:55 Sunday.
- **Why.** Saturday's worst failure (section 8) was a stopped desk nobody restarted.
- **Evidence.** PRs #34, #66, #79, #80, #81, #82, #93, #94, #95, #98.

### I8 · Analyst on duty: an agent that reads every Market Test and duel wave as it lands (Sunday)
- **What.** A Claude session on the VM (`docs/plans/sunday-analyst.md`, PRs #71, #91, #99) that wakes on each event, writes `logs/analyst/LATEST.md`, opens one PR per proposal and posts five lines on the bus, with a `deployed_check` that compares the running bot's `run_start` line against the parameter file before recommending anything (it caught that Saturday's duellist ran with flags that differed from its file).

### I9 · Dealer bots with a value gate (Friday to Sunday)
- **What.** `agent/abuela.py`, `agent/chato.py` (also Doña Pilar, Los Pícaros, Don Ernesto), `agent/dealer_client.py`. Each haggles with a measured opening, step and patience per dealer (`docs/analysis-friday/dealers.md`; 26 public Chato buys analysed), and the client clips every buy limit to floor(book × our multiplier) and every sell floor to the value of the copy given up, refuses a `--cap` or `--floor` on the wrong side, and re-prices from a fresh `/api/me` before every priced message (other bots trade the same cards mid-thread).
- **Why.** Measured Saturday 13:15: a dealer deal on the wrong side of our value scores **zero** on the ladder (`docs/analysis-friday/score.md` §4a). Section 7.
- **Evidence.** PRs #28, #35, #38, #69, #83; `docs/plans/ladder-sunday.md`.

### I10 · Market desk, key lease and card-for-card swaps
- **What.** `agent/market_desk.py` evaluates every offer addressed to us or posted on El Rastro against our values, with hourly and daily caps, a protected list (never the only copy of a page card), a STOP file, and a one-accept-per-tick lease (`agent/lease.py`) shared with the duellist via `duel.lock`. Sunday's page-completion mode (PR #70) bought the last card of a page from another team under a budget that discounts open commitments.
- **Evidence.** PRs #6, #11, #12, #70, #88.

### I11 · Offline evals for all four agent families (Saturday night)
- **What.** `tools/eval_common.py` and `tools/eval_{duels,dealers,market,broker}.py`, flows under `evals/`, all keyless, scoring by program. The broker eval ran 8,000 sessions per scenario against simulated traders fitted to the five recorded Market Test sessions, with the decision rule written **before** the runs (`docs/plans/market-test-sunday.md`).
- **Evidence.** PRs #62, #65, #75.

### I12 · Public feed recorder and findings (Friday)
- **What.** `tools/feed_recorder.py` + `tools/feed_report.py`: two independent recorders (Mac and VM), merged gap-free; `docs/findings.md` and `docs/analysis-friday/` hold every inference we drew from the 40,919 public events, with the scripts that produced each table.
- **Evidence.** PRs #1, #2, #4, #60, #61.

---

## 5. How we worked (Craft)

### C1 · Two engines, adversarial by construction
Claude implemented; **OpenAI Codex (GPT-6.1 Sol)** reviewed every non-trivial PR on the exact head with a written verdict (`SHIP | SHIP WITH FIXES | BLOCK | STALE`), running the tests against `main`'s baseline and reproducing defects before naming them. Merges only on SHIP or SHIP WITH FIXES with no MAJOR left (Thiago's rule, `CLAUDE.md`). Sunday: a review-and-fix circuit on the VM (`~/bin/bazaar-pr review|fix`) so no human had to be the reviewer on the last day (`docs/plans/sunday-night-handoff.md`).
- Real BLOCKs, all fixed before merge: #42 ledger (4 rounds), #96 Clearing House (5 rounds), #66 factory (2 rounds, 10 findings in round 1), #72 duels (reviewer reproduced a slow-server race through the real client; feature F4 switched off even though the arena said +0.0083 ± 0.0007 a duel: `docs/duel-lab/duels3-params.md`, test `SundaySlowServer`).

### C2 · Mutation-first tests
No guard enters a PR without a test that fails when the guard is removed; PR bodies carry the mutation matrix (#63: 6 of 6, #65: 8 of 8). 1,709 test functions in 84 files, 23,651 lines of tests for 38,072 lines of agent and tool code. The Saturday-night test baseline was recorded with its known failures named (5 of 937, then 3 of 1,556), never hidden.

### C3 · Decide the rule before the run
The Market Test policy bet ("more pairs per tick beats stall") was written as a decision rule first, then tested: it lost by eleven standard errors on the hard test and in refit simulations; the simple rule stayed (`docs/plans/market-test-sunday.md`). Both overnight searches (about 2,100 duel candidates, 6,600 broker policies) ended with the honest verdict "not better than the incumbent on held-out test"; nothing was deployed and the pitch said so (`docs/duel-lab/duels3-search/leaderboard.md`, `evals/broker-search/`, PRs #76, #77, #78).

### C4 · No model in the money path, and keyless by default
Every tool that another team or a judge could see runs without the team key. Only the Mini holds it; Hector's VM copy was shredded Saturday 11:17 once the single-source-of-truth decision was taken (`docs/plans/HANDOFF.md`; session notes). `tools/redaction.py` scrubs credentials from everything logged or posted; the pitch tooling has a `--stage` flag that drops team ids and a 5-second deadline so nothing could hang or leak on screen (`docs/judges/judges-evidence_v3.md`, "Never on screen").

### C5 · A trading-firm shape for the sessions
A conductor session (Opus) directing lanes; a PR steward session; ephemeral reviewers; overnight analysts; an analyst on duty on Sunday; every session signed on the bus. The night of Saturday to Sunday (Thiago out of quota until 07:00, Jay ill): Hector plus one orchestrating Fable session ran seven work packages in parallel across the Mac and the VM and merged **fourteen PRs between 01:30 and 04:52** (#62 #65 #63 #69 #72 #64 #67 #70 #68 #71 #57 #73 #74 #66), each through Codex review, then handed Thiago a 894-word "Read this first" and a 13-check pre-flight (`docs/plans/sunday-night-handoff.md`, `docs/plans/sunday-preflight.md`). The previous night (Friday 02:30 to 04:00) produced PRs #4 to #9 and the Saturday runbook (`docs/plans/saturday-runbook.md`).

### C6 · The truth test for the pitch
`tools/pitch_numbers.py` prints VERSION A, B-UNCONFIRMED or B from the recorded feed and the public leaderboard, and the script had one paragraph per version, so the team could not accidentally claim a network trade that the organisers' own server would contradict (`docs/judges/judges-story_v3.md` §0).

### C7 · Privacy and fair play as engineering constraints
Clearing House follow-up #103 after two disclosures were found in review (a zero-surplus price row revealing two reservation prices by inference; a brute-forceable unsalted commitment hash). Hector's standing rules: no reciprocal pacts, no messages that imitate the organisers, no injection bait, no accepting offers addressed to us on rival venues (a tactic that boosts the rival's market score). We declined a competitor-facing "probe" of pairing limits because it could have looked like an attack on third parties, and asked the organisers instead (`docs/findings.md`, "Open questions for the organisers").

### C8 · Everything documented as it happened
56 Markdown documents: Friday analyses with their scripts, plans with gates, two night handoffs, the judges' story in three versions with a "do not say" list and a screen-by-screen safety tag (SAFE / MASK / NEVER), and this dossier.

---

## 6. Negotiation, in detail

**Duels (40.19 duel points).** 202 duels, 163 deals, surplus 4,446 over the two live days. Patterns measured and acted on: Duels I (Saturday 11:26): 31 duels, 25 deals, our share of the pie 21.2 %, with the finding that we accepted with 1 to 3 ticks of margin while rivals were still conceding (16 of 21) and that 5 silent rivals ended at 0; both fed the Duels II parameters (`docs/duel-lab/duels2-params.md`). Duels II: 57 of 68. Duels III and the Grand Final: 80 of 102 under 12-tick duels, decay 0.10, four at once, with the robust two-topic rule and F4 off (`docs/duel-lab/duels3-params.md`).

**Team trades (136.5 neg points).** Four pages closed by buying the last card from another team: La Latina (LAT-09 from t16, 88 P, Saturday tick 724), Lavapiés (LAV-09 from Los Pícaros and LAV-10 from t07, tick 844), Salamanca (SAL-10 from t13, 108 P, Sunday 09:35, tick 1528), and El Retiro (RET-07, the closer, bought from a team on El Rastro at about 30 P, Sunday 13:20: neg points 86.5 → 136.5, rank 5 → 4; bus 13:20 and 13:30). Scoring rule measured on our own trades by Thiago's planning session (bus, 11:42): a team trade scores private value minus price, page bonus included, **capped at 50 per trade**; SAL-10 at 108 against a value of 177 with the page bonus = +50 exactly. Page bonus confirmed on the board: a page completed by a team trade moved it +1.6 to +4.7 (our LAT-09: +3.10); one completed by a dealer buy did not (`docs/findings.md`, "Sunday 01:30, ladder value measured"). Plus three correct bait-and-switch flags against Los Pícaros, +30 (I4b).

**Dealer ladder (0.371).** Small by design: after the first three deals per dealer the measured marginal effect is about zero (same section), so the bots stopped spending deals on it and the value gate stopped us from ever selling below value again after Saturday 13:15.

**From 16th to 4th.** Saturday 12:26: rank 16 (18.81). The diagnosis that day (`docs/strategy/strategy_win-plan_v1.md`, PR #29 red-team corrections, session analysis) found the levers: trade with teams not dealers, never below value, complete pages with team buys, keep the market desk alive. Saturday 18:25: rank 4 (29.64). Saturday close: 5th (29.81). Sunday freeze: 4th (34.19), first in Negotiating.

---

## 7. What we discovered about the game (all from public data, reproducible)

- **The leaderboard is relative and the ladder tops out:** with dealers alone the leader was capped near 12.5; team trades move the board (t10 8.3 → 29.1 on one sale, Friday tick 40). `docs/findings.md`.
- **Value gate on the ladder:** a dealer deal on the wrong side of our private value scores zero (LAT-06 sold at 28 with value 27.5 → +0). `docs/analysis-friday/score.md` §4a.
- **Market formula that fits:** market = 7.5 × (our mean bench efficiency ÷ the free stall's) + value created by other teams' trades on our venue; fits 3.61, 5.46 and 5.86 readings. `docs/plans/market-test-sunday.md`, session analysis.
- **Dealer behaviour measured:** Abuela's welcome price, open/close ranges, patience by step size; Chato's 1-by-1 vs 2-4 step outcomes on rares; Pilar's +1 per round. `docs/analysis-friday/dealers.md`, `docs/findings.md`.
- **Duel server model:** payoff = surplus × 0.92^rounds; seller earns +w per delivery day from day 0. Confirmed on three server results, patched live (#54).
- **Census and pseudonyms:** `/api/cards/{id}` hides other teams' owners ("a team"); venue pseudonyms are stable per team per venue, so rival decks are inferred from the feed with validated precision 1.00 / recall 0.70 against our own holdings (#73).
- **Easter egg chain decoded** from the catalogue and the feed (La Chulapa Dorada → Abuela → Don Ernesto); it does not score, we took the free badge ("Sharp ear") and spent nothing chasing the rest. Gifts correlate with conversation volume, not tricks.
- **Fees:** the acceptor pays ceil(5 %)+1 per card; eight swaps in the public feed had a fee nobody was charged for until the ledger fix (#42).
- **Team-trade scoring:** private value minus price, page bonus included, capped at 50 per trade (exact on SAL-10 and MAL-07; bus 11:42). Hence the Sunday plan: one page closer per hour beats ten small deals.
- **Dealer deceit pays if you catch it:** Los Pícaros' bait-and-switch flag is worth +10 per correct flag, capped at three (I4b).
- **Closing a venue after a good session keeps nothing** (`kit/RULES.md` line 81, re-read at 13:08 when the conductor was about to close v20 for 250 P of liquidity; v20 stayed open to the freeze).

---

## 8. Failures, stated plainly, and what each one changed

1. **Saturday 10:22, the market desk stopped and nobody restarted it.** From midday to evening another team addressed us twelve offers for the one card that would close a page; no bot of ours read them. → The factory with keepers and a watchdog (#34, #66), the swarm view's freshness lines (#48), the analyst on duty (#71).
2. **Saturday 11:50, Market Test session scored 0** because the broker's `same_maker` filter dropped all 15 crosses. → Fixed at 12:05 (#22); broker safety net and `bench_alarm` so a session can never score 0 again (#44).
3. **La Celestina got offers but no settlement between other teams.** → We said so in the pitch (version B) instead of stretching it, and built the Clearing House as the next idea.
4. **The Clearing House matched zero trades.** Correct behaviour, wrong guest list (we invited the teams like us and excluded the heterogeneous leaders out of fairness); recorded with the export (`docs/judges/clearing-house.md`, section 1b).
5. **Two privacy disclosures in the Clearing House status page**, found in review within the hour, fixed in #103.
6. **The inference misreads page-completion buys as preference** (it ranked our sets wrong at tick 961). Recorded, not hidden (#61).
7. **A dealer bot bought two cards above our value on Saturday** because a limit was mis-set. → Limits clipped in code, wrong-side caps refused (#69), with mutation tests.
8. **Both overnight searches found nothing better.** Reported as "not better"; incumbents kept (#76, #77, #78).

---

## 9. Timeline

| When (Madrid) | What |
|---|---|
| Fri 2 Oct, 20:20 to 23:00 | Game starts late. Feed recorder and report (#1); shared CLAUDE.md and first findings (#2). Dealer behaviour and leaderboard mechanics inferred from ticks 0 to 65. |
| Fri 23:00 to Sat 04:00 | Market brain: inference, ledger, plan, live page on the VM (#3, #5). Weekend plan with eight workstreams and gates (#4). Key lease and shadow market desk (#6), broker and bench simulator (#7), duel arena and Duels I params (#9, #10). Saturday runbook. |
| Sat 09:00 to 13:30 | Decision: one source of truth, the Mini runs everything with the key; VM key shredded. Venue v20 "La Celestina" opened (10:23). Duels I (31 duels). Rank 16 diagnosis at 12:26; win plan v1 (#23) and red-team (#29). Silver pack opened; MAL-10 sold at 74. La Celestina public page (#27). |
| Sat 13:30 to 19:00 | Duels II params after three review rounds (#33). Pilar bot (#28). Value-gate finding (13:15). Pages: LAT-09 (tick 724), LAV-09/LAV-10 (tick 796–844). Rank 4 at 18:25. Thiago and Hector re-plan (plan v2.1): bots decide on data within hard code limits. |
| Sat 19:00 to 00:00 | Ledger for every team (#42, 4 review rounds), brain with our real data (#43), market diagnosis and announcer with safety net (#44, #45, #49), bus signing (#46), Duels II arena (#47), swarm view (#48), Duels II: 57 of 68. Server day-model fix (#54). Evals for four agents (#62 prepared). Close: 5th, 29.81. |
| Sun 01:30 to 08:45 | Night orchestration: 14 PRs merged through Codex review (#62 … #66), Duels III referee and params (#72), Open Bazaar matchmaker (#67, #73, #74), page-completion desk (#70), analyst kit (#71), pitch v3 (#68), factory config and pre-flight (#66). Two overnight searches → "not better". Handoff to Thiago at 07:00; analyst on duty launched 08:44. |
| Sun 08:55 to 15:00 | Factory up on the Mini (08:55). SAL-10 bought from t13 (09:35), Salamanca complete. Hard Market Test (7 crosses, 85 %). Clearing House: idea 10:50, PR 11:07, live ~11:18, first team in 12:2x, six teams by 13:13, round held 13:33, stopped 13:43 (#96, #101, #102, #103). Three Pícaros bait-and-switch flags (+30) by 12:47. El Retiro completed by a team buy (13:20): rank 5 → 4. Duels III and Grand Final: 80 of 102. PR guard circuit on the VM. Freeze 14:59: **4th overall, 1st in Negotiating.** |

---

## 10. Index: where everything is

**Judges' material:** `docs/judges/` (this dossier; `judges-story_v3.md`; `judges-evidence_v3.md`; `judges-rehearsal_v3.md`; `clearing-house.md`; `clearing-house-status.json`).
**Findings and analyses:** `docs/findings.md`; `docs/analysis-friday/{dealers,duels,rastro,score}.md` with their `*_scripts/`.
**Plans and handoffs:** `docs/plans/HANDOFF.md`, `saturday-runbook.md`, `sunday-night-handoff.md`, `sunday-preflight.md`, `sunday-runbook.md`, `market-test-sunday.md`, `ladder-sunday.md`, `matchmaker-sunday.md`, `pages-sunday.md`, `sunday-analyst.md`, `staff-brief-sunday.md` (organisers' Sunday brief, transcribed).
**Duel lab:** `docs/duel-lab/` (duel book, params for each wave, matrices, overnight search leaderboard and narrative).
**Strategy:** `docs/strategy/strategy_win-plan_v1.md`.
**Agents (deterministic, keyed, run only on the Mini):** `agent/{duel,broker,abuela,chato,market_desk,dealer_client,lease,rastro_seller}.py`.
**Tools (keyless):** `tools/{value_inference,ledger,market_plan,brain,feed_recorder,feed_report,announce,matchmaker,outreach,celestina,clearing,clearing_client,swarm,bus,factory,logs_push,pitch_numbers,redaction,decks,snapshot,duel_arena,duel_tune,duel_matrix,eval_*}.py`.
**Evals:** `evals/{duels-arena,dealers,market-desk,broker,broker-search}/`.
**Tests:** `tests/` (84 files, 1,709 tests; `python3 -m unittest discover tests`).
**Live logs:** branch `mini/logs`.
**Pull requests:** #1 to #104 on `thiagoamaro91/negotiation-agent`; 99 merged, each with its review thread.
**Team bus:** issue #25.
