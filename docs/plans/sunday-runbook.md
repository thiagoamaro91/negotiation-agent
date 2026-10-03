# Sunday runbook: the factory

Sunday 4 October, doors 09:00 to 15:00 Madrid, 15 s ticks. Everything runs **on the Mac Mini** from `~/bazaar`, started by one command. `tools/factory.py` reads the live clock and schedule, starts the feed recorder, the broker, the duel bot, the dealer bots and the watchdog in their own windows of the tmux session `factory` when their gates open, restarts them, and reports health. What it starts and with which flags is data in `tools/factory_sunday.json`.

**The dealer bots (Abuela, Chato, Pilar) are on** since their safety fixes merged (#35 and #38: duel lock checked before every accept, pause-safe waits, distinct exit statuses). Each runs its enabled steps one after the other, a step starting after its gate (for the Round 3 steps: one minute after the +150 P allowance, never within 25 game minutes of a duel wave). A dealer with no enabled step is skipped by `up`. `rastro_seller` and `market_desk` stay off. The 08:40 checks and the expected 09:01 table are on [`sunday-preflight.md`](sunday-preflight.md); what changed overnight is in [`sunday-night-handoff.md`](sunday-night-handoff.md).

## Saturday night (before you sleep)

1. Pull `main` on the Mini once the open pull requests are merged (the Mini also pulls after every merge, and never restarts a bot).
2. Clear every `todo` in `tools/factory_sunday.json`: `python3 tools/factory.py plan` prints each one under its command. The duel params file must exist: `plan` says `MISSING input file` and `up` refuses the duel until it does.
3. Set `notify_cmd` to the Mini's Telegram notifier, so the watchdog can reach you.
4. Stop Saturday's hand-started bots (the broker loop, gate scripts, desks) once the doors close, **by hand**: `ps -ax | grep -E 'broker_loop|pilar_gate|_gate.sh'`. The factory recognises a bot by its script name plus its mode (`broker.py run`, also `cd agent; python3 broker.py run`, `python3 -m agent.broker run`, and a `bash -c` loop around them). It never opens a file to look inside a script, so a restart loop kept in a script file is visible only while its child runs. `plan` lists what it sees, `up` refuses it, and a keeper never launches beside it. A shell that merely mentions the command (a grep) can also be flagged: check the pid it names.
5. Check the bus board: `python3 tools/bus.py board`. The bus tells people apart by GitHub login only, so the factory also reads the board's machine column and refuses a process claimed on another machine. Two machines on the same login that run `up` at the same moment can still both pass: run the factory on the Mini only.

## 08:50 read, 08:55 start

```bash
cd ~/bazaar && python3 tools/factory.py plan
```

Read it top to bottom: the clock line, the schedule with wall times, every command, every `TODO` and `ALREADY RUNNING` line. Then the single start command:

```bash
cd ~/bazaar && python3 tools/factory.py up --yes
```

It reads the bus board, claims each process (`tools/bus.py --session <its session> claim <name> --where mini`), refuses anything already running, claimed on another machine, held by someone else, or missing an input file, prints the `off` entries with their reason, and opens one tmux window per process it starts. If the board or the claim cannot be read (GitHub down), nothing starts: say so in the team chat, then run `up --yes --no-bus`. Starting before 09:00 is safe: every gate waits for the doors and a running clock, and a clock response without explicit `doors` and `paused` values keeps every gate closed.

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
| abuela, chato | `WAITING`, `waiting for grant_all at 16.717 h` (their Round 3 steps) |
| pilar | `DONE` while it has no enabled step |
| watchdog | `RUNNING` |

At 09:05 check the leaderboard `rounds` to confirm Saturday's round still counts until Round 3 starts.

## Timeline (game hours from the schedule)

Wall times come from `plan`: the game clock stops during any pause, so every pause moves the later events (Saturday's lunch pause already moved Sunday's events by more than half an hour). The factory gates on game hours, so a pause only delays it.

| Game hour | Event | What the factory does |
|---|---|---|
| doors open (09:00) | Sunday opens, 15 s ticks | broker starts (feed and watchdog run from 08:55); dealers and duels keep waiting. No bot launches or restarts while the clock is paused |
| 14.65, 15.00 | The hard Market Test and the Market Test (they count in Saturday's round) | broker matches; watchdog checks dropped and matched |
| 16.65 | Round 3 starts, Chamberí released | nothing yet: the ladder work waits for the cash |
| 16.70 | 150 P allowance | the dealer steps with `after_event: grant_all` start one minute later (Abuela slots, Chato rare); Pilar only if a step is enabled |
| 17.00 | Market Test (16 ticks) | broker matches; watchdog checks dropped and matched |
| 18.23 | 25 game min before Duels III | no new dealer run from here (`duel_quiet_min`) |
| 18.48 | 10 min before Duels III | duel run starts: `--duel-ticks 12` from the schedule, `--late-poll 4`, `--until` closing time + 5 min |
| 18.65 | Duels III (2 rounds, 12-tick duels, decay 0.1, max 4) | status checks the duel log while the wave is live: something logged since it began, and no silence over 8 ticks while our duel lock exists |
| 19.00, 21.00 | Market Tests | as at 17.00 |
| 21.45 | finale warning | nothing |
| 21.65 | The Final (12-tick duels) and the dealer stalls close | a fresh duel run 10 min before, but only if the wave projects inside opening hours (rechecked every loop) |
| closing time | The Bazaar closes | gates close; keepers wait |

The clock closed Saturday at 13.37 h, not at the schedule's 16.65 h, so Sunday's events land earlier or later in wall time depending on the clock's speed (see the 09:05 read in the pre-flight page). At Sunday 01:30 `plan` projected the Final at about 14:00, inside opening hours; it marks an event `OUTSIDE OPENING HOURS` when its projection falls past the 15:00 close (the `Scores freeze` line always does, at exactly 15:00), and the factory follows whatever the schedule says.

## Alerts and the one action for each

The watchdog window runs `status --notify --every 60` and sends a message when the set of incidents changes (an incident is the problem text without its numbers, so a growing age or counter does not resend it), and "all clear again" when it clears.

| Alert | Meaning | Action |
|---|---|---|
| `<name> is down` | its keeper is not running (window killed, keeper crashed) | `python3 tools/factory.py up --yes` (starts only what is missing) |
| `<name> exited rc=N, restart K pending` | a broker, feed or duel run crashed; the keeper restarts it in 5 to 120 s | read the end of `results/factory/<name>.out`; if it repeats, post it on the bus |
| `<dealer>: step <label> exited rc=N: not relaunched` | a dealer run ended badly (lock timeout, close failed, all buys blocked, a crash); the keeper stopped | read `logs/<dealer>/<date>.jsonl`, decide, then `up --yes` (reruns that step) |
| `<dealer>: step <label> ran N times without a deal or nothing-to-do marker` | the run exited 0 but its log shows neither a deal (`result` with status `deal`) nor an empty plan (`run_start` with `plan: []`), for example a start refused by a fresh duel lock | read the dealer window and log; rerun by hand or `up --yes` |
| `<name> is disabled in the config but still runs` | someone set `"enabled": false` while it ran; keepers stop only before a launch | `tmux kill-window -t factory:<name>` |
| `duel stale during Duels III` | the duel bot logged nothing since the wave began, or holds our duel lock with a silent log | `tmux kill-window -t factory:duel` then `up --yes` |
| `<name>: missing input <file>` (FAILED) | its params file disappeared; the keeper stopped | restore the file, then `up --yes` |
| `<name>: keeper says running but child pid N is gone` | the bot died and its keeper has not noticed, or the pid now belongs to something else | `tmux kill-window -t factory:<name>` then `up --yes` |
| `<name>: no log at <path> after N s` | the bot runs but never wrote its log (wrong directory, stuck before its first line) | look at its window; if stuck, kill the window and `up --yes` |
| `<name>: another copy runs outside the factory (pid N)` | a hand-started copy is running; the keeper will not launch beside it | stop that pid (or leave it and kill the factory window) |
| `Market Test at H not on our book after N ticks` | the schedule says a test is on, our broker never saw it | check the broker window and that v20 is open; post it on the bus |
| `<name> log silent for N s` | bot alive but not logging for 4 ticks (broker) or 20 ticks (feed): hung call or frozen loop | `tmux kill-window -t factory:<name>` then `up --yes` |
| `broker dropped N matches in Market Test bXX` | Saturday's b36 failure: the broker saw pairs and refused them | read the `why` of the last `dropped` line in `logs/broker/<date>.jsonl` and post it on the bus; a restart does not fix a policy bug |
| `broker has no match in Market Test bXX after N ticks` | bench offers on our book, nothing sent | look at the broker window for `refused` or `send_error`; post it on the bus |
| `<dealer> dealer run live while the clock is paused` | a dealer run is live across a pause | none: the dealers' waits are pause-safe since #35 |
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
