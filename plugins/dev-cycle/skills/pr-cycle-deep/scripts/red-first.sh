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
#   0  可以往下走：PASS、SKIP（沒有 checker、PR 類型不需要）或 EXEMPT。
#      輸出中的 [EXEMPT]、[WEAK-RED]、[WARN] red-first: 行由呼叫端帶到人／reviewer 面前
#   1  red-first 判定失敗（checker 印出 `red-first: FAIL`）：測試抓不到這次改動
#   2  前提不成立或工具出錯：參數錯、gh/git 失敗、標題為空、跑之前工作區就不乾淨、
#      checker exit 2、沒有判定行的 exit 1（traceback）或其他 exit code
#   3  跑完後工作區有 checker 沒列為副作用的改動：產品碼可能沒還原。
#      **不要自行還原**（git checkout 屬 rule 15 不可逆操作），把狀態交給人
#
# 刻意**不**清除繼承的 GIT_DIR / GIT_WORK_TREE：本 script 問的是「呼叫端要檢查哪個
# checkout」，由 --repo-root 明確指定，與 preflight-review-snapshot.sh 同一族。

set -euo pipefail

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

# 跑之前工作區就必須乾淨，否則跑完後的「是否已還原」無從判斷
# （例如 pr-cycle-fast 3.0 的 check --sha 在 merge 進行中 review，工作區本來就不乾淨）
BEFORE=$(git -C "$REPO_ROOT" status --porcelain)
if [ -n "$BEFORE" ]; then
    echo "$BEFORE" >&2
    fail 2 "跑 checker 前工作區就不乾淨（見上方）；先 commit 或等 merge 完成再跑"
fi

# gh 從 cwd 推斷 repo，所以在本 script 自己的 shell 內切到目標 checkout
cd "$REPO_ROOT"

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
if git diff --name-only "$MERGE_BASE" HEAD -- scripts/red-first-check.py | grep -q .; then
    echo "[WARN] red-first: checker modified by this PR（判定由 PR 自己改過的 checker 產生，須由人確認）"
fi

CHECKER_EXIT=0
python3 "$CHECKER" --repo "$REPO_ROOT" --base "$BASE_SHA" --title "$PR_TITLE" \
    --pr-body-file "$OUT_DIR/pr-body.md" >| "$OUT_DIR/red-first.out" 2>&1 || CHECKER_EXIT=$?
cat "$OUT_DIR/red-first.out"

# 不論 checker 的 exit code，先確認工作區已還原。checker 以 [WARN] 標題後的縮排行列出
# 測試工具的副作用（例如 flutter test 改寫 pubspec.lock）；不在那份清單裡的改動才算沒還原。
AFTER=$(git -C "$REPO_ROOT" status --porcelain)
if [ -n "$AFTER" ]; then
    UNEXPLAINED=""
    SIDE_EFFECTS=""
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        if grep -qF -- "    ${line}" "$OUT_DIR/red-first.out"; then
            SIDE_EFFECTS="${SIDE_EFFECTS}${line}"$'\n'
        else
            UNEXPLAINED="${UNEXPLAINED}${line}"$'\n'
        fi
    done <<< "$AFTER"
    if [ -n "$UNEXPLAINED" ]; then
        printf '%s' "$UNEXPLAINED" >&2
        echo "[FAIL] red-first: 跑完後工作區有未列為副作用的改動（見上方），產品碼可能沒還原；不要自行還原，交給人判斷" >&2
        echo "RED_FIRST_RESULT=tree-not-restored"
        exit 3
    fi
    echo "[WARN] red-first: 測試工具留下副作用，還原前先問 user（git checkout HEAD -- <path>，rule 15）："
    printf '%s' "$SIDE_EFFECTS"
fi

case "$CHECKER_EXIT" in
    0)
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
