#!/usr/bin/env bash
# pr-review-cycle-mob Step 3.1 — 準備工作目錄
#
# 用法（從 SKILL.md 呼叫時 agent 會替換 {{base_branch}}；手動執行時自填）：
#   bash /Users/<you>/.agents/skills/pr-review-cycle-mob/scripts/setup-review-dir.sh main
#
# $1 = base branch（必填）
#
# 為什麼抽成 script：
#   1. SKILL.md 的 bash code block 容易被 agent 重寫成 fat command（rule 13 AP1）
#   2. 多個 "$VAR" 展開混在 compound script 觸發 rule 14 Quoting Rule 5
#   3. 原本 fat command 觸發多個確認框（`$?`、多 `"$VAR"`、寫入 .git/info/exclude）；
#      獨立 script 只需 allow-list 一次（rule 16 安全 pattern：完整絕對路徑）
#
# 副作用：
#   1. 建立 $WT_ROOT/.pr-review/ 目錄
#   2. 把 .pr-review/ 加進 worktree-local $GIT_DIR/info/exclude（不污染主 repo .gitignore）
#   3. 產生 .pr-review/diff.patch 與 .pr-review/changed-files.txt
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。
# stdout 最後一行 `REVIEW_DIR=<絕對路徑>` 為 informational，呼叫端可選擇解析或自行從
# worktree root 推導（兩者等價）。

set -euo pipefail

BASE_BRANCH="${1:-}"
if [ -z "$BASE_BRANCH" ]; then
    echo "[FAIL] base branch 未提供（例：bash setup-review-dir.sh main）" >&2
    exit 1
fi

# 先確認在 git repo 內，避免後續 git rev-parse 把「不在 repo」報成「ref 不存在」。
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

# 在進入 mkdir / git diff 之前先驗證 BASE_BRANCH 是有效 git ref，
# 避免 typo（如 'mian'）或只有遠端的 branch 留下 0-byte diff.patch 後才失敗。
# 注意：`git fetch origin <branch>` 只更新 `origin/<branch>` ref，**不會**建立 local
# branch；若需要 local `main` 對應 remote，要 `git fetch origin main:main` 或直接用
# `BASE_BRANCH=origin/main` 作為值。
if ! git rev-parse --verify "$BASE_BRANCH" >/dev/null 2>&1; then
    echo "[FAIL] '$BASE_BRANCH' 不是有效的 git ref（請確認本地有此 branch，或改用 'origin/${BASE_BRANCH}'）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if ! mkdir -p "$REVIEW_DIR"; then
    echo "[FAIL] 無法建立 review 目錄：$REVIEW_DIR（請確認 worktree 目錄有寫入權限）" >&2
    exit 1
fi

GIT_DIR=$(git rev-parse --git-dir)

if ! mkdir -p "$GIT_DIR/info"; then
    echo "[FAIL] 無法建立 $GIT_DIR/info（請確認 .git 目錄可寫）" >&2
    exit 1
fi

# 把 .pr-review/ 加進 git exclude（worktree-local，不污染 .gitignore）。
# 用 if-then 而非 ||：避免 rule 14 Quoting Rule 5 與 `||` 條件分支觸發 AP1 計分。
# grep 退出碼 1（not found）與 2（read error）都走 then-branch；read error 情境下
# 後續 echo >> 會因 set -e 失敗並停止——可接受（exotic case，不值得額外 case 分支）。
if ! grep -qF '.pr-review/' "$GIT_DIR/info/exclude" 2>/dev/null; then
    echo '.pr-review/' >> "$GIT_DIR/info/exclude"
fi

git diff "$BASE_BRANCH"...HEAD > "$REVIEW_DIR/diff.patch"
git diff "$BASE_BRANCH"...HEAD --name-only > "$REVIEW_DIR/changed-files.txt"

# Informational：呼叫端可選擇解析此行或自行 git rev-parse --show-toplevel 推導。
echo "REVIEW_DIR=$REVIEW_DIR"
