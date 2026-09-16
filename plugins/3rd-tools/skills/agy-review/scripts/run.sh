#!/usr/bin/env bash
# agy standalone review/challenge runner
# Usage: run.sh <mode> <base> [instruction]
#   mode:        review | challenge
#   base:        base branch (e.g. main, develop)
#   instruction: optional focus string (can be empty "")
set -euo pipefail

MODE="${1:-review}"
BASE="${2:-main}"
INSTRUCTION="${3:-}"

if [ -z "$BASE" ]; then
    echo "[FAIL] BASE branch is empty. Pass the base branch name as the second argument." >&2
    exit 1
fi

if ! command -v agy >/dev/null 2>&1; then
    echo "[FAIL] agy not found. Install with: pip install antigravity-cli" >&2
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)

# 預設用 Gemini：本 skill 存在的理由是取得**跨廠商**的第二意見，預設若是 Claude，
# 在 mob review 裡會與 Claude voice 家族塌縮（兩票同源卻被當成兩家）。
# 2026-09-03 實測（agy 1.1.25，台灣）：gemini-3.8-flash-high / 3.8-flash-low /
# 3.7-flash-low / 3.6-flash-low / 3.1-pro-low 五個 model id 各發一次請求全部成功，
# 無 FAILED_PRECONDITION: User location is not supported。四個模型各自回報與請求
# 一致的名稱，排除靜默 fallback。（此前的預設 claude-sonnet-4-6 是為了規避該地區
# 限制，該前提已不成立。）
# 這是版本相依的實測，不是永久事實——agy 升版後若 Gemini 路徑再度失效，請重測後
# 再改預設，並更新這段註解的版本戳記（rule 13 probe-rot）。
# 允許透過 AGY_MODEL 環境變數覆寫（可接受值見 `agy models` 左欄）。
AGY_MODEL="${AGY_MODEL:-gemini-3.8-flash-high}"

# agy print 模式的時間預算（整數秒），理由與 agy-consult/scripts/consult.sh 同段相同：
# `--print-timeout` 到期時回傳片段並 exit 0 的行為自 **agy 1.1.28** 起（changelog 1.1.28 原文
# 「returns the partial output it has and exits successfully」），以 1.2.3 實測複驗；預設 480 秒
# 低於 Claude Code Bash tool 的 600 秒上限，否則 harness 先砍掉 script，[FAIL] 診斷永遠印不出來。
# 上下界由程式強制，不只寫在文件：貼著 600 會原樣重現本 PR 要消滅的事故形狀，0 會讓耗時判定恆真。
# 上界取 570 而非 599：預算計的是 agy 內部時間，牆鐘還要加上 language server 啟動（實測 20 秒
# 預算的真 timeout 牆鐘 22 秒），599 + 啟動 ≈ 601 > 600，形同放行一個必然被 harness 砍掉的值。
AGY_PRINT_TIMEOUT_MAX=570
AGY_PRINT_TIMEOUT_SECS="${AGY_PRINT_TIMEOUT_SECS:-480}"
# 不需要 `''|`：上一行的 `:-` 對空字串也套用預設值。
case "$AGY_PRINT_TIMEOUT_SECS" in
    *[!0-9]*)
        echo "[FAIL] AGY_PRINT_TIMEOUT_SECS 必須是整數秒（收到：${AGY_PRINT_TIMEOUT_SECS}），例如 480" >&2
        exit 2
        ;;
esac
# 先擋長度再做數值比較（理由見 consult.sh 同段：超出 shell 整數範圍時 `[ -lt ]` 會以錯誤返回，
# 在 if 條件裡不受 set -e 管，超大值反而被放行）。
case "$AGY_PRINT_TIMEOUT_SECS" in
    ???|??|?) ;;
    *)
        echo "[FAIL] AGY_PRINT_TIMEOUT_SECS 必須介於 1 與 ${AGY_PRINT_TIMEOUT_MAX} 之間（收到：${AGY_PRINT_TIMEOUT_SECS}）。" >&2
        exit 2
        ;;
esac
if [ "$AGY_PRINT_TIMEOUT_SECS" -lt 1 ] || [ "$AGY_PRINT_TIMEOUT_SECS" -gt "$AGY_PRINT_TIMEOUT_MAX" ]; then
    echo "[FAIL] AGY_PRINT_TIMEOUT_SECS 必須介於 1 與 ${AGY_PRINT_TIMEOUT_MAX} 之間（收到：${AGY_PRINT_TIMEOUT_SECS}）。" >&2
    echo "       上界留了 30 秒餘裕給 agy 的啟動時間：預算是 agy 內部計時，牆鐘還要加上 language server 啟動（實測約 2 秒）；貼著 600 設會讓 Claude Code Bash tool 先砍掉整支 script，所有診斷都印不出來。0 則會讓耗時判定對任何回答都成立。" >&2
    exit 2
