#!/usr/bin/env bash
# pr-retrospective/scripts/bootstrap.sh
# 環境檢查 + 專案偵測 + SKILL_REPO 解析 + 工作目錄/branch 蒐集
# stdout: KEY=VALUE 一行一對，供 agent 解析
# stderr: [FAIL]/[WARN] 診斷訊息
# exit 1: 環境條件不足

set -euo pipefail

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

CONFIG="$HOME/.agents/config.json"
if [ ! -f "$CONFIG" ]; then
  echo '[FAIL] ~/.agents/config.json not found' >&2
  exit 1
fi
if ! SKILL_REPO=$(jq -r '.skill_repos["yibi-stack"] // .skill_repo' "$CONFIG"); then
  echo '[FAIL] ~/.agents/config.json is not valid JSON — run: jq . ~/.agents/config.json' >&2
  exit 1
fi
if [ "$SKILL_REPO" = "null" ] || [ -z "$SKILL_REPO" ]; then
  echo '[FAIL] skill_repo not configured in ~/.agents/config.json' >&2
  exit 1
fi
if [ ! -d "$SKILL_REPO" ]; then
  echo "[FAIL] skill_repo path not found: $SKILL_REPO" >&2
  exit 1
fi

REAL_WORKDIR=$(pwd)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

echo "SKILL_REPO=$SKILL_REPO"
echo "ORIG_PROJECT=$ORIG_PROJECT"
echo "REAL_WORKDIR=$REAL_WORKDIR"
echo "BRANCH=$BRANCH"
