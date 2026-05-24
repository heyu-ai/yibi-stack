#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.2 — Codex R1 Stage 1：Native review
#
# 用法：
#   bash ~/.agents/skills/pr-review-cycle-mob/scripts/codex-r1-stage1.sh main
#
# $1 = base branch（必填）
#
# 為什麼抽成 script：
#   1. 含 pipeline + 多個 "$VAR" 展開，觸發 rule 14 Quoting Rule 5
#   2. 原 inline block 用 if [ $? -ne 0 ]，違反 rule 14 $? 特殊案例
#   3. redirect 目標含 $() subshell 輸出的變數，觸發 hook
#   4. 獨立 script 只需 allow-list 一次（rule 16 安全 pattern：完整絕對路徑）
#
# 副作用：
#   - codex-r1-raw.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/codex-r1.stage1.log
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

BASE_BRANCH="${1:-}"
if [ -z "$BASE_BRANCH" ]; then
    echo "[FAIL] base branch 未提供（例：bash codex-r1-stage1.sh main）" >&2
    exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if [ ! -d "$REVIEW_DIR" ]; then
    echo "[FAIL] $REVIEW_DIR 不存在；請先執行 setup-review-dir.sh（Step 3.1）" >&2
    exit 1
fi

if ! codex review --base "$BASE_BRANCH" -c 'model_reasoning_effort="high"' \
    2>"$REVIEW_DIR/codex-r1.stage1.log" \
    | tee "$REVIEW_DIR/codex-r1-raw.md" > /dev/null; then
    echo "[FAIL] codex review 失敗，請查看 $REVIEW_DIR/codex-r1.stage1.log" >&2
    exit 1
fi

if [ ! -s "$REVIEW_DIR/codex-r1-raw.md" ]; then
    echo "[FAIL] codex-r1-raw.md 空白，Stage 1 輸出異常" >&2
    exit 1
fi

echo "Codex R1 Stage 1 complete"
