#!/usr/bin/env bash
# 為 pr-review-toolkit 的所有 agent 加入 git -C 指令規範。
# 雙層冪等保護：
#   1) STATE_FILE 記錄上次 patch 的識別 ID（gitCommitSha 優先，version fallback；無法取得時不寫入，強制重跑），ID 相符則整批跳過
#   2) 每個 agent 檔案以末尾唯一字串作為已 patch 標記，防止 patch 中途中斷後重複寫入
set -euo pipefail

PLUGIN_KEY="pr-review-toolkit@claude-plugins-official"
INSTALLED_JSON="$HOME/.claude/plugins/installed_plugins.json"
STATE_FILE="$HOME/.claude/plugins/pr-review-toolkit-patched-sha"

# 先排除不需要 jq 的 skip 路徑，再才確認 jq 存在
if [ ! -f "$INSTALLED_JSON" ]; then
  echo "  [SKIP] $INSTALLED_JSON 不存在，跳過"
  exit 0
fi

# jq 相依性檢查（只在確認需要解析 JSON 後才驗證）
if ! command -v jq >/dev/null 2>&1; then
  echo "  [FAIL] jq 未安裝，請執行：brew install jq" >&2
  exit 1
fi

# 確認 JSON 格式有效（分開驗證，避免 parse error 被誤判為「未安裝」）
if ! jq empty "$INSTALLED_JSON" 2>/dev/null; then
  echo "  [FAIL] $INSTALLED_JSON JSON 格式錯誤，請重新安裝 pr-review-toolkit" >&2
  exit 1
fi

# 確認 plugin 已安裝且 entry 不是空陣列
if ! jq -e --arg key "$PLUGIN_KEY" '.plugins[$key] | length > 0' "$INSTALLED_JSON" > /dev/null; then
  echo "  [SKIP] pr-review-toolkit 未安裝"
  exit 0
fi

# 取得目前 SHA 與安裝路徑（取 [0]，每個 plugin key 通常只有一筆安裝記錄）
# 用 // empty 讓 null 值輸出空字串，而非字面 "null"
CURRENT_ID=$(jq -r --arg key "$PLUGIN_KEY" '.plugins[$key][0].gitCommitSha // empty' "$INSTALLED_JSON")
INSTALL_PATH=$(jq -r --arg key "$PLUGIN_KEY" '.plugins[$key][0].installPath // empty' "$INSTALLED_JSON")

if [ -z "$CURRENT_ID" ]; then
  echo "  [WARN] installed_plugins.json 缺少 gitCommitSha 欄位，使用 version 作為 patch 追蹤 ID" >&2
  CURRENT_ID=$(jq -r --arg key "$PLUGIN_KEY" '.plugins[$key][0].version // ""' "$INSTALLED_JSON")
fi
if [ -z "$INSTALL_PATH" ]; then
  echo "  [FAIL] installed_plugins.json 缺少 installPath 欄位，請重新安裝 pr-review-toolkit" >&2
  exit 1
fi

# 確認 installPath 在預期位置（防止 JSON 被竄改或路徑異常）
case "$INSTALL_PATH" in
  "$HOME/.claude/plugins/"*) ;;
  *) echo "  [SKIP] installPath 不在預期位置：$INSTALL_PATH" >&2; exit 0 ;;
esac

AGENTS_DIR="$INSTALL_PATH/agents"

if [ ! -d "$AGENTS_DIR" ]; then
  echo "  [SKIP] agents 目錄不存在：$AGENTS_DIR"
  exit 0
fi

# 若 plugin 版本未更新（SHA 不變），進一步確認至少一個 agent 已有 patch marker
# 避免 same-SHA reinstall（plugin 刪除重裝但 STATE_FILE 殘留）靜默跳過
LAST_ID=$(cat "$STATE_FILE" 2>/dev/null || echo "")
if [ "$CURRENT_ID" = "$LAST_ID" ]; then
  # 確認每個 agent 都有 patch marker（「至少一個」不足以判斷整批完成）
  _all_patched=1
  shopt -s nullglob
  for _chk in "$AGENTS_DIR"/*.md; do
    grep -q "Apply this rule to ALL git subcommands" "$_chk" || { _all_patched=0; break; }
  done
  if [ "$_all_patched" = "1" ]; then
    echo "  [OK] pr-review-toolkit agents 已是最新 patch（ID: ${CURRENT_ID:0:12}）"
    exit 0
  fi
  echo "  [WARN] ID 相符但有 agent 未 patch，重新 patch..."
fi

echo "  Patching pr-review-toolkit agents (ID: ${CURRENT_ID:0:12})..."

PATCHED=0
shopt -s nullglob
for agent_file in "$AGENTS_DIR"/*.md; do
  agent_name="${agent_file##*/}"

  # 單檔保護：用末尾唯一字串確認 patch 完整（heading 存在但 content 截斷時也能偵測）
  # SHA 比對只能整批跳過，此處防止中途中斷後重跑時重複 append
  if grep -q "Apply this rule to ALL git subcommands" "$agent_file"; then
    echo "    -> $agent_name (already patched)"
    continue
  fi

  cat >> "$agent_file" <<'PATCH_EOF'

## Bash Command Rules

When running git commands in a directory other than the current working directory, always use `git -C <path>` instead of `cd <path> && git`. The `cd && git` pattern triggers a security warning and will be blocked.

```bash
# WRONG - triggers security warning
cd /path/to/repo && git diff main...HEAD -- file.py

# CORRECT - use git -C
git -C /path/to/repo diff main...HEAD -- file.py
git -C /path/to/repo log --oneline -10
git -C /path/to/repo show HEAD:file.py
git -C /path/to/repo status
```

Apply this rule to ALL git subcommands: diff, log, show, status, branch, rev-parse, worktree, etc.
PATCH_EOF

  echo "    -> $agent_name (patched)"
  PATCHED=$((PATCHED + 1))
done

# 無 .md 檔案時警告（plugin 目錄結構可能已變動）
if [ "$PATCHED" -eq 0 ]; then
  total=$(find "$AGENTS_DIR" -maxdepth 1 -name "*.md" | wc -l | tr -d ' ')
  if [ "$total" -eq 0 ]; then
    echo "  [WARN] $AGENTS_DIR 下無 .md 檔案，請確認 plugin 結構是否改變" >&2
  fi
fi

# STATE_FILE 在全部 patch 完成後才寫入，確保中途中斷時下次能重試
# CURRENT_ID 為空時不寫入（無可追蹤 ID），下次執行走 all_patched check 判斷
mkdir -p "$(dirname "$STATE_FILE")"
if [ -n "$CURRENT_ID" ]; then
  if ! echo "$CURRENT_ID" > "$STATE_FILE"; then
    echo "  [WARN] 識別 ID 無法寫入 state file：$STATE_FILE（patch 已套用，但下次仍會重跑）" >&2
  fi
  echo "  [OK] $PATCHED agent(s) patched，識別 ID：${CURRENT_ID:0:12}"
else
  echo "  [OK] $PATCHED agent(s) patched（未找到可追蹤識別 ID，下次仍會重跑）"
fi
