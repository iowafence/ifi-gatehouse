#!/bin/bash
# Starts the engine on 127.0.0.1:8099 (never published) and the web tier on $PORT. If either exits, the container exits so the platform restarts it.
# ENGINE_API_KEY and SESSION_SIGNING_SECRET are generated per start when not supplied; they are never printed or written to disk.
set -euo pipefail
cd /app
gen() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
export ENGINE_API_KEY="${ENGINE_API_KEY:-$(gen)}" SESSION_SIGNING_SECRET="${SESSION_SIGNING_SECRET:-$(gen)$(gen)}"
PORT_WEB="${PORT:-8080}"
(PORT=8099 ENGINE_HOST=127.0.0.1 ENGINE_DEMO_ROUTES=1 exec python3 /app/run/start_engine_dp001.py) &
ENGINE_PID=$!
for i in $(seq 1 40); do
  python3 - <<PY && break || sleep 0.5
import os,sys,urllib.request
try:
    r=urllib.request.Request("http://127.0.0.1:8099/health",headers={"X-Engine-Key":os.environ["ENGINE_API_KEY"]}); urllib.request.urlopen(r,timeout=1); sys.exit(0)
except Exception: sys.exit(1)
PY
done
kill -0 "$ENGINE_PID" 2>/dev/null || { echo "engine failed to start" >&2; exit 1; }
cd /app/web
ENGINE_BASE_URL=http://127.0.0.1:8099 node node_modules/next/dist/bin/next start -p "$PORT_WEB" -H 0.0.0.0 &
WEB_PID=$!
trap 'kill "$ENGINE_PID" "$WEB_PID" 2>/dev/null || true' TERM INT
wait -n "$ENGINE_PID" "$WEB_PID" || true
echo "a component exited; stopping" >&2
kill "$ENGINE_PID" "$WEB_PID" 2>/dev/null || true
exit 1
