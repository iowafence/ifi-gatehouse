#!/usr/bin/env bash
# Verify the RELEASE configuration of the image: no host mounts at all (this is what a hosting platform runs). Local only; nothing is pushed or deployed.
# Usage: hosting/verify_release.sh [host_port=18250]   (builds nothing; run `docker build -f hosting/Dockerfile -t gatehouse-judge-demo .` first)
set -euo pipefail
PORT="${1:-18250}"; IMAGE="${IMAGE:-gatehouse-judge-demo}"; NAME="gh-release-verify"
case "$PORT" in 5071|5051|8099) echo "refusing the frozen demo's port" >&2; exit 1;; esac
cleanup(){ docker stop "$NAME" >/dev/null 2>&1 || true; docker rm "$NAME" >/dev/null 2>&1 || true; }; trap cleanup EXIT
docker run -d --name "$NAME" --read-only --tmpfs /tmp --tmpfs /app/web/.next/cache:uid=10001 --cap-drop ALL --security-opt no-new-privileges -p "127.0.0.1:$PORT:8080" "$IMAGE" >/dev/null
for i in $(seq 1 40); do curl -fs "http://127.0.0.1:$PORT/api/demo/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fs "http://127.0.0.1:$PORT/api/demo/health"; echo
echo "== baked evidence hashes (inside the running container)"
docker exec "$NAME" sh -c 'cd /app && sed "s# traces/# traces/#" RELEASE_SHA256SUMS | while read h f; do d=$(echo "$f" | cut -d/ -f1); n=$(echo "$f" | cut -d/ -f2); case $d in loom) p=/app/loom_reports/$n;; *) p=/app/$d/$n;; esac; a=$(sha256sum "$p" | cut -d" " -f1); [ "$a" = "$h" ] && echo "OK   $f" || { echo "FAIL $f"; exit 1; }; done'
echo "== pinned audit + manifest inputs"
docker exec "$NAME" sh -c 'cd /app/dp001/independent_audits && sha256sum *.json; sha256sum /app/web/release/*.md'
echo "== read-only: the app user cannot write evidence"
for d in /app/traces /app/cases /app/dp001/independent_audits /app/loom_reports; do
  if docker exec "$NAME" sh -c "touch $d/.w 2>/dev/null"; then echo "WRITABLE $d"; exit 1; else echo "read-only $d"; fi; done
echo "== no host mounts"; docker inspect "$NAME" --format '{{len .Mounts}} mounts' ; echo "== user"; docker exec "$NAME" id -u
echo "RELEASE CONFIG VERIFIED on port $PORT (container is removed on exit)"; [ -n "${HOLD:-}" ] && { echo "holding; Ctrl-C to stop"; sleep "$HOLD"; } || true
