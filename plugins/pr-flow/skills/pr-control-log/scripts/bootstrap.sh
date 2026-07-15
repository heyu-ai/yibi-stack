#!/usr/bin/env bash
# pr-control-log/scripts/bootstrap.sh
# 環境檢查 + 專案偵測 + SKILL_REPO 解析 + 工作目錄/branch 蒐集
# stdout: KEY=VALUE 一行一對，供 agent 解析
# stderr: [FAIL]/[WARN] 診斷訊息
# exit 1: 環境條件不足

set -euo pipefail

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
# 只驗目錄存在（[ -d ]）的舊 gate 會讓錯 repo 靜默通過（見 rule 11、PR #215）。
#
# 語意（刻意設計）：SKILL_REPO = 「這份腳本副本所屬的 checkout」，程式碼隨腳本走，
# 腳本與其呼叫的 tasks/mycelium 版本必然一致。實務上經 make install 的
# ~/.claude/skills symlink 執行，pwd -P 穿透 symlink 解析到該 checkout。純 plugin
# 安裝（~/.claude/plugins/cache/...）是非 git 的解壓目錄且不含 tasks/，本腳本會在此
# fail-loud（符合預期：無 checkout 就無法跑 mycelium）。mycelium DB 位於 ~/.agents
# （見 tasks/mycelium/config.py 的 HANDOVER_DB_PATH），與 checkout 無關，故不同
# checkout 不會分岔資料。
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# 成功路徑丟掉 stderr：git 成功時仍可能輸出 warning（如讀不到 ~/.gitconfig），
# 用 2>&1 取值會把 warning 併進 SKILL_REPO，導致後續 tasks/mycelium 檢查誤報。
# 只在失敗分支才第二次呼叫抓 stderr 當診斷（2>&1 >/dev/null 順序不可調換）。
if ! SKILL_REPO=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null); then
  GIT_ERR=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>&1 >/dev/null || true)
  echo "[FAIL] 無法從腳本位置解析 SKILL_REPO: $SCRIPT_DIR" >&2
  echo "[FAIL] git: $GIT_ERR" >&2
  exit 1
fi
# 驗 resolved 目標確實含 pr-control-log 依賴的 tasks/mycelium，而非只驗目錄存在
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
