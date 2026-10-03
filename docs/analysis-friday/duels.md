# Practice duels analysis (Friday 2 Oct, snapshot 01:16)

Source: frozen snapshot `snap/` only (18 duel files, feed.jsonl 2103 events, snapshots.jsonl, score.jsonl). No live calls.
Scripts in `out/duels_scripts/` (run from that folder with `python3 <name>.py`); raw outputs saved next to each as `.out`.

| script | answers |
|---|---|
| `mirror_test.py` | Q1: mirror hypothesis, all three readings |
| `our_stats.py` | Q2: our outcomes, rounds vs who spoke, silent-accept counterfactual |
| `field_stats.py` | Q3: field-wide duel.closed, pair concordance, leaderboard fields |
| `rival_profiles.py` | Q4: aliases vs behaviour, per-duel concession paths, change-ratio test |
| `pie_share.py` | soft-mirror pie share of the rival's last offer; pair value/cost ratios |

## Q1. Mirror hypothesis

Three readings, tested separately.

1. **Rival price reveals our limit (same duel): KILLED.** 12 of 18 duels had rival prices. Rival first price == our limit in 1/12 (duel 37 only), mode == limit 1/12, final == limit 0/12, first within +-2 P in 1/12. Rival first / our limit ranges 0.769 to 1.184 (mean 0.924). Oro's "73 x7" is a cycler bot: Noche (same team, paired duel 38) repeated 128 x7 on the same ticks and both reset to their opening at tick 140.
2. **Rival limit == our limit in the same duel: KILLED.** It would mean zero pie in every duel, and 11/12 duels had rival prices beyond our own limit.
3. **Rival limit == our limit in the paired duel (ids odd/odd+1, same item, roles swapped): UNTESTABLE as an exact identity.** Rival limits are never shown: 0 deals of ours, and public `duel.closed` carries only `duel, session, status, item` (no price, limit, team or result). The leaderboard has no duel field. Consistency checks:
   - Against an exact mirror: 3/12 duels have rival offers that would breach the mirrored limit (duel 9: 82 < 84; duel 99: 154 > 152; duel 104: 98 and 95 < 102). Either those bots break their own limits or the mirror is not exact.
   - For an approximate mirror: of the 8 duels with 3+ rival prices, the rival's final price lands within +-7% of our paired limit in 6/8 (9: -2.4%, 10: -4.2%, 93: -6.3%, 94: +3.6%, 99: +1.3%, 100: +0.7%; the cycler 37/38 is the exception). Change-ratio test (rival-buyer move / rival-seller move vs our value/cost): 99/100 gives 1.133 vs 1.134, 93/94 1.595 vs 1.711, 9/10 1.300 vs 1.405, 37/38 1.318 vs 2.247. Opening margins mirror within the pair for 93/94 (0.479 vs 0.482).
   - The rules digest (section 7, tagged [A] = API/UI) says "Limits get a secret scale and shift per duel so allies cannot swap numbers". That predicts exactly what we see: close to the paired limit, but not equal.
   - Pair concordance field-wide: 98 pairs, both deal 43, split 6, both no_deal 49 (6 splits vs 48.8 expected if independent). This is CONFOUNDED: the same two bots play both duels of a pair, and an absent bot fails both. It is not mirror evidence.

**Operational reading:** treat our paired limit (`pairL`) as a soft estimate of the rival's limit (pie sizing, early-accept trigger, anchor clamp). Never as a hard cap, never as a reason to cross our own limit. `--mirror` as written (pairL taken as the exact rival limit) stays off.

## Q2. Our 18 duels

- Status: 12 closed (all `no_deal`, `result` 0.0), 6 live at the snapshot. Deal rate 0/12. By design: the bot ran watch-only except approved test messages.
- **Rounds vs who spoke** (MEASURED, 18/18):
  - we silent, rival silent: 4 duels, rounds 0 (23, 24, 91, 92)
  - we silent, rival spoke (4 to 12 messages): 7 duels, rounds 0 (9, 10, 29, 30, 38, 93, 94)
  - we spoke, rival silent: 2 duels, rounds 0 (139, 140)
  - both spoke: 5 duels, rounds 1 (37, 99, 100, 103, 104)
  So a round needs both sides to have spoken. Friday's "our message costs one round" holds whenever the rival has already spoken; an opening message to a silent rival cost nothing (so far). Untested: whether the rival's reply after our first message then bumps rounds to 1.
- Our messages: 7 (one per duel). Seller openings x1.396 to x1.712 cost; buyer openings x0.600 to x0.650 value. 5 of them cost a round (decay 0.06 each); none produced a deal by the snapshot.
- **Silent-accept counterfactual** (MEASURED): 8 of 12 closed duels had rival prices; in **8/8 the rival's last standing offer was inside our limit**, mean surplus **31.9% of our limit** (3.8, 12.0, 30.5, 34.5, 35.4, 39.4, 39.7, 60.2%). The best offer was the rival's last message in 8/8, and in 6/8 that came at D-1 (deadline minus 1 tick); 29/30 was a one-shot at D-8. Accepting it silently would have cost 0 rounds in 7 of those 8 (duel 37 already had our message). The other 4 closed duels had an absent rival (no messages, no offer).
- Live at the snapshot: 99 (+14.9% surplus standing), 100 (+11.2%), 104 (+7.8%), 103 (-13.7%, outside our limit), 139/140 no rival offer.

