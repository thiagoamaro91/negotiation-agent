"""Push our account (cash, cards, private multipliers) to the market brain, so its plan knows exactly what we hold,
pack pulls included, while the team key never leaves this laptop.

    python3 tools/me_relay.py            # every RELAY_SECONDS until stopped; run it on ONE laptop that holds the key
    python3 tools/me_relay.py --once

Reads BAZAAR_KEY, BRAIN_URL (e.g. https://fable-vm.<tailnet>.ts.net) and BRAIN_WRITE_TOKEN from .env or the
environment. One keyed read (GET /api/me) every RELAY_SECONDS: ~0.05 requests per second, far under the 5 per second
the key allows. Any field whose name contains "key" (the stall's broker key, for one) is dropped before sending.
It never sends anything to the game.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
from bazaar_sdk import Bazaar  # noqa: E402

RELAY_SECONDS = 20.0


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def scrub(x):
    """Drop every field whose name mentions a key, at any depth."""
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items() if "key" not in k.lower()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return x


def push(b: Bazaar, url: str, token: str) -> str:
    me = scrub(b.me())
    req = urllib.request.Request(url.rstrip("/") + "/ingest/me", data=json.dumps(me).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Brain-Write": token})
    with urllib.request.urlopen(req, timeout=15) as r:
        return f"tick {me.get('tick')} cash {me.get('cash')} cards {sum(1 for a in me.get('assets', []) if a.get('kind') == 'card')}: {r.status}"


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Relay our account to the market brain.")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    missing = [k for k in ("BAZAAR_KEY", "BRAIN_URL", "BRAIN_WRITE_TOKEN") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing {', '.join(missing)} (in .env or the environment)")
    b = Bazaar(os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai"), os.environ["BAZAAR_KEY"])
    while True:
        try:
            print(time.strftime("%H:%M:%S"), push(b, os.environ["BRAIN_URL"], os.environ["BRAIN_WRITE_TOKEN"]), flush=True)
        except Exception as e:  # the brain restarting, a network blip: try again next round
            print(time.strftime("%H:%M:%S"), f"relay failed: {e}", flush=True)
        if args.once:
            return
        time.sleep(RELAY_SECONDS)


if __name__ == "__main__":
    main()
