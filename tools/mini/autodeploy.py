#!/usr/bin/env python3
"""Deploy an immutable release from one fetched Git branch on a macOS Mini."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Callable


class DeployError(RuntimeError):
    """A bounded deployment failure suitable for the status file."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def scrub(message: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(message).replace("\n", " ").replace("\r", " ")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1<redacted>@", text)
    return text[:4000]


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise DeployError(f"cannot read status file: {exc.__class__.__name__}") from exc
    if not isinstance(value, dict):
        raise DeployError("status file must contain a JSON object")
    return value


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeployError(f"cannot read config: {exc.__class__.__name__}") from exc
    if not isinstance(config, dict):
        raise DeployError("config must contain a JSON object")
    required = ("deploy_root", "remote_url", "branch", "service_label", "health")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise DeployError("config missing required keys: " + ", ".join(missing))
    if not isinstance(config.get("validation_commands", []), list):
        raise DeployError("validation_commands must be a list")
    if not isinstance(config["health"], dict):
        raise DeployError("health must be a JSON object")
    return config


def command_error(argv: list[str], proc: subprocess.CompletedProcess[str]) -> DeployError:
    detail = (proc.stderr or proc.stdout or "no command output").strip()
    return DeployError(f"command failed ({proc.returncode}): {Path(argv[0]).name}: {detail}")


