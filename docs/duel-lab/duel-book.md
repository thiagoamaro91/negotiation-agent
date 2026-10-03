# Duel book: the rival bots behind the colour aliases

Built by `tools/duel_book.py` from 68 duel snapshots in `/Volumes/bazaar/logs/duels` (session 1 = Friday practice, session 2 = Saturday Duels I). A bot is a group of duels whose rival writes with the same text template (numbers -> N, item -> ITEM). Prices are read relative to OUR limit (x limit): a buyer rival opening at 0.56 offers 56 % of our cost; a seller rival at 1.65 asks 165 % of our max. b = the rival was the buyer (we sold), s = the rival was the seller (we bought). Step = median concession per tick in primas, and as a share of the gap between its opening and our limit. Acceptable at = median tick (from the duel start) at which its offer first crosses our limit. Profile columns use session 2 when the bot played it (Friday practice had 12 ticks and our side was mostly silent), n counts every duel. Run `--match "TEXT"` on a first message to name the bot.

| bot | example (first line) | n (s1/s2) | lang | shape | opening x limit @ tick | step P/tick (gap/tick) | acceptable at | reactive? | who accepted | final x limit | recognise it by | how to play it |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B01 | "Hello, and thank you for meeting me. I would propose 156 P for this..." | 4 (2/2) | en | stepped/4 2 | b 0.98 @0 / s 1.03 @0 | b 2.3 (2.33) / s 4.8 (0.97) | b 2 / s 2 | False 2 | we took theirs 2 | b 1.25 / s 0.84 | `hello, and thank you for meeting me. i would propose N p for this one.` at t+0 | steady concession: take its offer at the last safe tick (crosses our limit ~t+2) |
| B02 | "I can do 136. Let's close it quickly." | 4 (2/2) | en | every-tick 2; decelerating | b 1.01 @0 / s 1.00 @0 | b 2.1 (2.14) / s 1.3 (-) | b 0 / s 0 | False 2 | we took theirs 2 | b 1.23 / s 0.85 | `i can do N. let's close it quickly.` at t+0 | concedes early then floors: take it once steps shrink to ~1 P (crosses our limit ~t+0) |
| B03 | "Thank you for meeting me. I can do 51 P." | 4 (2/2) | en | oneshot 1, silent 1 | b 0.65 @0 | b 0.0 (0.00) | - | None 1 | no deal 2 | - | `thank you for meeting me. i can offer N p.` at t+0 | one line then quiet: little to read, make our own offers |
| B04 | "Propuesta justa para cerrar pronto y que ganemos los dos: 76 P." | 4 (2/2) | es | every-tick 2; linear | b 0.77 @0 / s 1.27 @0 | b 2.8 (0.12) / s 4.1 (0.11) | b 9 / s 10 | False 2 | we took theirs 2 | b 1.10 / s 0.92 | `propuesta justa para cerrar pronto y que ganemos los dos.` at t+0 | steady concession: take its offer at the last safe tick (crosses our limit ~t+10) |
| B05 | "We can do 74 P. Thank you for the talk." | 4 (2/2) | en | every-tick 2; decelerating | b 0.99 @0 / s 0.94 @0 | b 1.6 (1.64) / s 2.2 (0.22) | b 1 / s 0 | False 2 | we took theirs 2 | b 1.23 / s 0.81 | `we can do N p. thank you for the talk.` at t+0 | concedes early then floors: take it once steps shrink to ~1 P (crosses our limit ~t+1) |
| B06 | "Puedo llegar a 93 primas. Dime si cerramos." | 4 (2/2) | es | every-tick 2; accelerating | b 0.60 @0 / s 1.13 @0 | b 6.6 (0.11) / s 3.7 (0.21) | b 12 / s 9 | False 2 | we took theirs 2 | b 1.21 / s 0.76 | `puedo llegar a N primas. dime si cerramos.` at t+0 | concedes faster near the end: hold and take its last offer (crosses our limit ~t+12) |
| B07 | "I can do 45. That is a fair deal for both of us." | 4 (2/2) | en | every-tick 2; accelerating | b 0.56 @0 / s 1.65 @0 | b 5.6 (0.16) / s 14.0 (0.16) | b 9 / s 7 | False 2 | we took theirs 2 | b 1.34 / s 0.82 | `i can do N. that is a fair deal for both of us.` at t+0 | concedes faster near the end: hold and take its last offer (crosses our limit ~t+9) |
| B08 | "Hello! I can do 86. Thank you for your time." | 4 (2/2) | en | every-tick 1, silent 1; decelerating | b 0.87 @0 | b 1.9 (0.15) | b 3 | False 1 | we took theirs 1, no deal 1 | b 1.16 | `hello! i can do N. thank you for your time.` at t+0 | concedes early then floors: take it once steps shrink to ~1 P (crosses our limit ~t+3) |
| B09 | "Happy to buy Mercado de la Paz at 114 today. Shall we close fast?" | 4 (2/2) | en | every-tick 2; accelerating | b 1.25 @0 / s 0.88 @0 | b 2.9 (0.13) / s 2.4 (0.14) | b 0 / s 0 | False 2 | we took theirs 2 | b 1.67 / s 0.65 | `i can do N p. every round costs us both, so let's close.` at t+0 | concedes faster near the end: hold and take its last offer (crosses our limit ~t+0) |
| B10 | "Opening bid. Let's find a fair price." | 2 (2/0) | en | oneshot 2 | b 1.04 @4 / s 0.88 @4 | b 0.0 (0.00) / s 0.0 (0.00) | b 4 / s 4 | None 2 | no deal 2 | - | `opening bid. let's find a fair price.` at t+4 | one line then quiet: little to read, make our own offers |
| B11 | "103 P?" | 2 (2/0) | - | stepped 1, jump-hold 1; decelerating | b 0.77 @0 / s 1.18 @0 | b 6.2 (0.20) / s 5.5 (0.20) | b 1 / s 1 | False 2 | no deal 2 | - | `N p?` at t+0 | concedes early then floors: take it once steps shrink to ~1 P (crosses our limit ~t+1) |
| B12 | "I'm offering 85 P for Plaza de Olavide. That's a fair price given t..." | 2 (2/0) | en | stepped/2 2 | b 0.83 @0 / s 0.95 @0 | b 1.5 (0.09) / s 1.5 (0.30) | s 0 | True 2 | no deal 2 | - | long free text, never repeats (LLM) | LLM free text, slow steps; wait for the last ticks (crosses our limit ~t+0) |
| B13 | "I'm a serious buyer and ready to close quickly. For El Mesón de la ..." | 2 (0/2) | en | stepped/3 2; decelerating | b 0.70 @0 / s 1.22 @0 | b 1.6 (0.09) / s 1.7 (0.10) | b 13 / s 13 | False 2 | we took theirs 2 | b 1.06 / s 0.91 | long free text, never repeats (LLM) | LLM free text, slow steps; wait for the last ticks (crosses our limit ~t+13) |
| B14 | "97 for Mercado de la Paz. Every round costs us both: let's close it..." | 2 (0/2) | en | silent 1, stepped/5 1 | s 0.63 @2 | s 1.3 (0.02) | s 2 | False 1 | no deal 1, we took theirs 1 | s 0.54 | `N for ITEM. every round costs us both: let's close it now.` at t+2 | one line then quiet: little to read, make our own offers |
| B15 | "Hi there. 60 P from my side." | 2 (0/2) | en | stepped/3 2 | b 0.69 @2 / s 1.05 @2 | b 6.8 (0.25) / s 7.3 (0.81) | b 8 / s 5 | False 2 | we took theirs 2 | b 1.16 / s 0.79 | `hi there. N p from my side.` at t+2 | steady concession: take its offer at the last safe tick (crosses our limit ~t+8) |
| B16 | "39?" | 2 (0/2) | - | holds 2 | b 0.77 @0 / s 1.26 @0 | b 0.0 (0.00) / s 0.0 (0.00) | - | None 2 | took ours 2 | b 1.10 / s 0.92 | `N?` at t+0 | holds one number all duel; took our offer, so make offers instead of taking its number |
| B17 | "Propongo este precio, creo que es justo para los dos." | 2 (0/2) | es | every-tick 2; linear | b 0.64 @3 / s 1.06 @3 | b 3.3 (0.12) / s 3.0 (0.38) | b 12 / s 6 | False 2 | we took theirs 2 | b 1.10 / s 0.81 | `propongo este precio, creo que es justo para los dos.` at t+3 | steady concession: take its offer at the last safe tick (crosses our limit ~t+12) |
| SILENT | - | 16 (10/6) | - | silent 16 | - | - | - | - | no deal 12, live 2, took ours 2 | a 1.02 | no message at all | never writes; some took our first offer: open high, keep a margin |

