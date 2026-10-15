#!/bin/bash
# Docker-free start for a platform that runs a plain checkout (e.g. Replit Reserved VM): engine on 127.0.0.1:8099 (never exposed) + the Next.js server on $PORT.
# Build first: (cd web && npm ci && npm run build). Same architecture and environment as hosting/entrypoint.sh; no Gatehouse source differs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
gen() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
export ENGINE_API_KEY="${ENGINE_API_KEY:-$(gen)}" SESSION_SIGNING_SECRET="${SESSION_SIGNING_SECRET:-$(gen)$(gen)}"
export ENGINE_PORT="${ENGINE_PORT:-8099}" NODE_ENV=production DP001_DIR="$ROOT/dp001" FLIGHT_TRACE_DIR="${FLIGHT_TRACE_DIR:-$ROOT/traces}" PYTHONDONTWRITEBYTECODE=1 NEXT_TELEMETRY_DISABLED=1
PORT_WEB="${PORT:-8080}"
ENGINE_PORT="${ENGINE_PORT:-8099}"   # internal only (127.0.0.1). Change it if something else on this machine already uses 8099.
# Refuse to start (and never probe) if the internal port is already taken by another service.
python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); sys.exit(0 if s.connect_ex(('127.0.0.1',$ENGINE_PORT))!=0 else 1)" || { echo "internal engine port $ENGINE_PORT is already in use; set ENGINE_PORT" >&2; exit 1; }
(PORT="$ENGINE_PORT" ENGINE_HOST=127.0.0.1 ENGINE_DEMO_ROUTES=1 exec python3 "$ROOT/run/start_engine_dp001.py") &
ENGINE_PID=$!
for i in $(seq 1 60); do
  python3 - <<PY && break || sleep 0.5
import os,sys,urllib.request
try:
    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%s/health"%os.environ["ENGINE_PORT"],headers={"X-Engine-Key":os.environ["ENGINE_API_KEY"]}),timeout=1); sys.exit(0)
except Exception: sys.exit(1)
PY
done
kill -0 "$ENGINE_PID" 2>/dev/null || { echo "engine failed to start" >&2; exit 1; }
cd "$ROOT/web"
ENGINE_BASE_URL="http://127.0.0.1:$ENGINE_PORT" node node_modules/next/dist/bin/next start -p "$PORT_WEB" -H 0.0.0.0 &
WEB_PID=$!
trap 'kill "$ENGINE_PID" "$WEB_PID" 2>/dev/null || true' TERM INT
wait -n "$ENGINE_PID" "$WEB_PID" || true
echo "a component exited; stopping" >&2
kill "$ENGINE_PID" "$WEB_PID" 2>/dev/null || true
exit 1
