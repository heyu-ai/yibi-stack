"""Handover 寫入 / 讀取 / 搜尋服務。

自動填入 metadata（device / account / project / branch），同步鏡像到 JSONL。
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import uuid
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .account import (
    detect_account,
    detect_agent_type,
    detect_branch,
    detect_device,
    detect_project,
)
from .config import (
    HANDOVER_DB_PATH,
    HANDOVER_JSONL_PATH,
    from_portable_path,
    to_portable_path,
)
from .db import AgentsDB
from .models import HandoverRecord, SessionType


class HandoverBackupError(RuntimeError):
    """Canonical DB commit succeeded, but its JSONL backup could not be written."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.event_error: Exception | None = None
        self.event_warnings: list[warnings.WarningMessage] = []


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

    # 統一有效工作目錄，確保 working_dir、project、branch 來自同一 caller context。
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
        branch=branch if branch is not None else detect_branch(effective_dir),
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

    event_error, event_warnings = _emit_handover_written_event(record, db_path=db_path)
    try:
        _append_jsonl(record, jsonl_path or HANDOVER_JSONL_PATH)
    except HandoverBackupError as e:
        e.event_error = event_error
        e.event_warnings = event_warnings
        raise
    if event_error is not None:
        warnings.warn(f"handover_written 事件寫入失敗：{event_error}", stacklevel=2)
    for w in event_warnings:
        warnings.warn_explicit(
            message=w.message,
            category=w.category,
            filename=w.filename,
            lineno=w.lineno,
            source=w.source,
        )
    return record


def _emit_handover_written_event(
    record: HandoverRecord, *, db_path: Path | None
) -> tuple[Exception | None, list[warnings.WarningMessage]]:
    """嘗試寫入 handover_written 事件；捕捉異常與 warnings 供 caller 決定何時揭露。"""

    from .metrics_service import _try_resolve_session_id, log_event
    from .models import EventType, SourceLayer

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        err: Exception | None = None
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
            err = e
        return err, list(captured)


