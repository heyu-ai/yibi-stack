"""一次性遷移：把 ~/.handover/handover.db 與 ~/.claude/insight/insights.jsonl 搬到 ~/.agents/。

執行兩次應為冪等（靠 id 去重）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import HANDOVER_DB_PATH, HANDOVER_JSONL_PATH, INSIGHTS_JSONL_PATH
from .db import AgentsDB
from .models import HandoverRecord, SessionType

LEGACY_HANDOVER_DB = Path.home() / ".handover" / "handover.db"
LEGACY_INSIGHT_JSONL = Path.home() / ".claude" / "insight" / "insights.jsonl"

_HANDOVER_JSON_COLS = (
    "completed",
    "decisions",
    "blocked",
    "next_priorities",
    "lessons_learned",
    "attempted_approaches",
    "tags",
    "last_files",
)


@dataclass
class MigrationReport:
    handover_migrated: int
    handover_skipped: int
    handover_source: Path | None
    insight_migrated: int
    insight_skipped: int
    insight_source: Path | None


def migrate_all(
    handover_db_path: Path | None = None,
    handover_jsonl_path: Path | None = None,
    insight_jsonl_path: Path | None = None,
    legacy_handover: Path | None = None,
    legacy_insight: Path | None = None,
) -> MigrationReport:
    """搬遷 handover 與 insight 到新位置；回傳統計報告。"""
    h_report = migrate_handover(
        legacy_db=legacy_handover or LEGACY_HANDOVER_DB,
        new_db=handover_db_path or HANDOVER_DB_PATH,
        new_jsonl=handover_jsonl_path or HANDOVER_JSONL_PATH,
    )
    i_report = migrate_insights(
        legacy_jsonl=legacy_insight or LEGACY_INSIGHT_JSONL,
        new_jsonl=insight_jsonl_path or INSIGHTS_JSONL_PATH,
    )
    return MigrationReport(
        handover_migrated=h_report[0],
        handover_skipped=h_report[1],
        handover_source=h_report[2],
        insight_migrated=i_report[0],
        insight_skipped=i_report[1],
        insight_source=i_report[2],
    )


def migrate_handover(
    legacy_db: Path,
    new_db: Path,
    new_jsonl: Path,
) -> tuple[int, int, Path | None]:
    """把 legacy SQLite 的所有 row 搬到新 DB 與新 JSONL。回傳 (migrated, skipped, source)。"""
    if not legacy_db.exists():
        return 0, 0, None

    legacy_conn = sqlite3.connect(str(legacy_db))
    legacy_conn.row_factory = sqlite3.Row

    new = AgentsDB(new_db)
    try:
        new.init_db()

        migrated = 0
        skipped = 0
        existing_ids = {
            row["id"] for row in new.conn.execute("SELECT id FROM handovers").fetchall()
        }

        cur = legacy_conn.execute("SELECT * FROM handovers ORDER BY timestamp ASC")
        for row in cur.fetchall():
            record = _row_to_record(row)
            if record.id in existing_ids:
                skipped += 1
                continue
            new.insert_handover(record)
            _append_jsonl(record, new_jsonl)
            migrated += 1
    finally:
        legacy_conn.close()
        new.close()

    return migrated, skipped, legacy_db


def migrate_insights(
    legacy_jsonl: Path,
    new_jsonl: Path,
) -> tuple[int, int, Path | None]:
    """把 legacy JSONL append 到新 JSONL；以 id 去重。回傳 (migrated, skipped, source)。"""
    if not legacy_jsonl.exists():
        return 0, 0, None

    existing_ids: set[str] = set()
    if new_jsonl.exists():
        with new_jsonl.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rid := entry.get("id"):
                    existing_ids.add(rid)

    new_jsonl.parent.mkdir(parents=True, exist_ok=True)

    migrated = 0
    skipped = 0
    with (
        legacy_jsonl.open(encoding="utf-8") as f_in,
        new_jsonl.open("a", encoding="utf-8") as f_out,
    ):
        for line in f_in:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            rid = entry.get("id")
            if rid and rid in existing_ids:
                skipped += 1
                continue
            # 補上新 schema 的 account 欄位（舊資料預設 unknown）
            entry.setdefault("account", "unknown")
            f_out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if rid:
                existing_ids.add(rid)
            migrated += 1

    return migrated, skipped, legacy_jsonl


def _row_to_record(row: sqlite3.Row) -> HandoverRecord:
    """把 legacy SQLite row 轉成 HandoverRecord；JSON array 欄位先 decode。"""
    data = dict(row)
    for col in _HANDOVER_JSON_COLS:
        raw = data.get(col)
        if isinstance(raw, str):
            try:
                data[col] = json.loads(raw)
            except json.JSONDecodeError:
                data[col] = []
        elif raw is None:
            data[col] = []

    data.setdefault("project", None)

    # 收斂 session_type（舊資料理論上都是合法的四種）
    st = data.get("session_type") or "admin"
    try:
        data["session_type"] = SessionType(st)
    except ValueError:
        data["session_type"] = SessionType.admin

    return HandoverRecord.model_validate(data)


def _append_jsonl(record: HandoverRecord, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")


def ensure_tag_index(db_path: Path | None = None) -> bool:
    """確保 handovers.tags 欄位的 SQLite index 存在。

    schema v1.1 新增：tags 全文 LIKE 查詢在大型 DB（>10k 筆）下沒有 index 會全表掃描。
    此函式作為 migration step，已存在時為 no-op（冪等）。

    Args:
        db_path: 覆寫預設 DB 路徑（測試用）。

    Returns:
        True 表示 index 已存在或成功建立；False 表示 DB 不存在（跳過）。
    """
    from .config import HANDOVER_DB_PATH as _DEFAULT_DB_PATH

    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        return False

    conn = None
    try:
        conn = __import__("sqlite3").connect(str(path))
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_handovers_tags_fts ON handovers(tags)"
        )
        conn.commit()
        return True
    finally:
        if conn:
            conn.close()


def rebuild_tags_index(db_path: Path | None = None) -> dict[str, int]:
    """重建 tags LIKE 統計快取（用於 CLI tags stats 加速）。

    掃描所有 handover 記錄，計算各 tag 的使用頻率，寫入
    ~/.agents/_cache/tags_index.json。

    Args:
        db_path: 覆寫預設 DB 路徑（測試用）。

    Returns:
        tag -> count 的 dict，按 count 降序排列。
    """
    import json as _json

    from .config import AGENTS_HOME
    from .db import AgentsDB

    db = AgentsDB(db_path)
    try:
        db.init_db()
        tag_rows = db.get_tag_usage()
    finally:
        db.close()

    index = {row["tag"]: row["count"] for row in tag_rows}

    cache_dir = AGENTS_HOME / "_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "tags_index.json"
    cache_path.write_text(
        _json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index
