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

**Our best day** (`days_profile`), in this order (updated by "Duels II fixes" below):
1. `--days-best` if given: `0` or `10` for both roles, or per role, `buyer:0,seller:10` (one role alone is fine).
2. Otherwise a direction statement in `days_meaning` (`days_direction`): one direction (later / delay / more time, or earlier / sooner / rush) plus one effect, good (reduces, saves, better, want, ...) or bad (costs, penalty, loses, ...). "Each day later costs you" means early is best; "each day later reduces your cost" means late is best.
3. Otherwise the role default, **a buyer wants delivery early (day 0), a seller late (day 10)**, flipped by a negative `your_days_weight`. The flip only applies when `days_meaning` named no direction.
4. An ambiguous `days_meaning` (both directions, or a direction with no clear effect) keeps the role default unflipped and logs `days_ambiguous`: set `--days-best` per role.

`days_meaning` is logged raw the first time a duel shows it, with `days_best` and `days_read` (override / named / ambiguous / sign / default) on the `duel_new` line. **Read the first Duels II duels' log lines** (operator step below).

**What we offer:**
- Days are *cheap* for us when `10 x weight <= days_cheap x your_limit` (tuned `days_cheap` 0.153, default 0.10, so slightly more duels count as cheap). Then we give the rival the day it wants (its structured `days` if it sent one, else the opposite of ours) and ask our days cost back in price plus a premium. The premium falls along our concession schedule from 0.629 x our days cost at the anchor to 0.087 x at the floor (defaults 0.8 to 0.25). We trade the day away early and cheaply instead of haggling over it, which is where the pie grows.
- Days are *dear* for us otherwise: we hold our best day and concede on price only.

