#!/bin/bash
# Final conductor queue G: get RET to 9/10 with a dealer buy, so the last card is a team closer.
cd ~/bazaar
retn() { python3 tools/snapshot.py --me-only --score >/dev/null 2>&1; python3 -c "import json;print(len({a['ref'] for a in json.load(open('logs/state/me.json'))['assets'] if a['ref'].startswith('RET')}))"; }
step() { n=$(retn); if [ "$n" -ge 9 ]; then echo "$(date +%T) RET at $n/10: stop"; return; fi
  echo "$(date +%T) START $* (RET $n/10)"; python3 -u agent/abuela.py run --reserve 40 --max-deals 1 --until 13:50 "$@"; echo "$(date +%T) EXIT $?"; python3 logs/conductor/tc.py score; }
step --only RET-01 --cap 9
step --only RET-01 --cap 9
echo "$(date +%T) RET now $(retn)/10"; echo "$(date +%T) QUEUE G DONE"
