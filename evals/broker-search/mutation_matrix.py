"""Mutation matrix for tests/test_broker_search.py: each guard in the lab is broken in turn, in a scratch copy of
the tree, and the tests must go red. Usage: python3 evals/broker-search/mutation_matrix.py SCRATCH_DIR (SCRATCH_DIR
must hold tests/, evals/broker-search/ copies and kit, agent, tools, logs links; see setup())."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def setup(S: Path) -> None:
    import shutil
    if S.exists():
        shutil.rmtree(S)
    (S / "tests").mkdir(parents=True)
    (S / "evals" / "broker-search").mkdir(parents=True)
    shutil.copy(ROOT / "tests" / "test_broker_search.py", S / "tests")
    for f in (ROOT / "evals" / "broker-search").glob("*.py"):
        shutil.copy(f, S / "evals" / "broker-search")
    for d in ("kit", "agent", "tools", "logs"):
        os.symlink(ROOT / d, S / d)


S = Path(sys.argv[1])
setup(S)
M = [
 ("lab.py", "return r[\"diff\"] > 2 * r[\"se\"]", "return r[\"diff\"] > 1.8 * r[\"se\"]"),
 ("lab.py", "return r[\"diff\"] + r[\"ci95\"] < 0", "return r[\"diff\"] + r[\"ci95\"] < -0.0001"),
 ("lab.py", "    if dv:\n", "    if False:\n"),
 ("lab.py", "    if bm:\n", "    if False:\n"),
 ("lab.py", "    required = battery(extra=False)\n    missing", "    required = battery()\n    missing"),
 ("lab.py", "if s not in matched and b not in matched:\n            adj", "if True:\n            adj"),
 ("lab.py", "return sum(s not in matched and b not in matched for", "return sum(s not in matched or b not in matched for"),
 ("lab.py", "var = max(0.0, (a[\"sumsq\"] + b[\"sumsq\"]) / n - m * m)", "var = max(0.0, (a[\"sumsq\"]) / n - m * m)"),
 ("lab.py", "if not beats(rows[k])]\n    if everywhere", "if worse(rows[k])]\n    if everywhere"),
 ("policies.py", "                    if not _crosses(book, ask, bid):\n                        continue\n", ""),
 ("policies.py", "if urg.get(y, 0.0) > cfg[\"lo\"]:", "if False:"),
 ("policies.py", "if loss > cfg[\"delta\"]:", "if False:"),
 ("policies.py", "if urg.get(x, 0.0) < cfg[\"hi\"]:", "if False:"),
 ("policies.py", "if st >= cfg[\"t_max\"]:", "if False:"),
 ("policies.py", "if recent.get(c) and others", "if others"),
 ("policies.py", "and urg.get(x, 0.0) <= cfg[\"lo\"]:\n                hold", ":\n                hold"),
 ("policies.py", "if ps[\"st\"] >= TICKS - 1 - cfg[\"end_margin\"]:", "if ps[\"st\"] > TICKS - 1 - cfg[\"end_margin\"]:"),
 ("policies.py", "if b[0] > tick - window)", "if b[0] >= tick - window)"),
 ("leave_model.py", "                if last and r[\"how\"] in (\"ours\", \"engine\"):\n                    continue  # censored\n", ""),
 ("leave_model.py", "firm = 1.0 if not first and move <= 0 else 0.0", "firm = 1.0 if not first and move < 0 else 0.0"),
]
res = []
for f, a, b in M:
    p = S / "evals/broker-search" / f
    orig = p.read_text()
    if a not in orig:
        res.append(("MISSING", f, a[:50])); continue
    p.write_text(orig.replace(a, b, 1))
    r = subprocess.run([sys.executable, "-m", "unittest", "tests.test_broker_search"], cwd=S, capture_output=True, text=True)
    p.write_text(orig)
    res.append(("KILLED" if r.returncode else "SURVIVED", f, a[:60].replace("\n", "\\n")))
for x in res: print(*x)
