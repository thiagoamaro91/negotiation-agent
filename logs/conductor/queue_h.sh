#!/bin/bash
# Final conductor queue H: Chato L2 slots before stalls close, MAL-06 / MAL-07 at floor 18 (value 17.5).
cd ~/bazaar
for a in 1193 898; do
  [ "$(date +%H%M)" -ge 1357 ] && break
  echo "$(date +%T) START sell:$a"; python3 -u agent/chato.py run --dealer chato --only sell:$a --allow-single --floor 18 --sell-anchor 26 --sell-step 1 --reserve 0 --max-deals 1 --max-rounds 16 --max-wait-ticks 8 --until 13:58; echo "$(date +%T) EXIT $?"; python3 logs/conductor/tc.py score
done
echo "$(date +%T) QUEUE H DONE"
