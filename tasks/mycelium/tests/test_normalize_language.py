"""測試 handover language normalization（audit / collect / apply）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.handover_service import (
    _apply_translations,
    _collect_cjk_texts,
    _has_cjk,
    _record_has_cjk,
    audit_handover_language,
    normalize_handover_language,
)


def _insert_handover(db: AgentsDB, **overrides: object) -> str:
    """Insert a minimal handover row and return its id."""
    import uuid

    row_id = str(uuid.uuid4())
    defaults: dict[str, object] = {
        "id": row_id,
        "timestamp": "2026-09-01T12:00:00+08:00",
        "operator": "howie",
        "session_type": "sdd",
        "topic": "test topic",
        "conversation_summary": "test summary",
        "completed": "[]",
        "decisions": "[]",
        "blocked": "[]",
        "next_priorities": "[]",
        "lessons_learned": "[]",
        "attempted_approaches": "[]",
        "tags": "[]",
        "device": "test",
        "agent_type": "claude",
        "subscription_account": "test",
        "branch": "main",
        "working_dir": "~/test",
        "last_files": "[]",
        "test_status": None,
        "token_usage_estimate": None,
        "project": "test-project",
        "source_bot": None,
    }
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    db.conn.execute(
        f"INSERT INTO handovers ({cols}) VALUES ({placeholders})",  # nosec B608
        list(defaults.values()),
    )
    db.conn.commit()
    return row_id


class TestHasCjk:
    def test_nlang_dt_001_ascii_returns_false(self) -> None:
        """NLANG-DT-001：純 ASCII 文字不含 CJK。"""
        assert not _has_cjk("hello world PR #42")

    def test_nlang_dt_002_chinese_returns_true(self) -> None:
        """NLANG-DT-002：含中文字元回傳 True。"""
        assert _has_cjk("修正 auth 問題")

    def test_nlang_dt_003_empty_returns_false(self) -> None:
        """NLANG-DT-003：空字串不含 CJK。"""
        assert not _has_cjk("")


class TestRecordHasCjk:
    def test_nlang_dt_004_all_english_record(self) -> None:
        """NLANG-DT-004：全英文 record 回傳 False。"""
        row = {
            "topic": "fix auth bug",
            "conversation_summary": "fixed the auth bug",
            "completed": ["task 1"],
            "decisions": [],
            "blocked": [],
            "next_priorities": [],
            "lessons_learned": [],
            "attempted_approaches": [],
        }
        assert not _record_has_cjk(row)

    def test_nlang_dt_005_chinese_in_topic(self) -> None:
        """NLANG-DT-005：topic 含中文回傳 True。"""
        row = {
            "topic": "修正 auth 問題",
            "conversation_summary": "fixed it",
            "completed": [],
            "decisions": [],
            "blocked": [],
            "next_priorities": [],
            "lessons_learned": [],
            "attempted_approaches": [],
        }
        assert _record_has_cjk(row)

    def test_nlang_dt_006_chinese_in_array_field(self) -> None:
        """NLANG-DT-006：JSON array 欄位含中文回傳 True。"""
        row = {
            "topic": "english topic",
            "conversation_summary": "english summary",
            "completed": [],
            "decisions": ["決定用 Pydantic v2"],
            "blocked": [],
            "next_priorities": [],
            "lessons_learned": [],
            "attempted_approaches": [],
        }
        assert _record_has_cjk(row)


class TestCollectCjkTexts:
    def test_nlang_st_007_collects_text_and_array_fields(self) -> None:
        """NLANG-ST-007：同時收集 text 和 array 欄位的 CJK 段落。"""
        row = {
            "topic": "修正問題",
            "conversation_summary": "english summary",
            "completed": ["完成 task 1", "done task 2"],
            "decisions": [],
            "blocked": [],
            "next_priorities": ["下一步：寫測試"],
            "lessons_learned": [],
            "attempted_approaches": [],
        }
        segments = _collect_cjk_texts(row)
        assert len(segments) == 3
        assert segments[0] == ("topic", None, "修正問題")
        assert segments[1] == ("completed", 0, "完成 task 1")
        assert segments[2] == ("next_priorities", 0, "下一步：寫測試")


class TestApplyTranslations:
    def test_nlang_st_008_applies_text_and_array(self) -> None:
        """NLANG-ST-008：正確套用翻譯到 text 和 array 欄位。"""
        row = {
            "topic": "修正問題",
            "conversation_summary": "english",
            "completed": ["完成 task 1", "done task 2"],
        }
        segments = [
            ("topic", None, "修正問題"),
            ("completed", 0, "完成 task 1"),
        ]
        translated = ["Fix the issue", "Completed task 1"]
        updates = _apply_translations(row, segments, translated)
        assert updates["topic"] == "Fix the issue"
        assert updates["completed"] == ["Completed task 1", "done task 2"]


class TestAuditHandoverLanguage:
    def test_nlang_st_009_audit_counts(self, tmp_path: Path) -> None:
        """NLANG-ST-009：audit 正確統計 CJK 筆數。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _insert_handover(db, topic="修正 auth", conversation_summary="修了")
        _insert_handover(db, topic="fix bug", conversation_summary="fixed")
        _insert_handover(
            db,
            topic="another",
            conversation_summary="ok",
            decisions=json.dumps(["決定 A"]),
        )
        db.close()

        stats = audit_handover_language(db_path=db_path)
        assert stats["total"] == 3
        assert stats["cjk_count"] == 2
        assert stats["field_stats"]["topic"] == 1
        assert stats["field_stats"]["conversation_summary"] == 1
        assert stats["field_stats"]["decisions"] == 1


