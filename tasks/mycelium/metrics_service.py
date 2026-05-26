"""Auto-Handover 成功率量測：事件記錄、統計、rule-based 建議。

Phase 1（shadow logging）：hook 與 `write_handover()` 在關鍵時點呼叫 `log_event()`，
所有寫入失敗一律 swallow 成 warning，不影響主邏輯。

事件流分類見 `EventType`。成功率計算見 `AgentsDB.aggregate_success_counts`。
"""

from __future__ import annotations

import json
import uuid
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import HANDOVER_DB_PATH, HANDOVER_EVENTS_JSONL_PATH
from .db import AgentsDB
from .models import EventType, HandoverEvent, MetricsReport, SourceLayer


def log_event(
    event_type: EventType | str,
    *,
    session_id: str | None = None,
    source_layer: SourceLayer | str | None = None,
    matcher: str | None = None,
    handover_id: str | None = None,
    project: str | None = None,
    device: str | None = None,
    extra: dict[str, Any] | None = None,
    db_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> HandoverEvent | None:
    """寫入一筆事件；任何失敗 swallow 為 warning，回傳 None。

    Phase 1 契約：此函式絕不 raise，以免 hook / write_handover 主流程被影響。
    """
    try:
        etype = event_type if isinstance(event_type, EventType) else EventType(event_type)
        slayer: SourceLayer | None
        if source_layer is None:
            slayer = None
        elif isinstance(source_layer, SourceLayer):
            slayer = source_layer
        else:
            slayer = SourceLayer(source_layer)

        event = HandoverEvent(
            id=str(uuid.uuid4()),
            timestamp=_now_iso(),
            session_id=session_id,
            event_type=etype,
            source_layer=slayer,
            matcher=matcher,
            handover_id=handover_id,
            project=project,
            device=device,
            extra=extra or {},
        )
    except (ValueError, TypeError) as e:
        warnings.warn(f"log_event 建構失敗（event_type={event_type!r}）：{e}", stacklevel=2)
        return None

    db_success = False
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        db.insert_event(event)
        db_success = True
    except Exception as e:  # noqa: BLE001  shadow logging 不影響主流程
        warnings.warn(f"log_event DB 寫入失敗：{e}", stacklevel=2)
    finally:
        db.close()

    _append_jsonl(event, jsonl_path or HANDOVER_EVENTS_JSONL_PATH)
    return event if db_success else None


def list_events(
    last: int = 50,
    *,
    session_id: str | None = None,
    event_type: EventType | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """讀取最近 N 筆事件。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.read_events(last=last, session_id=session_id, event_type=event_type)
    finally:
        db.close()


def compute_stats(
    since: datetime | None = None,
    project: str | None = None,
    db_path: Path | None = None,
) -> MetricsReport:
    """計算 auto-handover 成功率報告。

    `since` 預設為 30 天前；`project` 過濾特定專案。
    session_id 為 NULL 的事件不列入聚合（見 SQL WHERE session_id IS NOT NULL）。
    """
    cutoff = since or (datetime.now(UTC) - timedelta(days=30))
    since_iso = cutoff.astimezone().replace(microsecond=0).isoformat()

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        counts = db.aggregate_success_counts(since=since_iso, project=project)
    finally:
        db.close()

    total_intercepts = counts["total_intercepts"]
    wrote = counts["wrote_after_intercept"]
    silent = counts["silent_fail"]
    hard = counts["hard_fail"]
    layer1 = counts["layer1_win"]
    stale = counts["stale_reset"]
    sessions = counts["sessions_observed"]

    def _rate(numer: int, denom: int) -> float:
        return round(numer / denom, 4) if denom else 0.0

    return MetricsReport(
        since=since_iso,
        project=project,
        total_intercepts=total_intercepts,
        wrote_after_intercept=wrote,
        silent_fail=silent,
        hard_fail=hard,
        layer1_win=layer1,
        stale_resets=stale,
        sessions_observed=sessions,
        success_rate=_rate(wrote + layer1, max(sessions, 1)),
        silent_fail_rate=_rate(silent, total_intercepts),
        hard_fail_rate=_rate(hard, sessions),
        layer1_win_rate=_rate(layer1, sessions),
    )


def generate_advice(report: MetricsReport) -> list[str]:
    """依 report 產生 rule-based 建議。樣本 < 5 時回傳「資料不足」。"""
    if report.sessions_observed < 5:
        return [
            f"樣本不足（sessions_observed={report.sessions_observed}），"
            "建議持續累積 ≥ 5 筆 session 後再檢視。"
        ]

    advice: list[str] = []

    if report.silent_fail_rate > 0.30:
        advice.append(
            f"Silent-fail 率 {report.silent_fail_rate:.0%} > 30%："
            "Layer 2 提醒被忽略偏高。建議 (a) 強化 .claude/rules/12-auto-handover.md 的指示語氣，"
            "(b) 把 pre-compact-handover.sh systemMessage 改為強制先回覆 y/n。"
        )

    if report.hard_fail_rate > 0.10:
        advice.append(
            f"Hard-fail 率 {report.hard_fail_rate:.0%} > 10%："
            "出現未 handover 就 compact 的 session。建議縮短狀態檔 TTL 從 1h 到 20min，"
            "或啟用 AUTO_HANDOVER_AGGRESSIVE=1（Layer 2 永遠 intercept 直到有 handover_written）。"
        )

    if report.layer1_win_rate > 0.50:
        advice.append(
            f"Layer 1 自估成功率 {report.layer1_win_rate:.0%} > 50%："
            "LLM 主動提醒表現良好，可考慮把 12-auto-handover.md 的 70% 閾值降到 60%，"
            "讓更多 session 在 Layer 2 介入前就完成。"
        )

    if report.layer1_win_rate < 0.10 and report.sessions_observed > 20:
        advice.append(
            f"Layer 1 自估成功率 {report.layer1_win_rate:.0%} < 10%"
            f"（樣本 {report.sessions_observed}）："
            "LLM 幾乎沒主動建議 handover。檢查 12-auto-handover.md 觸發條件是否過嚴。"
        )

    if report.total_intercepts and report.stale_resets > report.total_intercepts * 0.20:
        advice.append(
            f"狀態檔過期 {report.stale_resets} 次 > intercepts*20%："
            "TTL 1h 可能太短，建議調整為 3h 或改以 session_id 生命週期為界。"
        )

    if not advice:
        advice.append(f"目前成功率 {report.success_rate:.0%}，無明顯異常。繼續累積樣本追蹤即可。")

    return advice


def _append_jsonl(event: HandoverEvent, path: Path) -> None:
    """把 event 以單行 JSON 寫入 JSONL 檔案尾端。失敗時僅警告。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except (OSError, TypeError, ValueError) as e:
        warnings.warn(f"事件 JSONL 備份寫入失敗：{e}", stacklevel=2)


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()


def _try_resolve_session_id() -> str | None:
    """嘗試從 `/tmp/claude-handover-suggested-*` 狀態檔推斷當前 session_id。

    若僅有一個、mtime 在 30 分鐘內，視為當前 session；其餘情況回傳 None。
    由 `write_handover()` 於 CLI 無法取得 session_id 時呼叫。
    """
    tmp_dir = Path("/tmp")  # nosec B108 — hook 協定寫入此路徑，非此函式決定
    try:
        candidates = list(tmp_dir.glob("claude-handover-suggested-*"))
    except OSError:
        return None

    now = datetime.now(UTC).timestamp()
    fresh: list[tuple[float, str]] = []
    for p in candidates:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if now - mtime > 1800:  # 30 分鐘
            continue
        session_id = p.name.removeprefix("claude-handover-suggested-")
        if session_id and session_id != "default":
            fresh.append((mtime, session_id))

    if len(fresh) != 1:
        return None
    return fresh[0][1]