def read_recent(
    last: int = 4,
    *,
    project: str | None = None,
    exclude_tags: list[str] | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """讀取最近 N 筆，可選依 project 過濾，可排除含指定 tag 的記錄。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return [
            _expand_paths(row)
            for row in db.read_recent(last, project=project, exclude_tags=exclude_tags)
        ]
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
    """把 record 以單行 JSON 寫入 JSONL 備份尾端。

    DB 已由呼叫端提交；備份失敗仍須 raise，並在訊息中明示 DB 資料已保存。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        raise HandoverBackupError("DB 資料已保存，但 JSONL 備份寫入失敗") from e


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Language normalization (one-time maintenance)
# Scope: Traditional Chinese (CJK Unified Ideographs basic block U+4E00-U+9FFF).
# Hiragana / Katakana / Hangul are not targeted -- issue #206 scope is zh-TW only.
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[一-鿿]")

_TEXT_FIELDS = ("topic", "conversation_summary")
# tags / last_files intentionally excluded: metadata fields, not translatable prose.
_JSON_ARRAY_FIELDS = (
    "completed",
    "decisions",
    "blocked",
    "next_priorities",
    "lessons_learned",
    "attempted_approaches",
)

_ITEM_RE = re.compile(r'<item\s+index="(\d+)">(.*?)</item>', re.DOTALL)


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _record_has_cjk(row: dict[str, Any]) -> bool:
    return bool(_collect_cjk_texts(row))


def _xml_escape(text: str) -> str:
    """Escape XML special characters in user text before embedding in prompt."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_unescape(text: str) -> str:
    """Reverse _xml_escape: restore &amp; &lt; &gt; to their original characters."""
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def audit_handover_language(*, db_path: Path | None = None) -> dict[str, Any]:
    """Audit handover records for CJK content. Returns statistics dict."""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        rows = db.fetch_all_handovers()
    finally:
        db.close()

    total = len(rows)
    cjk_count = sum(1 for r in rows if _record_has_cjk(r))

    field_stats: dict[str, int] = {}
    for f in (*_TEXT_FIELDS, *_JSON_ARRAY_FIELDS):
        if f in _TEXT_FIELDS:
            field_stats[f] = sum(1 for r in rows if _has_cjk(r.get(f) or ""))
        else:
            field_stats[f] = sum(
                1
                for r in rows
                if isinstance(r.get(f), list) and any(_has_cjk(str(i)) for i in r[f])
            )

    return {
        "total": total,
        "cjk_count": cjk_count,
        "field_stats": field_stats,
    }


def _translate_batch(texts: list[str]) -> list[str]:
    """Translate a list of Chinese texts to English using the Anthropic API.

    Raises RuntimeError if the API response is missing items or truncated.
    """
    try:
        from anthropic import Anthropic  # pylint: disable=import-error
    except ImportError as exc:
        raise RuntimeError("anthropic SDK 未安裝。請執行：uv sync --extra ledger") from exc

    if not texts:
        return []

    client = Anthropic()
    prompt_parts = []
    for i, t in enumerate(texts):
        prompt_parts.append(f'<item index="{i}">{_xml_escape(t)}</item>')
    items_xml = "\n".join(prompt_parts)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": (
                    "Translate each <item> from Traditional Chinese to English. "
                    "Preserve technical identifiers (file paths, CLI flags, class names, "
                    "variable names, PR numbers, issue numbers, branch names) verbatim. "
                    "Keep the translation concise — same register as a developer handover note. "
                    'Return each translation inside <item index="N">...</item> tags, '
                    "matching the input indices exactly. "
                    "Do not add explanations outside the tags.\n\n"
                    f"{items_xml}"
                ),
            }
        ],
    )

    first_block = response.content[0]
    result_text: str = first_block.text if hasattr(first_block, "text") else str(first_block)

    if hasattr(response, "stop_reason") and response.stop_reason == "max_tokens":
        raise RuntimeError(f"API 回應被截斷（max_tokens）：預期 {len(texts)} 個項目")

    translated: dict[int, str] = {}
    for m in _ITEM_RE.finditer(result_text):
        translated[int(m.group(1))] = _xml_unescape(m.group(2).strip())

    missing = [i for i in range(len(texts)) if i not in translated]
    if missing:
        raise RuntimeError(
            f"API 回應缺少 {len(missing)}/{len(texts)} 個翻譯項目（缺少索引：{missing[:10]}）"
        )

    return [translated[i] for i in range(len(texts))]


def _collect_cjk_texts(row: dict[str, Any]) -> list[tuple[str, int | None, str]]:
    """Collect all CJK text segments from a handover row.

    Returns list of (field_name, array_index_or_None, text).
    """
    result: list[tuple[str, int | None, str]] = []
    for f in _TEXT_FIELDS:
        val = row.get(f) or ""
        if _has_cjk(val):
            result.append((f, None, val))
    for f in _JSON_ARRAY_FIELDS:
        items = row.get(f)
        if isinstance(items, list):
            for idx, item in enumerate(items):
                s = str(item)
                if _has_cjk(s):
                    result.append((f, idx, s))
    return result


def _apply_translations(
    row: dict[str, Any],
    segments: list[tuple[str, int | None, str]],
    translated: list[str],
) -> dict[str, str | list[str]]:
    """Build an updates dict from translated segments."""
    updates: dict[str, str | list[str]] = {}
    arr_copies: dict[str, list[str]] = {}

    for (field, arr_idx, _orig), new_text in zip(segments, translated, strict=True):
        if arr_idx is None:
            updates[field] = new_text
        else:
            if field not in arr_copies:
                arr_copies[field] = list(row.get(field) or [])
            arr_copies[field][arr_idx] = new_text

    for f, arr in arr_copies.items():
        updates[f] = arr

    return updates


def normalize_handover_language(
    *,
    dry_run: bool = True,
    batch_size: int = 20,
    db_path: Path | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Normalize CJK handover records to English.

    Translates in batches of ``batch_size`` rows. Each batch collects all CJK
    text segments, translates them in a single API call, then applies updates.

    Returns a summary dict with counts and sample changes.
    """
    effective_db = db_path or HANDOVER_DB_PATH
    db = AgentsDB(effective_db)
    try:
        db.init_db()
        rows = db.fetch_all_handovers()
    finally:
        db.close()

    cjk_rows = [r for r in rows if _record_has_cjk(r)]
    if not cjk_rows:
        return {
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "total_cjk": 0,
            "dry_run": dry_run,
            "samples": [],
        }

    processed = 0
    skipped = 0
    failed = 0
    samples: list[dict[str, Any]] = []
    errors: list[str] = []

    db2 = AgentsDB(effective_db)
    try:
        db2.init_db()
        for batch_start in range(0, len(cjk_rows), batch_size):
            batch = cjk_rows[batch_start : batch_start + batch_size]

            all_texts: list[str] = []
            row_segments: list[list[tuple[str, int | None, str]]] = []
            for row in batch:
                segs = _collect_cjk_texts(row)
                row_segments.append(segs)
                all_texts.extend(t for _, _, t in segs)

            if not all_texts:
                skipped += len(batch)
                if progress_callback:
                    progress_callback(batch_start + len(batch), len(cjk_rows))
                continue

            try:
                translated = _translate_batch(all_texts)
            except RuntimeError as exc:
                failed += len(batch)
                errors.append(f"batch {batch_start}: {exc}")
                if progress_callback:
                    progress_callback(batch_start + len(batch), len(cjk_rows))
                continue

            offset = 0
            for row, segs in zip(batch, row_segments, strict=True):
                n = len(segs)
                row_translated = translated[offset : offset + n]
                offset += n

                updates = _apply_translations(row, segs, row_translated)
                if updates:
                    if len(samples) < 5:
                        sample: dict[str, Any] = {
                            "id": row["id"][:8],
                            "changes": {},
                        }
                        for k, v in updates.items():
                            orig = row.get(k)
                            sample["changes"][k] = {
                                "from": str(orig)[:60] if orig else "",
                                "to": str(v)[:60],
                            }
                        samples.append(sample)

                    if not dry_run:
                        db2.update_handover_text_fields(row["id"], updates)
                    processed += 1
                else:
                    skipped += 1

            if progress_callback:
                progress_callback(batch_start + len(batch), len(cjk_rows))
    finally:
        db2.close()

    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total_cjk": len(cjk_rows),
        "dry_run": dry_run,
        "samples": samples,
        "errors": errors,
    }
