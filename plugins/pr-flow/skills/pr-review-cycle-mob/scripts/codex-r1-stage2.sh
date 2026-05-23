#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.2 — Codex R1 Stage 2：Extract（raw → JSON）
#
# 用法：
#   bash ~/.agents/skills/pr-review-cycle-mob/scripts/codex-r1-stage2.sh
#
# 副作用：
#   - codex-r1.json 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/codex-r1.extract.log
#   - 暫存 codex-extract-input.md（完成後自動刪除）
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

if [ ! -f "$REVIEW_DIR/codex-r1-raw.md" ]; then
    echo "[FAIL] codex-r1-raw.md 不存在；請確認 Stage 1 已成功完成" >&2
    exit 1
fi

if ! cat "$EXTRACT_PROMPT" "$REVIEW_DIR/codex-r1-raw.md" > "$REVIEW_DIR/codex-extract-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

printf '\n---END RAW OUTPUT---\n' >> "$REVIEW_DIR/codex-extract-input.md"

if ! codex exec -C "$WT_ROOT" -s read-only -c 'model_reasoning_effort="low"' \
    < "$REVIEW_DIR/codex-extract-input.md" \
    2>"$REVIEW_DIR/codex-r1.extract.log" \
    | tee "$REVIEW_DIR/codex-r1.json" > /dev/null; then
    echo "[FAIL] codex extract 失敗，請查看 $REVIEW_DIR/codex-r1.extract.log" >&2
    rm -f "$REVIEW_DIR/codex-extract-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/codex-extract-input.md"
echo "Codex R1 Stage 2 complete"