fi

# 參數驗證通過後才碰 agy（AC-5 要求參數無效時不呼叫 agy，而 `agy --help` 也算一次呼叫）。
# 舊版 agy 不認得新 flag，且它對未知 flag 的退出碼也是 2，與上方驗證撞號，故在此先擋下。
# 退出碼與輸出分開判斷（理由見 consult.sh 同段：`|| true` 會讓「agy 在但 --help 因別的原因
# 失敗」被誤報成「版本太舊請升級」，正是 rule 13「|| true Turns a Real Result Into a Silent
# Skip」那一節的形狀）。
AGY_HELP_EXIT=0
AGY_HELP=$(agy --help 2>&1) || AGY_HELP_EXIT=$?
if [ "$AGY_HELP_EXIT" -ne 0 ]; then
    echo "[FAIL] agy --help 執行失敗（exit ${AGY_HELP_EXIT}），無法確認它是否支援本腳本需要的 flag。原始輸出：" >&2
    printf '%s\n' "$AGY_HELP" >&2
    exit 2
fi
for flag in --print-timeout --log-file; do
    case "$AGY_HELP" in
        *"$flag"*) ;;
        *)
            echo "[FAIL] 這個 agy 版本不支援 ${flag}，本腳本的 timeout 防線無法運作。" >&2
            echo "       該行為自 agy 1.1.28 起提供，請升級：agy update（或 pip install -U antigravity-cli）。" >&2
            exit 2
            ;;
    esac
done

# Get diff; fallback to HEAD~1 when no upstream tracking
DIFF=$(git diff "origin/${BASE}...HEAD" 2>/dev/null || git diff HEAD~1 2>/dev/null || true)
if [ -z "$DIFF" ]; then
    echo "[FAIL] diff is empty or unavailable. Ensure origin/${BASE} exists and commits are present." >&2
    exit 1
fi

if [ "$MODE" = "challenge" ]; then
  HEADER="你是資深 security 與 correctness 審查員，以對抗模式審查以下 PR diff。只找問題，不給讚美。尋找：bug、race condition、安全漏洞、邊界條件錯誤、效能陷阱。每個問題標記 [P0]（production 致命）或 [P1]（嚴重）。找不到問題時輸出 [PASS] No critical issues found。"
else
  HEADER="你是資深程式碼審查員，審查以下 PR diff。評估：正確性、安全性、可讀性、邊界條件。嚴重問題標記 [P0]（production 致命）或 [P1]（嚴重）。結尾必須輸出 [PASS]（無 P0/P1 問題）或 [FAIL]（有 P0/P1 問題），後接一行中文 summary。"
fi

cd "$REPO_ROOT"

# prompt 以 inline 形式當 -p 的值傳入，取代 @file（nested worktree（.claude/worktrees/<name>/）下
# @file 解析失敗會讓 agy 靜默進入 agentic 探索模式：review 錯 target / brain-artifact / timeout，
# 與 pr-cycle-deep issue #153 同根因）。inline 保住三點：
#   (1) agy 不讀 @file 即無 agentic 觸發點；
#   (2) 開頭永遠是 HEADER，內容不會以 '@' 起始而被誤判成檔案路徑重觸發本 bug；
#   (3) prompt 本身不落地，免去並行 review 互相覆寫與 SIGKILL 繞過 EXIT trap 殘留 untracked 檔。
#       （下方的 stderr／log 暫存檔是後來加的診斷管道，落在 $TMPDIR 而非 worktree，且檔名由
#       mktemp 產生，所以並行覆寫與 untracked 殘留這兩個理由都不受影響。）
#
# 不可改回 `{ ... } | agy --print ...`（PR #229 retro 實測）：-p/--print 不是 boolean，它把
# 下一個 token 當 prompt 值吃掉，因此該形式會讓 agy 收到 "--add-dir" 當 prompt、完全不讀 pipe
# 進來的 diff，回一段關於 --add-dir 的說明後 exit 0——靜默失敗，看起來像 review 但不是。
# agy 1.1.2 沒有 stdin prompt 通道（`printf 'x' | agy --print` 直接報 flag needs an argument）。
# 代價是 inline 佔 ARG_MAX 參數預算，故需下方 size guard（比照 pr-cycle-deep 的 agy 腳本）。
# --sandbox 保持不變（standalone 為輕量第二意見，維持較嚴格的 sandbox security posture）。
PROMPT_CONTENT=$(
  printf '%s\n\n' "$HEADER"
  if [ -n "$INSTRUCTION" ]; then
    printf '特別關注：%s\n\n' "$INSTRUCTION"
  fi
  printf 'Base branch: %s\n\n' "$BASE"
  printf '```diff\n%s\n```\n' "$DIFF"
)

