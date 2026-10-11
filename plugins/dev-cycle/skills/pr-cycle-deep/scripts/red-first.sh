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
#      revert 進行中或有未解衝突（此時 HEAD 不是要檢查的樹）、跑之前工作樹就不乾淨、
#      checker exit 2、沒有判定行的 exit 1（traceback）或其他 exit code
#   3  跑完後工作樹不乾淨，或 HEAD 的 commit／所在分支與跑之前不同：產品碼可能沒還原。
#      不論 checker 的 exit code 都先檢查這一項。
#      **不要自行還原**（git checkout 屬 rule 15 不可逆操作），把狀態交給人
#
# 跑之前工作樹必須乾淨（`git status --porcelain --untracked-files=all --ignore-submodules=none`
# 為空，含 staged、
# 未 stage、untracked 與 submodule 內的改動）。這是刻意的（#496 NIT 1 不收）：checker 若就地
# 把產品碼還原到 merge-base，會覆蓋使用者未 commit 的改動，而乾淨的樹沒有可遺失的東西。
# 乾淨也代表 index 與 HEAD 一致，所以跑後只要同一個指令仍為空、HEAD 與分支不變，就是已還原。
# 不涵蓋 .gitignore 忽略的檔案（已接受的殘留風險）。
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
# 這一段排在乾淨檢查之前，讓錯誤訊息指出具體的操作。每個條件各自偵測：一般的 cherry-pick
# 衝突即使已 `git add` 解決，commit 之前仍留著 CHERRY_PICK_HEAD；stash apply 衝突沒有任何
# *_HEAD，只能從 unmerged 項目看出來。`cherry-pick --no-commit` 與 `merge --squash` 不留任何
# 狀態檔，只留 staged 改動，由下面的乾淨檢查擋下
IN_PROGRESS=""
for state_ref in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    # rev-parse -q --verify：0 = 存在、1 = 不存在，其他是 git 本身出錯
    REF_RC=0
    git rev-parse -q --verify "$state_ref" >/dev/null || REF_RC=$?
    case "$REF_RC" in
        0) IN_PROGRESS="${IN_PROGRESS} ${state_ref}" ;;
        1) ;;
        *) fail 2 "git rev-parse --verify ${state_ref} 失敗（exit ${REF_RC}）" ;;
    esac
done
for state_dir in rebase-merge rebase-apply; do
    # 先取路徑再判斷：寫成 [ -d "$(git rev-parse ...)" ] 時 rev-parse 失敗會被讀成「沒有 rebase」
    if ! STATE_PATH=$(git rev-parse --git-path "$state_dir"); then
        fail 2 "git rev-parse --git-path ${state_dir} 失敗"
    fi
    if [ -d "$STATE_PATH" ]; then
        IN_PROGRESS="${IN_PROGRESS} rebase（${state_dir}）"
    fi
done
if ! UNMERGED=$(git ls-files --unmerged); then
    fail 2 "git ls-files --unmerged 失敗"
fi
if [ -n "$UNMERGED" ]; then
    IN_PROGRESS="${IN_PROGRESS} 未解衝突"
fi
if [ -n "$IN_PROGRESS" ]; then
    fail 2 "有操作進行中：${IN_PROGRESS# }；HEAD 不是要檢查的樹，先完成或中止進行中的操作，或解決衝突再跑"
fi

# 跑之前工作樹必須乾淨（AC-3）。兩個旗標都是為了不讓使用者的 git 設定壓掉輸出：
#   --untracked-files=all：設了 status.showUntrackedFiles=no（大型 repo 常見）時，
#     預設的 git status 完全不列 untracked 檔
#   --ignore-submodules=none：.gitmodules 或 config 設了 submodule.<name>.ignore 時，
#     預設的 git status 看不到 submodule 內的改動
if ! BEFORE=$(git status --porcelain --untracked-files=all --ignore-submodules=none); then
    fail 2 "git status 失敗"
fi
if [ -n "$BEFORE" ]; then
    printf '%s\n' "$BEFORE" >&2
    fail 2 "跑 checker 前工作樹就不乾淨（見上方）；先 commit 或 stash 再跑"
fi

