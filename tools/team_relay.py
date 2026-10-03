"""Relay the team's own live files (our account, the live score, every bot decision, the desks' heartbeats) to the
market brain. Keyless: it only reads files the key machine already wrote, from a fixed allowlist.

    python3 tools/team_relay.py                       # Hector's Mac: the Mini's shares mounted at /Volumes/bazaar(-live)
    python3 tools/team_relay.py --once --dry-run      # read and scrub once, print what would be sent, send nothing
    python3 tools/team_relay.py --repo ~/negotiation-agent --live ~/bazaar-live   # on the Mini itself
    python3 tools/team_relay.py --out logs/state/team_live.json                   # brain on the same machine: write the file

Every RELAY_SECONDS it reads exactly these files and nothing else (no glob, no directory walk):
    <repo>/logs/state/me.json        our /api/me as tools/snapshot.py last saved it (cash, cards, private multipliers)
    <repo>/logs/score.jsonl          our real score and cash over time
    <repo>/logs/state/desk-*.json    the named desks' heartbeats (DESKS below)
    <live>/score.state.json          the live score reader's last reading (score, rank, cash, pages), minute by minute
    <live>/decisions.jsonl           every bot decision with its reason
A symlink, or a path whose name mentions "env" or "key", is never opened. Every field whose name contains "key" is
dropped at any depth and key-shaped strings are redacted before anything leaves the machine. It POSTs the bundle to
BRAIN_URL/ingest/team with BRAIN_WRITE_TOKEN (from the environment or --env, default ~/bazaar/brain-relay.env), or
writes it to --out. It never writes to the shares and never talks to the game.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

RELAY_SECONDS = 20.0
DEFAULT_REPO = Path("/Volumes/bazaar")
DEFAULT_LIVE = Path("/Volumes/bazaar-live")
DEFAULT_ENV = Path.home() / "bazaar" / "brain-relay.env"
DESKS = ("broker", "market", "duel", "seller", "chato", "pilar", "trades")
FILES = {  # name in the bundle -> (root, relative path); the only files this relay ever opens
    "me": ("repo", "logs/state/me.json"),
    "score_rows": ("repo", "logs/score.jsonl"),
    "score_state": ("live", "score.state.json"),
    "decisions": ("live", "decisions.jsonl"),
    **{f"desk:{d}": ("repo", f"logs/state/desk-{d}.json") for d in DESKS},
}
MAX_DECISIONS = 400
MAX_SCORE_ROWS = 200
MAX_TEXT = 600
MAX_BYTES = 900_000          # the brain refuses a bundle over 1 MB
KEYLIKE = re.compile(r"\b(?:tk|bk|sk)-[A-Za-z0-9-]{6,}")
FORBIDDEN = re.compile(r"env|key", re.IGNORECASE)


def scrub(x, limit: int | None = None):
    """Drop every field whose name mentions a key, at any depth; redact key-shaped strings; cut long text."""
    if isinstance(x, dict):
        return {k: scrub(v, limit) for k, v in x.items() if "key" not in str(k).lower()}
    if isinstance(x, list):
        return [scrub(v, limit) for v in x]
    if isinstance(x, str):
        x = KEYLIKE.sub("[redacted]", x)
        return x[:limit] if limit else x
    return x


def safe_path(root: Path, rel: str) -> Path | None:
    """The file to read, or None: never a symlink, never outside the root, never a name with env/key in it."""
    if FORBIDDEN.search(rel):
        return None
    path = root / rel
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if root.resolve() not in path.resolve().parents:
            return None
    except OSError:
        return None
    return path


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_jsonl(path: Path, last: int) -> list:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-last:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def slim_me(me) -> dict | None:
    """Only what the brain uses from our account: no venue settings, no threads."""
    if not isinstance(me, dict):
        return None
    keep = ("id", "cash", "tick", "level", "unlocked", "affinity", "collection_value", "album", "score")
    out = {k: me[k] for k in keep if k in me}
    out["assets"] = [{k: a.get(k) for k in ("id", "kind", "ref", "set", "rarity", "your_value")}
                     for a in me.get("assets") or [] if isinstance(a, dict)]
    return out


def collect(repo: Path, live: Path, now: float | None = None) -> dict:
    """Read the allowlist once and return the scrubbed bundle."""
    roots = {"repo": repo, "live": live}
    bundle = {"kind": "team", "at": now if now is not None else time.time(), "files": {}, "desks": []}
    for name, (root, rel) in FILES.items():
        path = safe_path(roots[root], rel)
        if path is None:
            continue
        try:
            bundle["files"][rel] = round(path.stat().st_mtime, 1)
        except OSError:
            continue
        if name == "me":
            bundle["me"] = slim_me(read_json(path))
        elif name == "score_state":
            bundle["score_state"] = read_json(path)
        elif name == "decisions":
            bundle["decisions"] = read_jsonl(path, MAX_DECISIONS)
        elif name == "score_rows":
            bundle["score_rows"] = read_jsonl(path, MAX_SCORE_ROWS)
        elif name.startswith("desk:"):
            d = read_json(path)
            if isinstance(d, dict):
                bundle["desks"].append({**d, "_file": rel, "_mtime": bundle["files"][rel]})
    return scrub(bundle, MAX_TEXT)


def encode(bundle: dict) -> bytes:
    """The bundle as JSON under MAX_BYTES: the oldest decisions are dropped first if it is too big."""
    body = json.dumps(bundle, ensure_ascii=False).encode()
    while len(body) > MAX_BYTES and bundle.get("decisions"):
        bundle["decisions"] = bundle["decisions"][len(bundle["decisions"]) // 4 + 1:]
        body = json.dumps(bundle, ensure_ascii=False).encode()
    return body


def send(body: bytes, url: str, token: str) -> int:
    req = urllib.request.Request(url.rstrip("/") + "/ingest/team", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Brain-Write": token})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def write(body: bytes, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(out)


def load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def summary(b: dict) -> str:
    me, st = b.get("me") or {}, (b.get("score_state") or {}).get("prev") or {}
    return (f"account t{me.get('tick')} · live score t{st.get('tick')} cash {st.get('cash')} · "
            f"{len(b.get('decisions') or [])} decisions · {len(b.get('desks') or [])} desks")


def main() -> None:
    ap = argparse.ArgumentParser(description="Relay the team's live files (keyless, allowlisted) to the market brain.")
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="the key machine's clone (read only)")
    ap.add_argument("--live", type=Path, default=DEFAULT_LIVE, help="the key machine's live view folder (read only)")
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV, help="KEY=VALUE file with BRAIN_URL and BRAIN_WRITE_TOKEN")
    ap.add_argument("--out", type=Path, help="write the bundle to this file instead of POSTing it")
    ap.add_argument("--every", type=float, default=RELAY_SECONDS)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the scrubbed bundle's summary and size, send nothing")
    args = ap.parse_args()
    load_env(args.env)
    url, token = os.environ.get("BRAIN_URL"), os.environ.get("BRAIN_WRITE_TOKEN")
    if not (args.out or args.dry_run) and not (url and token):
        raise SystemExit(f"missing BRAIN_URL / BRAIN_WRITE_TOKEN (environment or {args.env})")
    while True:
        try:
            b = collect(args.repo, args.live)
            body = encode(b)
            if args.dry_run:
                status = f"dry run, {len(body)} bytes, fields {sorted(b)}"
            elif args.out:
                write(body, args.out)
                status = f"wrote {args.out} ({len(body)} bytes)"
            else:
                status = f"{send(body, url, token)} ({len(body)} bytes)"
            print(time.strftime("%H:%M:%S"), summary(b), "→", status, flush=True)
        except Exception as e:  # a share unmounted, the brain restarting, a network blip: try again next round
            print(time.strftime("%H:%M:%S"), f"relay failed: {type(e).__name__}: {e}"[:300], flush=True)
        if args.once or args.dry_run:
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
