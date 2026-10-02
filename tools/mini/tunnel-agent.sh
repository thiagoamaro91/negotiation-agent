#!/bin/bash
# Public link to the Team 3 dashboard via a free Cloudflare quick tunnel. Run by the LaunchAgent
# com.thiago.bazaar-tunnel (KeepAlive), so a crash or a reboot brings it back.
# - writes the current public URL to tunnel.url
# - when the URL changes, sends the new token-gated link to Thiago on Telegram
# - watchdog: checks the public link every 60 s; after 3 failures it exits and launchd restarts it
cd "$HOME/bazaar-dashboard" || exit 1
TOKEN=$(grep '^DASH_TOKEN=' .env | cut -d= -f2)
CUR=tunnel.current.log
: > "$CUR"
/opt/homebrew/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765 > "$CUR" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null; cat "$CUR" >> tunnel.log' EXIT TERM INT

URL=""
for _ in $(seq 1 90); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CUR" | tail -1)
  [ -n "$URL" ] && break
  sleep 1
done
[ -z "$URL" ] && { echo "$(date) no tunnel URL after 90 s" >> tunnel.log; exit 1; }

OLD=$(cat tunnel.url 2>/dev/null)
echo "$URL" > tunnel.url
echo "$(date) tunnel up: $URL" >> tunnel.log
if [ "$URL" != "$OLD" ] && [ -f "$HOME/.config/telegram-notify.env" ]; then
  ( set -a; . "$HOME/.config/telegram-notify.env"; set +a
    curl -sS -m 30 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=Team 3 dashboard link (new): ${URL}/?t=${TOKEN}" > /dev/null ) \
    || echo "$(date) telegram notify failed" >> tunnel.log
fi

sleep 20  # let the new hostname propagate before the first check
FAILS=0
while kill -0 "$PID" 2>/dev/null; do
  CODE=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "$URL/?t=$TOKEN")
  if [ "$CODE" = "200" ]; then FAILS=0; else FAILS=$((FAILS + 1)); fi
  if [ "$FAILS" -ge 3 ]; then
    echo "$(date) public link failed 3 checks (last HTTP $CODE), restarting tunnel" >> tunnel.log
    exit 1
  fi
  sleep 60
done
echo "$(date) cloudflared exited" >> tunnel.log
exit 1
