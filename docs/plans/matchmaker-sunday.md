# Open Bazaar for Sunday: bring other teams' trades to La Celestina (v20)

Lane WP3, night of Sat 3 to Sun 4 Oct. Data: `logs/feed/feed.jsonl` (26,615 events, ticks 0-1445) and the live public books at tick 1445 (clock paused). Tools: `tools/matchmaker.py`, `tools/announce.py --variant missing`, La Celestina's `/api/missing`, `tools/outreach.py`. Private: nothing here names Team 3's own needs or values.

## 1. What the feed says about team-to-team trades

**Where they happen.** 141 team-to-team settlements: El Rastro 99, v02 (t12) 11, v07 (t10) 11, v21 (t09) 6, v01 (t06) 3, v11 3, v10 2, v06 2, v16 2, v14 1, v17 1. v20: 0.

**Who takes offers off El Rastro, and what.** 42 off-Rastro trades; the side that accepted (a buy when it took an ask, a sale when it took a bid): t12 7 (bought LAT-05 at 5, LAT-07 at 19, LAT-01 at 7; sold LAT-02, RET-02, RET-03, LAT-08 at 4-10), t04 6 (bought RET-02 at 9, MAL-02 at 5, MAL-03 at 7, LAV-03 at 6, MAL-08 at 14; sold MAL-03 at 5), t08 5 (bought SAL-10 at 76, LAV-01 at 4, LAT-01 at 6; sold LAT-06 at 20, LAV-08 at 14), t09 5 (bought RET-03/04/05 at 9, RET-06 at 28, SAL-09 at 70), t14 4, t13 3, t15 3, t01 2, t16 2, others 1. Buyers take cards of the sets they are collecting (t12 La Latina, t04 Malasaña, t09 El Retiro) at about the recent team price: commons 4-10, uncommons 14-28, rares 70-76.

**How fast.** The filled offer had been listed a median of 3 ticks earlier (31 of 42 within 8 ticks). These bots scan every venue's book; a fairly priced offer for a card they want is taken almost at once, wherever it is.

**Who posts on other venues.** t13 573 offers (375 open to all), t08 548 (all addressed to one team), t05 267 (260 addressed), t15 215 on 18 venues (the explorer: it made the first trade on v02, v01, v14, v17 and v21), t06 177, t12 135, t14 117, t07 96, t10 74, t04 72.

**Addressed offers are no shortcut.** 2,210 offers carried `to: <team>`; 35 were taken (1.6 %). The recipients that do accept: t13 6/185, t08 6/78, t16 5/154, t09 4/177, t10 3/55.

**Announcements alone bring nothing.** v06 posted 64 announcements (2 trades), v24 53 (0), v05 48 (0), v03 46 (0), v19 39 (0), v20 13 (0). v07's 11 trades came from cross-listing (t05 and t06 list there), not from its 54 posts.

**What preceded the trades on v02 / v07 / v21 / v01.** In every case, a live offer at a market price for a card someone was collecting, taken within a few ticks: t14's five RET commons at 9 P on v02 (listed at ticks 589-590, all taken by t09, t04 and t15 within 8 ticks); t05's and t06's bids and asks on v07 at 4-15 P; t08's 4 P bids on v21 addressed to the holder (t13, t16, t02 accepted); t15's LAT-05 at 5 and t12's SAL-10 at 76 on v01. A trade within 40 ticks of an announcement happened only where other teams' offers already stood (v07: after 17 of its 54 posts).

**Why v20's 29 listings found nobody.** t15's 16 asks (ticks 384-395) were priced 1.3 to 2.2 times the recent team trades (LAT-07 at 26 against 13-19, LAV-01 at 8-9 against 4) and expired after 10 ticks (5 minutes); t12 bought LAT-07 at 19 on v14 and LAT-01 at 7 on v17 from t15 within 50 ticks. t13's 13 were swaps addressed to one team each, mostly a common for an uncommon or a RET card, cancelled after 4 to 26 ticks. Nobody posted a bid on v20.

## 2. What we built

