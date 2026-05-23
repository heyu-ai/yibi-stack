#!/usr/bin/env bash
# pr-review-cycle-mob Step 4.3 — Gemini R2：Cross-model debate
#
# 用法：
#   GEMINI_MODEL=gemini-3.1-pro-preview bash ~/.agents/skills/pr-review-cycle-mob/scripts/gemini-r2.sh
#
# GEMINI_MODEL 預設 gemini-3.1-pro-preview；若無此模型權限，
# 依序改用 gemini-3-pro-preview 或 gemini-2.5-pro。
#
# 副作用：
#   - gemini-r2.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r2.log
#   - 暫存 gemini-r2-input.md（完成後自動刪除）
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.1-pro-preview}"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if [ ! -f "$REVIEW_DIR/prompt-r2.md" ]; then
    echo "[FAIL] prompt-r2.md 不存在；請確認 Step 4.2 已完成" >&2
    exit 1
fi

if [ ! -f "$REVIEW_DIR/r1-aggregate.md" ]; then
    echo "[FAIL] r1-aggregate.md 不存在；請確認 Step 4.1 已完成" >&2
    exit 1
fi

if ! cat "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" > "$REVIEW_DIR/gemini-r2-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：Gemini @file 沙箱只允許讀取 worktree root 或 ~/.gemini/tmp/<name>/
cd "$WT_ROOT"

if ! gemini -m "$GEMINI_MODEL" -p "@.pr-review/gemini-r2-input.md" \
    > "$REVIEW_DIR/gemini-r2.md" \
    2>"$REVIEW_DIR/gemini-r2.log"; then
    echo "[FAIL] gemini R2 失敗，請查看 $REVIEW_DIR/gemini-r2.log" >&2
    rm -f "$REVIEW_DIR/gemini-r2-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/gemini-r2-input.md"

if [ ! -s "$REVIEW_DIR/gemini-r2.md" ]; then
    echo "[FAIL] gemini-r2.md 空白，R2 輸出異常" >&2
    exit 1
fi

echo "Gemini R2 complete"
