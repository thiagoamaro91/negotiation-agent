"""Infer every team's secret set multipliers from the public feed. Offline, no key.

Every team gets the same six set multipliers (1.6, 1.3, 1.1, 0.9, 0.7, 0.5), shuffled (kit/RULES.md), so each team
is one of 720 permutations, and what it does in public is evidence about which one:
- it CHOOSES a set when it asks a dealer for a card of it, bids for one on a venue, or buys one from another team;
- it SHEDS a set when it sells a card of it (to a dealer, on a venue, or in a swap);
- a PRICE it paid or bid for a single card is a FLOOR on its value: multiplier >= price / book.
Choices and sheds are scored with a softmax over the sets in play (how strongly a team follows its values is
BETA_CHOOSE / BETA_SHED, re-tested by `check`), floors with a soft step, and Bayes does the rest. Only structure is read
(who, which card, how much): the words in the feed never reach this file.

    python3 tools/value_inference.py teams              # every team: expected multiplier per set, favourite, confidence
    python3 tools/value_inference.py team t13           # one team: its evidence tick by tick, and the posterior
    python3 tools/value_inference.py check              # does it work? Team 3's truth vs the inference, and a time-split test
    python3 tools/value_inference.py targets            # for us: who to sell our spares to, who holds the cards we need
    python3 tools/value_inference.py teams --json       # the same numbers as JSON (for a dashboard); targets --json too

`check` and `targets` read logs/state/me.json (our private values): the output stays on this machine and in our repo.
The catalog (book values, released sets) is a keyless public read, cached in logs/public/catalog.json.
BAZAAR_FEED=<dir> reads the feed from another clone (the one where tools/feed_recorder.py runs).
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = Path(os.environ.get("BAZAAR_FEED") or ROOT / "logs" / "feed")  # point it at the clone where the recorder runs
ME = ROOT / "logs" / "state" / "me.json"           # tools/snapshot.py (needs the key)
ME_LIVE = ROOT / "logs" / "state" / "me_live.json"  # pushed by tools/me_relay.py from the laptop that holds the key
CONVERSIONS = ROOT / "logs" / "state" / "conversions.json"  # Workshop conversions our bots logged (tools/brain.py keeps them)
PUBLIC = ROOT / "logs" / "public"   # cached keyless reads: catalog, schedule, dealers
URL = "https://bazaar.causaprima.ai"
US = "t03"

MULTS = (1.6, 1.3, 1.1, 0.9, 0.7, 0.5)
FLOOR_SHARPNESS = 12.0   # a floor 0.1 above a multiplier makes that multiplier ~3x less likely
FLOOR_NOISE = 0.10       # share of price floors that say nothing (overpaying to unlock a level, page bonus, a bad agent)
BETA_CHOOSE = 4.0        # how strongly a team's choices follow its multipliers (0 = not at all); `check` re-tests it
BETA_SHED = 0.5          # sheds say little (most are spare copies from packs); `check` slightly prefers 0, but a sold rare
                         # does say something a next-choice test cannot see
# Confidence label: the favourite's probability AND enough independent choices behind it. Choices of the same set weigh
# 1/k (see Model.weights), so a team that asked Abuela for five LAV cards has ~2.3 choice-equivalents, not five.
STRONG_P, STRONG_CHOICES = 0.6, 4.0
SOME_P, SOME_CHOICES = 0.4, 2.0
STRONG_SHOWN = False     # "strong" was right 25 % of the time (n=4): shown as "some" (the medium tier) until
                         # `check` (which keeps scoring the raw rule) shows otherwise
RELIABILITY_BINS = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0001)


# ---------------------------------------------------------------- data

def rows(name: str) -> list:
    path = FEED / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def public(name: str, refresh: bool = False) -> dict:
    """A keyless public read (/api/<name>), cached in logs/public/<name>.json; the cache is used if the server is unreachable."""
    path = PUBLIC / f"{name}.json"
    if refresh or not path.exists():
        try:
            with urllib.request.urlopen(f"{URL}/api/{name}", timeout=15) as r:
                data = json.load(r)
            PUBLIC.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            if not path.exists():
                raise
    return json.loads(path.read_text(encoding="utf-8"))


def catalog(refresh: bool = False) -> dict:
    return public("catalog", refresh)


def load_me() -> dict:
    """Our account (cash, cards, private multipliers): the freshest of the relayed copy and the last snapshot."""
    best = None
    for path in (ME_LIVE, ME):
        if path.exists():
            me = json.loads(path.read_text(encoding="utf-8"))
            if best is None or (me.get("tick") or 0) > (best.get("tick") or 0):
                best = me
    if best is None:
        raise SystemExit("no account snapshot: run tools/snapshot.py or tools/me_relay.py (both need the key)")
    try:
        convs = json.loads(CONVERSIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        convs = []
    later = [c for c in convs if isinstance(c, dict) and isinstance(c.get("tick"), int) and c["tick"] > (best.get("tick") or 0)]
    return {**best, "conversions": later} if later else best


def set_of(key: str) -> str:
    return key.split("-")[0].split(":")[0]


def card_types(side: dict) -> list:
    return [t.split(":", 1)[1] for t in side.get("types") or [] if t.startswith("card:")]


def evidence(events: list, book: dict) -> dict:
    """team -> [{tick, kind: choose|shed|floor, set, ref, price, how}], deduplicated: one choice or shed per
    (team, card), one floor per (team, card) at the highest price seen."""
    teams = {e["payload"]["team"] for e in events if e["type"] == "team.joined"}
    asset_ref = {}
    for e in events:  # asset id -> card ref, from every offer and settlement that shows one
        p = e["payload"]
        o = p.get("offer")
        if isinstance(o, dict):  # offer.cancelled carries only the id
            for side in (o.get("give") or {}, o.get("want") or {}):
                for a in side.get("assets") or []:
                    if isinstance(a, dict) and a.get("ref"):
                        asset_ref[a["id"]] = a["ref"]
        for i in p.get("items") or []:
            if i.get("ref"):
                asset_ref[i["id"]] = i["ref"]

    out = collections.defaultdict(list)
    seen = set()
    floors = {}
    known_sets = {set_of(r) for r in book}

    def add(team: str, kind: str, key: str, tick: int, how: str) -> None:
        if team not in teams or (team, kind, key) in seen or set_of(key) not in known_sets:
            return
        seen.add((team, kind, key))
        out[team].append({"tick": tick, "kind": kind, "set": set_of(key), "ref": key, "price": None, "how": how})

    def floor(team: str, ref: str, price, tick: int, how: str) -> None:
        if team not in teams or ref not in book or not price:
            return
        cur = floors.get((team, ref))
        if cur is None or price > cur["price"]:
            floors[(team, ref)] = {"tick": tick, "kind": "floor", "set": set_of(ref), "ref": ref, "price": price, "how": how}

    for e in events:
        p, t = e["payload"], e["tick"]
        if e["type"] == "thread.opened" and p.get("kind") == "persona":
            topic = p.get("topic") or {}
            buy, sell = topic.get("buy") or {}, topic.get("sell") or {}
            if buy.get("card"):
                add(p["team"], "choose", buy["card"], t, f"asked {p['with']} for it")
            elif buy.get("set"):
                add(p["team"], "choose", f"{buy['set']}:{buy.get('rarity', 'any')}", t, f"asked {p['with']} for any {buy.get('rarity', '')} of the set")
            for aid in sell.get("assets") or []:
                if aid in asset_ref:
                    add(p["team"], "shed", asset_ref[aid], t, f"offered it to {p['with']}")
        elif e["type"] == "thread.message" and p.get("kind") == "persona" and p.get("sender") == p.get("team"):
            o = p.get("offer") or {}
            wants = card_types(o.get("want") or {})
            if len(wants) == 1 and (o.get("give") or {}).get("cash") and not (o.get("give") or {}).get("assets"):
                floor(p["team"], wants[0], o["give"]["cash"], t, f"bid to {p['with']}")
        elif e["type"] == "offer.listed":
            o = p.get("offer") or {}
            maker, give, want = o.get("maker"), o.get("give") or {}, o.get("want") or {}
            wants = card_types(want) + [a.get("ref") for a in want.get("assets") or [] if isinstance(a, dict) and a.get("ref")]
            gives = [a.get("ref") for a in give.get("assets") or [] if isinstance(a, dict) and a.get("ref")]
            to = f" to {o['to']}" if o.get("to") else ""
            for ref in wants:
                add(maker, "choose", ref, t, f"asked for it on {o.get('venue')}{to}")
            for ref in gives:
                add(maker, "shed", ref, t, f"offered it on {o.get('venue')}{to}")
            if len(wants) == 1 and give.get("cash") and not gives:
                floor(maker, wants[0], give["cash"], t, f"bid on {o.get('venue')}{to}")
        elif e["type"] == "settlement":
            items = [i for i in p.get("items") or [] if i.get("kind") == "card"]
            single = len(p.get("items") or []) == 1
            for i in items:
                if p.get("persona"):  # the choice came with the thread topic; here only the price paid
                    if i.get("frm") == p["persona"] and single:
                        floor(i["to"], i["ref"], p.get("price"), t, f"paid {p['persona']}")
                    continue
                add(i.get("to"), "choose", i["ref"], t, f"bought it from {i.get('frm')}")
                add(i.get("frm"), "shed", i["ref"], t, f"sold it to {i.get('to')}")
                if single:
                    floor(i.get("to"), i["ref"], p.get("price"), t, f"paid {i.get('frm')}")
    for (team, _), f in floors.items():
        out[team].append(f)
    for team in teams:
        out[team].sort(key=lambda x: x["tick"])
    return {t: out[t] for t in sorted(teams)}


# ---------------------------------------------------------------- model

def choice_weight(evs: list) -> float:
    """Independent choice-equivalents in a team's evidence: the k-th choice of the same set counts 1/k."""
    return sum(w for ev, w in zip(evs, Model.weights(evs)) if ev["kind"] == "choose")


