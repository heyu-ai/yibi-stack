#!/usr/bin/env python3
"""記錄 bash hygiene hook 攔截事件到 ~/.agents/bash-hygiene-events.jsonl。

用法：
  python3 scripts/log_bash_hygiene_event.py <hook> <pattern> <cmd_prefix>

欄位：
  ts         ISO 8601 UTC 時間戳
  hook       ap1 | ap2
  pattern    偵測模式（如 python_c_multiline、unicode_U+2014）
  cmd_prefix 指令前 120 字元（截斷，避免記錄完整敏感指令）
"""
import datetime
import json
import pathlib
import sys

_UTC = datetime.timezone.utc


def log_event(hook: str, pattern: str, cmd_prefix: str) -> None:
    rec = {
        "ts": datetime.datetime.now(_UTC).isoformat(),
        "hook": hook,
        "pattern": pattern,
        "cmd_prefix": cmd_prefix[:120],
    }
    log_path = pathlib.Path.home() / ".agents" / "bash-hygiene-events.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(1)
    try:
        log_event(sys.argv[1], sys.argv[2], sys.argv[3])
    except Exception:
        pass
