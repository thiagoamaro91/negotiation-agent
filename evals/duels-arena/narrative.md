> **Superseded.** This climb was tuned with the pre-#47/#54 referee; the params file it produced is kept as `duel-params-duels3-v1-old-referee.json` and is superseded by WP1's file at `docs/duel-lab/duel-params-duels3.json` (fixed referee). Do not deploy this one.

# duels-arena: parameter climb for Duels III (2026-10-03 night)

| round | change | test score | Δ vs baseline ± 95% CI (paired, by session) | friday | saturday | breach | verdict |
|---|---|---|---|---|---|---|---|
| baseline | `duel-params-duels2-final.json` | 0.2537 | — | 0.459 | 0.188 | 0 | — |
| v1 (R1) | `last_chance_ticks` 4 → 2 | 0.2572 | +0.0035 ± 0.0025 (z 2.7) | 0.459 (±0) | 0.188 (±0) | 0 | KEEP |
| v2 (R2) | v1 + `near_ticks` 0 → 2, `late_ticks` 3 → 2 | 0.2586 | +0.0049 ± 0.0025 (vs v1 +0.0014 ± 0.0020, z 1.4) | 0.441 (−0.018) | 0.188 (−0.001) | 0 | REVERT (gain under 2 SE vs v1; Friday guardrail −0.018 > 0.01) |
| v3 (R3) | duel_tune `--session 3` tunables (from defaults: v1 fails its D-1 guard) on v1's late-read keys | 0.2528 | −0.0009 ± 0.0025 (vs v1 −0.0044 ± 0.0031) | 0.456 (−0.003) | 0.190 (+0.002) | 0 | REVERT (worse than v1; duel_ab REJECT: −0.019 held-out, Friday −0.055) |
| v4 (R4) | v1 + `stall_ticks` 4 → 3 | 0.2587 | +0.0050 ± 0.0027 (vs v1 +0.0015 ± 0.0016, z 1.9) | 0.458 (−0.001) | 0.188 (−0.001) | 0 | REVERT (under 2 SE vs v1; duel_ab REJECT −0.0005 on Duels I format) |

**Winner: v1** → `evals/duels-arena/duel-params-duels3-v1-old-referee.json` (v1 with `duel_ticks 12`, `late_poll 4` to match the
factory's flags; scores identical to v1 on all three flows). Stopped after three flat rounds (R2, R3, R4).

Test = 100 arena sessions from seed 900000 (6,800 duels, Duels III format, paired limit hidden). Selection =
duel_tune / duel_ab held-out seeds 500000..; train = seeds 0... The run is deterministic (rerunning baseline gives an
identical results file), so the only noise is case sampling: paired SE 0.0010-0.0013 for these one-lever changes.

**What is winning and why.** The R1 hypothesis (rivals post in-limit offers mid-duel while we wait for the window,
then the one-accept slot is lost) is real but small: only 1.9% of TRAIN duels end with no deal after an acceptable
offer, and the traces show the loss happens in the last 2-3 ticks, when 3-4 duels with the same deadline compete for
one accept per tick. Accepting earlier does not fix it: widening `accept_any_ticks` to 3-6 is flat or worse on TRAIN,
because in this arena most rivals keep conceding to the deadline, so the last ticks are worth waiting for
(`accept_any_ticks 1`, `window_retry 0` and `hold_while_conceding` all gain +0.003 to +0.008 on TRAIN, but lose
0.06-0.10 if a deadline-1 accept does not settle, so they fail the D-1 stress). The one lever of the R1 set that won
is the last-chance timing: sending it with 2 ticks left instead of 4 (+0.0035 on TEST). That gain is almost all
on the `deadline` rival kind (+0.078: it accepts near the deadline, so a later last chance lands) and costs `tft`
(−0.037); under the Duels I field mix (no deadline-type rivals) it is flat (−0.0005 ± 0.0006 on TRAIN), and it gives
up 0.010 in the D-1-never-settles stress (duel_ab: exactly at its tolerance). R2 (slot competition) is flat: the
current `slot_demand acceptable, late_ticks 3, near_ticks 0` is already the best cell of the 60-cell TRAIN grid; the
late read itself is worth +0.030 (`late_poll 0` loses that much), which is why the factory's `--late-poll 4` matters.

R3: `duel_tune.py --session 3` ran through a wrapper (`evals/duels-arena/climb/tune_wrap.py`, nothing in tools/ edited; TRAIN grids: `grid.py`, paired compare: `cmp.py`) because the
plain command keeps only its TUNABLE keys, which drops `late_poll` (late read off, −0.030) and tunes with the paired
limit visible (PAIR_SEEN 1; Sunday hides it). Even so its D-1 guard (no more than 0.03 under duel.py's defaults when a
deadline-1 accept never settles) rejected v1 as a start, so it searched around the defaults: 1,025 candidates in 25
min, one step accepted (+0.003 held-out). The result is much safer if D-1 accepts fail (+0.053 in duel_ab's stress)
but loses 0.004 on TEST and 0.055 on the Friday replay. R4: a 38-cell coordinate grid on the concession schedule and
day levers around v1 was flat (all under +0.0025 on TRAIN); `stall_ticks 3` was the only lever that held on TRAIN
(+0.0020), selection (+0.0016), D-1 stress (+0.0011) and the Duels I mix (+0.0007), and on TEST it reached z 1.9:
a real but too small gain to clear the bar. The landscape around v1 is flat for this arena; the remaining big levers
(`accept_any_ticks 1`, `window_retry 0`, `hold_while_conceding`) all bet on deadline-1 accepts and lose 0.06-0.10 if
one fails to settle at Sunday's 15 s ticks.
