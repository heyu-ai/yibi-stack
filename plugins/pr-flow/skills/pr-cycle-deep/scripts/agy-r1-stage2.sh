#!/usr/bin/env bash
# pr-cycle-deep Step 3.2 — agy R1 Stage 2：Extract（raw → JSON）
#
# 用法：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh
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

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
EXTRACT_PROMPT=~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md

# issue #153 fix 2：清掉殘留的 agy scratch input，避免 agentic 檔案搜尋撈到 stale input。
rm -f "$HOME"/.gemini/antigravity-cli/scratch/gemini-*-input.md 2>/dev/null || true

# Ensure temp files are cleaned even on unexpected exit (set -e early exit, signal, etc.)
_STAGE2_CLEANUP() { rm -f "${REVIEW_DIR:-/dev/null}/gemini-extract-input.md" "${TMP_JSON:-/dev/null}"; }
trap _STAGE2_CLEANUP EXIT

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

# cd 到 worktree root：--add-dir . 以 WT_ROOT 為 context 基準。
cd "$WT_ROOT"

# issue #153 fix 1：inline prompt 取代 @file。萃取任務只需 raw 文字，--sandbox 即足夠
# （extraction 不需讀周邊程式碼，sandbox 更安全）。inline 後 agy 無需讀檔即無 agentic 觸發點。
TMP_JSON="$REVIEW_DIR/gemini-r1.json.tmp"
EXTRACT_CONTENT=$(cat "$REVIEW_DIR/gemini-extract-input.md")
if ! agy -p "$EXTRACT_CONTENT" \
    --add-dir . \
    --sandbox \
    --print-timeout 10m \
    > "$TMP_JSON" \
    2>"$REVIEW_DIR/gemini-r1.extract.log"; then
    echo "[FAIL] agy extract 失敗，請查看 $REVIEW_DIR/gemini-r1.extract.log" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md" "$TMP_JSON"
    exit 1
fi

# issue #153 fix 4：brain-artifact rescue。萃取若進入 agentic 模式，真正輸出會寫到 brain
# artifact，TMP_JSON 只剩 narration+pointer。validator 就地把 TMP_JSON 還原成真正內容，
# 後續 JSON 萃取才找得到 JSON。此處不檢 Verdict / changed-file（萃取輸出為 JSON，schema
# 由下方 Python 把關），只做 rescue + timeout + narration。
if ! python3 "$SCRIPT_DIR/agy_validate.py" \
    --raw "$TMP_JSON" \
    --label "agy R1 Stage 2"; then
    echo "[FAIL] agy R1 Stage 2 萃取輸出未通過 fail-loud 驗證（見上方 [FAIL] 訊息）" >&2
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
