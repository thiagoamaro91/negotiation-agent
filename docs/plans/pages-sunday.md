# Sunday page buys: SAL-10 from a team (WP8)

Private plan (our values and caps are in here: team only). Built on the night of 3–4 October from the recorded feed
(`logs/feed/feed.jsonl` ticks 0–1445 plus `logs/feed-vm/feed.jsonl` for Friday's ticks 0–159), the last recorded El
Rastro board (`logs/feed/snapshots.jsonl`, tick 1445, 23:00:01) and `logs/state/me.json` (tick 1445). Inferences are
marked INFERRED.

## The target

SAL-10 is the only card missing from our Salamanca page. Holding SAL-01..09, one more SAL-10 is worth **177.1** to
us: 70 × 1.3 = 91 plus the page bonus 25 % × 344.5 = 86.1 (the same arithmetic `/api/me/value` showed on Saturday
when LAT-09 went from 77 to 149.9 once LAT-03 arrived). A team buy scores value − price − fee at once; a dealer buy
scores only ladder credit. No other card on the board clears our buy rule (section 4).

## The command (Sunday, from the +150 P grant, ~10:40)

```
python3 agent/market_desk.py run --no-team-venues --no-bids \
    --page SAL-10:110:80 --page-step 4 --page-step-ticks 8 \
    --min-cash 40 --cap-hour 150 --cap-day 250 --until <HH:MM>
```

What it does each tick (module docstring step 8):

1. **Ask:** takes any El Rastro listing of SAL-10 with price + fee ≤ 110 (a 103 ask costs 103 + 7 = 110). Team
   venues never (`--no-team-venues`, and page cards are El Rastro only in any case).
2. **Bid:** otherwise ONE bid on El Rastro, `give {cash}`, `want {"cards": ["SAL-10"]}`, addressed to nobody. It
   starts at 80 and rises 4 P every 8 ticks: 80, 84, … 108 at +56 ticks, 110 (the cap) at +64 ticks
   (16 min at 15 s ticks). It never
   rises above 110, above value − margin (159), or above the cost of a live SAL-10 ask, and never steps down.
3. **Guards:**
   - At most one live bid for SAL-10: the ordinary bid planner never touches a page card, run cancels a duplicate,
     and before accepting an ask the desk re-reads `/api/me/offers` and cancels every bid of ours on the card. If
     any of those cancels fails or has no quota, nothing is accepted that tick.
   - No post or step while `results/duel.lock` is fresh or a duel of ours is live. Both are checked at planning and
     again (a fresh `/api/duels` read) right before each page post or replacement; a live bid stays, cancels go.
   - The bid fits in cash − 40 and in the spend room left after this tick's accept and the other bids, or it is not
     posted. Every other buy keeps 110 P of cash and of hourly and daily spend room free for SAL-10 while we lack it.
   - A replacement that fails after its cancel keeps the step clock: the next tick re-posts at the stepped price.
   - Only a well-formed rival bid (cash only, for SAL-10 alone) moves our first price.
   - It is cancelled when SAL-10 arrives or when we take an ask for it. `main()` refuses a page cap above
     `--cap-hour` / `--cap-day` (the defaults 100 / 250 would have blocked every buy above 100 P).
4. Every decision goes to `logs/market/<date>.jsonl` with `"page": true`, value, ceiling, anchor, price and gain
   (also on the completed-card lines, where value is one more copy's).

Expected gain: **+97 if the 80 bid fills, +67 at the 110 cap**. `--no-bids` keeps the cash for the page (the
ordinary bids would chase RET/MAL/CHA page cards worth 5–63 to us); the desk still buys any other listing that passes
its rule, within `--max-price 80`, as long as 110 P of spend room stays free for SAL-10 (with `--cap-hour 150`, at
most 40 P of other buys per game hour until SAL-10 arrives).

### What it would do now against the recorded board (tick 1445, cash assumed 403 = 253 + 150)

```
python3 agent/market_desk.py plan --keyless --recorded logs/feed/snapshots.jsonl --release CHA --assume-cash 403 \
    --page SAL-10:110:80 --page-step 4 --page-step-ticks 8 --no-bids --no-team-venues --min-cash 40 \
    --cap-hour 150 --cap-day 250

tick 1445 BID  SAL-10 PAGE cap 110 @ 80 on rastro: value 177.1, ceiling 110, anchor 80 (--page floor),
  gain if filled +97.1 -> POST: page bid 80 (gain if filled +97.1, steps to 110)
  decisions: bid/post 1, buy/skip 26, sell/skip 8;  accept this tick: none
```

No SAL-10 ask was open at the close, so the desk posts the bid. The 26 asks it skips are all below the buy rule:
the best are RET-01 at 8 (−1.0) and RET-03 at 10 (−3.0).

## Why a floor of 80 and a cap of 110 (evidence)

**Team trades of SAL-10** (settlement with `venue`, no persona):

| tick | price | from → to | venue |
|---|---|---|---|
| 72 (Fri) | 80 | t12 → t18 | rastro |
| 98 (Fri) | 70 | t10 → t13 | rastro |
| 163 | 72 | t02 → t01 | rastro |
| 376 | 76 | t01 → t06 | rastro |
| 556 | 76 | t12 → t08 | v01 |

The p25 is 72 (the desk's default floor without `:80`). The two Friday trades are only in `logs/feed-vm` (the laptop
recorder lost ticks 49–118). Before this PR the desk read only the first feed file, so its anchors never saw a
Saturday trade.

**Why 80 and not 72:** Doña Pilar buys SAL-10 from teams at **69–87** (10 buys, ticks 722–1391: 69 70 74 78 75 87 76
80 75 71), and t10 and t14 run a loop: they buy at 52–57 from Los Pícaros and sell to Pilar at 75–87. A holder compares
our bid with Pilar's price, so 72 loses. 80 is above Pilar's median, and the steps pass her maximum (87) at tick +16
(4 min).

**Dealer sales (not the route, for reference):** Los Pícaros sold 8 copies to teams at 52–62 (median 55.5, ticks
798–1300). They open at 73 and close at 56–66. Chato sold one at 90 (tick 266).

**Asks and bids seen:** t10 offered SAL-10 to us at 105 (796), at 80 (843) and at **67** (1108; it expired and t10
sold that copy to Pilar at 80). t09 kept a standing bid of **68** from tick 1201 to 1387. Our own bids of 55–73
(ticks 735–758) never filled. Nothing for SAL-10 was open at tick 1445.

**Holders (RECONSTRUCTED from asset ids in both feeds: pack openings, settlements, and the assets offers give).**
19 copies (#2–#20) are seen; #1 never is (probably a starter hand). Pilar bought 10 (#8–10, #12, #14–19) and has
never sold. Nine teams hold one each, as of the last public move:

| copy | holder | last public move |
|---|---|---|
| #2 | t13 | t10 → t13 at 70, tick 98 (Friday, logs/feed-vm only) |
| #3 | t18 | t12 → t18 at 80, tick 72 (Friday, logs/feed-vm only) |
| #4 | t17 | never traded; t17 listed it at ticks 89–94 |
| #5 | t01 | t02 → t01 at 72, tick 163 |
| #6 | t16 | Chato → t16 at 90, tick 266 |
| #7 | t06 | t01 → t06 at 76, tick 376 |
| #11 | t05 | Pícaros → t05 at 54, tick 798 (listed at 93 to t08 at 799) |
| #13 | t08 | Pícaros → t08 at 53, tick 958 |
| #20 | t14 | Pícaros → t14 at 56, tick 1300 |

Starter hands and pack pulls are not public, so a holder may have moved a copy unseen. The bid goes to nobody because
nine possible sellers are better than one guess. `--page-address` would show it to the last public receiver only.

**Server expiry:** our desk bids on Saturday morning came back with expires = created + 15 although we asked for 30.
The desk re-posts an expired page bid with the same step clock, so the step is not lost.

## Decisions for the orchestrator

- **SAL-10 from a team, not from Chato.** `tools/factory_sunday.json` (main) has `r3-slots-2-3` (disabled) buying
  SAL-10 from Chato up to 88. Running both could bring two copies (a filled bid is the other team's accept and the
  lease cannot stop it), and the second is worth 22.75. Keep it disabled while the page desk runs, or use another rare.
- **`r3-slot-1-rare` buys SAL-09 from Chato up to 88, but we hold SAL-09** (me.json, tick 1445). A second copy is
  worth 22.75, so any price above that is on the wrong side of our value and scores 0 on the ladder. Its todo says
  "SAL-09, or LAT-09 if still missing": we hold LAT-09 too. That step needs a different card.
- **Fallback if no team sells by ~13:30:** Los Pícaros at ~56 would still complete the page (+121 by value, but
  scored as a dealer deal, not as a team trade). Their message once named SAL-09 inside a SAL-10 thread (tick 1385,
  thread 2124): check the structured `give` before accepting. Hector's call.
- **Start earlier?** Cash allows it from 09:00 (253 − 40 = 213 ≥ 110), but the morning dealer steps need cash too, and
  the round the gain lands in (round 2 before 16.65 h, round 3 after) is a scoring choice. The plan assumes 10:40.

## Chamberí (CHA): what to sell, to whom, where

Our CHA values (book × 0.5): common 5, uncommon 12.5, rare 35, epic 90, legendary 225. CHA is a pure sell set for us.

**When:** `/api/schedule` (read at tick 1445) puts `set_release CHA` at **16.65 h**, the same game hour as Sunday's
open and the 150 P grant (16.7). The night brief says ~10:39. Check `t_hours` and `/api/catalog` at the open
(INFERRED either way).

**Who values CHA high: unknown.** `tools/value_inference.py teams` as shipped is biased on CHA: it counts CHA as "in
play" only because t07 asked El Chato for CHA-06 ten times (ticks 1074–1083), so 14 of 18 teams come out as CHA
haters. Re-run with CHA decided by elimination, the model still cannot separate the teams (with all evidence every
team lands low; with choices only almost every team lands at 1.6). Weak targets (low confidence): t16, t18, t07, t11
(t11 never trades). Better signal: at the El Retiro launch, 3 of the 4 first-hour bidders turned out to be RET fans.
**Treat the makers of the first `want card:CHA-*` bids as the CHA fans.**

| CHA card | our value | target teams | floor: they take our ask / we take their bid (we pay the fee) | outlet |
|---|---|---|---|---|
| common (01–05) | 5 | first CHA bidders | 8 / 10 | Take any team bid ≥ 10. Pilar never buys commons. Abuela at ≥ 6 only if it improves our best three at her level. El Rastro listings of commons did not sell on Saturday. |
| uncommon (06–08) | 12.5 | first CHA bidders | 16 / 18 | A team bid ≥ 18 first (accepting a team bid of 24 scores 24 − 3 fee − 12.5 = +8.5 by value). Else **Pilar**: anchor 30, floor 22 (from tick 939 she paid a median of 25; RET uncommons 22–26). |
| rare (09–10) | 35 | first CHA bidders; Los Pícaros sell any rare at ~57, which caps teams (INFERRED) | 39 / 43 | Team bid ≥ 55 (+16 or more). Else **Pilar**: anchor 85, floor 65 (non-SAL rares 50–78; RET 78). |
| epic CHA-11 | 90 | the first CHA bidder with cash (t16 729, t11 950, t18 555 before the grant) | 99 / 106 | Ask teams 190–210 (team epic trades 160–216). Fallback Pilar ≥ 150 (she paid 140–199). Not Banco (116–120). |
| legendary CHA-12 | 225 | same | 248 / 263 | No trade data: ask ≥ 400 or hold. |

**Seller vs Pilar:** keep `agent/rastro_seller.py` off. On Saturday it posted 191 El Rastro listings in our log (215
t03 card listings in the feed; the brief's 232 could not be reproduced) and none filled; our spares sold only through
Chato (14) and on v06 (3–6). Pilar is the outlet for CHA uncommons and rares (`agent/chato.py run --dealer pilar
--only sell:<asset> ...`, as in `r3-resell-ret`). Team bids are taken by the desk's sell side if the desk runs with
`--sell-first-copies CHA --sell-margin-frac 0.5`: its sell rule (price − fee ≥ value + max(3, 50 % of value)) then
accepts a CHA common bid from 10, an uncommon from 22 and a rare from 57, close to the table. That flag pair also
makes every other spare sale stricter, never looser. A team sale scores price − fee − our value; a Pilar sale fills
only a ladder slot (best three per level, right side of our value), so a team bid at the floor beats Pilar.
