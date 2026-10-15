#!/bin/bash
# Generic demo engine (the built-in synthetic scope). Needs run/engine.env: ENGINE_API_KEY, ENGINE_DEMO_ROUTES=1, PORT.
cd "$(dirname "$0")/.."
set -a; . run/engine.env; set +a
PYTHONDONTWRITEBYTECODE=1 exec python3 -m api.server
