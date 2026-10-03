# Judges' evidence checklist v1 (Team 3)

Companion to [`judges-story_draft_v1.md`](judges-story_draft_v1.md). What to have open on screen while Thiago talks, in script order, and who drives it. Internal.

## Roles (proposal, confirm in the team chat)

- **Thiago**: speaks. Holds the clicker if there are slides. Does not drive a terminal on stage.
- **Hector**: drives the laptop. Opens each screen on cue, in the order below.
- **Jay**: timer (signals at 1:00, 2:00, 2:40) and the backup: the screenshots folder, ready to show if the live screens fail.

## Safety tags

- **SAFE**: shows nothing private. Fine to show live.
- **MASK**: has a private panel or line. Crop, scroll past it, or use a screenshot checked beforehand.
- **NEVER**: private values, keys or personal data. Not on any screen judges or other teams can see.

## Screens, in script order

| Cue (script time) | Screen | How to open | Tag | Notes |
|---|---|---|---|---|
| 0:00 Hook | Public leaderboard | `https://bazaar.causaprima.ai` (big-screen board) | SAFE | Only if the "6 of 8" line survives the refresh. Never show the threat map itself |
| 1:05 "we see everything" | Feed recorder proof | `logs/feed-vm/README.md` (3,770 events, every tick 0 to 159) | SAFE | Public data only |
| 1:05 "always on" | Bots running on the Mac Mini | Screenshot of the tmux windows (`seller`, `desk`) and the dashboard LaunchAgent, taken beforehand | MASK | Live tmux can print caps and our values in log lines. Use a checked screenshot, never a live attach on stage. Confirm where the duel bot runs before saying "all of them" |
| 1:15 "29 to 22" | Abuela LAT-08 conversation | `logs/threads/thread-00362.json`, or the dashboard's conversation chart for that thread | SAFE (thread file) / MASK (dashboard) | The thread file has no value fields (checked). The dashboard page also shows the El Rastro board and album with our private values: zoom on the chart only |
| 1:30 "84 vs 90" | Chato LAV-09 conversation | `logs/threads/thread-00335.json`, or the dashboard chart | SAFE (thread file) / MASK (dashboard) | Do **not** show `logs/chato/2026-10-03.jsonl` line 1: the `run_start` line carries our cap |
| 1:45 "8 of 8, +11 % in simulation" | Duel lab result | `docs/duel-lab/improvements.md`, the held-out paragraph at lines 18 to 19 | SAFE | Say "in simulation" on screen too. Swap for the live Duels I result if it is good |
| 1:45 (optional) | Friday duel replay | `docs/analysis-friday/duels.md` | MASK | Shows practice duel limits (for example 164 vs 106). Low risk, but crop the limit column |
| 2:05 "107 of 108" | Mutation catch rates | `docs/plans/HANDOFF.md` PR table, lines 17 to 22 only | MASK | Crop to the table. Line 48 of the same file states a value "at our values" |
| 2:20 "18 minutes" | PR #11 and #12 merged | GitHub, repo pull requests, closed tab; or `gh pr view 11` / `gh pr view 12` | MASK | PR #12's title names our cash floor. Show the merge times, not the title, or say it without the screen |
| Q&A "how do you stop a runaway bot?" | Code that caps our limit | `agent/abuela.py` around line 159, `agent/chato.py` around line 179, `agent/lease.py` | SAFE | Code holds no values; they come from the API at run time |
| Q&A "show the tests" | Test run | `git pull` on the demo laptop first, then `python3 -m unittest discover tests` | SAFE | On `origin/main` (8daf50a) it prints 273 tests OK. This laptop's checkout is behind and prints 266 with 2 failures: pull first or skip |

## Never on screen

- `logs/state/me.json` (our set multipliers and card values).
- `docs/findings.md` ("Where we stand" names our best and worst sets, and what two cards are worth to us).
- The dashboard's El Rastro board and album panels (our private values), and the brain page's value table (`tools/brain.html`).
- Any `run_start` log line, `results/*.out`, or the runbook (they hold caps, reserves and max bids).
- `.env`, any terminal where the key could appear, and the brain or dashboard token in a URL bar.
- The vault competitor map (personal data on 47 people).

## Before going on (10 minutes out)

1. Re-score the threat map against `GET /api/leaderboard`. Keep "6 of today's top 8" only if it is still 5 or more; say the new number.
2. Check whether Duels I scored, and with what result. Swap beat 4's last line if the live number is good.
3. `git pull` on the demo laptop, so tests and docs match `origin/main`.
4. Open the screens above in tabs, in order, with the MASK ones already cropped or zoomed.
5. Take the backup screenshots and drop them in one folder on Jay's machine.
6. Read the "Do not say, do not show" list in the story draft once more.
