# Judges' evidence v3 (Team 3)

Companion to [`judges-story_v3.md`](judges-story_v3.md). What is on screen while Thiago talks, in script order, who drives it, and what needs Thiago's yes. Internal. Replaces [`judges-evidence_v2.md`](judges-evidence_v2.md); its safety tags and "never on screen" list carry over and grow.

## Roles (as v2; confirm in the team chat)

- **Thiago** speaks. Does not drive a terminal on stage.
- **Hector** drives the laptop: opens each screen on its cue, in the order below, from tabs prepared at 14:50.
- **Jay** keeps time (signals at 1:00, 2:00, 2:40) and holds the backup: the screenshots folder, ready if a live screen fails.

## Safety tags

- **SAFE**: nothing private. Fine live.
- **MASK**: one panel, column or line is private (or names a team). Crop, zoom, or use the screenshot checked at 14:50.
- **NEVER**: private values, caps, cash floors, keys, tokens, personal data. Not on any screen judges or other teams can see.

## Needs Thiago's yes (ask at 07:00, not at 14:50)

| What | Command | Why it needs a yes | If no |
|---|---|---|---|
| **Public swarm link** (Tailscale Funnel) | on the Mini: `python3 tools/swarm.py serve --public --port 8778`, then `tailscale funnel --bg 8778` | It puts a page on the public internet. The public view shows only what already sits on a public board (`tools/swarm.py` `public_view()`: no why, no highlight, no value), but a funnel is still an outward-facing step. **Never funnel 8777** (the private view, which carries the why of each decision and holdings-based highlights) | Show the public view on the Mini's own screen (`http://127.0.0.1:8778`), or the 14:50 screenshot |
| **Dashboard tunnel** (Mini dashboard, La Celestina panel) | the tunnel the Mini already uses for the dashboard (`~/bazaar-dashboard`, see `docs/plans/sunday-night-handoff.md` on PR #66) | The same page carries the El Rastro board and the album with our private values; only the La Celestina panel is SAFE | Skip the dashboard: the public site's venue list (row 5 below) says the same thing with no risk |
| La Celestina public page and agent API, if we want them live | `python3 tools/celestina.py serve --port 8795 --public-url https://<host>` behind a tunnel | Public page; its private side (127.0.0.1:8796) must never be tunnelled | Do not mention the API on stage beyond the Q&A wording in the story |

Nothing in this list sends a message, posts an offer or spends. None of them needs the team key.

## Screens, in script order

Version B is the default. Version A changes row 5 only.

| # | Cue (script time) | Screen | How to open | Tag | Driver | Notes |
|---|---|---|---|---|---|---|
| 1 | 0:00 Hook | Title, or the public game site | `https://bazaar.causaprima.ai` (the organisers' own board) | SAFE | Hector | Do not point at our rank. A still screen is fine: the hook is about their problem, not ours |
| 2 | 0:44 "El Chato wanted 90 ... stopped at 84" | El Chato LAV-09 conversation | `logs/threads/thread-00335.json` in a viewer (36 keys, none a value, cap, limit, floor or multiplier: checked Sunday 02:40) | SAFE | Hector | Never `logs/chato/2026-10-03.jsonl`: its `run_start` line carries our cap. Never the dashboard chart page (album panel) |
| 3 | 1:08 "every public event ... every team's cash ... twelve readings out of twelve" | The 14:50 numbers | Terminal: `python3 tools/pitch_numbers.py`, lines 3 and 4 only | MASK | Hector | Crop to lines 3 and 4. The VERSION line can print team ids (version A), and line 2 can be read as "who posted": keep both off screen. Do not show `tools/ledger.py` with every team's cash on stage |
| 4 | 1:20 "Bayes over the 720 ways ... beats chance, but not ..." | Inference check, reliability line | `python3 tools/value_inference.py check`, the line starting `3) reliability` and the `baselines over 539 choices` line | MASK | Hector | **Section 1 of that output is NEVER**: it prints our true multipliers. Use the 14:50 screenshot cropped to the two lines, never a live run |
| 5B | 1:35 La Celestina, version B | Our venue's public row and book | `https://bazaar.causaprima.ai/api/venues` (keyless JSON; the v20 row reads `fee_bps 0`, `trades`, `pairs`, and the venue's own description), or the organisers' board if it lists venues; `GET /api/venues/v20/offers` for the open book (empty after Saturday's close) | SAFE | Hector | Shows the truth: offers posted, trades 0. Do not zoom on other teams' venues or on who posted. Do not show the brain page (`tools/brain.html`: values) |
| 5A | 1:35 La Celestina, version A | The settlement between two other teams | The settlement line from `python3 tools/pitch_numbers.py` (tick, card, price), and the public site's v20 row showing `trades` of 1 or more | MASK | Hector | Crop the team ids in brackets: we never name teams. If the broker log shows our `matched` line at that tick, it can be shown too (`logs/broker/<date>.jsonl`, one line, no values in it) |
| 6 | 1:50 "we bet ... our idea lost" | The decision table | `docs/plans/market-test-sunday.md` (PR #65 branch `feat/broker-maxpairs` until it merges), the "Decision rule (fixed before the runs)" section and the `hard` and `refit` rows | SAFE | Hector | Simulated traders only; no team values. The words "fixed before the runs" on screen carry the point |
| 7 | 2:19 "running Claude sessions like a trading firm" | Swarm view, public | The funnel link (needs Thiago's yes), or `http://127.0.0.1:8778` on the Mini, or the screenshot | SAFE (public view only) | Hector | **Only port 8778, the public view.** The private view (8777) is NEVER on stage. Check the page once at 14:50: if any line shows a price we only planned, a why, or a value, use the screenshot instead |
| 8 | 2:30 "An audit found our broker's timeouts ..." | PR #63 | `https://github.com/thiagoamaro91/negotiation-agent/pull/63`, the first paragraph | SAFE | Hector | Do not scroll to the factory note. Merged or open, the first paragraph says what was found |
| 9 | 2:42 Close | Back to screen 1, or the La Celestina row | | SAFE | Hector | |

### Back pocket screens (only if a judge asks)

| Question | Screen | Tag | Notes |
|---|---|---|---|
| "Show us a decision with its reason" | One `matched` line from `logs/broker/<date>.jsonl` | SAFE | The broker's lines hold bench quotes, no team values. Never a dealer `run_start`, a duel `duel_new` (`your_limit`) or `decisions.jsonl` without reading it first |
| "How do you stop a runaway bot?" | `agent/abuela.py`, `agent/chato.py` cap code; `agent/lease.py`; `tools/factory.py` docstring | SAFE | Code holds no values. **Not** `tools/factory.py plan` output or `tools/factory_sunday.json`: they print caps and reserves |
| "Show the evals" | `evals/broker/narrative.md` table; `evals/duels-arena/narrative.md` table | SAFE | **Not** `evals/dealers/recommended.md` or `evals/market-desk*/`: they print caps or derive our values |
| "Show the tests" | Skip, or a mutation matrix in a PR body (#63: 6 of 6, #65: 8 of 8) | SAFE | Do not run the suite on stage. On the VM this branch runs 994 tests: with `TZ=Europe/Madrid` only the 5 known failures; in UTC 4 more fail on time zone alone |
| "Who's on your venue?" | Do not answer with names | | "Two other teams posted offers" is the most we say |
| "Show the duels" | `docs/duel-lab/duel-book.md`, the table only | MASK | It reads prices "relative to our limit" (x limit): ratios only, but crop the "Acceptable at" column if asked to zoom. Never `logs/duels/*.json` (`your_limit`) |

## Never on screen (v2's list plus tonight's)

- `logs/state/me.json`; `docs/findings.md` "Where we stand"; the dashboard's El Rastro board and album panels; the brain page's value table (`tools/brain.html`); the private swarm view (8777); the private Celestina side (127.0.0.1:8796).
- `python3 tools/value_inference.py check` section 1 (our true multipliers), and PR #61's inference paragraph (it names the order of our sets).
- Any `run_start` log line, `results/*.out`, `tools/factory_sunday.json`, `tools/factory.py plan` output, the runbook, `evals/dealers/*`, `evals/market-desk*/*`: caps, reserves, max bids.
- `logs/duels/*.json` (`your_limit`), `logs/duel/*.jsonl`.
- `.env`, any terminal where the key could appear, the brain, swarm or dashboard token in a URL bar (`?t=`).
- The vault competitor map, and any screen that lists team names next to our notes about them.
- `tools/pitch_numbers.py` full output (team ids next to the v20 trades and offers).

## Backup plan

1. **14:40 to 14:50, after the freeze:** Hector takes one screenshot per row 1 to 8 (version B and, if it applies, 5A), cropped as the MASK notes say, and drops them in one folder on Jay's machine, named `01-title.png` ... `08-pr63.png`. Before saving each MASK screenshot, read it once for values, caps, team ids and tokens.
2. **If the live laptop fails mid-pitch:** Jay shows the folder in order; Thiago does not stop talking.
3. **If there is no screen at all, or the slot is cut:** Thiago switches to the 60-second fallback (story section 4).
4. **If the funnel or the tunnel is refused or down:** rows 5 and 7 use the public site and the screenshot; nothing else changes.

## Before going on (from the freeze)

| Wall time | Step | Who |
|---|---|---|
| 14:39 | Scores freeze. Bots stop by the factory's gates; nothing to do on stage until 15:00 | |
| 14:45 | `git pull` on the demo laptop. Run `python3 tools/pitch_numbers.py --live` on the Mini (its `logs/feed/` is the live recorder) | Hector |
| 14:50 | **Version A or B** from that output (story section 0). Refresh the five numbers and the lines in story section 3's table. Tell Thiago in one line: "Version B, two teams, twelve of twelve" | Hector |
| 14:50 | `python3 tools/value_inference.py check`: does "beats chance, not repeat" still hold? (story section 3 table) | Hector |
| 14:52 | Screenshots (backup step 1). Open the tabs in row order | Hector |
| 14:55 | Thiago reads the "Do not say" list once (story section 7) | Thiago |
