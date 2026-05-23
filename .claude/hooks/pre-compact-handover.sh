#!/bin/bash
# PreCompact hook: 攔截第一次 auto-compact，提醒 Claude 在壓縮前執行 handover
#
# 流程：
#   1. 讀取 stdin JSON，取得 session_id（matcher 欄位在 payload 中不保證存在）
#   2. hook_event_name 不是 PreCompact 時直接放行
#      （auto/manual 過濾已由 settings.json matcher:"auto" 承擔）
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
    matcher = data.get('matcher', '')
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

# 只處理 PreCompact（auto/manual 過濾由 settings.json matcher:"auto" 承擔）
[ "$EVENT" != "PreCompact" ] && exit 0

# 狀態檔路徑
if [ -n "$SESSION_ID" ]; then
    STATE_FILE="/tmp/claude-handover-suggested-${SESSION_ID}"
else
    STATE_FILE="/tmp/claude-handover-suggested-default"
fi

# REPO_ROOT：供所有 shadow logging 使用，計算一次
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# 清除過期狀態檔（超過 3600 秒 = 1 小時）
# date -r 相容 macOS（BSD）與 Linux（GNU coreutils）；stat -f %m 在 GNU stat 下行為不同
if [ -f "$STATE_FILE" ]; then
    NOW=$(date +%s)
    FILE_MTIME=$(date -r "$STATE_FILE" +%s 2>/dev/null || echo "")
    if [ -z "$FILE_MTIME" ]; then
        # 無法讀取 mtime：跳過過期檢查，保留狀態檔（避免 FILE_MTIME=0 → 永遠視為過期）
        echo "pre-compact-handover: 警告：無法讀取狀態檔 mtime，跳過過期檢查" >&2
    else
        FILE_AGE=$(( NOW - FILE_MTIME ))
        if [ "$FILE_AGE" -gt 3600 ]; then
            rm -f "$STATE_FILE"
            # Shadow logging：狀態檔過期，重新攔截（async fire-and-forget）
            (
                cd "$REPO_ROOT" && \
                SESSION_ID_ENV="$SESSION_ID" MATCHER_ENV="$MATCHER" \
                uv run python -c "
import os
from tasks.session_memory.metrics_service import log_event
from tasks.session_memory.models import EventType, SourceLayer
log_event(EventType.layer2_stale_reset, session_id=os.environ.get('SESSION_ID_ENV') or None,
    source_layer=SourceLayer.layer2, matcher=os.environ.get('MATCHER_ENV') or None)
"
            ) >/dev/null 2>&1 &
            disown
        fi
    fi
fi

# 第二次：狀態檔已存在 → 放行
if [ -f "$STATE_FILE" ]; then
    rm -f "$STATE_FILE"
    # Shadow logging：第二次放行（async fire-and-forget）
    (
        cd "$REPO_ROOT" && \
        SESSION_ID_ENV="$SESSION_ID" MATCHER_ENV="$MATCHER" \
        uv run python -c "
import os
from tasks.session_memory.metrics_service import log_event
from tasks.session_memory.models import EventType, SourceLayer
log_event(EventType.layer2_passthrough, session_id=os.environ.get('SESSION_ID_ENV') or None,
    source_layer=SourceLayer.layer2, matcher=os.environ.get('MATCHER_ENV') or None)
"
    ) >/dev/null 2>&1 &
    disown
    exit 0
fi

# 第一次：建立狀態檔 → 攔截並提醒
touch "$STATE_FILE"
# Shadow logging：第一次攔截（async fire-and-forget）
(
    cd "$REPO_ROOT" && \
    SESSION_ID_ENV="$SESSION_ID" MATCHER_ENV="$MATCHER" \
    uv run python -c "
import os
from tasks.session_memory.metrics_service import log_event
from tasks.session_memory.models import EventType, SourceLayer
log_event(EventType.layer2_intercept, session_id=os.environ.get('SESSION_ID_ENV') or None,
    source_layer=SourceLayer.layer2, matcher=os.environ.get('MATCHER_ENV') or None)
"
) >/dev/null 2>&1 &
disown

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
