"""Tier promotion / demotion service。

run_promotion_check() 掃描所有 non-archived lessons，依規則升降級：
  working -> hot：access_count >= 3
  working/hot -> cold：access_count == 0 AND age > 90 天
  cold -> archival：access_count == 0 AND age > 365 天

archival 降級同時呼叫 archival.archive_lesson()。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class PromotionResult:
    """升降級統計報告。"""

    promoted_to_hot: int = 0
    demoted_to_cold: int = 0
    demoted_to_archival: int = 0
    errors: list[str] = field(default_factory=list)


def run_promotion_check(
    db_path: str | Path | None = None,
    now: datetime | None = None,
) -> PromotionResult:
    """掃描 lessons table，依 tier 規則執行升降級。

    升降級規則（依 spec mycelium-memory-tiers）：
    - working -> hot：access_count >= 3
    - working/hot -> cold：access_count == 0 AND age > 90 天
    - cold -> archival：access_count == 0 AND age > 365 天

    回傳 PromotionResult 含升降級計數。
    """
    from .db import AgentsDB

    _now = now if now is not None else datetime.now(UTC)
    result = PromotionResult()

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = _fetch_non_archival(db)
        for row in rows:
            try:
                _process_row(row, db, _now, result)
            except Exception as e:
                result.errors.append(f"id={row.get('id', '?')}: {e}")
    finally:
        db.close()

    return result


def _fetch_non_archival(db: Any) -> list[dict[str, Any]]:
    """取得所有 tier != 'archival' 的 lesson rows。"""
    cur = db.conn.execute(
        "SELECT id, ts, tier, access_count, last_accessed_at FROM lessons WHERE tier != 'archival'"
    )
    return [dict(row) for row in cur.fetchall()]


def _age_days(row: dict[str, Any], now: datetime) -> float:
    """計算 lesson 的 age（天數）；使用 ts 作為 creation time。"""
    ts_str = row.get("ts", "")
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return (now - ts).total_seconds() / 86400
    except ValueError:
        return 0.0


def _process_row(
    row: dict[str, Any],
    db: Any,
    now: datetime,
    result: PromotionResult,
) -> None:
    """對單筆 lesson 判斷 tier 是否需要變更。"""
    lesson_id = row["id"]
    tier = row.get("tier", "working")
    access_count = row.get("access_count", 0)
    age = _age_days(row, now)

    new_tier: str | None = None

    if tier in ("working", "hot") and access_count >= 3:
        new_tier = "hot"
    elif tier in ("working", "hot") and access_count == 0 and age > 90:
        new_tier = "cold"
    elif tier == "cold" and access_count == 0 and age > 365:
        new_tier = "archival"

    if new_tier is None or new_tier == tier:
        return

    db.conn.execute(
        "UPDATE lessons SET tier = ? WHERE id = ?",
        (new_tier, lesson_id),
    )
    db.conn.commit()

    if new_tier == "hot":
        result.promoted_to_hot += 1
    elif new_tier == "cold":
        result.demoted_to_cold += 1
    elif new_tier == "archival":
        result.demoted_to_archival += 1
        _try_archive(lesson_id, db)


def _try_archive(lesson_id: str, db: Any) -> None:
    """嘗試把 lesson 匯出到 ~/.agents/archive/YYYY-MM.md；失敗時靜默記錄。"""
    try:
        from .archival import archive_lesson_by_id

        archive_lesson_by_id(lesson_id, db)
    except Exception:
        pass
