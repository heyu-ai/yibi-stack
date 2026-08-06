#!/usr/bin/env bash
# review 入口的 merge-state preflight（issue #372）
#
# 用途：在派出任何 reviewer 之前，確認工作區是一個穩定的 snapshot。
#
# 為什麼需要：review 類 skill 讓 reviewer 直接讀**工作區**檔案，但工作區不是 immutable
# snapshot。只要有另一個 session 同時在同一個 worktree 動作，或本 session 正在解 merge
# 衝突，reviewer 就可能讀到中間狀態，並回報**對實際落地內容不成立**的 finding。
#
# 這種假 finding 特別貴：它吃掉一整輪 fix + re-review，而且讀起來和真 finding 一模一樣。
# 實例（yibi-mvp PR #1169，2026-08-04）：一個 code-reviewer subagent 在 ci.yml 處於 `UU`
# 未解衝突狀態時讀檔，回報「ci-status 的 needs 漏掉 vertex-preflight-url-canary」為
# Important；實際落地的 needs 含它。該 PR 的彙整 review 留言已把這筆記為 worktree 被外部
# 改動的實例並駁回。
#
# 用法：
#   # 派 reviewer 前
#   bash <path>/preflight-review-snapshot.sh check
#   # -> stdout 最後一行 `HEAD=<sha>`，呼叫端記下它
#
#   # merge 進行中但確實要 review 某個不可變 SHA
#   bash <path>/preflight-review-snapshot.sh check --sha <40-hex>
#
#   # reviewer 全部回來後
#   bash <path>/preflight-review-snapshot.sh verify <先前記下的 sha>
#
# 退出碼（每一個都是具名結果，不是籠統的 PASS/FAIL）：
#   0  快照穩定（check），或 HEAD 未移動（verify）
#   1  用法錯誤 / 不在 git repo 內 / 指定的 SHA 不存在
#   2  有未解衝突的檔案（unmerged entries）-> 一律拒絕從工作區 review
#   3  有 MERGE_HEAD（merge 進行中）-> 預設拒絕；要 review 必須以 --sha 指定不可變 SHA
#   4  verify 發現 HEAD 已移動 -> 該輪 review 的基準已改變
#
# 為什麼是 review 入口的 preflight 而不是全域 PreToolUse hook：hook 會誤擋「請 reviewer
# 協助審查這次 conflict resolution」這個完全合法的情境，而且擋不到人類 review。放在 review
# entrypoint 並提供 explicit-SHA override，false positive 最低。
#
# 為什麼不寫成散文 rule：「有沒有進行中的 merge」「HEAD 有沒有動」都是一行 git 指令，
# 屬於該用 gate 而非散文的類型。
#
# 刻意**不**清除繼承的 GIT_DIR / GIT_WORK_TREE：這與 resolve-skill-repo 那一族相反。
# 那族問的是「這個 script 自己住在哪個 repo」，必須無視呼叫端環境；本 script 問的是
# 「呼叫端正在哪個 repo 工作」，清掉反而會回答錯的 repo。見 .claude/rules/11 的
# 「Scope the clearing deliberately」。

set -euo pipefail

usage() {
    echo "用法：preflight-review-snapshot.sh check [--sha <40-hex>]" >&2
    echo "      preflight-review-snapshot.sh verify <expected-sha>" >&2
}

MODE="${1:-}"
if [ -z "$MODE" ]; then
    echo "[FAIL] 未指定模式（check 或 verify）" >&2
    usage
    exit 1
fi
shift

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在要 review 的 worktree 目錄執行）" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# verify：review 跑完後確認基準沒被搬走
# ---------------------------------------------------------------------------
if [ "$MODE" = "verify" ]; then
    if [ "$#" -lt 1 ]; then
        echo "[FAIL] verify 需要一個參數：先前 check 記下的 HEAD sha" >&2
        usage
        exit 1
    fi
    EXPECTED="$1"
    CURRENT=$(git rev-parse HEAD)
    if [ "$CURRENT" != "$EXPECTED" ]; then
        echo "[FAIL] review 期間 HEAD 已移動：${EXPECTED} -> ${CURRENT}" >&2
        echo "       這一輪 review 的基準已改變，其 finding 可能對實際落地內容不成立。" >&2
        echo "       請重跑 preflight 並重新派 reviewer，不要直接採信本輪結果。" >&2
        exit 4
    fi
    echo "[OK] HEAD 未移動（${CURRENT}）"
    exit 0
