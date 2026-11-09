#!/usr/bin/env bash
# 唯讀 pre-merge gate；不執行 ready、bump、push 或 merge。
# Exit 0: OPEN 且非 draft；1: 參數／工具／API／格式錯誤；
# 2: MERGED/CLOSED；3: draft（須人類決定）；4: DIRTY/CONFLICTING/BEHIND。
set -euo pipefail

fail() { echo "[FAIL] $*" >&2; exit 1; }
if [ "$#" -ne 1 ] || ! [[ "$1" =~ ^[1-9][0-9]*$ ]]; then
    fail 'Usage: bash preflight-pr-merge.sh <pr-number>'
fi
PR_NUMBER="$1"
command -v gh >/dev/null 2>&1 || fail '找不到 gh'
command -v jq >/dev/null 2>&1 || fail '找不到 jq'
if ! PR_JSON=$(gh pr view "$PR_NUMBER" --json number,state,mergeable,mergeStateStatus,isDraft); then
    fail "無法查詢 PR #${PR_NUMBER}；不允許進入 merge 流程"
fi
if ! jq -e --argjson number "$PR_NUMBER" '
    type == "object" and .number == $number
    and (.state == "OPEN" or .state == "CLOSED" or .state == "MERGED")
    and (.isDraft | type == "boolean")
    and (.mergeable | type == "string" and length > 0)
    and (.mergeStateStatus | type == "string" and length > 0)
' <<< "$PR_JSON" >/dev/null; then
    fail 'PR metadata 不完整或格式錯誤'
fi
printf '%s\n' "$PR_JSON"
STATE=$(jq -r '.state' <<< "$PR_JSON")
if [ "$STATE" != OPEN ]; then
    echo "[STOP] PR #${PR_NUMBER} is ${STATE}" >&2
    exit 2
fi
if jq -e '.isDraft' <<< "$PR_JSON" >/dev/null; then
    echo "[STOP] PR #${PR_NUMBER} is draft；請使用者明確同意後才可 gh pr ready，再重跑本 gate" >&2
    exit 3
fi
if jq -e '.mergeable == "CONFLICTING" or .mergeStateStatus == "DIRTY" or .mergeStateStatus == "BEHIND"' <<< "$PR_JSON" >/dev/null; then
    echo "[STOP] PR #${PR_NUMBER} 需要先更新 base／解衝突" >&2
    exit 4
fi
