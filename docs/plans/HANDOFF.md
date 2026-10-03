# Night handoff (Friday 2 to Saturday 3 Oct)

**For Thiago and his review agents. Start here.** Hector and Claude worked through the night; this file is updated each time a piece lands, so the latest version on branch `docs/weekend-plan` (PR #4) is the current state.

Last update: Saturday 04:50 Madrid time.

## What did not happen tonight

- Nobody used the team key, wrote to the game, pushed to `main` or merged anything.
- Every piece of code below runs in read-only modes (`plan`, `watch`, `selftest`) until the team says yes.

## Pull requests, in review order

| Order | PR | Branch → base | What | Status |
|---|---|---|---|---|
| 1 | [#3](https://github.com/thiagoamaro91/negotiation-agent/pull/3) | `feat/value-inference` → `main` | Market brain (value inference, ledger, plan, live page) | open. **Conflicts with your 02:37 commits on `agent/chato.py`: keep main's version** (your `--anchor/--step/--max-bid` and the duel lock supersede the rare-step change in #3; drop `tests/test_chato.py` with it) |
| 2 | [#5](https://github.com/thiagoamaro91/negotiation-agent/pull/5) | `feat/brain-saturday` → `feat/value-inference` | Your section 10 fixes: measured dealer closes, scoring like the game, `likely_buyers` capped, confidence that needs evidence with the naive baseline, every venue's book recorded, desk heartbeats | open; 66 tests, 31/31 mutations caught |
| 3 | [#8](https://github.com/thiagoamaro91/negotiation-agent/pull/8) | `feat/desk-forwarder` → `feat/brain-saturday` | Posts each desk's heartbeat file to the brain page (token from `~/bazaar/brain.env`, never the repo `.env`) | open; 7 tests, 5/5 mutations caught |
| 4 | [#6](https://github.com/thiagoamaro91/negotiation-agent/pull/6) | `feat/market-desk` → `main` | `agent/lease.py` (one accept per tick by priority, honours your `results/duel.lock`) and the market desk (`plan`/`watch`/`run`), `make_floors`, a Friday replay | open; 56 tests, 38/39 mutations caught |
| 5 | [#7](https://github.com/thiagoamaro91/negotiation-agent/pull/7) | `feat/broker` → `main` | Market Test broker, bench simulator, venue opener. Finding: blind it ties the stall; it wins (+2 points) only if bench offers show each trader's expiry | open; 42 tests, 18/18 mutations caught |
| 6 | [#4](https://github.com/thiagoamaro91/negotiation-agent/pull/4) | `docs/weekend-plan` → `main` | The plan, this handoff, the runbook, and `logs/feed-vm/` (the gap-free VM feed you asked for) | open |
| 7 | [#9](https://github.com/thiagoamaro91/negotiation-agent/pull/9) | `feat/duel-lab` → `main` | Arena that drives your `duel.py` exactly as `run` does, a tuner refereed by held-out rivals + your `simulate()` + the Friday replay + a deadline-1 stress, and Duels I params for `--params`: **safe** +2.5 % (never worse anywhere), **tuned** +5.6 % (bets that a deadline-1 accept settles). `duel.py` untouched | open; 16 tests, 15/15 mutations caught |
| 8 | [#10](https://github.com/thiagoamaro91/negotiation-agent/pull/10) | `feat/duel-improve` → `feat/duel-lab` | Code-level improvements to your `duel.py`, every one behind a flag OFF by default (no flags = byte-for-byte your behaviour): a late read of the duels 8 s before the tick ends in the last 3 ticks, accept-slot demand from acceptable offers only, last-chance share 0.3. **Improved file: 0.394 per duel vs 0.354 safe (+11 %) and 0.343 your defaults**, better on all three referees and all 12 stress rows | open; 35 tests, staged on the VM (not live) |

## Already in main from your side (02:37-02:39), and how tonight's work fits

- `duel.py`: silent-by-default tuning, accept staggering, `--params`, `results/duel.lock`. The duel lab tunes your numbers through `--params`; it does not replace your logic.
- `chato.py`: `--anchor/--step/--max-bid`, refuses to start while the duel lock is fresh. The lease treats a fresh lock as a duel window, so the market desk never takes the accept during duels.
- `rastro_floors.json` with the Saturday prices (LAV-08 24/22, MAL-06 28/20, commons 7-9/6).

## What runs on the VM now

Deployed at 03:05-03:50 with Hector's go-ahead: `main` at 0289293 + #5 + #6 + #7 + #8 + #9 in `~/bazaar/negotiation-agent` (all tests pass there; `.env` untouched; Friday's `logs/duels/` added for the arena). tmux session `bazaar`: `recorder` (now also records every venue's book), `brain` (the fixed brain), `desks` (the forwarder). Nothing that uses the key is running; the key sits in `.env` (mode 600) until Sunday after 15:00.

Duel params on the VM, in `~/bazaar/negotiation-agent/results/`:
- `duel-params.json`: the **safe** Duels I set (what the runbook launches; `duel.py selftest` passes with it).
- `duel-params-duels1-overnight.json`: the VM search's full set at 03:31 (held-out objective 0.308 vs 0.290 for your defaults). The search keeps going until ~07:28 in `~/lab/duel/` (tmux `lab:duel`); its latest is `~/lab/duel/best_params_duels1.json` with `report_duels1.md`.
- `duel-params-duels2-candidate.json`: the Duels II (price + day) search at 03:40 (0.192 vs 0.176, +9 %); it runs until ~10:28 (`~/lab/duel/best_params_duels2.json`, `report_duels2.md`).
- Stop both searches if the VM needs the cores: `pkill -f "^python3 tools/duel_tune.py"`.

## Decisions for the morning

1. **The clock at 09:00**: read `t_hours`; the plan assumes 4.0. If it resumed at 2.65 every time moves about 81 minutes later.
2. **Venue**: not at 09:03 blind (it would tie the stall). Decide at 11:50, before the 12:00 session, with the 10:00 data and the desk's answers (PR #7 lists the three conditions).
3. **Lavapiés rare**: a team listing under ~82 first, otherwise El Chato with your ladder (`--anchor 60 --step 4 --max-bid 84`), cap 88, `--reserve 280` to keep the venue option.
4. **Page bonus**: once we hold LAV-09, `/api/me/value?card=LAV-10` ~218 means it counts.
5. **Duels I**: `duel.py run --params results/duel-params.json` from 10:15 (it waits for the wave). **If you approve #10**, activate it first on the VM (one command, runbook step 12): it is the biggest duel gain of the night (+11 % over the safe set). Otherwise the safe set from #9 is already in place. The tuned set's narrower accept window waits until one of our deadline-1 accepts is seen to settle.
6. **Market desk LIVE from 09:00, if you approve PR #6** (Hector's decision, 03:30). Friday's best opportunity (LAV-10 listed at 70, +37 at our values) lasted 3 ticks before t10 took it; in shadow mode nobody catches that. Strict caps: 110 P per game hour (one Lavapiés rare at most), 250 P per day, 80 P per card (100 for a Lavapiés rare), one trade per partner per hour, cash never below 280 until the 11:50 venue decision, El Rastro only (`--no-team-venues`, so we hand no market points to other venues; t13 is first), bids addressed to holders only. It never buys a card we hold, never sells our only Lavapiés copy, never accepts while your duel lock is fresh, and `touch logs/state/STOP` stops it. Exact command in the runbook, step 5. If PR #6 is not approved by 09:00, it starts in `watch` (shadow) instead.
7. **Questions for the desk** (in person): judging criteria and format; whether duel accepts share the one-accept-per-tick limit; whether the ladder resets per day; whether the page bonus counts in a card's trade value; whether bench offers carry each trader's expiry, whether the stall crosses one pair or all per tick, whether broker matches are checked against quotes or hidden limits.

## The 09:00 runbook

[`saturday-runbook.md`](saturday-runbook.md): every command, on the VM, in order, with its gate.