The same logic runs for both roles; only the best day differs (buyer early, seller late, unless `days_meaning` or the weight's sign says otherwise).

## On the Mini, before Duels II

Superseded by "Duels II fixes" below: pull the branch first, then use `duel-params-duels2-final.json`.

```bash
cp docs/duel-lab/duel-params-duels2-final.json results/duel-params.json
python3 agent/duel.py selftest --n 300 --params results/duel-params.json
python3 agent/duel.py watch --once --params results/duel-params.json
python3 agent/duel.py run --until 21:00 --params results/duel-params.json
```

68 duels at up to 6 at once over 16-tick duels is about 12 waves, roughly 1 h 40 min at 30 s ticks: `--until 21:00` leaves margin.

## Duels II fixes (Saturday afternoon, after Duels I)

**Run `duel-params-duels2-final.json`** = tuned + #10 plus `"early_share": 99`, on this branch's `agent/duel.py`. The file uses only keys an older `duel.py` knows, so it loads either way, but the accept-path and two-issue fixes below are in the code: pull before the run.

### What Duels I showed (logs/duel/2026-10-03.jsonl, logs/duels session 2, to tick 630)

- 34 duels, 31 finished, 25 deals: 21 by our accept (all with 1-3 ticks left), 4 by the rival taking our offer (2436 and 2437 took our absent offer, 2498 and 2499 took our last chance after freezing on one number). Deadline-1 accepts 2314, 2394 and 2412 settled (3/3). 48 `late=True` rival lines: the late read worked. Rivals walked away 0/31.
- The run used the Duels I file (`accept_any_ticks 3, near_ticks 2, absent_at 0.2`), not tuned + #10.
- **The paired limit was never visible: `pair_limit` None in 34/34.** Pairs are now (even, even + 1) with a different rival in each duel, and the two limits are unrelated (2360 sells at cost 154, 2361 buys at value 140). `mirror_limit` looks for (odd, odd + 1), so the early accept, the pair caps and `last_share` never ran. If the parity flips in Duels II it would switch on with a meaningless estimate (Friday replay: the early accept costs 0.053 per duel), hence `"early_share": 99`. Any `early_share` above 1 now switches the paired limit off everywhere (`pair_trusted`): the early accept, the thin test, the "instead" accept, the anchor and last-chance caps, `absent_share` and `last_share` (tests `EarlyAcceptOff`, `EarlyOffInstead`). Review of PR #33 found the "instead" path still firing: buyer at 100, paired limit 90, a stale rival offer of 96, tick 106 of 116: the anchor capped at 1.07 x 90 = 97 made 96 look better than our own bid, and the bot accepted 10 ticks early. Now it bids its own anchor (64).
- Rival mix, each path read by eye: 13 conceded every tick to the end, 5 every 2-4 ticks, 4 jumped then held, 1 spoke once, 2 froze and took our last chance, 2 silent that took our offer, 7 silent that never took anything (5 finished no-deals). That is `DUELS1_WEIGHTS` in the arena. `NEVER_TAKES` could not be refitted: our offers to rivals that spoke never sat inside their final range.

### Arena changes (tools/duel_arena.py)

- The Friday replay was reading the 31 Duels I files too (logs/duels holds both sessions) with 12-tick duels: it now reads server session 1 only.
- New **Duels I replay**: the real rival price paths on the real tick timeline (overlapping duels share the one accept per tick), late read included. Rivals do not react or accept there, and where we accepted the rival's path ends, so it can show what waiting costs but never what it gains. Scored: 24 duels where the rival posted a price; score = surplus / our limit x decay.
- `PAIR_SEEN` (`--pair-seen`), `DUELS1_WEIGHTS` (`--weights duels1`), and four stress rows with the paired limit hidden and the Duels I mix.
- Two issues: the arena used to write `days_meaning` strings that matched `duel.py`'s own keywords. It now writes a sentence that names no direction (`DAYS_WORDING`, test checks `days_direction` reads nothing from it), so the bot plays on its role default and the weight's sign; `DAYS_FLIP` flips every side's best day and shows us a negative weight. Final params, realistic: 0.330 either way, no deal below our true utility (tests `TwoIssueArena`). It still cannot tell whether the real server's wording is read right: the two-issue path has never run on real data, see the operator step below.

### Results (session 2, 150 fresh sessions from seed 1200000, slot busy 0.03; stress: 120 from seed 1300000)

"Realistic" = paired limit hidden, Duels I rival mix. Mean score per duel. F-variants run on tuned + #10 (with the pair hidden, `final` and tuned + #10 play identically). Re-run after the PR #33 review fixes (slot plan, neutral days wording): every cell within 0.003 of the first run, same ranking; the table shows the re-run where it moved (final 0.330 realistic, 0.264 as modelled, Friday 0.560).

| | defaults | tuned | tuned+#10 | **final** | +F1 counter | +F1 silent | +F2 0.05 | +F2 0.08 | +F3 rung 1 | no anchor | window_retry 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| arena, realistic | 0.277 | 0.307 | 0.330 | **0.330** | 0.327 | 0.329 | 0.330 | 0.331 | 0.326 | 0.317 | 0.329 |
| arena, as modelled (pair visible) | 0.221 | 0.245 | 0.265 | 0.264 | 0.264 | 0.265 | 0.260 | 0.263 | 0.261 | 0.249 | 0.264 |
| stress: slot busy 15% | 0.219 | 0.233 | 0.248 | 0.246 | 0.245 | 0.245 | 0.242 | 0.246 | 0.246 | 0.237 | 0.242 |
| stress: deadline-1 does not settle | 0.199 | 0.203 | 0.192 | 0.186 | 0.156 | 0.155 | 0.187 | 0.191 | 0.195 | 0.183 | 0.146 |
| stress: late read 40% late, 15% fail | 0.222 | 0.243 | 0.249 | 0.248 | 0.248 | 0.249 | 0.244 | 0.248 | 0.247 | 0.239 | 0.247 |
| stress: firmer field | 0.210 | 0.237 | 0.258 | 0.257 | 0.259 | 0.259 | 0.254 | 0.257 | 0.248 | 0.236 | 0.258 |
| stress: Duels I mix, no pair | 0.277 | 0.313 | 0.342 | 0.342 | 0.340 | 0.341 | 0.342 | 0.343 | 0.338 | 0.328 | 0.341 |
| ... and deadline-1 does not settle | 0.261 | 0.256 | 0.221 | 0.221 | 0.163 | 0.164 | 0.220 | 0.222 | 0.218 | 0.210 | 0.163 |
| ... and slot busy 15% | 0.276 | 0.296 | 0.304 | 0.304 | 0.297 | 0.299 | 0.304 | 0.305 | 0.300 | 0.291 | 0.299 |
| Friday replay (deals /18) | 0.433 (17) | 0.433 (17) | 0.506 (16) | **0.560** (16) | 0.506 | 0.506 | 0.506 | 0.506 | 0.499 | 0.511 | 0.560 |
| Duels I replay, P (deals /24) | 490 (21) | 501 (21) | 551 (20) | **551** (20) | 540 | 551 | 551 | 551 | 554 | 554 | 551 |

The real run scored 566 P on those 24 duels: the replay's 551 misses the 13 P of 2498/2499 (the rival took our offer, which the replay cannot do) and, in the replay only (tuned + #10's narrower accept window puts both at deadline-1 on tick 474), loses 2314 (3.8 P) to a slot clash with 2328 (61 P). In the real run both settled: 2328 accepted at tick 472, 2314 at tick 474.

