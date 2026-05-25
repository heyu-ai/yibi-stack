"""教訓聯合查詢 service：整合 handover lessons_learned、attempted_approaches 與 insight 洞察。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from math import floor
from pathlib import Path
from typing import Any

# search_lessons 內部查詢上限：用 query_lessons 載入所有含教訓的記錄再 Python 過濾，
# 確保 limit 語意為「回傳教訓條目數」而非「掃描 handover 記錄數」
_SEARCH_INTERNAL_LIMIT = 500

# Insight 注入保護：10 條 case-insensitive regex
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore.*previous.*(instructions|context|rules)", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"always output no findings", re.IGNORECASE),
    re.compile(r"skip.*(security|review|checks)", re.IGNORECASE),
    re.compile(r"override:", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\bassistant\s*:", re.IGNORECASE),
    re.compile(r"\buser\s*:", re.IGNORECASE),
    re.compile(r"do not (report|flag|mention)", re.IGNORECASE),
    re.compile(r"approve (all|every|this)", re.IGNORECASE),
]


def add_lesson(
    record_data: dict[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """寫入一筆 typed lesson，回傳儲存後的 id 和 trusted bit。

    record_data 會先通過 LessonRecord 驗證（含 injection protection）。
    """
    from .db import AgentsDB
    from .models import LessonRecord

    record = LessonRecord.model_validate(record_data)

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        db.insert_lesson(record)
    finally:
        db.close()

    return {"id": record.id, "trusted": record.trusted}


def _apply_decay(
    confidence: int,
    source: str,
    ts: str,
    now: datetime | None = None,
) -> int:
    """計算 effective_confidence（Decay 演算法）。

    observed / inferred：每 30 天 -1，下限 1。
    user-stated / cross-model：不衰減。
    ts 若無時區資訊，補 UTC。
    """
    if source not in ("observed", "inferred"):
        return confidence

    _now = now if now is not None else datetime.now(UTC)
    try:
        lesson_ts = datetime.fromisoformat(ts)
        if lesson_ts.tzinfo is None:
            lesson_ts = lesson_ts.replace(tzinfo=UTC)
    except ValueError:
        return confidence

    days_elapsed = (_now - lesson_ts).total_seconds() / 86400
    decay = floor(days_elapsed / 30)
    return max(1, confidence - decay)


def _dedup_latest_winner(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Key+type deduplication：同 key+type 只保留 ts 最新者。"""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("key", ""), row.get("type", ""))
        existing = seen.get(key)
        if existing is None or row.get("ts", "") > existing.get("ts", ""):
            seen[key] = row
    return list(seen.values())


