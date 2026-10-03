# W4 · One hand on the key (the lease)

**Lever.** Protects every other desk. On Saturday duel.py, the market desk, the El Rastro seller, chato.py and the account relay may all run on the team key at once. The server allows **one accept per team per tick**, shared by every agent on the key. Without coordination the market desk can spend the tick's only accept on a 3 P trade while a 40 P duel expires, or a dealer's final offer walks.

**Suggested owner.** Thiago (it touches his agents and his Mac Mini).

## Limits in force (`GET /api/clock` → `limits`, Friday night)

| Limit | Value |
|---|---|
| Accepts per team per tick | 1 |
| Messages per conversation per tick | 1 |
| New listings per team per tick (a cancelled one still counts) | 12 |
| Open conversations per team | 6 |
| Open offers per team | 30 |
| Requests per second per key | 5 (bursts of 20) |

The organisers may change any of these during the game; the feed announces it. Read them every tick, never hard-code them.

## Design: `agent/lease.py`

A small module every key process imports; state in `logs/state/lease.json` on the key machine, guarded by an `fcntl` file lock.

```python
from lease import Lease
lease = Lease("duel")                    # desk name, for the log
if lease.claim("accept", tick, priority=lease.DUEL):
    b.duel_accept(duel_id)
```

- **Accept**: one per tick. Priorities: duel (fewest ticks left first) > dealer final offer > market desk > anything else. A higher-priority desk may claim at any moment of the tick; the market desk may claim only after half the tick has gone and only if nobody has. The cost is at most half a tick of delay on a market snipe; duels never lose a tick. During the last 3 ticks of any live duel nothing but duels may accept ([analysis-friday](../analysis-friday/duels.md#q5-recommended-settings-for-saturday-duels-i): up to 3 duels can share a deadline).
- **Listings**: the 12 per tick split by quota (for example seller 6, market desk 4, spare 2), re-read from `limits`.
- **Requests**: a shared token bucket at 4 per second (one below the server's limit), so a burst from one desk cannot make another one's call fail.
- **Accepts never auto-retry on the next tick.** The SDK's `wait_on_tick=True` (the default) sleeps and repeats a refused write on the next tick; for `POST /api/duels/{id}/accept` that would accept whatever the rival's standing offer is by then. `duel.py` and `rastro_seller.py` already pass `wait_on_tick=False`; `abuela.py` and `chato.py` should too.
- **STOP**: if `logs/state/STOP` exists, every desk stops sending at the next tick (reads stay on). `touch` to stop, `rm` to resume.
- Every claim, grant and refusal is logged through `agent/runlog.py`.

## Where it runs

All key processes on **one always-on machine**, because the lease is a local file: the Mac Mini already runs the dashboard under LaunchAgents with a watchdog and Telegram pings, so it is the natural host. The account relay (`tools/me_relay.py`, from the brain PR) runs there too and pushes `/api/me` to the brain every 20 s, keys stripped.

## Done when

- A test with a fake clock: three desks asking for the accept in the same tick get it in priority order, never two in one tick.
- `duel.py`, `rastro_seller.py`, `chato.py` and the market desk call the lease before every accept and listing.

## Risks

| Risk | What we do |
|---|---|
| A process outside the lease (someone runs an agent from a laptop) | Team rule: key processes run only on the key machine; say it in the chat before starting one |
| The lock file left behind by a crash | Claims expire with their tick; a stale lock older than one tick is ignored |
| The organisers change the limits mid-game | Read `limits` every tick |
