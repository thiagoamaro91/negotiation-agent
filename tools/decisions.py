"""The standing decision log (H2, team bus #5970008367): one shared file, every lane's decisions in one shape.

Thiago's rule #4 (bus #5970008367, 16:00): "Every decision is logged with its reason... The standing engine must
write the same shape." Today that shape is kept by hand on his Air (~/bazaar-decisions/decisions.jsonl). This file
automates it: it reads every agent's own log (logs/<agent>/<date>.jsonl, already written by abuela.py, chato.py,
market_desk.py, duel.py) and normalises each decision into one row:

    {ts, tick, lane, action, card, price, our_value, surplus, why, result}

It writes nothing to any agent's own log and sends nothing to the game: purely a local, offline merge of files
that already exist. Safe to run next to the live bots.

    python3 tools/decisions.py once                    # one pass, prints and appends new rows, then exits
    python3 tools/decisions.py watch                    # polls every --interval seconds (default 5), Ctrl-C to stop
    python3 tools/decisions.py once --out logs/decisions.jsonl --agents-dir logs

Idempotent: logs/decisions.offsets.json remembers the byte offset read in each source file, so reruns and the
watch loop never duplicate a row. A source file that shrinks (rotated) is read from its start again.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGS = ROOT / "logs"
DEFAULT_OUT = DEFAULT_LOGS / "decisions.jsonl"
DEFAULT_OFFSETS = DEFAULT_LOGS / "decisions.offsets.json"

# event -> result, for the lanes that log one event per outcome (abuela.py, chato.py, duel.py)
DEALER_RESULT = {"accept": "accepted", "stop": "stopped", "close_failed": "failed", "mismatch": "mismatch"}
DUEL_RESULT = {"accept": "accepted", "would_accept": "would_accept", "refused": "refused", "accept_skipped": "skipped",
               "accept_mismatch": "mismatch", "bug_skip": "skipped"}
# market_desk.py logs one "decision" row per candidate (most are skip/keep/note) plus terminal rows for the one taken
MARKET_TAKE = {"buy", "sell", "bid", "swap", "myswap"}
MARKET_RESULT = {"accepted": "accepted", "sent": "sent", "refused": "refused", "skip_accept": "skipped"}


KNOWN_AGENTS = frozenset({"market", "duel", "abuela", "chato"})   # chato.py also runs --dealer pilar/picaros under agent="chato"


def normalise(agent: str, row: dict) -> dict | None:
    """One source row -> one canonical row, or None if it carries no decision worth keeping (reads, heartbeats,
    an agent we do not yet recognise, ...). Unknown agents are dropped rather than guessed at: a wrong mapping
    (e.g. reading a future agent's "price" as ours) is worse than a gap that a next --agents-dir pass fills in."""
    if agent not in KNOWN_AGENTS:
        return None
    event = row.get("event")
    base = {"ts": row.get("ts"), "tick": row.get("tick"), "lane": agent}

    if agent == "market":
        if event == "decision":
            if row.get("kind") not in MARKET_TAKE or row.get("action") in (None, "skip", "keep", "note"):
                return None
            return {**base, "action": f"{row['kind']}:{row['action']}", "card": row.get("card"), "price": row.get("price"),
                    "our_value": row.get("value"), "surplus": row.get("gain"), "why": row.get("reason"), "result": "proposed"}
        if event in MARKET_RESULT:
            return {**base, "action": row.get("op") or row.get("side") or row.get("kind") or event, "card": row.get("card"),
                    "price": row.get("price"), "our_value": row.get("value"), "surplus": row.get("gain"),
                    "why": row.get("why") or row.get("reason") or row.get("msg"), "result": MARKET_RESULT[event]}
        return None

    if agent == "duel":
        if event not in DUEL_RESULT:
            return None
        return {**base, "action": "accept", "card": row.get("duel"), "price": row.get("taken", {}).get("price")
                if isinstance(row.get("taken"), dict) else row.get("price"), "our_value": row.get("limit"),
                "surplus": None, "why": row.get("why") or row.get("msg"), "result": DUEL_RESULT[event]}

    # abuela.py / chato.py (any --dealer, including pilar): shared loop, shared event names
    if event in DEALER_RESULT:
        return {**base, "action": "accept" if event == "accept" else event, "card": row.get("item") or row.get("card"),
                "price": row.get("price"), "our_value": row.get("value"), "surplus": None,
                "why": row.get("why") or row.get("code") or row.get("reason"), "result": DEALER_RESULT[event]}
    if event == "result":
        return {**base, "action": "settle", "card": row.get("item") or row.get("card"), "price": row.get("price"),
                "our_value": None, "surplus": None, "why": row.get("reason"), "result": row.get("status")}
    return None


def source_files(logs_dir: Path) -> list[tuple[str, Path]]:
    """[(agent, path), ...] for every logs/<agent>/*.jsonl except our own output and offsets."""
    if not logs_dir.is_dir():
        return []
    out = []
    for d in sorted(p for p in logs_dir.iterdir() if p.is_dir()):
        for f in sorted(d.glob("*.jsonl")):
            out.append((d.name, f))
    return out


def load_offsets(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_offsets(path: Path, offsets: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(offsets))


def pass_once(logs_dir: Path, out_path: Path, offsets_path: Path) -> list[dict]:
    """Read every new line since the last pass, normalise it, append any decision rows to out_path. Returns them."""
    offsets = load_offsets(offsets_path)
    new_rows: list[dict] = []
    for agent, path in source_files(logs_dir):
        key = str(path)
        size = path.stat().st_size
        start = offsets.get(key, 0)
        if start > size:        # the file shrank (rotated): read it again from the start
            start = 0
        if start == size:
            continue
        with path.open("r", encoding="utf-8") as f:
            f.seek(start)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                canon = normalise(agent, row)
                if canon is not None:
                    new_rows.append(canon)
            offsets[key] = f.tell()
    if new_rows:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as f:
            for r in new_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    save_offsets(offsets_path, offsets)
    return new_rows


def show(rows: list[dict]) -> None:
    for r in rows:
        print(f"[{r.get('ts', '')[11:]}] tick {r.get('tick')} {r.get('lane'):<7} {r.get('action'):<14} "
              f"{str(r.get('card') or '-'):<8} price={r.get('price')} our_value={r.get('our_value')} "
              f"surplus={r.get('surplus')} result={r.get('result')} | {r.get('why')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["once", "watch"])
    ap.add_argument("--agents-dir", default=str(DEFAULT_LOGS), help="directory holding logs/<agent>/*.jsonl")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--offsets", default=str(DEFAULT_OFFSETS))
    ap.add_argument("--interval", type=float, default=5.0, help="watch: seconds between passes")
    ap.add_argument("--quiet", action="store_true", help="do not print rows, only write them")
    args = ap.parse_args()
    logs_dir, out_path, offsets_path = Path(args.agents_dir), Path(args.out), Path(args.offsets)

    if args.cmd == "once":
        rows = pass_once(logs_dir, out_path, offsets_path)
        if not args.quiet:
            show(rows)
        print(f"{len(rows)} new decision row(s) -> {out_path}", file=sys.stderr)
        return
    try:
        while True:
            rows = pass_once(logs_dir, out_path, offsets_path)
            if rows and not args.quiet:
                show(rows)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
