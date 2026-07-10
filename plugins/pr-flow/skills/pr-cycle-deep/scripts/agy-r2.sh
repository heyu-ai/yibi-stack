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
# issue #153：nested worktree 下 agy 無法解析 @file，靜默進入 agentic 模式（R2 實測觀察到
# timeout 這個結局）。修法同 stage1：inline prompt 取代 @file、開頭清 scratch、跑 agy_validate.py。
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# issue #153 fix 2：清掉殘留的 agy scratch input，避免 agentic 檔案搜尋撈到 stale input。
# 不吞掉真實失敗（如權限錯誤）——清理失敗代表 stale-input 防線失效，須讓使用者看到 [WARN]。
rm -f "$HOME"/.gemini/antigravity-cli/scratch/gemini-*-input.md || echo "[WARN] agy scratch cleanup failed; stale-input vector not cleared" >&2

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

# 防越界編輯（PR #194 retro）：agy 以權限繞過旗標執行，具 worktree 寫入權；review 階段
# 應為唯讀。快照 agy 執行前的 git 狀態，執行後比對，若工作樹被改動則 fail-loud [WARN]。
# review 產物不誤報：.pr-review/ 全部未追蹤，git status 摺疊成單行 `?? .pr-review/`，
# PRE/POST 相同——只有 agy 改動「已追蹤」檔才觸發。
PRE_TREE=$(git status --porcelain)

# issue #153 fix 1：inline prompt 取代 @file，移除 agentic 觸發點。
# 256000B 上限：macOS ARG_MAX 約 1 MiB（單一 arg 與 env 共用該預算），256KB 留足 headroom。
# 註：量的是 prepend REVIEW_ONLY_GUARD 前的 input；guard 為固定 ~400B，相對 headroom 可忽略。
INPUT_BYTES=$(wc -c < "$REVIEW_DIR/gemini-r2-input.md")
if [ "$INPUT_BYTES" -gt 256000 ]; then
    echo "[FAIL] R2 輸入 ${INPUT_BYTES}B 超過 256000B inline 上限" >&2
    exit 1
fi
# REVIEW-ONLY guard：prepend 到餵給 agy 的 prompt，顯式禁止編輯（權限繞過旗標讓 agy 能寫，
# 唯一防線是明確約束 + 下方的 tree-diff 偵測）。
REVIEW_ONLY_GUARD="[REVIEWER CONSTRAINT — 最高優先] 你是唯讀 code reviewer。禁止修改、建立或刪除任何檔案，禁止執行任何寫入／編輯指令。只讀取檔案與 diff，然後輸出你的 review 文字。改動工作樹是協議違規——若你發現自己正要編輯，停手，改在 review 裡用文字描述該修改建議。"
INPUT_CONTENT="$REVIEW_ONLY_GUARD

$(cat "$REVIEW_DIR/gemini-r2-input.md")"

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

# 偵測 agy 是否在 review 階段越界編輯工作樹（PR #194 retro：agy R2 曾自主改 6 個檔）。
# 不 hard-fail（review 文字仍有價值），但 loud [WARN] 要 lead 逐行稽核並 revert 非預期編輯。
POST_TREE=$(git status --porcelain)
if [ "$PRE_TREE" != "$POST_TREE" ]; then
    echo "[WARN] agy 在 review 階段改動了工作樹（review 應唯讀）；請稽核以下變更並在採用前 revert 非預期編輯：" >&2
    git status --short >&2
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
