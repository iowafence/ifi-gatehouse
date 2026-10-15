#!/usr/bin/env bash
# Usage: check_commit_msgs.sh <file-with-message>   (one message)
#        check_commit_msgs.sh --range <git-range>   (every commit in range: message, author, committer)
set -euo pipefail
PATTERN='co-authored-by:[[:space:]]*.*(claude|anthropic|chatgpt|openai|codex|grok|copilot|gemini)|generated (with|by).*(claude|chatgpt|codex|grok|copilot|gemini)|noreply@anthropic\.com|🤖'
EXPECTED_NAME="Iowa Fence Inc."
fail=0
check_msg() { if grep -Eiq "$PATTERN" <<<"$1"; then echo "REJECTED: prohibited AI attribution/trailer in commit message" >&2; fail=1; fi; }
if [ "${1:-}" = "--range" ]; then
  for sha in $(git rev-list "$2"); do
    check_msg "$(git log -1 --format=%B "$sha")"
    for who in "$(git log -1 --format='%an' "$sha")" "$(git log -1 --format='%cn' "$sha")"; do
      if [ "$who" != "$EXPECTED_NAME" ]; then echo "REJECTED: $sha has author/committer '$who', expected '$EXPECTED_NAME'" >&2; fail=1; fi
    done
    if grep -Eiq "$PATTERN" <<<"$(git log -1 --format='%ae %ce' "$sha")"; then echo "REJECTED: $sha has AI-tool email" >&2; fail=1; fi
  done
else
  check_msg "$(cat "$1")"
fi
exit $fail
