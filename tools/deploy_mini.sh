#!/bin/bash
# Deploy the Team 3 dashboard to the Mac Mini (ssh alias "mini") and keep it always on.
#   tools/deploy_mini.sh            # copy code, (re)install both LaunchAgents, print the public link
#   tools/deploy_mini.sh --page     # only copy dashboard.html (picked up on the next page load, no restart)
# The team key and DASH_TOKEN live only in ~/bazaar-dashboard/.env on the Mini (created by hand, never in git).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "--page" ]; then
  ssh mini "/bin/bash -c 'cat > ~/bazaar-dashboard/tools/dashboard.html'" < tools/dashboard.html
  echo "page updated"
  exit 0
fi

# Rivals panel: the offline feed tools (ledger.py fills Friday's recording hole from logs/feed-vm/feed.jsonl);
# value_inference.py caches keyless reads under ~/bazaar-dashboard/logs/public, created below.
tar czf - tools/dashboard.py tools/dashboard.html kit/bazaar_sdk.py tools/mini \
    tools/ledger.py tools/value_inference.py tools/price_index.py logs/feed-vm/feed.jsonl \
  | ssh mini "/bin/bash -c 'mkdir -p ~/bazaar-dashboard/logs/public && tar xzf - -C ~/bazaar-dashboard'"
ssh -n mini "/bin/bash ~/bazaar-dashboard/tools/mini/install.sh"