def run_command(
    argv: list[str], *, cwd: Path | None = None, timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    if not argv or not all(isinstance(part, str) and part for part in argv):
        raise DeployError("command argv must be a nonempty list of strings")
    try:
        proc = subprocess.run(
            argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"command timed out: {Path(argv[0]).name}") from exc
    except OSError as exc:
        raise DeployError(f"cannot run {Path(argv[0]).name}: {exc.__class__.__name__}") from exc
    if proc.returncode:
        raise command_error(argv, proc)
    return proc


def _safe_member_path(root: Path, member_name: str) -> Path:
    posix = PurePosixPath(member_name)
    if posix.is_absolute() or not posix.parts or any(part in ("", ".", "..") for part in posix.parts):
        raise DeployError("git archive contains an unsafe path")
    target = root.joinpath(*posix.parts)
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise DeployError("git archive path escapes release directory") from exc
    return target


def extract_archive(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            target = _safe_member_path(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isreg():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise DeployError("cannot read file from git archive")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(target, member.mode & 0o777)
            elif member.issym():
                target.parent.mkdir(parents=True, exist_ok=True)
                link = PurePosixPath(member.linkname)
                if link.is_absolute():
                    raise DeployError("git archive contains an absolute symlink")
                resolved = target.parent.joinpath(*link.parts).resolve(strict=False)
                try:
                    resolved.relative_to(destination.resolve())
                except ValueError as exc:
                    raise DeployError("git archive symlink escapes release directory") from exc
                os.symlink(member.linkname, target)
            else:
                raise DeployError("git archive contains an unsupported entry type")


def read_env_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DeployError(f"cannot read health env file: {exc.__class__.__name__}") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value
    raise DeployError(f"health token key {key} is absent")


def _http_status(url: str, timeout: float) -> int:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(url, timeout=timeout) as response:
            response.read(1)
            return response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        return code
    except (OSError, urllib.error.URLError, TimeoutError):
        return 0


def check_health(settings: dict[str, Any]) -> None:
    base_url = str(settings.get("url", ""))
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise DeployError("health URL must use HTTP on localhost")
    if parsed.path != "/meta" or parsed.query or parsed.fragment:
        raise DeployError("health URL must be the query-free /meta endpoint")
    token_key = str(settings.get("token_key", "SWARM_TOKEN"))
    token = read_env_value(Path(str(settings.get("env_file", ""))).expanduser(), token_key)
    if len(token) < 16:
        raise DeployError("health token must contain at least 16 characters")
    authenticated = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode({"t": token})))
    attempts = max(1, int(settings.get("attempts", 20)))
    interval = max(0.0, float(settings.get("interval_seconds", 0.5)))
    timeout = max(0.1, float(settings.get("request_timeout_seconds", 2)))
    for attempt in range(attempts):
        if _http_status(base_url, timeout) == 403 and _http_status(authenticated, timeout) == 200:
            return
        if attempt + 1 < attempts:
            time.sleep(interval)
    raise DeployError("health check did not return 403 unauthenticated and 200 authenticated")


class Deployer:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        command: Callable[..., subprocess.CompletedProcess[str]] = run_command,
        health_checker: Callable[[dict[str, Any]], None] = check_health,
        identity_checker: Callable[[Path], None] | None = None,
        restarter: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.root = Path(str(config["deploy_root"])).expanduser().resolve()
        self.repo = self.root / "repo.git"
        self.releases = self.root / "releases"
        self.manifests = self.root / "manifests"
        self.current = self.root / "current"
        self.status_path = self.root / "status.json"
        self.command = command
        self.health_checker = health_checker
        self._identity_checker = identity_checker
        self.git = str(config.get("git", "/usr/bin/git"))
        self.fetch_timeout = float(config.get("fetch_timeout_seconds", 30))
        self.validation_timeout = float(config.get("validation_timeout_seconds", 120))
        self._restarter = restarter

    def cmd(self, argv: list[str], *, cwd: Path | None = None, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        return self.command(argv, cwd=cwd, timeout=timeout)

    def git_cmd(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        return self.cmd([self.git, f"--git-dir={self.repo}", *args], timeout=timeout or self.fetch_timeout)

    def fetch(self) -> str:
        if not self.repo.exists():
            self.repo.parent.mkdir(parents=True, exist_ok=True)
            self.cmd([self.git, "init", "--bare", str(self.repo)], timeout=self.fetch_timeout)
        remote = str(self.config["remote_url"])
        try:
            existing = self.git_cmd("remote", "get-url", "origin").stdout.strip()
        except DeployError:
            self.git_cmd("remote", "add", "origin", remote)
        else:
            if existing != remote:
                self.git_cmd("remote", "set-url", "origin", remote)
        branch = str(self.config["branch"])
        ref = f"refs/remotes/origin/{branch}"
        self.git_cmd(
            "fetch", "--no-tags", "--prune", "origin",
            f"+refs/heads/{branch}:{ref}", timeout=self.fetch_timeout,
        )
        revision = self.git_cmd("rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise DeployError("fetched branch did not resolve to a commit")
        return revision

    def is_ancestor(self, older: str, newer: str) -> bool:
        proc = subprocess.run(
            [self.git, f"--git-dir={self.repo}", "merge-base", "--is-ancestor", older, newer],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.fetch_timeout,
            check=False,
        )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        raise command_error([self.git, "merge-base"], proc)

    def stage_release(self, revision: str) -> Path:
        release = self.releases / revision
        if release.is_dir():
            self.verify_manifest(revision, release)
            return release
        if release.exists():
            raise DeployError("release path exists but is not a directory")
        self.releases.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=self.releases))
        archive = work.parent / f".{revision}.{os.getpid()}.tar"
        try:
            self.git_cmd("archive", "--format=tar", f"--output={archive}", revision)
            extract_archive(archive, work)
            manifest = self.build_manifest(revision, work)
            atomic_json(self.manifests / f"{revision}.json", manifest)
            os.replace(work, release)
        finally:
            archive.unlink(missing_ok=True)
            if work.exists():
                shutil.rmtree(work)
        return release

    @staticmethod
    def cache_artifact(relative: str) -> bool:
        path = PurePosixPath(relative)
        return (
            "__pycache__" in path.parts or ".pytest_cache" in path.parts
            or path.suffix in (".pyc", ".pyo")
        )

    def build_manifest(self, revision: str, release: Path) -> dict[str, Any]:
        files = []
        for path in sorted(release.rglob("*"), key=lambda value: value.as_posix()):
            relative = path.relative_to(release).as_posix()
            if path.is_symlink():
                value = os.readlink(path).encode("utf-8", "surrogateescape")
                kind = "symlink"
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                files.append({"path": relative, "kind": "file", "sha256": digest.hexdigest()})
                continue
            elif path.is_dir():
                continue
            else:
                raise DeployError("release contains an unsupported filesystem entry")
            files.append({"path": relative, "kind": kind, "sha256": hashlib.sha256(value).hexdigest()})
        return {"version": 1, "revision": revision, "files": files}

    def verify_manifest(self, revision: str, release: Path) -> None:
        manifest_path = self.manifests / f"{revision}.json"
        manifest = read_json(manifest_path)
        if manifest.get("revision") != revision or not isinstance(manifest.get("files"), list):
            raise DeployError("release integrity manifest is missing or invalid")
        expected = {}
        for item in manifest["files"]:
            if not isinstance(item, dict) or not all(item.get(key) for key in ("path", "kind", "sha256")):
                raise DeployError("release integrity manifest contains an invalid entry")
            expected[str(item["path"])] = item
        current = self.build_manifest(revision, release)
        actual = {str(item["path"]): item for item in current["files"]}
        for path, item in expected.items():
            if actual.get(path) != item:
                raise DeployError(f"release source integrity mismatch: {path}")
        extras = [path for path in actual if path not in expected and not self.cache_artifact(path)]
        if extras:
            raise DeployError(f"release contains unexpected source: {extras[0]}")

    @staticmethod
    def freeze_release(release: Path) -> None:
        paths = sorted(release.rglob("*"), key=lambda value: len(value.parts), reverse=True)
        for path in paths:
            if path.is_symlink():
                continue
            mode = path.stat().st_mode & 0o777
            os.chmod(path, mode & ~0o222)
        os.chmod(release, (release.stat().st_mode & 0o777) & ~0o222)

    def validate(self, release: Path) -> None:
        for item in self.config.get("validation_commands", []):
            if isinstance(item, list):
                argv, relative, timeout = item, ".", self.validation_timeout
            elif isinstance(item, dict):
                argv = item.get("argv")
                relative = item.get("cwd", ".")
                timeout = float(item.get("timeout_seconds", self.validation_timeout))
            else:
                raise DeployError("each validation command must be an argv list or object")
            if not isinstance(argv, list):
                raise DeployError("validation command argv must be a list")
            cwd = (release / str(relative)).resolve()
            try:
                cwd.relative_to(release.resolve())
            except ValueError as exc:
                raise DeployError("validation cwd escapes the release") from exc
            if not cwd.is_dir():
                raise DeployError("validation cwd is not a directory")
            self.cmd(argv, cwd=cwd, timeout=timeout)

    def current_revision(self) -> str | None:
        if not self.current.is_symlink():
            return None
        try:
            target = self.current.resolve(strict=True)
            target.relative_to(self.releases.resolve())
        except (OSError, ValueError):
            return None
        return target.name if re.fullmatch(r"[0-9a-f]{40,64}", target.name) else None

    def flip_current(self, revision: str) -> None:
        release = self.releases / revision
        if not release.is_dir():
            raise DeployError("cannot activate a missing release")
        if self.current.exists() and not self.current.is_symlink():
            raise DeployError("current exists but is not a symlink")
        temp = self.root / f".current.{os.getpid()}"
        temp.unlink(missing_ok=True)
        os.symlink(Path("releases") / revision, temp)
        os.replace(temp, self.current)

    def restart(self) -> None:
        if self._restarter is not None:
            self._restarter()
            return
        launchctl = str(self.config.get("launchctl", "/bin/launchctl"))
        label = str(self.config["service_label"])
        self.cmd([launchctl, "kickstart", "-k", f"gui/{os.getuid()}/{label}"], timeout=30)

    def check_identity(self, release: Path) -> None:
        if self._identity_checker is not None:
            self._identity_checker(release)
            return
        launchctl = str(self.config.get("launchctl", "/bin/launchctl"))
        label = str(self.config["service_label"])
        ps = str(self.config.get("ps", "/bin/ps"))
        lsof = str(self.config.get("lsof", "/usr/sbin/lsof"))
        parsed = urllib.parse.urlsplit(str(self.config["health"].get("url", "")))
        port = parsed.port or 80
        attempts = max(1, int(self.config["health"].get("attempts", 20)))
        interval = max(0.0, float(self.config["health"].get("interval_seconds", 0.5)))
        expected = str((release / "tools" / "swarm.py").resolve())
        for attempt in range(attempts):
            try:
                details = self.cmd(
                    [launchctl, "print", f"gui/{os.getuid()}/{label}"], timeout=5,
                ).stdout
                match = re.search(r"(?m)^\s*pid = (\d+)\s*$", details)
                if not match:
                    raise DeployError("LaunchAgent has no PID")
                pid = match.group(1)
                command = self.cmd([ps, "-p", pid, "-o", "command="], timeout=5).stdout
                if expected not in command:
                    raise DeployError("LaunchAgent PID is not running the attempted release")
                sockets = self.cmd(
                    [lsof, "-nP", "-a", "-p", pid, f"-iTCP:{port}", "-sTCP:LISTEN"],
                    timeout=5,
                ).stdout
                if not sockets.strip():
                    raise DeployError("LaunchAgent PID does not own the health listener")
                return
            except DeployError:
                if attempt + 1 == attempts:
                    break
                time.sleep(interval)
        raise DeployError("service identity did not match the attempted release and listener")

    def record(self, status: dict[str, Any], **changes: Any) -> dict[str, Any]:
        status.update(changes)
        status["updated_at"] = utc_now()
        status["version"] = 1
        atomic_json(self.status_path, status)
        return status

    def rollback(self, revision: str | None) -> str:
        if not revision:
            return "no previous deployed release was available"
        try:
            self.flip_current(revision)
            self.restart()
            release = self.releases / revision
            self.check_identity(release)
            self.health_checker(self.config["health"])
            return "previous release restored, restarted, and verified"
        except Exception as exc:
            return "rollback failed: " + scrub(exc)

    def deploy(self, *, prepare: bool = False) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / "deploy.lock"
        lock = lock_path.open("a+")
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"result": "locked", "exit_code": 0}
            status = read_json(self.status_path)
            last_result = status.get("result")
            started = utc_now()
            status = self.record(status, attempt_started_at=started, attempted_revision=None, result="fetching", error=None)
            try:
                revision = self.fetch()
                status = self.record(status, attempted_revision=revision)
                deployed = status.get("deployed_revision")
                if deployed and deployed != revision and not self.is_ancestor(str(deployed), revision):
                    raise DeployError("refusing non-fast-forward deployment relative to last success")
                release = self.stage_release(revision)
                if deployed == revision and last_result in ("success", "unchanged") and self.current_revision() == revision:
                    return self.record(status, result="unchanged", error=None, exit_code=0)
                if prepare and last_result == "staged_pending_health" and status.get("staged_revision") == revision and self.current_revision() == revision:
                    return self.record(status, result="staged_pending_health", error=None, exit_code=0)
                self.validate(release)
                self.verify_manifest(revision, release)
                self.freeze_release(release)
                self.flip_current(revision)
                if prepare:
                    return self.record(
                        status, staged_revision=revision, staged_at=utc_now(),
                        result="staged_pending_health", error=None, exit_code=0,
                    )
                previous = str(deployed) if deployed else None
                try:
                    self.restart()
                    self.check_identity(release)
                    self.health_checker(self.config["health"])
                except Exception as exc:
                    rollback = self.rollback(previous)
                    raise DeployError(f"activation failed: {scrub(exc)}; {rollback}") from exc
                return self.record(
                    status, deployed_revision=revision, deployed_at=utc_now(), staged_revision=None,
                    result="success", error=None, exit_code=0,
                )
            except Exception as exc:
                secrets = (str(self.config.get("remote_url", "")),)
                return self.record(status, result="failed", error=scrub(exc, secrets), exit_code=1)
        finally:
            lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="deploy once (the default)")
    mode.add_argument("--prepare", action="store_true", help="stage, validate, and flip without restart or health")
    args = parser.parse_args(argv)
    try:
        result = Deployer(load_config(args.config)).deploy(prepare=args.prepare)
    except DeployError as exc:
        print("autodeploy: " + scrub(exc), file=sys.stderr)
        return 2
    print(f"autodeploy: {result['result']}")
    return int(result.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main())
