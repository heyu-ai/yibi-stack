#!/usr/bin/env bash
# last-human-activity.sh -- issue-triage 最後一次實質人為活動
#
# 用法：last-human-activity.sh <issue 編號>
# 目標 repo 取自目前目錄的 gh 設定（或 GH_REPO）。
#
# 「最後一次實質人為活動」= issue 建立時間，與所有「非 bot 且非 skill 自己」的留言時間
# 之中最晚的一個。排除 bot 與 skill 自己，是為了不讓 stale bot 或這個 skill 的每次盤點
# 重置過期時鐘。
#
# bot 的判定只看帳號型別（REST 的 user.type 為 Bot），不看 login 文字：實測 gh issue list
# 的 JSON 會去掉 [bot] 後綴（github-actions[bot] 顯示為 github-actions），Copilot 這類 bot
# 更是本來就沒有後綴，所以這支腳本走 REST。已刪除的帳號（user 為 null）與沒見過的帳號型別
# 一律視為人為活動，往「看起來比較活躍」的安全方向失敗。
#
# skill 自己貼的留言 = 內文「最後一個非空行」恰好是一個完整的 triage 標記
# `<!-- issue-triage:<已知種類> YYYY-MM-DD -->`（已知種類：close、update-scope、merge、
# stale-notice，與 SKILL.md 一致；SKILL.md 規定標記是留言的最後一行），且作者是目前登入的帳號。
# 只比對前綴不夠：內文提到 `<!-- issue-triage:stale-notice` 的人為留言、或 `stale-notice-foo`
# 這種長得像的種類，都會被誤當成 skill 的留言而從活動度量隱形。標記單獨出現也不夠：
# 任何人都能貼上標記，所以還要比對作者。
#
# stdout（僅成功時）：一行，tab 分隔
#   <最後人為活動時間 ISO 8601>  <stale notice 留言的時間；沒有則為空>
# stderr（僅失敗時）：以 [FAIL] 開頭的說明，stdout 不輸出任何東西
#
# Exit codes:
#   0  成功
#   1  腳本自身的未預期錯誤
#   2  參數錯誤（缺 issue 編號或不是正整數）
#   3  gh API 呼叫失敗（目前帳號、issue、留言任一個）；不會回退成「沒有人是 skill」
#   4  缺 jq，或 API 回應無法解析
#
# 對外只做三種 gh 呼叫（測試以假的 gh 回放，並以靜態測試確認沒有偏離）：
#   目前登入的帳號、issue 本身、issue 的全部留言（含分頁）。
set -euo pipefail

fail() {
  echo "[FAIL] $2" >&2
  exit "$1"
}

ISSUE="${1:-}"
case "$ISSUE" in
  "" | *[!0-9]* | 0*)
    fail 2 "需要一個正整數的 issue 編號；用法：last-human-activity.sh <issue 編號>"
    ;;
esac

if ! command -v jq > /dev/null 2>&1; then
  fail 4 "找不到 jq；請先安裝（例如 brew install jq）"
fi

ERRFILE=$(mktemp)
trap 'rm -f "$ERRFILE"' EXIT

if ! USER_JSON=$(gh api user 2> "$ERRFILE"); then
  fail 3 "取得目前登入帳號失敗（無法判斷哪些留言是 skill 自己貼的）：$(cat "$ERRFILE")"
fi
if ! ISSUE_JSON=$(gh api "repos/{owner}/{repo}/issues/${ISSUE}" 2> "$ERRFILE"); then
  fail 3 "取得 issue #${ISSUE} 失敗：$(cat "$ERRFILE")"
fi
if ! COMMENTS_JSON=$(gh api "repos/{owner}/{repo}/issues/${ISSUE}/comments" --paginate 2> "$ERRFILE"); then
  fail 3 "取得 issue #${ISSUE} 的留言失敗：$(cat "$ERRFILE")"
fi

if ! VIEWER=$(printf '%s' "$USER_JSON" | jq -er '.login' 2> "$ERRFILE"); then
  fail 4 "目前登入帳號的回應沒有 login 欄位：$(cat "$ERRFILE")"
fi
if ! CREATED=$(printf '%s' "$ISSUE_JSON" | jq -er '.created_at' 2> "$ERRFILE"); then
  fail 4 "issue #${ISSUE} 的回應沒有 created_at 欄位：$(cat "$ERRFILE")"
fi

# gh --paginate 會把每一頁的陣列連續輸出（不是合併成一個陣列），所以用 -s 讀成陣列的陣列。
JQ_PROGRAM='
  def last_line: (.body // "") | split("\n") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0)) | (last // "");
  def marker: last_line | test("^<!--\\s*issue-triage:(close|update-scope|merge|stale-notice)\\s+[0-9]{4}-[0-9]{2}-[0-9]{2}\\s*-->$");
  def own($me): marker and (((.user.login // "") | ascii_downcase) == $me);
  def bot: (.user.type // "") == "Bot";
  def notice($me): own($me) and (last_line | test("^<!--\\s*issue-triage:stale-notice\\s+"));
  ([.[] | .[]]) as $all
  | ($viewer | ascii_downcase) as $me
  | ([$created] + [$all[] | select((bot or own($me)) | not) | .created_at] | max) as $last
  | ([$all[] | select(notice($me)) | .created_at] | max // "") as $stale
  | "\($last)\t\($stale)"
'
if ! RESULT=$(printf '%s' "$COMMENTS_JSON" | jq -s -r --arg viewer "$VIEWER" --arg created "$CREATED" "$JQ_PROGRAM" 2> "$ERRFILE"); then
  fail 4 "issue #${ISSUE} 的留言回應無法解析：$(cat "$ERRFILE")"
fi

printf '%s\n' "$RESULT"
