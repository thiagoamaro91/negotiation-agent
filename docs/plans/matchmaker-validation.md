# Matchmaker validation: deck inference against our own holdings (Sun 4 Oct, night)

Private. This file names our cards; nothing here goes into an announcement, a page or anything another team reads.

Question: when `tools/matchmaker.py` says "team X appears to be missing card Y", how often is that true? A wrong
claim wastes a 12-minute announcement slot and credibility; a right one is worth 2.8 to 5 board points for the first
other-team trade on v20. The one deck we know exactly is ours, so we ran the matchmaker's inference on Team 3 and
compared it with what we really held.

## Ground truth: which source

`logs/state/me.json` (a raw `GET /api/me` saved by `tools/snapshot.py`: every asset with its id and ref, our album
pages with `have/of/complete`, at a known tick) and its **12 committed versions** in git history, ticks 33 to 1445
(Friday 20:54 to Saturday 23:02). It is the only source with exact holdings by asset id. The others are weaker:
`logs/market/2026-10-03.jsonl` carries desk decisions (a `copies` count per card it looked at), not holdings;
`logs/score.jsonl` carries `album_filled` only; `docs/plans/pages-sunday.md` is prose ("9/10 Salamanca").

At tick 1445 we held 31 cards: 30 page cards (LAV 10/10, LAT 10/10, SAL 9/10 lacking SAL-10, MAL 1/10, RET 0/10) and
the epic LAV-11. Leaderboard row: `album_filled` 30, `pages_complete` 2, `rarest` LAV-11.

## Commands (all offline and keyless)

```bash
python3 tools/decks.py                                   # the rebuilt deck's check against logs/state/me.json
python3 tools/matchmaker.py validate --git               # every committed me.json: recall, precision, false missing, calibration
python3 tools/matchmaker.py validate --me logs/state/me.json   # one snapshot (e.g. a fresh Sunday one)
python3 tools/matchmaker.py report --live --feed logs/feed      # the board (keyless live reads), as announce sees it
```

`validate` runs exactly the matchmaker's functions (`decks.build` up to the snapshot's tick, `holdings`,
`missing_odds`, `near_pages`) on Team 3, with our own album counts standing in for the leaderboard's.

## Results

### What the rebuilt deck names (tick 1445)

`decks.py` check: `real 31, rebuilt 28, ids_right 26, ids_missed 5, ids_wrong 3, named 24, names_right 21`.
PR #57 said "names 23 of our 30 cards, 3 of them wrong": reproduced with one difference, **24 copies named, 21
right, 3 wrong** (on the committed feed to tick 1445). The 3 wrong are **extra copies, not wrong cards**: LAV-01,
LAV-05 and MAL-02 are each named twice and held once (a second copy left without a settlement the feed shows). The
matchmaker adds one gift copy without an id (LAV-02): 25 named, 22 right.

At the level that matters for "missing" (distinct page cards):

| tick | page cards held | named | named but not held | recall | precision |
|---|---|---|---|---|---|
| 33 | 13 | 1 | 0 | 0.08 | 1.00 |
| 146 | 21 | 9 | 0 | 0.43 | 1.00 |
| 227 | 26 | 15 | 0 | 0.58 | 1.00 |
| 630 | 30 | 14 | 0 | 0.47 | 1.00 |
| 1445 | 30 | 21 | 0 | **0.70** | **1.00** |

Precision is 1.00 in all 12 snapshots: the feed never named a page card we did not hold. Recall grows with play (our
starter and pack cards are unseen until they are listed or traded): 9 of our 30 page cards were never shown.

### "Appears to be missing" about us (false missing)

At tick 1445 the inference sees LAV at 8/10 (LAV-04 and LAV-08 never shown). With `album_filled` 30 and
`pages_complete` 2 the count model gives both **p_missing 0.002**: two complete pages must exist and LAV is the only
page they can complete it with. Nothing is flagged: **0 false missing** in all 12 snapshots (we were never 9/10 or 8/10
on a page by inference while holding it, except LAV here, which the count resolved).

Without the page count (what the old code fell back to when the counts did not fit a deck) the same two cards read
**p 0.55 and 0.76: two false missing**, both above the matchmaker's MIN_P 0.15.

