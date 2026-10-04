#!/bin/bash
# Final conductor queue B: Picaros RET-09 now, then low-cap Picaros threads (value-safe buys; switched offers get flagged).
cd ~/bazaar
gate() { while :; do hm=$(date +%H%M); if [ "$hm" -ge 1228 ] && [ "$hm" -lt 1245 ]; then echo "$(date +%T) quiet window, waiting"; sleep 30; else break; fi; done; }
neg() { python3 -c "import json;print(json.load(open('logs/state/me.json'))['score']['neg_points'])"; }
run() { gate; python3 tools/snapshot.py --me-only --score >/dev/null 2>&1; a=$(neg); echo "$(date +%T) START $* neg=$a"; python3 -u agent/chato.py run --dealer picaros --reserve 40 --max-deals 1 --max-wait-ticks 20 --until 13:50 "$@"; rc=$?; python3 tools/snapshot.py --me-only --score >/dev/null 2>&1; echo "$(date +%T) EXIT $rc neg $a -> $(neg)"; python3 logs/conductor/tc.py score; }
run --only RET-09 --cap 61 --anchor 40 --step 1 --max-rounds 40
for i in 1 2 3 4 5 6; do
  [ "$(date +%H%M)" -ge 1345 ] && break
  for c in MAL-09 MAL-10 CHA-09 CHA-10; do
    [ "$(date +%H%M)" -ge 1345 ] && break
    run --only $c --cap 25 --anchor 8 --step 1 --max-rounds 14
  done
done
echo "$(date +%T) QUEUE B DONE"
