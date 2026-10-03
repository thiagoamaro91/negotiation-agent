# W2 · Duel desk and lab (the mega-duelist)

**Lever.** Duels are one of the three parts of the 30 negotiating points. Every team meets every other team twice per round-robin (once as seller, once as buyer): 34 duels for us in Duels I, 68 in Duels II, 68 in Duels III and 34 in the final.

**Suggested owner.** Thiago runs `agent/duel.py` live (his code); Hector + Claude build the arena and the tuner.

## What we know

| Session | When | Issues | Ticks per duel | Decay per round | At once | Our duels | Rough length |
|---|---|---|---|---|---|---|---|
| Duels I | Sat 11:30 | price | 16 | 6 % | 3 | 34 | ~90 min |
| Duels II | Sat 18:00 | price + delivery day | 16 | 8 % | 6 | 68 | ~90 min |
| Duels III | Sun 11:00 | price + delivery day | 12 | 10 % | 4 | 68 | ~50 min |
| Final | Sun 14:00 | price + delivery day | 12 | 10 % | 4 | 34 | ~25 min |

- A duel scores the share of the pie we capture (pie = buyer's value minus seller's cost), shrunk by every round of talk. No deal scores 0; a deal outside our limit loses points.
- The measured detail is in [analysis-friday/duels.md](../analysis-friday/duels.md). What this plan relies on:
  - **A round needs both sides to have spoken.** Our message after a rival message cost a round (5/5); an opening to a silent rival cost none (2/2). Listening, waiting and accepting are free.
  - **Practice was watch-only**, so our 0 of 12 is not a bot failure. In 8/8 duels where the rival named a price, its last offer was inside our limit, on average 31.9 % of our limit; that best offer came as the rival's last message, at deadline minus 1 tick in 6/8.
  - The field closed 96 of 206 practice duels; 103 of the 110 no-deals were timeouts on the deadline tick.
  - **Mirror:** the exact form is dead (rivals offered past it in duels 9, 99 and 104). The soft form holds: the rival's final price landed within 7 % of our limit in the paired duel in 6/8, as "a secret scale and shift per duel" would predict. Use the paired limit as a soft estimate of the rival's limit, never as a cap.
  - **Rival archetypes** cluster by rival team, not by alias: steady conceder, fast conceder, cycler, one-shot, LLM reciprocity, absent.
- `agent/duel.py` keeps the numbers in code, never parses rival text, and has `decide(d, state, tick, cfg)` as a pure decision step: the arena can call it directly.

## Design

### Live desk: `agent/duel.py` (unchanged role)

- Move the strategy constants (`RATIOS`, `LAST_R`, `MAX_MSGS`, `OPEN_WAIT`, `FLOOR_FRAC`, `ACCEPT_ANY_TICKS`, `DAYS_CHEAP`, `DAYS_PREMIUM`, ...) into `agent/duel_params.json`, read at start; command-line flags still override.
- The starting point is [analysis-friday's Duels I settings](../analysis-friday/duels.md#q5-recommended-settings-for-saturday-duels-i): silent while the rival moves toward us, accept any offer inside our limit in the last 3 ticks, early accept at 0.85 of the soft pie, at most 2 messages, the anchor clamped by the paired limit, one early offer to an absent rival. The arena's first job is to confirm these beat today's defaults; the tuner then searches around them.
- Accepts go through the key lease ([W4](key-lease.md)) with the highest priority, and never auto-retry on the next tick: the rival's standing offer may have changed.
- Words: persuasive lines are fine (anchors, "last word from me"). Prompt injection against other teams' agents only if the organisers confirm it is allowed; our own agent is immune because it never reads rival text.

### Lab: `tools/duel_arena.py`

- Scenarios: limits drawn like Friday's (buyer values 88-182, seller costs 65-134, pies from a few primas to ~100), session settings from the table above, and delivery-day weights for two-issue sessions.
- Rival population:
  - **fitted** from the Friday logs: the six archetypes above, with their opening margins, concession paths and timing;
  - **classic styles** for what Saturday's scored bots may add: hardliner, linear conceder, tit-for-tat (mirrors our steps), deadline-only;
  - **ours**: earlier versions of our own policy (self-play).
- Score per duel exactly as the rules describe it: our share of the pie × decay^rounds, negative outside our limit, 0 without a deal. Report the mean and the worst quartile per rival style.

### Tuner (overnight on the VM)

- Random or evolutionary search over `duel_params.json`, evaluated in the arena. A change is kept only if it wins on **held-out** rivals it was not tuned on. Each kept change writes a report: what moved, by how much, on which rivals.
- Next step, if the parameter search plateaus: an agent proposes code-level changes to the policy, judged by the same arena (Karpathy-style auto-improve). The arena is the referee, so a change that does not win does not ship.

### After each real wave

After Duels I (~13:00) we have 34 real duels: refit the rival population on them, retune, and load the new parameters before Duels II at 18:00. Same after Duels II for Sunday.

## Done when

- Before 11:15: `duel_params.json` from the tuner beats the current defaults on held-out rivals, and `duel.py watch` against the live clock shows sane decisions.
- 11:15: `duel.py run` live (gate: a yes in the team chat).

## Risks

| Risk | What we do |
|---|---|
| Overfitting a simulator that does not look like the real rivals | Fitted rivals, held-out validation, refit after every wave |
| Two duels want the same tick's accept | The lease serves the duel with the fewest ticks left first (duel.py already orders them that way) |
| An accept retried blindly on the next tick | Accepts never auto-retry; re-read the duel before accepting |
| Delivery days misread in Duels II | The arena includes two-issue scenarios; `missing_days` errors are logged and fixed before 18:00 |
