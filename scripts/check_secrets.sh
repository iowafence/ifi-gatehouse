#!/usr/bin/env bash
# Usage: check_secrets.sh --staged | --tree
# Fails on committed .env files, key files, unapproved document/archive types, and credential-shaped strings.
# Prints file names only, never values.
# Optional local denylist: a git-ignored file `.private-names` (one extended-regex per line) blocks
# project or customer names that must never be published. It is not tracked, so CI does not use it.
set -uo pipefail
mode="${1:---tree}"
if [ "$mode" = "--staged" ]; then files="$(git diff --cached --name-only --diff-filter=ACM)"; else files="$(git ls-files)"; fi
top="$(git rev-parse --show-toplevel)"
names=""
[ -f "$top/.private-names" ] && names="$(grep -Ev '^[[:space:]]*(#|$)' "$top/.private-names" | paste -sd'|' -)"
fail=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    .env.example) ;;
    .env|.env.*|*.pem|*.key|*.p12|config/*.local.json|private/*|demo_documents/*) echo "BLOCKED path: $f" >&2; fail=1; continue;;
  esac
  case "$f" in *.pdf|*.zip|*.xlsx|*.xls|*.dwg)
    # Documents, archives and spreadsheets are allowed ONLY as reviewed public synthetic assets: under samples/public-demo/, never named like
    # private material, and listed in samples/public-assets.sha256 as "<sha256>  <path>  # <provenance>" with the exact content hash.
    if grep -Eiq 'answer[_ -]?key|ground[_ -]?truth|original_with|legacy|private|internal|coordination|evaluation|customer|rate[_ -]?book' <<<"$f"; then
      echo "BLOCKED document/archive with a private-material name: $f" >&2; fail=1; continue; fi
    case "$f" in samples/public-demo/*) ;; *) echo "BLOCKED document/archive outside samples/public-demo/: $f" >&2; fail=1; continue;; esac
    if [ "$mode" = "--staged" ]; then h="$(git show ":$f" 2>/dev/null | sha256sum | cut -d' ' -f1)"; man="$(git show ":samples/public-assets.sha256" 2>/dev/null || true)"
    else h="$(sha256sum "$f" | cut -d' ' -f1)"; man="$(cat "$top/samples/public-assets.sha256" 2>/dev/null || true)"; fi
    if ! grep -Eq "^$h  $f  # .+" <<<"$man"; then echo "BLOCKED document/archive not approved in samples/public-assets.sha256 (hash and provenance required): $f" >&2; fail=1; fi
    continue;;
  esac
  case "$f" in scripts/check_secrets.sh) continue;; esac
  # In --staged mode scan the staged blob, not the working-tree file (they can differ).
  if [ "$mode" = "--staged" ]; then content="$(git show ":$f" 2>/dev/null)" || continue; else [ -f "$f" ] || continue; content="$(cat "$f")"; fi
  if grep -Eiq '(AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|token|password)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+_-]{24,})' <<<"$content"; then
    echo "BLOCKED credential-shaped content in: $f" >&2; fail=1
  fi
  if [ -n "$names" ] && grep -Eiq "($names)" <<<"$content"; then
    echo "BLOCKED private name (from .private-names) in: $f" >&2; fail=1
  fi
done <<<"$files"
exit $fail
