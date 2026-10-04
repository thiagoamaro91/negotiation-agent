#!/bin/bash
# Final conductor queue D: ladder sells of spares (Pilar LAV-10, Chato LAT-07), floors above our value.
cd ~/bazaar
gate() { while :; do hm=$(date +%H%M); if [ "$hm" -ge 1228 ] && [ "$hm" -lt 1245 ]; then echo "$(date +%T) quiet window, waiting"; sleep 30; else break; fi; done; }
have() { python3 -c "import json,sys;a=[x['id'] for x in json.load(open('logs/state/me.json'))['assets']];sys.exit(0 if $1 in a else 1)"; }
step() { gate; echo "$(date +%T) START $*"; python3 -u agent/chato.py run --reserve 40 --max-deals 1 --max-wait-ticks 20 --until 13:50 "$@"; echo "$(date +%T) EXIT $?"; python3 tools/snapshot.py --me-only --score >/dev/null 2>&1; python3 logs/conductor/tc.py score; }
step --dealer pilar --only sell:1194 --floor 50 --sell-anchor 80 --max-rounds 40
have 1194 && step --dealer pilar --only sell:1194 --floor 36 --sell-anchor 60 --max-rounds 40
step --dealer chato --only sell:1192 --floor 11 --max-rounds 12
have 1192 && step --dealer chato --only sell:1192 --floor 9 --max-rounds 12
echo "$(date +%T) QUEUE D DONE"