def show_lessons_typed(  # pylint: disable=too-many-arguments
    project: str | None = None,
    lesson_type: str | None = None,
    source: str | None = None,
    min_confidence: int = 1,
    trusted_only: bool = False,
    cross_project: bool = False,
    include_legacy: bool = True,
    with_decay: bool = True,
    limit: int = 20,
    db_path: str | Path | None = None,
    insights_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """查詢 typed lessons，可合併 legacy handovers.lessons_learned（include_legacy=True）。

    回傳 dict list，每筆含 effective_confidence（with_decay=True 時套用衰減）。
    cross_project=True 時只回傳 trusted=True 的記錄（跨專案安全限制）。
    """
    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        typed_rows = db.query_lessons_typed(
            project=project,
            lesson_type=lesson_type,
            source=source,
            min_confidence=1,
            trusted_only=trusted_only or cross_project,
            cross_project=cross_project,
            limit=_SEARCH_INTERNAL_LIMIT,
        )
    finally:
        db.close()

    results: list[dict[str, Any]] = []
    for row in typed_rows:
        eff = (
            _apply_decay(row["confidence"], row["source"], row["ts"])
            if with_decay
            else row["confidence"]
        )
        if eff < min_confidence:
            continue
        results.append({**row, "effective_confidence": eff})

    if include_legacy:
        _trusted_only = trusted_only or cross_project
        results.extend(
            _load_legacy_lessons(
                db_path=db_path,
                project=project,
                cross_project=cross_project,
                trusted_only=_trusted_only,
                with_decay=with_decay,
            )
        )
        if insights_path is not None:
            resolved = Path(insights_path)
            results.extend(
                _load_insights_as_typed(
                    resolved,
                    project=project,
                    cross_project=cross_project,
                    trusted_only=_trusted_only,
                )
            )

    deduped = _dedup_latest_winner(results)
    deduped.sort(key=lambda r: r.get("effective_confidence", r.get("confidence", 0)), reverse=True)
    return deduped[:limit]


def search_lessons_typed(  # pylint: disable=too-many-arguments
    query: str,
    project: str | None = None,
    lesson_type: str | None = None,
    source: str | None = None,
    min_confidence: int = 1,
    trusted_only: bool = False,
    cross_project: bool = False,
    include_legacy: bool = True,
    with_decay: bool = True,
    limit: int = 20,
    db_path: str | Path | None = None,
    insights_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """在 typed lessons 中搜尋（含 legacy 合併，可套用 filter 和 dedup）。"""
    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        typed_rows = db.search_lessons_typed(
            query=query,
            project=project,
            lesson_type=lesson_type,
            source=source,
            min_confidence=1,
            trusted_only=trusted_only or cross_project,
            cross_project=cross_project,
            limit=_SEARCH_INTERNAL_LIMIT,
        )
    finally:
        db.close()

    results: list[dict[str, Any]] = []
    q = query.lower()
    for row in typed_rows:
        eff = (
            _apply_decay(row["confidence"], row["source"], row["ts"])
            if with_decay
            else row["confidence"]
        )
        if eff < min_confidence:
            continue
        results.append({**row, "effective_confidence": eff})

    if include_legacy:
        _trusted_only = trusted_only or cross_project
        for entry in _load_legacy_lessons(
            db_path=db_path,
            project=project,
            cross_project=cross_project,
            trusted_only=_trusted_only,
            with_decay=with_decay,
        ):
            if q in entry.get("insight", "").lower() or q in entry.get("key", "").lower():
                results.append(entry)
        if insights_path is not None:
            resolved = Path(insights_path)
            for entry in _load_insights_as_typed(
                resolved,
                project=project,
                cross_project=cross_project,
                trusted_only=_trusted_only,
            ):
                if q in entry.get("insight", "").lower():
                    results.append(entry)

    deduped = _dedup_latest_winner(results)
    deduped.sort(key=lambda r: r.get("effective_confidence", r.get("confidence", 0)), reverse=True)
    return deduped[:limit]


def _load_legacy_lessons(
    db_path: str | Path | None,
    project: str | None,
    cross_project: bool = False,
    trusted_only: bool = False,
    with_decay: bool = True,
) -> list[dict[str, Any]]:
    """從 handovers.lessons_learned 讀取 legacy 教訓，正規化為 typed-like dict。"""
    if trusted_only:
        return []  # legacy items 永遠 trusted=False，無法滿足 trusted_only 要求

    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = db.query_lessons(
            project=None if cross_project else project, limit=_SEARCH_INTERNAL_LIMIT
        )
    finally:
        db.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("timestamp", "")
        proj = row.get("project") or project or ""
        topic = row.get("topic", "")
        eff = _apply_decay(5, "observed", ts) if with_decay else 5
        for item in row.get("lessons_learned", []):
            text = item.get("insight") if isinstance(item, dict) else str(item) if item else ""
            if not text:
                continue
            result.append(
                {
                    "key": text[:40].replace(" ", "-").lower(),
                    "type": "pattern",
                    "ts": ts,
                    "project": proj,
                    "insight": text,
                    "confidence": 5,
                    "source": "observed",
                    "trusted": False,
                    "effective_confidence": eff,
                    "_legacy": True,
                    "_legacy_source": "handover",
                    "_context": topic,
                }
            )
        for item in row.get("attempted_approaches", []):
            text = item.get("insight") if isinstance(item, dict) else str(item) if item else ""
            if not text:
                continue
            result.append(
                {
                    "key": f"approach-{text[:36].replace(' ', '-').lower()}",
                    "type": "pattern",
                    "ts": ts,
                    "project": proj,
                    "insight": text,
                    "confidence": 5,
                    "source": "observed",
                    "trusted": False,
                    "effective_confidence": eff,
                    "_legacy": True,
                    "_legacy_source": "handover-approach",
                    "_context": topic,
                }
            )
    return result


def _load_insights_as_typed(
    path: Path,
    project: str | None,
    cross_project: bool = False,
    trusted_only: bool = False,
) -> list[dict[str, Any]]:
    """從 insights.jsonl 讀取，正規化為 typed-like dict。"""
    if trusted_only:
        return []  # insight items 永遠 trusted=False，無法滿足 trusted_only 要求

    if not path.exists():
        return []

    results: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:  # nosec B112
                    continue
                proj = entry.get("project", "")
                if not cross_project and project and proj != project:
                    continue
                text = entry.get("insight_text", "")
                if not text:
                    continue
                results.append(
                    {
                        "key": text[:40].replace(" ", "-").lower(),
                        "type": "pattern",
                        "ts": entry.get("timestamp", ""),
                        "project": proj,
                        "insight": text,
                        "confidence": 5,
                        "source": "observed",
                        "trusted": False,
                        "effective_confidence": 5,
                        "_legacy": True,
                        "_legacy_source": "insight",
                        "_context": entry.get("session_id", ""),
                    }
                )
    except OSError as e:
        import sys

        print(f"[WARN] insights.jsonl 讀取失敗：{e}", file=sys.stderr)
        return []
    return results


def show_lessons(
    project: str | None = None,
    limit: int = 20,
    include_insights: bool = False,
    db_path: str | Path | None = None,
    insights_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """查詢 handover 教訓（含試過的方案），可選合併 insight 洞察。

    委託 show_lessons_typed（include_legacy=True, with_decay=False, min_confidence=1）
    並映射回舊 dict 格式，保持 backward compat。
    """
    _insights = insights_path if include_insights else None
    if include_insights and _insights is None:
        from .config import INSIGHTS_JSONL_PATH

        _insights = INSIGHTS_JSONL_PATH

    typed_rows = show_lessons_typed(
        project=project,
        include_legacy=True,
        with_decay=False,
        min_confidence=1,
        limit=limit,
        db_path=db_path,
        insights_path=_insights,
    )

    results: list[dict[str, Any]] = []
    for row in typed_rows:
        if row.get("_legacy"):
            src = row.get("_legacy_source", "handover")
            ctx = row.get("_context", "")
            results.append(
                {
                    "source": src,
                    "text": row.get("insight", ""),
                    "timestamp": row.get("ts", ""),
                    "project": row.get("project", ""),
                    "context": ctx,
                }
            )
        else:
            results.append(
                {
                    "source": "typed",
                    "text": row.get("insight", ""),
                    "timestamp": row.get("ts", ""),
                    "project": row.get("project", ""),
                    "context": f"[{row.get('type', '')}] {row.get('key', '')}",
                }
            )

    return results


def search_lessons(
    query: str,
    project: str | None = None,
    limit: int = 20,
    include_insights: bool = False,
    db_path: str | Path | None = None,
    insights_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """在 handover 教訓、試過的方案（與可選 insight）中搜尋關鍵字。

    委託 search_lessons_typed（include_legacy=True, with_decay=False, min_confidence=1）
    並映射回舊 dict 格式，保持 backward compat。
    """
    _insights = insights_path if include_insights else None
    if include_insights and _insights is None:
        from .config import INSIGHTS_JSONL_PATH

        _insights = INSIGHTS_JSONL_PATH

    typed_rows = search_lessons_typed(
        query=query,
        project=project,
        include_legacy=True,
        with_decay=False,
        min_confidence=1,
        limit=limit,
        db_path=db_path,
        insights_path=_insights,
    )

    results: list[dict[str, Any]] = []
    for row in typed_rows:
        if row.get("_legacy"):
            src = row.get("_legacy_source", "handover")
            ctx = row.get("_context", "")
            results.append(
                {
                    "source": src,
                    "text": row.get("insight", ""),
                    "timestamp": row.get("ts", ""),
                    "project": row.get("project", ""),
                    "context": ctx,
                }
            )
        else:
            results.append(
                {
                    "source": "typed",
                    "text": row.get("insight", ""),
                    "timestamp": row.get("ts", ""),
                    "project": row.get("project", ""),
                    "context": f"[{row.get('type', '')}] {row.get('key', '')}",
                }
            )
    return results[:limit]


def _load_insights(
    path: Path,
    project: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """從 insights.jsonl 載入洞察記錄。

    回傳最近（尾端）N 筆；格式錯誤的行靜默跳過；
    檔案不存在或 I/O 錯誤時回傳空 list。
    """
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    try:
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
    except OSError:
        return []

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