fi

if [ "$MODE" != "check" ]; then
    echo "[FAIL] 未知模式：${MODE}（只接受 check 或 verify）" >&2
    usage
    exit 1
fi

# ---------------------------------------------------------------------------
# check：派 reviewer 前的快照穩定性
# ---------------------------------------------------------------------------
PINNED_SHA=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --sha)
            # `set -u` 下先驗邊界再取 $2，否則漏傳值會噴 unbound variable 而不是乾淨的 [FAIL]
            if [ "$#" -lt 2 ]; then
                echo "[FAIL] --sha 需要一個值" >&2
                exit 1
            fi
            PINNED_SHA="$2"
            shift 2
            ;;
        *)
            echo "[FAIL] 未知參數：$1" >&2
            usage
            exit 1
            ;;
    esac
done

# 1) 未解衝突：一律拒絕，即使有 --sha。工作區此時的檔案內容對任何 SHA 都不成立。
#    `diff-filter=U` 在無衝突時輸出空字串且 exit 0，所以這裡可以直接取值。
UNMERGED=$(git diff --name-only --diff-filter=U)
if [ -n "$UNMERGED" ]; then
    echo "[FAIL] 偵測到未解衝突的檔案，拒絕從工作區 review：" >&2
    echo "${UNMERGED}" >&2
    echo "       reviewer 會讀到衝突標記或中間狀態，產出對實際落地內容不成立的 finding。" >&2
    echo "       請先解完衝突並 commit，再重跑本 preflight。" >&2
    exit 2
fi

# 2) MERGE_HEAD：merge 進行中。即使沒有未解檔案，工作區仍是中繼態。
#    `rev-parse -q --verify` 在 ref 不存在時 exit 非零，故必須包在 `if !` 裡，
#    否則 `set -e` 會讓「沒有 MERGE_HEAD」這個正常情況直接中止整個 script。
if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
    if [ -z "$PINNED_SHA" ]; then
        echo "[FAIL] 偵測到進行中的 merge（MERGE_HEAD 存在），預設拒絕從工作區 review。" >&2
        echo "       工作區是 merge 中繼態，不是任何 commit 的忠實內容。" >&2
        echo "       若確實要在 merge 期間 review，請以不可變 SHA 明確指定：" >&2
        echo "         preflight-review-snapshot.sh check --sha <40-hex>" >&2
        echo "       並要求 reviewer 一律用 'git show <sha>:<path>' 或獨立 checkout 讀檔，" >&2
        echo "       不得讀工作區。" >&2
        exit 3
    fi
fi

# 3) --sha 指定時，確認它真的存在且是個 commit，否則後續 `git show` 全部會失敗。
if [ -n "$PINNED_SHA" ]; then
    if ! git rev-parse -q --verify "${PINNED_SHA}^{commit}" >/dev/null 2>&1; then
        echo "[FAIL] 指定的 SHA 不存在或不是 commit：${PINNED_SHA}" >&2
        exit 1
    fi
    RESOLVED=$(git rev-parse "${PINNED_SHA}^{commit}")
    echo "[OK] 已釘選不可變 SHA。reviewer 必須用 'git show <sha>:<path>' 或獨立 checkout 讀檔，不得讀工作區。"
    echo "PINNED=${RESOLVED}"
    exit 0
fi

HEAD_SHA=$(git rev-parse HEAD)
echo "[OK] 工作區快照穩定：無未解衝突、無進行中的 merge。"
echo "HEAD=${HEAD_SHA}"
