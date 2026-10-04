#!/bin/bash

set -u
umask 077

WORK_DIR=/Users/thiago/bazaar-swarm
CURRENT_LOG="$WORK_DIR/tunnel.current.log"
URL_FILE="$WORK_DIR/tunnel.url"
CHILD_PID=""
URL_TMP=""

cleanup() {
  status=$?
  trap - EXIT TERM INT
  if [ -n "$URL_TMP" ]; then
    rm -f "$URL_TMP"
  fi
  if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill "$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT TERM INT

cd "$WORK_DIR" || exit 1
: > "$CURRENT_LOG"

/opt/homebrew/bin/cloudflared tunnel --no-autoupdate \
  --url http://127.0.0.1:8777 > "$CURRENT_LOG" 2>&1 &
CHILD_PID=$!

URL=""
attempt=0
while [ "$attempt" -lt 90 ]; do
  URL=$(sed -nE \
    '/\|[[:space:]]+https:\/\/[a-z0-9-]+\.trycloudflare\.com[[:space:]]+\|/ {
      s#^.*(https://[a-z0-9-]+\.trycloudflare\.com).*$#\1#
      p
    }' "$CURRENT_LOG" | tail -1)
  if [ "$URL" = "https://api.trycloudflare.com" ]; then
    URL=""
  fi
  if [ -n "$URL" ]; then
    break
  fi
  if ! kill -0 "$CHILD_PID" 2>/dev/null; then
    wait "$CHILD_PID"
    child_status=$?
    CHILD_PID=""
    printf '%s cloudflared exited before publishing a tunnel URL, status %s\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$child_status" >&2
    exit "$child_status"
  fi
  sleep 1
  attempt=$((attempt + 1))
done

if [ -z "$URL" ]; then
  printf '%s no tunnel URL was published within 90 seconds\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >&2
  exit 1
fi

URL_TMP=$(mktemp "$WORK_DIR/.tunnel.url.XXXXXX") || exit 1
printf '%s\n' "$URL" > "$URL_TMP"
chmod 600 "$URL_TMP"
mv -f "$URL_TMP" "$URL_FILE"
URL_TMP=""
printf '%s tunnel URL saved\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

wait "$CHILD_PID"
child_status=$?
CHILD_PID=""
printf '%s cloudflared exited, status %s\n' \
  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$child_status" >&2
exit "$child_status"
