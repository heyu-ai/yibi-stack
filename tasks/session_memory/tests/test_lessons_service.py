"""測試 lessons_service：show_lessons、search_lessons。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tasks.session_memory.cli import cli
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


def make_db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    db = AgentsDB(db_path=p)
    db.init_db()
    db.close()
    return p


def make_insights_file(tmp_path: Path, entries: list[dict[str, object]] | None = None) -> Path:
    path = tmp_path / "insights.jsonl"
    if entries:
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8",
        )
    return path


_SAMPLE_INSIGHT: dict[str, object] = {
    "id": "ins-1",
    "timestamp": "2026-04-15T11:00:00+00:00",
    "session_id": "sess-abc",
    "project": "ainization-skill",
    "working_dir": "/tmp",
    "branch": "main",
    "insight_text": "★ 這是一個洞察",
    "session_reason": "stop",
}


class TestShowLessons:
    def test_lesson_dt_001_empty_db_returns_empty(self, tmp_path: Path) -> None:
        """LESSON-DT-001：空 DB 回傳空 list。"""
        rows = show_lessons(db_path=make_db_path(tmp_path))
        assert rows == []

    def test_lesson_dt_002_returns_handover_lessons(self, tmp_path: Path) -> None:
        """LESSON-DT-002：有 lessons_learned 的 handover 記錄會被展開為個別項目。"""
        db = AgentsDB(db_path=make_db_path(tmp_path))
        db.init_db()
        db.insert_handover(
            make_record(lessons_learned=["nom 比 regex 穩", "always test edge cases"])
        )
        db.close()

        rows = show_lessons(db_path=tmp_path / "test.db")
        assert len(rows) == 2
        texts = [r["text"] for r in rows]
        assert "nom 比 regex 穩" in texts
        assert "always test edge cases" in texts
        assert all(r["source"] == "handover" for r in rows)

    def test_lesson_dt_003_project_filter(self, tmp_path: Path) -> None:
        """LESSON-DT-003：project 過濾只回傳匹配的教訓。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(id="a", project="proj-a", lessons_learned=["lesson a"]))
        db.insert_handover(make_record(id="b", project="proj-b", lessons_learned=["lesson b"]))
        db.close()

        rows = show_lessons(project="proj-a", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["text"] == "lesson a"

    def test_lesson_dt_004_includes_attempted_approaches(self, tmp_path: Path) -> None:
        """LESSON-DT-004：attempted_approaches 也會被展開，source 為 handover-approach。"""
        db_path = make_db_path(tmp_path)
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

    def test_lesson_dt_005_include_insights(self, tmp_path: Path) -> None:
        """LESSON-DT-005：include_insights=True 時也回傳 insight 記錄。"""
        insights_file = make_insights_file(tmp_path, [_SAMPLE_INSIGHT])
        rows = show_lessons(
            db_path=make_db_path(tmp_path),
            include_insights=True,
            insights_path=insights_file,
        )
        assert len(rows) == 1
        assert rows[0]["source"] == "insight"
        assert "這是一個洞察" in rows[0]["text"]

    def test_lesson_eg_001_insights_file_not_exist(self, tmp_path: Path) -> None:
        """LESSON-EG-001：insights.jsonl 不存在時 graceful 回傳空（不拋例外）。"""
        missing = tmp_path / "nonexistent.jsonl"
        rows = show_lessons(
            db_path=make_db_path(tmp_path),
            include_insights=True,
            insights_path=missing,
        )
        assert rows == []

    def test_lesson_eg_002_insights_oserror_returns_empty(self, tmp_path: Path) -> None:
        """LESSON-EG-002：insights.jsonl 讀取 OSError 時 graceful 回傳空（不拋例外）。"""
        db_path = make_db_path(tmp_path)
        insights_file = make_insights_file(tmp_path, [_SAMPLE_INSIGHT])
        with patch.object(Path, "open", side_effect=OSError("disk error")):
            rows = show_lessons(
                db_path=db_path,
                include_insights=True,
                insights_path=insights_file,
            )
        assert rows == []


class TestSearchLessons:
    def test_lesson_dt_006_search_matches_lesson_text(self, tmp_path: Path) -> None:
        """LESSON-DT-006：搜尋關鍵字比對 lessons_learned 文字。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["nom parser 很穩"]))
        db.insert_handover(make_record(id="r2", lessons_learned=["完全無關的教訓"]))
        db.close()

        rows = search_lessons(query="nom", db_path=db_path)
        assert len(rows) == 1
        assert "nom" in rows[0]["text"]

    def test_lesson_dt_007_search_includes_insights(self, tmp_path: Path) -> None:
        """LESSON-DT-007：include_insights=True 且關鍵字符合時回傳 insight。"""
        insights_file = make_insights_file(
            tmp_path,
            [
                {
                    **_SAMPLE_INSIGHT,
                    "insight_text": "pydantic v2 的 model_dump_json 效能比較好",
                }
            ],
        )
        rows = search_lessons(
            query="pydantic",
            db_path=make_db_path(tmp_path),
            include_insights=True,
            insights_path=insights_file,
        )
        assert len(rows) == 1
        assert rows[0]["source"] == "insight"

    def test_lesson_dt_008_search_no_match_returns_empty(self, tmp_path: Path) -> None:
        """LESSON-DT-008：關鍵字無匹配時回傳空 list。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["something unrelated"]))
        db.close()

        rows = search_lessons(query="zzz_notfound", db_path=db_path)
        assert rows == []

    def test_lesson_dt_009_search_matches_attempted_approaches(self, tmp_path: Path) -> None:
        """LESSON-DT-009：搜尋也比對 attempted_approaches 文字，source 為 handover-approach。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(
                lessons_learned=["無關教訓"],
                attempted_approaches=["試過 regex 但太脆弱"],
            )
        )
        db.close()

        rows = search_lessons(query="regex", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["source"] == "handover-approach"
        assert "regex" in rows[0]["text"]

    def test_lesson_dt_010_search_topic_match_does_not_bleed_lessons(self, tmp_path: Path) -> None:
        """LESSON-DT-010：topic 含關鍵字但 lessons 不含時，不應回傳該教訓。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        # topic 含 "parser"，但 lessons 不含
        db.insert_handover(
            make_record(topic="parser refactoring", lessons_learned=["use types instead"])
        )
        db.close()

        rows = search_lessons(query="parser", db_path=db_path)
        assert rows == []

    def test_lesson_dt_011_search_limit_caps_lesson_items(self, tmp_path: Path) -> None:
        """LESSON-DT-011：limit 控制回傳教訓條目數，不是 handover 記錄數。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        for i in range(5):
            db.insert_handover(
                make_record(
                    id=f"r{i}",
                    timestamp=f"2026-04-{i + 10:02d}T00:00:00+00:00",
                    lessons_learned=[f"target lesson {i}", f"another target {i}"],
                )
            )
        db.close()

        rows = search_lessons(query="target", db_path=db_path, limit=3)
        assert len(rows) == 3


class TestLessonsCLI:
    def test_lesson_cli_dt_001_show_empty_outputs_placeholder(self) -> None:
        """LESSON-CLI-DT-001：無教訓時顯示占位訊息。"""
        runner = CliRunner()
        with patch("tasks.session_memory.lessons_service.show_lessons", return_value=[]):
            result = runner.invoke(cli, ["lessons", "show"])
        assert result.exit_code == 0
        assert "尚無教訓記錄" in result.output

    def test_lesson_cli_dt_002_show_json_flag_outputs_valid_json(self) -> None:
        """LESSON-CLI-DT-002：--json 旗標輸出合法 JSON。"""
        sample = [
            {
                "source": "handover",
                "text": "test",
                "timestamp": "2026-04-15",
                "project": "p",
                "context": "c",
            }
        ]
        runner = CliRunner()
        with patch("tasks.session_memory.lessons_service.show_lessons", return_value=sample):
            result = runner.invoke(cli, ["lessons", "show", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1
        assert parsed[0]["text"] == "test"

    def test_lesson_cli_dt_003_search_no_match_outputs_placeholder(self) -> None:
        """LESSON-CLI-DT-003：search 無匹配時顯示占位訊息。"""
        runner = CliRunner()
        with patch("tasks.session_memory.lessons_service.search_lessons", return_value=[]):
            result = runner.invoke(cli, ["lessons", "search", "xyz"])
        assert result.exit_code == 0
        assert "無符合" in result.output

    def test_lesson_cli_dt_004_search_outputs_matches(self) -> None:
        """LESSON-CLI-DT-004：search 有匹配時正確顯示教訓。"""
        sample = [
            {
                "source": "handover",
                "text": "nom 很穩",
                "timestamp": "2026-04-15T10:00:00",
                "project": "proj",
                "context": "topic",
            }
        ]
        runner = CliRunner()
        with patch("tasks.session_memory.lessons_service.search_lessons", return_value=sample):
            result = runner.invoke(cli, ["lessons", "search", "nom"])
        assert result.exit_code == 0
        assert "nom 很穩" in result.output
        assert "交班教訓" in result.output

    def test_lesson_cli_eg_001_show_with_insights_flag(self) -> None:
        """LESSON-CLI-EG-001：--insights 旗標正確傳遞 include_insights=True。"""
        runner = CliRunner()
        with patch(
            "tasks.session_memory.lessons_service.show_lessons", return_value=[]
        ) as mock_show:
            runner.invoke(cli, ["lessons", "show", "--insights"])
        mock_show.assert_called_once()
        assert mock_show.call_args.kwargs.get("include_insights") is True
