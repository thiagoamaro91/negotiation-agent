# Sunday pre-flight: 08:40 on the Mac Mini

Ten checks, one line each (check 1 also pulls when behind), then the 08:55 command. Everything here is read-only except the last command. Run it in `~/bazaar` on the Mini; no check prints a key (key checks print a count and a file mode only). If one fails and two minutes do not fix it, say so in the team chat before starting anything. The full operator page is [`sunday-runbook.md`](sunday-runbook.md); what changed overnight is in [`sunday-night-handoff.md`](sunday-night-handoff.md).

Before 08:40, once, after the 08:00 code freeze: set `notify_cmd` in `tools/factory_sunday.json` (the line is in the handoff, section "What needs you"). Without it the watchdog still prints problems in its tmux window but sends nothing to your phone.

1. **The Mini is on the `origin/main` head.** Expect the head named in the handoff, then `0`. Do not assume an auto-pull ran (Thiago's own doc says there is none; Hector says one was enabled): if the count is not `0`, pull, then rerun this check, check 2 and the self-test (expect `OK`). If the pull refuses because of local changes, say so in the team chat; do not reset.
   ```bash
   cd ~/bazaar && git fetch -q && git log -1 --format='%h %s' && git rev-list --count HEAD..origin/main
   git pull --ff-only && python3 -m unittest tests.test_factory 2>&1 | tail -1
   ```
2. **The config has nothing open.** Expect no output. (`OUTSIDE OPENING HOURS` next to `Scores freeze` is normal; next to `Final duels` it is not. Before 09:00 the wall-time column is indicative only: it anchors on a stale `day_opens` event, and the gates use game hours.)
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
   ps -axo pid=,args= | grep -E 'agent/(broker|duel|abuela|chato|rastro_seller|market_desk)\.py|feed_recorder|announce\.py|broker_loop|_gate\.sh' | grep -v grep; tmux ls
   ```
8. **The bus board has no foreign claim on a factory name.** Expect no output. Saturday's `broker` and `duel` rows on `mini` are yours; `up` takes them over.
   ```bash
   cd ~/bazaar && python3 tools/bus.py --session thiago-mini-factory board | awk -F'|' '$2 ~ /^ *(feed|broker|duel|abuela|chato|pilar|watchdog) *$/ && $4 !~ /mini/ {print "BAD:" $0}'
   ```
9. **Cash and level, from the dashboard.** Expect `cash 253 level 5 age <10 error None` (Saturday's close, ledger-checked at tick 1445; 403 after the 150 P at about 10:40).
   ```bash
   T=$(grep '^DASH_TOKEN=' ~/bazaar-dashboard/.env | cut -d= -f2); curl -s "http://127.0.0.1:8765/data?t=$T" | python3 -c "import sys,json;d=json.load(sys.stdin);m=d['me'];print('cash',m['cash'],'level',m['level'],'age',d['age'],'error',d['error'])"
   ```
10. **The dashboard tunnel is alive.** Expect `200`. If the link changed, the tunnel agent sends the new one to your Telegram.
   ```bash
   T=$(grep '^DASH_TOKEN=' ~/bazaar-dashboard/.env | cut -d= -f2); curl -s -o /dev/null -w '%{http_code}\n' "$(cat ~/bazaar-dashboard/tunnel.url)/?t=$T"
   ```

The team key sits in `~/bazaar/.env` and the bots read it themselves; the factory never passes a key to a bot. The dashboard's duel and broker panels read the folder named by `BROKER_ROOT` in `~/bazaar-dashboard/.env`; for the factory's bots it must be `~/bazaar` (`grep '^BROKER_ROOT=' ~/bazaar-dashboard/.env`), otherwise those panels stay empty.

## 08:55: start

```bash
cd ~/bazaar && python3 tools/factory.py up --yes
```

Starting before 09:00 is safe: every gate waits for open doors and a running clock. Expected output, one line per process, exit 0:

```
started feed        started broker      started duel
started abuela      started chato       skip    pilar: no enabled step left to run today   (or started pilar)
off     rastro_seller: ...              off     market_desk: ...              started watchdog
```

Any `REFUSE` line names its reason. `already running outside the factory`: stop that pid and run `up --yes` again. `missing input file ...`: the duel params file is not on this checkout, pull again. `cannot read the bus board`: GitHub is down; say so in the team chat, then `up --yes --no-bus`.

## 09:01: expected `python3 tools/factory.py status`

| Process | Expected line |
|---|---|
| feed | `RUNNING`, log a few seconds old |
| broker | `RUNNING`, log under a minute old; `Market Test bNN: matched N dropped 0` appears once a test has started |
| duel | `WAITING`, `next duel wave Duels III at 18.650 h` |
| abuela, chato | `WAITING`, `waiting for grant_all at 16.717 h`; «FILL wp4: any step that starts at 09:00 instead» |
| pilar | `DONE` (no enabled step) unless WP4 enabled one: «FILL wp4» |
| rastro_seller, market_desk | `off` |
| watchdog | `RUNNING` |
| last line | `ok` (no `PROBLEM` lines) |

`tmux attach -t factory` shows one window per bot (detach with Ctrl-b d).

## 09:05: the clock speed (one more read)

The schedule is in game hours. The organisers' wall-clock table (hard test 09:39, Round 3 10:39, Duels III 11:39, Final 14:09) fits a game clock that runs two game hours per wall hour from Saturday's close at 13.37 h, with a one-hour pause around 12:30. The factory's wall times (`plan`) assume one for one. Measure it:

```bash
python3 - <<'EOF'
import json, time, urllib.request
def clock(): return json.load(urllib.request.urlopen("https://bazaar.causaprima.ai/api/clock"))
a, ta = clock(), time.time(); time.sleep(60); b, tb = clock(), time.time()
print("game seconds per wall second:", round((b["t_hours"] - a["t_hours"]) * 3600 / (tb - ta), 2))
EOF
```

`1.0`: use `plan`'s wall times. `2.0`: use the organisers' table in the handoff; `plan`'s wall column is then twice too far. The bots are not affected, they gate on game hours. At 09:05 also check that the leaderboard still shows Saturday's round as the active one until Round 3 starts.

## Alerts and the one action for each

The watchdog window sends one message when its set of problems changes, and "all clear again" when it clears.

| Alert | Action |
|---|---|
| `<name> is down` | `python3 tools/factory.py up --yes` (starts only what is missing) |
| `<name> exited rc=N, restart K pending` | the keeper restarts it in 5 to 120 s; if it repeats, read the end of `results/factory/<name>.out` and post it on the bus |
| `<dealer>: step <label> exited rc=N: not relaunched` | read `logs/<dealer>/<date>.jsonl`, decide, then `up --yes` (reruns that step) |
| `<dealer>: step <label> ran N times without a deal or nothing-to-do marker` | read the dealer's window and log; rerun by hand or `up --yes` |
| `duel stale during Duels III` (or the Final) | `tmux kill-window -t factory:duel`, then `up --yes` |
| `<name>: missing input <file>` | restore the file, then `up --yes` |
| `<name>: keeper says running but child pid N is gone` | `tmux kill-window -t factory:<name>`, then `up --yes` |
| `<name>: another copy runs outside the factory (pid N)` | stop that pid |
| `<name> log silent for N s` | `tmux kill-window -t factory:<name>`, then `up --yes`. Right after the clock resumes from a pause (about 13:30) this can flash for a minute and clear itself: act only if it is still there after two minutes |
| `Market Test at H not on our book after N ticks` | check the broker window and that v20 is open; if it appears in the first two ticks of a test and clears, ignore it (the wall-time estimate is rough at double speed) |
| `broker dropped N matches in Market Test bXX` | read the `why` of the last `dropped` line in `logs/broker/<date>.jsonl` and post it on the bus; a restart does not fix a policy bug |
| `broker has no match in Market Test bXX after N ticks` | look at the broker window for `refused` or `send_error`; post it on the bus |
| `clock unreachable` | `curl -s https://bazaar.causaprima.ai/api/clock`; the keepers wait on their own |

Nothing changes during a duel wave or a Market Test: no restart, no edit, no hand-started bot. Restart one bot between them with `tmux kill-window -t factory:<name>` and `up --yes`. After 15:00: `tmux kill-session -t factory`.
