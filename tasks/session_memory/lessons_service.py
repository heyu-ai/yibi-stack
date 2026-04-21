"""教訓聯合查詢 service：整合 handover lessons_learned 與 insight 洞察。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def show_lessons(
    project: str | None = None,
    limit: int = 20,
    include_insights: bool = False,
    db_path: str | Path | None = None,
    insights_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """查詢 handover 教訓，可選合併 insight 洞察。

    回傳統一格式 list，每筆含：
    - source: "handover" | "insight"
    - text: 教訓或洞察內容
    - timestamp: ISO 8601
    - project: 專案名稱
    - context: 來源脈絡（handover topic 或 insight session_id）
    """
    from .config import INSIGHTS_JSONL_PATH
    from .db import AgentsDB

    results: list[dict[str, Any]] = []

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = db.query_lessons(project=project, limit=limit)
    finally:
        db.close()

    for row in rows:
        ts = row.get("timestamp", "")
        topic = row.get("topic", "")
        proj = row.get("project") or project or ""
        for lesson in row.get("lessons_learned", []):
            results.append(
                {
                    "source": "handover",
                    "text": lesson,
                    "timestamp": ts,
                    "project": proj,
                    "context": topic,
                }
            )
        for approach in row.get("attempted_approaches", []):
            results.append(
                {
                    "source": "handover-approach",
                    "text": approach,
                    "timestamp": ts,
                    "project": proj,
                    "context": topic,
                }
            )

    if include_insights:
        resolved = Path(insights_path) if insights_path else INSIGHTS_JSONL_PATH
        results.extend(_load_insights(resolved, project=project, limit=limit))

    return results


def search_lessons(
    query: str,
    project: str | None = None,
    limit: int = 20,
    include_insights: bool = False,
    db_path: str | Path | None = None,
    insights_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """搜尋 handover 教訓與 insight 洞察。"""
    from .config import INSIGHTS_JSONL_PATH
    from .db import AgentsDB

    results: list[dict[str, Any]] = []
    q = query.lower()

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = db.search(query=query, project=project, limit=limit)
    finally:
        db.close()

    for row in rows:
        ts = row.get("timestamp", "")
        topic = row.get("topic", "")
        proj = row.get("project") or project or ""
        for lesson in row.get("lessons_learned", []):
            if q in lesson.lower():
                results.append(
                    {
                        "source": "handover",
                        "text": lesson,
                        "timestamp": ts,
                        "project": proj,
                        "context": topic,
                    }
                )
        for approach in row.get("attempted_approaches", []):
            if q in approach.lower():
                results.append(
                    {
                        "source": "handover-approach",
                        "text": approach,
                        "timestamp": ts,
                        "project": proj,
                        "context": topic,
                    }
                )

    if include_insights:
        resolved = Path(insights_path) if insights_path else INSIGHTS_JSONL_PATH
        for entry in _load_insights(resolved, project=project, limit=limit):
            if q in entry["text"].lower():
                results.append(entry)

    return results


def _load_insights(
    path: Path,
    project: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """從 insights.jsonl 載入洞察記錄。"""
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project and entry.get("project") != project:
                continue
            rows.append(entry)

    return [
        {
            "source": "insight",
            "text": r.get("insight_text", ""),
            "timestamp": r.get("timestamp", ""),
            "project": r.get("project", ""),
            "context": r.get("session_id", ""),
        }
        for r in rows[-limit:]
    ]