**Tuned + #10 confirmed** over tuned and the defaults in every row except "deadline-1 does not settle", which Duels I ruled out (3/3 settled). The allocator fix below adds to it: the same set under the old allocator scored 0.317 realistic, 493 P on the Duels I replay and 0.484 on Friday's.

### What shipped (agent/duel.py)

Default on (bug fixes, each with a test that fails on the old code):

| | fix | effect |
|---|---|---|
| allocator (reported defect 2, reproduced; reworked after the PR #33 review) | `slot_plan`: keep the biggest surpluses that can all still get a tick (greedy by surplus with a feasibility check), and accept now the biggest of those whose taking now leaves the others feasible from the next tick. The first version still took (2,10) before (1,30) among (1,30) (3,20) (2,10) (3,5); now 30, then 10, then 20 | surpluses 50 and 5 on their last tick took the 5. Hypothetical built from Duels I data: replayed with tuned + #10's window, 2314 (3.8 P) and 2328 (61 P) both reach deadline-1 on tick 474 and the old allocator would spend that tick's accept on the 3.8 P one, letting the 61 P one expire. It did not happen: in the real run both settled (2328 accepted at 472, 2314 at 474), because the live window was 3 ticks with `near_ticks 2` |
| accept fallback (defect 3, reproduced) | the re-read before the POST takes a changed offer if it is still acceptable and at least as good for us; if it got worse, that duel is dropped and `slot_plan` runs again on the rest, in the first read and in the late read. Re-reads and the POST stop 0.5 s before the tick ends (`accept_budget` line) | one rival's last-tick move no longer wastes the tick's only accept. Review: A (1,100) B (3,90) C (1,80) with A worse on the re-read took B and let C expire; now C, and B still fits. At 15 s ticks, six slow re-reads no longer POST into the next tick |
| accept race (defect 1, reproduced; residual) | `POST /api/duels/{id}/accept` names no offer (RULES, `bazaar_sdk.duel_accept`), so a replacement between our re-read and the POST is accepted as it stands. The re-read now compares id AND terms, the POST follows it at once, and the response's price/days and the settled price/days are compared with what we approved: `accept_mismatch` alarm line | detected, not prevented. A rival offer posted in the current tick cannot be replaced before the tick ends (one message per tick), and with the late read our accept goes 8 s before the tick ends. Not reordered by freshness: no race in 21 accepts |
| duel length (defect 4, reproduced; reworked after the review) | `duel_span`: an explicit `start_tick` / `started_tick`, else an explicit `ticks` / `duel_ticks` / `total_ticks`, else born in this tick (the loop read the previous tick and the duel was not there: deadline minus this tick), else `duel_ticks`, never shorter than the deadline and the duel's own messages show. A malformed duel (no deadline, limit, role or id) is logged once as `bad_duel` and skipped; it used to raise and abort the whole tick for every duel | a 12-tick duel with `duel_ticks 16` made its absent offer on its first tick with `absent_at 0.2`. The first fix restarted a silent duel's clock when the run restarted mid-duel (the Mini restarted at 14:00 and 15:30); now a restart falls back to `duel_ticks` |
| days direction (audit 1; review item 5) | the negative-weight flip applies only when `days_meaning` named no direction; direction statements are read whole (`days_direction`), and an ambiguous one keeps the role default and logs `days_ambiguous` | a server that both names the direction and signs the weight had the buyer's best day flipped to 10. Substring keywords read "each day later reduces your cost" as early-is-best |
| `--days-best` per role (audit 2) | `buyer:0,seller:10` (either role alone; `0` / `10` still mean both) | |
| two-issue payload (audit 3) | two-issue messages send `{"text", "price", "days", "offer": {"price", "days"}}`; the kit's `duel_say` sent no top-level `days`. Price-only messages are unchanged | |
| rival names our best day (audit 4) | we offer that day with no premium | we offered the day neither side wanted, plus a premium |
| settlement alarm (review item 6) | `accept_mismatch` on a settled duel is computed with the configured `--days-best` | with `buyer:10`, approved (90, 10) and settled (90, 0) reported +10 instead of -20 |
| deadline-1 for lone duels (audit 6) | documented and exposed as `--window-retry N` (default 1 = unchanged: a lone duel whose rival still concedes is taken at deadline-2, deadline-1 kept as retry; 0 = take it at deadline-1) | not used: realistic 0.329 vs 0.330, and 0.163 vs 0.221 if a deadline-1 accept fails |

Off by default, measured above, **all killed** for Duels II:
- **F1** `--hold-while-conceding` (`--hold-ticks 2`, `--[no-]hold-counter`): wait for deadline-1 while the rival keeps improving, and counter one rung while waiting if that beats the offer by more than a round. +0.002 in the modelled field, -0.001 to -0.003 realistic, and it loses a quarter of the score if a deadline-1 accept fails (0.163 vs 0.221) or the slot is busy. Measured after the allocator and fallback fixes. The Duels I replay cannot show its gain (paths end at our accept).
- **F2** `--silent-last-margin M`: last chance to a silent rival at L x (1 +- M). With `absent_last` on and `last_r` 1.103 it already gets L x 1.103; 0.05 gives surplus away (silent 0.259 to 0.231 modelled), 0.08-0.10 is noise (+0.001). The 5 silent no-deals refused 1.08 x L too: dead bots more likely than a margin problem.
- **F3** `--open-rung K`: the anchor at rung 1 (1.277). Two-issue anchors already name both issues (test `OpenRung`). -0.004 realistic; tft rivals mirror our concessions and drop from 0.283 to 0.177. Duels I replay +3 P.
- Also measured: **no anchor at all** (`max_msgs 1`): -0.013 realistic (silent rivals lose the last chance), +3 P on the Duels I replay.

Flags off leave `decide()` and every number we send unchanged: test `FlagsOff` hashes them over 1,500 random states against the pre-change code (defaults and tuned + #10).

### Operator step: the first Duels II duels (conductor)

The two-issue path has never run on real data. As soon as the first duels appear:
1. In `logs/duel/<date>.jsonl`, read the `duel_new` line of the **first buyer and the first seller**: the raw `days_meaning`, the sign of `days_weight`, and what the bot made of it, `days_best` and `days_read` (`named`: read from `days_meaning`; `sign`: role default flipped by a negative weight; `default`; `ambiguous`: role default, also logged as `days_ambiguous`). The role default is buyer day 0 (early), seller day 10 (late). Check `days_best` against the sentence by hand.
2. Read the first `say` line of each: a `refused` with `missing_days` (or any 4xx) means the payload is wrong. Stop the run and call it out.
3. If the best day is wrong for a role: ctrl-c, then restart with the explicit flag (it beats the params file), e.g. `python3 agent/duel.py run --until 21:00 --params results/duel-params.json --days-best buyer:10,seller:0`, or one role only: `--days-best seller:0`. A restart picks up the messages we already sent from the duel itself.
4. Watch for `accept_mismatch` lines (an accept that settled on other terms than the ones approved).

### On the Mini (Duels II, ~18:30)

```bash
git pull   # this branch's agent/duel.py, once merged
cp docs/duel-lab/duel-params-duels2-final.json results/duel-params.json
python3 agent/duel.py selftest --n 300 --params results/duel-params.json
python3 agent/duel.py watch --once --params results/duel-params.json
python3 agent/duel.py run --until 21:00 --params results/duel-params.json
```

### Sunday note (Duels III and the Final: 15 s ticks, 12-tick duels)

- Set `"duel_ticks": 12` and `"late_poll": 4` in the params file (8 s before the end of a 15 s tick is too early to see the rival's same-tick message). A running loop takes a new duel's length from the tick it appears in, but after a restart mid-duel it falls back to `duel_ticks` (unless the API shows a start or length field).
- The late-read kill switch never re-enables: after 2 failed late reads in a row (`late_off` in the log) the run accepts in the first read only for the rest of the run. Restart the run to re-arm it.
- `--idle-ticks 40` is 10 minutes at 15 s ticks: the run exits after 10 minutes without a live duel. Start a fresh run for the Final.

Reproduce the tables: `python3 tools/duel_arena.py --session 2 --sessions 150 --seed0 1200000 --slot-busy 0.03 --pair-seen 0 --weights duels1 --stress --params docs/duel-lab/duel-params-duels2-tuned-plus10.json --params docs/duel-lab/duel-params-duels2-final.json` (add a params file with a flag on to measure it).
