"""bash-hygiene hook 共用 audit logger（Python hooks 使用）。

Fail-safe 合約：任何 exception 靜默吞掉，絕不影響 hook 判斷。
呼叫方式：
    from _audit_log import log_event
    log_event("ap2", command, exit_code=0, duration_ms=elapsed_ms)
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path.home() / ".agents" / "bash-hygiene.json"
PREVIEW_CHARS = 200
HOOK_VERSION = "1"


def _enabled() -> bool:
    try:
        if not CONFIG_PATH.is_file():
            return False
        return bool(json.loads(CONFIG_PATH.read_text("utf-8")).get("audit_enabled"))
    except Exception:
        return False


def _log_path() -> Path | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode != 0:
            return None
        d = Path(r.stdout.strip()) / ".runtime" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / "bash-hygiene-audit.jsonl"
    except Exception:
        return None


def log_event(
    hook: str,
    command: str,
    exit_code: int,
    block_reason: str | None = None,
    duration_ms: int | None = None,
) -> None:
    if not _enabled():
        return
    try:
        path = _log_path()
        if path is None:
            return
        record = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(),
            "hook": hook,
            "hook_version": HOOK_VERSION,
            "exit_code": exit_code,
            "verdict": "block" if exit_code == 2 else ("allow" if exit_code == 0 else "error"),
            "block_reason": block_reason,
            "command_preview": command[:PREVIEW_CHARS],
            "command_hash": hashlib.sha256(command.encode("utf-8")).hexdigest()[:16],
            "session_id": os.environ.get("CLAUDE_SESSION_ID"),
            "duration_ms": duration_ms,
        }
        with path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


# 供 bash hook 呼叫的 CLI entry（bash-ap1 不應使用，改用 _audit_log.sh）
def _main_cli() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="bash-hygiene audit logger CLI")
    parser.add_argument("--hook", required=True)
    parser.add_argument("--verdict", required=True, choices=["allow", "block"])
    parser.add_argument("--command", required=True)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--duration-ms", type=int, default=None, dest="duration_ms")
    args = parser.parse_args()
    exit_code = 2 if args.verdict == "block" else 0
    log_event(args.hook, args.command, exit_code, args.reason, args.duration_ms)


if __name__ == "__main__":
    _main_cli()
