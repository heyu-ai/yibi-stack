#!/bin/bash
# SessionStart hook: compact 或 clear 後，提示 Claude 執行 /handover-back
#
# 流程：
#   1. 讀取 stdin JSON，取得 matcher（compact / clear / startup / resume）
#   2. 只處理 compact 與 clear（startup / resume 不作處理）
#   3. 確認 ~/.agents/handover/handover.db 存在
#   4. 呼叫 log_event 記錄 layer3_session_start（shadow logging）
#   5. 輸出 systemMessage 提示執行 /handover-back
#   6. 永遠 exit 0，絕不阻斷 session start

set -euo pipefail

STDIN_DATA=$(cat)

PARSED=$(echo "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    matcher = data.get('matcher', data.get('matcher_type', ''))
    session_id = data.get('session_id', '')
    print(f'{matcher}|{session_id}')
except Exception:
    print('|')
" 2>/dev/null || echo "|")

MATCHER=$(echo "$PARSED" | cut -d'|' -f1)
SESSION_ID=$(echo "$PARSED" | cut -d'|' -f2)

# 只處理 compact 或 clear
case "$MATCHER" in
    compact|clear) ;;
    *) exit 0 ;;
esac

# 確認 handover DB 存在
HANDOVER_DB="${HOME}/.agents/handover/handover.db"
if [ ! -f "$HANDOVER_DB" ]; then
    exit 0
fi

# Shadow logging：記錄 layer3_session_start 事件（async fire-and-forget）
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
(
    cd "$REPO_ROOT" && \
    SESSION_ID_ENV="$SESSION_ID" \
    MATCHER_ENV="$MATCHER" \
    uv run python -c "
import os
from tasks.session_memory.metrics_service import log_event
from tasks.session_memory.models import EventType, SourceLayer
log_event(
    EventType.layer3_session_start,
    session_id=os.environ.get('SESSION_ID_ENV') or None,
    source_layer=SourceLayer.layer3,
    matcher=os.environ.get('MATCHER_ENV') or None,
)
"
) >/dev/null 2>&1 &
disown

# 輸出 systemMessage 提示執行 /handover-back
python3 -c "
import json
msg = (
    'Context 已壓縮/清空。請立即執行 /handover-back 恢復上次工作狀態，'
    '然後告知使用者已恢復並詢問如何繼續。'
)
print(json.dumps({'systemMessage': msg}))
"

exit 0