def confidence_label(p_favourite: float, choices: float, raw: bool = False) -> str:
    """'strong' needs a likely favourite AND enough independent choices behind it; few choices are never strong.
    While STRONG_SHOWN is off, a 'strong' is shown as 'some' (raw=True gives the rule's own label, for `check`)."""
    if p_favourite >= STRONG_P and choices >= STRONG_CHOICES:
        return "strong" if raw or STRONG_SHOWN else "some"
    if p_favourite >= SOME_P and choices >= SOME_CHOICES:
        return "some"
    return "weak"


def reliability(records: list, bins: tuple = RELIABILITY_BINS) -> list:
    """Prequential reliability table: records are (predicted probability, came true); one row per probability bin with
    how many predictions fell in it, their mean, and how often they came true."""
    out = []
    for lo, hi in zip(bins, bins[1:]):
        inside = [(p, ok) for p, ok in records if lo <= p < hi]
        out.append({"lo": lo, "hi": min(hi, 1.0), "n": len(inside),
                    "predicted": round(sum(p for p, _ in inside) / len(inside), 3) if inside else None,
                    "observed": round(sum(ok for _, ok in inside) / len(inside), 3) if inside else None})
    return out


def fit_shrink(preds: list, step: float = 0.05) -> tuple[float, float]:
    """The share of the model's confidence worth keeping: lam in [0, 1] minimising the out-of-sample log-loss of
    lam * prediction + (1 - lam) * uniform, over preds = [(predicted {set: p}, actual set)]. Returns (lam, loss)."""
    if not preds:
        return 1.0, 0.0
    best = None
    for i in range(int(round(1 / step)) + 1):
        lam = round(i * step, 4)
        loss = 0.0
        for pred, actual in preds:
            u = 1.0 / len(pred)
            loss += -math.log(max(lam * pred.get(actual, 0.0) + (1 - lam) * u, 1e-12))
        loss /= len(preds)
        if best is None or loss < best[1] - 1e-12:
            best = (lam, loss)
    return best


