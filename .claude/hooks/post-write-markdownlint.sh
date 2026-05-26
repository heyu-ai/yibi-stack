#!/bin/bash
# PostToolUse hook: 對 **/*.md 寫入後跑 markdownlint-cli2
#
# 輸入（stdin JSON）：
#   tool_input.file_path  - 被寫入的檔案路徑
#
# 流程：
#   1. 讀 stdin JSON，解析 file_path
#   2. 非 .md 直接 exit 0
#   3. 用 uv run pre-commit run markdownlint-cli2 --files <path> 驗證
#   4. 失敗時輸出錯誤給 Claude（不中止 session）

set -euo pipefail

STDIN_DATA=$(cat)

FILE=$(printf '%s' "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    fp = (data.get('tool_input') or {}).get('file_path', '')
except Exception:
    fp = ''
print(fp)
") || exit 0

case "$FILE" in
  *.md) ;;
  *) exit 0 ;;
esac

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

LINT_EXIT=0
LINT_OUT=$(uv run --directory "$REPO_ROOT" pre-commit run markdownlint-cli2 --files "$FILE" 2>&1) || LINT_EXIT=$?

if [ "$LINT_EXIT" -ne 0 ]; then
    printf '[post-write-markdownlint] %s\n' "$LINT_OUT"
fi
