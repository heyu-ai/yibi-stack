"""`handover write` 在真實 SQLite 鎖定下的共用測試 helper（issue #584 AC-5）。

不 mock 專案內的 `AgentsDB`：另開一條 sqlite3 連線對 tmp DB 持有 `BEGIN EXCLUSIVE`，
再把 `tasks.mycelium.db.sqlite3.connect` 換成 `timeout=0.2` 的版本，讓 CLI 很快就收到真正的
`database is locked`。供 tasks/mycelium/tests/test_cli.py 與
scripts/tests/test_handover_command_doc.py 共用（依 rule 09 不用 conftest／fixture）。
"""

from __future__ import annotations

import functools
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.handover_service import read_recent
from tasks.mycelium.metrics_service import list_events
from tasks.mycelium.models import EventType

# 兩種鎖定時點：空 DB 鎖在 init_db（切 WAL／建表），已初始化的 DB 鎖在 INSERT
LOCK_STAGES = ("init_db", "insert")


@dataclass(frozen=True)
class LockedWriteResult:
    """鎖定下執行 `handover write` 的結果，以及鎖釋放後量到的副作用。"""

    exit_code: int
    output: str
    exception: BaseException | None
    handover_rows: list[dict[str, Any]]
    handover_jsonl_exists: bool
    written_events: list[dict[str, Any]]
    events_jsonl_exists: bool


def run_handover_write_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stage: str
) -> LockedWriteResult:
    """在 tmp DB 被另一條連線鎖住時執行 `handover write --from-file`。

    交班 DB／JSONL 與 metrics 事件 DB／JSONL 都導到 tmp；事件 DB 與交班 DB 分開，
    這樣若事件被提前寫出（例如 emit 移到 DB 寫入之前），不會因同一把鎖而被吞掉、無從察覺。
    """
    if stage not in LOCK_STAGES:
        raise ValueError(f"未知的鎖定時點：{stage}")
    db_path = tmp_path / "handover.db"
    jsonl_path = tmp_path / "handover.jsonl"
    events_db = tmp_path / "events.db"
    events_jsonl = tmp_path / "events.jsonl"
    if stage == "insert":
        db = AgentsDB(db_path)
        try:
            db.init_db()
        finally:
            db.close()

    monkeypatch.setattr("tasks.mycelium.handover_service.HANDOVER_DB_PATH", db_path)
    monkeypatch.setattr("tasks.mycelium.handover_service.HANDOVER_JSONL_PATH", jsonl_path)
    monkeypatch.setattr("tasks.mycelium.metrics_service.HANDOVER_DB_PATH", events_db)
    monkeypatch.setattr("tasks.mycelium.metrics_service.HANDOVER_EVENTS_JSONL_PATH", events_jsonl)
    payload = tmp_path / "handover.json"
    payload.write_text(
        json.dumps({"session_type": "debug", "topic": "t", "summary": "s"}), encoding="utf-8"
    )

    real_connect = sqlite3.connect
    holder = real_connect(db_path)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        # 注意：這會換掉整個 sqlite3 模組的 connect，monkeypatch 於測試結束時還原
        monkeypatch.setattr(
            "tasks.mycelium.db.sqlite3.connect", functools.partial(real_connect, timeout=0.2)
        )
        result = CliRunner().invoke(cli, ["handover", "write", "--from-file", str(payload)])
    finally:
        holder.rollback()
        holder.close()

    # 鎖已釋放才量副作用，否則 read_recent／list_events 自己也會撞鎖
    return LockedWriteResult(
        exit_code=result.exit_code,
        output=result.output,
        exception=result.exception,
        handover_rows=read_recent(last=10, db_path=db_path),
        handover_jsonl_exists=jsonl_path.exists(),
        written_events=list_events(event_type=EventType.handover_written, db_path=events_db),
        events_jsonl_exists=events_jsonl.exists(),
    )


def assert_clean_lock_failure(result: LockedWriteResult) -> None:
    """鎖定失敗必須乾淨：exit 1、兩段分流文字、沒有 ✓ 行、DB／JSONL／事件都沒有寫出。"""
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "交班記錄寫入失敗" in result.output
    assert "database is locked" in result.output
    assert "✓" not in result.output
    assert result.handover_rows == []
    assert not result.handover_jsonl_exists
    assert result.written_events == []
    assert not result.events_jsonl_exists