def shrink(dist: dict, lam: float) -> dict:
    """A multiplier distribution pulled toward the uniform prior: keep `lam` of the model's confidence."""
    u = 1.0 / len(dist) if dist else 0.0
    return {m: lam * p + (1 - lam) * u for m, p in dist.items()}


class Model:
    """Uniform prior over the 720 permutations; evidence multiplies in.

    Choices and sheds are a softmax over the sets in play (released, plus any set seen in the feed). The k-th choice
    (or shed) of the same set by the same team weighs 1/k: a team that goes for one page asks for card after card
    of it, and those are not independent votes. Floors weigh 1 (there is one per card already)."""

    def __init__(self, sets: list, in_play: list, book: dict, beta_choose: float = BETA_CHOOSE, beta_shed: float = BETA_SHED):
        self.sets, self.in_play, self.book = sets, in_play, book
        self.perms = [dict(zip(sets, p)) for p in itertools.permutations(MULTS)]
        self.beta_choose, self.beta_shed = beta_choose, beta_shed
        self._z = {}
        self._top = [max(in_play, key=lambda s: p[s]) for p in self.perms]  # each permutation's favourite set in play

    def p_top(self, post: list) -> dict:
        """P(set s is the team's highest multiplier among the sets in play)."""
        out = dict.fromkeys(self.in_play, 0.0)
        for w, s in zip(post, self._top):
            out[s] += w
        return out

    def _logz(self, i: int, beta: float) -> float:
        if (i, beta) not in self._z:
            self._z[(i, beta)] = math.log(sum(math.exp(beta * self.perms[i][s]) for s in self.in_play))
        return self._z[(i, beta)]

    def loglik(self, ev: dict, i: int) -> float:
        m = self.perms[i][ev["set"]]
        if ev["kind"] == "choose":
            return self.beta_choose * m - self._logz(i, self.beta_choose)
        if ev["kind"] == "shed":
            return -self.beta_shed * m - self._logz(i, -self.beta_shed)
        x = FLOOR_SHARPNESS * (m - ev["price"] / self.book[ev["ref"]])
        return math.log(FLOOR_NOISE + (1 - FLOOR_NOISE) / (1 + math.exp(-x)))

    @staticmethod
    def weights(evs: list) -> list:
        k = collections.Counter()
        out = []
        for ev in evs:
            if ev["kind"] == "floor":
                out.append(1.0)
                continue
            k[(ev["kind"], ev["set"])] += 1
            out.append(1.0 / k[(ev["kind"], ev["set"])])
        return out

    def _normalise(self, logp: list) -> list:
        top = max(logp)
        w = [math.exp(x - top) for x in logp]
        z = sum(w)
        return [x / z for x in w]

    def posterior(self, evs: list) -> list:
        logp = [0.0] * len(self.perms)
        for ev, w in zip(evs, self.weights(evs)):
            for i in range(len(self.perms)):
                logp[i] += w * self.loglik(ev, i)
        return self._normalise(logp)

    def predict_choice(self, post: list) -> dict:
        """P(the team's next choice is in set s), averaged over the posterior."""
        out = collections.Counter()
        for w, i in zip(post, range(len(self.perms))):
            z = math.exp(self._logz(i, self.beta_choose))
            for s in self.in_play:
                out[s] += w * math.exp(self.beta_choose * self.perms[i][s]) / z
        return dict(out)

    def time_split(self, by_team: dict) -> dict:
        """Predict every choice from the evidence of earlier ticks only, one team at a time (prequential), and score it:
        hit rate and log-loss against two baselines (chance, and 'repeat the team's most frequent past choice'), a
        reliability table (predicted probability of the top pick vs how often it came true), how often the next choice
        was the favourite under each confidence label, and the share of confidence worth keeping (`shrink`)."""
        n = hits = naive_hits = 0
        loss = 0.0
        top_records, preds = [], []
        by_label = collections.defaultdict(lambda: [0, 0])
        for evs in by_team.values():
            logp = [0.0] * len(self.perms)
            weights = self.weights(evs)
            past = collections.Counter()
            choices = 0.0
            ticks = sorted({ev["tick"] for ev in evs})
            for tick in ticks:
                now = [(ev, w) for ev, w in zip(evs, weights) if ev["tick"] == tick]
                pred = label = fav = None
                for ev, _ in now:
                    if ev["kind"] != "choose":
                        continue
                    if pred is None:
                        post = self._normalise(logp)
                        pred = self.predict_choice(post)
                        top = self.p_top(post)
                        fav = max(top, key=top.get)
                        flat = top[fav] <= 1.0 / len(self.in_play) + 0.01  # no favourite yet (ties go to the first set)
                        label = "no evidence" if flat else confidence_label(top[fav], choices, raw=True)
                    n += 1
                    pick = max(pred, key=pred.get)
                    hits += pick == ev["set"]
                    naive_hits += bool(past) and past.most_common(1)[0][0] == ev["set"]
                    loss += -math.log(max(pred[ev["set"]], 1e-12))
                    top_records.append((pred[pick], pick == ev["set"]))
                    preds.append((pred, ev["set"]))
                    by_label[label][0] += 1
                    by_label[label][1] += fav == ev["set"]
                for ev, w in now:
                    for i in range(len(self.perms)):
                        logp[i] += w * self.loglik(ev, i)
                    if ev["kind"] == "choose":
                        past[ev["set"]] += 1
                        choices += w
        lam, lam_loss = fit_shrink(preds)
        return {"n": n, "hit": hits / n if n else 0, "naive_hit": naive_hits / n if n else 0,
                "loss": loss / n if n else 0, "uniform_loss": math.log(len(self.in_play)),
                "reliability": reliability(top_records),
                "by_label": {k: {"n": v[0], "favourite_next": round(v[1] / v[0], 3) if v[0] else None}
                             for k, v in sorted(by_label.items())},
                "shrink": lam, "shrunk_loss": lam_loss}

    def summary(self, post: list, evs: list | None = None) -> dict:
        """Expected multiplier and distribution per set, favourite and least liked; the confidence label also needs the
        evidence behind the posterior (`evs`): without it the label is 'weak'."""
        exp = {s: sum(w * p[s] for w, p in zip(post, self.perms)) for s in self.sets}
        dist = {s: {m: sum(w for w, p in zip(post, self.perms) if p[s] == m) for m in MULTS} for s in self.sets}
        best = self.p_top(post)
        worst = {s: sum(w for w, p in zip(post, self.perms) if p[s] == min(p[r] for r in self.in_play)) for s in self.in_play}
        fav = max(best, key=best.get)
        least = max(worst, key=worst.get)
        choices = choice_weight(evs or [])
        return {"expected": exp, "dist": dist, "favourite": fav, "p_favourite": best[fav],
                "least": least, "p_least": worst[least], "choices": round(choices, 2), "n_evidence": len(evs or []),
                "confidence": confidence_label(best[fav], choices)}


