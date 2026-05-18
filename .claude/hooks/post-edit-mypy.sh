#!/bin/bash
# PostToolUse hook: 對 tasks/**/*.py 編輯後跑 mypy
#
# 輸入（stdin JSON）：
#   tool_input.file_path  - 被編輯的檔案路徑
#   duration_ms           - 工具執行時間（v2.1.133+）
#
# 流程：
#   1. 讀 stdin JSON，解析 file_path 與 duration_ms
#   2. 非 tasks/*.py 直接 exit 0
#   3. duration_ms < 100 視為超短編輯，略過，減少雜訊
#   4. 用 --directory 跑 mypy，輸出 error/note 行給 Claude

set -euo pipefail

STDIN_DATA=$(cat)
REPO_ROOT=$(git rev-parse --show-toplevel)

PARSED=$(printf '%s' "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    fp = (data.get('tool_input') or {}).get('file_path', '')
    dur = data.get('duration_ms', 0)
    print(f'{fp}|{dur}')
except Exception:
    print('|0')
") || exit 0

FILE=$(printf '%s' "$PARSED" | cut -d'|' -f1)
DUR=$(printf '%s' "$PARSED" | cut -d'|' -f2)

case "$FILE" in
  */tasks/*.py) ;;
  *) exit 0 ;;
esac

if [ "${DUR:-0}" -lt 100 ] 2>/dev/null; then
    exit 0
fi

uv run --directory "$REPO_ROOT" mypy "$FILE" --no-error-summary 2>/dev/null \
    | grep -E 'error:|note:' || true
