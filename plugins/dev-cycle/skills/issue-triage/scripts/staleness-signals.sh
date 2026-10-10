#!/usr/bin/env bash
# staleness-signals.sh -- issue-triage 程式碼漂移訊號
#
# 用法：staleness-signals.sh <issue 建立時間 ISO 8601> [<repo 相對路徑>...]
# 在目標 repo 的目錄（根目錄或任何子目錄）執行；先跑過 check-baseline.sh（確保 origin/main 是新的）。
# 路徑一律是 repo 根目錄相對：腳本會先切到 repo 根目錄，不論從哪一層呼叫，同一個引數結果相同。
#
# issue 引用的檔案若自建立以來被刪除、改名或大量變動，就是比天數更直接的
# 「前提可能已消失」訊號。狀態由 refs/remotes/origin/main 的歷史判斷，不看工作樹；一律用完整 ref，
# 因為短名稱 origin/main 會先解析到同名的本機分支（refs/heads/origin/main）。
#
# stdout：每個路徑一行，以 tab 分隔「路徑、狀態、細節」
#   unchanged      仍存在，自建立後沒有 commit 動過它；細節為空
#   changed        仍存在，自建立後被動過；細節為 commit 數
#   deleted        已不存在，歷史上被刪除；細節為刪除它的 commit SHA
#   renamed        已不存在於原路徑，歷史上被改名；細節為新路徑
#   never-existed  origin/main 的歷史上從未有過這個路徑；細節為空
# 沒有任何路徑時輸出單行 NOT_APPLICABLE。「沒有漂移訊號」不等於「前提仍成立」，
# 這由呼叫端處理，本腳本不下結論。
#
# Exit codes:
#   0  成功
#   1  腳本自身的未預期錯誤（不是漂移結果，不要當成「沒有漂移」）
#   2  參數錯誤（缺建立時間、時間格式不對；路徑為空、絕對路徑、含 ..，或含 tab 或換行）
#   3  不在 git repo 內，或 refs/remotes/origin/main 不存在（請先跑 check-baseline.sh）
#
# 已知限制：
#   - git 的 --since 依 commit 時間過濾，commit 時間嚴重倒退的歷史可能少算。
#   - 刪除或改名發生在 merge commit 上時，只會看到合併後的差異，可能判成 deleted。
#   - 只認「路徑」；issue 只提到符號或功能名稱時沒有任何訊號。
set -euo pipefail

# 路徑必須逐字比對：GIT_LITERAL_PATHSPECS 讓 *、:(glob) 等不被當成 pathspec 語法。
# 同時清掉會讓 git 忽略 cwd 的環境變數，並關閉非 ASCII 檔名的引號跳脫。
_git() {
  env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE \
    GIT_LITERAL_PATHSPECS=1 git -c core.quotepath=false "$@"
}

fail() {
  echo "[FAIL] $2" >&2
  exit "$1"
}

CREATED_AT="${1:-}"
if [ -z "$CREATED_AT" ]; then
  fail 2 "缺少 issue 建立時間；用法：staleness-signals.sh <ISO 8601 時間> [路徑...]"
fi
TIME_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:?[0-9]{2})?)?$'
if ! [[ "$CREATED_AT" =~ $TIME_RE ]]; then
  fail 2 "issue 建立時間格式不對：${CREATED_AT}（需要 ISO 8601，例如 2026-03-01T00:00:00Z）"
fi
shift

for p in "$@"; do
  case "$p" in
    "" | /* | .. | ../* | */.. | */../* | *$'\t'* | *$'\n'*)
      fail 2 "路徑必須是 repo 相對路徑，不得為空、絕對路徑、含 .. 或含 tab 與換行：${p}"
      ;;
  esac
done

ERR_FILE=$(mktemp)
trap 'rm -f "$ERR_FILE"' EXIT

if ! ROOT=$(_git rev-parse --show-toplevel 2>"$ERR_FILE"); then
  fail 3 "目前目錄不在 git repo 內；請在要盤點的 repo 內執行：$(cat "$ERR_FILE")"
fi
# pathspec 預設相對於 cwd；從子目錄呼叫時 `sub/x.txt` 會被解讀成 `sub/sub/x.txt` 而誤判 never-existed。
if ! cd "$ROOT"; then
  fail 1 "無法切到 repo 根目錄：${ROOT}"
fi

# 只解析一次，之後每個查詢都用這個 SHA；stderr 另存並附在失敗訊息裡，不丟掉。
REF="refs/remotes/origin/main"
if ! BASE=$(_git rev-parse --verify --quiet "${REF}^{commit}" 2>"$ERR_FILE"); then
  fail 3 "找不到 ${REF}；請先跑 check-baseline.sh $(cat "$ERR_FILE")"
fi

if [ "$#" -eq 0 ]; then
  echo "NOT_APPLICABLE"
  exit 0
fi

emit() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3"
}

for p in "$@"; do
  if ! LISTED=$(_git ls-tree --name-only "$BASE" -- "$p" 2>"$ERR_FILE"); then
    fail 1 "無法讀取 ${REF} 的檔案樹：$(cat "$ERR_FILE")"
  fi

  if [ -n "$LISTED" ]; then
    if ! COUNT=$(_git rev-list --count --since="$CREATED_AT" "$BASE" -- "$p" 2>"$ERR_FILE"); then
      fail 1 "無法計算 ${p} 的變動次數：$(cat "$ERR_FILE")"
    fi
    if [ "$COUNT" = "0" ]; then
      emit "$p" unchanged ""
    else
      emit "$p" changed "$COUNT"
    fi
    continue
  fi

  # 已不在 origin/main：找出刪除它的 commit。用 `log -- <舊路徑>` 看不到改名
  # （目的端不在 pathspec 內，rename 偵測不會觸發，會顯示成刪除），
  # 所以先定位刪除的 commit，再針對那一個 commit 做 -M 偵測。
  if ! DEL_SHA=$(_git log "$BASE" --diff-filter=D --format=%H -1 -- "$p" 2>"$ERR_FILE"); then
    fail 1 "無法查詢 ${p} 的刪除紀錄：$(cat "$ERR_FILE")"
  fi
  if [ -z "$DEL_SHA" ]; then
    emit "$p" never-existed ""
    continue
  fi

  if ! SHOWN=$(_git show -M --name-status --format= "$DEL_SHA" 2>"$ERR_FILE"); then
    fail 1 "無法讀取 commit ${DEL_SHA} 的變更：$(cat "$ERR_FILE")"
  fi
  RENAMED_TO=""
  while IFS=$'\t' read -r STATUS OLD NEW; do
    case "$STATUS" in
      R*)
        if [ "$OLD" = "$p" ]; then
          RENAMED_TO="$NEW"
          break
        fi
        ;;
    esac
  done <<< "$SHOWN"

  if [ -n "$RENAMED_TO" ]; then
    emit "$p" renamed "$RENAMED_TO"
  else
    emit "$p" deleted "$DEL_SHA"
  fi
done
