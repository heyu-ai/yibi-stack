#!/usr/bin/env bash
# red-first gate 的單一入口（pr-cycle-deep Step 1.7、pr-cycle-fast 3.0b 共用）
#
# 用途：在派 reviewer 之前，跑目標 repo 提供的 scripts/red-first-check.py，並把它包成
# 一個「一次呼叫、fail loud」的步驟。
#
# 為什麼要包成 script（PR #469 mob review Round 2，Claude + Codex 4 個來源一致）：
# runbook 原本要 agent 分成數個 Bash call，並用 shell 變數（PR_TITLE、WT_ROOT、
# BASE_REMOTE）在 call 之間傳值。Bash tool 不會在 call 之間保留變數，照字面執行時：
# checker 路徑變成 `/scripts/red-first-check.py` 而誤判 `[SKIP] no checker`，或
# `--title ""` 讓 gate 失效，全程沒有警告。更早一版（Round 1）則把標題直接貼進雙引號，
# `${N}`（本 repo PR #387 的真實標題）被展開成空字串、反引號會被執行。放進 script 後，
# 標題只存在變數裡，所有值都在同一個 shell 內傳遞。
#
# 用法：
#   bash <path>/red-first.sh --pr <number> --repo-root <checkout> --out-dir <dir>
#   （Bash tool 要給 timeout 600000：checker 會跑兩次測試）
#
# 輸出：checker 的完整輸出寫到 <out-dir>/red-first.out，並同步印到 stdout；
# PR body 寫到 <out-dir>/pr-body.md。最後一行固定是 `RED_FIRST_RESULT=<名稱>`。
#
# 退出碼（每一個都是具名結果）：
#   0  可以往下走：PASS、SKIP（沒有 checker、PR 類型不需要）、EXEMPT，或 UNCHECKED。
#      輸出中的 [EXEMPT]、[WEAK-RED]、[WARN] red-first: 行由呼叫端帶到人／reviewer 面前。
#      `RED_FIRST_RESULT=unchecked` **不是通過**：checker 以 exit 0 結束，但說它沒有檢查任何東西
#      （輸出有整行 `red-first: UNCHECKED`，或過渡期接受的舊句子，見下方偵測處）。呼叫端照常
#      往下走，但要把它帶到人面前，並要求另附證據（例如手動 mutation），不得當成 pass
#   1  red-first 判定失敗（checker 印出 `red-first: FAIL`）：測試抓不到這次改動
#   2  前提不成立或工具出錯：參數錯、gh/git 失敗、標題為空、merge／rebase／cherry-pick／
#      revert 進行中或有未解衝突（此時 HEAD 不是要檢查的樹）、checker exit 2、
#      沒有判定行的 exit 1（traceback）或其他 exit code
#   3  跑完後工作樹的內容與跑之前不一致：產品碼可能沒還原。
#      **不要自行還原**（git checkout 屬 rule 15 不可逆操作），把狀態交給人
#
# 跑之前可以有未 commit 的改動（#496）：比對的是跑前跑後的**內容**，不是要求跑前乾淨。
# checker 自己負責拒絕它在意的未 commit 改動（例如 yibi-mvp 的 checker 檢查 stack 目錄），
# 並在暫存 worktree 執行測試，不會寫使用者的工作區。
#
# 刻意**不**清除繼承的 GIT_DIR / GIT_WORK_TREE：本 script 問的是「呼叫端要檢查哪個
# checkout」，由 --repo-root 明確指定，與 preflight-review-snapshot.sh 同一族。

set -euo pipefail

# 任何沒被 `if !` / `|| X=$?` 保護到的指令失敗（例如 base 與 PR 沒有共同祖先時的
# git merge-base），在 set -e 下會以該指令自己的 exit code 結束；那可能剛好是 1，
# 被呼叫端讀成「判定失敗」並要求作者補測試。統一收斂成 exit 2（工具錯誤）。
trap 'echo "[FAIL] red-first: 未預期的指令失敗（line ${LINENO}）" >&2; echo "RED_FIRST_RESULT=error"; exit 2' ERR

PR=""
REPO_ROOT=""
OUT_DIR=""

usage() {
    echo "用法：red-first.sh --pr <number> --repo-root <checkout> --out-dir <dir>" >&2
}

