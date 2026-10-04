# Duel matrix: Final

60 fresh sessions per cell (seeds 970000..), paired limit never visible, 0.3 min. Cells: mean score per duel (share of the pie x decay^rounds, 0 without a deal). Delta: each candidate minus `base` on the same seeds, with its standard error; **bold** = more than 2 SE better, _italic_ = more than 2 SE worse.

| world | mode | base | hold_while_conceding@True | silent_last_margin@0.05 |
|---|---|---|---|---|
| mix: Duels II field | robust | 0.363 | 0.350 (_-0.013_ ±0.003) | 0.363 (+0.000 ±0.001) |
| mix: Duels I field | robust | 0.388 | 0.372 (_-0.016_ ±0.002) | 0.386 (-0.001 ±0.001) |
| mix: likely field | robust | 0.422 | 0.412 (_-0.011_ ±0.003) | 0.424 (+0.002 ±0.001) |
| mix: Duels III refit | robust | 0.398 | 0.382 (_-0.016_ ±0.002) | 0.398 (+0.000 ±0.000) |
| mix: Duels II field | confirmed | 0.363 | 0.350 (_-0.013_ ±0.003) | 0.363 (+0.000 ±0.001) |
| mix: Duels I field | confirmed | 0.388 | 0.372 (_-0.016_ ±0.002) | 0.386 (-0.001 ±0.001) |
| mix: likely field | confirmed | 0.422 | 0.412 (_-0.011_ ±0.003) | 0.424 (+0.002 ±0.001) |
| mix: Duels III refit | confirmed | 0.398 | 0.382 (_-0.016_ ±0.002) | 0.398 (+0.000 ±0.000) |
| d1: Duels II field | robust | 0.332 | 0.222 (_-0.110_ ±0.006) | 0.332 (+0.000 ±0.001) |
| d1: Duels I field | robust | 0.359 | 0.247 (_-0.112_ ±0.006) | 0.358 (-0.001 ±0.001) |
| d1: likely field | robust | 0.374 | 0.269 (_-0.105_ ±0.006) | 0.375 (+0.001 ±0.001) |
| d1: Duels III refit | robust | 0.356 | 0.252 (_-0.105_ ±0.005) | 0.356 (+0.000 ±0.000) |
| rival: steady | robust | 0.478 | 0.467 (_-0.011_ ±0.004) | 0.478 (+0.000 ±0.000) |
| rival: fast | robust | 0.604 | 0.579 (_-0.024_ ±0.001) | 0.604 (+0.000 ±0.000) |
| rival: cycler | robust | 0.083 | 0.082 (-0.002 ±0.001) | 0.083 (+0.000 ±0.000) |
| rival: oneshot | robust | 0.176 | 0.176 (+0.000 ±0.000) | 0.176 (+0.000 ±0.000) |
| rival: llm | robust | 0.446 | 0.454 (**+0.008** ±0.001) | 0.446 (+0.000 ±0.000) |
| rival: silent | robust | 0.314 | 0.314 (+0.000 ±0.000) | 0.324 (**+0.010** ±0.003) |
| rival: hardliner | robust | 0.195 | 0.190 (_-0.005_ ±0.002) | 0.195 (+0.000 ±0.000) |
| rival: linear | robust | 0.500 | 0.470 (_-0.030_ ±0.003) | 0.500 (+0.000 ±0.000) |
| rival: tft | robust | 0.319 | 0.320 (+0.001 ±0.001) | 0.319 (+0.000 ±0.000) |
| rival: deadline | robust | 0.417 | 0.417 (+0.000 ±0.000) | 0.351 (_-0.066_ ±0.002) |
| rival: boulware | robust | 0.375 | 0.397 (**+0.022** ±0.005) | 0.375 (+0.000 ±0.000) |
| rival: conceder | robust | 0.535 | 0.502 (_-0.034_ ±0.003) | 0.535 (+0.000 ±0.000) |
| rival: greedy | robust | 0.494 | 0.494 (+0.000 ±0.000) | 0.515 (**+0.021** ±0.005) |
| rival: micro | robust | 0.133 | 0.147 (**+0.014** ±0.001) | 0.133 (+0.000 ±0.000) |
| rival: split | robust | 0.388 | 0.422 (**+0.034** ±0.002) | 0.388 (+0.000 ±0.000) |
| rival: logroll | robust | 0.440 | 0.433 (-0.006 ±0.004) | 0.440 (+0.000 ±0.000) |
| rival: llmfair | robust | 0.299 | 0.317 (**+0.018** ±0.002) | 0.299 (+0.000 ±0.000) |
| days: as modelled (0-4 P/day, opposed, rivals as fitted) | robust | 0.422 | 0.412 (_-0.011_ ±0.003) | 0.424 (+0.002 ±0.001) |
| days: light weights (0-1 P/day) | robust | 0.497 | 0.469 (_-0.027_ ±0.003) | 0.497 (+0.001 ±0.001) |
| days: heavy weights (2-8 P/day) | robust | 0.342 | 0.313 (_-0.029_ ±0.004) | 0.343 (+0.001 ±0.001) |
| days: weights 0.5-4% of cost per day | robust | 0.417 | 0.410 (_-0.008_ ±0.003) | 0.419 (+0.002 ±0.001) |
| days: 50% of pairs want the same day | robust | 0.459 | 0.426 (_-0.033_ ±0.005) | 0.459 (+0.000 ±0.001) |
| days: rivals stubborn on their best day | robust | 0.418 | 0.407 (_-0.011_ ±0.003) | 0.420 (+0.002 ±0.001) |
| days: rivals ignore days (weight 0) | robust | 0.469 | 0.473 (+0.004 ±0.003) | 0.471 (+0.002 ±0.002) |
| days: rivals name a random day | robust | 0.447 | 0.416 (_-0.031_ ±0.003) | 0.448 (+0.002 ±0.001) |
| days: direction flipped (buyer late, seller early) | robust | 0.333 | 0.317 (_-0.017_ ±0.003) | 0.332 (-0.001 ±0.001) |

Duels I replay (real rival price paths; rivals do not react or accept):

- base: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)
- hold_while_conceding@True: mean score 0.1760, result 520.5 P, deals 21/25 (real run: 574.0 P, 24 deals)
- silent_last_margin@0.05: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)

Duels II replay (real (price, day) paths, 16 ticks, decay 0.08; rivals do not react or accept):

- base: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- hold_while_conceding@True: mean score 0.2314, result 1167.8 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- silent_last_margin@0.05: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