## Same team across sessions?

Each session pairs us once with each of the same 17 teams, so a bot seen only on Friday is most likely one of the bots (or silent pairs) seen only on Saturday. Closest template by character overlap (a hint for a human):

- B10 (`opening bid. let's find a fair price.`): closest B17 (0.39); not merged
- B11 (`N p?`): closest B16 (0.67); not merged
- B12 (`i'm offering N p for ITEM. that's a fair price giv`): closest B13 (0.45); not merged

## Evidence (duel ids per bot)

- **B01**: [9, 10, 2398, 2399]. Templates: `hello, and thank you for meeting me. i would propose N p for` x4; `i appreciate it. let us try to close quickly: N p.` x2; `fair enough, i will meet you partway at N p.` x2; `we are getting close. N p works for me.` x2
- **B02**: [37, 38, 2500, 2501]. Templates: `i can do N. let's close it quickly.` x51; `N with delivery on day N. that day suits you too, i think.` x3
- **B03**: [93, 94, 2368, 2369]; silent in [2369]. Templates: `thank you for meeting me. i can offer N p.` x4; `i appreciate your move. N p is where i can be.` x4; `let us close quickly: N p.` x4; `a step towards you: N p.` x4
- **B04**: [193, 194, 2394, 2395]. Templates: `propuesta justa para cerrar pronto y que ganemos los dos: N ` x8; `me muevo para acercarnos: N p.` x6; `yo ya me he movido. ¿qué puedes hacer tú? propongo N p.` x6; `cerremos hoy: N p.` x6
- **B05**: [197, 198, 2384, 2385]. Templates: `we can do N p. thank you for the talk.` x8; `N p works well for us.` x8; `our offer is N p.` x6; `let's meet at N p, fair for both.` x6
- **B06**: [213, 214, 2360, 2361]. Templates: `puedo llegar a N primas. dime si cerramos.` x19; `es una pieza que merece su precio: N primas. pienso que es j` x19
- **B07**: [231, 232, 2336, 2337]. Templates: `i can do N. that is a fair deal for both of us.` x24; `hello, we're interested in your card and would like to open ` x1; `we haven't heard a number from you yet, so we're stepping up` x1; `we've now moved twice without a counter from your side, so w` x1
- **B08**: [295, 296, 2412, 2413]; silent in [2413]. Templates: `hello! i can do N. thank you for your time.` x7; `thanks for the reply. N works for me.` x7; `let me move closer: N.` x5; `i'd like to close this. my offer is N.` x5
- **B09**: [303, 304, 2328, 2329]. Templates: `N p works for me and we can close now.` x10; `a real step from me: N p.` x10; `meeting you closer: N p.` x9; `i can do N p. every round costs us both, so let's close.` x8
- **B10**: [29, 30]. Templates: `opening bid. let's find a fair price.` x1; `opening ask. fair margin for both.` x1
- **B11**: [99, 100]. Templates: `N p?` x24
- **B12**: [103, 104]. Templates: `i'm offering N p for ITEM. that's a fair price given there's` x1; `that figure is the same one you've already put forward, so i` x1; `ITEM is one of madrid's most sought-after squares: a lively,` x1; `i've come down to N p as a gesture of good faith, but your o` x1
- **B13**: [2314, 2315]. Templates: `i'm a serious buyer and ready to close quickly. for ITEM, i ` x1; `thanks for the reply. i've moved up to N p as a show of good` x1; `to show i mean business, i'm raising my offer to N p. time i` x1; `i've moved a long way from where i started, and i'm now at N` x1
- **B14**: [2370, 2371]; silent in [2370]. Templates: `N for ITEM. every round costs us both: let's close it now.` x4
- **B15**: [2458, 2459]. Templates: `how about N p?` x2; `N p, then.` x2; `hi there. N p from my side.` x1; `hello! i can let it go for N p.` x1
- **B16**: [2498, 2499]. Templates: `N?` x24
- **B17**: [2586, 2587]. Templates: `propongo este precio, creo que es justo para los dos.` x24
- **SILENT**: [23, 24, 91, 92, 139, 140, 249, 250, 261, 262, 2396, 2397, 2436, 2437, 2582, 2583]. Templates: 