fail() {
    # $1 = exit code，其餘為訊息
    local code="$1"
    shift
    echo "[FAIL] red-first: $*" >&2
    echo "RED_FIRST_RESULT=error"
    exit "$code"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --pr|--repo-root|--out-dir)
            if [ "$#" -lt 2 ]; then
                usage
                fail 2 "$1 需要一個值"
            fi
            case "$1" in
                --pr) PR="$2" ;;
                --repo-root) REPO_ROOT="$2" ;;
                --out-dir) OUT_DIR="$2" ;;
            esac
            shift 2
            ;;
        *)
            usage
            fail 2 "未知參數：$1"
            ;;
    esac
done

if [ -z "$PR" ] || [ -z "$REPO_ROOT" ] || [ -z "$OUT_DIR" ]; then
    usage
    fail 2 "--pr、--repo-root、--out-dir 都必須指定"
fi
case "$PR" in
    *[!0-9]*) fail 2 "--pr 必須是數字：${PR}" ;;
esac
if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail 2 "--repo-root 不是 git checkout：${REPO_ROOT}"
fi
mkdir -p "$OUT_DIR"

CHECKER="$REPO_ROOT/scripts/red-first-check.py"
if [ ! -f "$CHECKER" ]; then
    echo "[SKIP] red-first: no checker（${CHECKER} 不存在）"
    echo "RED_FIRST_RESULT=skip-no-checker"
    exit 0
fi

# gh 從 cwd 推斷 repo，所以在本 script 自己的 shell 內切到目標 checkout。
# 下面的 git 呼叫因此都以 cwd 為準（含 --git-path 回傳的相對路徑）
cd "$REPO_ROOT"

# merge／rebase／cherry-pick／revert 進行中時，HEAD 不是要檢查的那棵樹，checker 會對錯的
# commit 下判定且沒有任何警告（pr-cycle-fast 3.0 走 check --sha 時就會碰到）。
# 每個條件各自偵測：cherry-pick --no-commit 不留狀態檔，但衝突解決後仍會留 CHERRY_PICK_HEAD；
# stash apply 衝突沒有任何 *_HEAD，只能從 unmerged 項目看出來
IN_PROGRESS=""
for state_ref in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    if git rev-parse -q --verify "$state_ref" >/dev/null; then
        IN_PROGRESS="${IN_PROGRESS} ${state_ref}"
    fi
done
for state_dir in rebase-merge rebase-apply; do
    if [ -d "$(git rev-parse --git-path "$state_dir")" ]; then
        IN_PROGRESS="${IN_PROGRESS} rebase（${state_dir}）"
    fi
done
UNMERGED=$(git ls-files --unmerged)
if [ -n "$UNMERGED" ]; then
    IN_PROGRESS="${IN_PROGRESS} 未解衝突"
fi
if [ -n "$IN_PROGRESS" ]; then
    fail 2 "有操作進行中：${IN_PROGRESS# }；HEAD 不是要檢查的樹，等 merge／rebase 完成再跑"
fi

# 工作樹內容的指紋：把整個工作樹（含 untracked、不含 ignored）放進一份暫存 index 後取 tree
# OID。只比 `git status --porcelain` 不夠：跑之前已修改的檔案若被 checker 再改，或既有
# untracked 檔的內容被改，那幾行字完全不變。用暫存 index，真實 index 不會被動到
INDEX_TMP_DIR=$(mktemp -d)
trap 'rm -rf "$INDEX_TMP_DIR"' EXIT
tree_fingerprint() {
    local idx="$INDEX_TMP_DIR/index.$1"
    cp "$(git rev-parse --git-path index)" "$idx"
    GIT_INDEX_FILE="$idx" git add -A
    GIT_INDEX_FILE="$idx" git write-tree
}
TREE_BEFORE=$(tree_fingerprint before)

if ! PR_TITLE=$(gh pr view "$PR" --json title -q .title); then
    fail 2 "gh pr view ${PR}（title）失敗"
fi
if [ -z "$PR_TITLE" ]; then
    fail 2 "PR #${PR} 的標題為空"
fi
if ! BASE_BRANCH=$(gh pr view "$PR" --json baseRefName -q .baseRefName); then
    fail 2 "gh pr view ${PR}（baseRefName）失敗"
fi
if [ -z "$BASE_BRANCH" ]; then
    fail 2 "PR #${PR} 的 base branch 為空"
