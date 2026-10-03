# Sunday runbook: the factory

Sunday 4 October, doors 09:00 to 15:00 Madrid, 15 s ticks. Everything runs **on the Mac Mini** from `~/bazaar`, started by one command. `tools/factory.py` reads the live clock and schedule, starts each bot in its own window of the tmux session `factory` when its gate opens, restarts it, and reports health. What it starts and with which flags is data in `tools/factory_sunday.json`.

## Saturday night (before you sleep)

1. Pull `main` on the Mini once the open pull requests are merged. **Pull request #35 (dealer bots: duel lock checked before every accept, pause-safe waits, distinct exit statuses) is a prerequisite for the dealer runs**: without it, keep `abuela`, `chato` and `pilar` off. Hector's duel rewrite is the other one.
2. Clear every `todo` in `tools/factory_sunday.json`: `python3 tools/factory.py plan` prints each one under its command. The duel params file must exist: `plan` says `MISSING input file` and `up` refuses the duel until it does.
3. Set `notify_cmd` to the Mini's Telegram notifier, so the watchdog can reach you.
4. Stop Saturday's hand-started bots (the broker loop, gate scripts, desks) once the doors close. `plan` lists any bot still running outside the factory (python, `python -m`, or a shell loop running it), `up` refuses it, and a keeper never launches while one runs. A shell that merely mentions the command (an editor, a grep) can also be flagged: check the pid it names.

## 08:50 read, 08:55 start

```bash
cd ~/bazaar && python3 tools/factory.py plan
```

Read it top to bottom: the clock line, the schedule with wall times, every command, every `TODO` and `ALREADY RUNNING` line. Then the single start command:

```bash
cd ~/bazaar && python3 tools/factory.py up --yes
```

It claims each process on the team bus (`tools/bus.py claim <name> --where mini`), refuses anything already running, held by someone else, or missing an input file, and opens one tmux window per process. If the bus claim fails (GitHub down), nothing starts: say so in the team chat, then run `up --yes --no-bus`. Starting before 09:00 is safe: every gate waits for the doors.

## 09:00 check

```bash
python3 tools/factory.py status
tmux attach -t factory          # one window per bot; detach with Ctrl-b d
```

Expected at 09:01:

| Process | Expected line |
|---|---|
| feed | `RUNNING`, log a few seconds old |
| broker | `RUNNING`, log under a minute old |
| duel | `WAITING`, next duel wave at 18.650 h |
| abuela, chato | `WAITING`, waiting for grant_all |
| pilar | `DONE`: both its steps are off until someone fills them in |
| watchdog | `RUNNING` |

At 09:05 check the leaderboard `rounds` to confirm Saturday's round still counts until Round 3 starts.

## Timeline (game hours from the schedule)

Wall times come from `plan`: the game clock stops during any pause, so every pause moves the later events (Saturday's lunch pause already moved Sunday's events by more than half an hour). The factory gates on game hours, so a pause only delays it.

| Game hour | Event | What the factory does |
|---|---|---|
| doors open (09:00) | Sunday opens, 15 s ticks | broker starts (feed and watchdog run from 08:55); dealers and duels keep waiting. No bot launches or restarts while the clock is paused |
| 16.65 | Round 3 starts, Chamberí released | nothing yet: the ladder work waits for the cash |
| 16.70 | 150 P allowance | one minute later: Abuela slots 1-3 and the Chato rare start, one process per dealer |
| 17.00 | Market Test (16 ticks) | broker matches; watchdog checks dropped and matched |
| 18.45 | 12 min before Duels III | no new dealer run starts from here (a live one finishes) |
| 18.48 | 10 min before Duels III | duel run starts: `--duel-ticks 12` from the schedule, `--late-poll 4`, `--until` closing time + 5 min |
| 18.65 | Duels III (2 rounds, 12-tick duels, decay 0.1, max 4) | dealer runs held while `results/duel.lock` is fresh |
| 19.00, 21.00 | Market Tests | as at 17.00 |
| 21.45 | finale warning | nothing |
| 21.65 | The Final (12-tick duels) and the dealer stalls close | a fresh duel run 10 min before, but only if the wave projects inside opening hours (rechecked every loop) |
| closing time | The Bazaar closes | gates close; keepers wait |

