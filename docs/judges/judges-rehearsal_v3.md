# Rehearsal note for Thiago, Sunday 07:00

Twenty-five minutes. Everything you need is in [`judges-story_v3.md`](judges-story_v3.md) (what you say) and [`judges-evidence_v3.md`](judges-evidence_v3.md) (what Hector shows). This page is the order to read them in, what to practise, the 07:00 fill for the overnight lab, three yes/no calls, and seven anecdotes with their sources.

## 1. Read (8 minutes)

1. Story **section 3**, version B, out loud once, slowly. It is the default; Saturday closed on B. Brackets: `[if merged #NN]` and `[if served]` are read only if Hector confirms at 14:50; `[07:00: ...]` you fill now (section 2a below).
2. Story **section 0**: version A replaces one paragraph, and only if `tools/pitch_numbers.py` finds a v20 trade between two other teams at 14:50. Hector tells you which at 14:50 in one line.
3. Story **section 7**, "Do not say". The new traps: no volume or adoption words for La Celestina in version B; never name a team, including the two that posted on v20; "beats chance", never "knows their values".
4. Story **section 6**, the back-pocket answers. Read the first line of each only.

## 2. Practise (10 minutes)

- **Version B, three times with a timer, every bracket read.** Target 3:45 to 3:55 (B 572 words at about 150 a minute, demo included; B-UNCONFIRMED 586, A 574). The hard limit is 4:00, and the demo can add up to 5 seconds. If you run over, drop the optional demo first, then the `[if merged]` brackets, never the numbers. With nothing optional the script is 469 words, about 3:08.
- **"When it broke", twice on its own.** It is the beat judges remember. Say it flat, no apology tone: what stopped, what we missed, that the page stayed incomplete, the lesson ("an offer is worth nothing if nothing is listening"), what runs today. It is not a claim of why we lost the page. Never name the card, the page, the team or a price.
- **The version A paragraph, twice.** Practise it with "[card] for [price] primas" filled with something neutral (say "a rare for sixty primas") so the real numbers drop in at 14:50 without a stumble.
- **The 60-second fallback, once** (story section 4).
- **Six lines to say exactly as written** (each is the safe wording of something easy to overstate):
  - "Our ladder stopped at 84. No deal." (not "we walked away", not "his final was 90")
  - "Honestly, it beats chance, but not 'they'll do what they did last time'."
  - "Two other teams posted offers there. No trade between them settled." (only on plain B; on B-UNCONFIRMED: "our records and the public board don't agree yet, so we don't count one")
  - "Our idea lost: eleven standard errors on the hard test, and in simulations fitted to all five recorded sessions." (not "lost everywhere", not "on five real sessions": those five are simulations refit to each recorded session)
  - "No bot of ours even read them, and the page stayed incomplete." (not "we lost it because nothing was listening", not "the desk would have bought it", not "we fixed it that night")
  - The lab result sentence exactly as section 2a picks it, or nothing
- **Say aloud once:** "La Celestina", "seven hundred and twenty", "primas", "Bayes".

## 2a. The 07:00 fill (5 minutes)

Open the two 06:45 reports and fill the three `[07:00: ...]` brackets of the "Test before trust" beat, following story section 3a exactly:

- `docs/duel-lab/duels3-search/leaderboard.md` (branch `vm/wp10-duel-search`: `git show origin/vm/wp10-duel-search:docs/duel-lab/duels3-search/leaderboard.md`): the "Candidates scored" count (123 at 02:54 Madrid).
- `evals/broker-search/leaderboard.md` (branch `vm/wp11-broker-search`): the count of policies screened. At 03:10 this file did not exist yet; if it still does not, cut the broker half of the sentence.
- The result line: **no default**. Read each file's TEST verdict line and pick the matching wording from story section 3a: (a) none passed, (b) one passed and was deployed, (c) one passed but was not deployed before the 08:00 freeze. No TEST verdict line, or no file: no result sentence. Tell Hector which verdict line you used.

## 2b. The optional demo (practise once, 07:15)

Hector runs `python3 tools/pitch_numbers.py --live --stage` on the demo laptop after `git pull`. It prints within 5 seconds (it has a 5-second deadline; anything slower prints `unavailable`): a `VERSION` line (A, B-UNCONFIRMED or B) with its reason, the v20 leaderboard row, and five numbered lines (v20 trades between other teams; teams and offers posted on v20; public events, two recorder copies merged; ledger readings matching our cash; pull requests merged). `--stage` keeps every team id off the screen. You say: "These numbers are not slides. Hector?" and, when it prints: "These five verification figures come from our recorded data, computed now." Not "every figure in this talk". If it errors, hangs past 5 seconds or prints anything odd: Hector says "we'll skip that" and you read on. Never debug on stage. `factory.py plan` is not a demo: its command lines carry caps.

## 3. Three calls for you at 07:00

1. **Public swarm link (Tailscale Funnel), yes or no.** Public view on port 8778 only; the private view on 8777 is never exposed. Command and fallback: evidence, "Needs Thiago's yes".
2. **Dashboard tunnel for the La Celestina panel, yes or no.** The rest of that page carries our values; the public venue row says the same thing with no risk, so "no" costs little.
3. [Line removed after the event.]

