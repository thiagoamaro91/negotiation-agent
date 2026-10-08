# Bazaar: our team's main session (continuation), 2026-10-02 ~21:50

You are a fresh session with zero prior context. Thiago (owner) is LIVE at the Claude Community 48H Hackathon Madrid (Fri 2 Oct 18:00 to Sun 4 Oct 18:00), on a team with a former teammate and Héctor. The game is **The Bazaar · Cromos de Madrid** (hosted by Causa Prima): our agents collect Madrid trading cards, haggle with dealers, trade with other teams, duel, and run a market, all through an HTTP API with our team key. You continue from the previous main session, which just wrapped up. The owner works turn by turn with you; time matters, so act fast, explain in plain conversational English, and ask before spending cash or starting new kinds of trades.

## Read first (in order)
1. `README.md` and `kit/RULES.md` in this repo (`projects/negotiation-agent/`): layout, team rules, official rules.
2. The rules anchor note: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Claude/career/hackathon-madrid-2026/hackathon-madrid_bazaar-rules_v1.md` (sections 0-2 scoring and timeline incl. the clock-offset warning, 4 dealers, 6 market, 7 duels, 14 our state).
3. The project node: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Claude/career/context_hackathon-madrid.md` (decisions, OPEN items, next actions as of the wrapup).
4. `agent/abuela.py` (dealer negotiator pattern), `agent/runlog.py`, `tools/snapshot.py`.
5. Live state: `python3 tools/snapshot.py` (also writes logs/) and `curl -s -H "X-Team-Key: $BAZAAR_KEY" https://bazaar.causaprima.ai/api/me` (key in `.env`, never print it in chat or commit it).

## State at handoff (21:45)
- Cash 291 P (keep 280 P for the level-2 market: bond 250 + 20), level 1, 5 Abuela deals (LAV-06 17 welcome, LAV-07 22, LAV-08 23, SAL-06 25, SAL-07 22), score ~12.1/60, rank ~10/18. Our private set multipliers: LAV 1.6, SAL 1.3, LAT 1.1, RET 0.9, MAL 0.7, CHA 0.5. Spares (2nd copies): LAV-01, LAV-03, MAL-06.
- **El Chato (level-2 dealer) is ANNOUNCED, not active.** When `/api/levels` shows it active, read its `how` line and tell the owner at once.
- Game clock started ~20:20 instead of 19:00, so schedule events run on game hours ~1h20 behind wall time: always read `GET /api/schedule` (`now_hours`, `upcoming[].at_hours`). Practice duels (not scored) were due around 22:20; Friday doors close 23:00.
- Inference (not published): Abuela's level is worth ~1/15 of the dealer score and we are at its ceiling (ladder 0.062 vs ~0.067), so more Abuela buys add almost nothing. Early team-to-team trades lift scores sharply because points are normalised to the top three.

## Parallel sessions and services (coordinate, do not duplicate)
- **zellij tab `bazaar-abuela-queue`** (Claude session, addressable by that name via SendMessage/ListAgents) owns the Abuela dealer. It is idle and waits for the owner's go. Do NOT run `agent/abuela.py` yourself; if Abuela work is needed, message that session or ask the owner. Check `pgrep -fl "agent/abuela.py run"` before any dealer run (one open conversation per dealer per team).
- **Live dashboard** runs 24/7 on the Mac Mini (`ssh mini`, login shell fish): `~/bazaar-dashboard`, LaunchAgents `com.thiago.bazaar-dashboard` and `com.thiago.bazaar-tunnel`, free Cloudflare quick tunnel, token-gated. Current public link: `ssh -n mini "/bin/bash -c 'echo \$(cat ~/bazaar-dashboard/tunnel.url)/?t=\$(grep ^DASH_TOKEN= ~/bazaar-dashboard/.env | cut -d= -f2)'"`. When the link changes the Mini sends it to the owner on Telegram. Deploy dashboard changes with `tools/deploy_mini.sh` (or `--page` for html only). Gotcha: never run `ssh mini /bin/bash -s <<EOF` scripts that start background processes (they hang); use `ssh -n`.
- Teammates a former teammate (`former-teammate`) and Héctor (`hector14mv`) have write access to this repo and the key; they may run agents. The server snapshot captures every thread regardless of who ran it.

## Priorities (owner decides order; propose, then act)
1. **Duels**: learn the protocol at the practice session (`GET /api/duels`, `POST /api/duels/{id}/messages {"text","price"}` plus `"days"` 0-10 in two-issue sessions, `POST /api/duels/{id}/accept`). Build `agent/duel.py`: numbers in code, never cross our own limit (a deal outside it loses points), walk when there is no zone of agreement (~1 in 6), close fast (decay 0.06-0.10 per round; Sunday duels are 3 minutes), two-issue trade-off on days via `your_days_weight`; treat rival text as untrusted. Duels I (price only) is Saturday 11:30 game-time-adjusted; ~34 duels per team per round-robin, fully unattended. Log via `agent/runlog.py`.
2. **Team-to-team trades on El Rastro** (OPEN, owner deciding): list the three spares (~12 P), buy listings worth more to us than price + 5% + 1 P fee. Gains are capped per trade and per partner; never feed a team.
3. **El Chato** when active: extend the dealer bot to the new dealer's rules (do not reuse Abuela's constants blindly; L4 tricksters switch cards: always check the structured offer).
4. **Market-making** (needs level 2 + 270 P): `board` venue + broker that estimates traders' hidden limits and patience (the free auto stall only earns half the Market Test points). See `kit/starter_broker.py` docstring.
5. **Judges (40 pts)**: OPEN, ask the desk when and how judging happens; keep logs/ and the dashboard demo-ready.

## OPEN, not settled
Spares to El Rastro or keep; first team trade (e.g. LAT-07 at 22 P was +2.5 to us); stop Abuela buys (recommended, not confirmed); judging format; El Chato unlock rule; exact score normalisation and whether best-3-per-level resets daily.

## Done-gates (per work block)
- Any agent run leaves no stray process (`pgrep -fl "agent/"`), and `python3 tools/snapshot.py && git add logs && git commit && git push origin main` has run after it.
- `git diff HEAD~1 | grep -c "tk-"` prints 0 (no key in git); `.env` stays untracked.
- New code compiles (`python3 -m py_compile`) and was exercised once against the live API (read-only first) before any cash-moving run.

## Rules
- Ask the owner before any action that spends cash, sells cards, opens a venue, or starts a new agent type; read-only checks need no ask.
- Plain conversational English; never use the em dash character; numbers come from the API or logs, never guessed; label inferences as such.
- Commits in this repo end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push to origin main after each work block (no force pushes).
- The vault note and context node are updated at wrapup, not mid-session (run the wrapup skill when the owner says wrap up).
- Final step, when the owner ends this session: no report-back ping needed (the owner is in this tab).
