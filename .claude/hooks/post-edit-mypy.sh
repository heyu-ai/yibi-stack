#!/bin/bash
# PostToolUse hook: 對 tasks/**/*.py 編輯後跑 mypy
#
# 輸入（stdin JSON）：
#   tool_input.file_path  - 被編輯的檔案路徑
#   duration_ms           - 工具執行時間（v2.1.133+）
# 環境變數：
#   CLAUDE_EFFORT         - 當前 session effort（v2.1.133+；未設定時 fallback normal）
#
# 流程：
#   1. 讀 stdin JSON，解析 file_path 與 duration_ms
#   2. 非 tasks/*.py 直接 exit 0
#   3. duration_ms < 100 視為超短編輯，略過，減少雜訊
#   4. CLAUDE_EFFORT=low 略過（快速 session 不需型別檢查）
#   5. 用 --directory 跑 mypy，輸出 error/note 行給 Claude

set -euo pipefail

STDIN_DATA=$(cat)

{ read -r FILE; read -r DUR; } < <(printf '%s' "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    fp = (data.get('tool_input') or {}).get('file_path', '')
    dur = data.get('duration_ms', 0)
except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError):
    fp, dur = '', 0
print(fp)
print(dur)
") || exit 0

case "$FILE" in
  */tasks/*.py) ;;
  *) exit 0 ;;
esac

if [ "${DUR:-0}" -lt 100 ] 2>/dev/null; then
    exit 0
fi

# no [SKIP] message: this hook fires after every edit;
# silence avoids stderr noise unlike the lower-frequency pre-commit.sh gate
if [ "${CLAUDE_EFFORT:-normal}" = "low" ]; then
    exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
MYPY_EXIT=0
MYPY_OUT=$(uv run --directory "$REPO_ROOT" mypy "$FILE" --no-error-summary 2>&1) || MYPY_EXIT=$?
MATCHING=$(printf '%s\n' "$MYPY_OUT" | grep -E 'error:|note:' || true)
if [ -n "$MATCHING" ]; then
    printf '%s\n' "$MATCHING"
elif [ "$MYPY_EXIT" -ne 0 ]; then
    printf '[post-edit-mypy] invocation failed (exit %s): %s\n' "$MYPY_EXIT" "$MYPY_OUT" >&2
fi
