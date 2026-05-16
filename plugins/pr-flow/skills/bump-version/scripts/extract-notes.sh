#!/usr/bin/env bash
# extract-notes.sh — 從 CHANGELOG.md 抽出指定版本的 section
# 用法：extract-notes.sh <version> [changelog_path]
# 輸出：該版本的 CHANGELOG 內容到 stdout
# 範圍：從 "## [X.Y.Z]" 到下一個 "## [" 行（不含）或檔尾

set -euo pipefail

VERSION="${1:?用法：extract-notes.sh <version> [changelog_path]}"
CHANGELOG="${2:-CHANGELOG.md}"

if [ ! -f "$CHANGELOG" ]; then
  echo "[FAIL] 找不到 CHANGELOG 檔案：$CHANGELOG" >&2
  exit 1
fi

OUTPUT=$(awk -v ver="$VERSION" '
  /^## \[/ {
    if (in_section) exit
    if (index($0, "## [" ver "]") == 1) { in_section = 1; next }
  }
  in_section { print }
' "$CHANGELOG")

if [ -z "$OUTPUT" ]; then
  echo "[WARN] 在 $CHANGELOG 找不到版本 $VERSION 的 section" >&2
  echo "（請確認 CHANGELOG 格式為 ## [X.Y.Z] - YYYY-MM-DD）" >&2
  exit 1
fi

echo "$OUTPUT"
