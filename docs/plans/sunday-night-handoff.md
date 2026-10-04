# Sunday night handoff (Sat 3 to Sun 4 Oct)

**For Thiago, 07:00, five minutes.** Nothing was sent, spent or merged outside the review gate; no key entered a model's context. Updated «FILL: time»; `main` head «FILL: sha». Then run the [pre-flight](sunday-preflight.md) at 08:40.

## Thiago's priorities, confirmed tonight

1. **Market Test first.** 5 left, the first 2 count for Saturday; broker live at 09:00.
2. **Money into deals.** About 20 P surplus per deal, 40 P in reserve, many teams, dealer slots filled.
3. **Duels: keep it.** Duels II: 29 of 33 deals, none below our limit.

## What the night built, and why (with PR state)

- **Duels III params** (WP1, «FILL: PR, state»): `--params` for the new wave (price and day, 12 ticks, decay 0.10). «FILL wp1: gain, file».
- **Broker** (WP2, #63 and #65 merged): `--policy stall` all day; `maxpairs` lost everywhere.
- **Matchmaker, outreach** (WP3, «FILL: PR, state»): finds the card another team misses and says so on the feed. «FILL wp3».
- **Ladder steps** (WP4, #69 under review, 4fa627b): Abuela buys RET uncommons, Pícaros the two RET rares, Pilar resells them. No Ernesto level-5 play (decided).
- **Page buy** (WP8, #70 under review, 361be93): the desk bids for SAL-10, the last card of our Salamanca page, from a team on El Rastro: 80 rising to 110 over 64 ticks, from 09:00. A team copy pays the page bonus, a dealer copy does not, so dealer SAL-10 steps stay off. #70 also fixed the desk's tape and bid churn.
- **Evals** (WP7, #62 merged); **factory** (WP5, #66): dealers on, pre-flight page. #66 merges after #69 and #70 (it runs `--dealer picaros` and `--page`).

## On the Mini

**Pulling.** Your Sunday doc says no auto-pull; Hector says you enabled one. Rely on neither: pre-flight check 1 compares `~/bazaar` with `origin/main` and pulls if behind. A pull restarts nothing. The factory starts feed, watchdog, broker, market desk, then the duel bot (10 game minutes before each wave) and the dealers (after the +150 P): your "broker first, then the duel bot". Start nothing by hand. `~/bazaar-dashboard` is a separate copy, updated only by `tools/deploy_mini.sh` from a Mac «FILL: stale or not». `plan` says `MISSING` for the duel params until WP1 merges.

## What needs you (or Hector)

1. **Telegram notifier**, after the 08:00 freeze: in `tools/factory_sunday.json` replace `"notify_cmd": null` with this line (it reuses the tunnel agent's env file; the factory never sees the token):
   ```json
   "notify_cmd": ["/bin/bash", "-c", "set -a; . ~/.config/telegram-notify.env; set +a; curl -sS -m 30 -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=${TELEGRAM_CHAT_ID}\" --data-urlencode \"text=$1\" > /dev/null", "notify"],
   ```
2. **Open both held packs before 10:39**, your yes (it uses the key): later pulls can include Chamberí cards.
3. **Matchmaker test thread, 09:05, your yes**: one real message to one team. «FILL wp3: command».
4. **Push `logs/` to `main` about every 15 minutes** from the Mini session all day: the VM analyst reads them.
5. **Chamberí cards we pull**: uncommons and rares go to Pilar (WP4's `r3-cha-*` steps) unless a team bids 18+ / 55+.
6. **Swarm view public link, your yes**: `python3 tools/swarm.py serve --public --port 8778`, then `tailscale funnel --bg 8778`.
7. **By hand, not a service:** `tools/announce.py` (its silence fix is not on `main`; its missing-cards list is Saturday's).

Known gaps (documented, not fixed). Broker, from #63's review: a batch of slow matches can consume a tick; a book can be filed under the next tick. Four dealer bots plus the desk share the key's 5 requests/s (each dealer now reads `/api/me` once per decision): if `rate_limited` shows in a dealer log, stagger the steps.

## Sunday timeline (Madrid, organisers' table)

- **08:55** `up --yes`. **09:00** doors; 09:01 `status`; 09:05 clock-speed read, then item 3.
- **Market Tests, hands off:** 09:39 (hard), 09:49, 10:49, 11:49, 13:49. The first two count for Saturday.
- **10:39** Round 3 Chamberí, ladder resets. **10:40** +150 P; the dealers start by themselves (Pilar's resales after 16 game minutes). Read their results by 10:55.
- **11:29** duel bot starts by itself. **11:39** Duels III (2 rounds of 34, 12 ticks each): hands off until it ends.
- **12:30** read-out of Duels III.
- **13:30 decision:** if no team has sold us SAL-10, buy it from Los Pícaros by hand (about 56): `python3 agent/chato.py run --dealer picaros --only SAL-10 --cap 88`. Check the structured `give` first (at tick 1385 they named SAL-09 in a SAL-10 thread). It fills a Pícaros slot but pays no page bonus.
- **14:03** finale warning: last moment to change anything. **14:09** Final, NPC stalls close: hands off.
- **14:39** scores freeze. **14:50** Hector refreshes the pitch numbers. **15:00** pitch; `tmux kill-session -t factory`.

These times assume a game clock at two game hours per wall hour; `plan`'s wall column assumes one and may read twice too far (bots gate on game hours: right either way). The pre-flight measures it at 09:05.

## Stop rules

- Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot.
- Live parameters change only through the factory: edit the config or params file; it lands at that bot's next restart, between waves.
- Restart one bot: `tmux kill-window -t factory:<name>`, then `up --yes`.
- Any spend outside a configured step, and any message to another team, needs a yes from Hector or you.
