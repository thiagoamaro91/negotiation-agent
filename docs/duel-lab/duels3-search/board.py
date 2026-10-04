"""Leaderboard for the Duels III overnight search: reads results.jsonl (+ gates.json), writes leaderboard.md."""
from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "leaderboard.md"
GATES = HERE / "gates.json"
D1_MAX_LOSS = 0.03

RULE = """**Acceptance rule.** A candidate replaces the incumbent (`docs/duel-lab/duel-params-duels3.json`) only if,
on the TEST seeds (900000..): (1) it beats the incumbent in the main world (Duels III, Duels II field refit plus
self-play) by more than 2 SE of the paired per-session difference; (2) it is not worse than the incumbent by more
than 2 SE against any rival type, both in `tools/duel_matrix.py --session 3` (17 rival rows) and in our own
per-type split of the main world (which adds the self-play rival); (3) in the D-1 stress (an accept sent with one
tick left never settles, 15 s ticks) its mean is no more than 0.03 below the incumbent's; (4)
`python3 agent/duel.py selftest --params <file>` passes. Otherwise it stays here as "not better"."""


def load(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def gates() -> dict:
    return json.loads(GATES.read_text()) if GATES.exists() else {}


def _d(c: dict, two=False) -> str:
    if not c:
        return "-"
    if two:
        return f"{c['delta']:+.4f} ± {2 * c['se']:.4f}"
    return f"{c['delta']:+.4f} ±{c['se']:.4f}"


def worst_kind(row: dict):
    ks = row.get("kinds") or {}
    if not ks:
        return None
    k = min(ks, key=lambda x: ks[x][0])
    return k, ks[k][0], ks[k][1]


def worse_kinds(row: dict) -> list:
    """Rival types where the candidate is worse than the incumbent by more than 2 SE."""
    return [k for k, (m, se) in (row.get("kinds") or {}).items() if m + 2 * se < 0]


def verdict(row: dict, g: dict) -> tuple:
    """(verdict, reasons)"""
    why = []
    m = row.get("main")
    if not m or m["delta"] <= 2 * m["se"]:
        why.append("TEST gain not above 2 SE")
    for k in worse_kinds(row):
        why.append(f"worse vs {k} beyond noise")
    d1 = row.get("d1")
    if d1 and d1["delta"] < -D1_MAX_LOSS:
        why.append(f"D-1 stress {d1['delta']:+.3f}")
    gg = g.get(row["id"], {})
    if gg.get("matrix", "").startswith("fail"):
        why.append("matrix: " + gg["matrix"][5:].strip())
    if gg.get("selftest", "").startswith("fail"):
        why.append("selftest fails")
    if why:
        return "not better", why
    pend = [x for x in ("matrix", "selftest") if x not in gg]
    if pend:
        return "passes TEST, gates pending (" + ", ".join(pend) + ")", []
    return "REPLACES the incumbent", []


def write(rows: list) -> None:
    g = gates()
    by_split = {s: [r for r in rows if r.get("split") == s and "error" not in r] for s in ("train", "select", "test")}
    uniq = {s: len({r["id"] for r in v}) for s, v in by_split.items()}
    L = ["# Duels III overnight search: leaderboard", "",
         f"Refreshed {time.strftime('%Y-%m-%d %H:%M %Z')}. Candidates scored: {uniq['train']} on train "
         f"(200 sessions x 4 worlds), {uniq['select']} on select (600 sessions x 4 worlds), {uniq['test']} on TEST "
         f"(2000 sessions x 4 worlds). Deltas are each candidate minus the incumbent on the same sessions (mean score "
         f"per duel: share of the pie x 0.9^rounds, 0 without a deal), ± one SE unless marked 2 SE.", "",
         RULE, "",
         "Worlds: **main** = Duels III (68 duels, 12 ticks, decay 0.10, 4 at once), the Duels II field refit "
         "(68 real duels: linear 28, oneshot 11, steady 8, fast 8, tft 5, absent 5, silent 3) plus a copy of duel.py "
         "with the incumbent params at weight 8 (10.5 %); **drift** = main with 20 % of the mix moved to "
         "deadline-concede and mute (silent, absent) rivals; **final** = the Grand Final's single round (34 duels); "
         "**D-1** = main where an accept at deadline-1 never settles. Training objective = 0.5 main + 0.15 drift + "
         "0.15 final + 0.2 D-1 (the D-1 stress is in it because the biggest raw gains of the first sweep all came from "
         "accepting at deadline-1); candidates more than 0.03 worse in D-1 are never parents or finalists.", ""]

    test = sorted(by_split["test"], key=lambda r: -(r.get("main") or {"delta": -9})["delta"])
    if test:
        L += ["## TEST (seeds 900000.., 2000 sessions)", "",
              "| candidate | what it changes | TEST Δ main (± 2 SE) | drift | final | worst rival type Δ | D-1 Δ | "
              "matrix | selftest | verdict |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in test:
            wk = worst_kind(r)
            v, why = verdict(r, g)
            gg = g.get(r["id"], {})
            L.append(f"| {r['name']} `{r['id']}` | {r['change']} | {_d(r.get('main'), True)} | "
                     f"{_d(r.get('drift'))} | {_d(r.get('final'))} | "
                     f"{f'{wk[0]} {wk[1]:+.4f} ±{wk[2]:.4f}' if wk else '-'} | {_d(r.get('d1'))} | "
                     f"{gg.get('matrix', '-')} | {gg.get('selftest', '-')} | "
                     f"**{v}**{' (' + '; '.join(why) + ')' if why else ''} |")
        L.append("")
        for r in test:
            if r.get("kinds"):
                ks = ", ".join(f"{k} {a:+.4f}±{b:.4f}" for k, (a, b) in sorted(r["kinds"].items()))
                L.append(f"- `{r['id']}` per rival type (main world, self = self-play): {ks}")
        L.append("")

    sel = {}
    for r in by_split["select"]:
        sel[r["id"]] = r
    tr = {}
    for r in by_split["train"]:
        tr[r["id"]] = r
    top = sorted(sel.values(), key=lambda r: -r["obj"]["delta"])[:25]
    if top:
        L += ["## Best on select (seeds 500000.., 600 sessions)", "",
              "| # | candidate | what it changes | objective Δ | main | drift | final | D-1 | train objective |",
              "|---|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(top, 1):
            t = tr.get(r["id"], {}).get("obj")
            L.append(f"| {i} | {r['name']} `{r['id']}` | {r['change']} | {_d(r['obj'])} | {_d(r.get('main'))} | "
                     f"{_d(r.get('drift'))} | {_d(r.get('final'))} | {_d(r.get('d1'))} | {_d(t)} |")
        L.append("")

    hyp = [r for r in tr.values() if r["name"].startswith("H")]
    if hyp:
        L += ["## Structured hypotheses (train)", "",
              "| hypothesis | what it changes | objective Δ | main | drift | final |", "|---|---|---|---|---|---|"]
        for r in sorted(hyp, key=lambda r: -r["obj"]["delta"]):
            L.append(f"| {r['name']} | {r['change']} | {_d(r['obj'])} | {_d(r.get('main'))} | "
                     f"{_d(r.get('drift'))} | {_d(r.get('final'))} |")
        L.append("")

    sw = [r for r in tr.values() if r["name"].startswith("S ")]
    if sw:
        levers = {}
        for r in sw:
            k = r["name"][2:].split("=")[0]
            levers.setdefault(k, []).append(r)
        L += ["## One lever at a time (train): best and worst value of each", "",
              "| lever | incumbent | best value: objective Δ | worst value: objective Δ |", "|---|---|---|---|"]
        inc = next((r["params"] for r in rows if r.get("name") == "incumbent"), {})
        order = sorted(levers, key=lambda k: -max(x["obj"]["delta"] for x in levers[k]))
        for k in order:
            xs = sorted(levers[k], key=lambda r: -r["obj"]["delta"])
            b, w = xs[0], xs[-1]
            iv = {"anchor": (inc.get("ratios") or ["?"])[0], "floor": (inc.get("ratios") or ["?"])[-1],
                  "prem0": (inc.get("days_premium") or ["?"])[0],
                  "prem1": (inc.get("days_premium") or ["?", "?"])[-1]}.get(k, inc.get(k, "default"))
            L.append(f"| {k} | {iv} | {b['name'][2:].split('=')[1]}: {_d(b['obj'])} | "
                     f"{w['name'][2:].split('=')[1]}: {_d(w['obj'])} |")
        L.append("")

    if tr:
        worst = sorted(tr.values(), key=lambda r: r["obj"]["delta"])[:10]
        L += ["## What lost most (train)", "", "| candidate | what it changes | objective Δ |", "|---|---|---|"]
        for r in worst:
            L.append(f"| {r['name']} | {r['change']} | {_d(r['obj'])} |")
        L.append("")
    OUT.write_text("\n".join(L) + "\n")