# 用實際位元組數而非字元數（PR #367 mob review Important：${#PROMPT_CONTENT} 在 UTF-8
# locale 下數的是字元，中文 diff 會低估約 3 倍，讓這道 ARG_MAX 防線對主打的中文情境失效）。
PROMPT_BYTES=$(printf '%s' "$PROMPT_CONTENT" | wc -c)
if [ "$PROMPT_BYTES" -gt 256000 ]; then
  echo "[FAIL] review 輸入 ${PROMPT_BYTES}B 超過 256000B inline 上限，diff 過大不適合 agy inline 模式" >&2
  exit 1
fi

# 空輸出偵測（PR #367 mob review Critical，agy 1.1.8 實測確認）：--sandbox 底下 agy 想
# 主動探索 --add-dir 內容時，可能因 agy 自己的權限系統（與 Claude Code 的設定完全獨立）
# 擋下探索指令；headless 模式沒有終端可以核准，agy 會直接無輸出退出。不偵測的話，這支
# script 會把空白當成「完成的 review」原樣呈現。
# if 條件本身會豁免 set -e（`if`/`while`/`until` 條件、或 `&&`/`||` 前的指令不受 set -e 管），
# 這裡刻意用 if 包住賦值：agy 非零結束時若直接寫 `OUTPUT=$(...); AGY_EXIT=$?`，set -e 會在
# 賦值那行就中止 script，下面這行 AGY_EXIT=$? 永遠執行不到，[FAIL] 診斷訊息變死碼（實測驗證）。
# --add-dir 必須傳絕對路徑，不可傳相對的 `.`（agy 1.1.22 實測，見 agy-consult/scripts/consult.sh
# 的完整負向對照記錄）：agy 1.1.22 不再把相對路徑解析成 active workspace，即使已 cd 到該目錄、
# 且該目錄就在 trustedWorkspaces 清單內。失敗時 agy exit 0 並回一段語意完整但沒讀到任何檔案的
# 文字，下方 exit-code gate 與 20 字元下限都攔不住——對 review 而言等於產出一份沒看過程式碼的
# review 卻看起來正常，是本檔最不該靜默失敗的地方。
#
# stderr 與 agy log 分別落地、timeout 用兩個獨立訊號判定、log 一律保留、stderr 由 trap 在任何
# 離開路徑補放——完整理由與 agy 1.1.28／1.2.3 實測記錄見 agy-consult/scripts/consult.sh 同段
# 註解。對 review 而言，把 timeout 的半截輸出當成完整 review 呈現，等於產出一份還沒看完 diff
# 的 [PASS]，是本檔最不該靜默失敗的另一處。
AGY_STDERR_FILE=$(mktemp "${TMPDIR:-/tmp}/agy-review-stderr.XXXXXX")
AGY_LOG_FILE=$(mktemp "${TMPDIR:-/tmp}/agy-review-log.XXXXXX")

# 刪檔只掛在 EXIT，不掛在訊號路徑（理由見 consult.sh 同段：訊號 handler 先 rm 會讓主線的讀取
# 在 set -e 下把 rc 從 143 變成 1）。同段也記錄了這個修法的實測邊界：bash 會把訊號處理延後到
# 前景子行程結束，所以補送發生在 agy 返回時而非被砍當下；真正做事的是 EXIT trap，INT/TERM/HUP
# 是冗餘的第二層；整組被砍或 SIGKILL 則兩者皆無效（已知殘餘）。
AGY_STDERR_REPLAYED=0
replay_agy_stderr() {
    if [ "$AGY_STDERR_REPLAYED" -eq 0 ] && [ -s "$AGY_STDERR_FILE" ]; then
        cat "$AGY_STDERR_FILE" >&2
        AGY_STDERR_REPLAYED=1
    fi
}
on_agy_exit() {
    replay_agy_stderr
    rm -f "$AGY_STDERR_FILE"
}
# 退出碼按訊號給（128 + signo），理由見 consult.sh 同段。
on_agy_signal() {
    replay_agy_stderr
    exit "$1"
}
trap on_agy_exit EXIT
trap 'on_agy_signal 130' INT
trap 'on_agy_signal 143' TERM
trap 'on_agy_signal 129' HUP

