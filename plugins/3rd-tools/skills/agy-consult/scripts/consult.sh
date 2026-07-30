#!/usr/bin/env bash
# agy standalone consult runner -- no diff, just a technical question against the repo
# Usage: consult.sh <question-file>
#
# 吃「問題檔案路徑」而不是問題本文（PR #367 mob review Critical）：SKILL.md 呼叫這支 script
# 時是把整段指令當 bash 字串交給真正的 shell 執行；問題本文若直接 inline 進雙引號，
# 雙引號不會擋 $()/backtick/$VAR 展開，問題內容裡的 shell 語法會在 consult.sh 啟動前就被
# 外層 shell 執行（同一個 repo 的 codex-consult 早就靠「先寫檔、只傳檔案路徑」解過同個問題）。
# 檔案路徑是 Claude 自己產生的字串，不是使用者可控的任意文字，才能安全 inline 進 bash 指令。
set -euo pipefail

QUESTION_FILE="${1:-}"

if [ -z "$QUESTION_FILE" ] || [ ! -f "$QUESTION_FILE" ]; then
    echo "[FAIL] QUESTION_FILE missing or not found: $QUESTION_FILE. Pass the path to a file containing the question as the first argument." >&2
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
OUTPUT=$(agy -p "$PROMPT_CONTENT" --add-dir . --sandbox)
AGY_EXIT=$?
if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy 執行失敗（exit $AGY_EXIT）" >&2
    exit "$AGY_EXIT"
fi
if [ -z "$OUTPUT" ] || [ "${#OUTPUT}" -lt 20 ]; then
    echo "[FAIL] agy 回傳空白或極短輸出（${#OUTPUT} 字元）。常見原因：--sandbox 底下 agy 想探索周邊檔案時被自己的權限系統擋下（見 ~/.gemini/antigravity-cli/settings.json permissions.allow），headless 模式無法跳出確認框。請簡化問題避免需要額外讀檔，或改用 /agy-review（若有 diff 可看）。" >&2
    exit 1
fi
printf '%s\n' "$OUTPUT"
