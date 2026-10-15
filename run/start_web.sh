#!/bin/bash
# Production-mode web server on 127.0.0.1:${WEB_PORT:-5071}. Build first: (cd web && npm ci && npx next build). Needs web/.env.local.
cd "$(dirname "$0")/../web"
exec npx next start -p "${WEB_PORT:-5071}" -H 127.0.0.1
