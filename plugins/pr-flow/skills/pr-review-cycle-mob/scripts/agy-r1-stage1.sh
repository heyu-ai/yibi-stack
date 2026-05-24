#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.2 — agy R1 Stage 1：Native review
#
# 用法（在 worktree 目錄執行）：
#   bash ~/.agents/skills/pr-review-cycle-mob/scripts/agy-r1-stage1.sh
#
# agy 自動選擇最佳模型（無 -m flag）。
# 若需固定模型，在 ~/.gemini/antigravity-cli/settings.json 設定 defaultModel。
#
# 副作用：
#   - gemini-r1-raw.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r1.stage1.log
#   - 暫存 gemini-r1-input.md（完成後自動刪除）
#   - CWD 切換到 $WT_ROOT（agy @file 沙箱要求相對路徑以 WT_ROOT 為基準）
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

if ! WT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi
REVIEW_DIR="$WT_ROOT/.pr-review"
trap 'rm -f "$REVIEW_DIR/gemini-r1-input.md"' EXIT

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

# cd 到 worktree root：agy @file 沙箱只允許讀取 worktree root 下的路徑
cd "$WT_ROOT"

if ! agy -p "@.pr-review/gemini-r1-input.md" --add-dir . --sandbox \
    > "$REVIEW_DIR/gemini-r1-raw.md" \
    2>"$REVIEW_DIR/gemini-r1.stage1.log"; then
    echo "[FAIL] agy review 失敗，請查看 $REVIEW_DIR/gemini-r1.stage1.log" >&2
    rm -f "$REVIEW_DIR/gemini-r1-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/gemini-r1-input.md"

if [ ! -s "$REVIEW_DIR/gemini-r1-raw.md" ]; then
    echo "[FAIL] gemini-r1-raw.md 空白，Stage 1 輸出異常" >&2
    exit 1
fi

echo "agy R1 Stage 1 complete"
