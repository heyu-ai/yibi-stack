#!/usr/bin/env bash
# check-baseline.sh -- issue-triage 證據基準檢查
#
# 驗證 issue 症狀之前，確認「被檢視的程式碼」就是剛 fetch 的 origin/main：
# 落後的 main 或沒合併的分支，會讓 DONE 與 NOT DONE 都判反。
# 在目標 repo 的目錄執行，無需參數。
#
# stdout（僅成功時）：BASELINE_SHA=<40 字元 SHA> FETCHED_AT=<ISO 8601 UTC>
# stderr（僅失敗時）：以 [FAIL] 開頭的說明與補救方式
#
# Exit codes:
#   0  基準通過
#   1  腳本自身的未預期錯誤（不是基準問題，不要當成「沒有漂移」）
#   2  不在可讀取的 git repo
#   3  fetch origin main 失敗（不回退到本機殘留的 origin/main）
#   4  checkout 的 commit 與 origin/main 不一致（訊息含 ahead 與 behind 數）
#   5  tracked 檔案有未提交的修改（訊息含檔案數）；含被 assume-unchanged / skip-worktree
#      旗標隱藏、但磁碟內容與 HEAD 不同的檔案（sparse checkout 不在磁碟上的檔案不算）
#
# 已知殘餘風險：untracked 檔案不算失敗，但 Grep 工具會搜到它們，可能造成假的 DONE。
# 主 checkout 的 untracked 暫存目錄極為常見，列為失敗會讓檢查幾乎永遠紅。
set -euo pipefail

# 檢查對象是 Read/Grep 會讀到的 cwd 工作樹；GIT_DIR 等變數若指向別的 repo，
# git 會回報另一個 repo 的狀態，與實際被讀取的檔案脫鉤，所以每個 git 呼叫都先清掉。
# GIT_TERMINAL_PROMPT=0：fetch 遇到需要認證的 remote 時直接失敗，不要卡在互動提示。
_git() {
  env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE GIT_TERMINAL_PROMPT=0 git "$@"
}

fail() {
  echo "[FAIL] $2" >&2
  exit "$1"
}

ERR_FILE=$(mktemp)
LSV_FILE=$(mktemp)
trap 'rm -f "$ERR_FILE" "$LSV_FILE"' EXIT

if ! INSIDE=$(_git rev-parse --is-inside-work-tree 2>/dev/null); then
  fail 2 "目前目錄不是可讀取的 git repo；請在要盤點的 repo 內執行"
fi
if [ "$INSIDE" != "true" ]; then
  fail 2 "目前目錄不在 git 工作樹內；請在要盤點的 repo 內執行"
fi

if ! FETCH_OUT=$(_git fetch --quiet origin "+refs/heads/main:refs/remotes/origin/main" 2>&1); then
  fail 3 "fetch origin main 失敗，無法確認基準（不會回退到本機的 origin/main）：${FETCH_OUT}"
fi
FETCHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 一律用完整 ref：短名稱 origin/main 會先解析到同名的本機分支（refs/heads/origin/main）。
# stdout 才是要解析的值；stderr 另存，避免 git 的 warning 混進 SHA 或計數。
if ! BASELINE_SHA=$(_git rev-parse --verify --quiet "refs/remotes/origin/main^{commit}" 2>"$ERR_FILE"); then
  fail 1 "fetch 成功但解析不到 refs/remotes/origin/main；這是腳本或 git 的未預期狀態，請回報：$(cat "$ERR_FILE")"
fi
if ! COUNTS=$(_git rev-list --left-right --count "HEAD...${BASELINE_SHA}" 2>"$ERR_FILE"); then
  fail 1 "無法比較 HEAD 與 origin/main：$(cat "$ERR_FILE")"
fi
read -r AHEAD BEHIND <<< "$COUNTS"

if [ "$AHEAD" != "0" ] || [ "$BEHIND" != "0" ]; then
  fail 4 "checkout 與 origin/main 不一致：ahead=${AHEAD} behind=${BEHIND}；請從 origin/main 開乾淨的 worktree，或先更新主 checkout 再重跑"
fi

if ! MODIFIED=$(_git status --porcelain --untracked-files=no 2>"$ERR_FILE"); then
  fail 1 "無法讀取工作樹狀態：$(cat "$ERR_FILE")"
fi
if [ -n "$MODIFIED" ]; then
  COUNT=$(printf '%s\n' "$MODIFIED" | wc -l)
  COUNT=${COUNT// /}
  echo "[FAIL] tracked 檔案有未提交的修改：modified=${COUNT}；請提交、還原，或改在乾淨的 worktree 執行" >&2
  printf '%s\n' "$MODIFIED" >&2
  exit 5
fi

# `git status` 不看被 assume-unchanged（小寫 tag）或 skip-worktree（S/s）標記的檔案，
# 但 Read/Grep 讀的是磁碟內容：磁碟上存在的這類檔案必須逐一比對 HEAD 的 blob。
# sparse checkout 的 skip-worktree 檔案不在磁碟上，沒有東西被讀到，略過。
if ! _git ls-files -v -z > "$LSV_FILE" 2>"$ERR_FILE"; then
  fail 1 "無法讀取 index 旗標：$(cat "$ERR_FILE")"
fi
HIDDEN=""
HIDDEN_COUNT=0
while IFS= read -r -d '' ENTRY; do
  TAG=${ENTRY:0:1}
  # 明列 tag 而不用 [a-z]：bash 的範圍比對依 locale 排序，可能把大寫 H 也算進去
  case "$TAG" in
    h|s|m|r|c|k|S) ;;
    *) continue ;;
  esac
  FILE_PATH=${ENTRY:2}
  if [ -L "$FILE_PATH" ]; then
    LINK_TARGET=$(readlink "$FILE_PATH")
    if ! DISK_SHA=$(printf '%s' "$LINK_TARGET" | _git hash-object --stdin 2>"$ERR_FILE"); then
      fail 1 "無法計算 ${FILE_PATH} 的 hash：$(cat "$ERR_FILE")"
    fi
  elif [ -f "$FILE_PATH" ]; then
    if ! DISK_SHA=$(_git hash-object -- "$FILE_PATH" 2>"$ERR_FILE"); then
      fail 1 "無法計算 ${FILE_PATH} 的 hash：$(cat "$ERR_FILE")"
    fi
  else
    continue
  fi
  if ! HEAD_SHA=$(_git rev-parse --verify --quiet "HEAD:${FILE_PATH}" 2>"$ERR_FILE"); then
    HEAD_SHA="(not-in-HEAD)"
  fi
  if [ "$DISK_SHA" != "$HEAD_SHA" ]; then
    HIDDEN="${HIDDEN}${FILE_PATH}"$'\n'
    HIDDEN_COUNT=$((HIDDEN_COUNT + 1))
  fi
done < "$LSV_FILE"
if [ "$HIDDEN_COUNT" -gt 0 ]; then
  echo "[FAIL] tracked 檔案被 assume-unchanged / skip-worktree 標記隱藏，且磁碟內容與 HEAD 不同：modified=${HIDDEN_COUNT}；請還原內容或清除旗標（git update-index --no-assume-unchanged / --no-skip-worktree），或改在乾淨的 worktree 執行" >&2
  printf '%s' "$HIDDEN" >&2
  exit 5
fi

echo "BASELINE_SHA=${BASELINE_SHA} FETCHED_AT=${FETCHED_AT}"
