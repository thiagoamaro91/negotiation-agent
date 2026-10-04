"""How well can "leaving after this tick" be predicted from quote paths on the recorded sessions? Leave-one-run-out
log loss and AUC of leave_model's classifier (fitted on the other runs), against the base rate, and the simulator-
trained models scored on the real runs. Offline: reads logs/broker/2026-10-03.jsonl only.

    python3 evals/broker-search/leave_report.py
"""
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import leave_model as lm  # noqa: E402
import policies as pol  # noqa: E402

bs = pol.bs


def auc(p: list, y: list) -> float:
    pos = [a for a, t in zip(p, y) if t]
    neg = [a for a, t in zip(p, y) if not t]
    if not pos or not neg:
        return float("nan")
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    return wins / (len(pos) * len(neg))


def base_loss(y_train: list, y_test: list) -> float:
    r = min(max(sum(y_train) / len(y_train), 1e-6), 1 - 1e-6)
    return -sum(t * math.log(r) + (1 - t) * math.log(1 - r) for t in y_test) / len(y_test)


def main() -> int:
    runs = bs.read_runs(pol.LOG)
    print(f"runs {sorted(runs)}")
    allp, ally, allb = [], [], []
    for held in sorted(runs):
        Xtr, ytr = lm.samples_from_runs({r: v for r, v in runs.items() if r != held})
        Xte, yte = lm.samples_from_runs({held: runs[held]})
        w = lm.fit(Xtr, ytr)
        p = [lm.predict(w, x) for x in Xte]
        allp += p
        ally += yte
        allb.append((base_loss(ytr, yte), len(yte)))
        print(f"  held out {held}: n {len(yte)}, leavers {int(sum(yte))}, log loss {lm.log_loss(w, Xte, yte):.3f} "
              f"(base rate {base_loss(ytr, yte):.3f}), AUC {auc(p, yte):.3f}")
    ll = -sum(t * math.log(max(1e-12, a)) + (1 - t) * math.log(max(1e-12, 1 - a)) for a, t in zip(allp, ally)) / len(ally)
    bl = sum(b * n for b, n in allb) / sum(n for _, n in allb)
    print(f"leave-one-run-out: log loss {ll:.3f} vs base rate {bl:.3f}, AUC {auc(allp, ally):.3f}, n {len(ally)}")
    X, y = lm.samples_from_runs(runs)
    for kind in ("real", "sim", "sim_hard"):
        w = pol.leave_weights(kind)
        p = [lm.predict(w, x) for x in X]
        print(f"model {kind:<8} on all real samples: log loss {lm.log_loss(w, X, y):.3f}, AUC {auc(p, y):.3f}"
              + ("  (in-sample)" if kind == "real" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
