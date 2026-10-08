# Sunday final conductor handoff (bazaar-final-conductor, Mini, from 11:56)

Plan approved by Thiago 11:52 (actions A to H: RET page with a +50 team closer on RET-01, ladder sells of spares,
desk restart with bids, Market Test quiet window 12:28 to 12:45, keep v20 open unless the 13:30 close rule holds,
cash order from 13:30, last-hour listings, flag test). Board 11:14: us 30.47.

## Live state (updated by the conductor)

- 12:01 desk restarted through its keeper (cmd in tools/factory_sunday.json, backup logs/conductor/factory_sunday.json.bak-1206):
  `--no-team-venues --page SAL-11:184:150 --margin-min 10 --bid-min-value 10 --protect LAV,LAT,SAL,RET,MAL
  --duel-guard-ticks 2 --min-cash 40 --cap-hour 250 --cap-day 600`. Margin 10 and bid floor 10 keep RET-01 (value 9)
  out of every desk buy. The desk will NOT bid RET-01 by itself at 9/10 (bids rank by offline value, about 9): when
  me.json shows RET 9/10, restart the desk through the keeper cmd with `--page RET-01:16` added (outside 12:28-12:45, before 13:50).
- Dealer steps touching RET disabled in factory_sunday.json (all were already done_steps).
- Queue A (tmux factory:conductor_a, log logs/conductor/queue_a.log): Picaros RET-10, Abuela RET-06/07/08 cap 22,
  Abuela RET-02 cap 8. Queue B (factory:conductor_b): Picaros RET-09 retry after queue A. All with --reserve 40,
  no launch inside 12:28 to 12:45.
- Flag lever (H): Picaros switched RET-09 for RET-06 in thread 3041; flag on message 15943 moved neg_points 56.5 -> 66.5.
  agent/chato.py patched (backup logs/conductor/chato.py.bak-1210): on a switched offer while buying it flags the
  message (only if the words name our card and not the given one) and keeps countering, never accepts.
- Helper: `python3 logs/conductor/tc.py score|thread <id>|flag <msg> <reason>|close <id>|value <REF>` (key from .env, never printed).
- Telegram: scratchpad notify.sh (sources ~/.config/telegram-notify.env).

## Update 13:11

- Flags: only the first 3 correct flags scored (56.5 -> 86.5 neg_points); 7 more were accepted but scored 0. Harvest stopped.
  logs/conductor/flag_sweep.py flags after the fact (flagged ids in logs/conductor/flagged.json).
- RET 9/10: bought RET-10 53, RET-09 ~55 (Picaros), RET-08 22, RET-06 21, RET-02 8, RET-01 8 (Abuela). RET-07 is the CLOSER
  (live value 82.1): desk cmd now has `--page RET-07:32:14 --max-price 31` (full +50 at 32 or less incl. fee).
- Sold: LAV-10 spare to Pilar 50, LAT-07 spare to Chato 13. Chato would not pay 20 for MAL-06/07.
- SAL-11 page bid live 150 -> 184 on El Rastro (+50 if filled).
- v20 stays OPEN (RULES line 81 risk: closing may drop the 8.15 bench credit). No close.
- Clearing House joined 13:10 (venue v20), execute in tmux factory:clearing, scratchpad cc.sh wrapper (server URL and invite
  kept in a private cfg, never printed). Book keeps all RET page cards and LAV-03/05/09/10 out. check_buy re-reads live value.
- Do not `pkill -f "agent/market_desk.py run"` from a shell whose own command line contains that string (it kills the shell).
- The desk keeper treats ANY process whose command line contains 'agent/market_desk.py run' as a running desk (even a shell wait loop): never put that string in a waiting shell command, or the desk stays down.

## Result

- Final (15:01): score 34.19, rank 4 (11:14 board: 30.47, rank 5).
- Components: negotiating 26.04 (neg_points 56.5 -> 136.5), market 8.15 (unchanged, v20 0 trades), ladder_points 0.165 -> 0.371,
  duel_points 27.94 -> 40.19 (Grand Final). Cash 355 -> 17.
- RET page: complete 10/10. Closer RET-07 bought from a team on El Rastro at about 30 (live value 82.1) = +50.
- Deals: Picaros RET-10 53, RET-09 about 55; Abuela RET-08 22, RET-02 8, RET-06 21, RET-01 8; Pilar bought spare LAV-10 at 50;
  Chato bought spare LAT-07 13 and MAL-06 18; team: RET-07 about 30 (El Rastro), SAL-11 about 222 (El Rastro page bid, filled
  about 14:54; not visible in neg_points at 15:01).
- Flags: 3 correct Picaros bait-and-switch flags scored +10 each; 7 more correct flags scored 0 (cap of 3).
- Not done: Clearing House (joined 13:10, stopped 13:44 at Hector's call, 0 trades); v20 kept open (no close); no packs.
