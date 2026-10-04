# Mini autodeploy runbook

`autodeploy.py` fetches one Git branch into a dedicated bare cache, validates a full tracked source snapshot, atomically changes the `current` symlink, restarts the Swarm LaunchAgent, and checks its private `/meta` endpoint. It never runs Git commands in `/Users/thiago/bazaar`.

## Files and state

With `deploy_root` set to `/Users/thiago/bazaar-deploy`, the watcher owns:

- `repo.git`: fetched bare repository cache
- `releases/<commit>`: immutable tracked source snapshots without `.git`
- `manifests/<commit>.json`: external SHA-256 source integrity records
- `current`: atomic symlink to the active release
- `status.json`: last attempt, staged revision, last successful revision, timestamps, result, and scrubbed error
- `deploy.lock`: nonblocking process lock

Release history is retained. Secrets, runtime logs, `swarm-events.jsonl`, and `swarm-state.json` stay in external paths.

## Configuration

Create `/Users/thiago/bazaar-deploy/config.json` with mode `0600`:

```json
{
  "deploy_root": "/Users/thiago/bazaar-deploy",
  "remote_url": "https://github.com/thiagoamaro91/negotiation-agent.git",
  "branch": "main",
  "git": "/usr/bin/git",
  "launchctl": "/bin/launchctl",
  "ps": "/bin/ps",
  "lsof": "/usr/sbin/lsof",
  "service_label": "com.thiago.bazaar-swarm",
  "fetch_timeout_seconds": 30,
  "validation_timeout_seconds": 120,
  "validation_commands": [
    {
      "argv": ["/opt/homebrew/bin/python3", "-m", "compileall", "-q", "agent", "tools", "kit"],
      "cwd": "."
    },
    {
      "argv": ["/opt/homebrew/bin/python3", "/Users/thiago/bazaar-deploy/agent/validate_swarm_release.py", "--release", "."],
      "cwd": "."
    }
  ],
  "health": {
    "url": "http://127.0.0.1:8777/meta",
    "env_file": "/Users/thiago/bazaar-swarm/swarm.env",
    "token_key": "SWARM_TOKEN",
    "attempts": 20,
    "interval_seconds": 0.5,
    "request_timeout_seconds": 2
  }
}
```

Each validation entry uses an argv array, an optional release-relative `cwd`, and an optional `timeout_seconds`. Shell parsing is never used. Validation may generate Python caches. The watcher then verifies tracked source against the external checksum manifest and removes write permission from the whole release.

As of 2026-10-04, the merged upstream `test_swarm.py` suite reports 30 of 32 passing because two fixed synthetic fixtures depend on a narrower token shape and an Oct 3 file timestamp. The installed host gate above checks the same release with a real token shape and controlled timestamps. Keep the upstream result visible; do not suppress or modify those repository tests during deployment.

The health URL must be query-free HTTP `/meta` on loopback. Redirects are refused. A healthy private Swarm must return 403 without the token and 200 with the token read from the external env file. The LaunchAgent PID must also have the resolved active `releases/<commit>/tools/swarm.py` in its command line, and `lsof` must show that same PID listening on the health port.

## Install and first activation

Install the watcher outside the release tree so it can update `current` safely:

```sh
/usr/bin/install -d -m 0755 /Users/thiago/bazaar-deploy/agent
/usr/bin/install -m 0755 /Users/thiago/bazaar/tools/mini/autodeploy.py /Users/thiago/bazaar-deploy/agent/autodeploy.py
/opt/homebrew/bin/python3 /Users/thiago/bazaar-deploy/agent/autodeploy.py --config /Users/thiago/bazaar-deploy/config.json --prepare
```

`--prepare` fetches, validates, and flips `current`, then records `staged_pending_health`. Use it only for the first release before the Swarm service is installed. It does not record a successful deployment.

After installing and bootstrapping the Swarm LaunchAgent, run one normal attempt:

```sh
/opt/homebrew/bin/python3 /Users/thiago/bazaar-deploy/agent/autodeploy.py --config /Users/thiago/bazaar-deploy/config.json --once
```

The normal run restarts `com.thiago.bazaar-swarm`, checks both authenticated and unauthenticated responses, and only then records `success`. A LaunchAgent can invoke that same command every 60 seconds with `StartInterval`. An overlapping invocation exits successfully with `locked`; an already successful unchanged commit exits successfully with `unchanged`.

## External token-gated link

`com.thiago.bazaar-swarm-tunnel` runs a dedicated Cloudflare quick tunnel from the public hostname to `http://127.0.0.1:8777`. The current public base URL is written atomically to `/Users/thiago/bazaar-swarm/tunnel.url`; append `/?t=<SWARM_TOKEN>` when opening the graph. Keep that complete authenticated URL private.

The quick-tunnel hostname changes only when its cloudflared process restarts. Ordinary deployments restart `com.thiago.bazaar-swarm` on the same loopback port, so the tunnel process and current public hostname remain in place while the backend changes release.

## Operations

Read status without touching the dirty working checkout:

```sh
/usr/bin/python3 -m json.tool /Users/thiago/bazaar-deploy/status.json
/bin/readlink /Users/thiago/bazaar-deploy/current
/bin/launchctl print gui/$(/usr/bin/id -u)/com.thiago.bazaar-swarm
```

Validation or integrity failure leaves `current` unchanged. Restart, process identity, listener ownership, or HTTP health failure restores the last successfully deployed release, restarts it, and verifies the restored process and health before reporting the rollback as successful. A rewritten branch is refused when the fetched commit is not a descendant of the last success. If the very first activation has no prior successful release, the failure is recorded and left for diagnosis because there is no rollback target.

The release snapshot includes ordinary tracked files. Git metadata is absent, submodule contents are not expanded, and Git LFS objects are not downloaded by `git archive`. The watcher intentionally does not delete old releases. It also refuses an integrity mismatch instead of deleting or rebuilding the suspect release; an operator must quarantine that exact release directory and its matching manifest before retrying.
