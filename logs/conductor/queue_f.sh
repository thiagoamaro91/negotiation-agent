#!/bin/bash
# Final conductor queue F: Chato ladder slots, MAL-06 then MAL-07 (value 17.5, floor 20).
cd ~/bazaar
for a in 1193 898; do
  echo "$(date +%T) START sell:$a"; python3 -u agent/chato.py run --dealer chato --only sell:$a --allow-single --floor 20 --sell-anchor 30 --reserve 40 --max-deals 1 --max-rounds 14 --max-wait-ticks 20 --until 13:50; echo "$(date +%T) EXIT $?"; python3 logs/conductor/tc.py score
done
echo "$(date +%T) QUEUE F DONE"
