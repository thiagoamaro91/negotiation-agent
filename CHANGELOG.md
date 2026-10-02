# Changelog

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
