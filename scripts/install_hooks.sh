#!/usr/bin/env bash
# Point git at the tracked hooks. Run once per clone.
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* scripts/*.sh
echo "hooks installed (.githooks)"
