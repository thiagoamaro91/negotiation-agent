# Night handoff (Friday 2 to Saturday 3 Oct)

**For Thiago and his review agents. Start here.** Hector and Claude worked through the night; this file is updated each time a piece lands, so the latest version on branch `docs/weekend-plan` (PR #4) is the current state.

Last update: Saturday 03:00 Madrid time.

## What did not happen tonight

- Nobody used the team key, wrote to the game, pushed to `main` or merged anything.
- Every piece of code below runs in read-only modes (`plan`, `watch`, `selftest`) until the team says yes.

## Pull requests, in review order

| Order | PR | Branch | What | Status |
|---|---|---|---|---|
| 1 | [#3](https://github.com/thiagoamaro91/negotiation-agent/pull/3) | `feat/value-inference` | Market brain (value inference, ledger, plan, live page). Will receive the fixes from your analysis section 10 | open; fixes in progress |
| 2 | [#4](https://github.com/thiagoamaro91/negotiation-agent/pull/4) | `docs/weekend-plan` | The plan: architecture, 8 workstreams, gates, runbook. Plus `logs/feed-vm/`, the gap-free VM feed you asked for | open |
| 3 | to come | `feat/broker` | Market Test broker, simulator against the stall, `tools/open_venue.py` | in progress |
| 4 | to come | `feat/duel-lab` | Duel arena with your six archetypes, overnight tuner, `agent/duel_params.json` read by `duel.py` | in progress |
| 5 | to come | `feat/market-desk` | `agent/lease.py` (one accept per tick by priority) and the market desk in shadow mode | in progress |

Each PR says how to test it. They only add files, with one exception: the duel-lab PR changes `agent/duel.py` to load its params from a file, with behaviour identical to today's constants (covered by a test).

## Decisions for the morning

1. **Key on the VM.** Hector copied the `.env` to the VM himself (`~/bazaar/negotiation-agent/.env`, mode 600) so every key process runs on one always-on machine with the recorder, brain and broker. It gets deleted on Sunday after 15:00.
2. **Open our venue at 09:03** (270 P, 250 refundable) only if the broker beats the stall in the simulator. The numbers will be in PR 3 of this list.
3. **Duels I settings**: the tuned params from the arena, or your analysis settings if the tuned ones do not beat them on held-out rivals.
4. **Market desk**: shadow from 09:10; live with caps only after the team reads its decisions.
5. **The clock at 09:00**: read `t_hours` in `/api/clock`. The plan assumes it jumps to 4.0; if it resumed at 2.65 every time moves about 81 minutes later.

## The 09:00 runbook

[`saturday-runbook.md`](saturday-runbook.md). Final numbers and exact commands land here by 06:30.
