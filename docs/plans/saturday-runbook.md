# W8 · Saturday runbook

Madrid time. Game hours from `/api/schedule`, assuming the clock jumps to game hour 4.0 at 09:00 and runs one game hour per wall hour (see [the clock note](README.md#the-clock-on-saturday)). If `t_hours` resumed at 2.65 instead, every time moves about 81 minutes later. Every line marked **gate** needs a yes in the team chat.

## Tonight (Friday night)

| Who | What |
|---|---|
| Claude (VM) | Market Test simulator and `agent/broker.py`; duel arena and overnight tuner; recorder for every venue's book |
| Thiago | Review these plans; sketch `agent/lease.py` |
| Everyone | Pick workstreams (README table) |

## Saturday

| Time | What | Who |
|---|---|---|
| 09:00 | Doors open. Read `t_hours` and `tick_seconds` in `/api/clock`, `now_hours` in `/api/schedule`, the limits and `/api/levels`: they decide every time below. El Retiro released, +1 pack and +150 P per team (game hour 4.05) | on duty |
| 09:00 | **Gate:** relist the spares at the [analysis-friday prices](../analysis-friday/README.md#1-el-rastro-at-0900-relist-the-spares-cheaper) with `agent/rastro_seller.py run` | Thiago |
| 09:03 | **Gate:** open our venue (`tools/open_venue.py run`), copy the broker key file to the VM, start `agent/broker.py run` | key holder + Hector |
| 09:05 | Start `tools/me_relay.py` on the key machine | key holder |
| 09:10 | Market desk in `watch` (shadow); seller keeps running our spares (LAV-08 #13 is a spare: we hold two) | Thiago / Hector |
| ~09:15 | **Gate:** a Lavapiés rare. A team listing under ~82 first; otherwise El Chato, aiming at 82, capped at 88. Then `GET /api/me/value?card=LAV-10`: ~218 means the page bonus counts in the card's value | Hector |
| 10:00 | Market Test 1 (16 ticks, 8 min). After it: our `bench_efficiency`, the stall replay, every team's market score | Hector + Claude |
| 11:15 | **Gate:** `agent/duel.py run --until 13:15` with the tuned parameters | Thiago |
| 11:30-13:00 | Duels I: 34 duels, up to 3 at once. The market desk yields the accept to duels | - |
| 12:00, 14:00, 16:00 | Market Tests; refit the broker's priors between sessions | Hector + Claude |
| 13:00 | Refit the duel rivals on the 34 real duels; retune for Duels II | Hector + Claude |
| midday | **Gate:** market desk live with caps, if its shadow morning looks right | Hector |
| 17:45 | **Gate:** `agent/duel.py run` for Duels II (price + delivery day, 68 duels, up to 6 at once) | Thiago |
| 18:00 | Duels II and a Market Test at the same time: the lease decides the accept | - |
| 20:00, 21:00, 22:00 | Market Tests; 21:00 is the hard one (firmer, more impatient traders) | Hector + Claude |
| 23:00 | Doors close. Snapshot, commit logs, retune overnight for Sunday | everyone |

## Sunday (15 s ticks)

| Time | What |
|---|---|
| 09:00 | Chamberí released, +150 P |
| 10:00, 12:00 | Market Tests |
| 11:00 | Duels III (68 duels, 12 ticks each, 10 % decay) |
| 13:00 | Sell what we hold: cards do not score at the end |
| 14:00 | Final duels on the big screen; Abuela and El Chato close |
| 15:00 | Scores freeze |

## After every session

- Market Test: log our efficiency, replay the stall, refit the broker.
- Duel wave: refit rivals, retune, reload `duel_params.json`.
- Every hour: `tools/snapshot.py`, commit `logs/`, note anything new in [`docs/findings.md`](../findings.md).
