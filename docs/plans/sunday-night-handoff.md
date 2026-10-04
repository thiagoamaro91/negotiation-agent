# Sunday night handoff (Sat 3 to Sun 4 Oct)

> **Read this first · updated 04:49 Madrid**
> - **Merged:** #57 census, #62 evals, #63 broker pace, #64 announce fix, #65 Market Test memo, #67 Open Bazaar, #68 pitch, #69 ladder, #70 desk page mode, #71 analyst, #72 duel params, #73 deck validation, #74 public board. Open: nothing the bots need.

**For Thiago, 07:00, five minutes.** No key entered a model's context. Then the [pre-flight](sunday-preflight.md), 08:40.

## Thiago's priorities, confirmed tonight

1. **Market Test first.** 5 left, the first 2 count for Saturday; broker live at 09:00 Madrid.
2. **Money into deals.** About 20 P surplus a deal, 40 P reserve, many teams, slots filled.
3. **Duels: keep it.** Duels II: 29 of 33 deals, none below limit.

## What the night built, and why

- **Duels III params** (#72): Duels II blend, `days_best buyer:0,seller:10`, F4 `last_while_moving` **off** (it can block a late accept). The 06:45 Madrid verdict (`docs/duel-lab/duels3-search/`) should say "incumbent stays"; no swap after 08:00 Madrid. At 11:39 the first `days_meaning` lines must match Saturday's; if not, delete `days_best`, restart the duel bot.
- **Broker:** `--policy stall` all day (`maxpairs` lost; verdict 06:45 Madrid: `evals/broker-search/`).
- **Open Bazaar** (#67, #73): the matchmaker refreshes who-needs-which-card every 2 minutes from 08:55; the announcer posts one match per 12 minutes from 09:00; `outreach` stays off until flipped. Page-card matches pause unless an account snapshot younger than 90 game minutes exists (`me_snapshot` every 10 min on the Mini; the VM syncs `mini/logs` every 5 min). Census first: pre-flight 12.
- **Ladder** (#69): Abuela buys RET uncommons, Pícaros two RET rares, Pilar resells them.
- **Page buy** (#70): from 09:00 the desk bids 80 rising to 110 for SAL-10, our last Salamanca page card, from a team.

## What runs where

- **Mini (keyed; `up --yes`):** feed recorder, `logs_push`, `me_snapshot`, broker, market desk (page mode), matchmaker (keyless), announcer, watchdog, then the duel bot (before each wave) and the dealer steps (after the +150 P): your "broker first, then the duel bot".
- **Mini → VM:** `logs_push` copies `logs/` to branch `mini/logs` every 10 minutes (never `main`; the Mini is its only writer; fallback: pre-flight 11). Your doc says no auto-pull, Hector says one runs: check 1 pulls if behind.
- **VM (keyless):** feed recorder since Friday; La Celestina (restarted from main); the analyst from 08:45 Madrid; overnight searches until 07:45.
- **VM → humans:** the analyst writes `logs/analyst/LATEST.md` on its branch, opens a PR per proposal, posts five lines on the bus (issue #25) per trigger, signed `FROM: wp10-sunday-analyst`.
- **Human only:** the 09:05 outreach thread, enabling `outreach`, applying an analyst recommendation, the pitch.

## What needs you (or Hector)

1. **Telegram notifier**, after the 08:00 Madrid freeze: in `tools/factory_sunday.json` set `notify_cmd` to:
   ```json
   "notify_cmd": ["/bin/bash", "-c", "set -a; . ~/.config/telegram-notify.env; set +a; curl -sS -m 30 -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=${TELEGRAM_CHAT_ID}\" --data-urlencode \"text=$1\" > /dev/null", "notify"],
   ```
2. **Open both held packs before 10:39 Madrid**, your yes (later pulls can include Chamberí cards), never during a dealer step.
3. **Outreach test thread, 09:05, your yes.** Read: `python3 tools/outreach.py plan`. Send one: `python3 tools/outreach.py run --yes --max-teams 1`. If that team lists, accepts or trades the named card within 40 ticks, set `outreach.enabled` to true, run `up --yes`.
4. **Chamberí cards we pull** go to Pilar (`r3-cha-*`) unless a team bids 18+ (uncommons) or 55+ (rares).
5. **Swarm public link, your yes**: `python3 tools/swarm.py serve --public --port 8778`, then `tailscale funnel --bg 8778`.

Known gaps (not fixed): slow broker matches can consume a tick; a book can be filed under the next tick. Dealers and desk share 5 requests/s: on `rate_limited`, stagger the steps. A step that cannot wait out a cooloff exits 8: re-run `up --yes` after it. A dealer run can overlap a wave; its accepts wait.

## Sunday timeline: the organisers' published schedule, Madrid time (THE reference)

- **08:55** `up --yes`. **09:00** doors; 09:01 `status`; 09:05 pace check (pre-flight), item 3.
- **Market Tests, hands off:** 09:39 (hard), 09:49, 10:49, 11:49, 13:49.
- **10:39** Round 3 and Chamberí; ladder resets. **10:40** +150 P; the dealers start by themselves.
- **11:29 to 11:34** the duel bot starts (10 game minutes early). **11:39** Duels III: hands off. **12:30** read-out.
- **13:30 decision:** only if SAL-10 is still missing and the desk has no outstanding bid, buy it from Los Pícaros by hand (about 56): `python3 agent/chato.py run --dealer picaros --only SAL-10 --cap 88 --reserve 40 --max-deals 1`. Check the structured `give` first (tick 1385: they named SAL-09 in a SAL-10 thread).
- **14:03** finale warning: last moment to change anything. **14:09** Grand Final, NPC stalls close: hands off. **14:36** freeze warning; **14:39** scores freeze.
- **14:50** Hector refreshes the pitch numbers. **15:00** close, pitch; `tmux kill-session -t factory`.

`factory plan` prints wall times marked `+`: estimates from the game clock, up to an hour off (the 12:30 pause is not modelled). Bots act on game events, never on them; the 09:05 check compares them with 09:39.

## Stop rules

- Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot. Parameters change only through the factory, at a restart.
- Restart one bot: `tmux kill-window -t factory:<name>`, then `up --yes`.
- Any spend outside a configured step, or any message to another team, needs Hector's or your yes.
