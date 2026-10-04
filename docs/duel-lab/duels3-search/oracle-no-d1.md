# Ceiling of role- and rival-type-specific settings (hypotheses b, c)

duel.py's params cannot condition on our role (only days_best is per role) or on the rival's type, so these levers cannot ship tonight. This measures the ceiling instead: every one-lever sweep candidate is scored in the main world with the result split by (rival type, our role); for each split the best single lever change against the incumbent is picked (on train seeds) and re-measured on select seeds, and the ceiling is the duel-weighted sum of those per-split gains. An oracle that knows the type is an upper bound: recognising a bot (tools/duel_book.py) costs ticks and errs.

Train 300 sessions (pick), select 600 sessions (re-measure), main world.

| split | duels per session | best single lever (train pick) | train Δ per duel | select Δ per duel |
|---|---|---|---|---|
| kind: linear | 25.2 | hold_counter=False | +0.0296 ±0.0015 | +0.0297 ±0.0010 |
| kind: oneshot | 10.0 | absent_at=0.0 | +0.0103 ±0.0012 | +0.0097 ±0.0008 |
| kind: steady | 7.5 | hold_counter=False | +0.0417 ±0.0038 | +0.0415 ±0.0025 |
| kind: self | 7.2 | absent_at=0.08 | +0.0611 ±0.0029 | +0.0572 ±0.0020 |
| kind: fast | 7.5 | stall_ticks=1 | +0.0058 ±0.0017 | +0.0061 ±0.0012 |
| kind: absent | 4.9 | anchor=1.35 | +0.0000 ±0.0000 | +0.0000 ±0.0000 |
| kind: tft | 4.6 | accept_any_ticks=3 | +0.0562 ±0.0053 | +0.0499 ±0.0037 |
| kind: silent | 3.5 | silent_last_margin=0.1 | +0.0177 ±0.0047 | +0.0125 ±0.0033 |
| role: buyer | 34.0 | absent_at=0.0 | +0.0305 ±0.0017 | +0.0305 ±0.0012 |
| role: seller | 34.0 | hold_counter=False | +0.0293 ±0.0011 | +0.0290 ±0.0008 |

- Ceiling by rival type: +0.0268 per duel (±0.0006; negative select gains counted as 0, so this is an optimistic bound).
- Ceiling by our role: +0.0298 per duel (±0.0007; negative select gains counted as 0, so this is an optimistic bound).
