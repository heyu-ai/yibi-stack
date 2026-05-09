---
name: protect-push
type: tool
scope: global
description: >
  安裝 Claude Code PreToolUse hook，防止 worktree branch 的 git push 直推 origin/main。
  適用於使用 EnterWorktree 或 git worktree add 的所有專案。
  觸發情境：「安裝 push 防護」「設定 worktree hook」「protect push」「新專案初始化」
---

# protect-push

## 概要

此 skill 在目標專案的 `.claude/` 目錄下安裝一個 PreToolUse hook，在每次 Claude 執行 `git push` 前自動檢查 branch tracking。

**解決的問題**：

- `EnterWorktree` 或 `git worktree add` 建立的 branch 預設追蹤 `origin/main`
- 搭配 `push.default=upstream`，任何 `git push` 都會直推 main，繞過 PR 流程
- `@{upstream}` 語法在 zsh 下因 brace expansion 靜默失效，shell 層的安全檢查不可靠

**防護機制**：

- 攔截所有 Bash 中的 `git push` 指令
- 用 `git config branch.X.remote` + `.merge` 查 upstream（不依賴 `@{upstream}` 語法）
- 若追蹤 `origin/main` 或 `origin/master`，阻止並提示修復指令

## 執行步驟

### Step 1: 環境檢查

確認在 git repo 中，且 `.claude/` 目錄存在：

```bash
git rev-parse --show-toplevel
[ -d .claude/ ] && echo "✓ .claude/ 存在" || echo "⚠️  .claude/ 不存在，Step 2 會自動建立"
```

### Step 2: 安裝 hook 腳本

確認 skill 已安裝，並複製 hook 腳本：

```bash
SKILL_DIR="$HOME/.agent/skills/protect-push"
if [ ! -d "$SKILL_DIR" ]; then
    echo "錯誤：protect-push skill 未安裝。請先執行 make install-one SKILL=protect-push"
    exit 1
fi
echo "✓ Skill 目錄：$SKILL_DIR"

mkdir -p .claude/hooks
cp "$SKILL_DIR/protect-push.sh" .claude/hooks/protect-push.sh
cp "$SKILL_DIR/parse_git_dir.py" .claude/hooks/parse_git_dir.py
chmod +x .claude/hooks/protect-push.sh
echo "✓ hook 腳本已安裝：.claude/hooks/protect-push.sh"
echo "✓ 路徑解析器已安裝：.claude/hooks/parse_git_dir.py"
```

### Step 3: 設定 settings.json

**情況 A：settings.json 不存在** — 直接建立：

```bash
cat > .claude/settings.json << 'EOF'
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/protect-push.sh",
            "type": "command",
            "statusMessage": "檢查 git push 安全性..."
          }
        ],
        "matcher": "Bash"
      }
    ]
  }
}
EOF
echo "✓ settings.json 已建立"
```

**情況 B：settings.json 已存在** — 讀取現有內容，用 Python 合併 hook 設定（不覆蓋其他設定）：

```bash
python3 - << 'EOF'
import json, sys
from pathlib import Path

settings_path = Path(".claude/settings.json")
settings = json.loads(settings_path.read_text(encoding="utf-8"))

new_hook = {
    "hooks": [
        {
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/protect-push.sh",
            "type": "command",
            "statusMessage": "檢查 git push 安全性..."
        }
    ],
    "matcher": "Bash"
}

# 取得或初始化 hooks.PreToolUse
hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print("錯誤：settings.json 中 hooks 欄位格式不正確（應為 dict）")
    sys.exit(1)
pre_tool_use = hooks.setdefault("PreToolUse", [])

# 避免重複安裝（比對完整 command 字串）
HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/protect-push.sh'
already_installed = any(
    any(
        h.get("command", "") == HOOK_COMMAND
        for h in entry.get("hooks", [])
    )
    for entry in pre_tool_use
)

if already_installed:
    print("⚠️  protect-push hook 已存在，略過")
    sys.exit(0)

pre_tool_use.append(new_hook)
settings_path.write_text(
    json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8"
)
print("✓ protect-push hook 已合併到 settings.json")
EOF
```

### Step 4: 驗證

確認安裝成功：

```bash
echo "=== 安裝驗證 ==="
[ -x ".claude/hooks/protect-push.sh" ] && echo "✓ hook 腳本：存在且可執行" || echo "✗ hook 腳本：未找到"
[ -f ".claude/hooks/parse_git_dir.py" ] && echo "✓ 路徑解析器：存在" || echo "✗ 路徑解析器：未找到"
python3 -c "
import json
from pathlib import Path
s = json.loads(Path('.claude/settings.json').read_text())
hooks = s.get('hooks', {}).get('PreToolUse', [])
found = any(
    any('protect-push' in h.get('command','') for h in e.get('hooks',[]))
    for e in hooks
)
print('✓ settings.json：hook 設定正確' if found else '✗ settings.json：未找到 hook 設定')
"
echo "========================"
echo "✅ 安裝完成！下次 Claude 在此專案執行 git push 時將自動檢查 branch tracking。"
```

## 常見問題處理

| 問題 | 處理方式 |
|------|----------|
| `protect-push skill 未安裝` | 在 ainization-skill repo 執行 `make install-one SKILL=protect-push` |
| hook 阻止了合法的 push | 先執行 `git branch --unset-upstream && git push -u origin HEAD` 建立獨立 remote branch |
| settings.json 格式損壞 | 用 `python3 -m json.tool .claude/settings.json` 驗證 JSON 格式 |
| 想移除 hook | 從 settings.json 刪除對應的 hook 物件，並刪除 `.claude/hooks/protect-push.sh` |
