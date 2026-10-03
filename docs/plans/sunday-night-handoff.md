# Sunday night handoff (Sat 3 to Sun 4 Oct)

**For Thiago, 07:00, five minutes.** Nothing was sent, spent or merged outside the review gate overnight, and the team key never entered a model's context. Updated «FILL: time»; `main` head «FILL: sha». Then run [`sunday-preflight.md`](sunday-preflight.md) at 08:40.

## Thiago's priorities, confirmed tonight

1. **Market Test first.** 5 left, the first 2 count for Saturday; broker live at 09:00.
2. **Money into deals.** About 20 P surplus per deal, 40 P kept in reserve, spread over teams, dealer slots filled.
3. **Duels: keep it.** Duels II got 29 of 33 deals, none below our limit.

## What the night built, and why

- **Duels III params** (WP1): `--params` for the new wave (price and delivery day, 12-tick duels, decay 0.10). «FILL wp1: gain, file».
- **Broker for the hard Market Test** (WP2): 12 firmer, more impatient traders at 09:39 (Saturday's b36 matched 0 and dropped 15). The new `maxpairs` policy lost everywhere, so the broker stays on `--policy stall` all day.
- **Matchmaker and outreach** (WP3): finds the card another team is missing and says so on the feed (the organisers' hint: that attracts trades, free stalls do not). «FILL wp3».
- **Ladder lines** (WP4): the dealer steps for Round 3, when the ladder resets (best 3 deals per level, empty slot 0). «FILL wp4».
- **Evals** (WP7) and **factory** (WP5): offline agent checks; dealers on, a wider duel window, the pre-flight page.

## Pull requests

| PR | What | State |
|---|---|---|
| «FILL» | WP1 duels params | «FILL» |
| «FILL» | WP2 `maxpairs` (not used) | «FILL» |
| «FILL» | WP3 matchmaker | «FILL» |
| «FILL» | WP4 ladder lines | «FILL» |
| #62 | WP7 evals | merged (b7b20ce) |
| #63 | broker pace at 15 s | being fixed, merges later |
| #66 | WP5 factory, pre-flight, this page | open |

## On the Mini

**Pulling.** Your Sunday doc says the Mini has no auto-pull; Hector says you enabled one later tonight. Rely on neither: pre-flight check 1 compares `~/bazaar` with `origin/main` and pulls if behind, before `up`. A pull restarts nothing. The factory starts everything fresh at 08:55: feed and watchdog, broker, the duel bot (10 game minutes before each wave), Abuela and Chato (a minute after the +150 P). That is your "broker first, then the duel bot": start nothing by hand beside it. `~/bazaar-dashboard` is a separate copy, updated only by `tools/deploy_mini.sh` from a Mac «FILL: stale or not». `plan` shows the duel params file `MISSING` until WP1 merges.

## What needs you (or Hector)

1. **Telegram notifier**, after the 08:00 freeze: in `tools/factory_sunday.json` replace `"notify_cmd": null` with this line (it reuses the env file the tunnel agent reads; the factory appends the alert as the last argument and never sees the token):
   ```json
   "notify_cmd": ["/bin/bash", "-c", "set -a; . ~/.config/telegram-notify.env; set +a; curl -sS -m 30 -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=${TELEGRAM_CHAT_ID}\" --data-urlencode \"text=$1\" > /dev/null", "notify"],
   ```
2. **Matchmaker test thread, 09:05, your yes**: one real message to one team. «FILL wp3: command».
3. **Swarm view public link, your yes**: `python3 tools/swarm.py serve --public --port 8778`, then `tailscale funnel --bg 8778`. Never funnel the private view (8777).
4. **Ernesto level-5 play, Hector's yes**, not given yet.
5. **By hand, not a service:** `tools/announce.py` (public feed, broker key). Its Market Test silence fix (`fix/announce-gate-memory`) is not on `main`; its missing-cards list dates from Saturday. Read-only: `python3 tools/announce.py plan`.

## Sunday timeline (Madrid, organisers' table)

- **08:55** `up --yes`.
- **09:00** doors, 15 s ticks. 09:01 `status`; 09:05 clock-speed read, then item 2.
- **Market Tests, hands off:** 09:39 (hard), 09:49, 10:49, 11:49, 13:49. The first two count for Saturday.
- **10:39** Round 3 Chamberí, ladder resets.
- **10:40** +150 P; dealers start by themselves a minute later. Read their results by 10:55 «FILL wp4: next step».
- **11:29** duel bot starts by itself; `status` shows duel `RUNNING`.
- **11:39** Duels III (2 rounds of 34 duels, 12 ticks each): hands off until it ends.
- **12:30** read-out: read Duels III; Final changes go through the factory.
- **14:03** finale warning: last moment to change anything. **14:09** Final, NPC stalls close: hands off.
- **14:39** scores freeze. **14:50** Hector refreshes the pitch numbers. **15:00** close and pitch; `tmux kill-session -t factory`.

These times fit a game clock at two game hours per wall hour from Saturday's close (13.37 h), with a pause near 12:30; `plan`'s wall column assumes one for one and may read twice too far. The bots gate on game hours, so they are right either way. The pre-flight measures the speed at 09:05: trust this table if it says 2.0.

## Stop rules

- Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot.
- Live parameters change only through the factory: edit `tools/factory_sunday.json` or the params file; the change lands when that bot restarts, between waves.
- Restart one bot: `tmux kill-window -t factory:<name>`, then `python3 tools/factory.py up --yes`.
- Any spend outside a configured dealer step, and any message to another team, needs a yes from Hector or you.
