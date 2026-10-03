# Market desk: an experiment for Sunday, not the Sunday line

**Default: leave the factory's current `market_desk` step as it is** (`tools/factory_sunday.json`: `--no-team-venues`,
`enabled: false`, `--min-cash` at the desk's default 280). Nothing in this eval proves a better line. What follows is
an experiment, to be run only if both gates below are met, not a recommendation to switch.

## The experiment (v8)

```
python3 -u agent/market_desk.py run --min-cash 30 --cap-hour 150 --team-venues --until {until}
```

v8 = `--min-cash 30 --cap-hour 150` with team venues on (the factory's `--no-team-venues` dropped). Everything else
stays at the desk's defaults (bids on, `--bid-step 1 --bid-step-ticks 20 --bid-max 6`, `--cap-day 250`).

### Gate 1: a live cash check, and a `--min-cash` that covers the dealer steps

The eval replays with a fixed starting cash (60 P or 319 P) and a ledger-derived cash path, not the real account.
`--min-cash 30` lets the desk spend down to 30 P, cash that the dealer steps need (Abuela and El Chato buys, the caps
in `tools/factory_sunday.json`). Before starting: read the account's real cash from the server, and set `--min-cash`
to at least the cash the dealer steps still to run need plus the 30 P reserve, not 30. If the real cash cannot cover
that, do not run the experiment (the baseline's 280 also cannot buy, that is its cost).

### Gate 2: an explicit decision on rival-venue points

`--team-venues` lets the desk trade on other teams' venues, and a trade on a venue scores market points for that
venue's owner, a rival. The eval does not count that cost, and it is why the factory turned team venues off. The
whole cash 60 gain depends on it: without team venues the same flags (`--min-cash 30 --cap-hour 150`, v5) are flat
on test at cash 60 (+0.0 P). At cash 319 their +69.2 P comes from `--min-cash 30` alone (the two races below), and
`--cap-hour 150` adds nothing (v5 vs v2, +0.0). Someone has to decide, in chat and on the record, that the expected gain below is
worth giving rivals those points. If not, do not drop `--no-team-venues`.

## Evidence (paired over the 40 TEST cases, v8 minus the Sunday baseline)

| cash world | baseline test total | v8 test total | delta +- 95% CI | z | bad trade | cash breach | contested share of delta | plausible-fill share of delta |
|---|---|---|---|---|---|---|---|---|
| cash 60 (ledger -90 + allowance 150), primary | +3.0 P | +12.2 P | **+9.2 +- 18.1 P** | +1.0 | 0 | 0 | 0% | 0% |
| cash 319 (account 169 + allowance 150) | +6.0 P | +85.5 P | +79.5 +- 96.0 P | +1.6 | 0 | 0 | 87% | 0% |

These are the figures after the review fix to the grader (a listing addressed to a team no longer counts as fill
evidence; regraded from the stored rows, replay not rerun; see `narrative.md`, "Review corrections"). As first graded
the cash 60 line read +16.2 vs +3.0, delta +13.2 +- 19.6 P (z +1.3) with 30% plausible fill, and the cash 319 baseline
total +10.0, v8 +89.5. Train (60 cases): cash 60 +45.9 P (z +1.6), cash 319 +60.0 P (z +1.6), unchanged by the fix.

**How much weight this carries.** The primary gain is about +9 P with a 95% interval that includes 0 and a negative
side (+9.2 +- 18.1), on a split whose rows are not independent (one whole-day replay, shared cash and one accept slot
per tick), so the interval is optimistic. Read it as directional.

## Read this before using it

- **Not proven.** No round cleared the protocol's 2 SE bar, so by the protocol the winner is the baseline. v8 is the
  one config picked on train and checked once on test, and it was never below the baseline in any world or split. The
  reason to try anything is that the baseline's `--min-cash 280` is the old bond rule and, with it, the desk cannot buy
  at all in either cash world.
- **The cash 319 gain is mostly races.** 87% of it is two listings another team really took first. If we lose those
  races, the cash 319 gain falls to about what cash 60 shows. It also assumes 319 P of cash that Gate 1 has to confirm.
- **The cash 60 gain is small, from team venues, and no longer partly inferred.** The 30% that came from one inferred
  bid fill was an addressed listing and is gone; what remains is team-venue trades.
- **`--min-cash 100`** (v1) does about as well at cash 319 (+69.2 +- 95.0 P after the fix) but cannot buy at cash 60.
- **Bid stepping, the bid count and the LAV-09/LAV-10 bid churn** made no difference in the replay (about 0 P). Leave
  them at the defaults until the code fix lands.