def load(beta_choose: float = BETA_CHOOSE, beta_shed: float = BETA_SHED) -> tuple:
    cat = catalog()
    book = {c["id"]: c["book"] for s in cat["sets"] for c in s["cards"]}
    sets = [s["id"] for s in cat["sets"]]
    events = rows("feed.jsonl")
    if not events:
        raise SystemExit("logs/feed/feed.jsonl is empty: run tools/feed_recorder.py first.")
    by_team = evidence(events, book)
    seen = {ev["set"] for evs in by_team.values() for ev in evs}
    in_play = [s["id"] for s in cat["sets"] if s.get("released") or s["id"] in seen]
    return Model(sets, in_play, book, beta_choose, beta_shed), by_team, events, book


# ---------------------------------------------------------------- commands

def counts(evs: list) -> str:
    c = collections.Counter(ev["kind"] for ev in evs)
    return f"{c['choose']:2}c {c['shed']:2}s {c['floor']:2}f"


def cmd_teams(args) -> None:
    model, by_team, events, _ = load()
    res = {t: model.summary(model.posterior(evs), evs) for t, evs in by_team.items()}
    if args.json:
        print(json.dumps({"tick": events[-1]["tick"], "beta_choose": model.beta_choose, "beta_shed": model.beta_shed,
                          "in_play": model.in_play,
                          "teams": {t: {**r, "evidence": by_team[t]} for t, r in res.items()}}, indent=1, default=str))
        return
    print(f"feed up to tick {events[-1]['tick']}; beta_choose={model.beta_choose} beta_shed={model.beta_shed}; "
          f"sets in play {', '.join(model.in_play)}")
    print("expected multiplier per set (1.02 with no evidence); c/s/f = choices, sheds, price floors")
    print(f"confidence: strong = favourite >= {STRONG_P:.0%} on >= {STRONG_CHOICES:g} choice-equivalents, "
          f"some = >= {SOME_P:.0%} on >= {SOME_CHOICES:g} (the k-th choice of a set counts 1/k)")
    print(f"{'team':5} {'evidence':12} " + " ".join(f"{s:>5}" for s in model.in_play) + "   favourite   least liked   choices confidence")
    for t, r in res.items():
        e = r["expected"]
        print(f"{t:5} {counts(by_team[t]):12} " + " ".join(f"{e[s]:5.2f}" for s in model.in_play)
              + f"   {r['favourite']} {r['p_favourite']:4.0%}    {r['least']} {r['p_least']:4.0%}      {r['choices']:5.1f}  {r['confidence']}")


