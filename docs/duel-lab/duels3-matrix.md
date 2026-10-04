# Duel matrix: Duels III

200 fresh sessions per cell (seeds 970000..), paired limit never visible, 2.2 min. Cells: mean score per duel (share of the pie x decay^rounds, 0 without a deal). Delta: each candidate minus `blend` on the same seeds, with its standard error; **bold** = more than 2 SE better, _italic_ = more than 2 SE worse.

| world | mode | blend | duels3 | v1 | blend-no-days-best |
|---|---|---|---|---|---|
| mix: Duels II field | robust | 0.357 | 0.364 (**+0.007** ±0.001) | 0.359 (+0.003 ±0.001) | 0.313 (_-0.044_ ±0.002) |
| mix: Duels I field | robust | 0.381 | 0.384 (**+0.003** ±0.001) | 0.383 (+0.002 ±0.001) | 0.358 (_-0.023_ ±0.001) |
| mix: likely field | robust | 0.420 | 0.422 (**+0.002** ±0.001) | 0.426 (**+0.006** ±0.002) | 0.397 (_-0.023_ ±0.001) |
| mix: Duels II field | confirmed | 0.357 | 0.364 (**+0.007** ±0.001) | 0.359 (+0.003 ±0.001) | 0.357 (+0.000 ±0.000) |
| mix: Duels I field | confirmed | 0.381 | 0.384 (**+0.003** ±0.001) | 0.383 (+0.002 ±0.001) | 0.381 (+0.000 ±0.000) |
| mix: likely field | confirmed | 0.420 | 0.422 (**+0.002** ±0.001) | 0.426 (**+0.006** ±0.002) | 0.420 (+0.000 ±0.000) |
| rival: steady | robust | 0.483 | 0.489 (**+0.006** ±0.001) | 0.499 (**+0.016** ±0.002) | 0.465 (_-0.019_ ±0.002) |
| rival: fast | robust | 0.597 | 0.597 (+0.000 ±0.000) | 0.571 (_-0.026_ ±0.001) | 0.551 (_-0.047_ ±0.001) |
| rival: cycler | robust | 0.086 | 0.086 (_-0.000_ ±0.000) | 0.100 (**+0.014** ±0.000) | 0.082 (_-0.004_ ±0.000) |
| rival: oneshot | robust | 0.164 | 0.164 (+0.000 ±0.000) | 0.140 (_-0.025_ ±0.002) | 0.149 (_-0.016_ ±0.001) |
| rival: llm | robust | 0.438 | 0.440 (**+0.002** ±0.000) | 0.462 (**+0.024** ±0.001) | 0.416 (_-0.022_ ±0.001) |
| rival: silent | robust | 0.315 | 0.315 (+0.000 ±0.000) | 0.321 (**+0.006** ±0.001) | 0.280 (_-0.036_ ±0.001) |
| rival: hardliner | robust | 0.192 | 0.192 (_-0.001_ ±0.000) | 0.204 (**+0.011** ±0.001) | 0.181 (_-0.011_ ±0.001) |
| rival: linear | robust | 0.498 | 0.504 (**+0.006** ±0.001) | 0.507 (**+0.009** ±0.001) | 0.473 (_-0.025_ ±0.001) |
| rival: tft | robust | 0.304 | 0.305 (**+0.002** ±0.000) | 0.298 (_-0.005_ ±0.002) | 0.298 (_-0.005_ ±0.001) |
| rival: deadline | robust | 0.408 | 0.408 (+0.000 ±0.000) | 0.451 (**+0.042** ±0.001) | 0.356 (_-0.052_ ±0.002) |
| rival: boulware | robust | 0.377 | 0.376 (-0.001 ±0.002) | 0.424 (**+0.048** ±0.003) | 0.361 (_-0.016_ ±0.002) |
| rival: conceder | robust | 0.542 | 0.546 (**+0.004** ±0.001) | 0.546 (**+0.004** ±0.001) | 0.503 (_-0.039_ ±0.001) |
| rival: greedy | robust | 0.497 | 0.497 (+0.000 ±0.000) | 0.485 (_-0.012_ ±0.002) | 0.440 (_-0.056_ ±0.002) |
| rival: micro | robust | 0.136 | 0.137 (**+0.001** ±0.000) | 0.137 (**+0.001** ±0.001) | 0.129 (_-0.007_ ±0.000) |
| rival: split | robust | 0.390 | 0.391 (**+0.000** ±0.000) | 0.401 (**+0.011** ±0.002) | 0.359 (_-0.031_ ±0.001) |
| rival: logroll | robust | 0.440 | 0.453 (**+0.014** ±0.002) | 0.457 (**+0.017** ±0.002) | 0.428 (_-0.011_ ±0.002) |
| rival: llmfair | robust | 0.306 | 0.292 (_-0.014_ ±0.001) | 0.295 (_-0.011_ ±0.003) | 0.295 (_-0.011_ ±0.001) |
| days: as modelled (0-4 P/day, opposed, rivals as fitted) | robust | 0.420 | 0.422 (**+0.002** ±0.001) | 0.426 (**+0.006** ±0.002) | 0.397 (_-0.023_ ±0.001) |
| days: light weights (0-1 P/day) | robust | 0.495 | 0.487 (_-0.008_ ±0.001) | 0.507 (**+0.012** ±0.002) | 0.495 (+0.000 ±0.001) |
| days: heavy weights (2-8 P/day) | robust | 0.342 | 0.339 (_-0.003_ ±0.001) | 0.366 (**+0.024** ±0.002) | 0.245 (_-0.097_ ±0.002) |
| days: weights 0.5-4% of cost per day | robust | 0.417 | 0.417 (+0.000 ±0.001) | 0.420 (+0.003 ±0.002) | 0.392 (_-0.025_ ±0.002) |
| days: 50% of pairs want the same day | robust | 0.461 | 0.458 (_-0.003_ ±0.001) | 0.465 (**+0.004** ±0.002) | 0.431 (_-0.030_ ±0.002) |
| days: rivals stubborn on their best day | robust | 0.415 | 0.415 (+0.000 ±0.001) | 0.420 (**+0.005** ±0.002) | 0.396 (_-0.019_ ±0.001) |
| days: rivals ignore days (weight 0) | robust | 0.469 | 0.473 (**+0.004** ±0.001) | 0.484 (**+0.015** ±0.002) | 0.425 (_-0.044_ ±0.002) |
| days: rivals name a random day | robust | 0.443 | 0.439 (_-0.003_ ±0.001) | 0.445 (+0.002 ±0.002) | 0.409 (_-0.034_ ±0.002) |
| days: direction flipped (buyer late, seller early) | robust | 0.325 | 0.318 (_-0.007_ ±0.001) | 0.355 (**+0.031** ±0.002) | 0.398 (**+0.074** ±0.002) |

Duels I replay (real rival price paths; rivals do not react or accept):

- blend: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)
- duels3: mean score 0.1887, result 555.8 P, deals 22/25 (real run: 574.0 P, 24 deals)
- v1: mean score 0.1884, result 558.5 P, deals 21/25 (real run: 574.0 P, 24 deals)
- blend-no-days-best: mean score 0.1898, result 558.7 P, deals 22/25 (real run: 574.0 P, 24 deals)

Duels II replay (real (price, day) paths, 16 ticks, decay 0.08; rivals do not react or accept):

- blend: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- duels3: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- v1: mean score 0.2425, result 1226.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
- blend-no-days-best: mean score 0.2391, result 1204.0 P, deals 46/60 (real run: 1415.5 P, 54 deals)
