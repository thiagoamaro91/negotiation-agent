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

tar czf - tools/dashboard.py tools/dashboard.html kit/bazaar_sdk.py tools/mini \
  | ssh mini "/bin/bash -c 'mkdir -p ~/bazaar-dashboard && tar xzf - -C ~/bazaar-dashboard'"
ssh -n mini "/bin/bash ~/bazaar-dashboard/tools/mini/install.sh"
