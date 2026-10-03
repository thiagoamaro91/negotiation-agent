# W8 · Saturday runbook

Every command runs **on the VM**, from the deployed copy:

```bash
ssh fable@204.168.233.86
cd ~/bazaar/negotiation-agent
```

That folder holds `main` at 0289293 plus #5, #6, #7 and #8 (161 tests pass there), the team key in `.env` (mode 600, delete it Sunday after 15:00), and the tmux session `bazaar` with the windows `recorder`, `brain` and `desks`. Each long-running desk gets its own window:

```bash
tmux new-window -t bazaar -n NAME "cd ~/bazaar/negotiation-agent; COMMAND; sleep 3600"
```

(the trailing `sleep` keeps the window open so the last output can be read; `tmux attach -t bazaar`, then `Ctrl-b w` to pick a window). Lines marked **GATE** need a yes in the team chat from Hector or Thiago. Times assume the clock jumps to game hour 4.0 at 09:00 and runs one game hour per wall hour ([the clock note](README.md#the-clock-on-saturday)).

**Emergency stop**: `touch logs/state/STOP` stops the market desk at its next tick (it goes through the lease); stop any other window with `Ctrl-c` (or `tmux kill-window -t bazaar:NAME`). `duel.py`, `chato.py`, `abuela.py` and `rastro_seller.py` do not read STOP yet.

## Before 09:00

1. Check the brain page (Desks and Venues panels; the El Chato rare shown at ~91 P median with its ladder share) and that `logs/state/STOP` does not exist.
2. Confirm nobody else runs an agent with the key from a laptop: everything below runs here, once.

## 09:00 · Doors open

1. **Read the clock** (keyless). It decides every time below:

   ```bash
   curl -s https://bazaar.causaprima.ai/api/clock | python3 -c 'import json,sys; c=json.load(sys.stdin); print("t_hours", c["t_hours"], "tick_s", c["tick_seconds"], "doors", c["doors"], c["limits"])'
   ```

   `t_hours` about 4.0: times as written. About 2.65: add about 81 minutes to everything below.
2. **Account snapshot** (a keyed read): `python3 tools/snapshot.py`. Note the cash and the new pack.
3. **Account relay to the brain** (a keyed read every 20 s):

   ```bash
   tmux new-window -t bazaar -n relay "cd ~/bazaar/negotiation-agent; set -a; . ~/bazaar/brain.env; set +a; BRAIN_URL=http://127.0.0.1:8790 python3 -u tools/me_relay.py; sleep 3600"
   ```
4. **GATE · El Rastro seller** with Thiago's Saturday floors, without `--take-bids` (the market desk owns bids):

   ```bash
   tmux new-window -t bazaar -n seller "cd ~/bazaar/negotiation-agent; python3 -u agent/rastro_seller.py run --until 13:00; sleep 3600"
   ```
5. **Market desk in shadow** (decides and logs, sends nothing; its lines appear in the brain's Desks panel):

   ```bash
   tmux new-window -t bazaar -n market "cd ~/bazaar/negotiation-agent; python3 -u agent/market_desk.py watch --min-cash 130 --no-team-venues; sleep 3600"
   ```

## ~09:03 · The grant (+150 P and a pack)

6. `python3 tools/snapshot.py` again. Optional **GATE**: open the pack (its contents are luck and score nothing, but tell us what to sell or keep). Then `python3 tools/make_floors.py --keep-existing` (dry run) shows new spares for the seller.

## ~09:10 · A Lavapiés rare (GATE)

7. First a team listing: the market desk's lines and the brain's tape show any LAV-09 / LAV-10 listed under ~82 P. One accept by offer id if there is one.
8. Otherwise El Chato with Thiago's ladder (60, 64, 68 ... 84, never 1 P steps), his final taken up to 88. `--reserve 280` keeps the venue option open (383 - 280 leaves 103 for the rare):

   ```bash
   tmux new-window -t bazaar -n chato "cd ~/bazaar/negotiation-agent; python3 -u agent/chato.py run --only LAV-09 --max-deals 1 --anchor 60 --step 4 --max-bid 84 --cap 88 --reserve 280; sleep 3600"
   ```
9. **Page-bonus test** (a keyed read; prints only the value):

   ```bash
   python3 -c 'import os,sys; sys.path.insert(0,"kit"); [os.environ.setdefault(*l.strip().split("=",1)) for l in open(".env") if "=" in l and not l.startswith("#")]; from bazaar_sdk import Bazaar; print(Bazaar(os.environ["BAZAAR_URL"], os.environ["BAZAAR_KEY"]).value("LAV-10"))'
   ```

   About 218: the bonus counts. Restart the brain with it on (`tmux respawn-window -k -t bazaar:brain "cd ~/bazaar/negotiation-agent; export TZ=Europe/Madrid BRAIN_PAGE_BONUS=1; while true; do python3 -u tools/brain.py --port 8790 >> ~/bazaar/brain.log 2>&1; sleep 3; done"`) and hunt LAV-10 from a team (t10, t05, t04 hold it). About 112: no more Lavapiés spending.

## Ladder deals through the day (GATE)

10. Three negotiated Abuela deals at the bottom of her range, on first copies we miss (SAL-01, SAL-02, SAL-04, SAL-05 are worth 13 each to us; her commons close at 8-10):

    ```bash
    tmux new-window -t bazaar -n abuela "cd ~/bazaar/negotiation-agent; python3 -u agent/abuela.py run --only SAL-01,SAL-02,SAL-04 --max-deals 3 --cap 10 --reserve 280; sleep 3600"
    ```

## 10:00 · Market Test 1 (free stall)

11. Nothing to run: the free stall handles it. Afterwards `python3 tools/snapshot.py` and read `bench_efficiency` in `logs/state/me.json`, and every team's market score on the leaderboard (the brain shows both).

## 10:15 · Duel agent armed

12. **GATE**. `duel.py` waits until duels go live, so starting early is safe and covers a compressed clock. It writes `results/duel.lock` while duels are live: El Chato refuses to start and the market desk defers its accepts.

    ```bash
    tmux new-window -t bazaar -n duel "cd ~/bazaar/negotiation-agent; python3 -u agent/duel.py run --until 13:15 --params results/duel-params.json; sleep 3600"
    ```

## 11:50 · Venue decision (GATE, 270 P, 250 refundable)

13. Open before the 12:00 session if any of these holds (PR #7): the bench offers show a per-trader expiry; the desk says the stall crosses one pair per tick; the desk says matches are validated against hidden limits. Then:

    ```bash
    python3 tools/open_venue.py plan
    python3 tools/open_venue.py run --yes
    tmux new-window -t bazaar -n broker "cd ~/bazaar/negotiation-agent; while true; do python3 -u agent/broker.py run; sleep 2; done"
    ```

    Then Hector posts the "our market is open" message in the hackathon chat with the venue id the opener printed.

## 11:30-13:00 · Duels I

14. Watch the brain and the `duel` window. After the wave: refit the rivals on the 34 real duels and retune; load the new `results/duel-params.json` before 17:45.

## Midday · Market desk live (GATE)

15. Once the team agrees with its shadow lines: stop the `market` window and start it with `run`:

    ```bash
    tmux new-window -t bazaar -n market "cd ~/bazaar/negotiation-agent; python3 -u agent/market_desk.py run --until 23:00 --min-cash 130 --no-team-venues --address-bids; sleep 3600"
    ```

## Afternoon and evening

| Time | What |
|---|---|
| 12:00, 14:00, 16:00 | Market Tests. After each: efficiency, refit the broker if it runs (`python3 tools/bench_sim.py refit --log logs/broker/2026-10-03.jsonl`) |
| 17:45 | **GATE**: `duel.py run --until 19:45 --params results/duel-params.json` for Duels II (price and delivery day, 68 duels, up to 6 at once) |
| 18:00 | Duels II and a Market Test at once: the duel lock keeps the accept for duels |
| 20:00, 21:00 (hard), 22:00 | Market Tests |
| 23:00 | Doors close. `python3 tools/snapshot.py`, commit logs, retune overnight |

## Sunday (15 s ticks)

| Time | What |
|---|---|
| 09:00 | Chamberí, +150 P. Same start as Saturday |
| 10:00, 12:00 | Market Tests |
| 11:00 | Duels III (68 duels, 12 ticks, 10 % decay) |
| 13:00 | Sell what we hold: cards do not score at the end |
| 14:00 | Final duels; Abuela and El Chato close |
| 15:00 | Scores freeze. Delete the key from the VM: `rm ~/bazaar/negotiation-agent/.env` |
