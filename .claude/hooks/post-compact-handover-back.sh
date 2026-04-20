#!/bin/bash
# SessionStart hook: compact 或 clear 後，提示 Claude 執行 /handover-back
#
# 流程：
#   1. 讀取 stdin JSON，取得 matcher（compact / clear / startup / resume）
#   2. 只處理 compact 與 clear（startup / resume 不作處理）
#   3. 確認 ~/.agents/handover/handover.db 存在
#   4. 輸出 systemMessage 提示執行 /handover-back
#   5. 永遠 exit 0，絕不阻斷 session start

set -euo pipefail

STDIN_DATA=$(cat)

MATCHER=$(echo "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('matcher', data.get('matcher_type', '')))
except Exception:
    print('')
" 2>/dev/null || echo "")

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
