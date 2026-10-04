# Sunday pre-flight: 08:40 Madrid, on the Mac Mini

Twelve checks, one line each (check 1 also pulls when behind), then the 08:55 command. Everything here is read-only except the last command. Run it in `~/bazaar` on the Mini; no check prints a key (key checks print a count and a file mode only). If one fails and two minutes do not fix it, say so in the team chat before starting anything. The full operator page is [`sunday-runbook.md`](sunday-runbook.md); what changed overnight is in [`sunday-night-handoff.md`](sunday-night-handoff.md).

Before 08:40, once, after the 08:00 code freeze: set `notify_cmd` in `tools/factory_sunday.json` (the line is in the handoff, section "What needs you"). Without it the watchdog still prints problems in its tmux window but sends nothing to your phone.

1. **The Mini is on the `origin/main` head.** Expect `0` (no commit on `origin/main` that the Mini lacks). Do not assume an auto-pull ran (Thiago's own doc says there is none; Hector says one was enabled): if the count is not `0`, pull, then rerun this check, check 2 and the self-test (expect `OK`). If the pull refuses because of local changes, say so in the team chat; do not reset.
   ```bash
   cd ~/bazaar && git fetch -q && git log -1 --format='%h %s' && git rev-list --count HEAD..origin/main
   git pull --ff-only && python3 -m unittest tests.test_factory 2>&1 | tail -1
   ```
2. **The config has nothing open.** Expect no output. (`OUTSIDE OPENING HOURS` next to `Scores freeze` is normal; next to `Final duels` it is not. Before 09:00 the wall-time column is indicative only: it anchors on a stale `day_opens` event, and the gates use game hours. For the same reason `plan` shows `--until 23:05` on `market_desk` before 09:00 (Saturday's close); the real launch computes 15:05.)
   ```bash
   ! python3 tools/factory.py plan | grep -E 'TODO|MISSING|ALREADY RUNNING|WARNING|cannot read'
   ```
3. **Clock and doors.** Expect `closed True 1445 30.0 13.3667` (Saturday's close) before 09:00, and `open False <tick> 15.0 <hours>` after it.
   ```bash
   curl -s https://bazaar.causaprima.ai/api/clock | python3 -c "import sys,json;c=json.load(sys.stdin);print(c['doors'],c['paused'],c['tick'],c['tick_seconds'],c['t_hours'])"
   ```
4. **v20 is ours and open.** Expect `open board 0 t03`.
   ```bash
   curl -s https://bazaar.causaprima.ai/api/venues | python3 -c "import sys,json;v=[x for x in json.load(sys.stdin)['venues'] if x['venue']=='v20'][0];print(v['status'],v['rules']['mechanism'],v['fee_bps'],v['owner'])"
   ```
5. **Both keys are in place** (counts and file modes only, never values). Expect `1`, `1`, then `600` twice.
   ```bash
   cd ~/bazaar && grep -c '^BAZAAR_KEY=' .env; grep -c '^BROKER_KEY=' ~/.bazaar/broker.env; stat -f %Lp .env ~/.bazaar/broker.env
   ```
6. **No stale lock or stop file.** Expect `No such file or directory` twice. A leftover lock holds a time: if it is in the past, delete it (no duel is live at 08:40).
   ```bash
   cd ~/bazaar && ls results/duel.lock logs/state/STOP 2>&1
   ```
7. **No hand-started bot.** Expect no `ps` line, and no `bazaar` session or running `factory` window in `tmux ls`. Kill what shows (`tmux kill-session -t bazaar`, `kill <pid>`), Saturday's feed recorder included: the factory starts its own.
   ```bash
   ps -axo pid=,args= | grep -E 'agent/(broker|duel|abuela|chato|rastro_seller|market_desk)\.py|tools/(logs_push|matchmaker|announce|outreach)\.py|feed_recorder|broker_loop|_gate\.sh' | grep -v grep; tmux ls
   ```
8. **The bus board has no foreign claim on a factory name.** Expect no output. Saturday's `broker` and `duel` rows on `mini` are yours; `up` takes them over.
   ```bash
   cd ~/bazaar && python3 tools/bus.py --session thiago-mini-factory board | awk -F'|' '$2 ~ /^ *(feed|broker|duel|abuela|chato|pilar|picaros|market_desk|matchmaker|announce|logs_push|watchdog) *$/ && $4 !~ /mini/ {print "BAD:" $0}'
   ```
9. **Cash and level, from the dashboard.** Expect `cash 253 level 5 age <10 error None` (Saturday's close, ledger-checked at tick 1445; 403 after the 150 P at about 10:40 Madrid).
   ```bash
   T=$(grep '^DASH_TOKEN=' ~/bazaar-dashboard/.env | cut -d= -f2); curl -s "http://127.0.0.1:8765/data?t=$T" | python3 -c "import sys,json;d=json.load(sys.stdin);m=d['me'];print('cash',m['cash'],'level',m['level'],'age',d['age'],'error',d['error'])"
   ```
10. **The dashboard tunnel is alive.** Expect `200`. If the link changed, the tunnel agent sends the new one to your Telegram.
   ```bash
   T=$(grep '^DASH_TOKEN=' ~/bazaar-dashboard/.env | cut -d= -f2); curl -s -o /dev/null -w '%{http_code}\n' "$(cat ~/bazaar-dashboard/tunnel.url)/?t=$T"
   ```

11. **The logs push works** (08:45 Madrid). Expect `pushed <sha> <n> files` the first time, `nothing new` after, and one `refs/heads/mini/logs` line from `ls-remote`. This creates the worktree `~/bazaar/.logs-push`; the factory's `logs_push` service reuses it from 08:55 and pushes every 10 minutes. The tool is keyless, never touches `main`, and a failed push does not stop it.
   ```bash
   cd ~/bazaar && python3 tools/logs_push.py --once && git ls-remote origin mini/logs
   ```
   If it prints `push failed` (credentials, network): fix the git credentials if you can in two minutes; otherwise fall back to a manual push every 15 minutes, `cd ~/bazaar && git add logs && git commit -m "logs: $(date +%H:%M)" && git pull --rebase && git push`, and tell the VM analyst (bus post or by hand) that the logs are on `main`, not on `mini/logs`.

12. **The matchmaker board is sane** (08:50 Madrid). Expect a first number above 5 (lines), `0`, and `[]`: a board with tiers 1 to 4, no Team 3 row, none of the cards we lack. The factory's `matchmaker` service writes the same board from 08:55 and the announcer posts one match every 12 minutes from 09:00. If the board is empty, say so in the bus post and leave the announcer running: it posts nothing without matches.
   ```bash
   cd ~/bazaar && python3 tools/matchmaker.py report --live > /tmp/mm.txt; wc -l < /tmp/mm.txt; grep -c -E '\| Team 3 \|' /tmp/mm.txt; python3 -c "import re,sys; sys.path.insert(0,'tools'); import announce; t=open('/tmp/mm.txt').read(); print(sorted(c for c in announce.MISSING if re.search(r'\b'+c+r'\b', t)))"
   ```

The team key sits in `~/bazaar/.env` and the bots read it themselves; the factory never passes a key to a bot. The dashboard's duel and broker panels read the folder named by `BROKER_ROOT` in `~/bazaar-dashboard/.env`; for the factory's bots it must be `~/bazaar` (`grep '^BROKER_ROOT=' ~/bazaar-dashboard/.env`), otherwise those panels stay empty.

## If a pull request is not on `main` by 08:00 Madrid

- **#70 (desk page mode), merged.** `grep -c 'add_argument("--page",' agent/market_desk.py` must print `1`. If it prints `0`, the Mini has not pulled (check 1); the desk's page flags would be unknown and it would crash-loop. Only if it still prints `0` after a pull: in `tools/factory_sunday.json`, replace `market_desk.cmd` with the fallback below, or set `"enabled": false` to keep the cash for the dealers. SAL-10 then waits for the 13:30 decision.
  ```bash
  python3 agent/market_desk.py run --no-team-venues --no-bids --min-cash 40 --until 15:05
  ```
  As a `cmd` list: `["{python}", "-u", "agent/market_desk.py", "run", "--no-team-venues", "--no-bids", "--min-cash", "40", "--until", "{until}"]` (plain buys only, no page bid).
- **#72 (duel params), merged.** If check 2 still prints `MISSING input file docs/duel-lab/duel-params-duels3.json`, the Mini has not pulled: pull (check 1). Only if the file is truly absent from `origin/main`, set `duel.params` in the config to `docs/duel-lab/duel-params-duels2-final.json` (Duels II's set). Never copy one params file over another.

## 08:55 Madrid: start

```bash
cd ~/bazaar && python3 tools/factory.py up --yes
```

Starting before 09:00 is safe: every gate waits for open doors and a running clock. Expected output, one line per process, exit 0:

```
started feed        started broker      started duel
started abuela      skip    chato: no enabled step left to run today      started pilar      started picaros
off     rastro_seller: ...              started market_desk      started matchmaker
started announce    off     outreach: ...   started logs_push   started watchdog
```

Any `REFUSE` line names its reason. `already running outside the factory`: stop that pid and run `up --yes` again. `missing input file ...`: the duel params file is not on this checkout, pull again. `cannot read the bus board`: GitHub is down; say so in the team chat, then `up --yes --no-bus`.

## 09:01 Madrid: expected `python3 tools/factory.py status`

| Process | Expected line |
|---|---|
| feed | `RUNNING`, log a few seconds old |
| broker | `RUNNING`, log under a minute old; `Market Test bNN: matched N dropped 0` appears once a test has started |
| duel | `WAITING`, `next duel wave Duels III at 18.650 h` |
| abuela, picaros, pilar | `WAITING`, `waiting for grant_all at 16.717 h` (Abuela), `16.733 h` (Pícaros), `16.967 h` (Pilar's first resale) |
| chato | `DONE` (every step off: nothing a dealer sells is inside our value but SAL-10, and that comes from a team) |
| market_desk | `RUNNING` (page mode, SAL-10); its log line carries `"page": true` once it bids |
| matchmaker | `RUNNING` (log is `logs/matchmaker/latest.json`, rebuilt every 2 minutes) |
| announce | `WAITING` until 09:00, then `RUNNING`; its log `logs/announce/<date>.jsonl` shows `named` events once it posts (nothing without a match) |
| outreach | `off` until a human flips it after the 09:05 test thread |
| logs_push | `RUNNING`; its window (`tmux attach -t factory`) prints `pushed ...` or `nothing new` every 10 minutes |
| rastro_seller | `off` |
| watchdog | `RUNNING` |
| last line | `ok` (no `PROBLEM` lines) |

`tmux attach -t factory` shows one window per bot (detach with Ctrl-b d).

## 09:05 Madrid: the clock and the published schedule

**The reference for humans is the organisers' published Sunday schedule, in Madrid time:** doors 09:00, hard Market Test 09:39, Market Test 09:49, Round 3 and Chamberí 10:39, +150 P 10:40, Market Test 10:49, Duels III 11:39, Market Test 11:49, Market Test 13:49, finale warning 14:03, Grand Final and NPC stalls close 14:09, freeze warning 14:36, scores freeze 14:39, close 15:00. The wall times that `factory plan` prints (marked `+`) are ESTIMATES from the game clock: they use the pace the keepers measured (game hours per wall hour), do not model the pause near 12:30 (after it they read about an hour early) and can be off by up to an hour. **The bots never use them.** Every launch, gate and restart is decided in game hours from the live `/api/clock` and `/api/schedule`, re-read on every loop: the duel bot starts 10 game minutes before each wave (5 to 10 minutes of Madrid time, depending on the pace), the dealers stay 25 game minutes clear of a wave, and a pace that differs from the published one changes nothing but the wall time at which they happen.

```bash
cd ~/bazaar && python3 tools/factory.py plan | grep -E '^pace|hard Market Test'
```

Expect, from about 09:03 (the keepers need two minutes of running clock): a `pace` line that says `measured by the keepers` (about 2 game hours per wall hour) and `14.650  Sun 09:3x+ ... The hard Market Test` with the time between **09:37 and 09:41 Madrid**.

- **`pace NOT MEASURED yet`:** the clock has run less than two minutes, or the keepers are not up (`tmux ls`, then `up --yes`). Look again at 09:08.
- **The pace is about 2 and the hard Market Test reads outside 09:37 to 09:41:** the organisers moved events in `/api/schedule`. Nothing to fix: the bots follow the live schedule. Read the new times from `plan`, tell Hector, and use them instead of the table.
- **The pace is about 1:** the game clock really runs one game hour per wall hour, so the published times (Madrid) will not match the game: `plan` shows the real ones (hard Market Test about 10:17). Nothing to fix for the bots (they act on game events); tell Hector and the team chat at once and give the humans the `plan` times.

Also check that the leaderboard still shows Saturday's round as the active one until Round 3 starts (10:39 Madrid).

## What the VM analyst does at each trigger

The analyst (PR #71) reads the pushed logs, writes `logs/analyst/LATEST.md` on its own branch, opens a PR per proposal and posts five lines on the bus (issue #25). Applying anything is a human on the Mini: merge, pull, restart one bot. A duel-params candidate replaces the incumbent only if it wins by more than 2 SE on test without losing a gate; the two best of the overnight search fail the D-1 stress, so expect "incumbent stays". Known accept race: a rival replaces its offer between our decision and our POST (`accept_mismatch` in the duel log).

| Trigger | Analyst command | What it may lead to |
|---|---|---|
| a Market Test ends | `bench` | the stall stays unless `ours` wins by more than 2 SE; a restart only between tests |
| Duels III complete (about 12:35 Madrid, 68 of 68) | `duels --session 3 --matrix` | Final params only by PR plus a human restart of the duel window before 14:00 Madrid |
| each dealer step ends | `ladder` | nothing unless a slot is missing |
| every hour | `score` | nothing |

## Alerts and the one action for each

The watchdog window sends one message when its set of problems changes, and "all clear again" when it clears.

| Alert | Action |
|---|---|
| `<name> is down` | `python3 tools/factory.py up --yes` (starts only what is missing) |
| `<name> exited rc=N, restart K pending` | the keeper restarts it in 5 to 120 s; if it repeats, read the end of `results/factory/<name>.out` and post it on the bus |
| `<dealer>: step <label> exited rc=N: not relaunched` | read `logs/<dealer>/<date>.jsonl`, decide, then `up --yes` (reruns that step). `rc=8`: the step could not wait out a dealer's cooloff: re-run `up --yes` once the cooloff is over, do not edit params |
| `<dealer>: step <label> ran N times without a deal or nothing-to-do marker` | read the dealer's window and log; rerun by hand or `up --yes` |
| `duel stale during Duels III` (or the Final) | `tmux kill-window -t factory:duel`, then `up --yes` |
| `<name>: missing input <file>` | restore the file, then `up --yes` |
| `<name>: keeper says running but child pid N is gone` | `tmux kill-window -t factory:<name>`, then `up --yes` |
| `<name>: another copy runs outside the factory (pid N)` | stop that pid |
| `<name> log silent for N s` | `tmux kill-window -t factory:<name>`, then `up --yes`. Right after the clock resumes from a pause (about 13:30) this can flash for a minute and clear itself: act only if it is still there after two minutes |
| `Market Test at H not on our book after N ticks` | check the broker window and that v20 is open; if it appears in the first two ticks of a test and clears, ignore it (the wall-time estimate is rough at double speed) |
| `broker dropped N matches in Market Test bXX` | read the `why` of the last `dropped` line in `logs/broker/<date>.jsonl` and post it on the bus; a restart does not fix a policy bug |
| `broker has no match in Market Test bXX after N ticks` | look at the broker window for `refused` or `send_error`; post it on the bus |
| `rate_limited` in a dealer log (`logs/<dealer>/<date>.jsonl`) | four dealer bots and the desk share the key's 5 requests per second: stagger the steps (raise `after_event.delay_min` of the later ones in `tools/factory_sunday.json`; a keeper re-reads it before its next start) |
| `push failed: ...` in the `logs_push` window (the watchdog does not see it) | the loop retries every 10 minutes and the commit stays local; read the reason (credentials, network). Still failing after 09:30 Madrid: the manual fallback of check 11 |
| `clock unreachable` | `curl -s https://bazaar.causaprima.ai/api/clock`; the keepers wait on their own |

Open the two held packs between dealer steps and before 10:39, never while a step runs. Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot. Restart one bot between them with `tmux kill-window -t factory:<name>` and `up --yes`. After 15:00: `tmux kill-session -t factory`.
