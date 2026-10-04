# Sunday night handoff (Sat 3 to Sun 4 Oct)

> **Read this first · updated 03:55 Madrid**
> - **Merged:** #62 evals, #63 broker 15 s pace, #64 announce fix, #65 Market Test memo, #67 Open Bazaar, #69 dealer ladder steps, #72 Duels III params.
> - **Open:** #70 desk page mode (not in by 08:00: pre-flight fallback), #71 analyst, #68 pitch (bots do not need them).

**For Thiago, 07:00, five minutes.** No key entered a model's context; nothing was sent or spent outside review. Next: the [pre-flight](sunday-preflight.md) at 08:40.

## Thiago's priorities, confirmed tonight

1. **Market Test first.** 5 left, the first 2 count for Saturday; broker live at 09:00.
2. **Money into deals.** About 20 P surplus a deal, 40 P in reserve, many teams, dealer slots filled.
3. **Duels: keep it.** Duels II: 29 of 33 deals, none below our limit.

## What the night built, and why

- **Duels III params** (#72): Duels II blend, `days_best buyer:0,seller:10`, F4 `last_while_moving` **off** (a slow-response race lets it block a late accept). The 06:45 search verdict (`docs/duel-lab/duels3-search/`) should say "incumbent stays"; no params swap after 08:00. At 11:39 the first `days_meaning` lines must match Saturday's; if not, delete `days_best` and restart the duel bot.
- **Broker:** `--policy stall` all day; `maxpairs` lost everywhere and the overnight search (none confirmed) agrees. Verdict 06:45: `evals/broker-search/`.
- **Open Bazaar** (#67): the matchmaker writes who-needs-which-card every 2 minutes from 08:55; the announcer posts one match every 12 minutes from 09:00 (own Market Test silence; nothing without a match); `outreach` stays off until a human flips it.
- **Ladder steps** (#69): Abuela buys RET uncommons, Pícaros two RET rares, Pilar resells.
- **Page buy** (#70): from 09:00 the desk bids 80 rising to 110 for SAL-10, our last Salamanca page card, from a team (only a team copy pays the page bonus; dealer SAL-10 steps stay off).

## What runs where

- **Mini (keyed; `up --yes`, in this order):** feed recorder, `logs_push`, broker, market desk (page mode), matchmaker (keyless writer), announcer, watchdog, then the duel bot (before each wave) and the dealer steps (after the +150 P): your "broker first, then the duel bot".
- **Pulling:** your doc says no auto-pull, Hector says one runs: rely on neither; check 1 pulls if behind.
- **Mini → VM:** `logs_push` copies `logs/` to branch `mini/logs` every 10 minutes (never `main`; manual fallback: pre-flight check 11).
- **VM (keyless):** own feed recorder since Friday; La Celestina (public, restarted from main tonight); the analyst from 08:45; the two overnight searches until 07:45.
- **VM → humans:** the analyst writes `logs/analyst/LATEST.md` on its branch, opens a PR per proposal and posts five lines on the team bus (issue #25) at each trigger, signed `FROM: wp10-sunday-analyst`.
- **Human only:** the 09:05 outreach test thread (key), enabling `outreach`, applying any analyst recommendation (merge, pull, restart one bot), the pitch.

## What needs you (or Hector)

1. **Telegram notifier**, after the 08:00 freeze: in `tools/factory_sunday.json` replace `"notify_cmd": null` with this line:
   ```json
   "notify_cmd": ["/bin/bash", "-c", "set -a; . ~/.config/telegram-notify.env; set +a; curl -sS -m 30 -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=${TELEGRAM_CHAT_ID}\" --data-urlencode \"text=$1\" > /dev/null", "notify"],
   ```
2. **Open both held packs before 10:39**, your yes (later pulls can include Chamberí cards), never while a dealer step runs.
3. **Outreach test thread, 09:05, your yes.** Read it: `python3 tools/outreach.py plan`. Send one: `python3 tools/outreach.py run --yes --max-teams 1`. If that team lists, accepts or trades the named card within 40 ticks, set `outreach.enabled` to true and run `up --yes`.
4. **Chamberí cards we pull** go to Pilar (`r3-cha-*`) unless a team bids 18+ (uncommons) or 55+ (rares).
5. **Swarm view public link, your yes**: `python3 tools/swarm.py serve --public --port 8778`, then `tailscale funnel --bg 8778`.

Known gaps (not fixed): a batch of slow broker matches can consume a tick; a book can be filed under the next tick. Four dealers and the desk share the key's 5 requests/s: on `rate_limited`, stagger the steps. A step that cannot wait out a cooloff exits 8 and shows as failed: re-run `up --yes` after it; edit no params.

## Sunday timeline (Madrid, organisers' table)

- **08:55** `up --yes`. **09:00** doors; 09:01 `status`; 09:05 clock-speed read, item 3.
- **Market Tests, hands off:** 09:39 (hard), 09:49, 10:49, 11:49, 13:49.
- **10:39** Round 3 Chamberí, ladder resets. **10:40** +150 P; the dealers start by themselves.
- **11:29** duel bot starts. **11:39** Duels III (2 rounds of 34): hands off. **12:30** read-out.
- **13:30 decision:** no team has sold us SAL-10? Buy it from Los Pícaros by hand (about 56): `python3 agent/chato.py run --dealer picaros --only SAL-10 --cap 88`. Check the structured `give` first (at tick 1385 they named SAL-09 in a SAL-10 thread).
- **14:03** finale warning: last moment to change anything. **14:09** Final: hands off.
- **14:39** scores freeze. **14:50** Hector refreshes the pitch numbers. **15:00** pitch; `tmux kill-session -t factory`.

These times assume two game hours per wall hour; `plan`'s wall column may read twice too far (pre-flight, 09:05).

## Stop rules

- Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot. Parameters change only through the factory, at a bot's next restart.
- Restart one bot: `tmux kill-window -t factory:<name>`, then `up --yes`.
- Any spend outside a configured step, or any message to another team, needs Hector's or your yes.
