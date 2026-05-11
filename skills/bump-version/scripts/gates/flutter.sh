#!/usr/bin/env bash
# Flutter pre-release gate：flutter analyze + flutter test

set -euo pipefail

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "[FAIL] 非 git repo，無法偵測專案根目錄" >&2; exit 1; }
if [ -d "${GIT_ROOT}/mobile" ]; then
  FLUTTER_DIR="${GIT_ROOT}/mobile"
else
  FLUTTER_DIR="$GIT_ROOT"
fi

echo "[OK] Flutter 專案根目錄：$FLUTTER_DIR"
echo "[OK] 執行 flutter analyze..."
( cd "$FLUTTER_DIR" && flutter analyze )

echo "[OK] 執行 flutter test..."
( cd "$FLUTTER_DIR" && flutter test )
