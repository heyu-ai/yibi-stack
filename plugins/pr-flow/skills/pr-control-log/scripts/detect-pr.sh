#!/usr/bin/env bash
# pr-control-log/scripts/detect-pr.sh
# 從傳入引數或 gh pr view 偵測 PR 號
# 用法：detect-pr.sh [--pr <n>]
# stdout: PR_NUMBER=<n>
# stderr: [FAIL] 說明
# exit 1: 找不到 PR 號

set -euo pipefail

RAW_ARGS="$*"

PR_NUMBER=""
if echo "$RAW_ARGS" | grep -qE -- '--pr [0-9]+'; then
  PR_NUMBER=$(echo "$RAW_ARGS" | grep -oE -- '--pr [0-9]+' | grep -oE '[0-9]+')
fi

if [ -z "$PR_NUMBER" ]; then
  PR_NUMBER=$(gh pr view --json number -q .number 2>/dev/null || echo "")
fi

if [ -z "$PR_NUMBER" ] || [ "$PR_NUMBER" = "null" ]; then
  echo '[FAIL] no PR detected; pass --pr <n> if not on a PR branch' >&2
  exit 1
fi

echo "PR_NUMBER=$PR_NUMBER"
