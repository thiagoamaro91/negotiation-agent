"""Shared loaders for the frozen 01:17 snapshot. Read-only."""
import glob
import json
import os

S = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(S, "snap")


def duels():
    out = {}
    for f in sorted(glob.glob(os.path.join(SNAP, "logs", "duels", "duel-*.json"))):
        d = json.load(open(f))
        d["_file"] = os.path.basename(f)
        out[d["duel"]] = d
    return out


def partner_id(did):
    return did + 1 if did % 2 else did - 1


def rival_msgs(d):
    return [m for m in d["messages"] if m["from"] != "you" and m.get("price") is not None]


def our_msgs(d):
    return [m for m in d["messages"] if m["from"] == "you"]


def feed():
    seen, out = set(), []
    for line in open(os.path.join(SNAP, "logs", "feed", "feed.jsonl")):
        e = json.loads(line)
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    return out


def surplus(role, limit, price):
    """Our surplus at `price` (positive = inside our limit)."""
    return (price - limit) if role == "seller" else (limit - price)
