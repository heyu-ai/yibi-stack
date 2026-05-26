#!/usr/bin/env python3
"""冪等地將 agy（Antigravity CLI）相關指令加入 ~/.claude/settings.json allow list。"""

import json
import os
import pathlib
import shutil
import sys

SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"

_AGY_SCRIPT = str(pathlib.Path.home() / ".agents" / "skills" / "agy" / "scripts" / "run.sh")

ENTRIES_TO_ADD = [
    "Bash(agy:*)",
    f"Bash(bash {_AGY_SCRIPT}:*)",
]


def main() -> None:
    if not SETTINGS_PATH.is_file():
        print(
            f"  [FAIL] {SETTINGS_PATH} 不存在 — 請先啟動 Claude Code 以產生設定檔，再重跑 make patch-agy-allow-list",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [FAIL] settings.json 格式錯誤：{e}", file=sys.stderr)
        sys.exit(1)
    perms = data.setdefault("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms
    allow = perms.get("allow")
    if not isinstance(allow, list):
        allow = []
        perms["allow"] = allow

    added = []
    for entry in ENTRIES_TO_ADD:
        if entry not in allow:
            allow.append(entry)
            added.append(entry)

    if added:
        tmp = SETTINGS_PATH.with_name("settings.json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.copymode(SETTINGS_PATH, tmp)
        os.replace(tmp, SETTINGS_PATH)
        for entry in added:
            print(f"  [OK] Added: {entry}")
    else:
        print("  [OK] agy allow list entries already present")


if __name__ == "__main__":
    main()
