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

# Gemini 模型在台灣地區被 Google API 的 pre-invocation context summarization 擋下
# （FAILED_PRECONDITION 400: User location is not supported for the API use），
# 即使 agy auth 成功也無法使用。Claude 模型走不同的 API 路徑，不受地區限制。
# 允許透過 AGY_MODEL 環境變數覆寫（如 Google 日後開放台灣或使用者有 VPN）。
AGY_MODEL="${AGY_MODEL:-claude-sonnet-4-6}"

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
#   (3) 不落地暫存檔，免去並行 review 互相覆寫與 SIGKILL 繞過 EXIT trap 殘留 untracked 檔。
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
echo "[INFO] agy 模型：${AGY_MODEL}（可用 AGY_MODEL 環境變數覆寫）" >&2
if OUTPUT=$(agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL" --add-dir "$REPO_ROOT" --sandbox); then
    AGY_EXIT=0
else
    AGY_EXIT=$?
fi
if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy 執行失敗（exit ${AGY_EXIT}）" >&2
    exit "$AGY_EXIT"
fi
if [ -z "$OUTPUT" ] || [ "${#OUTPUT}" -lt 20 ]; then
    echo "[FAIL] agy 回傳空白或極短輸出（${#OUTPUT} 字元）。常見原因：--sandbox 底下 agy 想探索周邊檔案時被自己的權限系統擋下（見 ~/.gemini/antigravity-cli/settings.json permissions.allow），headless 模式無法跳出確認框。" >&2
    exit 1
fi
printf '%s\n' "$OUTPUT"
