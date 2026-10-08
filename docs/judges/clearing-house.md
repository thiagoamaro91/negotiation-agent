# The Clearing House: six teams, one private order book, zero bad trades

**Sunday 4 October 2026, 10:50 to 13:45 (Madrid). Built, reviewed, deployed and run in under three hours.**
Sources: PRs #96, #101 and this one; `docs/judges/clearing-house-status.json`, an operator export of the live
server's state with every price removed; the team bus (issue #25). Times without a PR or export behind them are
the operator's recollection and are marked so.

## What it is

A private clearing house between teams, run by our team and open to any invited team. Each team hands in, in
private, the cards it would sell with the least it takes and the cards it wants with the most it pays. On a run
a greedy matcher takes same-card pairs where a buyer's max covers a seller's min, prices at the midpoint of
[seller min, buyer max minus the venue fee] (so a cross can have zero surplus when the two numbers meet), and
assigns venues: it tries to give every participant's venue one trade (never a venue owned by one of the two
sides), then sends the rest to the venue with the least value hosted today. A round is held when some
participant's venue would host nothing, unless the operator forces it or a deadline passes; one copy serves one
buyer, so coverage is a goal, not a guarantee. A run is only a proposal: every team in it reads its own actions
and signs OK with a SHA-256 of exactly what it read; a NOT OK vetoes those pairs and the matcher proposes again.
Only with every OK does anything execute, and it is each team's own client that executes, on its own laptop,
with its own key.

- Server: `tools/clearing.py` (keyless; join by invite code, book, propose, vote, plan, report, status with a
  public allocation ledger and a per-team reliability record).
- Client: `tools/clearing_client.py` (one file, standard library). `book` reads the team's cards and private
  values from the game and sends only card, copy id and reservation price; it keeps a local copy. `execute`
  posts a sell only if the server's offer body gives exactly one of the team's own listed copies, for plain
  cash, at or above the min the team itself stored, addressed to the buyer the plan names (the seller's current
  value is not re-read). It accepts a buy only after finding the seller's offer in the game's public feed
  (maker, addressed to this team, venue, one copy of that card, cash only, open, unexpired), and only if the
  debit (price plus the venue's live fee, any announced change included) is at or below the max the team stored,
  at or below the card's current marginal value re-read from the game, within the quantity it asked for, and
  leaves its cash above a private cash reserve. Equality is allowed on every bound. The server is never
  trusted: the client acts only on actions it signed itself.
- Agent-readable onboarding at `/agents.md`; the server serves its own source for audit; both files are also a
  public gist. Invite codes are the only gate and were handed out in person.

## What happened

| time (Madrid) | event | source |
|---|---|---|
| 10:50 | Hector's idea: teams with few trades pool their spares privately and get trades on every venue | operator |
| 11:07 | PR #96 opened: server, client, selftest | GitHub |
| ~11:18 | live behind a tunnel on Hector's laptop; invitation message and a bilingual visual explainer to teams | operator |
| 11:30 to 13:05 | rules added as Hector sharpened the contract: a round for everyone or no round; balance by value hosted; proposal and OK / NOT OK with reasons; signed commitments; invite codes per team | PR #96 history |
| 12:2x to 13:13 | six teams join: t13, t07, t16, t15, our team (from the Mini), t14 | operator recollection (join times and order); status export (membership only) |
| ~12:44 | Team 7 hits a parser trap in the published join command; fixed. Team 13 reports that addressed offers never show on a venue's public book, so the hardened buyer could never verify one; fixed against the public feed | PR #96 commits, operator |
| 11:07 to 13:07 | five adversarial review rounds by Codex (Sol) on PR #96; the proven money-safety blockers were fixed on the live code; merged 13:07 | GitHub, review logs |
| 13:08 to 13:17 | follow-up PR #101 (feed state: cancellations, expiry) merged "ship with fixes": two lost-trade recovery defects remain open, neither spends money | GitHub, review log |
| 12:10 | round 1, scheduled: no active books, nothing proposed | status export |
| 13:33 | operator run with five books: **held, zero crosses** (no buyer max reached any seller min) | operator recollection (the held attempt is overwritten in the export by the later one) |
| 13:36 to 13:41 | two teams re-send books with no margin | status export (book timestamps) |
| 13:42 | operator-forced run: one zero-surplus candidate between two teams, both clients auto-approved it (votes in the export), and the **seller's own client refused to post** because the proposed price was below the min it had stored locally (export: trade `failed: client refused`, no offer posted). Server stopped at ~13:43 | status export, operator |

Six of the eighteen teams joined, five with books (export: per-team venues, book counts and timestamps). At
export, after round 2's approval consumed the matched copy and want: 26 copies for sale, 151 wanted, 40 same-card
pairs, 0 with a buyer max at or above a seller min. Trades executed by the clearing house: 0 (export: the only
approved trade failed before any offer was posted). Cash moved and keys shared: 0 by construction (the server
holds no key and the only trade never reached the game), as operator statements.

A disclosure we got wrong: while the server was up, its public status page listed every proposed trade with its
price, including the unexecuted zero-surplus one; for a zero-surplus cross that price equals both sides'
reservation prices. Reservation prices were never served as such, but that row disclosed two of them by
inference. The unsalted commitment hash was also brute-forceable from a status export (found by Codex in review
of this document; removed from the export). Both are fixed in the follow-up PR: ledger rows are public only once
settled (settled trades are public in the game anyway) and commitments carry a per-round nonce.

## Why zero trades is the right answer

In no same-card pair did the buyer's max reach the seller's min (export). Our reading, operator recollection of
the cards on offer: the teams that joined had the same neighbourhoods to spare (commons of Chamberí, Malasaña,
Salamanca) and did not value them; what they wanted, nobody in the group would sell. The teams that joined were
the teams like us: lower in the table, same cards left over. Liquidity needs heterogeneity; the heterogeneous
teams (the leaders, who value other neighbourhoods) were the ones we chose not to invite.

The system promised not to invent trades and never to let a client act outside its own stored numbers. It kept
that promise twice: the matcher held the 13:33 round, and when a forced run produced a zero-surplus candidate,
the seller's own client, checking against its own local book, refused it (export). In a game whose fair-play rule voids deals
where one team feeds another, a clearing house that answers "there is no value to share" is the correct
behaviour.

## What we would do with one more hour

Start at 10:00, not 12:30. Invite the heterogeneous teams. Add card-for-card swaps and three-way cycles, which
is where most of the surplus between similar teams hides. Close the two open recovery defects from #101.

## Credits

Idea and every product decision: Hector. Code, reviews and deployment: Claude (this session) with Codex (Sol)
as the independent reviewer across five rounds on #96 and one on #101; two live defects reported by Team 7 and
Team 13. Our team joined from the Mini through Thiago's sessions on the bus.
