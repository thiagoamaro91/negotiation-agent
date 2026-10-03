# Team 3 market audit: venue v20, broker, desk (snapshot 13:25 Sat, tick 630)

Source: Team 3 lunch review, Sat 3 Oct 2026, frozen copy of the Mini at commit fa91372, tick 630.

## 0. Headline
| Question | Answer | Tag |
|---|---|---|
| b36 possible gains | 205 over 4 pairs with the quote proxy, 225 with the shaded proxy, 257 at 30 % shading | MEASURED (q1). The proxy is an ASSUMPTION |
| b36 stall | 201 of 205 = 0.980 (0.982 and 0.972 under the other proxies). Score arithmetic says the server gave the stall 0.969 | MEASURED (q1) + INFERRED (q4) |
| b36 ours | 0 matches, efficiency 0.000. The reported 0.449 is the round mean (0.899 + 0) / 2 | MEASURED (q1, me.json) |
| Fixed broker replay (`run --policy stall`) | Same pairs and ticks as the stall: 4 matches, 0.980 | MEASURED (q1) |
| Can a policy beat the stall? | Not on b36: the quote-respecting ceiling equals the stall under all 3 proxies. In simulation, estimates without departure info score 0.0 to 0.4 points below the stall | MEASURED (q1, q3) |
| Market formula | market = 15 x bench + V. bench = 0.5 x (our round-mean efficiency) / (stall round-mean efficiency). V = 5 x min(1, v / mean of the top-3 venues' net value) | INFERRED. RMSE 0.002 points over 294 team-snapshots (q4) |
| One third-party trade on v20 | Typical (0.3 R) is about 1.5 points, strong (0.5-0.7 R) is 2.5-3.5, cap 5. Surplus at private values counts, volume does not, and a bad trade subtracts | INFERRED (q4) |
| 15 s ticks | Broker is fine after 2 constant changes. Desk is fine only when it trades El Rastro only | from code |
| v20 fallback | Never close it. Auto is weakly better than board if the venue can switch in place: ask the desk | rules + feed |

Flags, not interpreted:
- The last feed event in the snapshot is `clock.changed paused: true` at tick 630.
- The live broker has never sent one match to the real server. The 13:53 test is the first real `POST /api/broker/matches`.
- The selftest numbers in broker.py's docstring come from a simulated 10-trader mix, but b36 had 20 traders.
- The simulator is pessimistic in level: it gives the stall 0.80 on the fitted mix, against a real stall at 0.899 and 0.969. Use it only for paired comparisons.

## 1. b36 reconstructed (ticks 441-457), q1_b36_replay.out
Each trader: side, ticks, kind, quotes per tick, then limits under the Q / S / S30 proxies.

Buyers:
- b36-1, ticks 442-445, relaxing, 25 29 33 36. Limits 36 / 36 / 36.
- b36-4, ticks 442-447, firm, 76 six times. Limits 76 / 87.4 / 98.8.
- b36-8, ticks 444-448, relaxing, 30 31 33 34 35. Limits 35.
- b36-0, ticks 447-448, relaxing, 22 27. Limits 27.
- b36-2, ticks 447-450, relaxing, 24 26 27 29. Limits 29.
- b36-6, tick 447 only, 85. Limits 85 / 93.5 / 110.5.
- b36-9, ticks 447-449, relaxing, 80 89 97. Limits 97.
- b36-7, ticks 448-450, relaxing, 84 89 93. Limits 93.
- b36-3, ticks 450-455, firm, 51 six times. Limits 51 / 58.6 / 66.3.
- b36-5, ticks 451-453, relaxing, 45 50 55. Limits 55.

Sellers:
- b36-17, ticks 441-444, 29 28 26 25. Limits 25.
- b36-10, ticks 443-444, 87 81. Limits 81.
- b36-11, ticks 443-446, 73 68 64 59. Limits 59.
- b36-12, ticks 444-447, 77 75 73 72. Limits 72.
- b36-19, ticks 444-448, 89 85 81 77 72. Limits 72.
- b36-16, ticks 445-450, 42 41 40 39 38 38. Limits 38.
- b36-13, ticks 446-449, 73 69 66 63. Limits 63.
- b36-15, ticks 447-451, 30 28 27 26 24. Limits 24.
- b36-18, ticks 449-453, 87 83 79 75 71. Limits 71.
- b36-14, tick 452 only, 108. Limits 108 / 97.2 / 75.6.

What the run shows:
- Every offer showed expires_tick 457 (the session end) and maker "bench".
- Every trader left the book one tick after its last quote.
- The two firm traders were the two most patient, at 6 ticks each. 17 of the 20 stayed 5 ticks or fewer.

| b36 | Q | S | S30 |
|---|---|---|---|
| Possible gains | 205.0 (4 pairs) | 224.9 | 256.6 (5) |
| Quote-respecting ceiling | 201.0 (0.980) | 220.9 (0.982) | 249.3 (0.972) |
| Stall (kit bench_plan) | 0.980 | 0.982 | 0.972 |
| Ours | 0 | 0 | 0 |

"Possible gains" is an ASSUMPTION, taken from the textbook A8 measure in bench_sim. It is the max-weight matching on limits that ignores who was present when.
- Q proxy: the best quote each trader ever showed. This is a lower bound on true surplus.
- S proxy: firm traders pushed out 15 % and one-tick traders 10 %, using the broker's own priors.
- S30 proxy: both pushed out 30 %, the top of the kit's shading range.

Stall matches:
- t442: b36-17 x b36-4 at 52
- t447: b36-15 x b36-6 at 57
- t447: b36-16 x b36-9 at 60
- t448: b36-13 x b36-7 at 75

The one-tick buyer b36-6 carries 61 of the 201 points of gain (30 %).

DONE CHECK on the 0.449:
- We sent nothing in b36 (`run_end`: sent 0, dropped 15), so our b36 efficiency is exactly 0. MEASURED.
- The 0.899 is MEASURED: me.json at tick 227 shows bench_efficiency 0.899 and bench_points 0.5 on stall v09 for session 1.
- The 0.449 itself comes from strategy_win-plan_v1.md line 43 and your brief, not from a log in the snapshot.
- (0.899 + 0) / 2 = 0.4495, so 0.449 is the round averaging and not a partial b36 score.

## 2. Replay through the current broker (q1)

Same-tick settlement, each policy with its matches and efficiency under Q / S / S30:
- Pre-fix guard: 0 matches, 0 / 0 / 0. It reproduces the 15 same_maker drops in the log.
- Kit stall, all pairs per tick: 4 matches, .980 / .982 / .972.
- Stall at one pair per tick: 4 matches, the same efficiencies.
- `run --policy stall` with the PR #22 guard: 4 matches, the same efficiencies. Same pairs and ticks as the kit stall: True. The guard drops 0.
- `run` default "ours": 4 matches, the same efficiencies. Its plan note is `stall:blind` on every tick.

"ours" can never leave blind mode in this game. All expiries are equal, and the heartbeat's learned early value of 12 exceeds EXPIRY_TRUST_MAX of 3. Keep `--policy stall`.

Variant: a match settles only if both offers are still on the book at the next tick. Under that rule the stall makes 3 matches for 0.873 (Q). INFERRED not to apply to bench matches. t12 (v02) and t10 (v07) are board venues sitting at exactly 12.50, which is 7.5 plus the 5-point V cap. That requires their bench to be exactly at stall level.

Remaining risks in agent/broker.py. None of them is a correctness bug on b36:
- **First live match ever** (Desk.send, lines 609-634). There is no `matched` or `refused` event in any log. Verify right after the 13:53 test.
- **Silent failure** (Desk.step lines 598-602, end_runs lines 651-662). b36 dropped every pair for 16 ticks with no alert. HIGH.
- **Hung read** (HTTP_TIMEOUT 5.0 at line 97, retries=1 at line 696). Worst case is about 10.5 s per read: fine on 30 s ticks, most of a 15 s tick. MEDIUM on Sunday.
- **Error backoff** (ERROR_SLEEP, line 96). It goes up to 5 s. LOW.
- **Rate** (lines 91-92). About 3 GET/s plus one clock read per changed book, so under 5/s. LOW.
- **Stale tick** (lines 562-583). A book can be filed under the wrong tick for at most 0.2 s. No effect.
- **Pairing order and midpoint price** (stall_run, lines 145-157). Same as the kit. No effect.
- **Restart loop** (bazaar-watch/broker_loop.sh). It waits 10 s and Telegrams the owner on each restart. A missing key would make it spam. LOW.

## 3. Can a policy beat the stall? (q3_policy_headroom.out, 300 seeds x 4 sessions)

Each scenario lists: stall / live ours / estimates without expiry / stall one-pair / clairvoyant ceiling, then estimates minus stall with its 95 % half-width.
- Fitted to b36 (20 traders, 89 % impatient, expiry = end): .803 / .803 / .800 / .798 / .888. Difference -0.0036 (0.0018).
- Fitted with hard knobs, 24 traders: .769 / .769 / .766 / .755 / .860. Difference -0.0031 (0.0021).
- Fitted with hard knobs, 12 traders: .650 / .650 / .650 / .648 / .715. Difference -0.0001 (0.0025).
- Lab standard mix, expiry = end: .889 / .889 / .888 / .889 / .965. Difference -0.0013.
- Lab hard mix, expiry = end: .812 / .812 / .814 / .803 / .898. Difference +0.0026 (0.0026).

The fitted scenario comes from bench_sim refit (q3_refit.out). The trader model is an ASSUMPTION.

Reading:
- On b36 the ceiling equals the stall under every proxy. No pairing or waiting rule could have done better.
- This is one sample. It shows b36 had no room, not that no session ever has room.
- Pairing within a tick does not change surplus for the same matched set. The only edge is choosing whom to hold back for later, which needs departure info. The book has none, and 89 % of traders are impatient.
- The +6 to +9 point simulated ceilings are clairvoyant. The deployable estimator is flat or slightly negative.
- Weak signal: the firm traders were the patient ones. With 2 firm traders out of 20, that is too thin to build on.
- The prize would be large if the edge existed. Under the fitted rule, the only venue above the stall gets bench 1.0, worth 15 points instead of 7.5. INFERRED. No policy reaches it, so do not spend Saturday on it.
- In the hard session, the one-pair-per-tick reading loses 1.4 points and outages cost more.

## 4. Market score arithmetic (q4_market_fit.out, q4_market_series.out, q4_recovery.out)

**Phase-in.** The market column is multiplied by g(phase). Read off the stall-only teams, g is 0.64 at tick 220 and 1.0 from tick 330. MEASURED.

**Bench.** It is worth 15 x bench, where bench = 0.5 x E / S below the stall. E and S are our round mean and the stall's round mean.
- Stall-only teams sit at exactly 7.50.
- For us: 15 x 0.5 x 0.4495 / 0.934 = 3.61.
- Solving gives the stall's b36 efficiency S2 = 0.969 (0.966-0.971 within rounding), close to the quote-proxy 0.972-0.982. INFERRED.
- Averaging points per session instead is rejected. It gives 3.75, or needs a negative session-2 score of -0.019.

**V.** V = 5 x min(1, max(0, v) / R).
- v is the net value created on the venue, cumulative and fixed at trade time.
- R is the mean v of the top three venues that have positive v.
- Fit: RMSE 0.002. With zero-value venues included in the top three, RMSE is 0.072. INFERRED.

**Implied session efficiencies** (INFERRED):
- t06: 0.685, then 0.970.
- t08: 0.890, then 0.971.
- t13: 0.399, then 0.968.
- Every other team was at stall level in both sessions.
- Nobody has beaten the stall yet. The venues matching on estimated limits (t06, t08, t13) all lost to it in session 1.

**Observed V around trades** (MEASURED):
- t06: trade at tick 286 took V from 0 to 4.28.
- t05: trade at 311 took V from 0 to the 5.00 cap. Its trade at 398 (SAL-07 at 26) took it from 5.00 back to 0.
- t10: our buy at 351 took V from 0 to 4.34.
- t14: trade at 418 took V from 0 to 4.36. It then decayed to 3.10 and 2.22 with no trade of its own.
- t17: trade at 433 gave 2.76, which decayed to 1.96 and 1.40.
- t06: SAL-10 at 76 at tick 556 took V from 3.18 to 4.99.
- t09: trade at 602 gave 1.48.

**Fitted value per trade**, in units of R at tick 630:
- SAL-10, a rare at 76: +0.72.
- LAT-07 at 19: +0.44.
- MAL-02 at 5: +0.30.
- LAT-01 at 7: +0.28.
- SAL-07 at 26: -0.57.
- RET-02 at 9: -0.28.
- The median trade is 0.30 R.
- Price does not predict value.

**What one v20 trade of value x would add now:**
| x | V added |
|---|---|
| 0.10 R | 0.50 |
| 0.25 R | 1.25 |
| 0.50 R | 2.50 |
| 0.75 R | 3.75 |
| 1.00 R | 4.86 |
| 1.50 R | 5.00 (cap) |

Because R rises as the leaders keep trading, a single trade's points decay over time.

**Bench recovery** (INFERRED rule):
- If we match the stall in all 6 remaining Saturday sessions, market goes from 3.61 to about 4.9 after the 13:53 session and about 6.5 by the end of the day. Stall-only teams sit at 7.5.
- One more failed session costs about 0.94 points.
- Reaching 7.5 from bench alone needs +0.16 efficiency above the stall in every remaining session, which nothing delivers.
- So the gap to 7.5, and anything above it, has to come from V.

## 5. Who trades on team venues (q5_trade_origin.out, q5_venue_trades.out, q5_v20_public_offers.out, q5_threads_announce.out)

Trades (tick, venue, card, price, seller to buyer, then the listing behind it):
- 203, v02 (t12): MAL-03 at 7, t13 to t15. Behind it: a t15 bid directed to t13.
- 234, v02: RET-02 at 10, t13 to t15. Behind it: a t13 public ask, crossed by a broker match.
- 286, v01 (t06): LAT-05 at 5, t15 to t12. Behind it: a t15 public ask.
- 311, v10 (t05): MAL-07 at 14, t10 to t01. Behind it: a t10 public ask.
- 351, v07 (t10): SAL-01 at 7, t05 to t03. Behind it: a t05 ask directed to us.
- 398, v10: SAL-07 at 26, t10 to t15. Behind it: a t10 ask directed to t15.
- 404, v07: MAL-03 at 5, t04 to t05. Behind it: a t05 public bid that waited 34 ticks.
- 418, v14 (t14): LAT-07 at 19, t15 to t12. Behind it: a t15 public ask.
- 433, v17 (t17): LAT-01 at 7, t15 to t12. Behind it: a t15 public ask.
- 556, v01: SAL-10 at 76, t12 to t08. Behind it: a t12 public ask.
- 591-598, v02: RET-05, -02, -03, -01, -04 at 9 each, t14 to t09 (3 times), t04 and t15. Behind them: t14 public asks, each taken within 1-8 ticks.
- 600, v07: SAL-03 at 5, t06 to t14. Behind it: a t06 public ask.
- 602, v21 (t09): MAL-02 at 5, t15 to t04. Behind it: a t15 public ask.

What the trades show:
- 16 of the 17 trades are a team accepting a listed offer. One is a broker match.
- There were zero team-to-team threads all weekend: all 622 threads are with dealers.
- Repeated pairs:
  - t14 to t09: 3 trades in 7 ticks.
  - t13 to t15: 2 trades.
  - t15 to t12: 3 trades on 3 different venues. t12's bot buys cheap LAT cards on any venue.
- Reciprocal routing (INFERRED as arranged):
  - t05 posted 131 listings on t10's v07, and t10 posted 53 on t05's v10.
  - t06 posted 19 on t12's v02, and t12 posted 41 on t06's v01.
  - Three of those four teams are the market leaders.

What has happened on v20:
- 16 single-card asks from t15 at ticks 384-405, and never a bid.
- t15's LAT-07 ask at 26 expired at tick 394. It sold the same card on v14 at 19 from a listing posted at tick 414, 20 ticks later.
- t15 lists on all 18 venues, so v20 holding its listing at the right price is luck.
- Right now t13 has 11 open card-for-card swaps on v20, posted at ticks 626-627 and expiring 686-687. They are directed to t04, t15, t08, t02, t10, t06 and t12. If any is accepted, it settles on v20.
- Announcements do not drive trades. v03 posted 33 announcements, v06 20, v05 19 and v19 16, all with 0 trades. We posted none (announce.py never ran).

What would make two other teams cross on v20:
1. **A reciprocal routing deal with an active seller** (t14, t13 or t15). They list their sales on v20 and we list our own sales on their venue, which also saves us El Rastro's 5 % + 1 P fee. Fair-play note: every trade is at the parties' own prices, but the organisers can see the arrangement. That is the owner's call, and the owner sends any outreach.
2. **Leave t13's directed swaps alone.** They need nothing from us.
3. **Rely on broker public matching only as a bonus.** It needs a single-card ask and a bid with `want.types` equal to that card, both on v20, and that has never happened.

## 6. Our desk (q6_desk.out)
**Activity:** it ran 09:53-10:22, ticks 207-266.
- 287 buy skips, and 145 bid skips for lack of cash (room 0 above the 200 floor).
- 21 bids posted, all on El Rastro and all addressed:

| Card | Bid | Our value |
|---|---|---|
| LAV-10 | 70-71 | 112 |
| LAV-09 | 64-65 | 112 |
| SAL-09 | 74 | 91 |
| LAT-09 | 65 | 77 |
| SAL-01 and SAL-02 | 9 | 13 |
| LAT-03 | 8 | 11 |

- 0 fills.

**Our team-to-team trades all weekend:**
- MAL-08 sold on El Rastro on Friday.
- SAL-01 bought on v07 at 7 at tick 351, through sal01_buy.py, not the desk. That buy gave t10 +4.34 points at the time.
- MAL-10 sold to t10 on El Rastro at 74 at tick 585.

**Verdict:** a restart adds little market value, because our own trades never count on v20. If it restarts, keep it El Rastro only (`--no-team-venues`) with the cash floor. Never accept on a rival's venue.

## 7. Readiness for 15 s ticks
broker.py:
- Line 91, READ_EVERY 0.5 s: fine.
- Line 92, CLOCK_EVERY 1 s: fine.
- Line 96, ERROR_SLEEP up to 5 s: change to (0.25, 0.5, 1, 1, 2).
- Lines 97 and 696, timeout 5.0 with retries 1: change to 2.5 s with 0 retries for GETs.
- Lines 93-94, PENDING_TICKS and REFUSED_TICKS: counted in ticks, so fine.
- Line 708, 2 s sleep after an exception: fine.
- No tick length is hardcoded anywhere.

broker_loop.sh:
- 10 s restart delay: acceptable.

market_desk.py:
- Line 1206, PublicClient timeout 15 s at 2 req/s: change to 4 s.
- Lines 1756-1761, accept waits until mid-tick: it reads tick_seconds, so it adapts.
- Lines 2024-2025, sleeps next_tick_in + 1, clamped to 1-35 s: fine.
- Line 118, TICKS_PER_GAME_HOUR = 60: wrong for Saturday and Sunday, but only used as a fallback, so harmless.
- Lines 144-145, bid_step 20 ticks and expiry 30 ticks: these run twice as fast in wall time on Sunday.
- Measured: the desk processed 56 of 60 ticks at 30 s with team venues off. With team venues on, it reads every board and would miss ticks.

## 8. Fallback tree for v20 (quotes from kit/RULES.md)
1. **Keep board with the `--policy stall` broker.** Rule: "A broker can only act on a board venue". The replay shows stall level, but any session where the process is down scores 0, as in b36. This is the default today.
2. **Switch v20 to auto.** No endpoint is documented: the SDK's PATCH /api/venues/{id} carries fees only. A refused request "costs nothing and moves nothing". On auto, "the engine crosses every pair first", which gives stall level with no process risk, and it also crosses public offers. This is weakly dominant because no policy beats the stall. Ask the desk before trying.
3. **Open a second venue as an auto hedge.** Rules: "Each session counts your best venue open during it" and "a refused opening costs nothing". But an accepted opening "replaces the stall on the spot", and nothing says a second bond venue adds to the first. It could replace v20 and wipe our Saturday bench and V. It also needs 270 P, and we had 81 P at 11:05. Ask the desk first; this is not a free experiment.
4. **Close v20.** Rules: "none open counts 0" and "closing a venue after a good session keeps nothing". The free stalls were granted once, all at tick 201, and every venue.closed event so far is a stall being replaced. So closing scores 0 per session with no stall coming back. Never close.

## 9. Ranked fixes
1. **Session watchdog.**
   - What: alert on any `dropped` event, or on crossing bench offers with no `matched` within 1 tick, and run bench_check after each test.
   - Where: broker.py Desk.step lines 598-602 and end_runs lines 651-662, or an external tail of the log.
   - Evidence: b36's silent 16-tick failure.
   - Expected: protects about 0.94 points per session. The 13:53 session alone takes us from 3.61 to about 4.9.
   - Risk: none.
2. **Ask the desk whether v20 can switch to auto in place.**
   - What: if it can, switch, and keep the broker in watch mode.
   - Evidence: on b36 the ceiling equals the stall.
   - Expected: removes process risk, most valuable on Sunday.
   - Risk: low. Side effects of a mechanism change are unknown.
3. **Reciprocal routing deal for v20.**
   - What: route our own sales from agent/rastro_seller.py to a partner's venue in exchange for their sales on v20.
   - Evidence: the leaders run exactly this.
   - Expected: up to +5 points.
   - Risk: fair-play optics. Owner decision.
4. **Never buy on a rival's venue.**
   - Where: the sal01_buy.py pattern, and keep the desk on `--no-team-venues`.
   - Evidence: our one buy gave t10 +4.34.
   - Expected: denies rivals up to 5 points each.
5. **Sunday timeouts.**
   - Where: broker.py lines 96-97 and 696, market_desk.py line 1206.
   - Evidence: one-tick traders held 30 % of b36's gains.
   - Expected: protects a session, about 0.9 points.
   - Risk: low.
6. **Stop work on a beat-the-stall policy** (BenchPolicy).
   - Expected: 0 points, but it frees time.

Reproducibility: q1_b36_replay, q4_recovery and q3_policy_headroom were re-run from a clean env -i shell, and all three outputs are byte-identical. No file in the snapshot is newer than the scripts.
