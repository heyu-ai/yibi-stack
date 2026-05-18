#!/usr/bin/env python3
"""Sync all plugins/*/package.json to a single lockstep version."""

import json
import re
import sys
from pathlib import Path

if len(sys.argv) != 3:
    sys.exit("usage: sync_plugin_versions.py <plugins_dir> <version>")

plugins_dir = Path(sys.argv[1])
version = sys.argv[2]

if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+].*)?", version):
    sys.exit(f"[FAIL] invalid version: {version!r} (expected semver like 1.2.3)")

for pkg_file in sorted(plugins_dir.glob("*/package.json")):
    data = json.loads(pkg_file.read_text(encoding="utf-8"))
    old_version = data.get("version", "")
    if old_version == version:
        print(f"  [SKIP] {pkg_file.parent.name}: already at {version}")
        continue
    data["version"] = version
    pkg_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  [OK] {pkg_file.parent.name}: {old_version} -> {version}")