v2's open decision still stands: "no model call on the money path" against the team's written "the model writes the words". v3 keeps v2's wording ("the AI does the work, the structure holds the money"; template lines Claude wrote). Tell Hector and a former teammate if you change it.

## 4. Seven anecdotes, with sources

Keep three in your head; use them for questions or if a screen fails. The first three are v2's, updated; the next three are from tonight; the seventh is the one now in the script.

1. **The ladder held (discipline).** El Chato, LAV-09, Saturday ticks 171 to 178. Our bids 60, 64, 68, 72, 76, 80, 84; his asks 97, 97, 97, 97, 96, 94, 90. Stopped at 84, no deal (`max_rounds`). His 90 was not marked final. Say "our ladder stopped at 84, he stayed at 90, no deal". Source: `logs/threads/thread-00335.json`; never show `logs/chato/2026-10-03.jsonl` (its first line carries our cap).
2. **Watching taught us to accept (learning).** Friday's practice duels were watch-only by design: 0 of 12 closed, and in all 8 where the rival named a price, its last offer was already inside our limit (`docs/analysis-friday/README.md` line 9). Saturday, live, after the overnight lab: Duels I 25 deals in 31 finished (`docs/findings.md`, Duels I section), Duels II 57 deals in 68 (`logs/duels/`, session 3). v2's "+11 % in simulation" is not needed any more: the live counts say it.
3. **Our own bot was the risk (honesty).** PR #11 merged the market desk with swaps on by default; a post-merge review flagged it; PR #12 made them opt-in, 18 minutes merge to merge (`mergedAt` 07:42:00Z and 07:59:57Z). Say "the fix merged in 18 minutes"; PR #12's title names our cash floor, so never show it.
4. **We killed our favourite idea (tonight, PR #65).** The bet: a broker that makes the most pairs each tick would beat the free stall's "best bid against best ask" in the Market Test. The decision rule was written before the runs. Result: worse by 11 standard errors on the hard test (2,000 seeds x 4 sessions), worse beyond noise in 42 of 48 simulated scenarios and in simulations fitted to each of the five recorded Saturday sessions. Only one recorded session (b36, where our broker matched nothing, so every quote path survived) can be replayed as it happened: 0.800 against the stall's 0.980. On the other four recorded books it would have sent exactly the stall's matches. A second candidate from an independent reviewer failed too. We run the stall's rule all day. Source: `docs/plans/market-test-sunday.md` (branch `feat/broker-maxpairs`, PR #65); the offline eval had already said "keep stall" (`evals/broker/narrative.md`).
5. **The 15-second bug the broker would have hit (tonight, PR #63).** Saturday's broker waited up to 5 s on a read and retried once: about 10.5 s blind on one bad read, plus a backoff of up to 5 s. Fine on 30 s ticks; on Sunday's 15 s ticks, a whole tick, and the hard Market Test's traders can stay a single tick. Saturday's lunch audit found it (`docs/analysis-saturday/market.md` section 7, "MEDIUM on Sunday") and it sat unmerged until tonight's sprint picked it up: 6 of 6 planted bugs caught by its tests. The lesson to say if asked: a finding that lives only in a document is not a fix.
6. **The referee was wrong, so we threw away a night's tuning (tonight, PR #54 and `evals/duels-arena/narrative.md`).** In duels with a delivery day, the server pays a seller for every delivery day from day 0. Our model did not, so it undervalued every seller offer by ten days' worth. Three of the server's own Duels II results showed it; the live bot was patched during Duels II. Concrete case from the test (a fixture, not one of our values): value 100, rival offers 110 at day 0, weight 3 a day; the old model said hold (110 - 100 - 30 = -20), the server's model says accept (+10). That changed what "a good seller deal" means, and the overnight parameter climb, tuned on the old referee, was marked superseded and not deployed. For Causa Prima this is price against time: the same trade as an early-payment discount.

7. **Nothing was listening (Saturday, now the "When it broke" beat).** The market desk's log ends at tick 266, Saturday 10:22:12 (`logs/market/2026-10-03.jsonl`); nobody restarted it. Between 12:36 and 19:29 one team addressed twelve offers of the card that would complete one of our pages to us (feed, ticks 533 to 1108): nine asking for a swap (for a card not in our holdings at the close), three for cash, the last at 67 P, below our own earlier bids of 68 and 73 (ticks 750, 758). None was accepted; the page stayed incomplete at the close (`logs/state/me.json`). **For Q&A: and our cash was short of the asks at the time** (rebuilt by `tools/ledger.py`), so the desk being off was not the only obstacle; never claim it was. Cash figures stay off stage. The factory that starts and watches our bots was built that afternoon (commit 4e3553b, 14:47) but left the desk out, off by default: the post-mortem is ownership, not tooling. **Internal only:** the card, the team and the prices never go on stage (story section 7).

Back pocket, if they want a dealer story: Abuela, LAT-08, her asks 29, 26, 24, 24, 23, 22, her final at 22 (`logs/threads/thread-00362.json`). Market story: our MAL-08 spare sold at 28 P on El Rastro in 3 ticks while another team's copy at 38 sat for 21 (`docs/analysis-friday/rastro.md` lines 50 and 56).
