#!/usr/bin/env bash
# agy standalone consult runner -- no diff, just a technical question against the repo
# Usage: consult.sh <question>
set -euo pipefail

QUESTION="${1:-}"

if [ -z "$QUESTION" ]; then
    echo "[FAIL] QUESTION is empty. Pass the question as the first argument." >&2
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
# 當 prompt 吃掉、完全不讀 stdin；agy 1.1.2 起沒有 stdin prompt 通道）。
PROMPT_CONTENT=$(
  printf '%s\n\n' "$BOUNDARY"
  printf '%s\n' "$QUESTION"
)

PROMPT_BYTES=${#PROMPT_CONTENT}
if [ "$PROMPT_BYTES" -gt 256000 ]; then
  echo "[FAIL] 問題輸入 ${PROMPT_BYTES}B 超過 256000B inline 上限" >&2
  exit 1
fi

agy -p "$PROMPT_CONTENT" --add-dir . --sandbox
