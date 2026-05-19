#!/usr/bin/env python3
"""幂等地將 gemini 相關指令加入 ~/.claude/settings.json allow list。"""
import json
import os
import pathlib
import sys

SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"

ENTRIES_TO_ADD = [
    "Bash(gemini:*)",
    'Bash(gemini -m * -p "@/tmp/pr-review/*")',
]


def main() -> None:
    if not SETTINGS_PATH.is_file():
        print(f"  [WARN] {SETTINGS_PATH} 不存在 — 請先啟動 Claude Code 以產生設定檔，再重跑 make patch-gemini-allow-list")
        return

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [FAIL] settings.json 格式錯誤：{e}")
        sys.exit(1)
    perms = data.setdefault("permissions", {})
    allow: list[str] = perms.setdefault("allow", [])

    added = []
    for entry in ENTRIES_TO_ADD:
        if entry not in allow:
            allow.append(entry)
            added.append(entry)

    if added:
        tmp = SETTINGS_PATH.with_name("settings.json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, SETTINGS_PATH)
        for entry in added:
            print(f"  [OK] Added: {entry}")
    else:
        print("  [OK] gemini allow list entries already present")


if __name__ == "__main__":
    main()
