"""Open Team 3's own venue: a zero-fee `board` market that only our broker (agent/broker.py) matches.

Opening costs a refundable bond of 250 P plus 20 P (RULES.md, "Your own market"); the bond comes back after we close
the venue and a cooldown. A refused opening costs nothing. Each Market Test session counts the best venue we have open
during it, so once opened the venue stays open all weekend, with the broker running: on a board venue nothing matches
without it.

    python3 tools/open_venue.py plan           # prints the exact request body; sends nothing
    python3 tools/open_venue.py run --yes      # POST /api/venues with the team key from .env (owner's yes only)

`run` creates ~/.bazaar/broker.env (mode 600) BEFORE the POST, writes the broker key it gets back into it
(BROKER_KEY=...) WITHOUT printing it, and prints only the venue id. It refuses to overwrite an existing key file. The
key is returned only once, so if that write fails it goes to a fallback file next to it (broker.env.recovery-<pid>,
mode 600) with a recovery message, and only if that fails too is it printed to stderr as the last resort. The key holder then copies that file to the VM
(~/.bazaar/broker.env, mode 600) where `python3 agent/broker.py run` reads it. The key never passes through a chat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar, BazaarError  # noqa: E402

URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
KEY_FILE = Path.home() / ".bazaar" / "broker.env"
COST = "250 P bond (refundable after closing) + 20 P"

# The request. Fee 0: fees never score, and any fee shrinks the pairs that cross (price + fee <= bid). No rarity, set
# or level restriction: they only cut traffic. "board": our broker matches; on "auto" the engine crosses every pair
# first and a broker can do nothing (the free stall is auto).
NAME = "La Celestina · finds your missing card"  # at most 40 characters (the server cuts longer names)
BODY = {
    "name": NAME,
    "fee_bps": 0,
    "fee_per_card": 0,
    "rules": {"mechanism": "board"},
    "description": "Zero fees. Our broker crosses every matching bid and ask, card by card, every tick.",
}


def load_team_key() -> str:
    """BAZAAR_KEY from the environment or the repo's .env. Returned, never printed."""
    key = os.environ.get("BAZAAR_KEY", "").strip()
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("BAZAAR_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("no team key: set BAZAAR_KEY or put it in .env")
    return key


def venue_id(r: dict):
    """The new venue's id, wherever the response puts it ("v05", or inside a venue object)."""
    v = r.get("venue")
    if isinstance(v, dict):
        return v.get("venue") or v.get("id")
    return v or r.get("id") or r.get("venue_id")


def reserve_key_file(path: Path) -> int:
    """Create the empty key file (directory 700, file 600, never overwritten) and return its open fd. Done BEFORE the
    POST, so a key returned by the server always has a writable home."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.chmod(path, 0o600)
    return fd


def fill_key_file(fd: int, key: str) -> None:
    """Write BROKER_KEY=... into a reserved fd, flushed to disk, and close it."""
    with os.fdopen(fd, "w") as f:
        f.write(f"BROKER_KEY={key}\n")
        f.flush()
        os.fsync(f.fileno())


def write_key(path: Path, key: str) -> None:
    """BROKER_KEY=... in a new file only the owner can read (directory 700, file 600, never overwritten)."""
    fill_key_file(reserve_key_file(path), key)


def fallback_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.recovery-{os.getpid()}")


def save_key(fd: int, path: Path, key: str) -> Path:
    """Write the broker key (returned only once) so it can never be lost: the reserved file first; if that fails, a
    fallback file next to it (mode 600) plus an explicit recovery message; if both fail, print it to stderr as the
    last resort. Returns the path that holds the key (or the main path when it had to be printed)."""
    try:
        fill_key_file(fd, key)
        return path
    except Exception as e:  # noqa: BLE001 - anything here would lose a key the server never returns again
        print(f"WARNING: writing the broker key to {path} FAILED ({type(e).__name__}: {e}). The venue IS open.",
              file=sys.stderr)
    fb = fallback_path(path)
    try:
        write_key(fb, key)
        print(f"RECOVERY: the broker key was saved to {fb} (mode 600). Move it into place with:\n"
              f"    mv '{fb}' '{path}'   (remove the empty or partial {path} first)", file=sys.stderr)
        return fb
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: the fallback {fb} also FAILED ({type(e).__name__}: {e}).", file=sys.stderr)
    print("LAST RESORT, the key is shown once and only here. Put this line in "
          f"{path} (mode 600) and clear this terminal:\nBROKER_KEY={key}", file=sys.stderr)
    return path


def cmd_plan(_args) -> None:
    assert len(BODY["name"]) <= 40, "venue names are cut at 40 characters"
    print(f"POST {URL}/api/venues  (header X-Team-Key from .env; costs {COST})")
    print(json.dumps(BODY, ensure_ascii=False, indent=1))


def cmd_run(args) -> None:
    key_file = Path(args.key_file).expanduser()
    if not args.yes:
        cmd_plan(args)
        raise SystemExit(f"\nnot sent: add --yes to open the venue ({COST}). Only with the owner's yes in the chat.")
    if key_file.exists():
        raise SystemExit(f"{key_file} already exists: a broker key is there already. Move it away first; not sent.")
    team_key = load_team_key()
    try:  # the key file exists and is writable BEFORE we pay: the broker key is only returned once
        fd = reserve_key_file(key_file)
    except OSError as e:
        raise SystemExit(f"cannot create {key_file} ({e}); not sent.")
    b = Bazaar(URL, team_key, wait_on_tick=False, retries=0)
    try:
        r = b.open_venue(BODY["name"], fee_bps=BODY["fee_bps"], fee_per_card=BODY["fee_per_card"],
                         rules=BODY["rules"], description=BODY["description"])
    except BazaarError as e:  # a refused opening costs nothing
        os.close(fd)
        key_file.unlink(missing_ok=True)  # empty placeholder: nothing to keep
        raise SystemExit(f"refused: {e.code} ({e.status}): {e.message[:200]}")
    except BaseException:
        os.close(fd)  # unknown outcome: keep the empty file so a blind re-run cannot open a second venue
        print(f"the request failed with an unknown outcome; check GET /api/venues. {key_file} stays (empty) as a "
              "guard against opening twice.", file=sys.stderr)
        raise
    if not isinstance(r, dict) or not r.get("broker_key"):
        os.close(fd)
        fields = sorted(r) if isinstance(r, dict) else type(r).__name__
        raise SystemExit(f"opened? the response has no broker_key (fields: {fields}). Check GET /api/venues. "
                         f"{key_file} stays (empty) as a guard against opening twice.")
    where = save_key(fd, key_file, str(r["broker_key"]))
    print(f"venue {venue_id(r)} opened; broker key written to {where} (mode 600, not shown)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("plan", help="print the request body; sends nothing")
    r = sub.add_parser("run", help="open the venue (costs money: owner's yes only)")
    r.add_argument("--yes", action="store_true", help="really send it")
    r.add_argument("--key-file", default=str(KEY_FILE))
    args = ap.parse_args(argv)
    {"plan": cmd_plan, "run": cmd_run}[args.mode](args)


if __name__ == "__main__":
    main()
