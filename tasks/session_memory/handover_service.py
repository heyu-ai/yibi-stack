"""Handover 寫入 / 讀取 / 搜尋服務。

自動填入 metadata（device / account / project / branch），同步鏡像到 JSONL。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .account import detect_account, detect_agent_type, detect_branch, detect_device, detect_project
from .config import HANDOVER_DB_PATH, HANDOVER_JSONL_PATH
from .db import AgentsDB
from .models import HandoverRecord, SessionType


def write_handover(  # pylint: disable=too-many-arguments,too-many-locals
    session_type: SessionType,
    topic: str,
    summary: str,
    *,
    operator: str = "howie",
    completed: list[str] | None = None,
    decisions: list[str] | None = None,
    blocked: list[str] | None = None,
    next_priorities: list[str] | None = None,
    lessons_learned: list[str] | None = None,
    attempted_approaches: list[str] | None = None,
    tags: list[str] | None = None,
    last_files: list[str] | None = None,
    test_status: str | None = None,
    token_usage_estimate: str | None = None,
    working_dir: str | None = None,
    # 以下若未提供則自動偵測
    device: str | None = None,
    agent_type: str | None = None,
    account: str | None = None,
    branch: str | None = None,
    project: str | None = None,
    db_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> HandoverRecord:
    """寫入一筆 handover：自動 detect metadata、INSERT SQLite、append JSONL 鏡像。"""
    if not topic.strip():
        raise ValueError("topic 不可為空")
    if not summary.strip():
        raise ValueError("summary 不可為空")

    record = HandoverRecord(
        id=str(uuid.uuid4()),
        timestamp=_now_iso(),
        operator=operator,
        session_type=session_type,
        topic=topic,
        conversation_summary=summary,
        completed=completed or [],
        decisions=decisions or [],
        blocked=blocked or [],
        next_priorities=next_priorities or [],
        lessons_learned=lessons_learned or [],
        attempted_approaches=attempted_approaches or [],
        tags=tags or [],
        device=device or detect_device(),
        agent_type=agent_type or detect_agent_type(),
        subscription_account=account
        or detect_account(agent_type=agent_type or "claude", warn=False),
        branch=branch if branch is not None else detect_branch(),
        working_dir=working_dir or str(Path.cwd()),
        last_files=last_files or [],
        test_status=test_status,
        token_usage_estimate=token_usage_estimate,
        project=project or detect_project(),
    )

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        db.insert_handover(record)
    finally:
        db.close()

    _append_jsonl(record, jsonl_path or HANDOVER_JSONL_PATH)
    return record


def read_recent(
    last: int = 4,
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """讀取最近 N 筆。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.read_recent(last)
    finally:
        db.close()


def search_handovers(
    query: str | None = None,
    session_type: SessionType | None = None,
    project: str | None = None,
    account: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """搜尋 handover 記錄。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.search(
            query=query,
            session_type=session_type,
            project=project,
            account=account,
            limit=limit,
        )
    finally:
        db.close()


def _append_jsonl(record: HandoverRecord, path: Path) -> None:
    """把 record 以單行 JSON 寫入 JSONL 檔案尾端。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()
