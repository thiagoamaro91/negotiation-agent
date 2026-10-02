#!/bin/bash
# Runs ON the Mini (called by tools/deploy_mini.sh): install or refresh the two LaunchAgents and print the link.
set -euo pipefail
cd "$HOME/bazaar-dashboard"
test -f .env || { echo "missing ~/bazaar-dashboard/.env (BAZAAR_URL, BAZAAR_KEY, DASH_TOKEN)"; exit 1; }
cp tools/mini/tunnel-agent.sh tunnel-agent.sh && chmod +x tunnel-agent.sh

# retire hand-started loops from the first setup: only processes whose working dir is this folder
for pid in $(pgrep -f "bash ./(run|tunnel)\.sh" || true); do
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
  [ "$cwd" = "$HOME/bazaar-dashboard" ] && kill "$pid" 2>/dev/null || true
done

for name in dashboard tunnel; do
  cp "tools/mini/com.thiago.bazaar-$name.plist" "$HOME/Library/LaunchAgents/"
  launchctl bootout "gui/$(id -u)/com.thiago.bazaar-$name" 2>/dev/null || true
done
pkill -f "bazaar-dashboard/tools/dashboard.py --port 8765" 2>/dev/null || true
pkill -f "^python.*tools/dashboard.py --port 8765" 2>/dev/null || true
for pid in $(pgrep -f "tools/dashboard.py --port 8765" || true); do
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
  [ "$cwd" = "$HOME/bazaar-dashboard" ] && kill "$pid" 2>/dev/null || true
done
pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765" 2>/dev/null || true
sleep 1

START=$(date +%s)
for name in dashboard tunnel; do
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.thiago.bazaar-$name.plist"
done
for _ in $(seq 1 90); do
  if [ -s tunnel.url ] && [ "$(stat -f %m tunnel.url)" -ge "$START" ]; then break; fi
  sleep 1
done
launchctl print "gui/$(id -u)/com.thiago.bazaar-dashboard" | grep -E "^\s*(state|pid) =" | head -2
launchctl print "gui/$(id -u)/com.thiago.bazaar-tunnel" | grep -E "^\s*(state|pid) =" | head -2
echo "public link: $(cat tunnel.url)/?t=$(grep '^DASH_TOKEN=' .env | cut -d= -f2)"