As of Saturday 14:30 the Final at 21.65 fell after Sunday's 15:00 close because of the lunch pause. `plan` marks it `OUTSIDE OPENING HOURS` until the organisers move it, and the factory follows whatever the schedule says.

## Alerts and the one action for each

The watchdog window runs `status --notify --every 60` and sends the problem text when it changes, and "all clear again" when it clears.

| Alert | Meaning | Action |
|---|---|---|
| `<name> is down` | its keeper is not running (window killed, keeper crashed) | `python3 tools/factory.py up --yes` (starts only what is missing) |
| `<name> exited rc=N, restart K pending` | a broker, feed or duel run crashed; the keeper restarts it in 5 to 120 s | read the end of `results/factory/<name>.out`; if it repeats, post it on the bus |
| `<dealer>: step <label> exited rc=N: not relaunched` | a dealer run ended badly (lock timeout, close failed, all buys blocked, a crash); the keeper stopped | read `logs/<dealer>/<date>.jsonl`, decide, then `up --yes` (reruns that step) |
| `<name>: keeper says running but child pid N is gone` | the bot died and its keeper has not noticed, or the pid now belongs to something else | `tmux kill-window -t factory:<name>` then `up --yes` |
| `<name>: no log at <path> after N s` | the bot runs but never wrote its log (wrong directory, stuck before its first line) | look at its window; if stuck, kill the window and `up --yes` |
| `<name>: another copy runs outside the factory (pid N)` | a hand-started copy is running; the keeper will not launch beside it | stop that pid (or leave it and kill the factory window) |
| `Market Test at H not on our book after N ticks` | the schedule says a test is on, our broker never saw it | check the broker window and that v20 is open; post it on the bus |
| `<name> log silent for N s` | bot alive but not logging for 4 ticks (broker) or 20 ticks (feed): hung call or frozen loop | `tmux kill-window -t factory:<name>` then `up --yes` |
| `broker dropped N matches in Market Test bXX` | Saturday's b36 failure: the broker saw pairs and refused them | read the `why` of the last `dropped` line in `logs/broker/<date>.jsonl` and post it on the bus; a restart does not fix a policy bug |
| `broker has no match in Market Test bXX after N ticks` | bench offers on our book, nothing sent | look at the broker window for `refused` or `send_error`; post it on the bus |
| `<dealer> dealer run live while the clock is paused` | a dealer run is live across a pause | none with #35 merged (its waits are pause-safe); without it, watch the thread |
| `clock unreachable` | game server or network down | `curl -s https://bazaar.causaprima.ai/api/clock`; keepers wait on their own |

At `up`, `REFUSE <name>: already running outside the factory (pid N)` means an old copy is still running: stop it, then run `up --yes` again.

## Changing things during the day

- Edit `tools/factory_sunday.json`. Each keeper re-reads it before every start, so a change applies to the next start.
- To run a step that was off (the Pilar resale once the RET asset ids are known, Chato slots 2-3 once the cash is there): fill in its values, set `"enabled": true`, run `up --yes`. Steps already done today are not rerun.
- To stop one bot: `tmux kill-window -t factory:<name>`. Its keeper stops the bot, releases its lock and the bus claim.
- Bots get no key from the factory's environment, even one exported in the shell: they read `.env`.
- After 15:00: `tmux kill-session -t factory`.

## Decisions that stay with people

- Page-completing team buys (LAT-03, SAL-02, MAL-05 style), the LAT-09 or LAV-10 bids, and any other spend that is not a configured dealer step.
- The reciprocal venue cross-listing deal with another team, and any message to another team. The owner sends all outreach.
- Asking the desk whether venue v20 can switch to auto.
- Turning on `rastro_seller` or `market_desk` (both off by default), and every `todo` in the config.

## Dry run

```bash
python3 tools/factory.py plan          # read-only: keyless GETs only
python3 tools/factory.py up            # the same as plan; nothing starts without --yes
python3 tools/factory.py status        # exit 1 if anything required is down or failing
python3 -m unittest tests.test_factory
```