echo "[INFO] agy 模型：${AGY_MODEL}（可用 AGY_MODEL 環境變數覆寫）" >&2
AGY_START=$SECONDS
if OUTPUT=$(agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL" --add-dir "$REPO_ROOT" --sandbox \
    --print-timeout "${AGY_PRINT_TIMEOUT_SECS}s" --log-file "$AGY_LOG_FILE" 2>"$AGY_STDERR_FILE"); then
    AGY_EXIT=0
else
    AGY_EXIT=$?
fi
AGY_ELAPSED=$((SECONDS - AGY_START))
AGY_STDERR_SNAPSHOT=$(cat "$AGY_STDERR_FILE")
replay_agy_stderr

report_quota_if_any() {
    if grep -q 'RESOURCE_EXHAUSTED' "$AGY_LOG_FILE"; then
        # [INFO] 而非 [FAIL]：log 裡的 429 都是重試行，其中退避後成功的那種也會命中；主因的
        # [FAIL] 由各分支自己印（理由見 consult.sh 同段）。
        echo "[INFO] agy log 另有 429 RESOURCE_EXHAUSTED 重試紀錄（可能與本次失敗無關），最後一筆：" >&2
        grep 'RESOURCE_EXHAUSTED' "$AGY_LOG_FILE" | tail -n 1 >&2
        echo "       'Individual quota reached' 是帳號額度用完（訊息內含重置時間），重試無效，請把 agy 切換到另一個登入帳號（例如 GCP 帳號）或等重置；'try again later' 是暫時性容量不足，減少同時執行的 agy 後重試。" >&2
    fi
}

if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy 執行失敗（exit ${AGY_EXIT}）" >&2
    report_quota_if_any
    echo "       agy log：${AGY_LOG_FILE}" >&2
    exit "$AGY_EXIT"
fi
AGY_TIMEOUT_REASON=""
case "$AGY_STDERR_SNAPSHOT" in
    *"print timeout after"*) AGY_TIMEOUT_REASON="agy 印出 print timeout 標記" ;;
esac
if [ -z "$AGY_TIMEOUT_REASON" ] && [ "$AGY_ELAPSED" -gt "$AGY_PRINT_TIMEOUT_SECS" ]; then
    AGY_TIMEOUT_REASON="實際耗時超過預算（agy 未印出標記，故為疑似 timeout）"
fi
if [ -n "$AGY_TIMEOUT_REASON" ]; then
    # mktemp（0600）而非衍生檔名：後者權限隨 umask，022 下會是 0644，同機其他使用者可讀到
    # 這段可能含整份 diff 的輸出（理由與實測見 consult.sh 同段）。
    AGY_DISCARDED_FILE=$(mktemp "${TMPDIR:-/tmp}/agy-review-discarded.XXXXXX")
    printf '%s\n' "$OUTPUT" > "$AGY_DISCARDED_FILE"
    echo "[FAIL] agy 在 ${AGY_PRINT_TIMEOUT_SECS} 秒內沒有完成（實際 ${AGY_ELAPSED} 秒）：${AGY_TIMEOUT_REASON}。agy 此時仍 exit 0，其輸出可能只是半截 review，已不呈現。" >&2
    report_quota_if_any
    echo "       常見原因：diff 太大讓 agy 大量探索周邊檔案，或 API 額度不足（見上方）。可用 AGY_PRINT_TIMEOUT_SECS 調整，範圍 1-${AGY_PRINT_TIMEOUT_MAX}（再高會被 Claude Code Bash tool 先砍掉）。" >&2
    echo "       agy log：${AGY_LOG_FILE}；被丟棄的輸出：${AGY_DISCARDED_FILE}" >&2
    exit 124
fi
if [ -z "$OUTPUT" ] || [ "${#OUTPUT}" -lt 20 ]; then
    echo "[FAIL] agy 回傳空白或極短輸出（${#OUTPUT} 字元）。常見原因：--sandbox 底下 agy 想探索周邊檔案時被自己的權限系統擋下（見 ~/.gemini/antigravity-cli/settings.json permissions.allow），headless 模式無法跳出確認框。" >&2
    report_quota_if_any
    echo "       agy log：${AGY_LOG_FILE}" >&2
    exit 1
fi
# 成功路徑也印出 log 路徑：`--log-file` 改道後預設目錄沒有副本，這是「agy 沒讀到 diff 卻給出
# 看似正常的 review」這個殘餘風險唯一的追查入口。log 不刪；stderr 暫存檔由 trap 清掉。
echo "[INFO] agy log：${AGY_LOG_FILE}（review 若看起來沒讀到 diff，查此檔）" >&2
printf '%s\n' "$OUTPUT"