- `tools/matchmaker.py` (keyless, read-only; `report`, `json --out --every`, `selftest`). Explicit wants first, inferences second (Sol's review): **tier 1** a live bid or swap and a supplier we can name, **tier 2** a live want, **tier 3** a live ask and a team that *appears* to be missing that card, **tier 4** an inferred need with holders, no live offer. Tiers 1-3 carry one action: the counterparty accepts that offer (`POST /api/offers/<id>/accept`), wherever it is; only tier 4 proposes v20 orders. A missing card is inferred from `decks.py` checked against the leaderboard's album count (an exact count over which unseen cards are held); it is never stated as a fact. Offers expiring within 8 ticks, bids below what the dealers pay a holder and lopsided swaps never reach tier 1. Within a tier: v20, then El Rastro (nobody's points), then other teams' venues (their points).
- `tools/announce.py --variant missing`: one match per post, the live offer and the one action, or "appears to be missing ... not confirmed" plus the v20 bid and ask. Never an offer that left its book, another team's venue (unless `--rival-venues`), Team 3, our excluded cards, or a match named in the last 6 posts. Swaps are "accepted directly", never "crossed". Market Test silence gate unchanged.
- La Celestina, under the name other teams see, **Open Bazaar · who needs which card** (Thiago's Sunday plan): the page's first section, `/api/missing?team=tNN`, the first key of `/api/match` (and OPEN BAZAAR lines in `format=text`), `/agents.md`, the concierge's `/llms.txt`. Same matches, holder map kept private (a count; a team sees its own asset ids).
- `tools/outreach.py` (`plan` by default; `run --yes`): one thread at a time, one message, closed at once.

**How to run it on the Mini (orchestrator's call; nothing here is wired into `tools/factory_sunday.json`):**

```bash
python3 tools/matchmaker.py json --live --out logs/matchmaker/latest.json --every 120   # keyless, Market Test gate
python3 tools/announce.py plan --variant missing                                        # what the next post says
python3 tools/announce.py run --yes --variant missing --every-min 12 --count 20         # broker key; one match per post
python3 tools/celestina.py serve ... --matches logs/matchmaker/latest.json              # Open Bazaar on the page/API
python3 tools/outreach.py plan                                                          # keyless; run --yes needs Hector
```

## 3. Top matches for Sunday morning (books at tick 1445; re-run at 09:00)

| # | Tier | Match | Numbers |
|---|---|---|---|
| 1 | 2 | Team 9 bids for SAL-06 on El Rastro (#20259, to tick 1505) | 20 P; team trades 24-27, Abuela sells ~23, Chato ~30 |
| 2 | 2 | Team 1 bids for MAL-11 (epic) on El Rastro (#20243, to tick 1481) | 152 P; Los Pícaros sell epics ~142.5, one team trade at 195 |
| 3 | 3 | Team 6 asks for LAT-07 on El Rastro (#20218, to tick 1455); Team 14 appears to be missing it (p 0.80, La Latina 8/10) | 30 P; team trades 14-15 |
| 4 | 4 | Team 13 appears to be missing MAL-08 (p 0.77, Malasaña 8/10); Team 5 held a copy at tick 1445 (reconstructed) | v20 bid 24 P; team trades 15-20, Abuela ~23 |
| 5 | 4 | Team 14 appears to be missing LAT-06 (p 0.80, La Latina 8/10); Team 5 held one at tick 1445 (reconstructed) | v20 bid 24 P; team trade 20 |

Also live: Team 6's 450 P bid for SAL-12 and swaps for LAV-12 / RET-12 (legendaries, on v21 / v02: other teams' venues, so not announced by default), and Team 14 appears to be missing LAV-01 (p 0.59) with Teams 6, 12 and 17 holding two copies each at tick 1445 by public trades (reconstructed; a Workshop burn may have used them) (v20 bid 6 P). Several of these offers expire in the first minutes after 09:00: the 09:00 run decides.

**What the tools now promise, and no more** (review of #67): our broker crosses a bid and an ask for the same card from two different teams when the bid covers the ask plus the fee, at the midpoint, as capacity allows; an offer addressed to one team is for that team only; nobody is asked to accept on its own venue; holdings from the feed are history ("held at tick N, reconstructed"); every named offer is re-read in its venue's current book right before it is posted, served or sent.

**Honest limits.** Most of the top matches are on El Rastro, so taking them earns us no market points; they are the honest answer to "who needs what". Only tier 4 (and any live want on v20) can move v20. Round 3 releases Chamberí at 10:39: every team then starts that page at zero, so the page inferences matter less after it.

## 4. How we will know it worked

HTTP 200 on a post proves nothing. Per channel:

- **Announcements**: every post logs the match it named (`named` event in `logs/announce/<date>.jsonl`), and its `response` 20 ticks later carries `named_outcome` (`candidate`: a settlement with the named offer's whole structure: venue, direction, card, price, and for an ask or swap the very asset and both legs; a candidate, not proof, since the feed's settlements carry no offer id; `v20_trade`) plus v20 listings and trades in the 20 ticks after vs before.
- **La Celestina**: `--access-log` shows who read `/api/missing` and `/api/match`; success is a v20 listing or trade by that team within 40 ticks.
- **Outreach**: `logs/outreach/<date>.jsonl` names the team, card and offer; success is that team listing, accepting or trading that card within 40 ticks.
- **Overall**: other-team trades on v20 per hour (feed `settlement` with `venue: v20`, parties not t03), split by the channel that named that team and card last before the trade. Baseline: 0 per hour on Saturday.

Stop rule: if 6 announcements in a row show no `named_outcome` and no v20 listing, stop the variant and report; scale outreach beyond the single 09:05 test thread only after one response or settlement.
