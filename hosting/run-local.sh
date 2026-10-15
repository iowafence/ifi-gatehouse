#!/usr/bin/env bash
# Run the judge image locally with the Flight Recorder reading external traces from a host directory, mounted READ-ONLY.
# Usage: hosting/run-local.sh [host_port]   (default 18230; binds 127.0.0.1 only)
# Env:   FLIGHT_TRACE_HOST_DIR (default $HOME/gatehouse-flight-traces)  CASES_HOST_DIR (default $HOME/gatehouse-evolus-cases; see hosting/export_evolus_cases.py)  IMAGE (default gatehouse-judge-demo)  NAME (default gh-judge-traces)  AUDIT_HOST_DIR (TEST ONLY: mounts a different audit directory read-only over dp001/independent_audits, e.g. to prove a tampered audit is rejected)
set -euo pipefail
PORT="${1:-18230}"
DIR="${FLIGHT_TRACE_HOST_DIR:-$HOME/gatehouse-flight-traces}"
CASES="${CASES_HOST_DIR:-$HOME/gatehouse-evolus-cases}"; mkdir -p "$CASES"
IMAGE="${IMAGE:-gatehouse-judge-demo}"; NAME="${NAME:-gh-judge-traces}"
[ -d "$DIR" ] || { echo "trace directory not found: $DIR" >&2; exit 1; }
# The container user (uid 10001) is not the file owner: trace files must be world-readable (umask 022 or 002 is fine).
EXTRA=(); [ -n "${AUDIT_HOST_DIR:-}" ] && EXTRA=(-v "$AUDIT_HOST_DIR:/app/dp001/independent_audits:ro")
exec docker run -d --name "$NAME" --read-only --tmpfs /tmp --tmpfs /app/web/.next/cache:uid=10001 --cap-drop ALL --security-opt no-new-privileges \
  -v "$DIR:/app/traces:ro" -e FLIGHT_TRACE_DIR=/app/traces -v "$CASES:/app/cases:ro" -e GATEHOUSE_CASES_DIR=/app/cases "${EXTRA[@]}" -p "127.0.0.1:$PORT:8080" "$IMAGE"
