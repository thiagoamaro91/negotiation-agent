# Bazaar final conductor (Sun 2026-10-04, written 11:55 local)

You are a fresh session with zero prior context. You are the ONE conductor for our team (Thiago, Hector, a former teammate) for the last three hours of the Madrid hackathon game "The Bazaar - Cromos de Madrid". The game closes at 15:00 local today; scores freeze about 14:59:40. Thiago approved the plan below at 11:52. Your job: execute it on this Mac Mini, in the live repo `~/bazaar`, and get the score as high as possible. Board at 11:14: t12 34.87, t10 33.76, t18 32.36, t05 31.68, us 30.47 (rank 5).

## Authority and limits

- **No human gates.** Thiago's approval of this plan authorises every in-game move inside the value rules: dealer buys and sells, desk restart, team trades, packs under the pack rule, joining Hector's Clearing House with our book, closing the shop under the shop rule. Do not ask Thiago anything; he is not watching. Decide from the data on this machine.
- **Stays with humans, never you:** messages to other teams or people, announcement wording, team keys, new public services or tunnels, the /submit form.
- **Hard rules:** never print `.env`, any `tk-` or `bk_` key, dashboard tokens, bot tokens or tunnel URLs. Never trade on the wrong side of `/api/me/value` (buy above our value, sell below it). Never restart or signal `agent/broker.py` (pid 40142) or `agent/duel.py` (pid 70532). Never run `tools/factory.py up --yes`. No stall pact with other teams, no feeding another team on purpose. Never use the em dash character in any output or file.
- **Token rules (single shared account, it ran out yesterday):** you are the only Opus session. No Opus subagents, no parallel lanes. Haiku subagents only for bulk log extraction. Queue work as shell scripts in tmux first, then poll sparsely (one check every few minutes, not every tick). The bots use no model, so queued scripts keep running if tokens run out.

## Read first (in this order, quickly)

1. `python3 tools/bus.py --session bazaar-final-conductor read` (team bus on GitHub issue 25). Hector's session `hector-clearing` leads the shop strategy; messages 5978615063 and 5978659628 are our sync to him. Adopt his answers and run times if he replied. Every bus post of yours opens with `FROM: bazaar-final-conductor | TO: <target>`.
2. `logs/public/clock.json` and `logs/public/schedule.json`. Today: 15 s ticks, 240 ticks per game hour, 1 game hour = 1 wall hour. Anchor: game hour 15.475 at 11:06:09. Last Market Test at game hour 17.0 (about 12:37 to 12:41). Dealers close and Grand Final duels start at 18.367 (about 14:00). Freeze 19.367. Re-read after any pause.
3. `logs/state/me.json` (refreshed every 10 min; refresh on demand with `python3 tools/snapshot.py --me-only --score`).
4. `--help` of `agent/abuela.py`, `agent/chato.py`, `agent/market_desk.py`; `tools/factory_sunday.json` and `python3 tools/factory.py plan` for how the bots are invoked and kept alive (`tools/factory.py keep market_desk` is a keeper: read how it works before restarting the desk).
5. `kit/RULES.md` sections Scoring and venues; `docs/plans/ladder-sunday.md`.

## What the data says (verified from our logs this morning)

1. Team trades score our private value minus price (fee subtracted), page bonus INCLUDED, capped at 50 per trade. Today: SAL-10 from t13 at 108 (value 177.1) plus MAL-07 from t15 at 9 = neg_points 56.5 = 50 + 6.5. One capped trade moved our score about +1.0.
2. Dealer deals feed only the ladder: best three deals per dealer per day, a better one replaces the worst. Round 3 worth per counted deal: Picaros about 0.49, Pilar 0.29, Chato 0.20, Abuela 0.14 to 0.4. Slots used today: Abuela 1/3, Chato 0/3, Pilar 2/3, Picaros 2/3, Banco 0/3.
3. Banco: never. Wrong side of our value on everything.
4. Cash at 15:00 scores nothing. Cards in the album score nothing by themselves; only the deal counts.
5. The shop (v20, La Celestina, bond 250) scores only when two OTHER teams trade on it. We cannot trade on our own venue.

## State at 11:45

Cash 355. Album: LAV, LAT, SAL pages complete; MAL 4/10; RET 3/10 (RET-03 asset 1189, RET-04 asset 1206, RET-05 asset 1187); CHA 0/10. Values to us: RET common 9, RET uncommon 22.5, RET rare 63, RET page bonus about 59.6; MAL common 7, MAL uncommon 17.5; SAL-11 234; LAT-11 198.
Spares (second copies): LAV-10 rare (assets 490, 1194; spare worth 28), LAT-07 (512, 1192; 6.9), LAV-03 (35, 1191; 4), LAV-05 (38, 1188; 4). Low-value singles: MAL-06 (asset 1193), MAL-07 (898), MAL-04, MAL-02.
Running (do not disturb): broker `--policy stall`, duel bot, `agent/market_desk.py run --no-team-venues --no-bids --page SAL-10:110:80 ... --until 15:05` (pid 41485; SAL-10 is already bought), announcer, matchmaker (`logs/matchmaker/latest.json`), feed recorder (`logs/feed/feed.jsonl`), factory keepers.

