#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.1 — 準備工作目錄
#
# 用法：
#   BASE_BRANCH=main bash ~/.agents/skills/pr-review-cycle-mob/scripts/setup-review-dir.sh
#
# 為什麼抽成 script：
#   1. SKILL.md 的 bash code block 容易被 agent 重寫成 fat command（rule 13 AP1）
#   2. 多個 "$VAR" 展開混在 compound script 觸發 rule 14 Quoting Rule 5
#   3. 寫入 .git/info/exclude 需要使用者確認；獨立 script 只需要 allow-list 一次
#      pattern：Bash(bash ~/.agents/skills/pr-review-cycle-mob/scripts/setup-review-dir.sh)
#
# 輸出（最後一行）：
#   REVIEW_DIR=<絕對路徑>

set -euo pipefail

if [ -z "${BASE_BRANCH:-}" ]; then
    echo "[FAIL] BASE_BRANCH 環境變數未設定（例：BASE_BRANCH=main bash ...）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if ! mkdir -p "$REVIEW_DIR"; then
    echo "[FAIL] 無法建立 review 目錄：$REVIEW_DIR（請確認 worktree 目錄有寫入權限）" >&2
    exit 1
fi

GIT_DIR=$(git rev-parse --git-dir)
mkdir -p "$GIT_DIR/info"

# 把 .pr-review/ 加進 git exclude（worktree-local，不污染 .gitignore）。
# 用 if-then 而非 ||：避免 rule 14 Quoting Rule 5 與 `||` 條件分支觸發 AP1 計分。
if ! grep -qF '.pr-review/' "$GIT_DIR/info/exclude" 2>/dev/null; then
    echo '.pr-review/' >> "$GIT_DIR/info/exclude"
fi

git diff "$BASE_BRANCH"...HEAD > "$REVIEW_DIR/diff.patch"
git diff "$BASE_BRANCH"...HEAD --name-only > "$REVIEW_DIR/changed-files.txt"

# 最後一行輸出 REVIEW_DIR 給呼叫端解析。
echo "REVIEW_DIR=$REVIEW_DIR"
