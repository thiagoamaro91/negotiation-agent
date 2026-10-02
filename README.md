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
| `agent/memory.py` | **Memory.** Before every run it re-reads all past Abuela conversations (ours, graded good/bad, plus other teams' public ones), rebuilds what we know about her per item kind, and hands the agent a probe, a ceiling and the expected final. Writes `logs/memory/` (see below) |
| `agent/runlog.py` | Shared logger for every agent: `logs/<agent>/<date>.jsonl`, keys redacted |
| `tools/snapshot.py` | Saves the server's view of our team into `logs/`: every conversation, duel, offer, holdings, and a score line |
| `logs/` | **Committed.** Every run and every transcript, for the team and for the judges' demo |

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
- `logs/state/`: latest holdings (`me.json`, includes our private set multipliers) and offers.

## Memory (agent/memory.py)

`python3 agent/abuela.py run` calls `Memory.refresh(b)` first: it pulls every conversation the server holds for our key plus the public feed, re-analyses them, rewrites `logs/memory/` and prints a brief. After each conversation it re-learns before starting the next one. Flags: `--no-memory` (original fixed numbers), `--fast-steps` (let memory climb +3 P while far from its probe; the default stays STEP = 1 P, the team decision for tonight).

- `logs/memory/samples.jsonl`: one parsed conversation per line (her ask path, our bid path, final, outcome). Reads structure only, never her words.
- `logs/memory/abuela_memory.json`: per item kind (pack, unc, com): welcome price, where she opens, where her final lands, bids before the final, the lowest price she ever took from a bid, the highest bid she refused.
- `logs/memory/lessons.md`: each of our deals graded good / ok / bad / neutral against what other teams paid, and the current advice.
- What it changes in the bot: bids never go past her learned **ceiling** (the highest she has needed before naming a final); a final under our private value is still taken. It never changes what we accept below our value.
- `python3 agent/memory.py` rebuilds from the committed transcripts with no network. Tests: `python3 tests/test_memory.py` (15 offline tests).

- **Unlock counter:** `lessons.md` and the run brief show `good / negotiated of needed`. Welcome deals and deals at her opening price never count (rules). The threshold is read from the server when a dealer publishes `unlock.early_min_deals`; until then it is **assumed to be 3** and marked so. El Chato (level 2) is announced but his rule is not published yet.
- **Sell side:** conversations where we sell her a card are parsed too (her bids vs our asks). `lessons.md` shows what she pays per kind; the bot never opens a sell above 1.5 x the best price anyone has got from her (saves rounds; it never goes under our own value + 2 P).

Honest limits: every conversation has its own secret limit, so these numbers are soft evidence; with few deals the advice is mostly priors from Friday's public data. A bad grade means "another team paid less", not proof we could have.
