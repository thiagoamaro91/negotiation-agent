"""A "leaving after this tick" classifier for bench traders, from quote paths only (WP11, family 3).

Each sample is one trader on one tick it was seen. Features (all from what a broker can see live, no expiry):
  age   ticks on the book, this one included, / 16
  move  how far the quote has relaxed toward its limit since the first sight, as a share of the first quote (<= 0:
        never relaxed, or moved away)
  step  the last move toward the limit, same scale (0 on first sight)
  firm  1 when seen at least twice and never relaxed
  first 1 on first sight
  st    ticks since the run's first offer appeared (the session clock), / 16, and its square
  buy   1 for a buyer
Label: 1 when the trader is not on the book next tick and nobody matched it (left, or the session ended); a trader
matched on record (by us or the engine) has no label on its last tick (censored: we do not know if it would have left).

The fit is an L2-regularised logistic regression solved by Newton's method (IRLS): deterministic, standard library.
"""
from __future__ import annotations

import math

FEATURES = ("bias", "age", "move", "step", "firm", "first", "st", "st2", "buy")
SESSION = 16.0


def features(side: str, quotes: list, tick: int, run_start: int) -> list:
    """quotes: [(tick, quote)] up to and including `tick` (the last one is the current quote)."""
    t0, q0 = quotes[0]
    q = quotes[-1][1]
    sign = 1 if side == "buy" else -1
    n = tick - t0 + 1
    move = sign * (q - q0) / q0 if q0 else 0.0
    step = sign * (q - quotes[-2][1]) / q0 if len(quotes) >= 2 and q0 else 0.0
    first = 1.0 if len(quotes) < 2 else 0.0
    firm = 1.0 if not first and move <= 0 else 0.0
    st = (tick - run_start) / SESSION
    return [1.0, n / SESSION, move, step, firm, first, st, st * st, 1.0 if side == "buy" else 0.0]


def samples_from_runs(runs: dict) -> tuple:
    """(X, y) from bench_sim.read_runs output: run -> offer id -> {side, quotes, first, last, how}."""
    X, y = [], []
    for offers in runs.values():
        if not offers:
            continue
        start = min(r["first"] for r in offers.values())
        for r in offers.values():
            qs = sorted(r["quotes"])
            for k, (t, _q) in enumerate(qs):
                last = t == r["last"]
                if last and r["how"] in ("ours", "engine"):
                    continue  # censored
                X.append(features(r["side"], qs[:k + 1], t, start))
                y.append(1.0 if last else 0.0)
    return X, y


def samples_from_traders(sessions: list, quote_fn, ticks: int) -> tuple:
    """(X, y) from simulated sessions with nothing matched: every trader's whole path. sessions: [(traders, sc)];
    quote_fn(trader, t, sc) -> quote. A trader present from a to its last tick leaves after the last one."""
    X, y = [], []
    for traders, sc in sessions:
        start = min(tr["a"] for tr in traders)
        for tr in traders:
            last = min(tr["a"] + tr["P"] - 1, ticks - 1)
            path = []
            for t in range(tr["a"], last + 1):
                path.append((t, quote_fn(tr, t, sc)))
                X.append(features(tr["side"], path, t, start))
                y.append(1.0 if t == last else 0.0)
    return X, y


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _solve(a: list, b: list) -> list:
    """Gaussian elimination with partial pivoting (a is d x d, small)."""
    d = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(d):
        p = max(range(c, d), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        for r in range(d):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                for k in range(c, d + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][d] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(d)]


def fit(X: list, y: list, l2: float = 1.0, iters: int = 25) -> list:
    """Weights minimising the log loss + l2/2 |w|^2 (the bias is not penalised)."""
    if not X:
        raise ValueError("no samples")
    d = len(X[0])
    w = [0.0] * d
    for _ in range(iters):
        g = [l2 * w[j] if j else 0.0 for j in range(d)]
        h = [[(l2 if i == j and i else 0.0) for j in range(d)] for i in range(d)]
        for x, t in zip(X, y):
            p = _sigmoid(sum(a * b for a, b in zip(w, x)))
            r = p - t
            s = p * (1 - p)
            for i in range(d):
                if x[i]:
                    g[i] += r * x[i]
                    xi = s * x[i]
                    hi = h[i]
                    for j in range(d):
                        if x[j]:
                            hi[j] += xi * x[j]
        for i in range(d):
            h[i][i] += 1e-9
        step = _solve(h, g)
        w = [a - b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w


def predict(w: list, x: list) -> float:
    return _sigmoid(sum(a * b for a, b in zip(w, x)))


def log_loss(w: list, X: list, y: list) -> float:
    eps = 1e-12
    return -sum(t * math.log(max(eps, predict(w, x))) + (1 - t) * math.log(max(eps, 1 - predict(w, x)))
                for x, t in zip(X, y)) / max(1, len(X))
