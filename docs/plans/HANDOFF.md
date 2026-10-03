# Night handoff (Friday 2 to Saturday 3 Oct)

**For Thiago and his review agents. Start here.** Hector and Claude worked through the night; this file is updated each time a piece lands, so the latest version on branch `docs/weekend-plan` (PR #4) is the current state.

Last update: Saturday 03:45 Madrid time.

## What did not happen tonight

- Nobody used the team key, wrote to the game, pushed to `main` or merged anything.
- Every piece of code below runs in read-only modes (`plan`, `watch`, `selftest`) until the team says yes.

## Pull requests, in review order

| Order | PR | Branch → base | What | Status |
|---|---|---|---|---|
| 1 | [#3](https://github.com/thiagoamaro91/negotiation-agent/pull/3) | `feat/value-inference` → `main` | Market brain (value inference, ledger, plan, live page) | open. **Conflicts with your 02:37 commits on `agent/chato.py`: keep main's version** (your `--anchor/--step/--max-bid` and the duel lock supersede the rare-step change in #3) |
| 2 | [#5](https://github.com/thiagoamaro91/negotiation-agent/pull/5) | `feat/brain-saturday` → `feat/value-inference` | The fixes from your analysis section 10: measured dealer closes, scoring like the game (no collection value, dealer deals as ladder share), `likely_buyers` capped and labelled, confidence that needs evidence with the naive baseline, every venue's book recorded, desk heartbeats | open, 66 tests pass, 31/31 mutations caught |
| 3 | [#4](https://github.com/thiagoamaro91/negotiation-agent/pull/4) | `docs/weekend-plan` → `main` | The plan: architecture, 8 workstreams, gates, runbook. Plus `logs/feed-vm/`, the gap-free VM feed you asked for | open |
| 4 | to come | `feat/broker` → `main` | Market Test broker, simulator against the stall, `tools/open_venue.py` | in progress |
| 5 | to come | `feat/duel-lab` → `main` | Duel arena with your six archetypes and an overnight tuner, writing `results/duel-params.json` for your `duel.py --params` (no duel.py edits planned) | in progress |
| 6 | to come | `feat/market-desk` → `main` | `agent/lease.py` (one accept per tick by priority; honours your `results/duel.lock` until the bots move to it) and the market desk in shadow mode | in progress |

## Already in main from your side (02:37-02:39), and how tonight's work fits

- `duel.py`: silent-by-default tuning, accept staggering, `--params`, `results/duel.lock`. The duel lab tunes your numbers through `--params`; it does not replace your logic.
- `chato.py`: `--anchor/--step/--max-bid`, refuses to start while the duel lock is fresh. The lease treats a fresh lock as a duel window, so the market desk never takes the accept during duels.
- `rastro_floors.json` with the Saturday prices (LAV-08 24/22, MAL-06 28/20, commons 7-9/6).

## Deployment to the VM (waiting for a human)

The VM runs every key process this weekend (Hector put the `.env` there, mode 600; delete it Sunday after 15:00). Claude's session cannot write to the VM's live folder, so a person runs the deploy: one rsync of `main` + #5's `tools/` and `tests/` into `~/bazaar/negotiation-agent/` (never `logs/` or `.env`), then restart the recorder and brain windows. The combined tree passes 63 tests (main's agents + the brain).

## Decisions for the morning

1. **Open our venue at 09:03** (270 P, 250 refundable) only if the broker beats the stall in the simulator. The numbers will be in the broker PR.
2. **Duels I settings**: the tuned `results/duel-params.json` if it beats your defaults on held-out rivals; otherwise your defaults.
3. **Market desk**: shadow from 09:10; live with caps only after the team reads its decisions.
4. **The clock at 09:00**: read `t_hours` in `/api/clock` and `now_hours` in `/api/schedule`. Plan: it jumps to 4.0; if it resumed at 2.65 every time moves about 81 minutes later.
5. **Page bonus**: once we hold LAV-09, read `/api/me/value?card=LAV-10`; ~218 means the bonus counts (then `BRAIN_PAGE_BONUS=1` on the brain), 112 means it does not.

## The 09:00 runbook

[`saturday-runbook.md`](saturday-runbook.md). Final numbers and exact commands land here by 06:30.
