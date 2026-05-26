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

REPO_ROOT=$(git rev-parse --show-toplevel)
TMP="$REPO_ROOT/.agy-review-tmp.md"

# Get diff; fallback to HEAD~1 when no upstream tracking
DIFF=$(git diff "origin/${BASE}...HEAD" 2>/dev/null || git diff HEAD~1 2>/dev/null || echo "(diff not available)")

if [ "$MODE" = "challenge" ]; then
  HEADER="你是資深 security 與 correctness 審查員，以對抗模式審查以下 PR diff。只找問題，不給讚美。尋找：bug、race condition、安全漏洞、邊界條件錯誤、效能陷阱。每個問題標記 [P0]（production 致命）或 [P1]（嚴重）。找不到問題時輸出 [PASS] No critical issues found。"
else
  HEADER="你是資深程式碼審查員，審查以下 PR diff。評估：正確性、安全性、可讀性、邊界條件。嚴重問題標記 [P0]（production 致命）或 [P1]（嚴重）。結尾必須輸出 [PASS]（無 P0/P1 問題）或 [FAIL]（有 P0/P1 問題），後接一行中文 summary。"
fi

{
  printf '%s\n\n' "$HEADER"
  if [ -n "$INSTRUCTION" ]; then
    printf '特別關注：%s\n\n' "$INSTRUCTION"
  fi
  printf 'Base branch: %s\n\n' "$BASE"
  printf '```diff\n%s\n```\n' "$DIFF"
} > "$TMP"

trap 'rm -f "$TMP"' EXIT

cd "$REPO_ROOT"
agy -p "@.agy-review-tmp.md" --add-dir . --sandbox
