#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "[FAIL] Usage: sync-plugin-versions.sh <version>" >&2
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
PLUGINS_DIR="$REPO_ROOT/plugins"

if [ ! -d "$PLUGINS_DIR" ]; then
    echo "[FAIL] plugins/ directory not found at $PLUGINS_DIR" >&2
    exit 1
fi

python3 "$REPO_ROOT/scripts/sync_plugin_versions.py" "$PLUGINS_DIR" "$VERSION"
