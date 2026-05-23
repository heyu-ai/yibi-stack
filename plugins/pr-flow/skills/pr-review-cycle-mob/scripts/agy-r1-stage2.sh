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

if ! agy -p "@.pr-review/gemini-extract-input.md" \
    --add-dir . \
    --dangerously-skip-permissions \
    > "$REVIEW_DIR/gemini-r1.json" \
    2>"$REVIEW_DIR/gemini-r1.extract.log"; then
    echo "[FAIL] agy extract 失敗，請查看 $REVIEW_DIR/gemini-r1.extract.log" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/gemini-extract-input.md"

if [ ! -s "$REVIEW_DIR/gemini-r1.json" ]; then
    echo "[FAIL] gemini-r1.json 空白，Extract 輸出異常" >&2
    exit 1
fi

echo "agy R1 Stage 2 complete"
