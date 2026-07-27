#!/usr/bin/env bash
# pr-cycle-deep Step 4.3 — Codex R2：Cross-model debate
#
# 用法：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r2.sh
#
# 副作用：
#   - codex-r2.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/codex-r2.log
#   - 暫存 codex-r2-input.md（完成後自動刪除）
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

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

if ! cat "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" > "$REVIEW_DIR/codex-r2-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# -m pins the frontier model; see codex-r1-stage1.sh for why this is not left to
# ~/.codex/config.toml. R2 debate is the same reasoning-heavy workload as R1, so it gets
# the same tier.
if ! codex exec -C "$WT_ROOT" -s read-only -m gpt-5.6-sol -c 'model_reasoning_effort="high"' \
    < "$REVIEW_DIR/codex-r2-input.md" \
    2>"$REVIEW_DIR/codex-r2.log" \
    | tee "$REVIEW_DIR/codex-r2.md" > /dev/null; then
    echo "[FAIL] codex R2 失敗，請查看 $REVIEW_DIR/codex-r2.log" >&2
    rm -f "$REVIEW_DIR/codex-r2-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/codex-r2-input.md"

if [ ! -s "$REVIEW_DIR/codex-r2.md" ]; then
    echo "[FAIL] codex-r2.md 空白，R2 輸出異常" >&2
    exit 1
fi

echo "Codex R2 complete"
