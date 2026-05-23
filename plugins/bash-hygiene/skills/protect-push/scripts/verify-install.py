#!/usr/bin/env python3
"""protect-push 安裝驗證：確認 hook 腳本存在且 settings.json 設定正確。"""

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

try:
    repo_root = subprocess.check_output(  # nosec B603 B607
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
except (subprocess.CalledProcessError, FileNotFoundError):
    print("[FAIL] 無法找到 git repo root -- 請確認 git 已安裝且目前在 git repo 目錄內")
    sys.exit(1)

settings_path = Path(repo_root) / ".claude" / "settings.json"

try:
    text = settings_path.read_text(encoding="utf-8")
except FileNotFoundError:
    print(f"[FAIL] {settings_path} 不存在 -- 請先啟動 Claude Code 產生設定檔")
    sys.exit(1)
except PermissionError as e:
    print(f"[FAIL] {settings_path} 無法讀取：{e}")
    sys.exit(1)

try:
    s = json.loads(text)
except json.JSONDecodeError as e:
    print(f"[FAIL] {settings_path} JSON 格式錯誤：{e}")
    sys.exit(1)

hooks_root = s.get("hooks")
if not isinstance(hooks_root, dict):
    print("[FAIL] settings.json 格式異常：hooks 欄位應為 dict")
    sys.exit(1)

hooks = hooks_root.get("PreToolUse", [])
if not isinstance(hooks, list):
    print("[FAIL] settings.json 格式異常：PreToolUse 應為 list")
    sys.exit(1)

found = False
for entry in hooks:
    if not isinstance(entry, dict):
        continue
    nested = entry.get("hooks", [])
    if not isinstance(nested, list):
        continue
    for h in nested:
        if not isinstance(h, dict):
            continue
        if h.get("type") == "command" and "protect-push" in h.get("command", ""):
            found = True
            break
    if found:
        break

if found:
    print("[OK] settings.json：hook 設定正確")
else:
    print("[FAIL] settings.json：未找到 hook 設定")
    sys.exit(1)
