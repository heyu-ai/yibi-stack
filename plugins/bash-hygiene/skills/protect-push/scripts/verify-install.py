#!/usr/bin/env python3
"""protect-push 安裝驗證：確認 hook 腳本存在且 settings.json 設定正確。"""
import json
from pathlib import Path

s = json.loads(Path(".claude/settings.json").read_text())
hooks = s.get("hooks", {}).get("PreToolUse", [])
found = any(
    any("protect-push" in h.get("command", "") for h in e.get("hooks", []))
    for e in hooks
)
print("[OK] settings.json：hook 設定正確" if found else "[FAIL] settings.json：未找到 hook 設定")
