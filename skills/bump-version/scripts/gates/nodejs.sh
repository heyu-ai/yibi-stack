#!/usr/bin/env bash
# Node.js pre-release gate：npm test

set -euo pipefail

if [ ! -f package.json ]; then
  echo "[WARN] 找不到 package.json，跳過測試"
  exit 0
fi

echo "[OK] 執行 npm test..."
npm test
