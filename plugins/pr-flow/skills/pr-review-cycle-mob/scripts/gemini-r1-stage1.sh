#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.2 — Gemini R1 Stage 1：Native review
#
# 用法：
#   bash ~/.agents/skills/pr-review-cycle-mob/scripts/gemini-r1-stage1.sh [model]
#
# $1 = Gemini 模型名稱（選填）；預設 gemini-3.1-pro-preview。
#      若無此模型權限，改用 gemini-3-pro-preview 或 gemini-2.5-pro：
#   bash gemini-r1-stage1.sh gemini-2.5-pro
#
# 副作用：
#   - gemini-r1-raw.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r1.stage1.log
#   - 暫存 gemini-r1-input.md（完成後自動刪除）
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

GEMINI_MODEL="${1:-${GEMINI_MODEL:-gemini-3.1-pro-preview}}"
# 額外 flag 注入（例：GEMINI_EXTRA_ARGS=--yolo 用於 @file 觸發 agentic 模式時）
GEMINI_EXTRA_ARGS="${GEMINI_EXTRA_ARGS:-}"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if [ ! -f "$REVIEW_DIR/prompt-r1.md" ]; then
    echo "[FAIL] prompt-r1.md 不存在；請確認 Write tool 已寫入 review prompt（Step 3.1）" >&2
    exit 1
fi

if [ ! -f "$REVIEW_DIR/diff.patch" ]; then
    echo "[FAIL] diff.patch 不存在，請重跑 Step 3.1 setup block" >&2
    exit 1
fi

if ! cat "$REVIEW_DIR/prompt-r1.md" "$REVIEW_DIR/diff.patch" > "$REVIEW_DIR/gemini-r1-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：Gemini @file 沙箱只允許讀取 worktree root 或 ~/.gemini/tmp/<name>/
cd "$WT_ROOT"

# shellcheck disable=SC2086
if ! gemini -m "$GEMINI_MODEL" $GEMINI_EXTRA_ARGS -p "@.pr-review/gemini-r1-input.md" \
    > "$REVIEW_DIR/gemini-r1-raw.md" \
    2>"$REVIEW_DIR/gemini-r1.stage1.log"; then
    echo "[FAIL] gemini review 失敗，請查看 $REVIEW_DIR/gemini-r1.stage1.log" >&2
    rm -f "$REVIEW_DIR/gemini-r1-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/gemini-r1-input.md"

if [ ! -s "$REVIEW_DIR/gemini-r1-raw.md" ]; then
    echo "[FAIL] gemini-r1-raw.md 空白，Stage 1 輸出異常" >&2
    exit 1
fi

echo "Gemini R1 Stage 1 complete"
