#!/usr/bin/env python3
"""Parse .claude/commit-convention.yaml for commit-msg-hook.sh.

用法：
  commit-msg-parse.py value <config_path> <key> <default>
  commit-msg-parse.py list  <config_path> <key> <default>
"""

import re
import sys


def get_value(config_path: str, key: str, default: str) -> str:
    try:
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return default

    try:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(key + ":"):
                raw = stripped[len(key) + 1 :].strip()
                # 剝離 YAML inline comment（# 前的空白分隔）
                if " #" in raw:
                    raw = raw[: raw.index(" #")].strip()
                value = raw.strip("\"'")
                return value
    except Exception as e:
        print(f"[WARN] {config_path} 解析失敗（{e}），使用預設值", file=sys.stderr)

    return default


def get_list(config_path: str, key: str, default: str) -> str:
    try:
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return default

    try:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(key + ":"):
                rest = stripped[len(key) + 1 :].strip()
                # 支援 inline list 格式：types: [feat, fix, docs]
                if rest.startswith("[") and rest.endswith("]"):
                    items = [x.strip().strip("\"'") for x in rest[1:-1].split(",")]
                    return ",".join(i for i in items if i)
                break

        # block list 格式
        in_section = False
        items = []
        for line in content.splitlines():
            if re.match(rf"^{re.escape(key)}\s*:", line):
                in_section = True
                continue
            if in_section:
                m = re.match(r"^\s+-\s+(.+)", line)
                if m:
                    items.append(m.group(1).strip().strip("\"'"))
                elif line and not line[0].isspace():
                    break

        return ",".join(items) if items else default

    except Exception as e:
        print(f"[WARN] {config_path} 解析失敗（{e}），使用預設值", file=sys.stderr)
        return default


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("用法：commit-msg-parse.py <value|list> <config> <key> <default>", file=sys.stderr)
        sys.exit(1)

    mode, config_path, key, default = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    if mode == "value":
        print(get_value(config_path, key, default))
    elif mode == "list":
        print(get_list(config_path, key, default))
    else:
        print(f"[FAIL] 未知 mode：{mode}", file=sys.stderr)
        sys.exit(1)
