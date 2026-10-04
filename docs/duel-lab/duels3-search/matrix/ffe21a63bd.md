# Duel matrix: Duels III

200 fresh sessions per cell (seeds 970000..), paired limit never visible, 1.8 min. Cells: mean score per duel (share of the pie x decay^rounds, 0 without a deal). Delta: each candidate minus `incumbent` on the same seeds, with its standard error; **bold** = more than 2 SE better, _italic_ = more than 2 SE worse.

| world | mode | incumbent | ffe21a63bd |
|---|---|---|---|
| mix: Duels II field | robust | 0.357 | 0.371 (**+0.014** ±0.001) |
| mix: Duels I field | robust | 0.381 | 0.391 (**+0.010** ±0.001) |
| mix: likely field | robust | 0.420 | 0.428 (**+0.009** ±0.001) |
| mix: Duels II field | confirmed | 0.357 | 0.371 (**+0.014** ±0.001) |
| mix: Duels I field | confirmed | 0.381 | 0.391 (**+0.010** ±0.001) |
| mix: likely field | confirmed | 0.420 | 0.428 (**+0.009** ±0.001) |
| rival: steady | robust | 0.483 | 0.507 (**+0.024** ±0.001) |
| rival: fast | robust | 0.597 | 0.597 (_-0.001_ ±0.000) |
| rival: cycler | robust | 0.086 | 0.084 (_-0.002_ ±0.000) |
| rival: oneshot | robust | 0.164 | 0.165 (+0.001 ±0.001) |
| rival: llm | robust | 0.438 | 0.444 (**+0.006** ±0.001) |
| rival: silent | robust | 0.315 | 0.315 (-0.001 ±0.001) |
| rival: hardliner | robust | 0.192 | 0.196 (**+0.004** ±0.001) |
| rival: linear | robust | 0.498 | 0.521 (**+0.023** ±0.001) |
| rival: tft | robust | 0.304 | 0.307 (**+0.004** ±0.001) |
| rival: deadline | robust | 0.408 | 0.422 (**+0.014** ±0.001) |
| rival: boulware | robust | 0.377 | 0.384 (**+0.008** ±0.002) |
| rival: conceder | robust | 0.542 | 0.553 (**+0.011** ±0.001) |
| rival: greedy | robust | 0.497 | 0.510 (**+0.013** ±0.001) |
| rival: micro | robust | 0.136 | 0.138 (**+0.002** ±0.000) |
| rival: split | robust | 0.390 | 0.429 (**+0.039** ±0.001) |
| rival: logroll | robust | 0.440 | 0.474 (**+0.035** ±0.002) |
| rival: llmfair | robust | 0.306 | 0.288 (_-0.018_ ±0.001) |
| days: as modelled (0-4 P/day, opposed, rivals as fitted) | robust | 0.420 | 0.428 (**+0.009** ±0.001) |
| days: light weights (0-1 P/day) | robust | 0.495 | 0.499 (**+0.005** ±0.001) |
| days: heavy weights (2-8 P/day) | robust | 0.342 | 0.342 (-0.000 ±0.001) |
| days: weights 0.5-4% of cost per day | robust | 0.417 | 0.425 (**+0.008** ±0.001) |
| days: 50% of pairs want the same day | robust | 0.461 | 0.466 (**+0.005** ±0.001) |
| days: rivals stubborn on their best day | robust | 0.415 | 0.423 (**+0.008** ±0.001) |
| days: rivals ignore days (weight 0) | robust | 0.469 | 0.488 (**+0.020** ±0.001) |
| days: rivals name a random day | robust | 0.443 | 0.435 (_-0.007_ ±0.001) |
| days: direction flipped (buyer late, seller early) | robust | 0.325 | 0.331 (**+0.007** ±0.001) |

Duels I replay (real rival price paths; rivals do not react or accept):

- incumbent: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)
- ffe21a63bd: mean score 0.1856, result 550.0 P, deals 21/25 (real run: 574.0 P, 24 deals)

Duels II replay (real (price, day) paths, 16 ticks, decay 0.08; rivals do not react or accept):

- incumbent: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- ffe21a63bd: mean score 0.2382, result 1197.1 P, deals 46/60 (real run: 1415.5 P, 54 deals)
