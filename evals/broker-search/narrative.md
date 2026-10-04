# We searched all night: what the data said about beating the stall

Lane WP11, night of 3–4 Oct 2026. Lab: `evals/broker-search/`. Numbers: `leaderboard.md` (refreshed every 30 minutes
during the search) and `runs/confirm.jsonl`.

## The question

The Market Test scores the share of the possible gains between the bench traders' true limits that our venue
realises. The free stall's rule matches the best bid against the best ask, every tick, while they cross. In the
simulator it gets about 0.89 of the possible gains; a broker that knew every trader's schedule would get about 0.96.
The memo (`docs/plans/market-test-sunday.md`) already showed that two cleverer matching rules (`maxpairs`, `maxweight`)
lose to the stall. The gap that is left is timing: who leaves when. On Saturday no bench offer showed its own expiry,
so a policy has to win **blind**, reading only quotes, or it is useless on Sunday.

## The rule, fixed before the first run

Recommendable for the hard test only if: it beats the stall on `hard` by more than 2 SE, AND it is not worse than the
stall beyond noise on any of the other nine simulator mixes or the five refits of Saturday's real sessions, AND it
never lets both traders of a pair the stall would have crossed leave unmatched, AND no bad match. Recommendable
everywhere only if it also beats the stall by more than 2 SE on `standard` and on each refit. Selection used its own
seeds (`screen`); the leaderboard uses 1,000 different seeds (`unseen`) × 4 sessions per scenario; the final TEST
uses 2,000 more (`holdout`) that no selection step saw.

## What we searched

From 02:36 to 06:15 Madrid the driver screened **6,648 candidates** (1,662 per family; about 45 seconds per round
of 24, half drawn at random, half mutations of the best so far), sent 1,845 of them through the whole 15-scenario
battery, and confirmed 63 members on the unseen seeds (plus 8 reference rows). The final TEST ran the best member of
each family on the holdout seeds. A second phase (06:15–07:38 Madrid) screened 2,376 more candidates (9,024 in all) and
confirmed 16 more members on the unseen seeds; none was recommendable and none displaced a family's best member.

1. **Blind estimates**: our own `BenchPolicy` (estimated limits plus a patience prior; it holds traders it believes are
   patient) with every prior swept: shading, firm and first-sight shades, the impatient share and both patience
   ranges, how much of a staying trader's surplus to expect later, the minimum edge, the expiry margin, and two
   quote-path slope rules.
2. **Timing rules without expiries**: the stall's plan, changed only by quote-path rules. "Hold" keeps a pair back
   while its counterpart is still relaxing and the other side has at least N patient-looking traders (N and the
   relaxing window searched). "Second" gives the seller to an unmatched trader that looks about to leave, in place of
   a matched one that looks patient (thresholds, how much quote to give up, sides, number of swaps searched).
3. **Hybrid**: the stall by default, deviating only when a classifier of "leaving after this tick", fitted on
   Saturday's five recorded sessions (quote paths only), says an unmatched trader is about to leave. Plus a 3b
   variant that puts the classifier's probability inside `BenchPolicy`.

## What the data said

**Nothing beats the stall in a way that matters.** One member came close, and only one family produced it.

| family | best member (TEST, 2,000 holdout seeds × 4 sessions) | hard | standard | worst refit | verdict |
|---|---|---|---|---|---|
| 1 blind estimates | `8cfbaa8061` | +0.06 (z +1.6) | −0.02 | −0.10 (z −3.3) | not recommended: worse on 4 refits, drops 126 pairs the stall crossed |
| 2 timing rules | `79977000b8` ("second", buyers only, one swap) | **+0.09 (z +3.7)** | +0.06 (z +2.2) | −0.03 (z −1.2) | recommendable for the hard test on these seeds, but **not** on the unseen seeds (+0.05, z +1.7) |
| 3 hybrid swap | `23548db80f` | −0.00 | −0.00 | −0.01 | not recommended: it barely ever deviates |
| 3b classifier in BenchPolicy | `59f17ee96d` | +0.08 (z +2.3) | −0.05 | −0.18 (z −5.3) | not recommended: worse on all five refits |

(Cells in points of efficiency, i.e. hundredths of the share of the possible gains.)

The timing member is the most honest near-miss of the night. Its rule is: when an unmatched buyer looks like it is
about to leave (seen for the first time, never relaxed its bid, or relaxing fast) and a matched buyer looks patient
(relaxing its bid slowly), and the leaving-looking buyer's bid is at most 10 % lower and still crosses, give it the
seller and let the patient buyer wait. It fires in about one session in 35. Pooled over unseen and holdout seeds
(3,000 seeds × 4 sessions) it is +0.08 points on `hard` (z +4.0), never worse than the stall beyond noise anywhere,
and it never lets go of a pair the stall would have crossed. It does sometimes leave a crossable pair unmatched
(117 in the 60,000 holdout sessions; the stall, by construction, never does): typically the patient buyer it held back,
leaving later without a seller. But four of the five refits of Saturday's real sessions
have it slightly below the stall (within noise), and the whole gain is under a tenth of a point of efficiency. That is
smaller than the simulator's own known bias in level (it gives the stall about 0.80 where the real stall scored
0.90–0.97). It is implemented as `--policy swap` in a separate commit that can be dropped. We do not recommend
running it: the only hard test (09:39) comes before the first long restart window, and a restart to win at most 0.1
point is not worth the operational risk.

**Timing is worth a lot if you know it, and nothing if you guess.** We gave `BenchPolicy` the simulator's truth
(who leaves after this tick): it beats the stall by +1.6 to +4.3 points of efficiency in every scenario and every
refit except `arrive_all0` (+0.09, where everyone arrives at once and the stall is already at 0.96). Then we flipped a share of those perfect flags at random: with 5 % of them wrong most of the gain is gone and
two refits and two mixes turn negative; with 15 % wrong it loses everywhere (−0.4 to −3.4 points); with 30 % wrong it loses up to
5.9 points. Holding a trader who is in fact leaving loses a whole trade; matching a patient one early loses only a
little; so errors cost far more than hits earn.

**And the best guess the data allows is far from 5 %.** A logistic classifier of "leaving after this tick" from quote
paths, scored on each recorded session after fitting on the other four, reaches AUC 0.73 (log loss 0.496 against
0.553 for the base rate). A model fitted on simulated hard sessions does a little better on the real data (AUC 0.79),
still nowhere near the accuracy at which waiting pays.

**The swap with perfect information also loses.** Giving the seller to the trader who really is leaving, in place of
one who stays, loses in 14 of the 16 rows, by up to 2.9 points, even with the truth: the trader who stays often finds no seller later, or a
worse one. Displacement again, as in the memo.

**Saturday's sessions are the worst case for waiting.** The refits are 83–91 % impatient traders who stay 1–5 ticks:
almost everyone leaves soon, so matching now is almost always right. The policies that hold traders (families 1
and 3b) are worse than the stall on every refit.

## In one sentence (for the pitch)

"Overnight we pitted 6,600 blind broker policies against the free stall under rules we fixed before the first run:
knowing who leaves when would be worth 2–3 points of efficiency, but getting just 5 % of departures wrong erases it, and
quote paths predict departures far worse than that, so the best blind policy beats the stall by less than a tenth of a
point. We run the stall's rule, and we can show why."
