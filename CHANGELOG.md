# Changelog

## [2026-10-03] Card census

### Added
- `tools/census.py`: an exact card census from `GET /api/cards/{id}`, read only. `run` walks every asset id from 1 at 1 request/s (`--rate`, single-threaded) and stops after 60 consecutive 404s above the highest id found and above `--expect-max` (`--max-id 3000` hard cap, exit 4 if reached without that run). The snapshot `cards-<date>-t<tick>.json` has meta (wall times, ticks at start and end, ids walked, 404s, errors), `cards` {id, ref, name, rarity, set, serial, owner}, `packs`, `teams` {team: {cards, by_ref}} and `other_owners` (dealers, no owner); history only with `--with-history`, in its own file. `ids 12,57` / `--ids-file` re-read only those ids and merge into `--base` (moved, added, removed in meta). `summary` prints every team's deck by set. `selftest` walks a fake server offline.
- The route needs a key (401 `bad_key` keyless, checked 22:13): the first keyless 401/403 switches the run to the team key (`BAZAAR_KEY` or `.env`, `X-Team-Key`), once per run; a refused key stops the run (exit 5). The key is never printed or written, every error text goes through `tools/redaction.py`, and the loaded key is replaced literally whatever its shape.
- 429, 5xx and network errors retry the same id with exponential backoff (Retry-After honoured, 60 s cap); after `--max-retries` the id goes into `errors` and `--resume` reads it again; 10 ids failing in a row stop the run. Progress goes line by line to `cards-<date>-partial.jsonl` (scrubbed raw payloads), so `--resume` continues a stopped walk (also past midnight) or rebuilds the snapshot with no request.
- Market Test silence: `--quiet` windows pause before every request; at start the clock is read, and with the doors open the schedule and the feed place the Market Tests as `tools/announce.py` does: no start inside one or when that status cannot be read (exit 3, `--skip-market-check` overrides), and a pause for the ones ahead.
- `tests/test_census.py`: 31 offline tests (end of the id space and the `--expect-max` anchor, 429/5xx backoff, failed ids kept and retried on resume, resume after midnight, re-finalize with no request, top-up merge, per-team summary and totals, history file, key fallback once per run and never shown, redaction of errors and payloads, the Market Test start check, quiet windows, selftest).

### Fixed (Codex review of #57 at a950079: 3 MAJORs, all Market Test silence)
- Stale clock: with the doors open the clock is read again after the feed, and every window is placed from that read and its sampling time, so a retried schedule or feed request (a 503 with Retry-After 180) can no longer leave an old tick that drops a Market Test the feed shows; a `bench.started` above the clock's tick is kept, never dropped.
- No refresh: the status (clock, schedule, and feed with the doors open) is read again every 2 min before the next card request, card retries included; with the doors closed the run stops 2 min before the next opening (exit 3, resume once the doors are open), and a refresh that fails stops the run (exit 3, progress kept).
- Requests before the gate: local evidence comes first with no request at all: a start inside a window cached by the previous run (`<out>/census-status.json`, written at every status read, Sunday's sessions placed from the schedule's `day_opens` wall time) is refused, and the `--quiet` windows hold every request.
- New `--until HH:MM`: hard stop at that local time, the partial file kept, exit 6; `--resume` continues.
- `tests/test_census.py`: 38 tests, with a fake-clock test for each finding (all fail on a950079) and tests asserting zero requests of any kind inside a silence.

## [2026-10-03] Dashboard: Rivals and Market panels

