#!/usr/bin/env bash
# init-commit-hook.sh — 安裝 commit-msg hook 到目標專案
# 複製 hook script 和 parse script 到目標專案

set -euo pipefail

# cd 取自己所在目錄前先清 CDPATH，否則 $(cd ... && pwd) 可能多印一行（rule 17）
export CDPATH=

# 預設以本腳本自己的位置推出 skill 目錄（scripts/ 的上一層），不依賴任何安裝位置：
# 這支腳本由 plugin 提供，plugin 使用者的機器上沒有 ~/.agents/skills/bump-version。
# 本檔是一般檔案而非 symlink，用 dirname + cd -P + pwd 即可（rule 17 Self-Location）。
if ! SCRIPT_DIR=$(cd -P -- "$(dirname "${BASH_SOURCE[0]}")" && pwd); then
  echo "[FAIL] 無法解析腳本所在目錄：${BASH_SOURCE[0]}" >&2
  exit 1
fi
SKILL_DIR_DEFAULT=$(dirname "$SCRIPT_DIR")
SKILL_DIR="${SKILL_DIR:-$SKILL_DIR_DEFAULT}"
HOOK_SRC="$SKILL_DIR/scripts/commit-msg-hook.sh"
PARSE_SRC="$SKILL_DIR/scripts/commit-msg-parse.py"
CONFIG_TEMPLATE="$SKILL_DIR/assets/commit-convention.yaml.tpl"

# ---------- 確認環境 ----------

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "[FAIL] 不在 git repo 中" >&2; exit 1
}

if [ ! -f "$HOOK_SRC" ]; then
  echo "[FAIL] hook 腳本不存在：$HOOK_SRC" >&2
  echo "       預設位置是本腳本所在的 skill 目錄；若設了 SKILL_DIR，請確認它指向 bump-version skill 目錄" >&2
  exit 1
fi

if [ ! -f "$PARSE_SRC" ]; then
  echo "[FAIL] parse 腳本不存在：$PARSE_SRC" >&2
  exit 1
fi

# ---------- 決定 hooks 目錄 ----------

CUSTOM_HOOKS=$(git config --get core.hooksPath 2>/dev/null || true)
if [ -n "$CUSTOM_HOOKS" ]; then
  if [[ "$CUSTOM_HOOKS" != /* ]]; then
    CUSTOM_HOOKS="$GIT_ROOT/$CUSTOM_HOOKS"
  fi
  HOOKS_DIR="$CUSTOM_HOOKS"
  echo "[OK] 偵測到 core.hooksPath，使用自訂路徑：$HOOKS_DIR"
else
  HOOKS_DIR="$GIT_ROOT/.git/hooks"
fi

if [ ! -d "$HOOKS_DIR" ]; then
  echo "[FAIL] hooks 目錄不存在：$HOOKS_DIR" >&2
  echo "       若使用 git worktree，請先設定 core.hooksPath 指向共用目錄" >&2
  exit 1
fi

HOOK_DEST="$HOOKS_DIR/commit-msg"

# ---------- 安裝前備份現有 hook ----------

if [ -f "$HOOK_DEST" ]; then
  BACKUP="${HOOK_DEST}.bak.$(date +%Y%m%d%H%M%S)"
  cp "$HOOK_DEST" "$BACKUP"
  echo "[WARN] 已有 commit-msg hook，備份至：$BACKUP"
fi

# ---------- 安裝 hook 和 parse script ----------

cp "$HOOK_SRC" "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "[OK] commit-msg hook 已安裝：$HOOK_DEST"

CLAUDE_HOOKS_DIR="$GIT_ROOT/.claude/hooks"
mkdir -p "$CLAUDE_HOOKS_DIR"
cp "$PARSE_SRC" "$CLAUDE_HOOKS_DIR/commit-msg-parse.py"
echo "[OK] parse script 已安裝：$CLAUDE_HOOKS_DIR/commit-msg-parse.py"

# ---------- 產生設定檔 ----------

CONFIG_DEST="$GIT_ROOT/.claude/commit-convention.yaml"
if [ ! -f "$CONFIG_DEST" ]; then
  if [ -f "$CONFIG_TEMPLATE" ]; then
    mkdir -p "$GIT_ROOT/.claude"
    cp "$CONFIG_TEMPLATE" "$CONFIG_DEST"
    echo "[OK] commit-convention.yaml 已從 template 產生：$CONFIG_DEST"
    echo "     請依專案需求編輯此檔案"
  fi
else
  echo "[OK] commit-convention.yaml 已存在，略過（不覆蓋）"
fi

echo ""
echo "完成！之後每次 git commit 都會自動驗證 commit message 格式。"
