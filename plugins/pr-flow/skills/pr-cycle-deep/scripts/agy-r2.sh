#!/usr/bin/env bash
# pr-cycle-deep Step 4.3 — agy R2：Cross-model debate（Round 2）
#
# 用法（在 worktree 目錄執行）：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r2.sh
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
#   - CWD 切換到 $WT_ROOT（--add-dir . 以 WT_ROOT 為 context 基準）
#
# issue #153：nested worktree 下 agy 無法解析 @file，靜默進入 agentic 模式（R2 實測為
# timeout）。修法同 stage1：inline prompt 取代 @file、開頭清 scratch、跑 agy_validate.py。
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# issue #153 fix 2：清掉殘留的 agy scratch input，避免 agentic 檔案搜尋撈到 stale input。
rm -f "$HOME"/.gemini/antigravity-cli/scratch/gemini-*-input.md 2>/dev/null || true

if ! WT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi
REVIEW_DIR="$WT_ROOT/.pr-review"
trap 'rm -f "$REVIEW_DIR/gemini-r2-input.md"' EXIT

for f in "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" "$REVIEW_DIR/changed-files.txt"; do
    if [ ! -f "$f" ]; then
        echo "[FAIL] 前置檔案不存在：$f" >&2
        exit 1
    fi
done

if ! cat "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" > "$REVIEW_DIR/gemini-r2-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：--add-dir . 以 WT_ROOT 為 context 基準。
cd "$WT_ROOT"

# issue #153 fix 1：inline prompt 取代 @file，移除 agentic 觸發點。
INPUT_BYTES=$(wc -c < "$REVIEW_DIR/gemini-r2-input.md")
if [ "$INPUT_BYTES" -gt 256000 ]; then
    echo "[FAIL] R2 輸入 ${INPUT_BYTES}B 超過 256000B inline 上限" >&2
    exit 1
fi
INPUT_CONTENT=$(cat "$REVIEW_DIR/gemini-r2-input.md")

if ! agy -p "$INPUT_CONTENT" --add-dir . --dangerously-skip-permissions --print-timeout 10m \
    > "$REVIEW_DIR/gemini-r2.md" \
    2>"$REVIEW_DIR/gemini-r2.log"; then
    echo "[FAIL] agy R2 失敗，請查看 $REVIEW_DIR/gemini-r2.log" >&2
    exit 1
fi

if [ ! -s "$REVIEW_DIR/gemini-r2.md" ]; then
    echo "[FAIL] gemini-r2.md 空白，R2 輸出異常" >&2
    exit 1
fi

# issue #153 fix 3+4：brain-artifact rescue + fail-loud 驗證。
if ! python3 "$SCRIPT_DIR/agy_validate.py" \
    --raw "$REVIEW_DIR/gemini-r2.md" \
    --changed-files "$REVIEW_DIR/changed-files.txt" \
    --require-verdict \
    --label "agy R2"; then
    echo "[FAIL] agy R2 輸出未通過 fail-loud 驗證（見上方 [FAIL] 訊息）" >&2
    exit 1
fi

echo "agy R2 complete"