### Added
- `tools/dashboard.py` + `tools/dashboard.html`: a Rivals panel with all 18 teams from public data only, in a sortable table (rank, score with a negotiating / market split bar, level and unlocked dealers, cash rebuilt by `tools/ledger.py` with a sparkline, album and pages, known cards as a lower bound, inferred favourite and least liked set from `tools/value_inference.py`, deals, trades, venue). Click a row to see the known cards by set, a heat strip of the inferred multipliers, the rarest card and the last 8 cash moves. Below the table: cash vs score (one dot per team, ours in gold) and "who wants what" (per set, which of the other 17 teams favour it or like it least). A Market panel lists every venue (owner, mechanism, fee, trades, volume, fees, traders) and the 15 most traded cards between teams (count, last, median, range). A trust line compares our rebuilt cash with `/api/me`; past 10 P the cash column greys out.
- The panels run in their own thread: `/api/leaderboard` and `/api/venues` read keylessly every 15 s, and the feed tools rerun only when `feed.jsonl` changed, at most every 20 s. A failed source keeps its last good value and shows its error, so a broken feed never blanks the other panels. New `--feed DIR` (or `BAZAAR_FEED`); default `<broker root>/logs/feed`.
- Privacy: the block is built from an allowlist. Our row carries the leaderboard and our rebuilt cash only (no inferred multipliers, known cards or moves), "who wants what" never counts us, and nothing reads `logs/state/me*.json`.
- `tools/deploy_mini.sh` also ships `tools/ledger.py`, `tools/value_inference.py`, `tools/price_index.py` and `logs/feed-vm/feed.jsonl` (the ledger's Friday gap source), and creates `logs/public/`.
- `tests/test_dashboard_rivals.py`: 12 tests (18 rows, nothing private in our row or anywhere in the block, who-wants-what skips us and weak signals, trust states, partial feed line, an exception or `SystemExit` stays in the rivals block, a bad feed keeps the last good result; one end-to-end test runs when `BAZAAR_FEED` is set).

### Fixed
- `tools/dashboard.html` at phone width: panels, duel cards and status pills no longer push the page sideways.

## [2026-10-03] Ledger: Saturday cash

### Fixed
- `tools/ledger.py` rebuilds every team's cash on Saturday's feed again (Team 3 was 350 P short at tick 630, 14 of 18 teams below zero): the free starter stalls of tick 201 (`bond: 0`, `starter: true`) no longer cost 270 P; the Saturday allowance (150 P, fired at tick 165 with no cash field and gone from the schedule) is read from its note; Friday's recording hole (ticks 49-118) is filled by id from `logs/feed-vm`. Also pays bond refunds on `venue.closed` and fees charged on a team venue to its owner (new keys `refunds`, `fees_earned`; neither has happened yet), counts every card of a multi-card dealer lot, and `--json` adds `check_history` (rebuilt vs every row of `score.jsonl`) and `gaps`. Team 3 now matches its real cash at all 10 snapshots from tick 33 to 630, and no team is below zero.
- `tests/test_ledger_saturday.py`: 12 tests (starter stall, replaced stall, refund, fee earned, grant from note and from schedule, hole fill and no fill, the committed feed against every snapshot, no negative cash); 9 fail on the old ledger.

## [2026-10-03] Sunday factory

### Added
- `tools/factory.py`: one command starts Sunday's bots in order and keeps them up. `plan` (read-only, keyless) prints the clock, every schedule event in Madrid wall time, each process's exact command and gate, and any copy already running outside the factory. `up --yes` claims each process on the bus and opens one tmux window per process, each running a restart loop that waits for its gates (doors open, clock running, no fresh duel lock, no duel wave within 12 min, after the allowance) evaluated in game hours, so a pause only delays it. Duel runs start 10 min before each duel wave, with `--duel-ticks` from the schedule and `--until` from the closing time. Dealer steps run once each, and a step that lived through a pause is rerun. `status` shows one line per process (running, log age, restarts, last Market Test matched and dropped) and exits 1 on a required process down or stale, a crash, or a dropped or missing match; `--notify` runs a configured command, `--every 60` makes it the watchdog.
- `tools/factory_sunday.json`: the Sunday processes as data (feed recorder, broker, duel, Abuela, Chato, Pilar, the watchdog; Rastro seller and market desk off), with a `todo` on every value that waits for an open pull request or an 08:55 decision.
- `docs/plans/sunday-runbook.md`: the operator page (08:55 command, 09:00 check, timeline in game hours, one action per alert, decisions that stay with people).
- `tests/test_factory.py`: 21 tests (wall time at 15, 30 and 60 s ticks and across a pause or the overnight gap, gates, rendering the real config, staleness, the Market Test watch, double starts); 19 mutations, all caught.

### Fixed (adversarial review of #34)
- One keeper per process: a lock file held for the keeper's life; every launch, restarts included, checks gates, the duel wave, input files and outside copies (python, `python -m`, or a shell restart loop).
- The bus claim fails closed (`up --yes --no-bus` is the explicit override); doors-open and clock-running gates default on, so the broker and duel runs wait out a pause too.
- A dealer step that exits non-zero is not relaunched: the keeper stops and `status` reports it (needs the dealer exit statuses and pause-safe waits of #35).
- A duel wave projected outside opening hours never launches; `up` refuses a process with a missing input file.
- Shared schedule cache: unique temp files and a tolerant read-merge-write; a failed save no longer kills a keeper.
- `status` checks the child pid and its command line, says NO CHILD or WAITING instead of trusting the saved label, fails a log that never appears, counts only matches of the bench run's own offers, and alerts on a scheduled Market Test never seen on our book.
- Bots get an allowlisted environment with no key in it.
- 21 more tests driving `up`, `keep`, `status` and the cache with the OS and network mocked; each failed on the reviewed head; 21 more mutations, all caught.

### Changed (second review of #34: less surface)
- The dealer entries are off by default (pull request #35 first); `up` prints every `off` entry with its reason and `plan` prints the dealers' manual command lines.
- The process scanner decides from argv strings only and never opens a file (it used to read script files, which could include `.env`); it matches the script basename plus the mode token in any path form, `-m`, `--x=y`, or a `bash -c` loop.
- `up` reads the bus board and refuses a process claimed on another machine; an unreadable board fails closed.
- A dealer step is done only on a deal or a nothing-to-do line in its log; exit 0 without one is retried at the next open gate, `max_attempts` times (default 3), then reported.
- A missing input file stops the keeper as a reported failure; `"enabled": false` stops a keeper before its next launch, and `status` reports a disabled entry that still runs.
- The duel bot is checked for freshness while a scheduled wave is live; gates need explicit `doors` and `paused` values; notifications are deduplicated per incident.
- 17 tests added or changed (14 failed on 21c5efa, 3 are controls); 16 more mutations, all caught.

## [2026-10-03] Dealer bots: post-merge audit of #35 (afternoon)

### Fixed
- `agent/chato.py`, `agent/abuela.py`: the printed `--resume` command carries every limit and override of the run (`--cap`, `--reserve`, `--floor`, `--sell-anchor`, `--sell-step`, `--anchor`, `--step`, `--max-bid`, `--max-rounds`, `--max-defer-ticks`, `--dealer`, `--allow-single`, `--only`); following the old line could take an 80 the operator had capped at 50.
- Both bots: an accept whose settlement cannot be confirmed (thread unreadable, or no confirmed tick) is `unsettled`: the plan stops with exit 6 and one line naming the thread, instead of counting nothing and starting more trades.
- `agent/dealer_client.py`: `Rounds.wait` blocks until a tick is confirmed, so no decision or write follows an unconfirmed wait (no same-tick resend while the game is frozen, the max-bid stall counts ticks); after 5 unconfirmed waits in a row the thread is closed (`clock_lost`, exit 7, or exit 4 with the resume line if the close fails).
- Both bots: the status line (exits 3 to 7) is printed before the final account read, which is best effort.
- Review of #38: a confirmed tick clears the lost-clock state, so a clock that recovers while the clock_lost close is refused lets the bot read again and take an in-limit final instead of closing on it; the exit 6 line names the side and the card (and the copy for a sell).
- Both bots: `--resume` is no longer skipped by the cash check for a new conversation; the thread is read and resolved inside its limit, and a resumed buy whose earlier bid is above what may be spent now, or with nothing spendable at all, is closed.

### Tests
- `tests/test_dealer_followup.py`: 27 tests, all failing on `main` before the fix (six of them added after reviews, each failing on the commit before its fix too). `tests/dealer_fakes.py`: a frozen-clock window and request hooks. `tests/test_dealer_loop.py`: the pause test's clock outage shortened to 200 s (under the new 5-wait bound). `run_main` now also fakes `RunLog`, which `main()` rebinds for a non-default dealer (a pilar run test had appended to the committed `logs/`; restored).

## [2026-10-03] Dealer bots: lunch fixes

### Fixed
- `agent/chato.py`: no more bid-cap deadlock. Pinned at `--max-bid`, the bot listens while the dealer's offer improved (or we moved) in the last 2 ticks, then takes it if it is inside our reservation or closes at once (`max_bid_no_deal`). Thread 335 (LAV-09, his 90 inside our 93) closed on `max_rounds` instead. When the round budget runs out, a standing offer inside our reservation (buy: at or under it; sell: at or over our floor) is accepted instead of closed on.
- `agent/chato.py`, `agent/abuela.py`: the duel lock is re-checked before every accept, not only at start. While it is fresh the accept waits a tick (`accept_deferred_lock`) without spending a round.
- `agent/chato.py`, `agent/abuela.py`: the client is built with `wait_on_tick=False`. A refused accept, message or close is logged (`accept_refused`, `say_refused`, `close_refused`), the bot waits a tick, re-reads the thread and decides again; nothing is resent blindly and nothing raises out of `negotiate()` with the thread open.
- `agent/chato.py`, `agent/abuela.py`: a paused clock or closed doors no longer burns the round budget. The new `wait_tick` polls every 3 s through the pause and tolerates a null `next_tick_in`. `kit/` is unchanged.
- `agent/chato.py`, `agent/abuela.py`: when the cash reserve (default 280 P, unchanged) blocks every buy, `run` prints one line saying how to pass `--reserve`, logs `reserve_blocks_buys`, and exits 3.
- Review round (Codex findings on PR #35), both bots: writes are never retried by the SDK (a `rate_limited` accept could land after the duel lock turned fresh); a refused close goes back to a fresh read and decision, and after 3 refusals the run stops with `close_failed`, exit 4 and one line with the `--resume` command; lock deferral is bounded by `--max-defer-ticks` (default 60, then `lock_timeout`, exit 5); a round is counted only for a confirmed new tick; clock reads have a 5 s timeout and no retries, so an unreadable clock releases the wait within about a minute; a pause, an unreadable clock or a running clock whose tick does not move prints one line a minute; once the budget is spent the bot still decides on a fresh read, with at most 2 accept attempts; resume reads go through the same recovery; `--max-bid` equal to the reservation also closes on a stall.
- `agent/abuela.py`: sell floors are rounded up before any price is built (a 19.5 floor gave a binding ask of 19); the end-of-budget accept now applies to Abuela too; `--resume` added so a thread that could not be closed can be continued.

### Changed
- `agent/chato.py --dealer pilar`: slow defaults that match how she concedes (by time): first ask `max(1.25 x her bid, floor + 9)` (27 for floor 18), 1 P steps, 40 rounds. `--sell-anchor`, `--sell-step` and `--max-rounds` still win. Chato's defaults are unchanged.

### Added
- `agent/dealer_client.py`: the dealer bots' client (`DealerBazaar`: the kit client with `wait_on_tick=False` and a pause-safe `wait_tick`), the lock-guarded accept, a close that never raises, and the reserve message.
- `tests/test_dealer_loop.py`, `tests/test_dealer_client.py`, `tests/test_dealer_cli.py`, `tests/dealer_fakes.py`: 77 tests, including a replay of thread 335. `FakeServer` is an in-process game server under the real kit SDK (urlopen patched): SDK retries, one accept per team and one message per thread per tick, accepts only of open offers, settlement on the next tick, dealer answers on the next tick, offers lapsing after 4 ticks; every loop test asserts no write was sent twice in one tick. Four assertions in `tests/test_chato_dealer.py` moved to Pilar's new defaults, and its `FakeDealer` now reports a tick from `wait_tick`.

## [2026-10-03] Team bus

### Added
- `tools/bus.py`: team bus on [issue #25](https://github.com/thiagoamaro91/negotiation-agent/issues/25), so Claude sessions on different accounts and machines can message each other. `post`, `ask` (blocks for the answer), `wait` (meant as background Bash: no tokens while it polls, exits when a message arrives), `read`, and a who-runs-what board (`claim`, `release`, `board`) rebuilt from the claim log. Sender is the GitHub account; comments typed by a person in the GitHub app count as messages (to whoever they @-mention, otherwise to all).
- `CLAUDE.md`: *Team bus* section, the protocol every session follows.
- `tests/test_bus.py`: 23 tests (message format, addressing, cursor, ask matching, board races); 13 mutations, all caught.

## [2026-10-02]

### Added
- `kit/`: the official Bazaar kit, unchanged from bazaar-kit.zip (`bazaar_sdk.py`, `RULES.md`, starter agent, starter broker).
- `agent/abuela.py`: Abuela Carmen negotiator for the L1 dealer. Numbers are decided in code, the words only dress them.
  - Takes her fixed welcome price once, on the first deal (LAV-06 at 17 P).
  - Opens with a low anchor at 40% of her opening price, then steps 1 P per round.
  - Accepts her final offer whenever it is still below our private value.
  - Never bids before she has answered our last number, so we never bid against ourselves.
  - Keeps a 280 P cash reserve for the level-2 venue (250 P bond plus 20 P).
  - Structure check: reads the structured offer, not her words, and refuses any offer that moves a different card than the one we negotiated (guards against switched cards).
- `agent/runlog.py`: shared logger for every agent, one JSONL file per agent per day under `logs/<agent>/`, keys redacted.
- `tools/snapshot.py`: server-side capture of everything our key has done, whoever ran it: all conversation threads, duels, offers, holdings, and a score line per snapshot.
- `tools/dashboard.py` and `tools/dashboard.html`: live team dashboard with score, conversations drawn as price charts with round-by-round play-by-play, the album, the El Rastro board with our private values, the leaderboard, the feed, and countdowns.
- `tools/deploy_mini.sh` and `tools/mini/`: always-on hosting of the dashboard on the Mac Mini, with LaunchAgents, a Cloudflare quick tunnel, a watchdog on the public link, and a Telegram ping when the link changes. The team key lives only in an untracked `.env` on the Mini.
- `logs/`: every run and transcript from today, committed. Five Abuela deals so far: LAV-06 at 17 P (welcome), LAV-07 at 22 P, LAV-08 at 23 P, SAL-06 at 25 P, SAL-07 at 22 P.

### Changed
- `README.md` rewritten for the real game (The Bazaar, Cromos de Madrid): setup, layout table, team rules while the game runs (one process per dealer, keep 280 P, snapshot before commit), and the log formats.

## [2026-10-02] (evening, continued)

### Added
- `agent/chato.py`: El Chato negotiator for the L2 dealer, copied from `abuela.py`. No welcome deal; terse lines with a new price in every message; uncommons and rares only. Flags: `--reserve`, `--cap`, `--resume <thread>`, `--max-rounds`.
- Chato deals: SAL-08 at 29 P (thread 234), LAT-06 at 28 P (thread 253), LAT-07 at 29 P (thread 275), each one his final offer. His uncommon pattern: opens at 33, holds 3 rounds, then drops 1 P per 1 P we add, final offer around round 7.
- `agent/duel.py`: duel negotiator draft (`watch` / `run`). Measured in practice duel 37: our own message counts as one round of decay. Max 3 messages per duel.
- `agent/rastro_seller.py` and `agent/rastro_floors.json`: El Rastro seller for our spare cards. Anchors high, steps down 2 P per 20 ticks to a floor, haggles in incoming team threads, renews listings before the 30-tick expiry. `--take-bids` is off by default (offers addressed to us outside a conversation are accepted only with it). Has a `selftest`.
- Merged Hector's public feed recorder (`tools/feed_recorder.py`, `tools/feed_report.py`), running since 22:34.
- Market: MAL-08 spare sold to another team on El Rastro at 28 P, score 11.63 to 14.63. LAV-08 (40) and MAL-06 (28) listed overnight.

### Fixed
- `fix(chato)`: `--cap` can only lower our limit, never raise it above our private value. Buys above our value (LAT-06 at 28 and LAT-07 at 29, worth 27.5 to us) earned zero ladder credit.
- `tools/snapshot.py`: reads the duel id from the `duel` key, not `id`.

## [2026-10-03]

### Changed
- `agent/duel.py`: retuned from the Friday duel analysis (`docs/analysis-friday/duels.md`); replaces the 3-message draft.
  - Silent by default: holds while the rival moved toward us within the last `--stall-ticks` (3) ticks, and speaks only to a stalled rival (offer outside our limit or thin) or a silent one. Max 2 messages per duel (`--max-msgs`, was 3).
  - Accept window: any offer strictly inside our limit in the last `--accept-any-ticks` (3, was 2) ticks, widened to the number of our open duels whose deadlines are within `--near-ticks` (2), since the team gets one accept per tick. Several acceptable at once: biggest surplus first, unless a duel would otherwise lose its slot. A lone duel whose rival is still conceding waits to deadline-2 and keeps deadline-1 as the retry (`--no-window-wait` takes the slot at once).
  - The paired duel's limit is used as a soft estimate of the rival's limit: it sizes the anchor and an early accept (`--early-share` 0.85 of the pie when the pie is above `--early-min-pie` 2), never moves us across our own limit. An absent rival gets one offer at `--absent-at` (0.5) of the clock.
  - Every tuning constant is a CLI flag and can also come from `--params file.json`; explicit flags win over the JSON. The `run_start` log line records the values used.
  - New: `watch --once` (one read-only pass) and `selftest` (rule fuzz plus scripted rival archetypes; `--n`, `--seed`).
  - `run` writes `results/duel.lock` (one line: expiry in epoch seconds, `--lock-ticks` 3 ticks ahead) while any of our duels is live, and deletes it when none is live and on exit.
- `agent/rastro_seller.py`: defers every accept (logged `defer_duel_lock`) while `results/duel.lock` is fresh; listing, renewing and messaging go on.
- `agent/chato.py` and `agent/abuela.py`: `run` refuses to start (warning, exit 0) while `results/duel.lock` is fresh.
- `agent/rastro_floors.json`: Saturday start/floor prices.
- `agent/market_desk.py`: swaps are opt-in (`--swap-fills`, `--swap-posts`; the old `--no-swap-*` flags are accepted as no-ops). Swap fills only on El Rastro unless `--swap-team-venue`. A swap never gives a last copy (`--sell-first-copies` does not apply) nor any asset in `agent/rastro_floors.json` (every line, re-read every tick, last good set kept if the file breaks) unless `--swap-seller-spares`. A swap fill keeps cash minus live bids minus the fee at 200 P or more.

### Added
- `agent/chato.py`: `--anchor N` (absolute first bid, overrides the anchor fraction), `--step N` (primas per round when buying, default 1), `--max-bid N` (highest number we send when buying; his final is still taken up to `--cap`). `plan` prints the bid ladder; a buy is skipped while spendable cash is below `--anchor`.
- `agent/abuela.py`: `--reserve N` (cash we never spend below, default 280) and `--cap N` (only lowers our limit below our private value).
