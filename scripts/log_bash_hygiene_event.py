#!/usr/bin/env python3
"""記錄 bash hygiene hook 攔截事件到 ~/.agents/bash-hygiene-events.jsonl。

用法：
  python3 scripts/log_bash_hygiene_event.py <hook> <pattern> <cmd>

欄位：
  ts       ISO 8601 UTC 時間戳
  hook     ap1 | ap2
  pattern  偵測模式（如 python_c_multiline、unicode_U+2014）
  cmd_name 指令名稱（去除前置 KEY=value env 賦值後的第一個 token，最多 40 字元）
"""
import contextlib
import datetime
import fcntl
import json
import pathlib
import re
import sys

# 去除指令前的 KEY=value env 賦值，提取安全的指令名稱（不含 credentials）
_ENV_PREFIX_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]*\s+)+")


def _cmd_name(cmd: str) -> str:
    stripped = _ENV_PREFIX_RE.sub("", cmd.strip())
    words = stripped.split()
    return words[0][:40] if words else (cmd.split()[0][:40] if cmd.split() else "")


def log_event(hook: str, pattern: str, cmd: str) -> None:
    rec = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "hook": hook,
        "pattern": pattern,
        "cmd_name": _cmd_name(cmd),
    }
    log_path = pathlib.Path.home() / ".agents" / "bash-hygiene-events.jsonl"
    with contextlib.suppress(Exception):
        log_path.parent.mkdir(exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fp:
            fcntl.flock(fp, fcntl.LOCK_EX)
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(0)
    log_event(sys.argv[1], sys.argv[2], sys.argv[3])
