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
| `agent/abuela.py` | Abuela Carmen negotiator (L1 dealer): low anchor, 1 P steps, takes her final offer; numbers in code, kind words around them; `--reserve`, `--cap` (can only lower our limit) |
| `agent/chato.py` | El Chato negotiator (L2 dealer): copied from Abuela, no welcome deal, terse lines with a new price each message, uncommons and rares only; `--reserve`, `--cap` (can only lower our limit), `--resume`, `--max-rounds`, `--anchor` (absolute first bid), `--step` (buy step), `--max-bid` (highest number we send; his final is still taken up to `--cap`) |
| `agent/duel.py` | Duel negotiator (`watch` / `run` / `selftest`): silent by default, speaks only to a stalled or silent rival, max 2 messages per duel; when several duels share a deadline it starts accepting early, biggest surplus first (one accept per team per tick); `run` writes `results/duel.lock` while any duel is live; every tuning constant is a flag or comes from `--params file.json` (flags win over the JSON) |
| `agent/rastro_seller.py` | El Rastro seller for our spares (floors in `agent/rastro_floors.json`): anchors high, steps down 2 P per 20 ticks, haggles in team threads, renews before expiry; `--take-bids` off by default; `selftest` |
| `agent/runlog.py` | Shared logger for every agent: `logs/<agent>/<date>.jsonl`, keys redacted |
| `tools/snapshot.py` | Saves the server's view of our team into `logs/`: every conversation, duel, offer, holdings, and a score line |
| `tools/feed_recorder.py` | Records the **public** feed, leaderboard and El Rastro board into `logs/feed/`. Keyless and read-only, so it never touches our per-tick limits; one copy running is enough |
| `tools/feed_report.py` | Reads `logs/feed/` offline: `board` (every team's score next to its deals at each refresh), `haggles` (every dealer conversation as a price sequence), `trades`, `prices` |
| `tools/value_inference.py` | Infers every team's secret set multipliers from the public feed (Bayes over the 720 shuffles): `teams`, `team t10`, `check` (validation against our own values and a time split), `targets`. Keyless |
| `tools/market_plan.py` | Team 3's market plan, recomputed on every run from the inference, the live El Rastro board, the catalog, the dealers and the schedule: what to sell, buy and hold, and when (Friday counts half, pages, the Sunday close). Plans only, never sends. `--json`, `--watch` (writes `logs/plan/latest.json` every tick) |
| `tools/ledger.py` | Every team's cash and known cards rebuilt from the public feed (exact for us: checked against `/api/me`) |
| `tools/brain.py` | The market brain: keyless service that recomputes inference, ledger and plan on every new event and serves a live page (`brain.html`: plan, live market tape with the real team behind each pseudonym, every team's cash and values, the model's learning curve). Token-gated (`BRAIN_TOKEN`) |
| `tools/run_brain.sh` | On the always-on VM: recorder + brain in tmux, restarted if they die |
| `tools/concierge.py` | La Celestina concierge: a public, keyless wants / haves board (page + JSON API + `/llms.txt`) that routes other teams to post on our venue v20. No key, no model, never trades; `selftest`, `quote CARD` |
| `tools/me_relay.py` | Run on ONE laptop that holds the key: pushes our account to the brain every 20 s (key fields scrubbed), so the plan sees pack pulls; the key never leaves the laptop |
| `tools/bus.py` | Team bus: messages between the team's Claude sessions across accounts and machines, on [issue #25](https://github.com/thiagoamaro91/negotiation-agent/issues/25) (`post`, `ask`, `wait`, `read`), plus the who-runs-what board (`claim`, `release`, `board`). Uses the `gh` CLI; see *Team bus* in `CLAUDE.md` |
| `tools/factory.py` | Sunday factory: `plan` (read-only: clock, schedule in wall time, every command and gate), `up --yes` (one tmux window per bot, each a restart loop gated on doors, pause, duel lock and duel waves, claimed on the bus), `status [--notify] [--every N]` (health, stale logs, Market Test dropped/matched). Processes and flags are data in `tools/factory_sunday.json`; runbook in [`docs/plans/sunday-runbook.md`](docs/plans/sunday-runbook.md) |
| `tests/` | `python3 -m unittest discover tests`: the plan's pure rules (fee, copy values, ask and bid prices) |
| `logs/` | **Committed.** Every run and every transcript, for the team and for the judges' demo. `logs/public/` caches keyless reads (catalog, clock, schedule, dealers); `logs/plan/` is the live plan, not committed |

## La Celestina concierge

`tools/concierge.py` is the public front door to our venue: other teams (or their agents) post the card they want or the spare they would sell, and get back the opposite-side requests for that card, a price range from public team trades, how many other teams appear to hold it, and the exact `POST /api/offers` body for v20. It holds no key, calls only keyless GETs, runs no model, and never shows our holdings, values, cash or who holds what. Run command, routes and limits are in the module docstring:

```bash
python3 tools/concierge.py serve --host 0.0.0.0 --port 8780 --feed ~/bazaar/logs/feed/feed.jsonl --store-dir ~/bazaar/logs/concierge --public-url https://<tunnel>
python3 tools/concierge.py selftest      # read-only, sample data, free port
```

## Team rules while the game runs

- **One process per dealer.** Abuela allows one open conversation per team; a second one gets `thread_exists`. Say in the chat before you start or stop an agent.
- **Duels hold the accept slot.** While `agent/duel.py run` has a live duel it keeps `results/duel.lock` fresh: `abuela.py` and `chato.py` refuse to start `run`, and `rastro_seller.py` defers its accepts. The lock is a local file, so it only covers bots running from the same checkout.
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
