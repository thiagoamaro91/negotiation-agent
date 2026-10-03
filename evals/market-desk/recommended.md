# Market desk: recommended flags for Sunday

```
python3 -u agent/market_desk.py run --min-cash 30 --cap-hour 150 --until {until}
```

That is v8: `--min-cash 30 --cap-hour 150` and team venues on (the factory's `--no-team-venues` dropped). Everything
else stays at the desk's defaults (bids on, `--bid-step 1 --bid-step-ticks 20 --bid-max 6`, `--cap-day 250`).

## Evidence (paired over the 40 TEST cases, v8 minus the Sunday baseline)

| cash world | baseline test total | v8 test total | Δ ± 95% CI | z | bad trade | cash breach | contested share of Δ | plausible-fill share of Δ |
|---|---|---|---|---|---|---|---|---|
| cash 60 (ledger −90 + allowance 150), primary | +3.0 P | +16.2 P | +13.2 ± 19.6 P | +1.3 | 0 | 0 | 0% | 30% |
| cash 319 (account 169 + allowance 150) | +10.0 P | +89.5 P | +79.5 ± 96.0 P | +1.6 | 0 | 0 | 87% | 0% |

Train (60 cases): cash 60 +45.9 P (z +1.6), cash 319 +60.0 P (z +1.6). v8 is not below the baseline in either world on
either split, and no guardrail fires anywhere (grader floor 0 P: never overdraw).

## Read this before using it

- **Not proven.** No round cleared the protocol's 2 SE bar, so by the protocol the winner is the baseline. v8 is the
  recommendation on judgment: the baseline's `--min-cash 280` is the old bond rule, and with it the desk cannot buy at
  all in either cash world. v8 is the one config picked on train and checked once on test, and it is the only one that
  is never worse.
- **The cash 319 gain is mostly races.** 87% of it is two listings another team really took first. If we lose those
  races, the cash 319 gain falls to about what cash 60 shows.
- **The cash 60 gain is small and partly inferred.** 30% of it is one bid fill backed by evidence, not by a real
  accept.
- **`--min-cash 30`** keeps a 30 P reserve if the ledger's cash is right. Raise it if dealer deals (Abuela, El Chato)
  need that cash on Sunday morning. `--min-cash 100` (v1) does as well at cash 319 but cannot buy at cash 60.
- **Team venues** score market points for the venue's owner. The eval does not count that cost, and it is why the
  factory turned them off. Drop `--team-venues` (keep `--no-team-venues`) if that matters more than about +13 P at
  cash 60.
- **Bid stepping, the bid count and the LAV-09/LAV-10 bid churn** made no difference in the replay (about 0 P).
  Leave them at the defaults until the code fix lands.
