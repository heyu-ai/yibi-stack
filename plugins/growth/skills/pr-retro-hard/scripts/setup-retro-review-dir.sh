#!/usr/bin/env bash
#
# 為 /pr-retro-hard 建立本次 review 的隔離產物目錄，並把產物根目錄註冊進 git exclude。
#
# 用法：bash setup-retro-review-dir.sh --pr <n>
# stdout：單行 `RETRO_REVIEW_DIR=<絕對路徑>`（呼叫端解析此行）
# stderr：所有 [FAIL] / [WARN] / [INFO] 診斷
#
# 退出碼：
#   0  成功，stdout 有 RETRO_REVIEW_DIR
#   1  執行期失敗（無法建目錄、exclude 不可寫、git 查詢失敗）
#   2  呼叫端用法錯誤（缺 --pr、--pr 缺值、PR 號非數字、未知參數）
#
# 本 script 刻意 **不** 清除繼承的 GIT_DIR / GIT_WORK_TREE：它問的是「呼叫端目前在哪個 repo
# 工作」，而非「本 script 自己住在哪」。rule 13 要求只在後者清除 git 環境變數；在前者清除
# 會破壞它想回答的問題本身。
set -euo pipefail

PR_NUMBER=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --pr)
            # set -u 下若使用者漏帶值，直接 deref "$2" 會炸 unbound variable stacktrace
            # 而非 clean [FAIL]。故先驗 $# 邊界。
            if [ "$#" -lt 2 ]; then
                echo "[FAIL] --pr 需要一個值，例如：--pr 123" >&2
                exit 2
            fi
            PR_NUMBER="$2"
            shift 2
            ;;
        *)
            echo "[FAIL] 未知參數：$1（唯一支援的參數是 --pr <n>）" >&2
            exit 2
            ;;
    esac
done

if [ -z "$PR_NUMBER" ]; then
    echo "[FAIL] 缺少 --pr <n>；本 script 需要 PR 號才能隔離產物目錄" >&2
    exit 2
fi

case "$PR_NUMBER" in
    ''|*[!0-9]*)
        echo "[FAIL] --pr 的值必須是純數字，收到：${PR_NUMBER}" >&2
        exit 2
        ;;
esac

if ! WT_ROOT=$(git rev-parse --show-toplevel); then
    echo "[FAIL] git rev-parse --show-toplevel 失敗；請在 git repo 內執行" >&2
    exit 1
fi

RETRO_REVIEW_ROOT="$WT_ROOT/.runtime/retro-review"
PR_DIR="$RETRO_REVIEW_ROOT/pr-${PR_NUMBER}"

if ! mkdir -p "$PR_DIR"; then
    echo "[FAIL] 無法建立產物目錄：${PR_DIR}（請確認 worktree 目錄有寫入權限）" >&2
    exit 1
fi

# info/exclude 的路徑必須用 --git-path 解析，不可用 --git-dir 自行拼接。
# linked worktree 下 --git-dir 回 per-worktree 目錄（.git/worktrees/<name>），但 git status
# 實際讀取的 info/exclude 在 common dir（.git/info/exclude）；寫到拼出來的位置會被 git
# 忽略且靜默失效（PR #203 實機發現）。--git-path 在主 worktree 與 linked worktree 都正確。
#
# 注意 info/exclude 是 **跨 worktree 共用** 的 git 中介資料，不是本 worktree 私有檔——
# 故只能 append、必須先查重、且不得覆寫既有內容。
if ! EXCLUDE_FILE=$(git rev-parse --git-path info/exclude); then
    echo "[FAIL] git rev-parse --git-path info/exclude 失敗；無法定位 exclude 檔" >&2
    exit 1
fi
EXCLUDE_DIR=$(dirname "$EXCLUDE_FILE")

if ! mkdir -p "$EXCLUDE_DIR"; then
    echo "[FAIL] 無法建立 ${EXCLUDE_DIR}（請確認 .git 目錄可寫）" >&2
    exit 1
fi

EXCLUDE_LINE='.runtime/'

# 用 -Fx 做整行精確比對，不用 -F。子字串比對會把 `!.runtime/keep` 這類既有行誤判成
# 「已註冊」，於是 .runtime/ 永遠不被加入、git status 持續被產物污染——靜默失效。
NEEDS_APPEND=1
if [ -f "$EXCLUDE_FILE" ]; then
    if grep -qFx "$EXCLUDE_LINE" "$EXCLUDE_FILE"; then
        NEEDS_APPEND=0
    fi
fi

if [ "$NEEDS_APPEND" -eq 1 ]; then
    # 這個 if 是唯一的可寫性關卡，刻意不在前面再加一道 `[ -w ]` 預檢：redirection 失敗時
    # bash 不執行該命令並回非零，`if !` 一律攔到，故預檢是無法被任何測試區分的冗餘分支
    # （突變驗證實測：把預檢換成 no-op，行為測試仍全綠）。
    #
    # 訊息不指名「檔案」或「目錄」哪一個不可寫——此分支的判定條件無從區分兩者，
    # 指名未經證實的原因會誤導讀者（rule 11：提示必須與其分支的判定條件一致）。
    if ! echo "$EXCLUDE_LINE" >> "$EXCLUDE_FILE"; then
        echo "[FAIL] 無法寫入 exclude：${EXCLUDE_FILE}（請確認該檔與其目錄的權限；未註冊 ${EXCLUDE_LINE} 會讓 review 產物持續污染 git status）" >&2
        exit 1
    fi
fi

# 陳舊產物偵測：同 PR 先前執行留下的 run-* 目錄。用 bash array + nullglob，不用 ls | wc
# ——後者在零筆時仍回 1、且解析 ls 輸出在檔名含空白時失效。
shopt -s nullglob
PRIOR_RUNS=( "$PR_DIR"/run-* )
shopt -u nullglob
if [ "${#PRIOR_RUNS[@]}" -gt 0 ]; then
    echo "[WARN] PR #${PR_NUMBER} 已有 ${#PRIOR_RUNS[@]} 份先前執行的產物留在 ${PR_DIR}；本次會寫入新的 run 目錄，先前產物不會被當成本次結果讀取" >&2
fi

# 每次執行取得獨立 run 目錄。mktemp -d 是原子建立，故同 PR 併發執行或多 worktree 併發
# 都不會互相覆蓋——這同時滿足「併發不覆蓋」與「陳舊產物不被誤用」兩項要求。
if ! RUN_DIR=$(mktemp -d "$PR_DIR/run-XXXXXX"); then
    echo "[FAIL] 無法建立本次 run 目錄於 ${PR_DIR}（請確認寫入權限）" >&2
    exit 1
fi

echo "RETRO_REVIEW_DIR=$RUN_DIR"