## Merges (check these by eye)

- co-occur (9): `hello, and thank you for meeting me. i would propose N p for` + `i appreciate it. let us try to close quickly: N p.`
- co-occur (9): `hello, and thank you for meeting me. i would propose N p for` + `fair enough, i will meet you partway at N p.`
- co-occur (9): `hello, and thank you for meeting me. i would propose N p for` + `we are getting close. N p works for me.`
- co-occur (37): `i can do N. let's close it quickly.` + `N with delivery on day N. that day suits you too, i think.`
- co-occur (93): `thank you for meeting me. i can offer N p.` + `i appreciate your move. N p is where i can be.`
- co-occur (93): `thank you for meeting me. i can offer N p.` + `let us close quickly: N p.`
- co-occur (93): `thank you for meeting me. i can offer N p.` + `a step towards you: N p.`
- co-occur (93): `thank you for meeting me. i can offer N p.` + `i think N p is fair for both of us.`
- co-occur (93): `thank you for meeting me. i can offer N p.` + `thank you for meeting me. i can do N p.`
- co-occur (103): `i'm offering N p for ITEM. that's a fair price given there's` + `that figure is the same one you've already put forward, so i`
- co-occur (104): `ITEM is one of madrid's most sought-after squares: a lively,` + `i've come down to N p as a gesture of good faith, but your o`
- co-occur (197): `we can do N p. thank you for the talk.` + `N p works well for us.`
- co-occur (197): `we can do N p. thank you for the talk.` + `our offer is N p.`
- co-occur (197): `we can do N p. thank you for the talk.` + `let's meet at N p, fair for both.`
- co-occur (197): `we can do N p. thank you for the talk.` + `N p, and we close now.`
- co-occur (197): `we can do N p. thank you for the talk.` + `we move to N p.`
- co-occur (232): `opening at N for this card — it's in excellent condition and` + `since you haven't countered yet, i'll take a step toward you`
- co-occur (232): `opening at N for this card — it's in excellent condition and` + `i've come down twice now without hearing a number from you, `
- co-occur (232): `opening at N for this card — it's in excellent condition and` + `i've made three moves and still haven't seen a number from y`
- co-occur (232): `opening at N for this card — it's in excellent condition and` + `i can do N. that is a fair deal for both of us.`
- co-occur (232): `opening at N for this card — it's in excellent condition and` + `i've moved a long way without a single counter from you, so `
- co-occur (295): `hello! i can do N. thank you for your time.` + `thanks for the reply. N works for me.`
- co-occur (295): `hello! i can do N. thank you for your time.` + `let me move closer: N.`
- co-occur (295): `hello! i can do N. thank you for your time.` + `i'd like to close this. my offer is N.`
- co-occur (295): `hello! i can do N. thank you for your time.` + `meeting you halfway at N, with thanks.`
- co-occur (295): `hello! i can do N. thank you for your time.` + `final stretch from me: N.`
- co-occur (303): `i can do N p. every round costs us both, so let's close.` + `N p works for me and we can close now.`
- co-occur (303): `i can do N p. every round costs us both, so let's close.` + `meeting you closer: N p.`
- co-occur (303): `i can do N p. every round costs us both, so let's close.` + `a real step from me: N p.`
- co-occur (2314): `i'm a serious buyer and ready to close quickly. for ITEM, i ` + `thanks for the reply. i've moved up to N p as a show of good`
- co-occur (2314): `i'm a serious buyer and ready to close quickly. for ITEM, i ` + `to show i mean business, i'm raising my offer to N p. time i`
- co-occur (2314): `i'm a serious buyer and ready to close quickly. for ITEM, i ` + `i've moved a long way from where i started, and i'm now at N`
- co-occur (2314): `i'm a serious buyer and ready to close quickly. for ITEM, i ` + `this is my last move before the deadline: N p. it's a solid `
- co-occur (2315): `ITEM is an established tavern with steady trade, a prime loc` + `thanks for your interest. the tavern's steady trade, prime l`
- co-occur (2315): `ITEM is an established tavern with steady trade, a prime loc` + `i've now moved twice, from my opening figure down to N p, wh`
- co-occur (2315): `ITEM is an established tavern with steady trade, a prime loc` + `i've moved a long way from my opening figure and i'm making `
- co-occur (2315): `ITEM is an established tavern with steady trade, a prime loc` + `i've come down a long way, and N p is my final clear offer f`
- co-occur (2394): `propuesta justa para cerrar pronto y que ganemos los dos: N ` + `me muevo para acercarnos: N p.`
- co-occur (2394): `propuesta justa para cerrar pronto y que ganemos los dos: N ` + `yo ya me he movido. ¿qué puedes hacer tú? propongo N p.`
- co-occur (2394): `propuesta justa para cerrar pronto y que ganemos los dos: N ` + `cerremos hoy: N p.`
- co-occur (2398): `hello, and thank you for meeting me. i would propose N p for` + `i appreciate it, thank you. could we close at N p, please?`
- co-occur (2398): `hello, and thank you for meeting me. i would propose N p for` + `fair enough, thank you. i will meet you partway at N p.`
- co-occur (2458): `hi there. N p from my side.` + `how about N p?`
- co-occur (2458): `hi there. N p from my side.` + `N p, then.`
- co-occur (2459): `hello! i can let it go for N p.` + `N p, then.`
- jaccard (0.83): `propuesta justa para cerrar pronto y que ganemos los dos.` + `propuesta justa para cerrar pronto y que ganemos los dos: N `
- pair ([29, 30]): `opening bid. let's find a fair price.` + `opening ask. fair margin for both.`
- pair ([103, 104]): `i'm offering N p for ITEM. that's a fair price given there's` + `ITEM is one of madrid's most sought-after squares: a lively,`
- pair ([213, 214]): `puedo llegar a N primas. dime si cerramos.` + `es una pieza que merece su precio: N primas. pienso que es j`
- pair ([2314, 2315]): `i'm a serious buyer and ready to close quickly. for ITEM, i ` + `ITEM is an established tavern with steady trade, a prime loc`
