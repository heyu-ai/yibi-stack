"""Archival service：將 archival tier 的 lesson 匯出到 ~/.agents/archive/YYYY-MM.md。

archive_lesson() 接受 LessonRecord，寫入月度 Markdown 檔並更新 DB 的 archived_path 欄位。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_ARCHIVE_DIR = Path.home() / ".agents" / "archive"


def archive_lesson(
    lesson: Any,
    db: Any,
    archive_dir: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """將 lesson 完整內容寫入 ~/.agents/archive/YYYY-MM.md 並更新 DB archived_path。

    參數：
      lesson: LessonRecord（或含 id/insight/type/tags 欄位的 dict-like 物件）
      db: AgentsDB 實例（需 init_db() 已呼叫）
      archive_dir: 自訂歸檔目錄（測試用）；預設 ~/.agents/archive/
      now: 指定時間點（測試用）；預設 UTC now

    回傳歸檔檔案路徑。
    """
    _now = now or datetime.now(UTC)
    _dir = archive_dir or _ARCHIVE_DIR

    month_str = _now.strftime("%Y-%m")
    archive_path = _dir / f"{month_str}.md"

    _dir.mkdir(parents=True, exist_ok=True)

    if isinstance(lesson, dict):
        lesson_id = lesson.get("id", "unknown")
        insight = lesson.get("insight", "")
        lesson_type = lesson.get("type", "")
        tags = lesson.get("tags", [])
        ts = lesson.get("ts", _now.isoformat())
    else:
        lesson_id = lesson.id
        insight = lesson.insight
        lesson_type = lesson.type
        tags = lesson.tags
        ts = lesson.ts

    if hasattr(lesson_type, "value"):
        lesson_type = lesson_type.value

    tags_str = ", ".join(tags) if tags else "(none)"

    entry = (
        f"\n## {ts[:10]} [{lesson_type}] {lesson_id}\n\n"
        f"**Tags**: {tags_str}\n\n"
        f"{insight}\n"
        f"\n---\n"
    )

    with archive_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    db.conn.execute(
        "UPDATE lessons SET archived_path = ? WHERE id = ?",
        (str(archive_path), lesson_id),
    )
    db.conn.commit()

    return archive_path


def archive_lesson_by_id(lesson_id: str, db: Any) -> Path | None:
    """透過 lesson_id 從 DB 讀取並呼叫 archive_lesson()。未找到時回傳 None。"""
    row = db.conn.execute(
        "SELECT id, ts, type, insight, tags FROM lessons WHERE id = ?",
        (lesson_id,),
    ).fetchone()
    if row is None:
        return None

    import json

    lesson_dict = {
        "id": row["id"],
        "ts": row["ts"],
        "type": row["type"],
        "insight": row["insight"],
        "tags": json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or []),
    }
    return archive_lesson(lesson_dict, db)
