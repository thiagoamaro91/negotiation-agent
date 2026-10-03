#!/usr/bin/env bash
# Keep tools/team_relay.py running (keyless): it reads the key machine's own files from a fixed allowlist and posts
# them to the market brain. Restarted 5 s after it stops; the Mac is kept awake while it runs (caffeinate).
#
#   tools/run_team_relay.sh                                              # Hector's Mac: the Mini's shares in /Volumes
#   REPO=~/negotiation-agent LIVE=~/bazaar-live tools/run_team_relay.sh  # on the Mini itself (local paths)
#
# Needs BRAIN_URL and BRAIN_WRITE_TOKEN in ~/bazaar/brain-relay.env (chmod 600, not in the repo).
# Log: ~/bazaar/team_relay.log. Stop: Ctrl-C, or kill the loop.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${RELAY_LOG:-$HOME/bazaar/team_relay.log}"
mkdir -p "$(dirname "$LOG")"
KEEP=()
if command -v caffeinate >/dev/null 2>&1; then KEEP=(caffeinate -i); fi
echo "team relay: ${REPO:-/Volumes/bazaar} + ${LIVE:-/Volumes/bazaar-live} -> brain (log $LOG)"
while true; do
  ${KEEP[@]+"${KEEP[@]}"} python3 -u tools/team_relay.py --repo "${REPO:-/Volumes/bazaar}" \
    --live "${LIVE:-/Volumes/bazaar-live}" >> "$LOG" 2>&1 || true
  sleep 5
done