### Calibration of p_missing (every unnamed page card, 12 snapshots, 421 card-observations)

| p_missing | cards | really missing | share | mean p |
|---|---|---|---|---|
| 0.00-0.15 | 10 | 0 | 0.00 | 0.08 |
| 0.15-0.50 | 76 | 39 | 0.51 | 0.44 |
| 0.50-0.80 | 229 | 141 | 0.62 | 0.64 |
| **0.80-1.00** | **106** | **96** | **0.91** | 0.89 |

p is roughly calibrated when the counts fit. Below 0.8 a claim is wrong 4 times in 10 or more. Caveat: one team (ours),
observations correlated over time; our deck always fit the leaderboard's counts.

## Hard facts from the official leaderboard

`GET /api/leaderboard` (keyless) gives per team: `album_filled`, `album_slots` (50), `pages_complete`, `rarest`
({ref, serial, print_run, rarity}), `deals`, `luck`, `level`, `badges`, scores. **Nothing per set or per page.** The
official dashboard's stars are `pages_complete` drawn as a gold star with the count (BigScreen view, title "N complete
pages"; Teams view "N pages complete"), so *which* page is complete is not public: only how many.

What the matchmaker now enforces (`build()`, tests in `tests/test_matchmaker.py`, each seen red with its guard removed):

1. **Counts as exact constraints** (existing, `missing_odds`): exactly `album_filled - named` unnamed page cards are
   held and exactly `pages_complete` pages are complete; a named complete page is never "missing", and the count pins
   which near page is complete (the LAV case above).
2. **`rarest` is held** (new): a team's rarest card, when it is a page card, counts as held; never "missing"
   (`teams[t].held_by_leaderboard`). Live at tick 1445: t07 LAV-09, t11 MAL-09, t13 SAL-09.
3. **Named page cards > `album_filled`** ⇒ the deck is wrong somewhere (new): before, `unseen` was clamped to 0 and
   every unnamed card read p_missing 1.0, the most confident exactly when wrong. Now the team is `consistent: false`
   and gets **no inferred need**.
4. **No choice of unnamed cards fits both counts** ⇒ some named card is not held (new): before, the page count was
   silently dropped (p 0.55-0.80). Now `consistent: false`, no inferred need. Live at tick 1445: **t13** (album 32,
   3 pages) and **t14** (album 41, 4 pages). All 7 tier 3-4 matches on the board came from these two teams (t14 LAT-07
   p 0.80, LAT-06 0.80, LAV-08 0.80, LAV-01 0.59; t13 MAL-08 0.77, LAV-01 0.57, LAV-03 0.57). They are now withheld
   (`withheld_inconsistent`: 7) and the report lists the two decks under "Decks that contradict the leaderboard".
   The board is left with its 5 explicit live wants (tier 2).

Supply side: a team is a supplier only with a named spare (two or more copies), a live ask, or one copy of a set it
values low and is far from filling (3+ page cards unnamed), so a completed page never supplies its only copy.

## What is safe to announce

| tier | basis | announce? |
|---|---|---|
| 1 live want + known supply | a live offer (re-read right before the post) | yes |
| 2 live want | a live offer | yes |
| 3 live ask + inferred need | the ask is a fact, the need an inference | only at p_missing >= 0.8 and a consistent deck |
| 4 inferred need | inference | only at p_missing >= 0.8 and a consistent deck |

