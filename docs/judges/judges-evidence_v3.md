# Judges' evidence v3 (Team 3)

Companion to [`judges-story_v3.md`](judges-story_v3.md). What is on screen while Thiago talks, in script order, who drives it, and what needs Thiago's yes. Internal. Replaces [`judges-evidence_v2.md`](judges-evidence_v2.md); its safety tags and "never on screen" list carry over and grow.

## Roles (as v2; confirm in the team chat)

- **Thiago** speaks. Does not drive a terminal on stage.
- **Hector** drives the laptop: opens each screen on its cue, in the order below, from tabs prepared at 14:50.
- **a former teammate** keeps time (signals at 1:00, 2:00, 2:40) and holds the backup: the screenshots folder, ready if a live screen fails.

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
| 2 | 0:39 "El Chato wanted 90 ... stopped at 84" | El Chato LAV-09 conversation | `logs/threads/thread-00335.json` in a viewer (36 keys, none a value, cap, limit, floor or multiplier: checked Sunday 02:40) | SAFE | Hector | Never `logs/chato/2026-10-03.jsonl`: its `run_start` line carries our cap. Never the dashboard chart page (album panel) |
| 3 | 1:03 "two public recorders, merged ... twelve readings out of twelve" | The 14:50 numbers | Terminal: `python3 tools/pitch_numbers.py --live --stage`, lines 3 and 4 | SAFE with `--stage` | Hector | `--stage` prints no team id. Without it the VERSION line can name the parties of a v20 trade: never run it without `--stage` on a shared screen. Do not show `tools/ledger.py` with every team's cash |
| 4 | 1:15 "Bayes over the 720 ways ... beats chance, but not ..." | Inference check, reliability line | `python3 tools/value_inference.py check`, the line starting `3) reliability` and the `baselines over 539 choices` line | MASK | Hector | **Section 1 of that output is NEVER**: it prints our true multipliers. Use the 14:50 screenshot cropped to the two lines, never a live run |
| 5 | 1:28 La Celestina, the network | Our venue's public row; the Celestina public page if served | `https://bazaar.causaprima.ai/api/venues` (keyless JSON; the v20 row reads `fee_bps 0`, `trades`, `pairs`, and the venue's own description). If the public page is served (Thiago's yes): its `/` page, or `/api/v20` | SAFE (public side only) | Hector | Never the private Celestina side (127.0.0.1:8796: the holder map). Do not zoom on other teams' venues or on who posted. Never the brain page (`tools/brain.html`: values) |
| 5B | 1:53 version B | Same as 5 | | SAFE | Hector | Shows the truth: trades 0 |
| 5A | 1:53 version A | The settlement between two other teams | The settlement line from `python3 tools/pitch_numbers.py --live --stage` (tick, card, price), and the v20 row with `trades` of 1 or more | SAFE with `--stage` | Hector | If the broker log shows our `matched` line at that tick, it can be shown too (`logs/broker/<date>.jsonl`, one line, no values in it) |
| 6 | 2:02 "Our worst failure ..." | **No screen** of the feed or the desk log; a still: `factory.py status` screenshot taken at 14:30 with the bots RUNNING | `python3 tools/factory.py status` on the Mini at 14:30, screenshot | MASK (check once) | Hector | The status lines carry names, states, log ages and restart counts, no arguments; read it once for a step label or number before saving. **Never** the feed lines of the incident (they name the card, the team and the prices), never `logs/market/2026-10-03.jsonl` (its decision lines carry our values and ceilings), never `factory.py plan` |
| 7 | 2:39 "we bet ... lost ... Simple rule kept" | The decision table | `docs/plans/market-test-sunday.md` (PR #65), the "Decision rule (fixed before the runs)" section and the `hard` and `refit` rows | SAFE | Hector | Simulated traders only; no team values. The words "fixed before the runs" on screen carry the point |
| 7b | 2:55 "Last night two searches ran until morning ..." | The two leaderboards, top table only | `docs/duel-lab/duels3-search/leaderboard.md` (branch `vm/wp10-duel-search`), `evals/broker-search/leaderboard.md` (branch `vm/wp11-broker-search`, once it exists) | MASK until read | Hector | Read both at 07:00 for limits or values before they go on a screen (duel candidates are ratios of our limit, not values, but check). If either is missing, no screen |
| 7c | 3:15 "one duel feature ... we switched off" | The F4 paragraph | `docs/duel-lab/duels3-params.md` lines 8 to 11 only | MASK (crop) | Hector | Lines 8 to 11 hold the gain and the race, no limit. The rest of the file names our accept and last-chance ratios: crop |
| 8 | 3:25 optional demo | Live terminal | `python3 tools/pitch_numbers.py --live --stage`, after `git pull`, font large, no other window or history visible | SAFE with `--stage` | Hector | `--stage` sets a 5-second deadline: slow figures print `unavailable` instead of hanging. If anything prints `unavailable` or an error, say "we'll skip that" and use the 14:52 screenshot of the same command. Clear the terminal first: no scrollback with a key, a token or an unstaged run |
| 9 | 3:32 "running Claude sessions like a trading firm" | Swarm view, public | The funnel link (needs Thiago's yes), or `http://127.0.0.1:8778` on the Mini, or the screenshot | SAFE (public view only) | Hector | **Only port 8778, the public view.** The private view (8777) is NEVER on stage. Check the page once at 14:50: if any line shows a price we only planned, a why, or a value, use the screenshot instead |
| 10 | 3:42 Close | Back to screen 1, or the La Celestina row | | SAFE | Hector | |

### Back pocket screens (only if a judge asks)

| Question | Screen | Tag | Notes |
|---|---|---|---|
| "Show us a decision with its reason" | One `matched` line from `logs/broker/<date>.jsonl` | SAFE | The broker's lines hold bench quotes, no team values. Never a dealer `run_start`, a duel `duel_new` (`your_limit`) or `decisions.jsonl` without reading it first |
| "How do you stop a runaway bot?" | A screenshot prepared at 14:52 of the guard logic only: the lines where `--cap` can only lower our limit, and `guarded_accept` in `agent/dealer_client.py` (the duel-lock check before an accept) | MASK | **Never open `agent/abuela.py` or `agent/chato.py` whole on stage**: both hold a numeric cash reserve constant near the top, and Chato's docstring carries example commands with caps. The screenshot shows no constant, no default and no example command; read it once before saving. `agent/lease.py` is the market desk's lease only: do not present it as the dealers' or the duel bot's. **Not** `tools/factory.py plan` output or `tools/factory_sunday.json`: they print caps and reserves |
| "Show the evals" | `evals/broker/narrative.md` table; `evals/duels-arena/narrative.md` table | SAFE | **Not** `evals/dealers/recommended.md` or `evals/market-desk*/`: they print caps or derive our values |
| "Show the tests" | Skip, or a mutation matrix in a PR body (#63: 6 of 6, #65: 8 of 8) | SAFE | Do not run the suite on stage. On the VM this branch runs 1,216 tests: with `TZ=Europe/Madrid` 4 failures (3 known, 1 intermittent); in UTC more fail on time zone alone |
| "Who's on your venue?" | Do not answer with names | | "Two other teams posted offers" is the most we say |
| "Show the duels" | `docs/duel-lab/duel-book.md`, the table only | MASK | It reads prices "relative to our limit" (x limit): ratios only, but crop the "Acceptable at" column if asked to zoom. Never `logs/duels/*.json` (`your_limit`) |

## Never on screen (v2's list plus tonight's)

- `logs/state/me.json`; `docs/findings.md` "Where we stand"; the dashboard's El Rastro board and album panels; the brain page's value table (`tools/brain.html`); the private swarm view (8777); the private Celestina side (127.0.0.1:8796).
- `python3 tools/value_inference.py check` section 1 (our true multipliers), and PR #61's inference paragraph (it names the order of our sets).
- Any `run_start` log line, `results/*.out`, `tools/factory_sunday.json`, `tools/factory.py plan` output, the runbook, `evals/dealers/*`, `evals/market-desk*/*`: caps, reserves, max bids.
- `logs/duels/*.json` (`your_limit`), `logs/duel/*.jsonl`.
- `.env`, any terminal where the key could appear, the brain, swarm or dashboard token in a URL bar (`?t=`).
- [Line removed after the event.]
- `tools/pitch_numbers.py` without `--stage` (team ids next to a v20 trade; makers in `--json`).
- The incident's raw data: feed lines of the offers addressed to us, `logs/market/2026-10-03.jsonl` (values, ceilings), `tools/factory.py plan` and `tools/factory_sunday.json` (caps, reserves).

## Backup plan

1. **14:30, before the shutdown:** `factory.py status` screenshot for row 6. **14:52, after the numbers:** Hector takes one screenshot per remaining row (version B and, if it applies, 5A), cropped as the MASK notes say, and drops them in one folder on a former teammate's machine, named `01-title.png` ... `10-close.png`. Before saving each MASK screenshot, read it once for values, caps, team ids and tokens.
2. **If the live laptop fails mid-pitch:** A former teammate shows the folder in order; Thiago does not stop talking.
3. **If there is no screen at all, or the slot is cut:** Thiago switches to the 60-second fallback (story section 4).
4. **If the funnel or the tunnel is refused or down:** rows 5 and 7 use the public site and the screenshot; nothing else changes.

## Before going on (archived rehearsal checklist)

Archived early-Sunday rehearsal plan; its predicted freeze time and shutdown checklist were superseded. Use the final submission timeline for actual events.

| Wall time | Step | Who |
|---|---|---|
| 14:30 | `python3 tools/factory.py status` screenshot on the Mini, bots RUNNING (row 6). Read it once before saving | Hector |
| 14:39 | Scores freeze. **The bots keep running**: the factory's gates only decide launches, a running bot is not stopped by the freeze | |
| 14:40 | **Explicit shutdown on the Mini**, by whoever is at it, after one line in the team chat (CLAUDE.md rule 5): `tmux kill-window -t factory:<name>` for broker, duel, abuela, chato, pilar and watchdog (each keeper stops its bot and releases its lock and claim). Leave `factory:feed` running for the numbers | Mini operator (Thiago, or Hector on his yes) |
| 14:42 | **Verify** before any screen is prepared: `python3 tools/factory.py status` shows no trading bot running, and `ps -ax \| grep -E 'agent/(broker\|duel\|abuela\|chato\|pilar)\|agent\.(broker\|duel)'` prints only the grep itself. Anything still alive: kill that pid, then check again. No live terminal of a bot is opened on stage either way | Mini operator |
| 14:45 | `git pull` on the demo laptop. Run `python3 tools/pitch_numbers.py --live` on the Mini (its `logs/feed/` is the live recorder). Then `tmux kill-session -t factory` | Hector |
| 14:50 | **Version A or B** from that output (story section 0; the tool prints B itself when feed and leaderboard disagree). Refresh the five numbers and the lines in story section 3's table. Tell Thiago in one line: "Version B, two teams, twelve of twelve" | Hector |
| 14:50 | `python3 tools/value_inference.py check`: does "beats chance, not repeat" still hold? (story section 3 table) | Hector |
| 14:52 | Screenshots (backup step 1). Open the tabs in row order | Hector |
| 14:55 | Thiago reads the "Do not say" list once (story section 7) | Thiago |
