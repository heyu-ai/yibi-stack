"""測試 lessons_service：show_lessons、search_lessons。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tasks.session_memory.db import AgentsDB
from tasks.session_memory.lessons_service import search_lessons, show_lessons
from tasks.session_memory.models import HandoverRecord, SessionType


def make_record(**overrides: object) -> HandoverRecord:
    defaults: dict[str, object] = {
        "id": "record-1",
        "timestamp": "2026-04-15T10:00:00+00:00",
        "operator": "howie",
        "session_type": SessionType.debug,
        "topic": "parser bug",
        "conversation_summary": "修了個 bug",
        "project": "ainization-skill",
    }
    return HandoverRecord.model_validate({**defaults, **overrides})


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    db = AgentsDB(db_path=p)
    db.init_db()
    db.close()
    return p


@pytest.fixture
def insights_file(tmp_path: Path) -> Path:
    return tmp_path / "insights.jsonl"


class TestShowLessons:
    def test_lesson_dt_001_empty_db_returns_empty(self, db_path: Path) -> None:
        """LESSON-DT-001：空 DB 回傳空 list。"""
        rows = show_lessons(db_path=db_path)
        assert rows == []

    def test_lesson_dt_002_returns_handover_lessons(self, db_path: Path) -> None:
        """LESSON-DT-002：有 lessons_learned 的 handover 記錄會被展開為個別項目。"""
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(lessons_learned=["nom 比 regex 穩", "always test edge cases"])
        )
        db.close()

        rows = show_lessons(db_path=db_path)
        assert len(rows) == 2
        texts = [r["text"] for r in rows]
        assert "nom 比 regex 穩" in texts
        assert "always test edge cases" in texts
        assert all(r["source"] == "handover" for r in rows)

    def test_lesson_dt_003_project_filter(self, db_path: Path) -> None:
        """LESSON-DT-003：project 過濾只回傳匹配的教訓。"""
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(id="a", project="proj-a", lessons_learned=["lesson a"]))
        db.insert_handover(make_record(id="b", project="proj-b", lessons_learned=["lesson b"]))
        db.close()

        rows = show_lessons(project="proj-a", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["text"] == "lesson a"

    def test_lesson_dt_004_includes_attempted_approaches(self, db_path: Path) -> None:
        """LESSON-DT-004：attempted_approaches 也會被展開，source 為 handover-approach。"""
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(
                lessons_learned=["lesson"],
                attempted_approaches=["試過 regex 太脆弱"],
            )
        )
        db.close()

        rows = show_lessons(db_path=db_path)
        sources = {r["source"] for r in rows}
        assert "handover" in sources
        assert "handover-approach" in sources
        approach_texts = [r["text"] for r in rows if r["source"] == "handover-approach"]
        assert "試過 regex 太脆弱" in approach_texts

    def test_lesson_dt_005_include_insights(self, db_path: Path, insights_file: Path) -> None:
        """LESSON-DT-005：include_insights=True 時也回傳 insight 記錄。"""
        insights_file.write_text(
            json.dumps(
                {
                    "id": "ins-1",
                    "timestamp": "2026-04-15T11:00:00+00:00",
                    "session_id": "sess-abc",
                    "project": "ainization-skill",
                    "working_dir": "/tmp",
                    "branch": "main",
                    "insight_text": "★ 這是一個洞察",
                    "session_reason": "stop",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        rows = show_lessons(db_path=db_path, include_insights=True, insights_path=insights_file)
        assert len(rows) == 1
        assert rows[0]["source"] == "insight"
        assert "這是一個洞察" in rows[0]["text"]

    def test_lesson_eg_001_insights_file_not_exist(self, db_path: Path, tmp_path: Path) -> None:
        """LESSON-EG-001：insights.jsonl 不存在時 graceful 回傳空（不拋例外）。"""
        missing = tmp_path / "nonexistent.jsonl"
        rows = show_lessons(db_path=db_path, include_insights=True, insights_path=missing)
        assert rows == []


class TestSearchLessons:
    def test_lesson_dt_006_search_matches_lesson_text(self, db_path: Path) -> None:
        """LESSON-DT-006：搜尋關鍵字比對 lessons_learned 文字。"""
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["nom parser 很穩"]))
        db.insert_handover(make_record(id="r2", lessons_learned=["完全無關的教訓"]))
        db.close()

        rows = search_lessons(query="nom", db_path=db_path)
        assert len(rows) == 1
        assert "nom" in rows[0]["text"]

    def test_lesson_dt_007_search_includes_insights(
        self, db_path: Path, insights_file: Path
    ) -> None:
        """LESSON-DT-007：include_insights=True 且關鍵字符合時回傳 insight。"""
        insights_file.write_text(
            json.dumps(
                {
                    "id": "ins-1",
                    "timestamp": "2026-04-15T11:00:00+00:00",
                    "session_id": "sess-abc",
                    "project": "ainization-skill",
                    "working_dir": "/tmp",
                    "branch": "main",
                    "insight_text": "pydantic v2 的 model_dump_json 效能比較好",
                    "session_reason": "stop",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        rows = search_lessons(
            query="pydantic", db_path=db_path, include_insights=True, insights_path=insights_file
        )
        assert len(rows) == 1
        assert rows[0]["source"] == "insight"

    def test_lesson_dt_008_search_no_match_returns_empty(self, db_path: Path) -> None:
        """LESSON-DT-008：關鍵字無匹配時回傳空 list。"""
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["something unrelated"]))
        db.close()

        rows = search_lessons(query="zzz_notfound", db_path=db_path)
        assert rows == []