# 記下 HEAD 的 commit 與所在分支，跑完後比對（AC-4）。結果寫進全域變數 HEAD_SHA／HEAD_REF；
# 刻意不在 $() 裡呼叫，fail 才能真的結束 script
read_head_state() {
    if ! HEAD_SHA=$(git rev-parse --verify HEAD); then
        fail 2 "git rev-parse HEAD 失敗"
    fi
    # symbolic-ref -q：0 = 在分支上、1 = detached HEAD，其他是 git 本身出錯
    local ref_rc=0
    HEAD_REF=$(git symbolic-ref -q HEAD) || ref_rc=$?
    case "$ref_rc" in
        0) ;;
        1) HEAD_REF="DETACHED" ;;
        *) fail 2 "git symbolic-ref HEAD 失敗（exit ${ref_rc}）" ;;
    esac
}
read_head_state
HEAD_SHA_BEFORE="$HEAD_SHA"
HEAD_REF_BEFORE="$HEAD_REF"

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

# 不論 checker 的 exit code，先確認已還原（AC-4）：同一個 porcelain 指令仍為空，HEAD 的 commit
# 與所在分支都沒變。不再豁免 checker 自己列出的「工具副作用」（#496 NIT 2）：那份清單只會讓
# 「自稱是副作用」的改動溜過去
if ! AFTER=$(git status --porcelain --untracked-files=all --ignore-submodules=none); then
    fail 2 "跑完後 git status 失敗"
fi
read_head_state
NOT_RESTORED=""
if [ -n "$AFTER" ]; then
    NOT_RESTORED="${NOT_RESTORED} 工作樹不乾淨"
fi
if [ "$HEAD_SHA" != "$HEAD_SHA_BEFORE" ]; then
    NOT_RESTORED="${NOT_RESTORED} HEAD 的 commit 變了（${HEAD_SHA_BEFORE} -> ${HEAD_SHA}）"
fi
if [ "$HEAD_REF" != "$HEAD_REF_BEFORE" ]; then
    NOT_RESTORED="${NOT_RESTORED} 所在分支變了（${HEAD_REF_BEFORE} -> ${HEAD_REF}）"
fi
if [ -n "$NOT_RESTORED" ]; then
    # 診斷指令失敗不得把 exit 3 變成 exit 2：放在 if 條件裡，不觸發 ERR trap
    if ! git status --short --untracked-files=all --ignore-submodules=none >&2; then
        echo "[WARN] red-first: 無法列出 git status" >&2
    fi
    echo "[FAIL] red-first: 跑完後沒有還原：${NOT_RESTORED# }。產品碼可能沒還原；不要自行還原，交給人判斷" >&2
    echo "RED_FIRST_RESULT=tree-not-restored"
    exit 3
fi

# checker 以 exit 0 結束不代表有檢查（issue #521）。偵測兩種形狀，任一出現即為 unchecked，
# 且優先於 `red-first: PASS`：
#   1. 整行 `red-first: UNCHECKED`：與 `red-first: FAIL` 對稱的機讀標記，checker 應改印這個
#   2. 含 `red-first 沒有檢查任何東西` 的行：yibi-mvp checker 目前印的句子。這是給人看的文字，
#      不是 API，只是過渡用，等 checker 改印機讀標記後移除
# grep 的 exit 2（例如讀不到檔）不是「沒有」：當成沒有會讓 unchecked 靜默退回 pass。
# 只在 `if is_unchecked` 直接呼叫（不在 $() 裡），fail 才能結束 script
is_unchecked() {
    local rc=0
    grep -qx 'red-first: UNCHECKED' "$OUT_DIR/red-first.out" || rc=$?
    case "$rc" in
        0) return 0 ;;
        1) ;;
        *) fail 2 "讀取 checker 輸出失敗（grep exit ${rc}）" ;;
    esac
    rc=0
    grep -qF 'red-first 沒有檢查任何東西' "$OUT_DIR/red-first.out" || rc=$?
    case "$rc" in
        0) return 0 ;;
        1) return 1 ;;
        *) fail 2 "讀取 checker 輸出失敗（grep exit ${rc}）" ;;
    esac
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
