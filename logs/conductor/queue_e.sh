#!/bin/bash
# Final conductor queue E (from 12:45): Abuela RET-02 at cap 9 (= value), then RET-06/07 retry at cap 22.
cd ~/bazaar
until [ "$(date +%H%M)" -ge 1245 ]; do sleep 20; done
retn() { python3 tools/snapshot.py --me-only --score >/dev/null 2>&1; python3 -c "import json;print(len({a['ref'] for a in json.load(open('logs/state/me.json'))['assets'] if a['ref'].startswith('RET')}))"; }
step() { n=$(retn); if [ "$n" -ge 9 ]; then echo "$(date +%T) RET at $n/10: no dealer buy (the last cards come from teams)"; return; fi
  echo "$(date +%T) START $* (RET $n/10)"; python3 -u agent/abuela.py run --reserve 40 --until 13:50 "$@"; echo "$(date +%T) EXIT $?"; python3 logs/conductor/tc.py score; }
step --only RET-02 --cap 9 --max-deals 1
step --only RET-06,RET-07 --cap 22 --max-deals 1
step --only RET-07,RET-06 --cap 22 --max-deals 1
echo "$(date +%T) QUEUE E DONE"
