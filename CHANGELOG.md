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
