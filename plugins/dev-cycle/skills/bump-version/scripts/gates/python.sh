#!/usr/bin/env bash
# Python pre-release gate：pytest
# 若 uv 可用則優先使用

set -euo pipefail

if command -v uv > /dev/null 2>&1; then
  echo "[OK] 執行 uv run pytest..."
  uv run pytest
elif command -v pytest > /dev/null 2>&1; then
  echo "[OK] 執行 pytest..."
  pytest
else
  echo "[FAIL] 找不到 pytest，無法執行 Python gate" >&2
  echo "      安裝：uv add pytest 或 pip install pytest" >&2
  echo "      或使用：gates.sh --skip-gates（緊急略過）" >&2
  exit 1
fi
