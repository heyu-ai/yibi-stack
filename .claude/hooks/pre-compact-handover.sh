#!/bin/bash
# PreCompact hook: 攔截第一次 auto-compact，提醒 Claude 在壓縮前執行 handover
#
# 流程：
#   1. 讀取 stdin JSON，取得 session_id 與 matcher
#   2. 只處理 matcher = "auto"（手動 /compact 直接放行）
#   3. 狀態檔 /tmp/claude-handover-suggested-{session_id}：
#      - 不存在（第一次）→ 建立狀態檔，輸出 systemMessage，exit 2（攔截）
#      - 已存在（第二次）→ 刪除狀態檔，exit 0（放行）
#   4. 狀態檔 TTL：超過 1 小時視為過期，重新攔截一次

set -euo pipefail

# 讀取 stdin（Claude Code 只傳一次）
STDIN_DATA=$(cat)

# 用 python3 解析 JSON（與 protect-push.sh 保持相同 pattern）
PARSED=$(echo "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    event = data.get('hook_event_name', '')
    session_id = data.get('session_id', '')
    matcher = data.get('matcher', data.get('matcher_type', ''))
    print(f'{event}|{session_id}|{matcher}')
except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
    print('||')
") || {
    echo "pre-compact-handover: 警告：JSON 解析失敗，略過" >&2
    exit 0
}

EVENT=$(echo "$PARSED" | cut -d'|' -f1)
SESSION_ID=$(echo "$PARSED" | cut -d'|' -f2)
MATCHER=$(echo "$PARSED" | cut -d'|' -f3)

# 只處理 PreCompact + auto
[ "$EVENT" != "PreCompact" ] && exit 0
[ "$MATCHER" != "auto" ] && exit 0

# 狀態檔路徑
if [ -n "$SESSION_ID" ]; then
    STATE_FILE="/tmp/claude-handover-suggested-${SESSION_ID}"
else
    STATE_FILE="/tmp/claude-handover-suggested-default"
fi

# 清除過期狀態檔（超過 3600 秒 = 1 小時）
if [ -f "$STATE_FILE" ]; then
    FILE_AGE=$(( $(date +%s) - $(stat -f %m "$STATE_FILE" 2>/dev/null || stat -c %Y "$STATE_FILE" 2>/dev/null || echo 0) ))
    if [ "$FILE_AGE" -gt 3600 ]; then
        rm -f "$STATE_FILE"
    fi
fi

# 第二次：狀態檔已存在 → 放行
if [ -f "$STATE_FILE" ]; then
    rm -f "$STATE_FILE"
    exit 0
fi

# 第一次：建立狀態檔 → 攔截並提醒
touch "$STATE_FILE"

python3 -c "
import json
msg = (
    'Context 即將自動 compact。建議先執行 /handover 保存工作進度，'
    '避免重要資訊在壓縮中遺失。'
    '執行完 handover 後，下次互動時 compact 將自動進行，'
    '然後執行 /handover-back 恢復工作狀態。'
    '是否要先執行 handover？'
)
print(json.dumps({'systemMessage': msg}))
"

exit 2
