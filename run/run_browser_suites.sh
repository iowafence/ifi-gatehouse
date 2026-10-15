#!/bin/bash
# Runs the browser suites in sequence against a running engine (DP-001 engine; pass6 needs the generic engine) and a fresh web server per suite
# (the per-IP new-demo limiter is in memory). Usage: WEB_PORT=5081 run/run_browser_suites.sh   -- starts/stops only the web server on that port.
cd "$(dirname "$0")/.."
export WEB_PORT="${WEB_PORT:-5071}" DEMO_URL="http://127.0.0.1:${WEB_PORT:-5071}/"
mkdir -p evidence; : > evidence/browser_suites.done
for s in ai_bridge footing takeoff dp001 viewer_stability; do
  W=$(ss -ltnp | grep ":${WEB_PORT} " | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1); [ -n "$W" ] && kill "$W"; sleep 1
  (bash run/start_web.sh > run/web.log 2>&1 &); sleep 5
  ( cd e2e && timeout 900 python3 e2e_$s.py > ../evidence/e2e_${s}_output.txt 2>&1; echo "exit $?" >> ../evidence/e2e_${s}_output.txt )
done
echo ALLDONE > evidence/browser_suites.done
