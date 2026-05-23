#!/usr/bin/env python3
"""protect-push 安裝：將 hook 設定合併到 .claude/settings.json。"""

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

try:
    repo_root = subprocess.check_output(  # nosec B603 B607
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
except (subprocess.CalledProcessError, FileNotFoundError):
    print("[FAIL] 無法找到 git repo root（git 未安裝、不在 PATH 或非 git repo）")
    sys.exit(1)

settings_path = Path(repo_root) / ".claude" / "settings.json"

try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
except FileNotFoundError:
    print(f"[FAIL] {settings_path} 不存在，請先確認 Step 3A 已建立 settings.json")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"[FAIL] {settings_path} JSON 格式錯誤：{e}")
    sys.exit(1)

new_hook = {
    "hooks": [
        {
            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/protect-push.sh',
            "type": "command",
            "statusMessage": "檢查 git push 安全性...",
        }
    ],
    "matcher": "Bash",
}

hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print("[FAIL] settings.json 格式異常：hooks 欄位應為 dict")
    sys.exit(1)

pre_tool_use = hooks.setdefault("PreToolUse", [])
if not isinstance(pre_tool_use, list):
    print("[FAIL] settings.json 格式異常：PreToolUse 應為 list")
    sys.exit(1)

HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/protect-push.sh'
already_installed = any(
    any(
        isinstance(h, dict) and h.get("command", "") == HOOK_COMMAND for h in entry.get("hooks", [])
    )
    for entry in pre_tool_use
    if isinstance(entry, dict)
)

if already_installed:
    print("[WARN] protect-push hook 已存在，略過")
    sys.exit(0)

pre_tool_use.append(new_hook)
settings_path.write_text(
    json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("[OK] protect-push hook 已合併到 settings.json")