def cmd_team(args) -> None:
    model, by_team, _, _ = load()
    evs = by_team.get(args.team)
    if evs is None:
        raise SystemExit(f"no team {args.team}")
    for ev, w in zip(evs, model.weights(evs)):
        price = f" at {ev['price']} P (floor {ev['price'] / model.book[ev['ref']]:.2f})" if ev["price"] else ""
        weight = "" if w == 1 else f"  [weight {w:.2f}]"
        print(f"  tick {ev['tick']:>3} {ev['kind']:6} {ev['ref']:13} {ev['how']}{price}{weight}")
    r = model.summary(model.posterior(evs), evs)
    print(f"\n{args.team}: favourite {r['favourite']} ({r['p_favourite']:.0%}), least liked {r['least']} ({r['p_least']:.0%}), {r['confidence']}")
    for s in model.sets:
        d = " ".join(f"{m}:{r['dist'][s][m]:4.0%}" for m in MULTS)
        print(f"  {s} E={r['expected'][s]:.2f} | {d}" + ("" if s in model.in_play else "  (not in play: only by elimination)"))


def cmd_check(args) -> None:
    model, by_team, _, _ = load()
    # 1) our own truth, never used by the inference
    if ME.exists() or ME_LIVE.exists():
        truth = load_me()["affinity"]
        r = model.summary(model.posterior(by_team.get(US, [])), by_team.get(US, []))
        print(f"1) Team 3, whose real multipliers we know ({counts(by_team.get(US, []))}):")
        for s in model.in_play:
            print(f"   {s}: inferred {r['expected'][s]:.2f}  true {truth[s]}")
        shown = [s for s in model.in_play if by_team.get(US) and any(ev["set"] == s for ev in by_team[US])] or model.in_play
        inf_rank = sorted(shown, key=lambda s: -r["expected"][s])
        true_rank = sorted(shown, key=lambda s: -truth[s])
        print(f"   order of the sets we touched: inferred {' > '.join(inf_rank)} | true {' > '.join(true_rank)}")
    # 2) time split: predict each choice from earlier ticks only, for a few settings of the two betas
    print("\n2) time split: every choice predicted only from that team's earlier evidence")
    print(f"   {'beta_choose':>11} {'beta_shed':>9} {'top pick right':>15} {'log-loss':>9}")
    for bc in (2.0, 3.0, 4.0, 5.0):
        for bs in (0.0, 0.5, 1.0):
            r = Model(model.sets, model.in_play, model.book, bc, bs).time_split(by_team)
            mark = "  <- in use" if (bc, bs) == (BETA_CHOOSE, BETA_SHED) else ""
            print(f"   {bc:11} {bs:9} {r['hit']:15.0%} {r['loss']:9.3f}{mark}")
    print(f"   baselines over {r['n']} choices: chance {1 / len(model.in_play):.0%} (log-loss {r['uniform_loss']:.3f}); "
          f"'same set as its most frequent past choice' {r['naive_hit']:.0%}")
    # 3) reliability of the setting in use: when the model said p, how often was its top pick right?
    r = model.time_split(by_team)
    print(f"\n3) reliability (betas in use): top pick right {r['hit']:.1%} vs 'repeat its favourite' {r['naive_hit']:.1%}, "
          f"n={r['n']}; keeping {r['shrink']:.0%} of the confidence minimises the log-loss ({r['shrunk_loss']:.3f})")
    print(f"   {'predicted':>11} {'n':>4} {'mean p':>7} {'right':>6}")
    for b in r["reliability"]:
        if b["n"]:
            print(f"   {b['lo']:4.0%}-{b['hi']:4.0%} {b['n']:4} {b['predicted']:7.0%} {b['observed']:6.0%}")
    print("   label at the time -> next choice was the favourite: "
          + ", ".join(f"{k} {v['favourite_next']:.0%} (n={v['n']})" for k, v in r["by_label"].items()))


