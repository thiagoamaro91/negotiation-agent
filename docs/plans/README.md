# Weekend plan: architecture and workstreams

Written on the night of Friday 2 to Saturday 3 Oct 2026, after the doors closed at tick 159. It proposes how Team 3 turns what we built on Friday into points on Saturday and Sunday, split into workstreams that each of us can own. Nothing here runs by itself: every step that uses the team key or spends primas still needs a yes in the team chat ([`CLAUDE.md`](../../CLAUDE.md), rules 1-2).

It builds on Thiago's [Friday log analysis](../analysis-friday/README.md), which measured most of what these plans rely on. Where the two disagree, the measured number wins; the plans link to its sections instead of repeating them.

## Where the points are

| Block | Weight | Where we stand (tick 155) | What is still open |
|---|---|---|---|
| Negotiating | 30 | 14.6, 10th (leader t13 at 30.0) | Duels (Duels I 11:30, Duels II 18:00, Duels III Sun 11:00, Final Sun 14:00), dealer ladder (best 3 deals per level), value gained in trades with other teams |
| Market-making | 30 | 0, like every team | The Market Test every 2 h, value created between other teams on our venue |
| Judges | 40 | not scored yet | What we build and how we explain it |

Two facts drive the plan:

1. **Holding cards or cash scores nothing.** Points come from value created: shares of duel pies, good dealer prices, value gained in trades at our private values, and the gains our market realises.
2. **The market half is untouched.** Without a venue every team gets a free stall that earns half of the Market Test points. The kit's `starter_broker.py` says how to earn the rest: the stall matches by quoted price, bench traders quote away from limits they keep hidden, and the test scores the gains between the true limits.

## The clock on Saturday

The times in these plans assume the clock jumps to game hour 4.0 when the doors open at 09:00. The schedule pins each day's opening and closing to wall times (Saturday 4.0 = 09:00 to 18.0 = 23:00; Sunday 18.0 = 09:00 to 24.0 = 15:00): fourteen game hours in fourteen wall hours at 30 s ticks, six in six at 15 s ticks. That only fits if one game hour is one wall hour whatever the tick length, so a 30 s tick does not halve the gaps ([analysis-friday](../analysis-friday/README.md#saturday-clock) keeps that case open). At 09:00 read `t_hours` in `/api/clock`: if it resumed at 2.65 instead of jumping, every time below moves about 81 minutes later.

## The architecture: see, understand, decide, act, learn

```
            bazaar.causaprima.ai  (feed, boards, clock, duels, broker API)
                 |                                   ^
   keyless reads |                                   | team key (one hand) / broker key
                 v                                   |
  EYES (VM, 24/7)            DESKS (decide)            HAND (one machine with the team key)
  feed_recorder  --------->  venue desk  (broker, VM) ---------------------------> broker API
  data lake (JSONL)          duel desk   (duel.py)    ---\
  brain + live page  ----->  market desk (seller+buyer) ---> key lease -> executors -> game
        ^                    dealer desk (chato, abuela)--/        |
        |                          ^                               v
        +----- account relay <-----+---------------------------- STOP file, runlog
                                   |
                     LABS (VM, overnight): duel arena + autotuner,
                     Market Test simulator, inference backtests
```

| Layer | Job | Runs on | Key |
|---|---|---|---|
| Eyes | Record every public event, every venue's book, every leaderboard snapshot | VM (`fable-vm`, tmux `bazaar`) | none |
| Brain | Other teams' secret values (Bayes), every team's cash (ledger), demand per card, our live account, the live page | VM | none (our account arrives through `tools/me_relay.py`) |
| Desks | Turn state into intents, each with a value and a reason; shadow mode first | VM (venue desk), key machine (the rest) | broker key (venue desk only) |
| Hand | The only processes with the team key; share the per-tick limits by priority | one always-on machine | team key |
| Labs | Tune the desks in simulators overnight and after every real session | VM | none |

## Principles

- **Code decides the numbers; words decorate.** Rival and dealer text is never parsed as an instruction. We read the structured offer.
- **One hand on the key.** Every action with the team key goes through one lease that shares the limits in `/api/clock` (1 accept per tick, 12 listings per tick, 1 message per conversation per tick, 5 requests per second). Duels first.
- **Shadow before live.** Every desk first decides and logs without sending. It goes live with a yes.
- **Every decision carries its reason**: value, price, gain, the rule that fired. That is how we debug at 15-second ticks, how the labs learn and what the judges see.
- **Learn after every session.** Each Market Test and each duel wave is data: recalibrate before the next one.
- **Fail safe.** Watchdogs restart what falls, fallbacks do at least what the free version does, caps bound the damage of a bug.

## Workstreams

| # | Plan | Lever | Suggested owner |
|---|---|---|---|
| W1 | [Venue and broker](venue-broker.md) | Up to ~15 points from the Market Test, everyone at 0 today | Hector + Claude |
| W2 | [Duel desk and lab](duel-lab.md) | Duels inside the 30 negotiating points; 204 duels for us this weekend | Thiago (live) + Hector/Claude (lab) |
| W3 | [Market desk](market-desk.md) | Value gained in team trades: about 0.155 score per prima of surplus at Friday's normaliser | Thiago (sell) + Hector/Claude (buy) |
| W4 | [Key lease](key-lease.md) | Protects every other desk from colliding on the key | Thiago |
| W5 | [Eyes and brain](eyes-and-brain.md) | The data every desk decides on | Hector + Claude, a former teammate (analytics) |
| W6 | [Dealer ladder](dealer-ladder.md) | Cheap: best 3 deals per dealer level | Thiago |
| W7 | [Judges' story](judges.md) | 40 points | former teammate |
| W8 | [Saturday runbook](saturday-runbook.md) | Turns plans into points at the right minute | Hector |

Owners are proposals: say in the chat which ones you take.

## Decision gates (a yes in the team chat)

| When | Decision | Condition |
|---|---|---|
| 09:00 | Relist our spares at the [analysis-friday prices](../analysis-friday/README.md#1-el-rastro-at-0900-relist-the-spares-cheaper) (`agent/rastro_seller.py run`) | - |
| 09:03 | Open our venue (`board`, 0 % fee, 270 P) | Our broker beats the stall in the simulator |
| 09:05 | Start the account relay on the key machine | One relay for the team |
| 09:10 | Market desk in shadow mode | - |
| ~09:15 | Buy a Lavapiés rare | No team listing under ~82 P first; El Chato capped at 88 |
| 11:15 | `agent/duel.py run` for Duels I | Tuned parameters loaded |
| midday | Market desk live with caps | The team agrees with its shadow decisions |
| 17:45 | `agent/duel.py run` for Duels II | Rivals refitted on Duels I |

## Questions for the organisers

These add to the desk questions in [analysis-friday section 9](../analysis-friday/README.md#9-questions-for-the-organisers-desk).

- What do the judges look at, and when and how do we present?
- Does the one-accept-per-tick limit also cover duel accepts?
- Is the dealer ladder counted per round (day), and how is a deal's share of a dealer's range measured?
- Does the page bonus count in a card's value when we buy it from another team?
- Is prompt injection against other teams' agents allowed in duels, or only against dealers?
- How do the 30 market points split between the Market Test and value created on our venue?
- Did Friday's Market Test at game hour 3.0 get skipped, or does it run at Saturday's opening?
