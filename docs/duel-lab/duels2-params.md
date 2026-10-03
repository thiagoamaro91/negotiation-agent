# Duels II parameters (Saturday ~18:30)

Duels II: price and delivery day, 68 duels per team (every other team twice, once per role), 16 ticks each, up to 6 at once, decay 0.08 per round. At game hour 11.65, about 18:30 Madrid if the clock keeps its pace (check `GET /api/schedule`).

## Two files, one decision

| file | what it is |
|---|---|
| `duel-params-duels2-tuned.json` | The overnight VM search for Duels II (`tools/duel_tune.py --session 2`, 421 min, 9,313 candidates). Full report: `duels2-search-report.md`. |
| `duel-params-duels2-tuned-plus10.json` | The same set plus the four PR #10 flags that are on for Duels I (`late_poll 8`, `late_ticks 3`, `slot_demand "acceptable"`, `last_share 0.3`). |

Both pass `agent/duel.py selftest --n 200`.

### Arena, fresh seeds (150 sessions from seed 900000, never used for tuning, accept slot busy 3%)

Mean score per duel (deal rate):

| rivals | defaults | tuned | tuned + #10 |
|---|---|---|---|
| **all** | 0.225 (46%) | 0.244 (49%) | **0.260** (48%) |
| deadline | **0.314** | 0.256 | 0.301 |
| fast | **0.594** | 0.578 | 0.550 |
| hardliner | 0.075 | 0.085 | **0.110** |
| linear | 0.369 | 0.406 | **0.456** |
| silent | 0.183 | **0.244** | **0.244** |
| steady | 0.340 | 0.374 | **0.435** |
| tft | 0.151 | **0.307** | 0.293 |

Friday replay (rivals don't react): defaults 0.426 (17/18 deals), tuned 0.426 (17/18), tuned + #10 0.484 (15/18).

### Stress (120 more sessions from seed 950000)

| variant | defaults | tuned | tuned + #10 |
|---|---|---|---|
| as modelled | 0.218 | 0.239 | **0.257** |
| accept slot busy 15% of ticks | 0.217 | 0.226 | **0.231** |
| 80% of rivals never accept ours | 0.213 | 0.236 | **0.255** |
| firmer field (hardliner, llm, tft, cycler) | 0.209 | 0.235 | **0.248** |
| Friday archetypes only | 0.213 | 0.223 | **0.242** |
| **an accept at deadline-1 does not settle** | 0.198 | **0.202** | 0.185 |
| late read: 40% of rival messages land after it, 15% of reads fail | 0.218 | **0.239** | 0.236 |

### Decision rule

Use **tuned + #10** if the Duels I logs on the Mini show both:
1. at least one of our accepts sent at deadline-1 that settled (both sets keep `accept_any_ticks 2, near_ticks 0`, which bet on it; plus #10's last-chance share leans on it harder); and
2. the late read working: `rival ... late=True` lines in the duel log (the rival's same-tick message seen before our accept).

Otherwise use **tuned**: it beats the defaults in every stress row, including the two above. If a deadline-1 accept was seen NOT to settle, widen the accept window in either file (`"accept_any_ticks": 3, "near_ticks": 2`, the defaults) before the run.

## Delivery day: how duel.py decides, both roles

Our utility in a two-issue duel is the price surplus minus our days cost, and the cost is linear: `your_days_weight` primas per day away from our best day. So `duel.py` always offers an extreme day (0 or 10).

**Our best day** (`days_profile`), in this order:
1. `--days-best 0|10` if given. It is GLOBAL: the same day for buyer and seller duels. Only use it if `days_meaning` says both roles want the same day.
2. Otherwise the role default: **a buyer wants delivery early (day 0), a seller late (day 10)**,
3. flipped by keywords in `days_meaning` ("each day later costs", "sooner is better" mean early is best; "each day earlier costs", "more time is better" mean late is best),
4. and flipped again by a negative `your_days_weight`.

`days_meaning` is logged raw the first time a duel shows it. **Read the first Duels II duel's log line**: if the guess is wrong for a role, stop and restart with the right setting before most duels are played.

**What we offer:**
- Days are *cheap* for us when `10 x weight <= days_cheap x your_limit` (tuned `days_cheap` 0.153, default 0.10, so slightly more duels count as cheap). Then we give the rival the day it wants (its structured `days` if it sent one, else the opposite of ours) and ask our days cost back in price plus a premium. The premium falls along our concession schedule from 0.629 x our days cost at the anchor to 0.087 x at the floor (defaults 0.8 to 0.25). We trade the day away early and cheaply instead of haggling over it, which is where the pie grows.
- Days are *dear* for us otherwise: we hold our best day and concede on price only.

The same logic runs for both roles; only the best day differs (buyer early, seller late, unless `days_meaning` or the weight's sign says otherwise).

## On the Mini, before Duels II

```bash
cp docs/duel-lab/duel-params-duels2-tuned-plus10.json results/duel-params.json   # or -tuned.json, per the rule above
python3 agent/duel.py selftest --n 300 --params results/duel-params.json
python3 agent/duel.py watch --once --params results/duel-params.json
python3 agent/duel.py run --until 21:00 --params results/duel-params.json
```

68 duels at up to 6 at once over 16-tick duels is about 12 waves, roughly 1 h 40 min at 30 s ticks: `--until 21:00` leaves margin.

Not done yet: a refit on the Duels I logs. They live on the Mini; if they are pushed to a branch, they go into the arena's Friday replay and both sets get rechecked before 17:30.
