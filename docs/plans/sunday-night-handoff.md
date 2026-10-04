# Sunday night handoff (Sat 3 to Sun 4 Oct)

> **Read this first · updated 02:55 Madrid** (`main` at e41a21a; fallbacks: pre-flight page)
> - **Merged:** #62 evals, #63 broker 15 s pace, #65 Market Test memo, #69 dealer limits, cooloff wait, Round 3 ladder steps.
> - **#72 duels, open.** Not in by 08:00: the duel bot will not start; point `duel.params` at `docs/duel-lab/duel-params-duels2-final.json`.
> - **#70 desk page mode, open.** Not in: use the pre-flight fallback (desk without page flags, or off).
> - **#64 announce fix, #67 Open Bazaar, open.** Not in: no matchmaker or 09:05 thread; keep `announce.py` off.
> - **#71 analyst, #68 pitch, open.** Not in: the bots do not need them.

**For Thiago, 07:00, five minutes.** Nothing was sent or spent outside the review gate; no key entered a model's context. Then run the [pre-flight](sunday-preflight.md) at 08:40.

## Thiago's priorities, confirmed tonight

1. **Market Test first.** 5 left, the first 2 count for Saturday; broker live at 09:00.
2. **Money into deals.** About 20 P surplus a deal, 40 P in reserve, many teams, dealer slots filled.
3. **Duels: keep it.** Duels II: 29 of 33 deals, none below our limit.

## What the night built, and why

- **Duels III params** (#72): Duels II blend, `days_best buyer:0,seller:10`, F4 `last_while_moving` **off** (arena +0.008 per duel, but in a slow-response race an F4 message can block a late accept). The 06:45 search verdict is in `docs/duel-lab/duels3-search/` (`vm/wp10-duel-search`): a candidate must win by more than 2 SE on test without losing a gate, and the best two fail the D-1 stress: expect "incumbent stays". No params swap after 08:00. At 11:39 the first `days_meaning` lines must match Saturday's; if not, delete `days_best` and restart the duel bot. Known race: a rival replaces its offer between our decision and our POST (`accept_mismatch`).
- **Broker:** `--policy stall` all day; `maxpairs` lost everywhere and the overnight search (120 candidates, none confirmed; perfect leave flags gain +0.025) agrees. Verdict 06:45 in `evals/broker-search/` (`vm/wp11-broker-search`).
- **Matchmaker, outreach** (#67): finds the card another team misses, says so on the feed. «FILL wp3».
- **Ladder steps** (#69): Abuela buys RET uncommons, Pícaros two RET rares, Pilar resells them. No Ernesto play.
- **Page buy** (#70): from 09:00 the desk bids for SAL-10, our last Salamanca page card, from a team: 80 rising to 110. Only a team copy pays the page bonus, so dealer SAL-10 steps stay off.

## On the Mini

Your Sunday doc says no auto-pull; Hector says you enabled one. Rely on neither: pre-flight check 1 pulls if behind. The factory starts feed, watchdog, broker and desk, then the duel bot (before each wave) and the dealers (after the +150 P): your "broker first, then the duel bot".

## What needs you (or Hector)

1. **Telegram notifier**, after the 08:00 freeze: in `tools/factory_sunday.json` replace `"notify_cmd": null` with this line (it reuses the tunnel agent's env file):
   ```json
   "notify_cmd": ["/bin/bash", "-c", "set -a; . ~/.config/telegram-notify.env; set +a; curl -sS -m 30 -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=${TELEGRAM_CHAT_ID}\" --data-urlencode \"text=$1\" > /dev/null", "notify"],
   ```
2. **Open both held packs before 10:39**, your yes (later pulls can include Chamberí cards), and never while a dealer step runs.
3. **Matchmaker test thread, 09:05, your yes**: one real message to one team. «FILL wp3: command».
4. **Push `logs/` to `main` every 15 minutes or so** from the Mini session: the VM analyst reads them.
5. **Chamberí cards we pull** go to Pilar (`r3-cha-*` steps) unless a team bids 18+ (uncommons) or 55+ (rares).
6. **Swarm view public link, your yes**: `python3 tools/swarm.py serve --public --port 8778`, then `tailscale funnel --bg 8778`.

Known gaps (not fixed): a batch of slow broker matches can consume a tick; a book can be filed under the next tick. Four dealers and the desk share the key's 5 requests/s: on `rate_limited` in a dealer log, stagger the steps. A step that cannot wait out a cooloff exits 8 and shows as failed: re-run `up --yes` once it is over; do not edit params.

## Sunday timeline (Madrid, organisers' table)

- **08:55** `up --yes`. **09:00** doors; 09:01 `status`; 09:05 clock-speed read, then item 3.
- **Market Tests, hands off:** 09:39 (hard), 09:49, 10:49, 11:49, 13:49.
- **10:39** Round 3 Chamberí, ladder resets. **10:40** +150 P; the dealers start by themselves.
- **11:29** duel bot starts. **11:39** Duels III (2 rounds of 34): hands off. **12:30** read-out.
- **13:30 decision:** no team has sold us SAL-10? Buy it from Los Pícaros by hand (about 56): `python3 agent/chato.py run --dealer picaros --only SAL-10 --cap 88`. Check the structured `give` first (at tick 1385 they named SAL-09 in a SAL-10 thread). No page bonus.
- **14:03** finale warning: last moment to change anything. **14:09** Final, NPC stalls close: hands off.
- **14:39** scores freeze. **14:50** Hector refreshes the pitch numbers. **15:00** pitch; `tmux kill-session -t factory`.

These times assume two game hours per wall hour; `plan`'s wall column may read twice too far. The pre-flight measures the speed at 09:05.

## Stop rules

- Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot. Parameters change only through the factory, at that bot's next restart.
- Restart one bot: `tmux kill-window -t factory:<name>`, then `up --yes`.
- Any spend outside a configured step, or any message to another team, needs Hector's or your yes.
