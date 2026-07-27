#!/usr/bin/env bash
# protect-push 安裝：複製 hook 腳本 + 合併 settings.json + 驗證，一次完成。
# 用法：install-hook.sh [target-repo-root]
#   未帶參數時以 cwd 所在的 git repo 為目標。
# stdout: [OK]/[DONE] 進度訊息；stderr: [WARN]/[FAIL] 診斷訊息
# exit 1: 任一步驟失敗
#
# 冪等：重複執行時 merge-settings.py 會偵測既有 hook 並跳過（[WARN] 已存在）。

set -euo pipefail

# 以 script 自身位置定位 skill 目錄（installed copy 與 in-repo 皆可用；
# realpath 在 macOS < Ventura 不存在，用 cd+pwd 可攜寫法）
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SKILL_DIR=$(dirname "$SCRIPT_DIR")

if [ "$#" -ge 1 ]; then
  if [ ! -d "$1" ]; then
    echo "[FAIL] 目標路徑不存在或非目錄：$1" >&2
    exit 1
  fi
  if ! REPO_ROOT=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null); then
    echo "[FAIL] 目標路徑不是 git repo：$1" >&2
    exit 1
  fi
else
  if ! REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "[FAIL] 不在 git repo 內 -- 請在目標專案根目錄執行，或帶目標路徑參數" >&2
    exit 1
  fi
fi

for f in protect-push.sh parse_git_dir.py; do
  if [ ! -f "$SKILL_DIR/$f" ]; then
    echo "[FAIL] $SKILL_DIR/$f 不存在 -- 請先在 yibi-stack 執行 make install-one SKILL=protect-push" >&2
    exit 1
  fi
done

# 目標已有不同內容的 hook 時警告（可能是該 repo 的客製版，例如 yibi-stack 自帶
# 的加強版 protect-push.sh），提醒使用者 git diff 檢查後再決定是否保留覆蓋結果
HOOK_TARGET="$REPO_ROOT/.claude/hooks/protect-push.sh"
if [ -f "$HOOK_TARGET" ] && ! cmp -s "$SKILL_DIR/protect-push.sh" "$HOOK_TARGET"; then
  echo "[WARN] 目標已有不同內容的 protect-push.sh，將被 skill 版覆蓋 -- 若該 repo 有客製版請用 git diff 確認" >&2
fi

mkdir -p "$REPO_ROOT/.claude/hooks"
cp "$SKILL_DIR/protect-push.sh" "$HOOK_TARGET"
cp "$SKILL_DIR/parse_git_dir.py" "$REPO_ROOT/.claude/hooks/parse_git_dir.py"
chmod +x "$HOOK_TARGET"
echo "[OK] hook 腳本已安裝：.claude/hooks/protect-push.sh"
echo "[OK] 路徑解析器已安裝：.claude/hooks/parse_git_dir.py"

# settings.json 不存在時先建立空骨架，統一走 merge 路徑
# （hook JSON 只定義在 merge-settings.py 一處，避免雙源漂移）
SETTINGS="$REPO_ROOT/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
  printf '{}\n' > "$SETTINGS"
  echo "[OK] settings.json 不存在，已建立空白骨架"
fi

# merge-settings.py / verify-install.py 以 cwd 解析 repo root，
# 用 subshell cd 到目標 repo 執行（不污染本 script 的 cwd）
if ! ( cd "$REPO_ROOT" && python3 "$SCRIPT_DIR/merge-settings.py" ); then
  echo "[FAIL] settings.json 合併失敗（用 python3 -m json.tool $SETTINGS 驗證格式）" >&2
  exit 1
fi

if ! ( cd "$REPO_ROOT" && python3 "$SCRIPT_DIR/verify-install.py" ); then
  echo "[FAIL] 安裝驗證失敗 -- 見上方訊息" >&2
  exit 1
fi

echo "[DONE] 安裝完成！下次 Claude 在此專案執行 git push 時將自動檢查 branch tracking。"
