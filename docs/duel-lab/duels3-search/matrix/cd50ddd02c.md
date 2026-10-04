# Duel matrix: Duels III

200 fresh sessions per cell (seeds 970000..), paired limit never visible, 1.9 min. Cells: mean score per duel (share of the pie x decay^rounds, 0 without a deal). Delta: each candidate minus `incumbent` on the same seeds, with its standard error; **bold** = more than 2 SE better, _italic_ = more than 2 SE worse.

| world | mode | incumbent | cd50ddd02c |
|---|---|---|---|
| mix: Duels II field | robust | 0.357 | 0.368 (**+0.011** ±0.001) |
| mix: Duels I field | robust | 0.381 | 0.386 (**+0.005** ±0.001) |
| mix: likely field | robust | 0.420 | 0.429 (**+0.010** ±0.001) |
| mix: Duels II field | confirmed | 0.357 | 0.368 (**+0.011** ±0.001) |
| mix: Duels I field | confirmed | 0.381 | 0.386 (**+0.005** ±0.001) |
| mix: likely field | confirmed | 0.420 | 0.429 (**+0.010** ±0.001) |
| rival: steady | robust | 0.483 | 0.499 (**+0.015** ±0.002) |
| rival: fast | robust | 0.597 | 0.583 (_-0.014_ ±0.001) |
| rival: cycler | robust | 0.086 | 0.092 (**+0.006** ±0.000) |
| rival: oneshot | robust | 0.164 | 0.176 (**+0.011** ±0.001) |
| rival: llm | robust | 0.438 | 0.455 (**+0.017** ±0.001) |
| rival: silent | robust | 0.315 | 0.330 (**+0.015** ±0.001) |
| rival: hardliner | robust | 0.192 | 0.195 (**+0.002** ±0.001) |
| rival: linear | robust | 0.498 | 0.506 (**+0.009** ±0.001) |
| rival: tft | robust | 0.304 | 0.352 (**+0.048** ±0.001) |
| rival: deadline | robust | 0.408 | 0.400 (_-0.008_ ±0.001) |
| rival: boulware | robust | 0.377 | 0.414 (**+0.038** ±0.002) |
| rival: conceder | robust | 0.542 | 0.552 (**+0.010** ±0.001) |
| rival: greedy | robust | 0.497 | 0.529 (**+0.033** ±0.002) |
| rival: micro | robust | 0.136 | 0.150 (**+0.014** ±0.000) |
| rival: split | robust | 0.390 | 0.443 (**+0.052** ±0.001) |
| rival: logroll | robust | 0.440 | 0.462 (**+0.022** ±0.002) |
| rival: llmfair | robust | 0.306 | 0.302 (_-0.004_ ±0.002) |
| days: as modelled (0-4 P/day, opposed, rivals as fitted) | robust | 0.420 | 0.429 (**+0.010** ±0.001) |
| days: light weights (0-1 P/day) | robust | 0.495 | 0.494 (-0.000 ±0.002) |
| days: heavy weights (2-8 P/day) | robust | 0.342 | 0.349 (**+0.007** ±0.001) |
| days: weights 0.5-4% of cost per day | robust | 0.417 | 0.427 (**+0.010** ±0.001) |
| days: 50% of pairs want the same day | robust | 0.461 | 0.452 (_-0.009_ ±0.002) |
| days: rivals stubborn on their best day | robust | 0.415 | 0.419 (**+0.004** ±0.001) |
| days: rivals ignore days (weight 0) | robust | 0.469 | 0.481 (**+0.012** ±0.002) |
| days: rivals name a random day | robust | 0.443 | 0.437 (_-0.006_ ±0.001) |
| days: direction flipped (buyer late, seller early) | robust | 0.325 | 0.316 (_-0.008_ ±0.002) |

Duels I replay (real rival price paths; rivals do not react or accept):

- incumbent: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)
- cd50ddd02c: mean score 0.1863, result 552.4 P, deals 21/25 (real run: 574.0 P, 24 deals)

Duels II replay (real (price, day) paths, 16 ticks, decay 0.08; rivals do not react or accept):

- incumbent: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- cd50ddd02c: mean score 0.2376, result 1193.7 P, deals 45/60 (real run: 1415.5 P, 54 deals)
