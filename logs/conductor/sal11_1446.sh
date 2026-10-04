#!/bin/bash
# 14:46: raise the SAL-11 page cap to 228 (value 234) through the keeper config, then restart the desk once.
cd ~/bazaar
until [ "$(date +%H%M)" -ge 1446 ]; do sleep 15; done
v=$(python3 logs/conductor/tc.py value SAL-11 | python3 -c "import sys,ast;print(int(ast.literal_eval(sys.stdin.read())['your_value']))")
echo "$(date +%T) SAL-11 live value $v"
[ "$v" -ge 230 ] || { echo 'value below 230: no change'; exit 1; }
python3 - <<'PY'
p='tools/factory_sunday.json'; t=open(p).read()
import json
old='"--page", "SAL-11:215:192",'
if t.count(old)==1:
    t=t.replace(old,'"--page", "SAL-11:228:216",'); json.loads(t); open(p,'w').write(t); print('config ok')
else:
    print('config pattern missing, no change'); raise SystemExit(1)
PY
[ $? -eq 0 ] || exit 1
pid=$(ps -axo pid,command | awk '/Python -u agent\/market_desk\.py/ {print $1}'); echo "$(date +%T) kill desk $pid"; kill $pid
for i in $(seq 1 60); do n=$(ps -axo pid,command | awk '/Python -u agent\/market_desk\.py/ {print $1}'); [ -n "$n" ] && [ "$n" != "$pid" ] && break; sleep 3; done
echo "$(date +%T) desk now $n"; tail -1 results/factory/market_desk.out | cut -c1-160
