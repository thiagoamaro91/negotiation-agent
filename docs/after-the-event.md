# After the event

Written on 2026-10-05, the day after the hackathon. [`SUBMISSION.md`](../SUBMISSION.md) stays exactly as it was submitted. This note records the final numbers, corrects two statements in it, and explains how to run its eval commands today.

## Standing at the close

4th of 18 teams when the market froze on Sunday 4 October at 15:00 Madrid time, with a score of 34.19: Negotiating 26.04 of 30 (first of the 18 teams on that column) and Market-making 8.15 of 30 (17th of 18). Source: the last leaderboard recorded in `logs/feed/snapshots.jsonl` (line 4482, tick 2802), which matches the final standing in `SUBMISSION.md` line 4.

## Pull requests

- 107 pull requests were merged during the 48 hours of the event, from Friday 2 October 18:00 to Sunday 4 October 18:00 Madrid time (16:00 to 16:00 UTC).
- 99 of them were merged before the game closed on Sunday at 15:00 Madrid time (13:00 UTC). The 8 merged after the close are documentation, among them `SUBMISSION.md` itself and the judges' dossier.
- `SUBMISSION.md` (lines 12 and 282) gives 101 pull requests with 99 merged. As its line 280 says, that was a snapshot taken at commit `3358e4c`, before the last documentation pull requests.

Counted with the GitHub search API on 2026-10-05:

```bash
# 107: merged in the 48-hour window
gh api "search/issues?q=repo:thiagoamaro91/negotiation-agent+is:pr+is:merged+merged:2026-10-02T16:00:00Z..2026-10-04T16:00:00Z" --jq .total_count
# 99: merged before the game closed
gh api "search/issues?q=repo:thiagoamaro91/negotiation-agent+is:pr+is:merged+merged:2026-10-02T16:00:00Z..2026-10-04T13:00:00Z" --jq .total_count
```

## Corrections to SUBMISSION.md

**1. Private values are in the repository.** `SUBMISSION.md` line 260 says: "Private account state and logs containing valuations or strategy limits are excluded from the judges' submission." Line 454 adds: "Private card valuations and strategy limits are excluded from the judges' submission. Raw private account state, bot logs, plans and handoffs are excluded".

What is actually in this repository: `logs/state/me.json` is committed and holds the team's private set multipliers (the `logs/state/` entry in the README's team notes says so), and other committed logs carry private limits too, for example the dealer bots' `run_start` lines with our caps (`SUBMISSION.md` line 267). Deleting the files now would not remove them from git history, so they are left in place.

**2. One tunnel address was not redacted.** `SUBMISSION.md` line 454 says: "Removed from this submission: the team key and any API tokens (never committed), Cloudflare tunnel URLs and dashboard tokens (replaced with `<redacted-tunnel>`), and the Clearing House invite code."

What is actually in this repository: the session briefings use the placeholder, but one committed log, `logs/concierge/2026-10-03.jsonl`, still records one Cloudflare quick-tunnel hostname, in the start command of two concierge runs. Quick-tunnel addresses are temporary, and the tunnels were stopped after the event (pull request #114). It stays in git history for the same reason as above.

## Running the evals today

The two eval commands under "How to run" in `SUBMISSION.md` (lines 444 and 445) now stop with "use a new variant (or move the old results away)". The results recorded under `evals/` were written by earlier versions of the bots, and the harness refuses to overwrite them. Adding `--out-root` writes a fresh run somewhere else and leaves `evals/` as recorded:

```bash
python3 tools/eval_dealers.py --variant baseline --reps 5 --out-root /tmp/negotiation-evals
python3 tools/eval_broker.py --variant baseline --policy stall --out-root /tmp/negotiation-evals
```
