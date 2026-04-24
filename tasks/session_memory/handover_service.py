"""Handover 寫入 / 讀取 / 搜尋服務。

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
from .config import HANDOVER_DB_PATH, HANDOVER_JSONL_PATH, from_portable_path, to_portable_path
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

    # 統一計算有效工作目錄，確保 working_dir 與 project 來自同一路徑
    effective_dir = Path(working_dir).resolve() if working_dir else Path.cwd().resolve()

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
        working_dir=to_portable_path(str(effective_dir)),
        last_files=[to_portable_path(f) for f in (last_files or [])],
        test_status=test_status,
        token_usage_estimate=token_usage_estimate,
        project=project or detect_project(effective_dir),
    )

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        db.insert_handover(record)
    except sqlite3.IntegrityError as e:
        raise RuntimeError(f"交班記錄寫入失敗（ID 衝突或 schema 不符）：{e}") from e
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"交班記錄寫入失敗（資料庫錯誤）：{e}") from e
    finally:
        db.close()

    _append_jsonl(record, jsonl_path or HANDOVER_JSONL_PATH)
    _emit_handover_written_event(record, db_path=db_path)
    return record


def _emit_handover_written_event(record: HandoverRecord, *, db_path: Path | None) -> None:
    """寫入 handover_written 事件，供成功率量測使用。永不 raise。"""
    import warnings

    from .metrics_service import _try_resolve_session_id, log_event
    from .models import EventType, SourceLayer

    try:
        log_event(
            EventType.handover_written,
            session_id=_try_resolve_session_id(),
            source_layer=SourceLayer.cli,
            handover_id=record.id,
            project=record.project,
            device=record.device,
            db_path=db_path,
        )
    except Exception as e:  # noqa: BLE001  shadow logging 不影響主流程
        warnings.warn(f"handover_written 事件寫入失敗：{e}", stacklevel=2)


def read_recent(
    last: int = 4,
    *,
    project: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """讀取最近 N 筆，可選依 project 過濾。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return [_expand_paths(row) for row in db.read_recent(last, project=project)]
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
        rows = db.search(
            query=query,
            session_type=session_type,
            project=project,
            account=account,
            limit=limit,
        )
    finally:
        db.close()
    return [_expand_paths(row) for row in rows]


def _expand_paths(row: dict[str, Any]) -> dict[str, Any]:
    """將 working_dir 與 last_files 的 ~/... 展開為當前機器絕對路徑。回傳新 dict，不改原物件。

    若單一欄位展開失敗（如舊格式絕對路徑），保留原值並繼續，避免舊 DB 資料讓整批讀取崩潰。
    """
    result = dict(row)
    if result.get("working_dir"):
        with contextlib.suppress(ValueError):  # 保留原值，向後相容舊 DB 格式
            result["working_dir"] = from_portable_path(result["working_dir"])
    if result.get("last_files") and isinstance(result["last_files"], list):
        expanded: list[str] = []
        for f in result["last_files"]:
            try:
                expanded.append(from_portable_path(f))
            except ValueError:
                expanded.append(f)  # 保留原值
        result["last_files"] = expanded
    return result


def _append_jsonl(record: HandoverRecord, path: Path) -> None:
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
