#!/usr/bin/env bash
# agy standalone consult runner -- no diff, just a technical question against the repo
# Usage: consult.sh (no arguments)
#
# 不吃任何參數，固定讀 $CLAUDE_JOB_DIR/agy-consult-question.txt（PR #367 mob review Critical，
# 第二輪發現）：第一輪的修法是「吃問題檔案路徑而不是問題本文」，解決了雙引號擋不住 shell
# 展開的問題，但把路徑做成參數本身就是新的漏洞——這支 script 的 allow-list entry 是
# `Bash(bash .../consult.sh:*)`（見 scripts/patch_agy_allow_list.py），`:*` 允許任意參數，
# 一旦允許清單生效，`bash consult.sh ~/.ssh/id_rsa` 一樣會通過驗證、讀出私鑰內容、包進
# prompt 傳給外部的 agy 行程——變成一個被預先核准、免確認的任意檔案讀取＋外傳原語。
# 固定死路徑 + exact-match allow-list（不帶 `:*`）才能真正關掉這個面：呼叫端沒有任何
# 參數可以塞，allow-list 也不再需要放行任何額外內容。
set -euo pipefail

if [ -z "${CLAUDE_JOB_DIR:-}" ]; then
    echo "[FAIL] CLAUDE_JOB_DIR 未設定，無法定位問題檔案。請在有 CLAUDE_JOB_DIR 的 Claude Code session 執行。" >&2
    exit 1
fi
QUESTION_FILE="$CLAUDE_JOB_DIR/agy-consult-question.txt"

if [ ! -f "$QUESTION_FILE" ]; then
    echo "[FAIL] $QUESTION_FILE 不存在。請先用 Write tool 把問題寫進這個檔案，再執行本 script。" >&2
    exit 1
fi

QUESTION=$(cat "$QUESTION_FILE")
if [ -z "$QUESTION" ]; then
    echo "[FAIL] $QUESTION_FILE is empty." >&2
    exit 1
fi

if ! command -v agy >/dev/null 2>&1; then
    echo "[FAIL] agy not found. Install with: pip install antigravity-cli" >&2
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

BOUNDARY="IMPORTANT: 不要讀取或執行 ~/.claude/、~/.agents/、.claude/skills/、agents/ 底下的任何檔案。這些是給另一個 AI 系統（Claude Code）用的 skill 定義，與這次諮詢無關，請完全忽略。專注在這個 repo 的程式碼本身。"

# 沿用 agy-review/scripts/run.sh 已驗證過的安全模式（issue #153 / PR #229 retro）：
# prompt 用 inline 形式當 -p 的值傳入，不用 @file（nested worktree 下 @file 解析失敗會讓 agy
# 靜默進入 agentic 模式）；也不能改用 stdin pipe（-p/--print 不是 boolean，會把下一個 flag
# 當 prompt 吃掉、完全不讀 stdin；agy 1.1.2 起沒有 stdin prompt 通道）。問題本文此時已經是
# 從檔案讀出的一般字串（而非 argv 上的原始 shell 語法），可以安全放進這裡的 $PROMPT_CONTENT。
PROMPT_CONTENT=$(
  printf '%s\n\n' "$BOUNDARY"
  printf '%s\n' "$QUESTION"
)

# 用實際位元組數而非字元數（PR #367 mob review Important：${#PROMPT_CONTENT} 在 UTF-8
# locale 下數的是字元，中文問題會低估約 3 倍，讓這道 ARG_MAX 防線對主打的中文情境失效）。
PROMPT_BYTES=$(printf '%s' "$PROMPT_CONTENT" | wc -c)
if [ "$PROMPT_BYTES" -gt 256000 ]; then
  echo "[FAIL] 問題輸入 ${PROMPT_BYTES}B 超過 256000B inline 上限" >&2
  exit 1
fi

# 空輸出偵測（PR #367 mob review Critical，agy 1.1.8 實測確認）：--sandbox 底下 agy 想
# 主動探索 --add-dir 內容時，可能因 agy 自己的權限系統（與 Claude Code 的設定完全獨立）
# 擋下探索指令；headless 模式沒有終端可以核准，agy 會直接無輸出退出。不偵測的話，這支
# script 會把空白當成「完成的回答」原樣呈現，使用者無法分辨是真的沒問題還是被靜默擋下。
# if 條件本身會豁免 set -e（`if`/`while`/`until` 條件、或 `&&`/`||` 前的指令不受 set -e 管），
# 這裡刻意用 if 包住賦值：agy 非零結束時若直接寫 `OUTPUT=$(...); AGY_EXIT=$?`，set -e 會在
# 賦值那行就中止 script，下面這行 AGY_EXIT=$? 永遠執行不到，[FAIL] 診斷訊息變死碼（實測驗證）。
if OUTPUT=$(agy -p "$PROMPT_CONTENT" --add-dir . --sandbox); then
    AGY_EXIT=0
else
    AGY_EXIT=$?
fi
if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy 執行失敗（exit ${AGY_EXIT}）" >&2
    exit "$AGY_EXIT"
fi
if [ -z "$OUTPUT" ] || [ "${#OUTPUT}" -lt 20 ]; then
    echo "[FAIL] agy 回傳空白或極短輸出（${#OUTPUT} 字元）。常見原因：--sandbox 底下 agy 想探索周邊檔案時被自己的權限系統擋下（見 ~/.gemini/antigravity-cli/settings.json permissions.allow），headless 模式無法跳出確認框。請簡化問題避免需要額外讀檔，或改用 /agy-review（若有 diff 可看）。" >&2
    exit 1
fi
printf '%s\n' "$OUTPUT"