fi
# >| ：Bash tool 的 zsh/bash 可能開著 noclobber，舊檔存在時 > 會失敗並留下舊內容
if ! gh pr view "$PR" --json body -q .body >| "$OUT_DIR/pr-body.md"; then
    fail 2 "gh pr view ${PR}（body）失敗"
fi

# base remote：有 upstream（fork workflow）就用 upstream，否則 origin（issue #196）
BASE_REMOTE="origin"
if git remote get-url upstream >/dev/null 2>&1; then
    BASE_REMOTE="upstream"
fi
if ! git fetch --quiet "$BASE_REMOTE" "$BASE_BRANCH"; then
    fail 2 "git fetch ${BASE_REMOTE} ${BASE_BRANCH} 失敗"
fi
BASE_SHA=$(git rev-parse FETCH_HEAD)

# PR 自己改了 checker 時，等於自己幫自己打分數：照跑，但標出來交給人
MERGE_BASE=$(git merge-base "$BASE_SHA" HEAD)
# 先取輸出再判斷：`git diff | grep -q .` 在 pipefail 下，grep 提早結束會讓 git diff
# 收到 SIGPIPE，整條 pipeline 變非零，警告就靜默消失
CHECKER_DIFF=$(git diff --name-only "$MERGE_BASE" HEAD -- scripts/red-first-check.py)
if [ -n "$CHECKER_DIFF" ]; then
    echo "[WARN] red-first: checker modified by this PR（判定由 PR 自己改過的 checker 產生，須由人確認）"
fi

CHECKER_EXIT=0
python3 "$CHECKER" --repo "$REPO_ROOT" --base "$BASE_SHA" --title "$PR_TITLE" \
    --pr-body-file "$OUT_DIR/pr-body.md" >| "$OUT_DIR/red-first.out" 2>&1 || CHECKER_EXIT=$?
cat "$OUT_DIR/red-first.out"

# 不論 checker 的 exit code，先確認工作樹內容與跑之前一致。不再豁免 checker 自己列出的
# 「工具副作用」（#496）：checker 在暫存 worktree 跑測試、不寫使用者的工作區，那份清單只會
# 讓「自稱是副作用」的改動溜過去
TREE_AFTER=$(tree_fingerprint after)
if [ "$TREE_AFTER" != "$TREE_BEFORE" ]; then
    git status --porcelain >&2
    echo "[FAIL] red-first: 跑完後工作樹的內容與跑之前不一致（目前狀態見上方；跑之前已修改的檔被再改時，那一行不會變），產品碼可能沒還原；不要自行還原，交給人判斷" >&2
    echo "RED_FIRST_RESULT=tree-not-restored"
    exit 3
fi

# checker 以 exit 0 結束不代表有檢查（issue #521）。偵測兩種形狀，任一出現即為 unchecked，
# 且優先於 `red-first: PASS`：
#   1. 整行 `red-first: UNCHECKED`：與 `red-first: FAIL` 對稱的機讀標記，checker 應改印這個
#   2. 含 `red-first 沒有檢查任何東西` 的行：yibi-mvp checker 目前印的句子。這是給人看的文字，
#      不是 API，只是過渡用，等 checker 改印機讀標記後移除
is_unchecked() {
    grep -qx 'red-first: UNCHECKED' "$OUT_DIR/red-first.out" \
        || grep -qF 'red-first 沒有檢查任何東西' "$OUT_DIR/red-first.out"
}

case "$CHECKER_EXIT" in
    0)
        if is_unchecked; then
            echo "[WARN] red-first: checker 沒有檢查任何東西（exit 0 不是通過）；請另附證據，例如手動 mutation"
            echo "RED_FIRST_RESULT=unchecked"
            exit 0
        fi
        echo "RED_FIRST_RESULT=pass"
        exit 0
        ;;
    1)
        if grep -qx 'red-first: FAIL' "$OUT_DIR/red-first.out"; then
            echo "RED_FIRST_RESULT=fail"
            exit 1
        fi
        fail 2 "checker exit 1 但沒有 'red-first: FAIL' 判定行（多半是 traceback），見上方輸出"
        ;;
    *)
        fail 2 "checker exit ${CHECKER_EXIT}（前提不成立或 checker 出錯），見上方輸出"
        ;;
esac
