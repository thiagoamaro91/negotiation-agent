#!/bin/bash
# Final conductor queue A: RET page buys, one dealer bot at a time; never launches inside the 12:28-12:45 Market Test quiet window.
cd ~/bazaar
gate() { while :; do hm=$(date +%H%M); if [ "$hm" -ge 1228 ] && [ "$hm" -lt 1245 ]; then echo "$(date +%T) quiet window, waiting"; sleep 30; else break; fi; done; }
step() { gate; echo "$(date +%T) START $*"; python3 -u "$@"; echo "$(date +%T) EXIT $? $*"; python3 tools/snapshot.py --me-only --score >/dev/null 2>&1; python3 -c "import json;s=json.load(open('logs/state/me.json'))['score'];print('SCORE',s['score'],'neg',s['neg_points'],'ladder',s['ladder_points'],'negotiating',s['negotiating'],'rank',s['rank'])"; }
step agent/chato.py run --dealer picaros --only RET-09 --cap 61 --anchor 40 --step 1 --reserve 40 --max-deals 1 --max-rounds 40 --until 13:55
step agent/chato.py run --dealer picaros --only RET-10 --cap 61 --anchor 40 --step 1 --reserve 40 --max-deals 1 --max-rounds 40 --until 13:55
step agent/abuela.py run --only RET-06,RET-07,RET-08 --cap 22 --reserve 40 --max-deals 3 --until 13:55
step agent/abuela.py run --only RET-02 --cap 8 --reserve 40 --max-deals 1 --until 13:55
echo "$(date +%T) QUEUE A DONE"