class TestNormalizeHandoverLanguage:
    @patch("tasks.mycelium.handover_service._translate_batch")
    def test_nlang_st_010_dry_run_does_not_modify(
        self, mock_translate: MagicMock, tmp_path: Path
    ) -> None:
        """NLANG-ST-010：dry-run 不修改 DB。"""
        mock_translate.return_value = ["Fix auth issue", "Fixed it"]

        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _insert_handover(db, topic="修正 auth 問題", conversation_summary="修了")
        db.close()

        result = normalize_handover_language(dry_run=True, db_path=db_path)
        assert result["dry_run"] is True
        assert result["processed"] == 1

        db2 = AgentsDB(db_path)
        db2.init_db()
        rows = db2.fetch_all_handovers()
        db2.close()
        assert rows[0]["topic"] == "修正 auth 問題"

    @patch("tasks.mycelium.handover_service._translate_batch")
    def test_nlang_st_011_apply_updates_db(self, mock_translate: MagicMock, tmp_path: Path) -> None:
        """NLANG-ST-011：apply 模式實際更新 DB。"""
        mock_translate.return_value = ["Fix auth issue", "Fixed it"]

        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _insert_handover(db, topic="修正 auth 問題", conversation_summary="修了")
        db.close()

        result = normalize_handover_language(dry_run=False, db_path=db_path)
        assert result["processed"] == 1

        db2 = AgentsDB(db_path)
        db2.init_db()
        rows = db2.fetch_all_handovers()
        db2.close()
        assert rows[0]["topic"] == "Fix auth issue"
        assert rows[0]["conversation_summary"] == "Fixed it"

    @patch("tasks.mycelium.handover_service._translate_batch")
    def test_nlang_st_012_skips_english_only_records(
        self, mock_translate: MagicMock, tmp_path: Path
    ) -> None:
        """NLANG-ST-012：純英文記錄不處理。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _insert_handover(db, topic="english topic", conversation_summary="english")
        db.close()

        result = normalize_handover_language(dry_run=True, db_path=db_path)
        assert result["total_cjk"] == 0
        assert result["processed"] == 0
        mock_translate.assert_not_called()

    @patch("tasks.mycelium.handover_service._translate_batch")
    def test_nlang_st_013_handles_array_field_translation(
        self, mock_translate: MagicMock, tmp_path: Path
    ) -> None:
        """NLANG-ST-013：正確翻譯 JSON array 欄位內的 CJK 項目。"""
        mock_translate.return_value = [
            "Fix the problem",
            "Completed task 1",
            "Next: write tests",
        ]

        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _insert_handover(
            db,
            topic="修正問題",
            conversation_summary="ok",
            completed=json.dumps(["完成 task 1", "done task 2"]),
            next_priorities=json.dumps(["下一步：寫測試"]),
        )
        db.close()

        result = normalize_handover_language(dry_run=False, db_path=db_path)
        assert result["processed"] == 1

        db2 = AgentsDB(db_path)
        db2.init_db()
        rows = db2.fetch_all_handovers()
        db2.close()
        assert rows[0]["topic"] == "Fix the problem"
        assert rows[0]["completed"] == ["Completed task 1", "done task 2"]
        assert rows[0]["next_priorities"] == ["Next: write tests"]
