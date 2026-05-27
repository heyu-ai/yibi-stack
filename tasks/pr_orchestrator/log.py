"""Append-only JSONL transition log。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .._paths import RUNTIME_DIR

_LOG_BASE = RUNTIME_DIR / "logs" / "pr_orchestrator"


def log_path(pr_number: int) -> Path:
    return _LOG_BASE / f"{pr_number}.log"


def append(
    pr_number: int, from_state: str, to_state: str,
    reason: str = "", actor: str = "orchestrator",
) -> None:
    """追加一筆 transition log（不讀、不重寫，只 append）。"""
    _LOG_BASE.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "pr": pr_number,
        "from": from_state,
        "to": to_state,
        "actor": actor,
        "reason": reason,
    }
    with log_path(pr_number).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read(pr_number: int) -> list[dict]:  # type: ignore[type-arg]
    """讀取全部 transition log entries（失敗時回傳空清單）。"""
    p = log_path(pr_number)
    if not p.exists():
        return []
    entries = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:  # nosec B112
                continue
    except OSError:
        return []
    return entries
