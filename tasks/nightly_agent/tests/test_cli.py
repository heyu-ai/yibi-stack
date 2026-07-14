"""NIGHTLY-cli tests：_load_mycelium_lessons 的 schema 相容性。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from tasks.nightly_agent.cli import _load_mycelium_lessons

CLI = "tasks.nightly_agent.cli"


def make_handover_db(tmp_path: Path, *, with_retrospective_id: bool) -> Path:
    """建立測試用 handover.db；with_retrospective_id 控制是否模擬已 migrate 過的 schema。"""
    db_dir = tmp_path / ".agents" / "handover"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "handover.db"

    columns = [
        "id TEXT PRIMARY KEY",
        "ts TEXT NOT NULL",
        "project TEXT NOT NULL",
        "type TEXT NOT NULL",
        "key TEXT NOT NULL",
        "insight TEXT NOT NULL",
        "confidence INTEGER NOT NULL",
        "source TEXT NOT NULL",
        "handover_id TEXT",
    ]
    if with_retrospective_id:
        columns.append("retrospective_id TEXT")

    conn = sqlite3.connect(str(db_path))
    conn.execute(f"CREATE TABLE lessons ({', '.join(columns)})")
    insert_cols = ["id", "ts", "project", "type", "key", "insight", "confidence", "source"]
    values = [
        "'l1'",
        "datetime('now')",
        "'yibi-stack'",
        "'pitfall'",
        "'k1'",
        "'test insight'",
        "5",
        "'observed'",
    ]
    if with_retrospective_id:
        insert_cols.append("retrospective_id")
        values.append("'r1'")
    conn.execute(f"INSERT INTO lessons ({', '.join(insert_cols)}) VALUES ({', '.join(values)})")
    conn.commit()
    conn.close()
    return db_path


class TestLoadMyceliumLessons:
    def test_pre_migration_schema_falls_back_to_null_retrospective_id(self, tmp_path: Path) -> None:
        """舊 handover.db 沒有 retrospective_id 欄位時，讀取仍成功，欄位回傳 None。"""
        db_path = make_handover_db(tmp_path, with_retrospective_id=False)
        schema_before = (
            sqlite3.connect(str(db_path))
            .execute("SELECT sql FROM sqlite_master WHERE name='lessons'")
            .fetchone()[0]
        )

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        schema_after = (
            sqlite3.connect(str(db_path))
            .execute("SELECT sql FROM sqlite_master WHERE name='lessons'")
            .fetchone()[0]
        )

        assert errors == []
        assert len(result) == 1
        assert result[0]["retrospective_id"] is None
        assert schema_after == schema_before, "讀取路徑不應寫入 schema（唯讀）"

    def test_migrated_schema_returns_retrospective_id(self, tmp_path: Path) -> None:
        """已 migrate 過的 handover.db（有 retrospective_id 欄位）正常回傳該值。"""
        make_handover_db(tmp_path, with_retrospective_id=True)

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        assert errors == []
        assert len(result) == 1
        assert result[0]["retrospective_id"] == "r1"

    def test_missing_lessons_table_returns_empty_with_warning(self, tmp_path: Path) -> None:
        """handover.db 存在但沒有 lessons table（極舊版本）：回傳空清單，記錄錯誤而非拋出例外。"""
        db_dir = tmp_path / ".agents" / "handover"
        db_dir.mkdir(parents=True)
        db_path = db_dir / "handover.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handovers (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        assert result == []
        assert len(errors) == 1
        assert "no such table" in errors[0].lower()

    def test_missing_db_file_returns_empty_no_error(self, tmp_path: Path) -> None:
        """handover.db 檔案完全不存在（首次使用）：回傳空清單，不記錄錯誤。"""
        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        assert result == []
        assert errors == []
