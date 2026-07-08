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
#   4. 執行 `git fetch <base-remote> <branch>`（每次執行都會發出網路請求；base remote
#      存在 upstream 時優先用它、否則 origin，一律以該 remote 上的版本為 base，本地未
#      push 的 branch 或離線環境不適用，fetch 失敗即 [FAIL] 退出，不 fallback 回本地 ref）
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
# 拿到不相關的 diff）。此 script 是 fetch+FETCH_HEAD 邏輯的唯一擁有者，產出的
# diff.patch 由所有 voice 共用（issue #194 起 codex-r1-stage1.sh 改用 codex exec
# review 這份 diff.patch，不再自行 fetch）：strip 掉可能已有的 remote 前綴，永遠對
# 選定的 base remote（見下方 issue #196 邏輯）重新 fetch，用 FETCH_HEAD 取代呼叫端
# 傳入的 branch 名稱本身。
#
# 已知限制（Codex round-3 finding）："origin/"、"upstream/" 一律視為 remote-tracking
# 記法並剝除，不支援字面上就叫 "origin/<name>" 的 branch（此為 mob-code-review-only/
# SKILL.md 既有呼叫慣例本身的語意：呼叫端傳 "origin/{{base_branch}}" 就是要用 base
# repo 上的版本，非要求保留這個字面 branch 名稱）。此工具的呼叫端一律是 gh pr view
# 取得的單純 PR base branch 名稱（如 "main"），不會出現這種罕見的 branch 命名衝突。
#
# PR #175 mob review 教訓（安全性 + 正確性）：
#   1. BASE_BRANCH 若解析成空字串（如呼叫端傳入 "origin/"），`git fetch origin ""`
#      不會報錯，而是靜默 fallback 抓 remote 的預設 branch，導致 diff 對到錯的 base
#      卻沒有任何失敗訊號——這正是本檔案原本要修的那類 bug，用別的路徑重新引入。
#      故先擋空字串。
#   2. $FETCH_BRANCH 未加 "--" 分隔符直接傳給 `git fetch` 時，若字串以 "-" 開頭
#      （如 "--upload-pack=<cmd>"），git 會把它當成選項而非 ref 名稱解析，構成
#      command-injection 風險（已用 `git fetch origin --upload-pack=touch_pwned`
#      實測驗證會嘗試執行任意指令）。故一律加 "--" 明確終止選項解析。
# 解析 base branch 該向哪個 remote fetch（issue #196）：當 `origin` 是個人 fork、其
# 預設 branch 落後真正的 base repo 時，向 origin fetch base 會取到 fork 落後的 tip，
# merge-base 往回退，review diff 從 PR 真正的變更集膨脹成數百個不相關檔案——且完全
# 靜默、無任何錯誤訊號。fork workflow 的慣例是 origin=fork、upstream=base repo，故
# 存在 `upstream` remote 時優先用它；否則退回 origin（非 fork 情境，行為不變）。
#
# 已知限制（採納的啟發式，issue #196）：remote 以「名稱」選取，未逐一比對 remote URL
# 是否等於 PR 的真實 base repository。罕見情況下若 origin 其實就是正確 base repo、卻又
# 存在一個不相關/過期的 `upstream` remote，會選錯。此權衡已在 issue #196 由 owner 拍板
# 採納（fork workflow 的 origin=fork/upstream=base 是壓倒性常見情境）。
BASE_REMOTE=origin
if git remote get-url upstream >/dev/null 2>&1; then
    BASE_REMOTE=upstream
fi

# strip 掉可能已有的 remote 前綴（呼叫端慣例傳 "origin/{{base_branch}}" 表示「用 base
# repo 上的版本」，非要求保留字面 branch 名稱）。同時剝除 "origin/" 與 "upstream/"，
# 讓兩種呼叫慣例都路由到上面選定的 $BASE_REMOTE。
FETCH_BRANCH="${BASE_BRANCH#origin/}"
FETCH_BRANCH="${FETCH_BRANCH#upstream/}"
if [ -z "$FETCH_BRANCH" ]; then
    echo "[FAIL] '$BASE_BRANCH' 解析後為空字串，不是有效的 branch 名稱" >&2
    exit 1
fi
if ! git fetch "$BASE_REMOTE" --quiet -- "$FETCH_BRANCH"; then
    echo "[FAIL] git fetch ${BASE_REMOTE} ${FETCH_BRANCH} 失敗，請確認 '${FETCH_BRANCH}' 已存在於 ${BASE_REMOTE}（此 script 以 base repo（存在 upstream 時優先，否則 origin）上的版本為 base，本地未 push 的 branch 或離線環境不適用）" >&2
    exit 1
fi
if ! BASE_SHA=$(git rev-parse FETCH_HEAD); then
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