def holdings(events: list, teams: set) -> dict:
    """team -> Counter(ref) of what the public record says it holds now (pack pulls are invisible until shown)."""
    owner = {}
    gifts = collections.defaultdict(collections.Counter)
    for e in events:
        p = e["payload"]
        if e["type"] == "offer.listed":
            o = p.get("offer") or {}
            for a in (o.get("give") or {}).get("assets") or []:
                if isinstance(a, dict) and a.get("ref"):
                    owner[a["id"]] = (o.get("maker"), a["ref"])
        elif e["type"] == "settlement":
            for i in p.get("items") or []:
                if i.get("kind") == "card":
                    owner[i["id"]] = (i.get("to"), i["ref"])
        elif e["type"] == "gift.given":
            for ref in p.get("cards") or []:
                gifts[p["team"]][ref] += 1
    out = collections.defaultdict(collections.Counter)
    for team, ref in owner.values():
        if team in teams:
            out[team][ref] += 1
    for team, c in gifts.items():
        for ref, k in c.items():
            out[team][ref] = max(out[team][ref], k)
    return out


CRAFT_SLACK = 2   # ticks between a logged conversion and the feed's taller.crafted event for it


def our_cards(me: dict, events: list) -> collections.Counter:
    """Our cards, copy by copy: the last snapshot (logs/state/me.json) by asset id, then in feed order our public
    settlements, gifts and easter eggs after it, and the Workshop conversions attached to the account (`conversions`:
    [{tick, burned: [{id, ref}], got: [{id, ref}]}]). A conversion is applied at our own taller.crafted event (the
    moment of the craft, after a purchase earlier in the same tick), or once the feed is past its tick if that event
    never shows; a burned copy we only know by name (a gift, no id) is taken from those."""
    since = me.get("tick", 0)
    held = {a["id"]: a["ref"] for a in me["assets"] if a.get("kind") == "card"}
    loose = collections.Counter()  # copies we got without an id (gifts, eggs) and have not seen leave
    pending = sorted((c for c in me.get("conversions") or [] if c.get("tick", 0) > since), key=lambda c: c["tick"])

    def leave(aid, ref) -> None:
        if aid in held:
            del held[aid]
        elif loose[ref] > 0:
            loose[ref] -= 1
        else:  # no id to match: drop any copy of that card
            other = next((k for k, r in held.items() if r == ref), None)
            if other is not None:
                del held[other]

    def convert(c: dict) -> None:
        for b in c.get("burned") or []:
            aid, ref = (b.get("id"), b.get("ref")) if isinstance(b, dict) else (b, None)
            if aid in held:
                del held[aid]
            elif ref and loose[ref] > 0:
                loose[ref] -= 1
        for g in c.get("got") or []:
            held[g["id"]] = g["ref"]

    for e in events:
        if e["tick"] <= since:
            continue
        while pending and pending[0]["tick"] + CRAFT_SLACK < e["tick"]:  # its craft event never showed: apply now
            convert(pending.pop(0))
        p = e["payload"]
        if e["type"] == "taller.crafted" and p.get("team") == US:
            if pending and pending[0]["tick"] - CRAFT_SLACK <= e["tick"]:
                convert(pending.pop(0))
        elif e["type"] == "settlement":
            for i in p.get("items") or []:
                if i.get("kind") != "card":
                    continue
                if i.get("frm") == US:
                    leave(i.get("id"), i["ref"])
                if i.get("to") == US:
                    held[i["id"] if i.get("id") is not None else object()] = i["ref"]
        elif e["type"] in ("gift.given", "egg.given") and p.get("team") == US:
            for ref in p.get("cards") or []:
                loose[ref] += 1
    for c in pending:
        convert(c)
    return collections.Counter(held.values()) + loose


