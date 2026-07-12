"""Retrospective 寫入 / 讀取 / 搜尋服務。

一次已完成 PR/session 的最終回顧報告；語意上與 handover_service（工作中途的暫存
handoff 狀態）分開，不共用 handovers table，也不需要 tag/topic 前綴 discriminator。
自動填入 metadata（device / account / project / branch），同步鏡像到 JSONL。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .account import detect_account, detect_agent_type, detect_branch, detect_device, detect_project
from .config import HANDOVER_DB_PATH, RETRO_JSONL_PATH, from_portable_path, to_portable_path
from .db import AgentsDB
from .models import RetrospectiveRecord
from .token_usage_service import compute_auto_token_fields


def write_retrospective(  # pylint: disable=too-many-arguments,too-many-locals
    pr_number: int,
    topic: str,
    summary: str,
    *,
    operator: str = "howie",
    completed: list[str] | None = None,
    decisions: list[str] | None = None,
    next_priorities: list[str] | None = None,
    lessons_learned: list[str] | None = None,
    tags: list[str] | None = None,
    auto_token_usage: bool = False,
    working_dir: str | None = None,
    # 以下若未提供則自動偵測
    device: str | None = None,
    agent_type: str | None = None,
    account: str | None = None,
    branch: str | None = None,
    project: str | None = None,
    db_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> RetrospectiveRecord:
    """寫入一筆 retrospective：自動 detect metadata、INSERT SQLite、append JSONL 鏡像。"""
    if not topic.strip():
        raise ValueError("topic 不可為空")
    if not summary.strip():
        raise ValueError("summary 不可為空")

    # 統一計算有效工作目錄，確保 working_dir 與 project 來自同一路徑
    effective_dir = Path(working_dir).resolve() if working_dir else Path.cwd().resolve()

    token_fields = compute_auto_token_fields(effective_dir, auto_token_usage)

    record = RetrospectiveRecord(
        id=str(uuid.uuid4()),
        timestamp=_now_iso(),
        operator=operator,
        pr_number=pr_number,
        topic=topic,
        conversation_summary=summary,
        completed=completed or [],
        decisions=decisions or [],
        next_priorities=next_priorities or [],
        lessons_learned=lessons_learned or [],
        tags=tags or [],
        device=device or detect_device(),
        agent_type=agent_type or detect_agent_type(),
        subscription_account=account
        or detect_account(agent_type=agent_type or "claude", warn=False),
        branch=branch if branch is not None else detect_branch(),
        working_dir=to_portable_path(str(effective_dir)),
        project=project or detect_project(effective_dir),
        **token_fields,
    )

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        db.insert_retrospective(record)
    except sqlite3.IntegrityError as e:
        raise RuntimeError(f"retrospective 寫入失敗（ID 衝突或 schema 不符）：{e}") from e
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"retrospective 寫入失敗（資料庫錯誤）：{e}") from e
    finally:
        db.close()

    _append_jsonl(record, jsonl_path or RETRO_JSONL_PATH)
    return record


def read_recent_retrospectives(
    last: int = 4,
    *,
    project: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """讀取最近 N 筆 retrospective，可選依 project 過濾。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return [_expand_paths(row) for row in db.read_recent_retrospectives(last, project=project)]
    finally:
        db.close()


def search_retrospectives(
    query: str | None = None,
    pr_number: int | None = None,
    project: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """搜尋 retrospective 記錄；`pr_number` 為精確匹配。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        rows = db.search_retrospectives(
            query=query,
            pr_number=pr_number,
            project=project,
            limit=limit,
        )
    finally:
        db.close()
    return [_expand_paths(row) for row in rows]


def _expand_paths(row: dict[str, Any]) -> dict[str, Any]:
    """將 working_dir 的 ~/... 展開為當前機器絕對路徑。回傳新 dict，不改原物件。

    若展開失敗（如舊格式絕對路徑），保留原值並繼續，避免舊 DB 資料讓整批讀取崩潰。
    """
    result = dict(row)
    if result.get("working_dir"):
        with contextlib.suppress(ValueError):  # 保留原值，向後相容舊 DB 格式
            result["working_dir"] = from_portable_path(result["working_dir"])
    return result


def _append_jsonl(record: RetrospectiveRecord, path: Path) -> None:
    """把 record 以單行 JSON 寫入 JSONL 檔案尾端。

    JSONL 為 DB 的備份副本。若寫入失敗（如磁碟空間不足），僅記錄警告，
    不影響主要 DB 寫入（DB 已在呼叫端完成，資料不遺失）。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        import warnings

        warnings.warn(f"JSONL 備份寫入失敗（DB 資料已保存）：{e}", stacklevel=2)


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()
