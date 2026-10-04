# The overnight duel search, in plain words

_Interim version, 06:45 Madrid. The search keeps running until 07:45; anything that passes after 06:45 is pitch
material, not something we deploy on Sunday._

## What we did

While the team slept, a training system tried about 1,800 versions of our duel bot against simulated rivals and
kept the ones that won. The rivals are not invented: they copy what the 68 real rival bots of Duels II did (28
conceded a little every tick, 11 spoke once, 8 stepped, 8 jumped and held, 5 only moved after we did, 8 never
spoke), plus a copy of our own bot, because other teams may have built something like ours. Every version played
Duels III's rules: 12-tick duels, 10 % of the pie lost per round of talk, four duels at once, price and delivery day.
We also tested a "field drift" world (a fifth of the rivals turn into last-second conceders or mute bots) and the
Grand Final's single round.

Three separate sets of simulated sessions keep it honest: versions are trained on one set, chosen on a second and
judged once on a third that the search never saw. A version only replaces the one we run if it wins on that last
set by more than twice the noise, is not worse against any single kind of rival, survives the worst case of the
15-second ticks, and passes the bot's own safety self-test.

## What we learned

- **The tempting trap.** The biggest raw gains of the first sweep (about +1.4 % of the pie per duel) all came from
  waiting until the very last tick to accept. At 15-second ticks an accept sent with one tick left may never
  settle, and then those versions lose about 11 % of the pie per duel. We put that worst case into the score and
  the trap disappeared from the search.
- **The best version found wins +2.2 % of the pie per duel on unseen sessions** (±0.08 %), and stays ahead in the
  drift world (+1.8 %), the Final (+2.1 %) and the 15-second worst case (+0.6 %). It does this by asking a little
  higher, keeping a wider endgame window, waiting for a rival that is still conceding (but never later than two
  ticks before the end) and sending a mute rival one fair last offer.
- **Half of that gain is against our own copy.** Against a copy of our current bot it wins +12.5 % of the pie per
  duel: two patient bots both wait, and the one that moves first and smarter takes more. Against the real Duels II
  field alone the gain is +0.95 % per duel. Both numbers are honest; the second is the one to quote for the field.
- **Why it is not deployed.** It still loses 1.7 % per duel against one rival style (bots that jump to their price
  and then hold), and its first form broke the bot's safety self-test (a minimum-margin setting made a last offer
  step backwards). Our rule says a version that is worse against any single rival type does not ship, so Sunday
  runs the incumbent.
- **What does nothing.** Several levers change nothing in Duels III because the paired limit is hidden: the early
  accept, the share asked from a silent rival, the near-deadline window. The delivery-day reading (days_best) is
  the single most valuable setting we have: switching it off costs 5.5 % of the pie per duel.
- **What type-recognition could be worth.** If the bot knew each rival's style and our role, the best single
  setting per style would add up to roughly +2.7 % per duel at most (an optimistic ceiling, first measured
  without the 15-second worst case). That is the next lever, and it needs code, not parameters.

## The line for the pitch

"Overnight we searched about 1,800 versions of our duel bot on rivals learned from 68 real duels. The best one wins
2 % more of every pie on sessions it never saw, but it is worse against one rival style, so our own rule kept it on
the bench: we ship only what wins everywhere."
