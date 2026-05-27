"""Lessons service 新 API（save_lesson + get_lessons）測試。"""

from __future__ import annotations

from pathlib import Path

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.lessons_service import get_lessons, save_lesson
from tasks.mycelium.models import LessonRecord, LessonSource, LessonType


def _make_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    db = AgentsDB(db_path=db_path)
    db.init_db()
    db.close()
    return db_path


class TestSaveLesson:
    def test_myc_svc_dt_001_tier_persisted(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-001: save_lesson(tier='hot') persists tier=hot in DB"""
        db_path = _make_db(tmp_path)
        result = save_lesson(
            content="Hot lesson content that exceeds ten characters.",
            tier="hot",
            db_path=db_path,
        )
        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.conn.execute(
            "SELECT tier FROM lessons WHERE id = ?", (result["id"],)
        ).fetchone()
        db.close()
        assert row["tier"] == "hot", "tier must be persisted, not silently dropped"

    def test_myc_svc_dt_002_working_tier_default(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-002: save_lesson() defaults to tier=working"""
        db_path = _make_db(tmp_path)
        result = save_lesson(
            content="Default tier lesson content that is long enough.",
            db_path=db_path,
        )
        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.conn.execute(
            "SELECT tier FROM lessons WHERE id = ?", (result["id"],)
        ).fetchone()
        db.close()
        assert row["tier"] == "working"

    def test_myc_svc_dt_003_tags_persisted(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-003: save_lesson(tags=[...]) persists tags"""
        import json

        db_path = _make_db(tmp_path)
        result = save_lesson(
            content="Tagged lesson content that is more than ten chars.",
            tags=["tag1", "tag2"],
            db_path=db_path,
        )
        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.conn.execute(
            "SELECT tags FROM lessons WHERE id = ?", (result["id"],)
        ).fetchone()
        db.close()
        tags = json.loads(row["tags"])
        assert "tag1" in tags
        assert "tag2" in tags


class TestGetLessons:
    def test_myc_svc_dt_004_tier_filter(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-004: get_lessons(tier_filter=['hot']) only returns hot lessons"""
        db_path = _make_db(tmp_path)
        # Save a working-tier lesson
        save_lesson(
            content="Working lesson content that is more than ten chars.",
            tier="working",
            db_path=db_path,
        )
        # Save a hot-tier lesson
        save_lesson(
            content="Hot lesson content that is more than ten chars here.",
            tier="hot",
            db_path=db_path,
        )
        rows = get_lessons(tier_filter=["hot"], db_path=db_path)
        assert all(r.get("tier") == "hot" for r in rows)
        assert len(rows) == 1

    def test_myc_svc_dt_005_token_budget_zero_is_unlimited(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-005: token_budget=0 behaves same as no budget"""
        db_path = _make_db(tmp_path)
        save_lesson(
            content="Token budget test lesson content that is long enough.",
            tier="working",
            db_path=db_path,
        )
        rows_budgeted = get_lessons(token_budget=0, db_path=db_path)
        rows_no_budget = get_lessons(db_path=db_path)
        assert len(rows_budgeted) == len(rows_no_budget)

    def test_myc_svc_dt_006_mode_episodic_returns_pitfall(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-006: mode='episodic' matches pitfall type (not invalid handover_summary)"""
        db = AgentsDB(db_path=str(tmp_path / "test.db"))
        db.init_db()
        record = LessonRecord(
            project="test",
            type=LessonType.pitfall,
            key="episodic-test",
            insight="Episodic pitfall lesson content long enough.",
            confidence=7,
            source=LessonSource.observed,
        )
        db.insert_lesson(record)
        db.close()

        rows = get_lessons(mode="episodic", db_path=str(tmp_path / "test.db"))
        assert len(rows) >= 1
        assert all(r.get("type") in ("pitfall", "investigation") for r in rows)

    def test_myc_svc_dt_007_invalid_mode_raises(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-007: get_lessons(mode='invalid') raises ValueError"""
        import pytest

        db_path = _make_db(tmp_path)
        with pytest.raises(ValueError, match="mode 必須為"):
            get_lessons(mode="invalid", db_path=db_path)

    def test_myc_svc_dt_008_access_count_incremented(self, tmp_path: Path) -> None:
        """MYC-SVC-DT-008: get_lessons() increments access_count for returned rows"""
        db = AgentsDB(db_path=str(tmp_path / "test.db"))
        db.init_db()
        record = LessonRecord(
            project="test",
            type=LessonType.pattern,
            key="access-inc-test",
            insight="Access count increment test content that is long enough.",
            confidence=7,
            source=LessonSource.observed,
        )
        db.insert_lesson(record)
        db.close()

        db_path = str(tmp_path / "test.db")
        rows = get_lessons(db_path=db_path)
        assert len(rows) >= 1

        db2 = AgentsDB(db_path=db_path)
        db2.init_db()
        row = db2.conn.execute(
            "SELECT access_count FROM lessons WHERE id = ?", (record.id,)
        ).fetchone()
        db2.close()
        assert row["access_count"] == 1
