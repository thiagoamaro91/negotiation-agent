# The Clearing House: six teams, one private order book, zero bad trades

**Sunday 4 October 2026, 10:50 to 13:45. Built, reviewed, deployed and run in under three hours.**

## What it is

A private clearing house between teams, run by Team 3 and open to any invited team. Each team hands in, in
private, the cards it would sell with the least it takes and the cards it wants with the most it pays. At a set
time a matcher crosses every pair where a buyer's max covers a seller's min, prices at the midpoint (each side
keeps half the gap), and spreads the trades over the participants' venues: coverage first (every participant's
venue gets a trade, never one owned by one of its two sides), then the venue with the least value hosted today.
A round is only a proposal: every team in it reads its own actions and signs OK with a SHA-256 of exactly what it
read; a NOT OK vetoes those pairs and the matcher proposes again. Only with every OK does anything execute, and
it is each team's own client that executes, on its own laptop, with its own key.

- Server: `tools/clearing.py` (keyless; join by invite code, book, propose, vote, plan, report, status with a
  public allocation ledger and a per-team reliability record).
- Client: `tools/clearing_client.py` (one file, standard library). `book` reads the team's cards and private
  values from the game and sends only card, copy id and reservation price. `execute` posts a sell only if the
  offer body gives exactly one of the team's own listed copies, for plain cash, at or above its own min, addressed
  to the named buyer; it accepts a buy only after finding the seller's offer in the game's public feed (maker, to,
  venue, one copy of that card, cash only, open, unexpired), re-reading the card's current value, the venue's live
  fee including pending changes, and its own cash reserve. The server is never trusted.
- Agent-readable onboarding at `/agents.md`; the server serves its own source for audit; both files are also a
  public gist. Invite codes are the only gate and were handed out in person.

## What happened

| time | event |
|---|---|
| 10:50 | Hector's idea: teams with few trades pool their spares privately and get guaranteed trades on every venue |
| 11:10 | PR #96 opened: server, client, selftest |
| 11:18 | live behind a tunnel on Hector's laptop; invitation message and visual explainer (bilingual) to teams |
| 11:30 to 13:05 | rule changes as Hector sharpened the contract: a round for everyone or no round; balance by value hosted; proposal and OK / NOT OK with reasons; signed commitments; invite codes per team |
| 12:2x | Team 13 joins, first external team; within the hour Teams 7, 15, 16, 14 and Team 3 itself (from the Mini) |
| 12:44 | Team 13 reports that the hardened client could never see addressed offers on a venue's public book; fixed in minutes against the public feed. Team 7 reports a parser trap in the published join command; fixed |
| 11:50 to 13:30 | five adversarial review rounds by Codex (Sol) on PR #96, every finding fixed on the live code within minutes; merged at 13:0x; follow-up PR #101 merged at 13:2x |
| 13:33 | first round, 5 teams with books, 30 cards for sale, 160 wanted: **held, zero crosses** |
| 13:42 | books re-sent with no margin: one cross (SAL-01, 4 P, surplus 0). Hector stops the system before any vote |

Six of the eighteen teams joined: a third of the market organised under one private book in an afternoon.
Cash spent by the clearing house: 0. Trades executed: 0. Trades at a loss, gifts between teams, keys shared: 0.

## Why zero trades is the right answer

The matcher looked at 51 seller-buyer pairs on the same card. In none did the buyer's max reach the seller's
min. Everyone had the same cards to spare (commons of Chamberí, Malasaña, Salamanca) and nobody valued them;
what everyone wanted (Lavapiés and Salamanca rares, Latina rares) nobody would sell, because its holders value
it too. The teams that joined were the teams like us: lower in the table, same neighbourhoods left over.
Liquidity needs heterogeneity; the heterogeneous teams (the leaders, who value other neighbourhoods) were the
ones we chose not to invite.

The system promised not to invent trades and not to move money unless both sides gained at their own private
values. It kept that promise. In a game whose fair-play rule voids deals where one team feeds another, a matcher
that answers "there is no value to share" is the correct behaviour, and the 13:42 forced round shows the floor:
the best legitimate cross in the whole book was worth 0 P of surplus.

## What we would do with one more hour

Start at 10:00, not 12:30. Invite the heterogeneous teams. Let `book` list the whole album at value (it already
lists duplicates, non-collected sets and valued page cards). Add card-for-card swaps and three-way cycles, which
is where most of the surplus between similar teams hides.

## Credits

Idea and every product decision: Hector. Code, reviews and deployment: Claude (this session) with Codex (Sol)
as the independent reviewer across five rounds; two live defects found by Team 13 and Team 7. Team 3 joined from
the Mini through Thiago's sessions on the bus.
