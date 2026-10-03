# Changelog

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
