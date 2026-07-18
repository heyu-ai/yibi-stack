#!/bin/bash
# PreCompact compatibility wrapper: delegate to the installed mycelium CLI.

set -euo pipefail

if ! MYCELIUM_BIN=$(command -v mycelium); then
    echo "[FAIL] 找不到 mycelium，無法執行 PreCompact hook" >&2
    exit 1
fi

exec "$MYCELIUM_BIN" hooks pre-compact
