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

# SKILL_REPO：從本腳本自身位置解析，不依賴 ~/.agents/config.json 的 skill_repo。
# 該 key 是多 repo 共寫的單一值，會被最後一個 make install 覆寫指向錯 repo；
# 只驗目錄存在（[ -d ]）的舊 gate 會讓錯 repo 靜默通過（見 rule 11 / 18）。
# 本腳本實體住在 yibi-stack，用 git rev-parse 從腳本所在目錄推導 repo 根最可靠；
# pwd -P 解析 symlink（skill 常以 symlink 掛到 ~/.claude/skills）。
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
if ! SKILL_REPO=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null); then
  echo "[FAIL] 無法從腳本位置解析 SKILL_REPO（非 git repo？）: $SCRIPT_DIR" >&2
  exit 1
fi
# 驗 resolved 目標確實含 pr-retrospective 依賴的 tasks/mycelium，而非只驗目錄存在
if [ ! -d "$SKILL_REPO/tasks/mycelium" ]; then
  echo "[FAIL] resolved SKILL_REPO 不含 tasks/mycelium（指向錯 repo？）: $SKILL_REPO" >&2
  exit 1
fi

REAL_WORKDIR=$(pwd)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

echo "SKILL_REPO=$SKILL_REPO"
echo "ORIG_PROJECT=$ORIG_PROJECT"
echo "REAL_WORKDIR=$REAL_WORKDIR"
echo "BRANCH=$BRANCH"
