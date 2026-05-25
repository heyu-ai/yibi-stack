"""Tag management service：全域 tag 統計、更名、清除。"""

from __future__ import annotations

from pathlib import Path

from .config import HANDOVER_DB_PATH
from .db import AgentsDB
from .models import TagEntry, TagStats


def get_tag_stats(
    db_path: Path | None = None,
    top_n: int | None = None,
) -> TagStats:
    """計算全域 tag 使用統計。

    Args:
        db_path: 覆寫預設 DB 路徑（測試用）。
        top_n: 只回傳最常用的前 N 個 tag；None 表示全部。

    Returns:
        TagStats 物件，entries 按 count DESC 排序。
    """
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        raw = db.get_tag_usage()
    finally:
        db.close()

    if top_n is not None and top_n > 0:
        raw = raw[:top_n]

    entries = [
        TagEntry(
            tag=item["tag"],
            count=item["count"],
            latest_at=item["latest_at"],
            projects=item["projects"],
        )
        for item in raw
    ]

    all_unique = len(raw) if top_n is None else len(db.get_all_tags()) if False else len(raw)
    total_with_tags = sum(e.count for e in entries)

    return TagStats(
        total_unique_tags=len(entries),
        total_handovers_with_tags=total_with_tags,
        entries=entries,
    )


def rename_tag(
    old_tag: str,
    new_tag: str,
    db_path: Path | None = None,
) -> int:
    """將所有 handover 記錄中的 old_tag 改為 new_tag。

    Args:
        old_tag: 要更名的 tag。
        new_tag: 新 tag 名稱（不可為空）。
        db_path: 覆寫預設 DB 路徑（測試用）。

    Returns:
        更新的 handover 筆數。

    Raises:
        ValueError: new_tag 為空字串。
    """
    if not new_tag.strip():
        raise ValueError("new_tag 不可為空字串")
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.rename_tag(old_tag, new_tag)
    finally:
        db.close()


def purge_tag(
    tag: str,
    db_path: Path | None = None,
) -> int:
    """刪除所有含指定 tag 的 handover 記錄。

    這是不可逆操作。呼叫端應在執行前向使用者確認。

    Args:
        tag: 要清除的 tag 名稱。
        db_path: 覆寫預設 DB 路徑（測試用）。

    Returns:
        刪除的 handover 筆數。
    """
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.delete_by_tag(tag)
    finally:
        db.close()


def list_all_tags(db_path: Path | None = None) -> list[str]:
    """列出所有已使用的 tag（去重排序）。

    Args:
        db_path: 覆寫預設 DB 路徑（測試用）。

    Returns:
        tag 名稱清單（升序排列）。
    """
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.get_all_tags()
    finally:
        db.close()
