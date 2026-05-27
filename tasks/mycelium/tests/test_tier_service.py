"""Tier service 測試。"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import LessonRecord, LessonSource, LessonType
from tasks.mycelium.tier_service import PromotionResult, _process_row, run_promotion_check


def _make_db(tmp_path: Path) -> AgentsDB:
    db_path = str(tmp_path / "test.db")
    db = AgentsDB(db_path=db_path)
    db.init_db()
    return db


def _insert_lesson(db: AgentsDB, *, tier: str, access_count: int, age_days: float) -> str:
    ts = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    record = LessonRecord(
        project="test",
        type=LessonType.pattern,
        key="test-key",
        insight="This is a ten-char test insight.",
        confidence=7,
        source=LessonSource.observed,
        tier=tier,
        access_count=access_count,
        ts=ts,
    )
    db.insert_lesson(record)
    return record.id


class TestRunPromotionCheck:
    def test_myc_tier_dt_001_working_to_hot(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-001: working + access_count>=3 -> hot"""
        db = _make_db(tmp_path)
        lesson_id = _insert_lesson(db, tier="working", access_count=3, age_days=1)
        db.close()

        result = run_promotion_check(db_path=str(tmp_path / "test.db"))

        assert result.promoted_to_hot == 1
        assert result.demoted_to_cold == 0
        assert result.errors == []

        # Verify DB updated
        db2 = _make_db(tmp_path)
        row = db2.conn.execute("SELECT tier FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        db2.close()
        assert row["tier"] == "hot"

    def test_myc_tier_dt_002_working_to_cold(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-002: working + access_count==0 + age>90 -> cold"""
        db = _make_db(tmp_path)
        lesson_id = _insert_lesson(db, tier="working", access_count=0, age_days=91)
        db.close()

        result = run_promotion_check(db_path=str(tmp_path / "test.db"))

        assert result.demoted_to_cold == 1
        assert result.promoted_to_hot == 0

        db2 = _make_db(tmp_path)
        row = db2.conn.execute("SELECT tier FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        db2.close()
        assert row["tier"] == "cold"

    def test_myc_tier_dt_003_low_access_old_to_cold(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-003: working + access_count==2 + age>90 -> cold (low-but-nonzero fix)"""
        db = _make_db(tmp_path)
        lesson_id = _insert_lesson(db, tier="working", access_count=2, age_days=91)
        db.close()

        result = run_promotion_check(db_path=str(tmp_path / "test.db"))

        assert result.demoted_to_cold == 1
        db2 = _make_db(tmp_path)
        row = db2.conn.execute("SELECT tier FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        db2.close()
        assert row["tier"] == "cold"

    def test_myc_tier_dt_004_no_change_boundary(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-004: age==89 (boundary) stays in working"""
        db = _make_db(tmp_path)
        lesson_id = _insert_lesson(db, tier="working", access_count=0, age_days=89)
        db.close()

        result = run_promotion_check(db_path=str(tmp_path / "test.db"))

        assert result.demoted_to_cold == 0
        assert result.promoted_to_hot == 0

    def test_myc_tier_dt_005_archival_failure_not_committed(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-005: archival failure leaves tier unchanged (no DB inconsistency)"""
        db = _make_db(tmp_path)
        lesson_id = _insert_lesson(db, tier="cold", access_count=0, age_days=366)
        db.close()

        # archive_lesson_by_id will fail because archival.py tries to read the lesson
        # row to build the archive content — not mocked here; let it run and check errors
        result = run_promotion_check(db_path=str(tmp_path / "test.db"))

        # Either it succeeded (tier=archival) or it failed (errors non-empty, tier=cold)
        db2 = _make_db(tmp_path)
        row = db2.conn.execute("SELECT tier, archived_path FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        db2.close()

        if result.errors:
            # Archival failed → tier must NOT have been updated (no inconsistency)
            assert row["tier"] == "cold", "tier must stay cold when archive fails"
            assert row["archived_path"] is None
        else:
            # Archival succeeded → tier updated and archived_path set
            assert row["tier"] == "archival"
            assert row["archived_path"] is not None

    def test_myc_tier_dt_006_error_reported_in_result(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-006: _try_archive failure is reported in result.errors"""
        from unittest.mock import patch

        db = _make_db(tmp_path)
        lesson_id = _insert_lesson(db, tier="cold", access_count=0, age_days=366)
        db.close()

        with patch("tasks.mycelium.archival.archive_lesson_by_id",
                   side_effect=RuntimeError("disk full")):
            result = run_promotion_check(db_path=str(tmp_path / "test.db"))

        assert len(result.errors) == 1
        assert "disk full" in result.errors[0]

        # Tier must stay cold — no inconsistency
        db2 = _make_db(tmp_path)
        row = db2.conn.execute("SELECT tier FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        db2.close()
        assert row["tier"] == "cold"


class TestIncrementAccessCount:
    def test_myc_tier_dt_007_access_count_increments(self, tmp_path: Path) -> None:
        """MYC-TIER-DT-007: get_lessons() increments access_count for returned rows"""
        from tasks.mycelium.lessons_service import get_lessons

        db = _make_db(tmp_path)
        record = LessonRecord(
            project="test",
            type=LessonType.pattern,
            key="acc-test",
            insight="Access count increment test insight text.",
            confidence=7,
            source=LessonSource.observed,
            tier="hot",
        )
        db.insert_lesson(record)
        db.close()

        # Call get_lessons to trigger access_count increment
        rows = get_lessons(tier_filter=["hot"], db_path=str(tmp_path / "test.db"))
        assert len(rows) == 1

        # Verify access_count was incremented
        db2 = _make_db(tmp_path)
        row = db2.conn.execute(
            "SELECT access_count, last_accessed_at FROM lessons WHERE id = ?", (record.id,)
        ).fetchone()
        db2.close()
        assert row["access_count"] == 1
        assert row["last_accessed_at"] is not None
