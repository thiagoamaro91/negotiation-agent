#!/usr/bin/env python3
"""Run clock-stable safety checks against a candidate Swarm release."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


FIXTURE_DAY = dt.date(2026, 10, 3)
TEST_TOKEN = "x" * 20


class GateFailure(RuntimeError):
    """A validation failure with a message safe for deployment logs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def load_candidate(release: Path):
    try:
        release = release.resolve(strict=True)
    except OSError as exc:
        raise GateFailure(f"candidate release is unavailable: {exc.strerror or type(exc).__name__}") from exc
    tools = release / "tools"
    if not (tools / "swarm.py").is_file() or not (tools / "redaction.py").is_file():
        raise GateFailure("candidate release is missing tools/swarm.py or tools/redaction.py")
    sys.path.insert(0, str(tools))
    sys.dont_write_bytecode = True
    try:
        import swarm  # type: ignore
    except Exception as exc:
        raise GateFailure(f"candidate Swarm import failed: {type(exc).__name__}") from exc
    return release, swarm


def validate_redaction(swarm) -> int:
    credentials = (
        "tk-ab12-cd34",
        "bk_live_9fA2xQ7z",
        "bk-old-shape-1234",
        "adm_root_42",
    )
    for index, credential in enumerate(credentials):
        row = swarm.agents_event(
            "agents.log",
            str(index),
            FIXTURE_DAY,
            f"10:00:00 [conductor] says: credential {credential} end",
        )
        require(row is not None, "documented credential fixture was not parsed")
        require(credential not in row["text"], "documented credential shape was not redacted")
        require("<redacted>" in row["text"], "credential redaction marker is missing")
    return len(credentials)


def fixture_tree(swarm, root: Path) -> tuple[Path, Path, Path]:
    live, repo, out = root / "live", root / "repo", root / "out"
    (repo / "logs" / "broker").mkdir(parents=True)
    live.mkdir()
    out.mkdir()

    agents = live / "agents.log"
    agents.write_text(
        "16:48:56 [lane-d-ladder] does: message to lane-c-trades: fixture message\n"
        "16:49:00 [lane-c-trades] says: partial li",
        encoding="utf-8",
    )
    fixed_mtime = dt.datetime(2026, 10, 3, 18, 0, tzinfo=swarm.LOCAL_TZ).timestamp()
    os.utime(agents, (fixed_mtime, fixed_mtime))

    decision = {
        "ts": "2026-10-03T17:16:48+0200",
        "tick": 844,
        "lane": "trades",
        "action": "accept",
        "card": "LAV-10",
        "counterparty": "t07",
        "venue": "rastro",
        "price": 38,
        "why": "fixture reason",
        "result": "FILLED",
    }
    (live / "decisions.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    match = {
        "ts": "2026-10-03T17:55:28",
        "agent": "broker",
        "event": "matched",
        "sell": "fixture-sell",
        "buy": "fixture-buy",
        "price": 43,
    }
    (repo / "logs" / "broker" / "2026-10-03.jsonl").write_text(
        json.dumps(match) + "\n", encoding="utf-8"
    )
    return live, repo, out


def fold_once(swarm, live: Path, repo: Path, store) -> int:
    folder = swarm.Folder(live, repo, store.state(), bus=False)
    return store.add(folder.fold(), folder.st)


def validate_folding(swarm, root: Path):
    live, repo, out = fixture_tree(swarm, root)
    store = swarm.Store(out)
    require(fold_once(swarm, live, repo, store) == 3, "initial fold count is incorrect")
    require(
        [row["kind"] for row in store.events] == ["msg", "decision", "match"],
        "folded events are not chronological",
    )
    require(fold_once(swarm, live, repo, store) == 0, "incremental fold duplicated existing events")
    with (live / "agents.log").open("a", encoding="utf-8") as handle:
        handle.write("ne\n")
    require(fold_once(swarm, live, repo, store) == 1, "completed partial line was not added exactly once")
    require(store.events[-1]["text"] == "partial line", "completed partial line was parsed incorrectly")
    return live, repo, store


def validate_visibility_and_binding(swarm) -> int:
    require(bool(swarm.bind_problem("127.0.0.1", None, False)), "private view accepted a missing token")
    require(bool(swarm.bind_problem("127.0.0.1", "short", False)), "private view accepted a short token")
    for host in ("", "0.0.0.0", "::", "*"):
        require(bool(swarm.bind_problem(host, TEST_TOKEN, False)), "private view accepted a wildcard bind")
    require(swarm.bind_problem("127.0.0.1", TEST_TOKEN, False) is None, "private loopback binding was rejected")

    private = swarm.event(
        "fixture",
        "1",
        "2026-10-03T12:00:00+02:00",
        "conductor",
        "bus",
        "decision",
        "internal fixture text",
        "internal fixture reason",
        "internal fixture highlight",
    )
    public = swarm.public_view(private)
    require(public.get("text") == "", "public view retained internal text")
    require(public.get("why") is None, "public view retained an internal reason")
    require("highlight" not in public, "public view retained an internal highlight")
    return 6


def get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.load(response)
    except Exception as exc:
        raise GateFailure(f"local HTTP validation request failed: {type(exc).__name__}") from exc


def validate_http(swarm, live: Path, repo: Path, store) -> int:
    server = swarm.ThreadingHTTPServer(
        ("127.0.0.1", 0), swarm.make_handler(store, live, repo, TEST_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    query = urllib.parse.urlencode({"t": TEST_TOKEN})
    try:
        for path in ("/events?since=0", "/meta"):
            try:
                with urllib.request.urlopen(base + path, timeout=5):
                    pass
            except urllib.error.HTTPError as exc:
                require(exc.code == 403, "unauthenticated endpoint returned the wrong status")
                exc.close()
            except Exception as exc:
                raise GateFailure(f"unauthenticated endpoint check failed: {type(exc).__name__}") from exc
            else:
                raise GateFailure("private endpoint accepted a missing token")

        status, events = get_json(base + "/events?since=0&" + query)
        require(status == 200 and events.get("next") == len(store.events), "authenticated events endpoint is invalid")
        require(len(events.get("events", [])) == len(store.events), "events endpoint omitted folded events")
        status, meta = get_json(base + "/meta?" + query)
        require(status == 200 and "conductor" in meta.get("nodes", {}), "authenticated metadata endpoint is invalid")
        require(meta.get("public") is False, "private endpoint reported public scope")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    require(not thread.is_alive(), "local HTTP validation server did not stop")
    return 4


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True, help="candidate release root")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        release, swarm = load_candidate(args.release)
        redactions = validate_redaction(swarm)
        with tempfile.TemporaryDirectory(prefix="swarm-release-gate-") as temp:
            live, repo, store = validate_folding(swarm, Path(temp))
            gates = validate_visibility_and_binding(swarm)
            endpoints = validate_http(swarm, live, repo, store)
    except (GateFailure, AssertionError, OSError, ValueError, TypeError) as exc:
        print(f"validate_swarm_release: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        f"validate_swarm_release: PASS release={release.name} "
        f"redactions={redactions} events={len(store.events)} gates={gates} endpoints={endpoints}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
