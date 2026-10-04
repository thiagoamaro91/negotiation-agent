"""Shared plumbing for the offline agent evals (tools/eval_*.py). No network, no key, no model.

Each eval is one flow directory under evals/<flow>/:

    evals/<flow>/_state.json            metrics (first binary one is the headline) and perf_fields; committed
    evals/<flow>/cases.jsonl            the signed-off case list (id, tags, source); committed
    evals/<flow>/cases.md               the same list, human-readable, for review; committed
    evals/<flow>/metrics.md             what each metric means and what was left out; committed
    evals/<flow>/<variant>/results.jsonl  one row per (case, rep), written as each case finishes
    evals/<flow>/<variant>/errors.jsonl   attempts that never produced a scorable result (crash, timeout)
    evals/<flow>/<variant>/traces/<id>_rep<k>.json   tick-by-tick trace of what the agent saw and did
    evals/<flow>/<variant>/change.md      non-baseline only: what this variant changes (first line = label)

<variant> is "baseline" or v1, v2, ... (the report builder ignores any other name). Resume is idempotent at the
(case, rep) key: a rerun skips rows already in results.jsonl and never writes a second row for the same key.
The report: node <claude-api skill>/shared/evals/report/build-report-lite.mjs evals/<flow>/

Trace turns are {role, content} with role one of system | user | assistant | tool_call | tool_result. For a
simulated negotiation: system = the policy and its params, user = what the agent saw that tick, assistant = what it
did. Game text (rival or dealer words, offer notes) is untrusted data and never goes into a trace or a prompt.
"""
from __future__ import annotations

import hashlib
import json
import math
import signal
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
VARIANT_OK = ("baseline",)


def flow_dir(flow: str) -> Path:
    return EVALS / flow


def check_variant(name: str) -> str:
    if name in VARIANT_OK or (name.startswith("v") and name[1:].isdigit()):
        return name
    raise SystemExit(f"variant must be 'baseline' or v<N> (v1, v2, ...), got {name!r}: the report ignores other names")


def write_state(flow: str, metrics: list, perf_fields: list, extra: dict = None) -> None:
    """Writes evals/<flow>/_state.json only if it does not exist yet (after sign-off it is the contract; edit by hand)."""
    p = flow_dir(flow) / "_state.json"
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"metrics": metrics, "perf_fields": perf_fields, **(extra or {})}, indent=1) + "\n")


def write_cases(flow: str, cases: list, title: str, columns: list) -> None:
    """cases: [{id, tags: [...], source, ...}]. Writes cases.jsonl and a cases.md table (columns = extra keys)."""
    d = flow_dir(flow)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "cases.jsonl").open("w") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    lines = [f"# {title}", "", f"{len(cases)} cases.", "", "| id | tags | " + " | ".join(columns) + " |",
             "|---|---|" + "---|" * len(columns)]
    for c in cases:
        cells = [str(c.get(k, "")).replace("|", "/") for k in columns]
        lines.append(f"| {c['id']} | {', '.join(map(str, c.get('tags', [])))} | " + " | ".join(cells) + " |")
    (d / "cases.md").write_text("\n".join(lines) + "\n")


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


class Timeout(Exception):
    pass


@contextmanager
def ceiling(seconds: float):
    """Hard wall-clock ceiling per case (main thread only; SIGALRM)."""
    def _fire(signum, frame):
        raise Timeout(f"case exceeded {seconds:.0f} s")
    old = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


class Run:
    """One variant's run of one flow. Use run.case(...) for every (case, rep)."""

    def __init__(self, flow: str, variant: str, policy_label: str, change: str = None):
        self.flow, self.variant = flow, check_variant(variant)
        self.dir = flow_dir(flow) / variant
        (self.dir / "traces").mkdir(parents=True, exist_ok=True)
        self.results = self.dir / "results.jsonl"
        self.errors = self.dir / "errors.jsonl"
        self.policy = policy_label
        self.done = set()
        prior = set()
        if self.results.exists():
            for line in self.results.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.done.add((r["prompt_id"], r.get("rep", 0)))
                    prior.add(r.get("model"))
        if prior and prior != {policy_label}:
            # A cached (case, rep) is skipped, so a rerun with another policy, params file or code hash would
            # report the old scores under the new label: refuse, like the market runner always did.
            raise SystemExit(f"{self.results} was written by {sorted(map(str, prior))}, not {policy_label}: use a "
                             f"new variant (or move the old results away)")
        if variant != "baseline" and change:
            (self.dir / "change.md").write_text(change.rstrip() + "\n")
        self.rows = []

    def case(self, case_id: str, rep: int, prompt: str, tags: list, fn, timeout_s: float = 120.0) -> dict:
        """fn() -> (grade: {metric: number}, perf: {field: number}, trace: [turns], meta: dict).
        Skips a (case, rep) already on disk. A crash or timeout goes to errors.jsonl, never to results.jsonl."""
        if (case_id, rep) in self.done:
            return None
        t0 = time.time()
        try:
            with ceiling(timeout_s):
                grade, perf, trace, meta = fn()
        except Exception as e:  # noqa: BLE001 - every failure is recorded with its class, then the run continues
            cls = "timeout" if isinstance(e, Timeout) else "harness_error"
            with self.errors.open("a") as f:
                f.write(json.dumps({"prompt_id": case_id, "rep": rep, "class": cls, "error": repr(e)[:500],
                                    "trace": traceback.format_exc()[-1500:], "model": self.policy}) + "\n")
            return None
        missing = [k for k, v in grade.items() if not isinstance(v, (int, float)) or isinstance(v, bool)
                   or (isinstance(v, float) and math.isnan(v))]
        if missing:
            raise ValueError(f"{case_id}: non-numeric grade fields {missing} (fail loud, do not write the row)")
        row = {"prompt_id": case_id, "rep": rep, "prompt": prompt, "tags": tags, "status": "ok",
               "stop_reason": "n/a", "model": self.policy, "grade": grade,
               "latency_s": round(time.time() - t0, 3), **perf, "meta": meta}
        (self.dir / "traces" / f"{case_id}_rep{rep}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1))
        with self.results.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.done.add((case_id, rep))
        self.rows.append(row)
        return row

    def all_rows(self) -> list:
        return [json.loads(l) for l in self.results.read_text().splitlines() if l.strip()] if self.results.exists() else []


def mean_ci(values: list, binary: bool = False) -> tuple:
    """Mean and 95% CI half-width (Wilson for a pass rate, normal approx for a float)."""
    n = len(values)
    if not n:
        return (float("nan"), float("nan"), 0)
    m = sum(values) / n
    if binary:
        z = 1.96
        den = 1 + z * z / n
        centre = (m + z * z / (2 * n)) / den
        half = z * math.sqrt(m * (1 - m) / n + z * z / (4 * n * n)) / den
        lo, hi = centre - half, centre + half
        return (m, max(m - lo, hi - m), n)
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return (m, 1.96 * sd / math.sqrt(n), n)


def summary_line(flow: str, variant: str, rows: list, metrics: list) -> str:
    """One line per metric: mean +- 95% CI over status-ok rows; metrics = the _state.json metric list."""
    parts = []
    for m in metrics:
        vals = [r["grade"][m["id"]] for r in rows if r.get("status") == "ok" and m["id"] in r["grade"]]
        mu, half, n = mean_ci(vals, m.get("kind") == "binary")
        parts.append(f"{m['id']} {mu:.3f} +- {half:.3f} (n={n})")
    return f"[{flow}/{variant}] " + "; ".join(parts)