`tools/announce.py --variant missing` named the first match in order whatever its p (the matchmaker's floor is 0.15),
so a t14 "appears to be missing LAT-07" at p 0.80 from a contradictory deck, or a 0.57 coin flip, could be posted.
Now `announce.MIN_P_ANNOUNCE = 0.8` (`--min-p` to change it): an inferred need below it, without a p, or from a team
marked `consistent: false` is never named. Live wants are untouched. The matchmaker's own MIN_P (0.15) stays for the
private report.

## Our cards never shown: `--exclude-from`

`announce.MISSING` is a hard-coded list from Saturday tick 556; at tick 1445 it hides LAV-09, LAV-10, LAT-03, LAT-09,
SAL-02, SAL-05, SAL-09 (all held now) and misses 18 cards we lack (MAL-01/04/06/07/08/10, RET-02/06, the
10 of CHA). New flag on
`matchmaker.py` and `announce.py`: `--exclude-from logs/state/me_live.json,logs/state/me.json` excludes every page card
in the catalog we do not hold (every card of every page we have not completed), from the freshest of those files.
At tick 1445 that is 30 cards (SAL-10, 9 MAL, 10 RET, 10 CHA). Missing, unreadable or another team's file: the
built-in list, with a WARNING line. Older than `--exclude-max-age-min` (default 60) of game time (snapshot tick
against the feed's tick; mtime only without a tick): its cards plus the built-in list, with a WARNING. Logged as a
count and the file name, never the cards; `announce.py` re-reads it before every post. Cheap keyed refresh for the
Mini: `python3 tools/snapshot.py --me-only` (one `GET /api/me`, writes only `logs/state/me.json`, atomically).

## Exact holdings: the census (PR #57)

Decision: **(b)**. PR #57 (`feat/card-census`, head 1d2a6e1) merges cleanly into main and its 39 tests pass, but it is
a 1,568-line keyed tool with its own review history; copying it into this keyless PR would duplicate that review.
This PR only reads its documented snapshot format: `matchmaker.py --census PATH` (a `cards-<date>-t<tick>.json` file,
or a directory: the snapshot or top-up with the highest tick). Census holdings replace the rebuilt decks for every team
(holders `"seen": "census tick N"`, matches `"basis": "census tick N"`, real asset ids), brought forward by every
public settlement since the walk started. `album_filled` still bounds it (cards minted after the census are unseen),
and an unusable census is a WARNING and the feed inference, never an empty board. `--census` needs #57 merged (or its
branch) on the Mini only to produce the file.

Size: the highest asset id the feed has shown is 1186; a full walk is about 1,250 ids plus 60 trailing 404s. At 4 req/s
that is ~1,300 requests in **~6 minutes** (plus status reads every 2 min). Saturday's hourly churn: 15-72 settled ids
and 1-102 minted cards per hour, plus 40 ids margin and the commons of teams that crafted since: a top-up is roughly
100-300 ids, **1-5 minutes at 1 req/s** (20 % of the key's 5 req/s, shared with every bot).

### Sunday procedure (Thiago, on the Mini, in `~/bazaar`)

```bash
# 08:40, BEFORE `factory.py up --yes` (doors closed, clock paused, no bot on the key yet)
python3 tools/census.py selftest && python3 tools/census.py run --rate 4 --out logs/census --until 08:57
python3 tools/snapshot.py --me-only                     # our holdings for --exclude-from
python3 tools/matchmaker.py report --live --census logs/census --exclude-from logs/state/me.json | head -40   # sanity
```

If the walk stops early (exit 1/3/6), `--resume` the same command; if it is not done by 08:57, start the factory
anyway: the matchmaker falls back to the feed inference by itself.

Factory lines (for PR #66's owner; this PR does not edit `tools/factory_sunday.json`):

```json
"cmd": ["{python}", "-u", "tools/matchmaker.py", "json", "--live", "--out", "logs/matchmaker/latest.json", "--every", "120", "--census", "logs/census", "--exclude-from", "logs/state/me_live.json,logs/state/me.json", "--exclude-max-age-min", "90"],
"cmd": ["{python}", "-u", "tools/announce.py", "run", "--yes", "--variant", "missing", "--every-min", "12", "--count", "40", "--exclude-from", "logs/state/me_live.json,logs/state/me.json", "--exclude-max-age-min", "90"],
```

Hourly top-up, only the ids that moved (the feed's settlements since the census, every id minted since, the commons
of teams that crafted since; `tools/decks.py moved`), and our holdings:

```bash
BASE=$(ls -t logs/census/cards-*-t*.json | grep -v history | head -1)
python3 tools/decks.py moved --base "$BASE" --out logs/census/moved.txt \
  && python3 tools/census.py ids --ids-file logs/census/moved.txt --base "$BASE" --out logs/census --rate 1
python3 tools/snapshot.py --me-only
```

The matchmaker picks the newest snapshot by itself at its next 2-minute build; nothing restarts.
