"""Archival 匯出測試。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tasks.mycelium.archival import archive_lesson, archive_lesson_by_id
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import LessonRecord, LessonSource, LessonType


def _make_db(tmp_path: Path) -> AgentsDB:
    db_path = str(tmp_path / "test.db")
    db = AgentsDB(db_path=db_path)
    db.init_db()
    return db


def _insert_lesson(db: AgentsDB) -> LessonRecord:
    record = LessonRecord(
        project="test-project",
        type=LessonType.pitfall,
        key="archive-test-key",
        insight="Archive test insight: this is the lesson content to be exported.",
        confidence=8,
        source=LessonSource.observed,
        tier="cold",
        tags=["test", "archival"],
    )
    db.insert_lesson(record)
    return record


class TestArchiveLesson:
    def test_myc_archive_dt_001_file_created(self, tmp_path: Path) -> None:
        """MYC-ARCHIVE-DT-001: archive_lesson writes YYYY-MM.md to archive_dir"""
        db = _make_db(tmp_path)
        record = _insert_lesson(db)
        archive_dir = tmp_path / "archive"
        now = datetime.now(UTC)

        archive_lesson(record, db, archive_dir=archive_dir, now=now)
        db.close()

        expected_filename = now.strftime("%Y-%m.md")
        archive_file = archive_dir / expected_filename
        assert archive_file.exists(), f"Archive file not created: {archive_file}"

    def test_myc_archive_dt_002_file_contains_insight(self, tmp_path: Path) -> None:
        """MYC-ARCHIVE-DT-002: archive file contains lesson insight text"""
        db = _make_db(tmp_path)
        record = _insert_lesson(db)
        archive_dir = tmp_path / "archive"
        now = datetime.now(UTC)

        archive_lesson(record, db, archive_dir=archive_dir, now=now)
        db.close()

        expected_filename = now.strftime("%Y-%m.md")
        content = (archive_dir / expected_filename).read_text(encoding="utf-8")
        assert "Archive test insight" in content

    def test_myc_archive_dt_003_archived_path_updated_in_db(self, tmp_path: Path) -> None:
        """MYC-ARCHIVE-DT-003: archive_lesson sets archived_path in lessons table"""
        db = _make_db(tmp_path)
        record = _insert_lesson(db)
        archive_dir = tmp_path / "archive"
        now = datetime.now(UTC)

        archive_lesson(record, db, archive_dir=archive_dir, now=now)

        row = db.conn.execute(
            "SELECT archived_path FROM lessons WHERE id = ?", (record.id,)
        ).fetchone()
        db.close()

        assert row["archived_path"] is not None
        assert row["archived_path"].endswith(".md")

    def test_myc_archive_dt_004_appends_to_existing_file(self, tmp_path: Path) -> None:
        """MYC-ARCHIVE-DT-004: archiving multiple lessons appends to same monthly file"""
        db = _make_db(tmp_path)
        archive_dir = tmp_path / "archive"
        now = datetime.now(UTC)

        # Insert and archive two lessons
        for i in range(2):
            r = LessonRecord(
                project="test",
                type=LessonType.pattern,
                key=f"multi-archive-{i}",
                insight=f"Multi-archive lesson {i} with enough content.",
                confidence=7,
                source=LessonSource.observed,
            )
            db.insert_lesson(r)
            archive_lesson(r, db, archive_dir=archive_dir, now=now)

        db.close()

        expected_filename = now.strftime("%Y-%m.md")
        content = (archive_dir / expected_filename).read_text(encoding="utf-8")
        assert "Multi-archive lesson 0" in content
        assert "Multi-archive lesson 1" in content

    def test_myc_archive_dt_005_archive_by_id(self, tmp_path: Path) -> None:
        """MYC-ARCHIVE-DT-005: archive_lesson_by_id works end-to-end"""
        import unittest.mock as mock

        import tasks.mycelium.archival as archival_mod

        db = _make_db(tmp_path)
        record = _insert_lesson(db)
        db.close()

        archive_dir = tmp_path / "archive"
        with mock.patch.object(archival_mod, "_ARCHIVE_DIR", archive_dir):
            db2 = _make_db(tmp_path)
            archive_lesson_by_id(record.id, db2)
            row = db2.conn.execute(
                "SELECT archived_path FROM lessons WHERE id = ?", (record.id,)
            ).fetchone()
            db2.close()

        assert row["archived_path"] is not None
