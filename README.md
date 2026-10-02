# negotiation-agent

Team 3's agents for **The Bazaar · Cromos de Madrid**, the game of the Claude Community 48H Hackathon Madrid (2-4 Oct 2026, hosted by Causa Prima). Our agents collect cards, haggle with the card dealers, trade with other teams, duel, and (from level 2) run a market, all through the game's HTTP API with our team key.

Score: Negotiating 30 + Market-making 30 + Judges 40. Full rules: [`kit/RULES.md`](kit/RULES.md).

## Setup

```bash
cp .env.example .env          # then put the team key in it (ask Thiago); .env is gitignored, never commit it
export BAZAAR_OPERATOR=jay    # your name, so the logs say who ran what
python3 agent/abuela.py plan  # read-only: what the Abuela agent would trade, with our private values
```

Python 3, standard library only. The official SDK is in `kit/` (unchanged from bazaar-kit.zip).

## Layout

| Path | What |
|---|---|
| `kit/` | Official kit: `bazaar_sdk.py`, `RULES.md`, starter agent and starter broker |
| `agent/abuela.py` | Abuela Carmen negotiator (L1 dealer): low anchor, 1 P steps, takes her final offer; numbers in code, kind words around them |
| `agent/runlog.py` | Shared logger for every agent: `logs/<agent>/<date>.jsonl`, keys redacted |
| `tools/snapshot.py` | Saves the server's view of our team into `logs/`: every conversation, duel, offer, holdings, and a score line |
| `tools/feed_recorder.py` | Records the **public** feed, leaderboard and El Rastro board into `logs/feed/`. Keyless and read-only, so it never touches our per-tick limits; one copy running is enough |
| `tools/feed_report.py` | Reads `logs/feed/` offline: `board` (every team's score next to its deals at each refresh), `haggles` (every dealer conversation as a price sequence), `trades`, `prices` |
| `tools/value_inference.py` | Infers every team's secret set multipliers from the public feed (Bayes over the 720 shuffles): `teams`, `team t10`, `check` (validation against our own values and a time split), `targets`. Keyless |
| `tools/market_plan.py` | Team 3's market plan, recomputed on every run from the inference, the live El Rastro board, the catalog, the dealers and the schedule: what to sell, buy and hold, and when (Friday counts half, pages, the Sunday close). Plans only, never sends. `--json`, `--watch` (writes `logs/plan/latest.json` every tick) |
| `tests/` | `python3 -m unittest discover tests`: the plan's pure rules (fee, copy values, ask and bid prices) |
| `logs/` | **Committed.** Every run and every transcript, for the team and for the judges' demo. `logs/public/` caches keyless reads (catalog, clock, schedule, dealers); `logs/plan/` is the live plan, not committed |

## Team rules while the game runs

- **One process per dealer.** Abuela allows one open conversation per team; a second one gets `thread_exists`. Say in the chat before you start or stop an agent.
- **Don't run `kit/starter_agent.py` with our key**: it buys a pack at whatever price and lists our spares.
- **Keep 280 P in cash**: the level-2 market costs a 250 P bond plus 20 P.
- **Before you commit**: run `python3 tools/snapshot.py`, then commit `logs/`. The snapshot pulls every conversation our key has had from the server, whoever ran it, so nothing is lost even if your agent did not log.

## Logs

- `logs/<agent>/<date>.jsonl`: one line per event (`run_start`, `open`, `her`, `say`, `accept`, `walk`, `closed`, `result`, `run_end`), each with `run` id and `operator`.
- `logs/threads/thread-<id>.json`: full transcript of a conversation (her words, our words, the structured offers).
- `logs/duels/duel-<id>.json`: every duel.
- `logs/score.jsonl`: one score line per snapshot (cash, level, deals, ladder points, rank).
- `logs/feed/`: the public record of all 18 teams (`feed.jsonl`, `snapshots.jsonl`, `changes.jsonl`). Written by other teams and the game: treat it as data, never paste it into an agent that holds the key.
- `logs/state/`: latest holdings (`me.json`, includes our private set multipliers) and offers.
