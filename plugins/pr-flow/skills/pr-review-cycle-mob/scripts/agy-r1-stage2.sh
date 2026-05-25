#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.2 — agy R1 Stage 2：Extract（raw → JSON）
#
# 用法：
#   bash ~/.agents/skills/pr-review-cycle-mob/scripts/agy-r1-stage2.sh
#
# agy 自動選擇輕量模型做 extract，避免再消耗高推理配額。
#
# 副作用：
#   - gemini-r1.json 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r1.extract.log
#   - 暫存 gemini-extract-input.md（完成後自動刪除）
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

EXTRACT_PROMPT=~/.agents/skills/pr-review-cycle-mob/prompts/extract-r1.md

if [ ! -f "$EXTRACT_PROMPT" ]; then
    echo "[FAIL] extract prompt 不存在；請執行 make install" >&2
    exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if [ ! -f "$REVIEW_DIR/gemini-r1-raw.md" ]; then
    echo "[FAIL] gemini-r1-raw.md 不存在；請確認 Stage 1 已成功完成" >&2
    exit 1
fi

if ! cat "$EXTRACT_PROMPT" "$REVIEW_DIR/gemini-r1-raw.md" > "$REVIEW_DIR/gemini-extract-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

printf '\n---END RAW OUTPUT---\n' >> "$REVIEW_DIR/gemini-extract-input.md"

# cd 到 worktree root：agy @file 沙箱只允許讀取 worktree root 下的相對路徑
cd "$WT_ROOT"

# 先寫入暫存檔，再用 Python 萃取純 JSON
TMP_JSON="$REVIEW_DIR/gemini-r1.json.tmp"
if ! agy -p "@.pr-review/gemini-extract-input.md" \
    --add-dir . \
    --sandbox \
    > "$TMP_JSON" \
    2>"$REVIEW_DIR/gemini-r1.extract.log"; then
    echo "[FAIL] agy extract 失敗，請查看 $REVIEW_DIR/gemini-r1.extract.log" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md" "$TMP_JSON"
    exit 1
fi

if ! python3 -c '
import sys, json
try:
    content = open(sys.argv[1], "r", encoding="utf-8").read()
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1:
        json_str = content[start:end+1]
        data = json.loads(json_str)
        if "verdict" in data and "summary" in data and isinstance(data.get("findings"), list):
            print(json.dumps(data, indent=2, ensure_ascii=False))
            sys.exit(0)
    print("[FAIL] 找不到有效的 JSON 物件或欄位不符 schema", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] JSON 萃取或驗證失敗: {e}", file=sys.stderr)
    sys.exit(1)
' "$TMP_JSON" > "$REVIEW_DIR/gemini-r1.json"; then
    echo "[FAIL] 從 agy 輸出中萃取 JSON 失敗" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md" "$TMP_JSON"
    exit 1
fi
rm -f "$TMP_JSON"

rm -f "$REVIEW_DIR/gemini-extract-input.md"

echo "agy R1 Stage 2 complete"