def wanted(by_team: dict) -> dict:
    """card ref -> {team: highest price it ever bid or paid (None if it only asked)}. History, not the live board:
    a bid may have been cancelled since (tools/market_plan.py reads the live board)."""
    out = collections.defaultdict(dict)
    for team, evs in by_team.items():
        for ev in evs:
            if ev["kind"] == "choose" and "-" in ev["ref"]:
                out[ev["ref"]].setdefault(team, None)
            if ev["kind"] == "floor":
                out[ev["ref"]][team] = max(ev["price"], out[ev["ref"]].get(team) or 0)
    return out


def targets(min_gap: float = 5.0, n: int = 12) -> dict:
    """What to sell and to whom, what to buy and from whom, as data."""
    model, by_team, events, book = load()
    me = load_me()
    ours = me["affinity"]
    teams = set(by_team) - {US}
    res = {t: model.summary(model.posterior(by_team[t]), by_team[t]) for t in teams}
    held = holdings(events, set(by_team))
    want = wanted(by_team)
    mine = our_cards(me, events)

    sell = []
    for ref, k in mine.items():
        if k <= 0 or ref not in book:
            continue
        b, s = book[ref], set_of(ref)
        ourv = b * ours[s] * (0.25 if k > 1 else 1.0)
        cand = [t for t in teams if held[t][ref] == 0]
        cand.sort(key=lambda t: (t not in want.get(ref, {}), -res[t]["expected"][s]))
        buyers = [{"team": t, "value": round(b * res[t]["expected"][s], 1), "asked": t in want.get(ref, {})} for t in cand[:3]]
        best = max((b * res[t]["expected"][s] for t in cand), default=0)
        if best - ourv >= min_gap:
            sell.append({"ref": ref, "copy": "spare" if k > 1 else "first", "ours": round(ourv, 1),
                         "best": round(best, 1), "gain": round(best - ourv, 1), "buyers": buyers})
    sell.sort(key=lambda x: -x["gain"])

    buy = []
    lacking = [ref for ref in book if set_of(ref) in model.in_play and mine[ref] <= 0 and int(ref.split("-")[1]) <= 10]
    lacking.sort(key=lambda r: -book[r] * ours[set_of(r)])
    for ref in lacking[:n]:
        b, s = book[ref], set_of(ref)
        holders = [t for t in teams if held[t][ref] > 0]
        holders.sort(key=lambda t: res[t]["expected"][s] * (0.25 if held[t][ref] > 1 else 1.0))
        buy.append({"ref": ref, "ours": round(b * ours[s], 1),
                    "holders": [{"team": t, "value": round(b * res[t]["expected"][s] * (0.25 if held[t][ref] > 1 else 1.0), 1),
                                 "spare": held[t][ref] > 1} for t in holders],
                    "rivals": [{"team": t, "bid": v} for t, v in sorted(want.get(ref, {}).items(), key=lambda x: -(x[1] or 0))
                               if t not in set(holders) | {US}]})
    return {"me_tick": me.get("tick"), "feed_tick": events[-1]["tick"], "affinity": ours, "sell": sell, "buy": buy}


