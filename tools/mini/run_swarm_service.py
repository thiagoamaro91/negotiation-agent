#!/usr/bin/env python3
"""Validate the deployed Swarm release and replace this process with it."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


DEFAULT_DEPLOY_ROOT = Path("/Users/thiago/bazaar-deploy")
DEFAULT_ENV_FILE = Path("/Users/thiago/bazaar-swarm/swarm.env")
DEFAULT_REPO = Path("/Users/thiago/bazaar")
DEFAULT_LIVE = Path("/Users/thiago/bazaar-live")
DEFAULT_OUT = Path("/Users/thiago/bazaar-live")
RELEASE_RE = re.compile(r"[0-9a-f]{40}")


class ConfigError(ValueError):
    """A safe startup error that never contains a secret value."""


def read_swarm_token(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"cannot read Swarm environment file {path}: {exc.strerror or exc}") from exc

    token = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if sep and key.strip() == "SWARM_TOKEN":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if token is not None:
                raise ConfigError(f"SWARM_TOKEN is defined more than once in {path}")
            token = value

    if token is None:
        raise ConfigError(f"SWARM_TOKEN is missing from {path}")
    if len(token) < 16:
        raise ConfigError(f"SWARM_TOKEN in {path} must contain at least 16 characters")
    return token


def resolve_release(deploy_root: Path) -> tuple[Path, Path]:
    current = deploy_root / "current"
    if not current.is_symlink():
        raise ConfigError(f"deployed release link is missing or is not a symlink: {current}")

    try:
        releases = (deploy_root / "releases").resolve(strict=True)
        release = current.resolve(strict=True)
    except OSError as exc:
        raise ConfigError(f"cannot resolve deployed Swarm release: {exc.strerror or exc}") from exc

    if not releases.is_dir():
        raise ConfigError(f"release directory is not a directory: {releases}")
    if release.parent != releases or not RELEASE_RE.fullmatch(release.name) or not release.is_dir():
        raise ConfigError(f"current does not resolve to a full-SHA release under {releases}")

    swarm = release / "tools" / "swarm.py"
    if not swarm.is_file():
        raise ConfigError(f"deployed release is missing tools/swarm.py: {release}")
    return release, swarm


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-root", type=Path, default=DEFAULT_DEPLOY_ROOT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--check", action="store_true", help="validate configuration without starting Swarm")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        release, swarm = resolve_release(args.deploy_root)
        token = read_swarm_token(args.env_file)
        python = args.python.resolve(strict=True)
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ConfigError(f"Python executable is not executable: {python}")
        if not 1 <= args.port <= 65535:
            raise ConfigError("Swarm port must be between 1 and 65535")
    except (ConfigError, OSError) as exc:
        print(f"run_swarm_service: {exc}", file=sys.stderr)
        return 2

    if args.check:
        print(f"Swarm service configuration OK: release {release.name}, {args.host}:{args.port}")
        return 0

    command = [
        str(python),
        "-u",
        str(swarm),
        "run",
        "--repo",
        str(args.repo),
        "--live",
        str(args.live),
        "--out",
        str(args.out),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    env = os.environ.copy()
    env["SWARM_TOKEN"] = token
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    os.chdir(release)
    os.execve(str(python), command, env)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
