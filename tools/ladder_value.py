"""What a dealer-ladder deal is worth in board points, measured from the public feed. Offline, no key.

For every dealer settlement of the round (default: Saturday, ticks 160 to 1445) it takes the change in the team's
`negotiating` between the leaderboard snapshot before and the one that contains the settlement, and keeps it only
when the change can be attributed to that deal:

- a settlement at tick T shows up in the snapshot interval (a, b] with a < T <= b;
- the board moves for everybody at once (the day's weight grows into it): the change is negotiating(b) - k * negotiating(a),
  k being the median ratio b/a of the teams that had no event in the interval;
- an interval is dropped if any duel result closed in it (the public duel.closed names no team: the rival is an NPC),
  and for a deal to count as `single` the team must have no other event in it (team trade, second dealer deal, pack,
  Workshop, gift, egg, badge). A `group` is an interval whose only events are dealer deals of one level, all in the best
  three of that dealer for the team or all after them: its change divided by its deals is one pooled estimate.

    python3 tools/ladder_value.py table       # table 1 (single deals by level and rank) and table 2 (pooled groups)
    python3 tools/ladder_value.py level5      # the Ernesto deals, with the team's row before and after
    python3 tools/ladder_value.py pages       # deals that changed a team's page count, dealer against team trade
    python3 tools/ladder_value.py noise       # the change of teams with no event at all (how small is nothing)

Results and what they mean: docs/plans/ladder-sunday.md. BAZAAR_FEED=<dir> reads another clone's feed.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import os
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = Path(os.environ.get("BAZAAR_FEED") or ROOT / "logs" / "feed")
LEVEL = {"abuela": 1, "chato": 2, "pilar": 3, "picaros": 4, "banco": 5}
NAME = {1: "1 Abuela", 2: "2 Chato", 3: "3 Pilar", 4: "4 Picaros", 5: "5 Ernesto"}
OTHER = ("pack.opened", "taller.crafted", "gift.given", "egg.given", "egg.found", "badge.awarded")


def rows(name: str) -> list:
    path = FEED / name
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def quantile(xs: list, p: float):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


class Data:
    def __init__(self, first: int = 160, last: int = 1445):
        by_id = {}
        for e in rows("feed.jsonl"):
            by_id[e["id"]] = e
        self.events = sorted(by_id.values(), key=lambda e: (e["tick"], e["id"]))
        snaps = {}
        for s in rows("snapshots.jsonl"):
            if s.get("what") == "leaderboard":
                snaps[s["body"]["tick"]] = {t["team"]: t for t in s["body"]["teams"]}
        self.snaps = snaps
        self.ticks = [t for t in sorted(snaps) if first <= t <= last]
        self.first, self.last = first, last
        self.duel = sorted(e["tick"] for e in self.events if e["type"] == "duel.closed")
        self.team_events = []   # (tick, team, kind, event)
        for e in self.events:
            p = e["payload"]
            if e["type"] == "settlement":
                for party in p["parties"]:
                    if party[:1] == "t" and party[1:].isdigit():
                        self.team_events.append((e["tick"], party, "settle", e))
            elif e["type"] in OTHER and p.get("team"):
                self.team_events.append((e["tick"], p["team"], e["type"], e))
        self.intervals = self._intervals()

    def _intervals(self) -> list:
        out = []
        for a, b in zip(self.ticks, self.ticks[1:]):
            busy = {tm for (t, tm, _, _) in self.team_events if a < t <= b}
            ratios = [self.snaps[b][tm]["negotiating"] / self.snaps[a][tm]["negotiating"] for tm in self.snaps[a]
                      if tm not in busy and tm in self.snaps[b] and self.snaps[a][tm]["negotiating"] > 1]
            out.append({"a": a, "b": b, "k": statistics.median(ratios) if len(ratios) >= 4 else None,
                        "duel": any(a < t <= b for t in self.duel), "busy": busy})
        return out

    def change(self, team: str, i: int):
        iv = self.intervals[i]
        a, b = iv["a"], iv["b"]
        if iv["k"] is None or team not in self.snaps[a] or team not in self.snaps[b]:
            return None
        return self.snaps[b][team]["negotiating"] - iv["k"] * self.snaps[a][team]["negotiating"]

    def deals(self) -> list:
        """One row per dealer settlement of the round: team, dealer level, rank for that team and dealer, side, price,
        items, the attributable change (None if the interval has no usable k) and the flags."""
        rank = collections.Counter()
        out = []
        dealer = [x for x in self.team_events if x[2] == "settle" and x[3]["payload"].get("persona")]
        for (T, tm, _, e) in sorted(dealer, key=lambda x: (x[0], x[3]["id"])):
            if T < self.first or T > self.last:
                continue
            p = e["payload"]
            pers = p["persona"]
            rank[(tm, pers)] += 1
            i = bisect.bisect_left(self.ticks, T) - 1
            row = {"T": T, "team": tm, "persona": pers, "level": LEVEL[pers], "rank": rank[(tm, pers)],
                   "price": p["price"], "side": "buy" if p["items"][0].get("frm") == pers else "sell",
                   "items": [(x.get("ref"), x.get("rarity"), x.get("kind")) for x in p["items"]],
                   "change": None, "single": False, "duel": None, "events": None, "i": i}
            if 0 <= i < len(self.intervals):
                iv = self.intervals[i]
                a, b = iv["a"], iv["b"]
                row["events"] = sum(1 for (t, tm2, _, _) in self.team_events if tm2 == tm and a < t <= b)
                row["duel"] = iv["duel"]
                row["change"] = self.change(tm, i)
                row["single"] = row["change"] is not None and row["events"] == 1 and not iv["duel"]
            out.append(row)
        return out

    def groups(self, deals: list) -> list:
        by = collections.defaultdict(list)
        for r in deals:
            if r["change"] is not None and not r["duel"]:
                by[(r["team"], r["i"])].append(r)
        out = []
        for rs in by.values():
            if rs[0]["events"] != len(rs) or len({r["level"] for r in rs}) != 1:
                continue
            kinds = {"top3" if r["rank"] <= 3 else "extra" for r in rs}
            if len(kinds) == 1:
                out.append({"level": rs[0]["level"], "kind": kinds.pop(), "n": len(rs),
                            "per_deal": rs[0]["change"] / len(rs), "rows": rs})
        return out


def cmd_table(d: Data, _args) -> None:
    deals = d.deals()
    usable = [r for r in deals if r["change"] is not None]
    print(f"{len(deals)} dealer settlements, ticks {d.first} to {d.last}; {len(usable)} with a usable interval: "
          f"{sum(1 for r in usable if r['duel'])} in an interval with a duel result, "
          f"{sum(1 for r in usable if not r['duel'] and not r['single'])} with another event of the team, "
          f"{sum(1 for r in usable if r['single'])} single deals")
    print("\ntable 1: change per single deal, by level and the deal's rank for the team (flat = under 0.15)")
    print(f"{'level':10} {'rank':5} {'n':>3} {'median':>7} {'q25':>6} {'q75':>6} {'min':>6} {'max':>6}  flat")
    for level in range(1, 6):
        for rk, lab in ((1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th+")):
            xs = [r["change"] for r in deals if r["single"] and r["level"] == level
                  and (r["rank"] == rk if rk < 4 else r["rank"] >= 4)]
            if xs:
                print(f"{NAME[level] if rk == 1 else '':10} {lab:5} {len(xs):3d} {statistics.median(xs):7.2f} "
                      f"{quantile(xs, .25):6.2f} {quantile(xs, .75):6.2f} {min(xs):6.2f} {max(xs):6.2f}  "
                      f"{sum(1 for x in xs if x < 0.15)}/{len(xs)}")
    groups = d.groups(deals)
    print("\ntable 2: pooled groups (intervals whose only events are dealer deals of one level, all top three or all later)")
    print(f"{'level':10} {'kind':6} {'deals':>5} {'median':>7} {'q25':>6} {'q75':>6}")
    for level in range(1, 6):
        for kind in ("top3", "extra"):
            xs = [g["per_deal"] for g in groups if g["level"] == level and g["kind"] == kind]
            if xs:
                print(f"{NAME[level]:10} {kind:6} {sum(g['n'] for g in groups if g['level'] == level and g['kind'] == kind):5d} "
                      f"{statistics.median(xs):7.2f} {quantile(xs, .25):6.2f} {quantile(xs, .75):6.2f}")
    extra = [g for g in groups if g["kind"] == "extra"]
    print(f"\nlater deals worth more than 0.3 each: {sum(1 for g in extra if g['per_deal'] > 0.3)} of {len(extra)}")


def cmd_level5(d: Data, _args) -> None:
    for r in d.deals():
        if r["level"] != 5:
            continue
        iv = d.intervals[r["i"]]
        before, after = d.snaps[iv["a"]][r["team"]], d.snaps[iv["b"]][r["team"]]
        print(f"tick {r['T']} {r['team']} {r['side']} {r['items'][0][0]} at {r['price']}: change {r['change']:+.2f} "
              f"(negotiating {before['negotiating']} -> {after['negotiating']}, k {iv['k']:.3f}), "
              f"{'single' if r['single'] else 'not single'}, rank {r['rank']}")


def cmd_pages(d: Data, _args) -> None:
    pages = lambda i, tm, key: d.snaps[d.intervals[i][key]][tm]["pages_complete"]   # noqa: E731
    print("single deals that changed the team's page count: dealer, then team trades")
    for r in d.deals():
        if r["single"] and pages(r["i"], r["team"], "a") != pages(r["i"], r["team"], "b"):
            print(f"  tick {r['T']} {r['team']} {r['persona']} {r['side']} {r['items'][0][0]} at {r['price']}: "
                  f"pages {pages(r['i'], r['team'], 'a')} -> {pages(r['i'], r['team'], 'b')}, change {r['change']:+.2f}")
    for (T, tm, kind, e) in d.team_events:
        p = e["payload"]
        if kind != "settle" or p.get("persona") or not d.first <= T <= d.last:
            continue
        i = bisect.bisect_left(d.ticks, T) - 1
        if i < 0 or i >= len(d.intervals) or d.intervals[i]["duel"]:
            continue
        a, b = d.intervals[i]["a"], d.intervals[i]["b"]
        if sum(1 for (t2, tm2, _, _) in d.team_events if tm2 == tm and a < t2 <= b) != 1:
            continue
        ch = d.change(tm, i)
        if ch is not None and pages(i, tm, "a") != pages(i, tm, "b"):
            print(f"  tick {T} {tm} TEAM TRADE {[x['ref'] for x in p['items']]} at {p['price']}: "
                  f"pages {pages(i, tm, 'a')} -> {pages(i, tm, 'b')}, change {ch:+.2f}")


def cmd_noise(d: Data, _args) -> None:
    xs = []
    for i, iv in enumerate(d.intervals):
        if iv["duel"] or iv["k"] is None:
            continue
        for tm in d.snaps[iv["a"]]:
            if tm not in iv["busy"] and d.snaps[iv["a"]][tm]["negotiating"] > 1:
                ch = d.change(tm, i)
                if ch is not None:
                    xs.append(ch)
    print(f"{len(xs)} team-intervals with no event: median {statistics.median(xs):.3f}, q05 {quantile(xs, .05):.2f}, "
          f"q25 {quantile(xs, .25):.2f}, q75 {quantile(xs, .75):.2f}, q95 {quantile(xs, .95):.2f}, "
          f"within 0.05: {sum(1 for x in xs if abs(x) < 0.05) / len(xs):.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["table", "level5", "pages", "noise"])
    ap.add_argument("--first", type=int, default=160)
    ap.add_argument("--last", type=int, default=1445)
    args = ap.parse_args()
    d = Data(args.first, args.last)
    {"table": cmd_table, "level5": cmd_level5, "pages": cmd_pages, "noise": cmd_noise}[args.cmd](d, args)


if __name__ == "__main__":
    main()
