#!/bin/bash
# Engine serving the DP-001 human-prepared scope (see start_engine_dp001.py). Needs run/engine.env.
cd "$(dirname "$0")/.."
set -a; . run/engine.env; set +a
PYTHONDONTWRITEBYTECODE=1 exec python3 run/start_engine_dp001.py
