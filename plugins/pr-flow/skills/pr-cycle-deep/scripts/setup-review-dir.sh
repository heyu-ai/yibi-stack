#!/usr/bin/env bash
# pr-cycle-deep Step 3.1 — 準備工作目錄
#
# 用法（從 SKILL.md 呼叫時 agent 會替換 {{base_branch}}；手動執行時自填）：
#   bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh main
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

# 一律 fetch 後用 FETCH_HEAD 當 diff base，不信任本地 branch ref（PR #22 mob review
# 教訓：本地 main 落後 origin/main 時，`git rev-parse --verify main` 仍會通過驗證，
# 但 diff 會混入已經合併到 origin/main、本地卻還沒同步的舊 commit 內容，導致 reviewer
# 拿到不相關的 diff）。比照 codex-r1-stage1.sh 的作法：strip 掉可能已有的 "origin/"
# 前綴，永遠對 origin 重新 fetch，用 FETCH_HEAD 取代呼叫端傳入的 branch 名稱本身。
FETCH_BRANCH="${BASE_BRANCH#origin/}"
if ! git fetch origin "$FETCH_BRANCH" --quiet; then
    echo "[FAIL] git fetch origin $FETCH_BRANCH 失敗，請確認 remote 連線與 branch 名稱是否正確" >&2
    exit 1
fi
if ! BASE_SHA=$(git rev-parse FETCH_HEAD 2>/dev/null); then
    echo "[FAIL] git rev-parse FETCH_HEAD 失敗，請確認 base branch 存在" >&2
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

git diff "$BASE_SHA"...HEAD > "$REVIEW_DIR/diff.patch"
git diff "$BASE_SHA"...HEAD --name-only > "$REVIEW_DIR/changed-files.txt"

# Informational：呼叫端可選擇解析此行或自行 git rev-parse --show-toplevel 推導。
echo "REVIEW_DIR=$REVIEW_DIR"
