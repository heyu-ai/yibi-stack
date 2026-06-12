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

# 直接 pipe prompt 進 agy stdin，取代 @file（nested worktree（.claude/worktrees/<name>/）下
# @file 解析失敗會讓 agy 靜默進入 agentic 探索模式：review 錯 target / brain-artifact / timeout，
# 與 pr-cycle-deep issue #153 同根因）。pipe 一次根治四點：
#   (1) agy 不讀 @file 即無 agentic 觸發點；
#   (2) 內容走 stdin 不佔 ARG_MAX 參數預算，無單一 arg 長度上限；
#   (3) 內容不經 -p 參數解析，開頭即使是 '@' 也不會被誤判成檔案路徑而重觸發本 bug；
#   (4) 不落地暫存檔，免去並行 review 互相覆寫與 SIGKILL 繞過 EXIT trap 殘留 untracked 檔。
# --sandbox 保持不變（standalone 為輕量第二意見，維持較嚴格的 sandbox security posture）。
{
  printf '%s\n\n' "$HEADER"
  if [ -n "$INSTRUCTION" ]; then
    printf '特別關注：%s\n\n' "$INSTRUCTION"
  fi
  printf 'Base branch: %s\n\n' "$BASE"
  printf '```diff\n%s\n```\n' "$DIFF"
} | agy --print --add-dir . --sandbox
