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
#
# 語意（刻意設計）：SKILL_REPO = 「這份腳本副本所屬的 checkout」，程式碼隨腳本走。
# 好處是腳本與其呼叫的 tasks/mycelium 版本必然一致（不會新腳本配舊模組）。
# 經 plugin 安裝執行時會解析到該 plugin clone；經 ~/.claude/skills symlink 執行時
# pwd -P 會穿透 symlink 解析到 dev checkout——兩者皆為預期。mycelium DB 位於
# ~/.agents（見 tasks/mycelium/config.py 的 HANDOVER_DB_PATH），與 checkout 無關，
# 故不同 checkout 不會分岔 retro 資料。
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
if ! GIT_ERR=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>&1 >/dev/null); then
  # 保留 git 原始錯誤：非 git repo 只是其一，dubious ownership / 權限問題訊息不同
  echo "[FAIL] 無法從腳本位置解析 SKILL_REPO: $SCRIPT_DIR" >&2
  echo "[FAIL] git: $GIT_ERR" >&2
  exit 1
fi
SKILL_REPO=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)
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
