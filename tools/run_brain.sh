#!/usr/bin/env bash
# Keep the public-feed recorder and the market brain alive on an always-on machine (the team VM).
# Each runs in its own tmux window and is restarted 3 s after it stops. Safe to run again: it does nothing if running.
#
#   tools/run_brain.sh              # start
#   tmux attach -t bazaar           # watch (Ctrl-b n for the next window, Ctrl-b d to leave)
#   tmux kill-session -t bazaar     # stop both
#
# The brain reads BRAIN_TOKEN / BRAIN_WRITE_TOKEN from ~/bazaar/brain.env (not in the repo) and listens on
# 127.0.0.1:${BRAIN_PORT:-8790}; publish it with `tailscale funnel --bg 8790`.
set -euo pipefail
cd "$(dirname "$0")/.."
if tmux has-session -t bazaar 2>/dev/null; then
  echo "already running: tmux attach -t bazaar"
  exit 0
fi
LOG="${BRAIN_LOG_DIR:-$HOME/bazaar}"
mkdir -p "$LOG" logs/feed logs/brain
tmux new-session -d -s bazaar -n recorder \
  "export TZ=Europe/Madrid; while true; do python3 -u tools/feed_recorder.py >> '$LOG/recorder.log' 2>&1; sleep 3; done"
tmux new-window -t bazaar -n brain \
  "export TZ=Europe/Madrid; while true; do python3 -u tools/brain.py --port ${BRAIN_PORT:-8790} >> '$LOG/brain.log' 2>&1; sleep 3; done"
echo "recorder + brain running in tmux session 'bazaar' (logs in $LOG)"
