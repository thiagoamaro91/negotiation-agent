# Sunday ladder and Chamberí

Written in the night of 3 to 4 Oct, from Saturday's public feed (ticks 160 to 1445) and our account at the close (tick 1445). **Private**: it names our set multipliers (LAV 1.6, SAL 1.3, LAT 1.1, RET 0.9, MAL 0.7, CHA 0.5) and what we lack; nothing here goes into an announcement or a page. The numbers that decide the dealer play are in section 1 and 2, the exact lines in section 4 ([`factory-dealer-steps-sunday.json`](factory-dealer-steps-sunday.json), ready to paste into `tools/factory_sunday.json`), the Chamberí plan in section 5.

## 0. The short version

- **How firm this is:** everything in sections 1 to 3 is a measured **association** between a public dealer deal and the same team's public `negotiating` score in the 10-tick interval around it, on Saturday, for other teams and for us. It is not the server's formula and not verified credit; the rules say the ladder counts the best three deals per level but not how many points each is worth. The projections (about 5 to 6 points, section 4.2) are **estimates** that assume Saturday's association carries over to Sunday.
- **Deals in a dealer's best three were followed by a board change of about 1.2 points at Abuela, 0.8 at Pilar, 0.6 at Pícaros and 0.3 at El Chato** (Saturday scale, medians of single deals). **After a team's first three deals with a dealer, later deals were followed by about 0** (median 0.00 to 0.07; 12 of 94 were followed by more than 0.3, each one displacing a worse deal).
- **Level 5 (Don Ernesto) is unmeasured.** Three teams sold him an epic at 116 to 120 and moved +0.14, -5.54 and -2.45 points; by the teams' inferred multipliers (not reliable) all three sold below what the card was worth to them. No team did a 4th. **Recommendation: no** to the CHA-epic round trip (buy at Pícaros 128 to 167, sell at 116 to 129): it costs 5 to 51 P (median 22), its buy leg is above our ceiling by construction (the clipped bots cannot run it), and nothing says the credit pays for it. Hector decides; section 3.
- **Only about 9 of the 15 slots can be filled inside our value**, because we already hold every card the dealers sell cheaply enough: all commons and uncommons of LAV, LAT and SAL, and every LAV and LAT rare. What is left to buy inside value is RET and the SAL-10 rare. Projection of the plan below: about 5 to 6 board points, an estimate (section 4.2).
- **Do not complete the SAL page with a dealer.** A dealer buy that completed a page was followed by about +0.5 points on Saturday (-0.17 to +0.83, n=10); a team trade that completed one by +1.6 to +4.7 (our LAT-09 at 88: +3.10). An association, with the confounders of section 1; the gap is large enough to act on. SAL-10 should come from a team (Hector's call) and only fall back to Pícaros or Chato.
- **Code fix shipped in the same PR:** buy limits are clipped to floor(book x our set multiplier), sell floors to the value of the copy we give up, a `--cap` or `--floor` on the wrong side is refused (exit 2, before any thread), a card whose set has no multiplier is refused, an offer must be exactly the deal (no extra asset of ours), and **every priced message and every accept re-reads `/api/me` and re-prices the card from the holdings it reads** (section 4.4), so Abuela, Pícaros and Pilar can run at once on the same RET cards. Three of the dealer lines now in `tools/factory_sunday.json` target cards we already hold or carry placeholder asset ids; section 4.3.

## 1. What followed a ladder deal on Saturday (board points; an association, not verified credit)

**Method.** `logs/feed/snapshots.jsonl` holds the leaderboard every 10 ticks on Saturday; `logs/feed/feed.jsonl` has 470 dealer settlements from tick 160. A settlement at tick T shows up in the snapshot interval (a, b] with a < T <= b (checked on isolated deals: the median change is 0.26 in that interval and 0.00 in the one before and after). The board drifts for everybody at once (the day's weight grows into it), so each team's change is `negotiating(b) - k * negotiating(a)`, with k the median ratio of the teams that had no event in that interval (k between 0.93 and 1.04). The public `duel.closed` event names no team (the rival is an NPC), so **every interval with a duel result is dropped** (136 deals), and so is every interval in which the same team had **any** other event: team trade, second dealer deal, pack, Workshop, gift, egg, badge (173 deals). What is left: **156 single deals** (table 1) and 172 homogeneous groups (188 deals, table 2). Reproduce with `python3 tools/ladder_value.py table | level5 | pages | noise` (stdlib, offline, `tests/test_ladder_value.py` pins the counts). Noise: 1,015 team-intervals with no event at all had a median change of 0.00, 70 % within 0.05 and 90 % between -0.16 and +0.28, so **anything under about 0.3 is noise**.

**Caveats on every number below.** The change is attributed to the deal by elimination (no duel result, no other event of that team in the interval), not observed from the server; two deals that the leaderboard refresh happened to split or merge, a penalty, or a rescale we cannot see would all show up as credit or loss; the cells are small (3 to 35 deals); and the Sunday round weights the board differently.

**Table 1. Change in the team's `negotiating` per single deal, by dealer level and by that deal's rank for the team in the round (rank counted from tick 160; "flat" is under 0.15).**

| Level | Rank | n | median | middle half | min to max | flat |
|---|---|---|---|---|---|---|
| 1 Abuela | 1st | 3 | 1.18 | 0.88 to 1.22 | 0.58 to 1.26 | 0/3 |
| | 2nd | 3 | 1.10 | 0.35 to 1.14 | -0.41 to 1.18 | 1/3 |
| | 3rd | 4 | 1.35 | 1.21 to 1.46 | 1.01 to 1.56 | 0/4 |
| | 4th+ | 35 | 0.00 | 0.00 to 0.08 | -0.30 to 0.77 | 30/35 |
| 2 Chato | 1st | 8 | 0.36 | 0.09 to 0.89 | 0.00 to 1.08 | 3/8 |
| | 2nd | 5 | 0.42 | -0.07 to 0.54 | -0.17 to 0.90 | 2/5 |
| | 3rd | 3 | -0.00 | -0.01 to 0.29 | -0.01 to 0.59 | 2/3 |
| | 4th+ | 5 | 0.04 | 0.00 to 0.23 | -0.01 to 0.73 | 3/5 |
| 3 Pilar | 1st | 5 | 0.82 | 0.42 to 0.82 | 0.00 to 1.22 | 1/5 |
| | 2nd | 6 | 0.84 | 0.78 to 0.93 | 0.05 to 1.22 | 1/6 |
| | 3rd | 6 | 0.79 | 0.55 to 1.04 | -0.01 to 1.60 | 1/6 |
| | 4th+ | 30 | 0.07 | 0.00 to 0.15 | -4.32 to 0.74 | 22/30 |
| 4 Pícaros | 1st | 11 | 0.82 | 0.67 to 0.97 | 0.52 to 2.10 | 0/11 |
| | 2nd | 8 | 0.59 | 0.54 to 0.89 | 0.36 to 1.10 | 0/8 |
| | 3rd | 8 | 0.59 | 0.12 to 0.78 | -0.20 to 1.03 | 2/8 |
| | 4th+ | 13 | 0.06 | 0.00 to 0.20 | -0.70 to 0.99 | 7/13 |
| 5 Ernesto | 1st | 3 | -2.45 | -3.99 to -1.15 | -5.54 to 0.14 | 3/3 |
| | 2nd and later | 0 | no team did a second | | | |

**Table 2. Per deal, pooled over every interval whose only events are dealer deals of one level and one kind (top three or later). "fit" is a least-absolute-deviation fit over those intervals (numpy, not in the repo): it agrees with the medians.**

| Level | top three: deals, median (middle half) | fit | 4th+: deals, median (middle half) | fit |
|---|---|---|---|---|
| 1 Abuela | 10: 1.18 (1.03 to 1.28) | 1.18 | 55: 0.01 (0.00 to 0.13) | 0.01 |
| 2 Chato | 16: 0.32 (0.00 to 0.65) | 0.23 | 5: 0.04 (0.00 to 0.23) | 0.00 |
| 3 Pilar | 17: 0.82 (0.52 to 0.95) | 0.76 | 32: 0.07 (0.00 to 0.19) | 0.07 |
| 4 Pícaros | 37: 0.63 (0.48 to 0.91) | 0.55 | 13: 0.06 (0.00 to 0.20) | 0.18 |
| 5 Ernesto | 3: -2.45 | -2.45 | 0 | |

**What it says.**

1. **Three slots per dealer, nothing after.** The 4th and later deals were followed by a flat score in 30 of 35 (Abuela), 22 of 30 (Pilar), 7 of 13 (Pícaros) and 3 of 5 (Chato). The exceptions are deals that beat an earlier one (t12's 4th Pícaros rare at 48 gave +0.99; a 4th Chato rare at 78 gave +0.73): the best three are kept, so a 4th only helps when it is better than the worst of the first three.
2. **The change does not rise with the level** (Abuela 1.2, Pilar 0.8, Pícaros 0.6, Chato 0.3): the weights are not a plain "higher level, more points" here, so Level 5 cannot be extrapolated.
3. **Price matters inside the gate.** Chato rares: 78 gave +0.73, 87 to 91 gave +0.4 to +1.1, 95 to 96 gave 0.0 (his rare closes: 75 to 96, median 87). Pilar uncommons at 14 to 16 gave 0.0 and at 19 to 20 gave about +1.0. Abuela commons at 8 to 9 and uncommons at 22 to 23 gave +0.9 to +1.4. Pícaros rares at 52 to 63 gave +0.4 to +1.0 (+2.10 once at 52).
4. **Our own two "wrong side" candidates were not zero.** LAV-06 sold to Pícaros at 11 (tick 961) gave +0.52 and SAL-03 at 5 (tick 1130) gave +0.54, both our 2nd and 3rd Pícaros deal. That fits spares valued at 25 % and 10 % of book x multiplier (10 and 1.3 P): both on the right side. The gate itself is still only proven by Friday's LAT-06 at 28 against 27.5 (+0).
5. **A dealer deal on the wrong side may cost points, not just earn none (two readings, one unexplained).** t01 sold its page-completing SAL-07 to Pilar at 29 (tick 948) and lost 4.32 for good (the re-buy ten ticks later gave +0.26). t08 broke a page the same way at tick 722 and moved +0.11, so it is not the page. The three Ernesto sales are the other cases (section 3).
6. **Completing a page through a dealer was not followed by a page-bonus-sized change.** Ten single dealer buys completed a page and moved -0.17 to +0.83 (median 0.5; t16's SAL-10 at Chato for 90 gave +0.83); the five single team trades that completed one moved +1.60 (a five-card swap) to +4.73 (+3.10 for our LAT-09 at 88).

## 2. Saturday prices, per dealer (closes, from the same 470 deals)

| Dealer | What | n | min | middle half | max |
|---|---|---|---|---|---|
| Abuela sells us | commons | 46 | 8 | 9 to 10 | 15 |
| | uncommons | 45 | 20 | 22 to 24 | 29 |
| | packs | 11 | 19 | 21 to 24 | 26 |
| El Chato sells us | uncommons | 13 | 26 | 30 to 31 | 61 |
| | rares | 25 | 75 | 86 to 90 | 96 |
| Los Pícaros sells us | rares | 52 | 48 | 54 to 59 | 67 |
| | epics | 18 | 128 | 139 to 154 | 167 |
| Pilar pays us | uncommons (SAL, RET she loves) | 33 | 22 | 24 to 26 | 30 |
| | uncommons (LAV, LAT, MAL) | 50 | 14 | 17 to 19 | 21 |
| | rares (SAL) | 24 | 65 | 71 to 78 | 87 |
| | rares (LAV, LAT, MAL) | 4 | 50 | 52 to 56 | 56 |
| | rares (RET, one deal) | 1 | 78 | | |
| | epics | 4 | 140 | 169 to 196 | 199 |
| Chato pays us | uncommons | 23 | 11 | 14 | 16 |
| Pícaros pays us | commons / uncommons | 22 | 4 / 10 | 5 / 11 to 12 | 5 / 12 |
| Don Ernesto pays us | epics | 3 | 116 | | 120 |

Pilar's threads (public offers) open at a base and rise as we come down: RET uncommons 22, 22, 23, 24, then a final of 24 to 26; SAL rares 61 or 70, then up to 72 to 84; RET-09 61, 63, 66, 70, 74, 78. Pícaros opens every rare at 73, then 64, 59, 54 and a final at 52 to 63; a team that moved 1 P a tick ended at 52 to 57, the ones that moved 3 to 4 P at 54 to 63. Ernesto's public offers are flat at 113 until the seller comes down, then climb: finals 115 to 117 (t16, t08), 120 (t06), and 123 to 129 against a seller who held out (t18 did not take 129).

## 3. Level 5: the CHA-epic round trip, and the recommendation

The only epic we could sell Ernesto without losing value is one we value at 120 or less: a **CHA epic** (book 180 x 0.5 = 90). The play: buy one from Los Pícaros, sell it to Don Ernesto.

| | |
|---|---|
| Buy leg | Pícaros epics closed at 128 to 167 (median 142, n=18). A CHA epic is worth 90 to us, so the buy is 38 to 77 P over value: **a wrong-side L4 deal by construction**, no credit, and `chato.py --dealer picaros` is not built to run it (epics are not in its targets, and a `--cap` of 128 or more is refused by the new gate). It would be a hand-driven thread. |
| Sell leg | Ernesto: 116, 120, 120 on Saturday; 123 to 129 finals for sellers who held out. A fast seller ends near 120, a patient one near 125. Above our 90 either way. |
| Net P | **-5 to -51 P, median -22** (142 - 120), from cash we would otherwise keep. |
| Level 5 credit | **Unmeasured.** The three Saturday sellers moved +0.14 (t08, LAV-11 at 120), -5.54 (t16, SAL-11 at 116) and -2.45 (t06, SAL-11 at 120). By their inferred multipliers (LAV 0.97, SAL 1.40, SAL 1.16: not reliable, so this is a guess) each epic was worth 175, 252 and 209 to its owner, so all three probably sold below value; none can be shown to have had a right-side sale. No team made a second Ernesto deal, so "does a 4th add anything" has no L5 data; at every other level it adds about 0. |
| Bracket | If an L5 deal credits like the other levels' top three, 0.3 to 1.2 points for about 22 P. If the wrong-side buy costs what wrong-side sales cost on Saturday (about 0.03 to 0.04 points per P short, from the -5.54 and -2.45), the round trip nets about 0. |

**Recommendation: no, do not schedule it.** It is the most expensive slot per point of the plan, its first leg cannot run in the factory, and the one number we need (the L5 credit at a price above value) does not exist yet. If cash is idle after the Final warning (14:03) and Hector wants the measurement, one deal by hand with `ladder_points` read before and after answers it for good; below 20 P net, with Pícaros at 135 or less and Ernesto bidding 118 or more.

## 4. Sunday's slots

### 4.1 What a card is worth to us, first copy, and the ceiling the bots now enforce

Value = book x multiplier. The bots buy at or under `floor(value)` and sell at or over `ceil(value)`; a deal on the line (price equals value) is the one case the gate evidence does not cover, so the lines below avoid it where they can.

| Set (x) | common 10 | uncommon 25 | rare 70 | epic 180 |
|---|---|---|---|---|
| LAV (1.6) | 16 | 40 | 112 | 288 |
| SAL (1.3) | 13 | 32.5 | 91 | 234 |
| LAT (1.1) | 11 | 27.5 | 77 | 198 |
| RET (0.9) | 9 | 22.5 | 63 | 162 |
| MAL (0.7) | 7 | 17.5 | 49 | 126 |
| CHA (0.5) | 5 | 12.5 | 35 | 90 |

A second copy is worth 25 % of that, a third 10 %. We hold **one copy of every card we own and no spare** (me.json at tick 1445), so nothing is auto-sellable today, and the cards we still lack are: SAL-10 (rare), SAL-11/LAT-11/RET-11/MAL-11 (epics), every legendary, **all of RET and MAL (9 of 10 missing), and CHA once it opens**. The API value of a card that completes a page includes the page bonus (SAL-10 would read about 177, not 91); the bots ignore that part, which is the bug the PR fixes.

### 4.2 The slots, cheapest first

| Dealer | Slots | Target | Limit | Closes it needs | Saturday change per deal | Cash | Verdict |
|---|---|---|---|---|---|---|---|
| Abuela (L1) | 3 | RET-06, RET-07, RET-08 | cap 22 (value 22.5) | 22 or less: 20 of 45 deals, 4 of 11 after tick 700 | about 1.2 each | 22 each, card kept or resold | run |
| | | RET-01 to RET-05 | cap 9 (value 9.0, on the line) | 9 or less: 30 of 46 | about 1.2 each | 9 each | fallback, 2 deals; drop if ladder_points does not move |
| | | packs | none | API value of a Neighbourhood pack to us is 17.1; she closes at 19 to 26 | 0 | | **no**: even with CHA out (1 in 6 cards, x0.5) the value stays 16.9 |
| El Chato (L2) | 0 to 1 | SAL-10 only | cap 88 (ceiling 91) | 91 or less: 21 of 25 | about 0.4 | 86 to 91 | **not by default** (see SAL-10 below) |
| | | MAL/RET/CHA uncommons and rares | | Chato sells from 26 and 75: above value 17.5/22.5/12.5 and 49/63/35 | | | nothing inside value |
| Doña Pilar (L3) | 3 | resell RET-09, RET-10, one RET uncommon | floor 64, 64, 23 | she pays RET uncommons 24 to 26 (finals), a RET rare 78 | about 0.8 each | brings cash back (+13 to +21 on a rare, +2 to +4 on an uncommon) | run, after the buys land |
| Los Pícaros (L4) | 3 | RET-09, RET-10 (and SAL-10 later) | cap 62 (RET ceiling 63) | 62 or less: 47 of 52 | about 0.6 each | about 57 each, resold at 64 or more | run; SAL-10 held back |
| Don Ernesto (L5) | 0 | | | | unmeasured | | **no** (section 3) |

**Why only about nine.** Abuela and Chato sell commons, uncommons and rares of the five released sets; every one of those we need is RET or MAL (below our ceilings only for RET commons and uncommons) or SAL-10. Pilar and the Pícaros buy and sell cards we can only trade at a profit if we hold a copy that is worth less to us than their price, and today we hold none: the RET cards are the inventory, **bought below value from Abuela and Pícaros and resold above value to Pilar, so each RET card fills two ladders at no loss** (22 in, 24 to 26 out; 57 in, 70 to 78 out). Ordered by cash outlay the slots are: Abuela commons 9 P, Abuela uncommons 22 P, Pícaros rares about 57 P, Chato 86 P+, Ernesto about 22 P net for an unmeasured credit.

**SAL-10.** It is the third Pícaros slot (about +0.6), but the same card from a team completes the SAL page for +3 to +5 points (section 1, point 6). The line is therefore written, off, behind a decision: if no team has offered SAL-10 by about 11:20 and Hector declines the team buy, enable `r3-p2-sal10` (Pícaros, cap 62) or, as a last resort, `r3-c1-sal10-fallback` (Chato, cap 88).

**Cash.** 253 P now, +150 at 10:40 = 403. Three Abuela uncommons tie up 66 P and two Pícaros rares about 114 (171 with SAL-10), 180 in all; the Pilar resales then bring back about 150 for the two rares and 24 for an uncommon. The reserve is lowered to 20 as in the existing steps, so cash is not the limit. No step touches venue v20 or the broker's key.

**Timing.** The schedule's Round 3 starts about 10:39 and the +150 P (`grant_all`) lands at 10:40: the Abuela steps start at +1 min, Pícaros at +2, the Pilar resales at +16, +30, +45 and +60 (each also waits for its gates: no duel lock, no duel wave within 12 min, so nothing starts between about 11:27 and the end of Duels III). A step is done on its first deal or on an empty plan, which is why each Pilar line appears twice at different delays.

**Projected gain** (an estimate, board points, Saturday scale; it assumes the Saturday association of section 1 carries over to Sunday, Saturday's close rates, and the Pilar prices of section 2): Abuela about 2.7 (2.2 credited deals of 1.2), Pícaros about 1.1 (two rares at 0.55; 90 % fill), Pilar about 1.9 (up to three resales at 0.8, depending on what the buys delivered), plus 0.6 if SAL-10 goes to Pícaros: **about 5 to 6**. A zero at Abuela costs us nothing but the slot.

### 4.3 What changed in the existing factory lines

| Existing step | Problem | Replacement |
|---|---|---|
| abuela `r3-slots-1-3` (`--only RET-07,RET-08,SAL-05 --cap 22`) | SAL-05 is already ours (asset 219): the plan drops it, so the third slot is lost | `r3-a1-ret-uncommons` (RET-06/07/08) |
| abuela `r3-best3-test` (RET-04 at cap 8) | a 4th deal adds about 0 (table 1); it stays off | none |
| chato `r3-slot-1-rare` (`--only SAL-09 --cap 88`) | SAL-09 is already ours (asset 1172): empty plan, which the factory marks **done without a trade** | `r3-c1-sal10-fallback`, off |
| chato `r3-slots-2-3` (SAL-10, cap 88) | `--cap 88` is under the ceiling 91 (fine), but it completes the page without the bonus | same step, off |
| chato `r2-fill-lav09` | LAV-09 is already ours | drop |
| pilar `r3-resell-ret` (`sell:<RET-07 id>,sell:827`) | asset ids are unknown before the buys, and 827 is not an asset we hold | `sell:<REF>` lines (new in this PR) |
| (none) | Los Pícaros had no bot | `chato.py --dealer picaros` (rares only, never sells to him) |
| fragment `r3-p1-ret-rares` (first draft of this PR) | two cards in one step: RET-09 filled, then a cooloff on RET-10 exits 0 and the factory marks the step done with one card | `r3-p1a-ret-09` and `r3-p1b-ret-10`, one card each |

`tests/test_ladder_steps.py` runs every step of the fragment through the same rules the bots now enforce (caps, floors, held cards, flags, delay order), against a frozen copy of our account. Run it on `tools/factory_sunday.json` after the paste (point `FRAGMENT` at it) before 08:00.

### 4.4 Concurrent runs: the limit is re-priced from the holdings, every time

The three dealers run at once, so a card's worth can change under an open thread: another bot buys RET-09 (our planned buy becomes a second copy, worth 25 %: 15 instead of 62), or the copy we kept leaves while Pilar negotiates the spare (the spare becomes a first copy: 63 instead of 17.75). Both bots therefore read `/api/me` at the start of every decision, immediately before any priced message and any accept, and take `live_limit()`:

- buy: `min(planned limit, floor(book x multiplier x marginal of the copy we would then hold))`
- sell: `max(planned floor, ceil(API value of that copy now), ceil(book x multiplier x marginal of the copy we give up))`

If our own standing number is already on the wrong side of the new limit the thread is closed (`limit_dropped`: a bid the dealer could still accept); if the read has no holdings, the copy is gone, or the set has no multiplier, the thread is closed (`limit_unknown`, with the reason); an offer that is not exactly the deal (an extra asset or type of ours, a second card, cash coming back) is refused as a `mismatch`. A thread is not even opened when the limit cannot be priced. Nothing is hidden: each close names the planned and the live number in `logs/<dealer>/<date>.jsonl`.

## 5. Chamberí (set CHA, released about 10:39; we value it x0.5, the worst)

### 5.1 What we do with every CHA card

CHA is our worst set, so every CHA card is worth more to almost any other team than to us, and each one is a sale. The floor is the least price above value (`ceil`); the ask is where to start. Fans pay at most what the dealers charge (Abuela sells commons at 9 to 10 and uncommons at 22 to 24, Chato rares at 75 to 96, Pícaros epics at 128 to 167), so ask just under that.

| CHA card we pull or receive | Value to us | First action | Floor | Ask | Then |
|---|---|---|---|---|---|
| common, first copy | 5.0 | a fan on El Rastro | 6 | 8 | Abuela buys commons at 5 to 6 (floor 6); a Pícaros bid of 4 to 5 is below value: no |
| common, 2nd copy | 1.25 | a fan | 2 | 6 | Workshop with two more spares of the same rarity: three become one card of the next rarity (the pull is luck; a random uncommon is worth about 13 to us) |
| common, 3rd copy | 0.5 | Workshop | | | |
| uncommon | 12.5 | a fan | 14 | 20 | Chato bids about 14 (13 to 16): an L2 slot at about +0.5; Pilar 16 to 21: an L3 slot at about +0.8; floor 13 |
| rare | 35 | a fan | 36 | 70 | Pilar 50 to 56 for sets she does not love; floor 36 |
| epic | 90 | a fan | 91 | 140 | Pilar paid 140 to 199 for epics on Saturday; Ernesto 116 to 129; floor 91 |
| legendary | 225 | Pilar or Ernesto | 226 | | |

The steps `r3-cha-sell-uncommons`, `r3-cha-sell-rares`, `r3-cha-sell-epic` (Pilar) and `r3-c2-sell-cha-uncommons` (Chato) in the fragment are written, off, for the moment a CHA card is ours: they name the card by ref (`sell:CHA-06`) because its asset id does not exist yet. We never buy CHA from a dealer or a team: every copy costs more than it is worth to us.

**Open both packs before 10:39.** Between 09:00 and 10:38 the draw cannot be CHA (if packs draw from released sets only; unverified). A Neighbourhood pack is worth about 17 either way, but the Silver pack's rare, epic and legendary slots lose about 9 P of expected value once CHA can be drawn (a CHA rare is worth 35 to us against 78 on average for the five old sets, an epic 90 against 202). The draws are also free inventory for the Pilar resales (a spare LAV, LAT or SAL uncommon is worth 7 to 10 to us and she pays 18 to 19).

### 5.2 Who is a CHA fan: elimination, and why not to trust it

Each team holds the same six multipliers shuffled, so what a team shows for the five released sets fixes what is left for CHA. `tools/value_inference.py teams` as it stands shows CHA as the least liked set of 14 of 18 teams (64 to 99 %). **That is an artifact:** Team 7 opened ten threads with Chato for CHA-06 at tick 1074 to 1077, before the set existed, so `load()` puts CHA in the softmax and every later choice of another set counts against it. Recomputed without CHA in the choices and without those probes (Model with the five released sets as `in_play`), the teams with the most unexplained multiplier mass, i.e. the likeliest homes for a high CHA, are:

| Team | evidence | E[CHA] | P(CHA >= 1.3) | note |
|---|---|---|---|---|
| t11 | none | 1.02 | 0.33 | silent all weekend: the prior, nothing else |
| t18 | 15 choices | 0.75 | 0.03 | spread over 0.9, 0.7, 0.5 |
| t16 | 41 | 0.69 | 0.16 | |
| t17 | 20 | 0.61 | 0.00 | |
| t05 | 33 | 0.59 | 0.06 | |
| t14 | 40 | 0.57 | 0.00 | |
| t01 | 27 | 0.57 | 0.01 | |
| t07 | 29 | 0.55 | 0.03 | |

Everyone else is at 0.51 to 0.54. Two warnings. First, the permutation prior expects **6 of 18 teams to have CHA at 1.3 or 1.6**, while this posterior finds fewer than one: the five released sets soak up the high multipliers in the model whether or not the evidence supports it. Second, the tool's own `check` says its top pick is right 21 % of the time against 17 % for chance and that **keeping 20 % of the confidence** minimises the log-loss: shrunk that way, every team's chance of a high CHA is 0.27 to 0.33. **Elimination cannot name the fans. The first buyers can.**

### 5.3 What the first CHA buyers tell us (the first 20 ticks after the release)

Template: Saturday's RET release at tick 160. Within five ticks t15 asked Abuela for RET-01 and RET-06 and bid on both RET rares, t02 bid on the RET rares and bought RET-01, RET-06 and RET-08 (10, 24 and 31 P); t12 asked Chato for RET-06 at tick 165 and Abuela for RET-08, RET-07 and RET-06 by 190; t05 at 181; t18 at 189. t13 listed a 2 P bid on every RET common (a bot that lowballs every new card). All of t15, t02, t12, t05 and t18 are RET fans in the inference (1.5 or more).

**Watch**, from the first tick after the release: `thread.opened` with a `buy` topic of a CHA card (dealer ask), `offer.listed` with a CHA card in `want` (a bid) or in `give` (a team shedding a pack pull), `settlement` of a CHA card, and `pack.opened`. Then `python3 tools/value_inference.py --refresh-catalog teams` and `... team t15` after 5, 10 and 20 ticks.

**How the conductor uses it:**

1. A team is a **fan** (use P about 0.6) if it asks a dealer for two or more different CHA cards, or lists a bid at or over book on one, or pays a dealer at or over book: choices weigh e^(4 x 1.1) = 81 to 1 for a x1.6 team over a x0.5 team. **Ignore** teams that bid on everything (t13's 2 P ladder) and one-off probes (t07's at tick 1074).
2. **Two or more fans within 20 ticks:** hold our CHA pulls for them and offer at just under the dealer's price (common 8, uncommon 20, rare 70, epic 140). Our gain is price minus our value (5 / 12.5 / 35 / 90), counted at our private values, which is how team trades score (0.05 points per P on Saturday).
3. **No fan within 20 ticks:** CHA demand is thin. Do not wait: sell to Pilar and Chato at their prices (table 5.1) at once. We do not buy CHA from a dealer: their prices (9 to 10, 22 to 24, 75 and up) are far above the CHA ceilings (5, 12, 35), so no ladder slot could be filled that way.
4. The fans' identities also say which sets they do **not** hold dear, which is who sells us RET and MAL cards below their price. That, not CHA, is where the points are.

## 6. What this does not settle

- The 0.3 to 1.2 per deal are Saturday-scale board points of single teams; the Sunday round grows into the board by its share of the day, so the same deal is worth that times a factor we cannot read until the first Sunday deal. The first Abuela deal of the round is our calibration: read `ladder_points` and the board before and after.
- Whether a deal at exactly our value is credited (RET commons at 9.0, a floor equal to the value) has no evidence; the lines avoid it except the Abuela commons fallback.
- Pilar's RET rare price rests on one Saturday deal (78) and her RET uncommon finals on about 20 threads; if she pays 64 or less for a rare, the L3 resale of the Pícaros rares fails and we keep two RET rares worth 63 each.
- The negative readings (t01 -4.32, the Ernesto sales) are not explained; the plan avoids anything that sells a card for less than it is worth to us.
- Los Pícaros has no tested bot: `--dealer picaros` is the Chato code with a new row, checked against a fake dealer only. Run its `plan` first (it prints the clipped limits) and watch the first thread.
