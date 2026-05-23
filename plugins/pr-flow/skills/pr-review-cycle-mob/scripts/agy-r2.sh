#!/usr/bin/env bash
# pr-review-cycle-mob Step 4.3 — agy R2：Cross-model debate（Round 2）
#
# 用法（在 worktree 目錄執行）：
#   bash ~/.agents/skills/pr-review-cycle-mob/scripts/agy-r2.sh
#
# agy 自動選擇最佳模型（無 -m flag）。
# 若需固定模型，在 ~/.gemini/antigravity-cli/settings.json 設定 defaultModel。
#
# 前置條件：$WT_ROOT/.pr-review/prompt-r2.md 與 r1-aggregate.md 已存在。
#
# 副作用：
#   - gemini-r2.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r2.log
#   - 暫存 gemini-r2-input.md（完成後自動刪除）
#   - CWD 切換到 $WT_ROOT（agy @file 沙箱要求相對路徑以 WT_ROOT 為基準）
#
# 安全注意：本 script 使用 --dangerously-skip-permissions，假設 PR 來自受信任
# repo。外部 fork 操作者應評估 prompt injection 風險，可移除此 flag 改用互動模式。
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

if ! WT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi
REVIEW_DIR="$WT_ROOT/.pr-review"
trap 'rm -f "$REVIEW_DIR/gemini-r2-input.md"' EXIT

for f in "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md"; do
    if [ ! -f "$f" ]; then
        echo "[FAIL] 前置檔案不存在：$f" >&2
        exit 1
    fi
done

if ! cat "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" > "$REVIEW_DIR/gemini-r2-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：agy @file 沙箱只允許讀取 worktree root 下的路徑
cd "$WT_ROOT"

if ! agy -p "@.pr-review/gemini-r2-input.md" --add-dir . --dangerously-skip-permissions \
    > "$REVIEW_DIR/gemini-r2.md" \
    2>"$REVIEW_DIR/gemini-r2.log"; then
    echo "[FAIL] agy R2 失敗，請查看 $REVIEW_DIR/gemini-r2.log" >&2
    exit 1
fi

if [ ! -s "$REVIEW_DIR/gemini-r2.md" ]; then
    echo "[FAIL] gemini-r2.md 空白，R2 輸出異常" >&2
    exit 1
fi

echo "agy R2 complete"