def cmd_targets(args) -> None:
    r = targets(args.min_gap, args.n)
    if args.json:
        print(json.dumps(r, indent=1))
        return
    print(f"our holdings: logs/state/me.json (tick {r['me_tick']}) plus our public settlements up to tick {r['feed_tick']}; "
          "others' holdings: public record only (pack pulls are invisible)")
    print("\nSELL: every card we hold, ranked by how much more it is likely worth to another team than to us")
    print("      (trades score at private values: that gap is the points). Teams that asked for the card come first;")
    print("      teams known to hold it already are skipped (a second copy is worth 25% to them). Page bonus not included.")
    for x in r["sell"]:
        top = ", ".join(f"{b['team']} ~{b['value']:.0f} P" + (" (asked for it)" if b["asked"] else "") for b in x["buyers"])
        print(f"  {x['ref']:7} {x['copy']:5} worth {x['ours']:5.1f} P to us, up to ~{x['best']:.0f} P to a buyer (+{x['gain']:.0f}) -> {top}")
    print("\nBUY: cards we lack, who is known to hold them (and what it is likely worth to the holder), and who else wants it")
    for x in r["buy"]:
        held_by = ", ".join(f"{h['team']} ~{h['value']:.0f} P" + (" (has a spare)" if h["spare"] else "") for h in x["holders"])
        rivals = ", ".join(f"{v['team']}" + (f" bid up to {v['bid']} P at some point" if v["bid"] else " (asked)") for v in x["rivals"])
        print(f"  {x['ref']:7} worth {x['ours']:5.1f} P to us -> held by {held_by or 'no holder in the public record'}"
              + (f" | also wanted by {rivals}" if rivals else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description="Infer each team's secret set multipliers from the public feed.")
    ap.add_argument("--refresh-catalog", action="store_true", help="re-read /api/catalog (public, no key)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("teams")
    t.add_argument("--json", action="store_true")
    one = sub.add_parser("team")
    one.add_argument("team")
    sub.add_parser("check")
    g = sub.add_parser("targets")
    g.add_argument("-n", type=int, default=12, help="how many missing cards to list")
    g.add_argument("--min-gap", type=float, default=5.0, help="only list cards worth at least this much more to a buyer")
    g.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.refresh_catalog:
        catalog(refresh=True)
    {"teams": cmd_teams, "team": cmd_team, "check": cmd_check, "targets": cmd_targets}[args.cmd](args)


if __name__ == "__main__":
    main()
