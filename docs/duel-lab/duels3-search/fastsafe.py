"""Post-interim targeted search: neighbours of a finalist that do not lose to the `fast` rival.

Grid around the finalist with absent_at back near the incumbent's (fastfix.py: the earlier absent offer is what
costs against jump-and-hold rivals), scored on the select seeds in the four search worlds and in the matrix's
`rival: fast` world (select seeds, never the matrix's own). Writes fastsafe-<id>.json; rows go to results.jsonl.
Usage: nice -n 10 python3 docs/duel-lab/duels3-search/fastsafe.py <id>
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fastfix  # noqa: E402
import lab  # noqa: E402
import search  # noqa: E402


def main():
    cid = sys.argv[1]
    ev = search.Evaluator(4)
    p0 = {r["id"]: r for r in ev.done}[cid]["params"]
    items = []
    for aa, acc, fl, lr in itertools.product([0.18, 0.21, 0.25], [5, 6], [1.42, 1.38, 1.35], [1.131, 1.155]):
        q = search._set(search._set(search._set(search._set(p0, "absent_at", aa), "accept_any_ticks", acc),
                                    "floor", fl), "last_r", lr)
        if search.valid(q):
            items.append((f"F {cid} aa={aa} acc={acc} floor={fl} last_r={lr}", q))
    rows = ev.score(items, "select", phase="fastsafe")
    fast = dict(ev.pool.map(fastfix.fast_world, [("incumbent", lab.INCUMBENT, 500000, 300)] +
                            [(search.cid(q), q, 500000, 300) for _, q in items]))
    out = []
    for r in rows:
        m, se = lab.paired(fast[r["id"]], fast["incumbent"])
        out.append({"id": r["id"], "name": r["name"], "obj": r.get("obj"), "main": r.get("main"), "d1": r.get("d1"),
                    "fast": [round(m, 5), round(se, 5)]})
    out.sort(key=lambda x: -(x["obj"] or {"delta": -9})["delta"])
    for x in out:
        print(x["id"], x["name"][len(cid) + 3:], x["obj"], "d1", (x["d1"] or {}).get("delta"), "fast", x["fast"],
              flush=True)
    (HERE / f"fastsafe-{cid}.json").write_text(json.dumps(out, indent=1))
    ev.refresh()
    ev.pool.close()


if __name__ == "__main__":
    main()
