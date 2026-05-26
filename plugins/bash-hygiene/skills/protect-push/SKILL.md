---
name: protect-push
type: tool
scope: global
description: >
  Install a Claude Code PreToolUse hook to prevent direct git push from a worktree branch to
  origin/main. Applies to all projects using EnterWorktree or git worktree add.
  Trigger contexts: "install push protection", "configure worktree hook", "protect push",
  "new project initialization"
---

# protect-push

## Overview

This skill installs a PreToolUse hook in the target project's `.claude/` directory.
The hook automatically checks branch tracking before Claude executes any `git push`.

**Problem Statement**:

- Branches created by `EnterWorktree` or `git worktree add` track `origin/main` by default
- With `push.default=upstream`, any `git push` directly pushes to main, bypassing the PR workflow
- The `@{upstream}` syntax silently fails under zsh due to brace expansion;
  shell-level safety checks are unreliable

**Protection Mechanism**:

- Intercepts all `git push` commands in Bash
- Checks the upstream using `git config branch.X.remote` + `.merge`
  (no dependency on `@{upstream}` syntax)
- Blocks and displays a fix command if tracking points to `origin/main` or `origin/master`

## Execution Steps

### Step 1: Environment Check

Confirm you are in a git repo and `.claude/` exists:

```bash
git rev-parse --show-toplevel
[ -d .claude/ ] && echo "[OK] .claude/ 存在" || echo "[WARN] .claude/ 不存在，Step 2 會自動建立"
```

### Step 2: Install Hook Script

Confirm the skill is installed, then copy the hook script:

```bash
SKILL_DIR="$HOME/.agents/skills/protect-push"
if [ ! -d "$SKILL_DIR" ]; then
    echo "錯誤：protect-push skill 未安裝。請先執行 make install-one SKILL=protect-push"
    exit 1
fi
echo "[OK] Skill 目錄：$SKILL_DIR"

mkdir -p .claude/hooks
cp "$SKILL_DIR/protect-push.sh" .claude/hooks/protect-push.sh || exit 1
cp "$SKILL_DIR/parse_git_dir.py" .claude/hooks/parse_git_dir.py || exit 1
chmod +x .claude/hooks/protect-push.sh
echo "[OK] hook 腳本已安裝：.claude/hooks/protect-push.sh"
echo "[OK] 路徑解析器已安裝：.claude/hooks/parse_git_dir.py"
```

### Step 3: Configure settings.json

**Case A: settings.json does not exist** — create it directly:

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
echo "[OK] settings.json 已建立"
```

**Case B: settings.json already exists** — read existing content and merge the hook config using
Python (does not overwrite other settings):

```bash
if ! python3 - << 'EOF'
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

# initialize hooks.PreToolUse if not present
hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print("錯誤：settings.json 中 hooks 欄位格式不正確（應為 dict）")
    sys.exit(1)
pre_tool_use = hooks.setdefault("PreToolUse", [])

# prevent duplicate install (compare full command string)
HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/protect-push.sh'
already_installed = any(
    any(
        h.get("command", "") == HOOK_COMMAND
        for h in entry.get("hooks", [])
    )
    for entry in pre_tool_use
)

if already_installed:
    print("[WARN] protect-push hook 已存在，略過")
    sys.exit(0)

pre_tool_use.append(new_hook)
settings_path.write_text(
    json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8"
)
print("[OK] protect-push hook 已合併到 settings.json")
EOF
then
  echo '[FAIL] settings.json 合併失敗（JSON 格式損壞？執行 python3 -m json.tool .claude/settings.json 驗證）' >&2
  exit 1
fi
```

### Step 4: Verify

Confirm installation succeeded:

```bash
echo "=== 安裝驗證 ==="
[ -x ".claude/hooks/protect-push.sh" ] && echo "[OK] hook 腳本：存在且可執行" || echo "[FAIL] hook 腳本：未找到"
[ -f ".claude/hooks/parse_git_dir.py" ] && echo "[OK] 路徑解析器：存在" || echo "[FAIL] 路徑解析器：未找到"
python3 - << 'EOF'
import json
from pathlib import Path
s = json.loads(Path('.claude/settings.json').read_text())
hooks = s.get('hooks', {}).get('PreToolUse', [])
found = any(
    any('protect-push' in h.get('command','') for h in e.get('hooks',[]))
    for e in hooks
)
print('[OK] settings.json：hook 設定正確' if found else '[FAIL] settings.json：未找到 hook 設定')
EOF
echo "========================"
echo "[DONE] 安裝完成！下次 Claude 在此專案執行 git push 時將自動檢查 branch tracking。"
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `protect-push skill 未安裝` | Run `make install-one SKILL=protect-push` in the yibi-stack repo |
| Hook blocked a legitimate push | Run `git branch --unset-upstream && git push -u origin HEAD` to create a dedicated remote branch |
| settings.json format corrupted | Validate with `python3 -m json.tool .claude/settings.json` |
| Want to remove the hook | Delete the hook object from settings.json and remove `.claude/hooks/protect-push.sh` |
