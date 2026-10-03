"""Paired comparison of two variants of an eval flow. usage: cmp.py <flow_dir> <a> <b>"""
import json, math, sys
from collections import defaultdict
from pathlib import Path

def load(d):
    return {(r["prompt_id"], r.get("rep", 0)): r for r in map(json.loads, (Path(d) / "results.jsonl").read_text().splitlines())}

def cmp(flow_dir, a, b):
    A, B = load(Path(flow_dir) / a), load(Path(flow_dir) / b)
    keys = sorted(set(A) & set(B))
    n = len(keys)
    out = {"n": n, "a": sum(A[k]["grade"]["score"] for k in keys) / n, "b": sum(B[k]["grade"]["score"] for k in keys) / n,
           "breach_b": sum(B[k]["grade"]["limit_breach"] for k in keys),
           "deal_a": sum(A[k]["grade"]["deal"] for k in keys) / n, "deal_b": sum(B[k]["grade"]["deal"] for k in keys) / n,
           "missed_b": sum(B[k]["grade"]["missed_ok_offer"] for k in keys) / n}
    by = defaultdict(float)
    kind = defaultdict(list)
    for k in keys:
        cl = A[k]["meta"].get("seed", k[0])
        d = B[k]["grade"]["score"] - A[k]["grade"]["score"]
        by[cl] += d
        kind[A[k]["tags"][0]].append(d)
    tot = list(by.values()); m = len(tot)
    mu = sum(tot) / m
    var = sum((t - mu) ** 2 for t in tot) / (m - 1) if m > 1 else 0
    out["diff"] = sum(tot) / n
    out["se"] = math.sqrt(m * var) / n
    out["by_kind"] = {kk: round(sum(v) / len(v), 4) for kk, v in sorted(kind.items())}
    out["changed"] = sum(1 for k in keys if B[k]["grade"]["score"] != A[k]["grade"]["score"])
    return out

if __name__ == "__main__":
    r = cmp(*sys.argv[1:4])
    print(f"{sys.argv[1]} {sys.argv[2]}->{sys.argv[3]}: n {r['n']} a {r['a']:.4f} b {r['b']:.4f} diff {r['diff']:+.4f} +- SE {r['se']:.4f} "
          f"(2SE {2*r['se']:.4f}) breach {r['breach_b']} deal {r['deal_a']:.3f}->{r['deal_b']:.3f} missed {r['missed_b']:.3f} changed {r['changed']}")
    print("  by kind:", r["by_kind"])
