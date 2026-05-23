#!/usr/bin/env python3
"""記錄 bash hygiene hook 攔截事件到 ~/.agents/bash-hygiene-events.jsonl。

用法：
  python3 scripts/log_bash_hygiene_event.py <hook> <pattern> <cmd> [rule_id] [outcome]

欄位：
  ts          ISO 8601 UTC 時間戳
  hook        ap1 | ap2
  pattern     偵測模式（如 python_c_multiline、unicode_U+2014）
  rule_id     對應的 rule 編號（如 "13" 代表 13-bash-anti-patterns）
  outcome     block | warn | pass
  cmd_name    指令名稱（去除前置 KEY=value env 賦值後的第一個 token，最多 40 字元）
  cmd_snippet 指令原文前 200 字元（env 前綴已移除，不含 credentials）
"""

import contextlib
import datetime
import fcntl
import json
import pathlib
import re
import sys

# 去除指令前的 KEY=value env 賦值，提取安全的指令內容（不含 credentials）
_ENV_PREFIX_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]*\s+)+")


def _strip_env_prefix(cmd: str) -> str:
    return _ENV_PREFIX_RE.sub("", cmd.strip())


def _cmd_name(cmd: str) -> str:
    stripped = _strip_env_prefix(cmd)
    words = stripped.split()
    return words[0][:40] if words else (cmd.split()[0][:40] if cmd.split() else "")


def log_event(hook: str, pattern: str, cmd: str, rule_id: str = "", outcome: str = "block") -> None:
    safe_cmd = _strip_env_prefix(cmd)
    rec = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "hook": hook,
        "pattern": pattern,
        "rule_id": rule_id,
        "outcome": outcome,
        "cmd_name": safe_cmd.split()[0][:40] if safe_cmd.split() else (cmd.split()[0][:40] if cmd.split() else ""),
        "cmd_snippet": safe_cmd[:200],
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
    rule_id = sys.argv[4] if len(sys.argv) > 4 else ""
    outcome = sys.argv[5] if len(sys.argv) > 5 else "block"
    log_event(sys.argv[1], sys.argv[2], sys.argv[3], rule_id, outcome)
