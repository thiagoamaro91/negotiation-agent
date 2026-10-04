# The overnight duel search, in plain words

_Draft; the numbers marked TBD are filled in by the final TEST run._

## What we did

While the team slept, a training system tried TBD versions of our duel bot against simulated rivals and kept the
ones that won. The rivals are not invented: they copy what the 68 real rival bots of Duels II did (28 conceded a
little every tick, 11 spoke once, 8 stepped, 8 jumped and held, 5 only moved after we did, 8 never spoke), plus a
copy of our own bot, because other teams may have built something like ours. Every version played Duels III's
rules: 12-tick duels, 10 % of the pie lost per round of talk, four duels at once, price and delivery day.

Three separate sets of simulated sessions keep it honest: versions are trained on one set, chosen on a second and
judged once on a third that the search never saw. A version only replaces the one we run if it wins on that last
set by more than twice the noise, is not worse against any single kind of rival, survives the worst case of the
15-second ticks, and passes the bot's own safety self-test.

## What we learned

- **The tempting trap.** The biggest raw gains in the first sweep (about +1.4 % of the pie per duel) all came from
  waiting until the very last tick to accept. At 15-second ticks an accept sent with one tick left may never
  settle, and then those versions lose about 11 % of the pie per duel. We put that worst case into the score, and
  the trap disappeared from the search.
- **Against a copy of ourselves, whoever speaks first wins.** Two patient bots both wait; opening one tick earlier
  against our own copy is worth +5.7 % of the pie in those duels.
- **What does nothing.** Several levers change nothing in Duels III because the paired limit is hidden: the early
  accept, the share asked from a silent rival, the near-deadline window. The delivery-day reading (days_best) is
  the single most valuable setting we have: switching it off costs 5.5 % of the pie per duel.

## What won

TBD

## What lost

TBD
