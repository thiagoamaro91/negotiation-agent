"""The last two gates for a TEST finalist: tools/duel_matrix.py --session 3 (no rival row worse by more than 2 SE)
and `agent/duel.py selftest --params`. Writes cands/<id>.json, matrix/<id>.md|json and gates.json.

Usage (repo root):
    nice -n 10 python3 docs/duel-lab/duels3-search/gate.py <id> [<id> ...] --workers 4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import board  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sessions", type=int, default=200)
    a = ap.parse_args()
    rows = {r["id"]: r for r in board.load(HERE / "results.jsonl")}
    gates = board.gates()
    (HERE / "cands").mkdir(exist_ok=True)
    (HERE / "matrix").mkdir(exist_ok=True)
    for cid in a.ids:
        r = rows[cid]
        f = HERE / "cands" / f"{cid}.json"
        f.write_text(json.dumps(r["params"], indent=2) + "\n")
        st = subprocess.run([sys.executable, str(ROOT / "agent" / "duel.py"), "selftest", "--params", str(f)],
                            cwd=ROOT, capture_output=True, text=True)
        g = {"selftest": "pass" if st.returncode == 0 else "fail"}
        out_json, out_md = HERE / "matrix" / f"{cid}.json", HERE / "matrix" / f"{cid}.md"
        subprocess.run([sys.executable, str(ROOT / "tools" / "duel_matrix.py"), "--session", "3",
                        "--sessions", str(a.sessions), "--workers", str(min(4, a.workers)),
                        "--params", f"incumbent={board.HERE.parents[0] / 'duel-params-duels3.json'}",
                        "--params", f"{cid}={f}", "--out-md", str(out_md), "--out-json", str(out_json)],
                       cwd=ROOT, capture_output=True, text=True, check=True)
        cells = json.loads(out_json.read_text())["cells"]
        bad = [c["world"][7:] for c in cells if c["policy"] == cid and c["world"].startswith("rival:")
               and c["delta"] < -2 * c["se"]]
        worse_any = [f"{c['world']} ({c['mode']})" for c in cells if c["policy"] == cid and c["delta"] < -2 * c["se"]]
        g["matrix"] = ("fail: " + ", ".join(bad)) if bad else "pass"
        g["matrix_other_worse"] = worse_any
        gates[cid] = g
        board.GATES.write_text(json.dumps(gates, indent=1) + "\n")
        print(cid, g, flush=True)
    board.write(board.load(HERE / "results.jsonl"))


if __name__ == "__main__":
    main()
