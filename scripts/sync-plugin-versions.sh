#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "[FAIL] Usage: sync-plugin-versions.sh <version>" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PLUGINS_DIR="$REPO_ROOT/plugins"

if [ ! -d "$PLUGINS_DIR" ]; then
    echo "[FAIL] plugins/ directory not found at $PLUGINS_DIR" >&2
    exit 1
fi

python3 - "$PLUGINS_DIR" "$VERSION" << 'PYEOF'
import sys
import json
from pathlib import Path

plugins_dir = Path(sys.argv[1])
version = sys.argv[2]

updated = []
for pkg_file in sorted(plugins_dir.glob("*/package.json")):
    data = json.loads(pkg_file.read_text(encoding="utf-8"))
    old_version = data.get("version", "")
    data["version"] = version
    pkg_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    updated.append((pkg_file.parent.name, old_version, version))

for name, old, new in updated:
    print(f"  [OK] {name}: {old} -> {new}")
PYEOF
