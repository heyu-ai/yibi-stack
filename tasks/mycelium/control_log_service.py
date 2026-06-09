"""Control log service：寫入、讀取、統計與建議。"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import HANDOVER_DB_PATH
from .db import AgentsDB
from .models import ControlLogCategory, ControlLogEntry


def write_control_log(
    entry: ControlLogEntry,
    db_path: Path | None = None,
) -> int:
    """寫入一筆 control log entry，回傳新 id。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.insert_control_log_entry(entry)
    finally:
        db.close()


def read_control_log(
    pr_number: int,
    project: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """讀取指定 PR 的所有 control log entries。"""
    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        return db.query_control_log_entries(pr_number=pr_number, project=project)
    finally:
        db.close()


def compute_stats(
    since_days: int = 30,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """計算 control log 四個核心指標。

    Division by zero 回傳 None（非 0.0 或 NaN）。

    Returns:
        dict with keys: autonomy_ratio, deviation_ratio, irreversible_op_count,
                        verification_score, total_entries
    """
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    since_iso = cutoff.replace(microsecond=0).isoformat()

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        rows = db.query_control_log_entries(since_iso=since_iso, limit=None)
    finally:
        db.close()

    total = len(rows)
    autonomous_count = sum(
        1 for r in rows if r["category"] == ControlLogCategory.autonomous_decision
    )
    user_requested_count = sum(1 for r in rows if r["user_requested"] == 1)
    spec_deviation_count = sum(
        1 for r in rows if r["category"] == ControlLogCategory.spec_deviation
    )
    irreversible_count = sum(1 for r in rows if r["category"] == ControlLogCategory.irreversible_op)

    verification_entries = [
        r for r in rows if r.get("verification_status") in ("verified", "partial", "unverified")
    ]
    verified_count = sum(
        1 for r in verification_entries if r.get("verification_status") == "verified"
    )

    auto_denom = autonomous_count + user_requested_count
    autonomy_ratio: float | None = autonomous_count / auto_denom if auto_denom > 0 else None

    deviation_ratio: float | None = spec_deviation_count / total if total > 0 else None

    verif_denom = len(verification_entries)
    verification_score: float | None = verified_count / verif_denom if verif_denom > 0 else None

    return {
        "autonomy_ratio": autonomy_ratio,
        "deviation_ratio": deviation_ratio,
        "irreversible_op_count": irreversible_count,
        "verification_score": verification_score,
        "total_entries": total,
    }


def compute_grouped_stats(
    since_days: int = 30,
    by: str = "category",
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """計算按 category 或 project 分組的統計。

    Args:
        by: "category" 或 "project"

    Returns:
        list of dicts with keys: group (str), count (int)
    """
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    since_iso = cutoff.replace(microsecond=0).isoformat()

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        rows = db.query_control_log_entries(since_iso=since_iso, limit=None)
    finally:
        db.close()

    if by == "category":
        counts: Counter[str] = Counter(r["category"] for r in rows)
    else:
        counts = Counter(r.get("project") or "(none)" for r in rows)

    return [{"group": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def generate_advice(
    since_days: int = 30,
    db_path: Path | None = None,
) -> list[str]:
    """根據 control log 閾值產生 zh-TW 建議。

    < 3 筆時回傳資料不足提示；無觸發時回傳 ["目前無建議"]。
    """
    stats = compute_stats(since_days=since_days, db_path=db_path)
    total = stats["total_entries"]

    if total < 3:
        return [f"資料不足（共 {total} 筆），需累積至少 3 筆 entries 才能評估。"]

    advice: list[str] = []

    autonomy = stats["autonomy_ratio"]
    if autonomy is not None and autonomy > 0.30:
        advice.append(
            f"R1：AI 自主決定比例偏高（{autonomy:.0%}），考慮在 CLAUDE.md / rules 補充規範。"
        )

    deviation = stats["deviation_ratio"]
    if deviation is not None and deviation > 0.20:
        advice.append(
            f"R2：偏離規格比例偏高（{deviation:.0%}），建議在 propose 階段更明確標註 AC。"
        )

    if _check_r3(since_days=since_days, db_path=db_path):
        advice.append("R3：考慮新增 hook 阻擋此類操作（相同 irreversible_op 模式出現 >= 3 次）。")

    verification = stats["verification_score"]
    if verification is not None and verification < 0.60:
        advice.append(
            "R4：驗證強度不足"
            f"（{verification:.0%}），建議在 retro 加 verify-before-completion gate。"
        )

    return advice if advice else ["目前無建議"]


def _check_r3(since_days: int, db_path: Path | None) -> bool:
    """判斷是否有相同 irreversible_op summary 模式出現 >= 3 次。"""
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    since_iso = cutoff.replace(microsecond=0).isoformat()

    db = AgentsDB(db_path or HANDOVER_DB_PATH)
    try:
        db.init_db()
        rows = db.query_control_log_entries(since_iso=since_iso, limit=None)
    finally:
        db.close()

    irreversible_summaries = [
        _normalize_summary(r["summary"])
        for r in rows
        if r["category"] == ControlLogCategory.irreversible_op
    ]
    counts = Counter(irreversible_summaries)
    return any(v >= 3 for v in counts.values())


def _normalize_summary(summary: str) -> str:
    """正規化 summary 作為 R3 相似性判斷 key（去除標點、lowercase）。"""
    return re.sub(r"[^\w\s]", "", summary.lower()).strip()
