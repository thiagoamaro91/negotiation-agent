# Helper audit: abuela / chato / rastro_seller + bazaar-watch (timing, CLI flags, behaviour locations)

Source: Team 3 lunch review, Sat 3 Oct 2026, frozen copy of the Mini at commit fa91372, tick 630.

Relayed by the main session: the helper's handback reached the main session instead of the dealer-trade-analyst.
Paths relative to snap/bazaar ; watch/ = snap/bazaar-watch

HEADLINE: no bot or watch script reads tick_seconds. Tick-to-minutes conversions exist only in comments. The only reader is duel.py:617-625 (lock = now + 3 x tick_seconds), so duel.lock scales correctly (45 s at 15 s ticks).

## (A) Timing constructs (file:line | construct | value | breaks at 15 s?)
- abuela.py:56,:139 | MAX_ROUNDS loop, counts every iteration incl. waits | 40 (~20 min Sat, ~10 Sun) | no: tick-count, and the dealer answers once/tick
- abuela.py:147,151,181,196,203 | b.wait_tick() | 1 tick | no
- abuela.py:210-211 | settle() 4 x wait_tick | 4 ticks | no
- abuela.py:48,:269 | duel lock vs time.time(), checked at START only | epoch s | no (expiry scales); start-only check: see D
- chato.py:65 | MAX_ROUNDS=12, comment "60 s ticks: 12 rounds is 12 minutes" | 6 min Sat / 3 min Sun | no for logic; comment already wrong Saturday
- chato.py:221,:398,:473 | --max-rounds loop, counts waits at :229,:233,:258,:278 | 12 | no: it is a TICK budget, not a message budget
- chato.py:229,233,258,278,285 wait_tick; :292-293 settle 4 ticks; :97,:462 lock start gate | no
- rastro_seller.py:67 (+:838, :815 haggle window, --step-ticks) | STEP_TICKS step-down cadence | 20 ticks = 10 min Sat, 5 min Sun | YES: steps down twice as fast in wall-clock time. Fix: --step-ticks 40
- rastro_seller.py:68 | STEP_P 2 | price | no
- rastro_seller.py:69,:852 | RENEW_AHEAD 3 ticks | 45 s Sun | no (the loop wakes every tick)
- rastro_seller.py:70,:820 | LIST_TTL 30 ticks (server cap 30) | 7.5 min Sun | no/maybe: 2x the cancel+relist churn
- rastro_seller.py:75,:590,:599 | IDLE_CLOSE_TICKS 20 | 5 min Sun | YES: human-typed team threads get closed after 5 min; not a flag
- rastro_seller.py:76,:490 | PENDING_TICKS 4 | 60 s | no
- rastro_seller.py:420 | refresh venues every 60 processed ticks | no
- rastro_seller.py:414-415 | budget/max_open read from clock.limits | no (adaptive)
- rastro_seller.py:897-903,:909,:943-944 | --until HH:MM Madrid, today only, past time = SystemExit | no
- rastro_seller.py:916 | sleep(10) on clock error | maybe: skips ~1 tick
- rastro_seller.py:918-925 | doors closed/paused: sleep(30) poll | yes (mild): loses up to 2 ticks at the 09:00 open and after any pause
- rastro_seller.py:935-936 | sleep(30) after 5+ consecutive errors | maybe
- rastro_seller.py:942-945 | wait=(next_tick_in or 5)+1, clamped [1,35] | no (adaptive)
- rastro_seller.py:87,:726 | lock re-checked on every accept | no
- bazaar_sdk.py:83-94 | wait_on_tick resend sleep min(65,next_tick_in)+0.2 | no
- bazaar_sdk.py:113 | HTTP timeout 15.0 | maybe: one hung call = one whole Sunday tick
- bazaar_sdk.py:302-312 | wait_tick sleeps next_tick_in+0.15 then polls 60x0.25 s | no (see D for :306, :309)
- watch/pilar_gate.sh:7 | wall-clock gate hm>=1335 + lock stale>=120 s, no date | maybe
- watch/mal10_ladder.py:34 | step-down = listing expiry, expires_in_ticks=40 (capped 30) | YES: ladder runs twice as fast Sunday
- watch/mal10_ladder.py:26,:30,:37 | sleep(30) poll | yes (mild)
- watch/lat10_sell.py:43 hardcoded stop "11:44"; watch/sal01_buy.py:35,:42 "11:45"/"11:20" | yes if rerun Sunday

