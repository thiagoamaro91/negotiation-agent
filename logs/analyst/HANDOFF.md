TRIGGER 10:23 hard Market Test read-out (b121, ticks 1690-1706; tick 1720, logs from origin/mini/logs at 10:22)
VERDICT stall behaved: 7 matches, 178 P = 85% of best 209 P, 100% of quote ceiling; ours replay identical; 24/24 expiries = session end -> keep stall. Score 27.71 rank 5 (leader t10 31.68, t05 29.58 just above, gap 1.87); score.jsonl stale since tick 1445
PROPOSE nothing for the bots; findings: clock ran 09:20 (late start), 1 game h = 1 wall h, schedule re-timed: MT ~10:37, Duels III ~10:59, MT ~12:37, stalls close + Final ~13:59, scores freeze ~14:59
NEEDS YES none (heads-up: dealer stalls close ~13:59 and only 2 Market Tests remain; Mini score reader has no row after tick 1445)
PR (see below)
ORGANISERS: feed#73309 tick 1445 announcement "Good morning! The Bazaar is open again: Sunday until 15:00, one tick every 15 s."
ORGANISERS: feed#73355 tick 1448 schedule.fired grant_all "The Sunday allowance: 150 primas for everyone"
ORGANISERS: feed#76432 tick 1553 announcement "Bug bounty: thank you, Team 12! You found and documented a real scoring bug, fixed overnight. A silver pack is on its way to you."
ORGANISERS: news#14 tick 1482 [Radio Rastro] "Bonus pay: the Bazaar gives everyone 60 primas in one hour" (no grant event seen by tick 1720)
ORGANISERS: news#12,13,15,16 [El Tablón/rumours] "Someone lost a red umbrella next to Abuela's stall" / "Tomorrow common cards will be worth double" / "El Rastro closes at midnight for roadworks" / "Anyone want to swap a Cine Doré for two roast chestnuts?"