## Q3. Field-wide (public feed)

- `duels.scheduled`: 306 practice duels, 12 ticks each, decay 0.06. 206 `duel.closed` by the snapshot.
- Status: deal 96, no_deal 110, deal rate **0.466**.
- 103 of 110 no_deals closed exactly on the deadline ticks 132/144/156: they were timeouts, not walk-aways. So 53% no-deal tells us nothing about the "1 in 6 has no zone of agreement" claim.
- Deals close throughout the window; 11 deals were recorded AT the deadline tick (3 at 132, 5 at 144, 3 at 156). That suggests an accept at D-1 settles in time (we cannot see the accept tick, INFERENCE).
- By item, deal rate: Andén 0 0.31, Taxi Blanco 0.32, El Rastro al Amanecer 0.50, Plaza de Olavide 0.51, El Tren Fantasma 0.55, Mercado de Vallehermoso 0.59.
- Prices, limits, surplus, teams and per-duel results are NOT public: field-wide close price vs limit cannot be measured.
- Practice did not score: our `/api/me` duel_points stayed 0.0 (tick 146, duels=24); the public leaderboard has no duel field.

## Q4. Aliases vs behaviour

Aliases do NOT map to behaviour: Rival Luna appears in 5 duels with 5 different text styles, Rival Rojo in 5 duels with 4 styles (one silent), Rival Sol in 3 duels with 3. Behaviour clusters by **pair** (same rival team plays both duels: identical templates and tick cadence in 9/10, 37/38, 93/94, 99/100). Archetypes, with steps "toward us" in P:

| archetype | pairs | path | counter |
|---|---|---|---|
| steady conceder | 9/10, 93/94 | monotone, every 1-3 ticks, ends at D-1 near our paired limit (-6% to +4%) | stay silent, accept at the end window |
| fast conceder | 99/100 | 2 jumps in 2 ticks (+34, +17 / -30, -15), crosses paired limit | silent; accept once surplus >= 0.85 x soft pie |
| cycler/repeater | 37/38 | repeats opening x5, 3-step cycle, resets at tick 140, best at D-1 | silent; accept the cycle peak in the end window |
| one-shot | 29/30 | one opening at D-8, then nothing | accept in the end window if inside the limit; one counter only if the surplus is thin |
| LLM reciprocity | 103/104 | verbose, +-3 P, "further movement depends on a real concession" | the only one worth talking to: max 2 messages, real steps |
| absent | 23/24, 91/92 (+139/140 so far) | no messages, no offer | one early offer near the soft-mirror midpoint (cost 0 rounds while they stay silent) |

## Q5. Recommended settings for Saturday Duels I

Schedule row (snapshots.jsonl): Duels I at game hour 6.5, 16 ticks per duel, decay 0.06, max_concurrent 3, one round-robin. Accepts are 1 per team per tick.

| setting | value | why | basis |
|---|---|---|---|
| default stance | silent; no anchor while the rival is moving toward us | rival speech and waiting cost 0 rounds (7/7); last offer inside limit 8/8, best = last message 8/8 | MEASURED |
| OPEN_WAIT | 16 (whole clock) while the rival improves; speak only if the rival is silent, or has not moved toward us for >= 3 ticks | each of our messages after a rival message = 1 round (5/5) | MEASURED-backed |
| accept window / ACCEPT_ANY_TICKS | 3 (accept any offer strictly inside the limit, surplus >= 1 P, at D-3..D-1, most urgent first) | 3 concurrent duels can share a deadline and accepts are 1/tick | INFERENCE (schedule row) |
| early accept | rival surplus >= 0.85 x (pairL - L) when pairL exists and pie > 2 | frees the accept slot; 6/12 last offers reached it | INFERENCE |
| MAX_MSGS | 2 | only the LLM-reciprocity type needs talk; 6% per message | INFERENCE |
| anchor (when we must speak) | seller min(1.55 x L, 0.93 x pairL), buyer max(L / 1.55, 1.07 x pairL), always inside our limit | our pair value/cost < 1.55 in 5/9 pairs, so 1.55 often sits beyond the likely rival limit | INFERENCE |
| absent rival | one offer at the soft midpoint L + 0.5 x (pairL - L), early | silent rivals: 4/12 closed; opening to a silent rival cost 0 rounds (2/2) | INFERENCE |
| walk | never accept outside our limit; no message in the last 3 ticks except the D-2 last chance to a non-moving rival | a deal outside the limit loses points | rule |
| cross-agent | no other agent on the key (Abuela, Rastro seller) accepts anything in a duel wave's last 3 ticks | accept slot is per team | INFERENCE (open question) |

## Open questions

1. Does a rival reply after our first message (to a silent rival) bump `rounds` to 1? Untested.
2. Does an accept at D-1 settle in time? 11 field deals were recorded at the deadline tick, but the accept tick is not visible.
3. Is the decay multiplicative on the share or on the pie, and how is "share of the pie" computed when one side breaches?
4. Is the one-accept-per-tick limit shared between duel accepts and trade/dealer accepts?
5. Transfer: 4/18 practice rivals were absent and most bots were naive; scored Saturday bots may be firmer.