## (B) CLI flags
abuela.py (:262-268): cmd plan|run ; --only (comma refs and/or sell:<asset_id>; a bare ref ALSO selects that card's spare for sale, :255) ; --max-deals 6 ; --reserve 280 (buy skipped if cash-reserve<5, :292; limit=min(value,cash-reserve), :159) ; --cap None (min(private,cap); 0 = no cap; buys only). NOT flags: --until/--anchor/--step/--max-bid/--max-rounds/--floor/--sell-anchor/--sell-step/--allow-single/--resume/--dealer. Constants: ANCHOR_FRAC 0.40 :52, SELL_ANCHOR_MULT 2.2 :53, STEP 1 :54, WELCOME_MAX_FRAC 0.75 :55, MAX_ROUNDS 40 :56; sell floor = spare value+2 :246. run exits 0 if duel.lock is fresh.
chato.py (:392-429): cmd plan|run ; --only (bare refs = buys only :333,:359; sell:<id> = sells; pilar rejects bare refs :424-428) ; --max-deals 3 ; --resume None (thread id, plan[0] only, :532) ; --max-rounds 12 (ticks incl. waits) ; --reserve 280 (skip buy if cash-reserve<max(5,anchor), :529) ; --cap None (default full private value; 0 = no cap) ; --anchor None (default int(0.40 x his ask)) ; --step 1 ; --max-bid None (his FINAL is still taken up to the reservation; a non-final above max-bid is never taken) ; --dealer chato|pilar ; --allow-single False (needs explicit sell:<id>) ; --sell-anchor None (chato round(1.6 x bid), pilar max(3 x bid, floor+20); never below the floor) ; --sell-step None (chato 2, pilar 4) ; --floor None (replaces private+2; if below ceil(private), run exits 2). No --until.
rastro_seller.py (:1363-1372): cmd watch|run|selftest ; --config agent/rastro_floors.json ; --until None (HH:MM Madrid, required for run, today only) ; --once ; --take-bids False ; --step-ticks 20 ; --step 2 ; --n / --seed (selftest). floor/start_ask/enabled/allow_last_copy come from the JSON; the floor is auto-raised to ceil(private)+1 (:454-458). Client wait_on_tick=False, retries=2. Config enabled: MAL-08 #501 (already sold), LAV-01 #41, LAV-03 #40, LAV-05 #499, MAL-02 #579, all 9/8. Disabled: LAV-08 #500, MAL-06 #43.

## (C) Behaviours
1. chato.py negotiate() :189-288. The round loop (:221) also counts wait-only iterations, so --max-rounds 16 = 16 ticks. Bids 60..84 (:263,:267); nxt = min(nxt, int(MAX_BID)) (:270) pins at 84. crossed = her <= nxt (:272) compares his 90 to 84, not to the 93 reservation, so a non-final 90 inside the cap is never taken. nxt == ours (:277) waits SILENTLY (no message, so the dealer has no reason to name a final); when the budget runs out, close_thread + "max_rounds" (:286-288). 7 bids in rounds 0-6, then 9 idle ticks.
2. chato.py :260-276 sells: first ask sell_anchor (:265, :170-175) = max(round(1.6 x 13)=21, floor), then ours - SELL_STEP (:267) gives 19, 17, 15. Next 13 is clamped by max(nxt, reservation) (:268). crossed = her >= nxt (:272) true for his 14, so accept with why="crossed" (:273-276). Reservation = ceil(spare value+2) (:344, :242).
3. abuela.py :183-194, :170-175. Anchor int(her * ANCHOR_FRAC) (:185), then ours + STEP, STEP=1 (:187, :54); steps only after she answers. Final: if good(her): accept (:171-175). Welcome path :166-169.
4. CASH_RESERVE = 280 at abuela.py:41 and chato.py:56. Block: abuela :292 cash - reserve < 5, chato :529 < max(5, anchor), both log skip_cash. At cash 170 every buy is skipped. Limit is also min(value, cash-reserve) at abuela :159 / chato :241.
5. abuela.py build_plan() :221-256 skips held cards (:235) before the --only filter (:253-255), so --only cannot force a second-copy buy. Same in chato :331.
6. chato.py build_plan() :335-337 "value": min(v, cap) if cap else v. Finals are taken up to full private value; --cap 0 = no cap. Abuela identical at :239.

## (D) Other Sunday risks
- bazaar_sdk.py:306 float(c.get("next_tick_in",1.0)) has no try/except: a null next_tick_in during a pause or doors-closed crashes abuela/chato with TypeError. Maybe.
- bazaar_sdk.py:309 wait_tick returns at once when paused, so abuela/chato burn rounds without ticks passing; chato can hit max_rounds in seconds and close the thread. Maybe.
- abuela.py:269 / chato.py:462 check duel.lock only at start; a duel wave mid-negotiation competes for the 1 accept/tick. rastro_seller re-checks per accept (:726).
- abuela.py:274 / chato.py:467 use SDK defaults wait_on_tick=True, retries=3: a refused accept/say is resent next tick against a possibly replaced offer; the 4th refusal raises uncaught out of negotiate() (crash, thread left open).
- abuela/chato never read clock "doors": started before 09:00 they log open_refused for every plan target.
- rastro_seller does 5+ GETs per pass: fine at 15 s; could overrun a tick at 5 s.
- rastro_floors.json _note says LAV-01 9/6, LAV-03 7/6, LAV-05 8/6, MAL-02 8/6; the actual entries are all 9/8.
- watch/pilar_ret06.sh:5: pgrep -f matches any command line containing that text, so the wait loop can spin forever.
