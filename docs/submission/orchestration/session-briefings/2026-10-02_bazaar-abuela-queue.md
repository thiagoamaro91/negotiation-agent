# Bazaar: own the Abuela queue (Team 3), 2026-10-02 evening

You are a fresh session with zero prior context. Thiago (owner) is at the Claude Community 48H Hackathon Madrid, on Team 3 with Jay and Héctor. The game is **The Bazaar · Cromos de Madrid** (hosted by Causa Prima): our agents trade Madrid trading cards over an HTTP API with our team key. The owner asked for this parallel session to **take over and keep processing the Abuela Carmen queue** while the parent session works on other things. He wants to **understand what is happening**: after every deal, explain it in plain conversational English (no jargon).

Owner decision trail so far (all approved by him):
- Welcome deal used: bought LAV-06 at her fixed welcome price 17 P (thread 49).
- Haggled deal 1: bought LAV-07 for 22 P (thread 70). She opened at 29, final offer at 22 after 6 rounds; gift LAV-02 in her first reply.
- Queue now: **buys only**. The three spare cards (second copies of LAV-01, LAV-03, MAL-06) are NOT to be sold to Abuela: the owner is deciding whether to sell them to other teams on El Rastro instead. Do not sell them.

## Read first
1. `README.md` (repo root: layout, team rules, logs).
2. `kit/RULES.md` (official rules; sections "Dealers", "Scoring", "The clock").
3. `agent/abuela.py` (the negotiator; read the module docstring and `negotiate()`).
4. `logs/threads/thread-00070.json` (a full successful haggle) and `logs/abuela/2026-10-02.jsonl` (every run so far).
5. Optional background: the rules anchor note in the vault, `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Claude/career/hackathon-madrid-2026/hackathon-madrid_bazaar-rules_v1.md` (sections 1, 4, 14).

## Current state (21:24, tick ~64)
- Cash 361 P, level 1 (only Abuela unlocked), 2 deals, score about 8.5 of 60, rank about 10 of 18.
- **A bot process is ALREADY RUNNING** (PID 8780, started by the parent session): `python3 -u agent/abuela.py run --only LAV-08,SAL-06 --max-deals 2`, output in `results/run-deals-2-3.out`, events also in `logs/abuela/2026-10-02.jsonl`. It is mid-haggle on LAV-08 (thread 105): her 24 P, us 15 P, her final offer expected any round now. After LAV-08 it will haggle SAL-06, then exit.
- Abuela allows ONE open conversation per team. **Never start a second `agent/abuela.py run` while PID 8780 (or any `agent/abuela.py run`) is alive**: check with `pgrep -fl "agent/abuela.py run"`. Jay sometimes runs his own Abuela agent with the same key; if you get `thread_exists` and the open thread is not ours, do NOT close it: tell the owner.

## What we know about Abuela (evidence from the feed and our logs)
- She opens at about 1.15 x list (29 P for an uncommon, 30 P for a pack, 12 P for a common), drops 3-4 P on her first move, then mirrors our step size (we go +1 P, she goes -1 P or holds).
- After about 6 rounds her patience runs out and she names a final offer (`"final": true`) at her limit for that conversation; the bot accepts if it is below our private value of the card, else walks.
- Her replies sometimes include a free gift card ("a little present from me: ..."). Gifts are not scored but the card is ours.
- Scoring (inferred from our live numbers, not published): each Abuela deal scores about 0.9-1.0 of her price range; only the **best three deals per dealer level** count; her level seems worth about 1/15 of the ladder. So after our third haggled deal, more Abuela deals add little score; they only add card value (Lavapiés ×1.6 and Salamanca ×1.3 are our best sets). The third negotiated deal should also unlock level 2 (next dealer + our own market).

## Deliverable(s)
1. Watch PID 8780 to completion (poll `results/run-deals-2-3.out` or `tail` the jsonl; `Monitor` with a grep on `her |say |accept|walk|result|run_end|refused|Traceback` works well). Report each round briefly and each deal in plain words: her opening, how she moved, the final price vs her opening, any gift, and the score/rank change from `GET /api/me`.
2. After it exits: check whether level 2 unlocked: `curl -s -H "X-Team-Key: $BAZAAR_KEY" https://bazaar.causaprima.ai/api/me` (fields `level`, `unlocked`), plus `GET /api/levels` and `GET /api/dealers`. If a new dealer or level appeared, **tell the owner immediately** (it is the most important event of the evening) and do not trade with the new dealer without his go: `agent/abuela.py` only knows Abuela.
3. Continue the queue only if the owner says so: show `python3 agent/abuela.py plan` (buys only) and propose the next 1-2 buys with their value to us; the code keeps a 280 P cash reserve (the level-2 market bond is 250 + 20 P). Run one at a time, e.g. `BAZAAR_OPERATOR=thiago-claude python3 -u agent/abuela.py run --only SAL-07 --max-deals 1` (Abuela caps 8 deals per team per hour).
4. After every run: `python3 tools/snapshot.py`, then commit `logs/` and push (`git add logs && git commit -m "logs: ..." && git push origin main`).

## Done-gates
- `pgrep -fl "agent/abuela.py run"` prints nothing (no bot left running) OR the owner told you to leave one running.
- `git -C . log --oneline -1` shows a logs commit pushed after the last deal; `git status --short logs` is empty.
- `git diff HEAD~1 | grep -c tk-ky4m` prints 0 (the team key never enters git; it lives only in `.env`, which is gitignored).
- You posted a plain-English summary: deals done tonight, prices, cash, level, score and rank.

## Rules
- Scope: run `agent/abuela.py` and `tools/snapshot.py`, commit `logs/`. Do NOT edit `tools/dashboard.*` (a live dashboard is running from it, locally on :8765 and on the Mac Mini), do NOT trade on El Rastro, open venues, duel, or sell the spare cards. Code changes to `agent/abuela.py` only for a clear bug, explained to the owner first.
- Friday doors close at 23:00 Madrid time; after that nothing ticks: stop and summarise.
- Plain, conversational English for the owner; never use the em dash character; numbers come from the API or logs, never guessed.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Final step, after the done-gates verdict either way: use SendMessage to send a ONE-LINE outcome message (done + summary, or blocked + why) to the conductor session: the session running in `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Claude/career/hackathon-madrid-2026`; pick it from ListAgents. If ListAgents shows no such session, or several match, skip the ping silently.