## Actions, in order

**A. RET page with a +50 closer (about 220 P, done by 13:30).** Run each bot's `plan` once, then `run`, one dealer bot at a time.
- Abuela: `agent/abuela.py run --only RET-02 --cap 8`, then `--only RET-06,RET-07,RET-08 --cap 22`. Always pass `--only`.
- Picaros: `agent/chato.py run --dealer picaros --only RET-09 --cap 61 --step 1`, then RET-10 the same way. KEEP both cards this time.
- A card no dealer sells under value: take a team ask at or under plain value (seen today: t02 RET-07 at 14 on v29, t07 RET-08 at 25 on El Rastro, t13 RET-02 at 8 on v10).
- **Closer rule:** RET-01 is excluded from EVERY buyer (desk, Abuela `--only`, clearing book) until `me.json` shows RET at 9 of 10 and the live value of RET-01 reads about 68. Then one targeted bid: `agent/market_desk.py ... --page RET-01:16`. Team 2 relists RET-01 at 8 on El Rastro every 40 to 60 ticks (assets 546, 1161). If another RET card ends up last, that one is the closer and must come from a team, cheap.

**B. Ladder sells (fill empty slots, right side only).** Spare LAV-10 to Pilar at 50 or more (`agent/chato.py run --dealer pilar --only sell:1194`), spare LAT-07 to Chato at 11 or more (`--dealer chato --only sell:1192`), spare LAV-03 and LAV-05 to Abuela or Picaros above 4. Check the floor flags so nothing sells under value.

**C. Desk restart, between 11:55 and 12:25 or after 12:45.** Drop `--no-bids` and the finished SAL-10 page target; `--cap-hour 250 --cap-day 600 --min-cash 40`; RET-01 protected (verify what `--protect` covers). Bids worth having: SAL-11 at 184 or less (holders t02, t13, t17, t08; t04 asked 220 on v15), RET uncommons at 22 or less. **Rivals rule:** t12, t10, t18, t05 get a trade only when our side scores the full +50.

**D. Market Test 12:37.** From 12:30 to 12:45 start nothing and restart nothing. Afterwards read `bench_efficiency` and `market`.

**E. Shop (Hector's lane).** His Clearing House (PR #96, branch `feat/clearing-house`, files `tools/clearing.py` and `tools/clearing_client.py`) matches teams' private sell and want books at the midpoint. If he posts a server URL on the bus, join with our book: sells at or above our value, wants at or under it, RET-01 stripped. Read the client with `git show origin/feat/clearing-house:tools/clearing_client.py`; never switch branches in the live tree. **v20 stays open by default.** Close it only if all three hold at 13:30: the schedule shows no market session left, v20 has zero trades in `me.json` and the feed, and Hector's session reports no team committed. Then a proper close (never "replace"); 250 P returns 20 ticks later and goes to action C buys.

**F. Cash order from 13:30.** (1) Team trades with gain; from 14:00 desk `--min-cash 0`, any team ask under live value, best gain first. (2) Dealer buys under value that improve a top-three slot (LAT-11 at Picaros at 150 or less). (3) Packs, last resort, before 14:00: only at or under the pack's live value to us from `/api/me/value`, Chato's silver first; a pack above value is a wrong-side deal and idle cash beats it.

**G. Last hour 14:00 to 14:59.** Dealers are closed, every team dumps cash. List all spares and MAL singles on El Rastro at our value plus 50 (MAL-06 and MAL-07 to t06 at 28 are also fine earlier). Pause desk accepts while the Grand Final duel wave is live (one accept per tick is shared with the duel bot; `results/duel.lock` was absent at 11:45, check the real lock path once).

**H. Optional flag test** after the Picaros buys: one clearly bad-faith dealer line, `neg_points` before and after, repeat only if it moves.

## Done-gates

- Before and after every deal: `neg_points`, `ladder_points`, `negotiating`. A line whose deal lowers the score stops.
- At 15:01: final score, rank, cash, RET page state, list of deals made. Append them under a `## Result` heading in a copy of this file at `docs/plans/sunday-final-handoff.md` (create it at start; untracked is fine, do not commit on the live tree).

## Rules for reporting

- Telegram to Thiago at 12:45, 13:30, 14:05, 14:30, 14:55 and 15:01: three lines, score, rank, cash, what moved. Use the notify path that `tools/factory.py status --notify` already uses (grep `tools/` for it; fallback `~/bin` or `~/scripts` notify.py). Never print the bot token.
- Bus post at the same checkpoints, so Hector's Claude can take over if this account runs out of tokens.
- Final step: one Telegram line with the result.
