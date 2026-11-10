#!/usr/bin/env bash
# pr-retrospective/scripts/bootstrap.sh
# 環境檢查 + 專案偵測 + 工作目錄/branch 蒐集
# stdout: KEY=VALUE 一行一對，供 agent 解析
# stderr: [FAIL]/[WARN] 診斷訊息
# exit 1: 環境條件不足
# exit 2: 參數錯誤；--pr <n> [--repo owner/name]，--repo 優先於 GH_REPO

set -euo pipefail

PR_NUMBER=""
TARGET_REPO="${GH_REPO:-}"
EXPLICIT_REPO=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pr|--repo)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        echo "[FAIL] $1 缺少值" >&2
        exit 2
      fi
      if [ "$1" = "--pr" ]; then
        PR_NUMBER="$2"
      else
        TARGET_REPO="$2"
        EXPLICIT_REPO=true
      fi
      shift 2
      ;;
    *) echo "[FAIL] 未知參數：$1" >&2; exit 2 ;;
  esac
done
if [ "$EXPLICIT_REPO" = true ] && [ -z "$PR_NUMBER" ]; then
  echo '[FAIL] 顯式 --repo 必須同時提供 --pr <n>；不以 cwd branch 猜跨 repo PR' >&2
  exit 2
fi
if [ -n "$PR_NUMBER" ] && ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
  echo '[FAIL] --pr 必須是正整數' >&2
  exit 2
fi
if [ -n "$TARGET_REPO" ] && ! [[ "$TARGET_REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo '[FAIL] --repo／GH_REPO 必須是 owner/name' >&2
  exit 2
fi

if ! command -v mycelium >/dev/null 2>&1; then
  echo '[FAIL] 缺少 mycelium，請執行：uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.23.2"' >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo '[FAIL] jq not installed' >&2
  exit 1
fi
if ! command -v gh >/dev/null 2>&1; then
  echo '[FAIL] gh not installed' >&2
  exit 1
fi

_gcd=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
if [ -z "$_gcd" ]; then
  ORIG_PROJECT=$(basename "$PWD")
elif [ "${_gcd:0:1}" = "/" ]; then
  _dir=$(dirname "$_gcd")
  ORIG_PROJECT=$(basename "$_dir")
else
  _top=$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")
  ORIG_PROJECT=$(basename "$_top")
fi
unset _gcd _dir _top

REAL_WORKDIR=$(pwd)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# GH_REPO alone may use gh's native unambiguous branch detection. Never treat
# repo lookup alone as evidence that a PR exists in that target repository.
if [ -z "$PR_NUMBER" ] && [ -n "$TARGET_REPO" ]; then
  SCRIPT_DIR=$(dirname "${BASH_SOURCE[0]}")
  if ! DETECTED_PR=$(bash "$SCRIPT_DIR/detect-pr.sh"); then
    echo '[FAIL] GH_REPO 的 branch PR 偵測失敗或有歧義；請明確提供 --pr <n>' >&2
    exit 1
  fi
  PR_NUMBER="${DETECTED_PR#PR_NUMBER=}"
  if ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
    echo '[FAIL] 無效的 branch PR identity；請明確提供 --pr <n>' >&2
    exit 1
  fi
fi
if [ -n "$PR_NUMBER" ] || [ -n "$TARGET_REPO" ]; then
  CWD_REPO=""
  if ! CWD_REPO=$(GH_REPO= gh repo view --json nameWithOwner -q .nameWithOwner); then
    CWD_REPO=""
    echo '[WARN] 無法確認 cwd 所屬 repo；寫入前必須確認目標專案' >&2
  fi
  if [ -n "$PR_NUMBER" ]; then
    REPO_ARGS=()
    if [ -n "$TARGET_REPO" ]; then REPO_ARGS=(--repo "$TARGET_REPO"); fi
    if ! PR_URL=$(gh pr view "$PR_NUMBER" ${REPO_ARGS[@]+"${REPO_ARGS[@]}"} --json url -q .url); then
      echo '[FAIL] 無法確認 PR 所屬 repo；停止，不使用 cwd 猜測專案' >&2
      exit 1
    fi
    if ! [[ "$PR_URL" =~ ^https://github.com/([^/]+)/([^/]+)/pull/([1-9][0-9]*)$ ]] ||
       [ "${BASH_REMATCH[3]}" != "$PR_NUMBER" ]; then
      echo '[FAIL] PR URL 或編號不符，無法確認目標專案' >&2
      exit 1
    fi
    TARGET_REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
  fi
  ORIG_PROJECT="${TARGET_REPO##*/}"
  CONFIRM_PROJECT=false
  if [ "$CWD_REPO" != "$TARGET_REPO" ]; then
    CONFIRM_PROJECT=true
    echo "[WARN] cwd repo=${CWD_REPO:-unknown}；PR／目標 repo=${TARGET_REPO}；寫入前請使用者確認 project=${ORIG_PROJECT}" >&2
  fi
  echo "PR_REPO=$TARGET_REPO"
  echo "PROJECT_CONFIRMATION_REQUIRED=$CONFIRM_PROJECT"
fi

echo "ORIG_PROJECT=$ORIG_PROJECT"
echo "REAL_WORKDIR=$REAL_WORKDIR"
echo "BRANCH=$BRANCH"
