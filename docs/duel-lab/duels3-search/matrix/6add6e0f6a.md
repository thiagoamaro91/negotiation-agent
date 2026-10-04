# Duel matrix: Duels III

200 fresh sessions per cell (seeds 970000..), paired limit never visible, 1.8 min. Cells: mean score per duel (share of the pie x decay^rounds, 0 without a deal). Delta: each candidate minus `incumbent` on the same seeds, with its standard error; **bold** = more than 2 SE better, _italic_ = more than 2 SE worse.

| world | mode | incumbent | 6add6e0f6a |
|---|---|---|---|
| mix: Duels II field | robust | 0.357 | 0.368 (**+0.011** ±0.001) |
| mix: Duels I field | robust | 0.381 | 0.391 (**+0.011** ±0.001) |
| mix: likely field | robust | 0.420 | 0.433 (**+0.013** ±0.001) |
| mix: Duels II field | confirmed | 0.357 | 0.368 (**+0.011** ±0.001) |
| mix: Duels I field | confirmed | 0.381 | 0.391 (**+0.011** ±0.001) |
| mix: likely field | confirmed | 0.420 | 0.433 (**+0.013** ±0.001) |
| rival: steady | robust | 0.483 | 0.507 (**+0.023** ±0.001) |
| rival: fast | robust | 0.597 | 0.595 (_-0.002_ ±0.000) |
| rival: cycler | robust | 0.086 | 0.092 (**+0.006** ±0.000) |
| rival: oneshot | robust | 0.164 | 0.164 (-0.000 ±0.001) |
| rival: llm | robust | 0.438 | 0.450 (**+0.012** ±0.001) |
| rival: silent | robust | 0.315 | 0.316 (+0.001 ±0.001) |
| rival: hardliner | robust | 0.192 | 0.202 (**+0.009** ±0.001) |
| rival: linear | robust | 0.498 | 0.516 (**+0.019** ±0.001) |
| rival: tft | robust | 0.304 | 0.353 (**+0.050** ±0.002) |
| rival: deadline | robust | 0.408 | 0.422 (**+0.014** ±0.001) |
| rival: boulware | robust | 0.377 | 0.410 (**+0.034** ±0.002) |
| rival: conceder | robust | 0.542 | 0.552 (**+0.010** ±0.001) |
| rival: greedy | robust | 0.497 | 0.518 (**+0.021** ±0.002) |
| rival: micro | robust | 0.136 | 0.144 (**+0.008** ±0.000) |
| rival: split | robust | 0.390 | 0.460 (**+0.070** ±0.001) |
| rival: logroll | robust | 0.440 | 0.462 (**+0.022** ±0.002) |
| rival: llmfair | robust | 0.306 | 0.299 (_-0.007_ ±0.002) |
| days: as modelled (0-4 P/day, opposed, rivals as fitted) | robust | 0.420 | 0.433 (**+0.013** ±0.001) |
| days: light weights (0-1 P/day) | robust | 0.495 | 0.511 (**+0.017** ±0.001) |
| days: heavy weights (2-8 P/day) | robust | 0.342 | 0.353 (**+0.011** ±0.001) |
| days: weights 0.5-4% of cost per day | robust | 0.417 | 0.429 (**+0.012** ±0.001) |
| days: 50% of pairs want the same day | robust | 0.461 | 0.473 (**+0.012** ±0.001) |
| days: rivals stubborn on their best day | robust | 0.415 | 0.427 (**+0.012** ±0.001) |
| days: rivals ignore days (weight 0) | robust | 0.469 | 0.486 (**+0.018** ±0.001) |
| days: rivals name a random day | robust | 0.443 | 0.445 (+0.002 ±0.001) |
| days: direction flipped (buyer late, seller early) | robust | 0.325 | 0.339 (**+0.014** ±0.001) |

Duels I replay (real rival price paths; rivals do not react or accept):

- incumbent: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)
- 6add6e0f6a: mean score 0.1865, result 552.8 P, deals 21/25 (real run: 574.0 P, 24 deals)

Duels II replay (real (price, day) paths, 16 ticks, decay 0.08; rivals do not react or accept):

- incumbent: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- 6add6e0f6a: mean score 0.2379, result 1192.9 P, deals 45/60 (real run: 1415.5 P, 54 deals)
