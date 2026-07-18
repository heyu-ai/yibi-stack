"""教訓聯合查詢 service：整合 handover lessons_learned、attempted_approaches 與 insight 洞察。"""

from __future__ import annotations

import importlib.util
import json
import re
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from math import floor
from pathlib import Path
from typing import Any

# search_lessons 內部查詢上限：用 query_lessons 載入所有含教訓的記錄再 Python 過濾，
# 確保 limit 語意為「回傳教訓條目數」而非「掃描 handover 記錄數」
_SEARCH_INTERNAL_LIMIT = 500


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


def get_lesson(
    lesson_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """依 id 取回單筆 typed lesson（含 retired）；找不到時回傳 None。"""
    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        return db.get_lesson(lesson_id)
    finally:
        db.close()


def delete_lesson(
    lesson_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """刪除單筆 lesson（誤寫修正用），先寫 tombstone 保留 audit trail。

    回傳含被刪除 row 與剩餘筆數的 dict：{"deleted": <row>, "remaining": <int>}。
    找不到 id 時 raise RuntimeError（fail loud，避免靜默 no-op）。
    """
    if not lesson_id or not lesson_id.strip():
        raise ValueError("lesson_id 不可為空")

    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        deleted = db.delete_lesson(lesson_id, datetime.now(UTC))
        if deleted is None:
            raise RuntimeError(f"找不到 id={lesson_id} 的教訓，未刪除任何記錄")
        remaining = db.count_lessons()
    finally:
        db.close()

    return {"deleted": deleted, "remaining": remaining}


def retire_lesson(
    lesson_id: str,
    reason: str,
    superseded_by: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """標記單筆 lesson 為 retired（教訓過期用，保留內容但退出流通）。

    reason 必填且非空（「這條為什麼被推翻」本身常是下一條教訓）。
    回傳更新後的 row；找不到 id 時 raise RuntimeError（fail loud）。
    """
    if not lesson_id or not lesson_id.strip():
        raise ValueError("lesson_id 不可為空")
    if not reason or not reason.strip():
        raise ValueError("retire 必須提供 --reason 說明為何退場")

    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        updated = db.retire_lesson(lesson_id, reason, superseded_by, datetime.now(UTC))
        if updated is None:
            raise RuntimeError(f"找不到 id={lesson_id} 的教訓，未標記任何記錄")
    finally:
        db.close()

    return updated


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
    include_retired: bool = False,
) -> list[dict[str, Any]]:
    """查詢 typed lessons，可合併 legacy handovers.lessons_learned（include_legacy=True）。

    回傳 dict list，每筆含 effective_confidence（with_decay=True 時套用衰減）。
    cross_project=True 時只回傳 trusted=True 的記錄（跨專案安全限制）。
    include_retired=False（預設）時排除已 retire 的 typed 教訓。
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
            include_retired=include_retired,
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
        for entry in _load_legacy_lessons(
            db_path=db_path,
            project=project,
            cross_project=cross_project,
            trusted_only=_trusted_only,
            with_decay=with_decay,
        ):
            if lesson_type and entry.get("type") != lesson_type:
                continue
            if source and entry.get("source") != source:
                continue
            if entry.get("effective_confidence", entry.get("confidence", 0)) < min_confidence:
                continue
            results.append(entry)
        if insights_path is not None:
            resolved = Path(insights_path)
            for entry in _load_insights_as_typed(
                resolved,
                project=project,
                cross_project=cross_project,
                trusted_only=_trusted_only,
            ):
                if lesson_type and entry.get("type") != lesson_type:
                    continue
                if source and entry.get("source") != source:
                    continue
                if entry.get("effective_confidence", entry.get("confidence", 0)) < min_confidence:
                    continue
                results.append(entry)

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
    include_retired: bool = False,
) -> list[dict[str, Any]]:
    """在 typed lessons 中搜尋（含 legacy 合併，可套用 filter 和 dedup）。

    include_retired=False（預設）時排除已 retire 的 typed 教訓。
    """
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
            include_retired=include_retired,
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
            if lesson_type and entry.get("type") != lesson_type:
                continue
            if source and entry.get("source") != source:
                continue
            if entry.get("effective_confidence", entry.get("confidence", 0)) < min_confidence:
                continue
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
                if lesson_type and entry.get("type") != lesson_type:
                    continue
                if source and entry.get("source") != source:
                    continue
                if entry.get("effective_confidence", entry.get("confidence", 0)) < min_confidence:
                    continue
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

    import sys

    from .db import AgentsDB

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = db.query_lessons(
            project=None if cross_project else project, limit=_SEARCH_INTERNAL_LIMIT
        )
    except Exception as e:
        print(f"[WARN] legacy handover DB 讀取失敗：{e}", file=sys.stderr)
        return []
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
                    "key": f"legacy-{text[:34].replace(' ', '-').lower()}",
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
                    "key": f"legacy-approach-{text[:29].replace(' ', '-').lower()}",
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

    回傳 dict 的 source 欄位值域：
    "handover"、"handover-approach"（legacy）、"insight"、"typed"（typed lessons table）。
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


def save_lesson(
    content: str,
    tier: str = "working",
    tags: list[str] | None = None,
    source_bot: str | None = None,
    lesson_type: str = "pattern",
    project: str | None = None,
    confidence: int = 7,
    db_path: str | Path | None = None,
) -> dict[str, str]:
    """儲存一筆 lesson，自動產生 key 與 project（若未提供）。

    `content` 對應 LessonRecord.insight。
    """
    import uuid

    from .db import AgentsDB
    from .models import LessonRecord, LessonSource, LessonType
    from .registry import resolve_project_slug

    if project is None:
        project = resolve_project_slug(Path.cwd()) or "unknown"

    # Auto-generate key from first 40 chars of content, kebab-case
    raw_key = re.sub(r"[^a-zA-Z0-9]+", "-", content[:40]).strip("-").lower()
    if not raw_key:
        raw_key = "lesson"
    key = raw_key[:40] + "-" + str(uuid.uuid4())[:8]

    if lesson_type in LessonType.__members__:
        lesson_type_enum = LessonType(lesson_type)
    else:
        lesson_type_enum = LessonType.pattern

    record = LessonRecord(
        project=project,
        type=lesson_type_enum,
        key=key,
        insight=content,
        confidence=confidence,
        source=LessonSource.observed,
        source_bot=source_bot,
        tags=tags or [],
        tier=tier,
    )

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        db.insert_lesson(record)
    finally:
        db.close()

    return {"id": record.id, "trusted": str(record.trusted)}


def get_lessons(
    project: str | None = None,
    limit: int = 20,
    tier_filter: list[str] | None = None,
    lesson_type: str | None = None,
    include_cold: bool = False,
    include_archived: bool = False,
    token_budget: int = 0,
    mode: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """查詢 typed lessons，回傳 effective_weight 降序清單。

    project=None 回傳所有 project 的 lesson。
    tier_filter 指定允許的 tier 清單（如 ["hot"]）；None 表示 working+hot
    （除非 include_cold/archived）。
    include_cold=True 包含 cold tier；include_archived=True 包含 archival tier。
    token_budget > 0 時以 tiktoken cl100k_base 估算累計 token，超過 budget 就停止。
    mode 對映 lesson_type filter：episodic/semantic/procedural。
    """
    from .db import AgentsDB, compute_effective_weight

    # Build effective tier filter
    if tier_filter is not None:
        effective_tiers = set(tier_filter)
    else:
        effective_tiers = {"working", "hot"}
        if include_cold:
            effective_tiers.add("cold")
        if include_archived:
            effective_tiers.add("archival")

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = db.query_lessons_typed(
            project=project,
            lesson_type=lesson_type,
            limit=limit * 4,  # over-fetch before tier filter
        )
    finally:
        db.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        row_tier = row.get("tier", "working")
        if row_tier not in effective_tiers:
            continue
        eff = _apply_decay(row["confidence"], row["source"], row["ts"])
        results.append({**row, "effective_confidence": eff})

    import os
    from datetime import UTC, datetime

    from .models import LessonRecord, LessonSource, LessonType
    from .trust_scoring import compute_bot_trust_weight

    now = datetime.now(UTC)
    querying_agent = os.environ.get("AGENT_TYPE", "claude")

    accessed_ids: list[str] = []
    for r in results:
        try:
            lesson = LessonRecord(
                project=r.get("project", "unknown"),
                type=LessonType(r.get("type", "pattern")),
                key=r.get("key", "k"),
                insight=r.get("insight", "x" * 10),
                confidence=int(r.get("confidence", 5)),
                source=LessonSource(r.get("source", "observed")),
                access_count=int(r.get("access_count", 0)),
                last_accessed_at=r.get("last_accessed_at"),
                ts=r.get("ts", now.isoformat()),
                source_bot=r.get("source_bot"),
            )
            trust_w = compute_bot_trust_weight(lesson, querying_agent, [])
            r["effective_weight"] = compute_effective_weight(lesson, now, trust_w)
        except Exception as e:
            import sys as _sys

            print(f"[mycelium] lesson id={r.get('id', '?')} weight 計算失敗：{e}", file=_sys.stderr)
            r["effective_weight"] = float(r.get("effective_confidence", r.get("confidence", 0)))
        accessed_ids.append(str(r.get("id", "")))

    results.sort(key=lambda r: r.get("effective_weight", 0.0), reverse=True)

    # Mode filter: map mode to lesson_type values
    if mode is not None:
        _MODE_MAP: dict[str, list[str]] = {
            "episodic": ["pitfall", "investigation"],
            "semantic": ["pattern", "architecture", "investigation"],
            "procedural": ["tool", "operational", "preference"],
        }
        allowed_types = _MODE_MAP.get(mode)
        if allowed_types is None:
            raise ValueError(f"mode 必須為 episodic / semantic / procedural，收到：{mode!r}")
        results = [r for r in results if r.get("type") in allowed_types]

    # Token budget filtering
    if token_budget > 0:
        final = _apply_token_budget(results, token_budget, limit)
    else:
        final = results[:limit]

    # Increment access_count for returned lessons (best-effort; does not block return)
    returned_ids = [str(r.get("id", "")) for r in final if r.get("id")]
    if returned_ids:
        try:
            _db = AgentsDB(db_path=db_path)
            _db.init_db()
            _db.increment_access_count(returned_ids, now)
            _db.close()
        except Exception as _e:
            import sys as _sys

            print(f"[mycelium] access_count update 失敗：{_e}", file=_sys.stderr)

    return final


_TOKEN_BUDGET_ENCODING = "cl100k_base"  # nosec B105


def _rough_token_count(text: str) -> int:
    """粗估：1 token 約 4 字元。tiktoken 不可用時的退路。"""
    return len(text) // 4


@lru_cache(maxsize=1)
def _make_token_counter() -> Callable[[str], int]:
    """回傳 token 計數函式；tiktoken 不可用時退化為粗估。

    **為何用 find_spec 而非靠 exception 型別分流**：`except ImportError` 會同時涵蓋兩個
    語意完全不同的情況——(a) 沒裝 tokens extra（預期，不該吵）、(b) 裝了但它自己的
    transitive dep 壞掉（例如 `regex` 缺失），或 `get_encoding()` 內部 import
    `tiktoken_ext` plugin 失敗。(b) 正是本函式的警告要服務的對象，卻會被 (a) 的靜默分支
    吃掉。find_spec 直接問「裝了沒」，讓兩者不再共用一個 except。

    **為何 lru_cache**：本函式在每次 `_apply_token_budget` 呼叫（即每次帶 token_budget 的
    查詢）都會執行。`get_encoding()` 在冷快取時會向 openaipublic.blob.core.windows.net 下載
    BPE vocab；離線時每次都要等它逾時（實測約 30 秒）。不快取的話，降級結果本身不被記住，
    於是**每次查詢都重新卡一次**。maxsize=1 是因為本函式無參數。

    PR #249 之前 tiktoken 從未被宣告為依賴，故 len/4 是唯一跑過的路徑；該 PR 新增
    `tokens` extra 後 tiktoken 分支首次可達，這些失敗模式也隨之從理論變成活的。
    """
    try:
        installed = importlib.util.find_spec("tiktoken") is not None
    except Exception as e:  # find_spec 自己會拋：__spec__ is None -> ValueError；
        # meta-path finder 的例外也會傳播（兩者皆實測確認）。探測失敗不是「沒裝」，
        # 是異常狀態——降級但要吵，否則這個 best-effort 估算會把例外往外拋。
        warnings.warn(
            f"tiktoken 探測失敗（{type(e).__name__}: {e}），token 預算改用 len/4 粗估。",
            UserWarning,
            stacklevel=2,
        )
        return _rough_token_count

    if not installed:
        # 未安裝 tokens extra：預期情形，非異常，不發警告。
        return _rough_token_count

    # 走到這裡代表 tiktoken 已安裝，故任何失敗都是「裝了卻不能用」——必須讓使用者知道，
    # 否則付錢裝了 --extra tokens 的人會拿到粗估卻不知為何。
    try:
        # tiktoken 是 optional extra，CI 的 `uv sync --all-groups` 刻意不裝它（--all-groups
        # 只裝 dependency-groups；extras 要 --all-extras），故 pylint 的 import-error 是環境
        # 事實而非缺陷。用 inline 而非 [tool.pylint.main].ignored-modules：後者是 repo-wide，
        # 實測會連 member 檢查一起關掉（`tiktoken.get_encodig` 這種 typo 不再被 E1101 抓到）。
        import tiktoken  # type: ignore[import-not-found]  # pylint: disable=import-error

        enc = tiktoken.get_encoding(_TOKEN_BUDGET_ENCODING)
    except Exception as e:  # 網路／HTTP／快取權限／損壞的 tiktoken_ext；一律退化而非中斷
        warnings.warn(
            f"tiktoken 已安裝但初始化失敗（{type(e).__name__}: {e}），token 預算改用 len/4 粗估。",
            UserWarning,
            stacklevel=2,
        )
        return _rough_token_count

    def count_tokens(text: str) -> int:
        return len(enc.encode(text))

    return count_tokens


def _apply_token_budget(
    rows: list[dict[str, Any]],
    budget: int,
    limit: int,
) -> list[dict[str, Any]]:
    """依 token budget 截斷 rows（tiktoken cl100k_base 估算；不可用時退化為 len/4 粗估）。"""
    count_tokens = _make_token_counter()

    result: list[dict[str, Any]] = []
    cumulative = 0
    for row in rows[:limit]:
        text = row.get("insight", "")
        tokens = count_tokens(text)
        if cumulative + tokens > budget:
            break
        cumulative += tokens
        result.append(row)
    return result
