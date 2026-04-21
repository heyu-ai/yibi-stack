"""測試 AgentsDB：CRUD、search、upsert 冪等。"""

from __future__ import annotations

import pytest

from tasks.session_memory.db import AgentsDB
from tasks.session_memory.models import HandoverRecord, SessionType


def make_record(**overrides: object) -> HandoverRecord:
    defaults = {
        "id": "record-1",
        "timestamp": "2026-04-15T10:00:00+00:00",
        "operator": "howie",
        "session_type": SessionType.debug,
        "topic": "parser bug",
        "conversation_summary": "修了個 bug",
        "tags": ["parser", "rust"],
        "device": "mac-mini",
        "agent_type": "claude",
        "subscription_account": "claude-pro",
        "project": "flight-mcp",
    }
    return HandoverRecord.model_validate({**defaults, **overrides})


@pytest.fixture
def db() -> AgentsDB:
    instance = AgentsDB(":memory:")
    instance.init_db()
    return instance


class TestAgentsDB:
    def test_agents_st_001_insert_and_read(self, db: AgentsDB) -> None:
        """AGENTS-ST-001：寫入後讀回同樣內容。"""
        db.insert_handover(make_record())
        rows = db.read_recent(last=1)
        assert len(rows) == 1
        assert rows[0]["id"] == "record-1"
        assert rows[0]["topic"] == "parser bug"
        assert rows[0]["tags"] == ["parser", "rust"]  # JSON array 已 decode

    def test_agents_st_002_ordering_desc_by_timestamp(self, db: AgentsDB) -> None:
        """AGENTS-ST-002：read_recent 依 timestamp 降冪排序。"""
        db.insert_handover(make_record(id="a", timestamp="2026-04-14T00:00:00+00:00"))
        db.insert_handover(make_record(id="b", timestamp="2026-04-15T00:00:00+00:00"))
        rows = db.read_recent(last=2)
        assert [r["id"] for r in rows] == ["b", "a"]

    def test_agents_st_003_upsert_idempotent(self, db: AgentsDB) -> None:
        """AGENTS-ST-003：相同 id 的 upsert 不會產生第二筆。"""
        db.upsert_handover(make_record(id="dup"))
        db.upsert_handover(make_record(id="dup"))
        assert db.count() == 1

    def test_agents_vl_001_invalid_session_type_rejected(self, db: AgentsDB) -> None:
        """AGENTS-VL-001：SessionType enum 以外的值在 Pydantic 階段就會失敗。"""
        with pytest.raises(ValueError):
            HandoverRecord.model_validate(
                {
                    "id": "x",
                    "timestamp": "2026-04-15T00:00:00+00:00",
                    "session_type": "INVALID",
                    "topic": "t",
                    "conversation_summary": "s",
                }
            )


class TestSearch:
    def test_agents_dt_006_search_by_query_case_insensitive(self, db: AgentsDB) -> None:
        """AGENTS-DT-006：query 比對大小寫不敏感，且跨多個欄位。"""
        db.insert_handover(make_record(id="1", topic="Parser Bug", tags=[]))
        db.insert_handover(make_record(id="2", topic="unrelated", tags=["parser"]))
        db.insert_handover(make_record(id="3", topic="nothing", tags=[]))

        rows = db.search(query="parser")
        assert {r["id"] for r in rows} == {"1", "2"}

    def test_agents_dt_007_search_by_session_type(self, db: AgentsDB) -> None:
        """AGENTS-DT-007：session_type filter 只回傳該類型。"""
        db.insert_handover(make_record(id="d", session_type=SessionType.debug))
        db.insert_handover(make_record(id="a", session_type=SessionType.admin))
        rows = db.search(session_type=SessionType.debug)
        assert [r["id"] for r in rows] == ["d"]

    def test_agents_dt_008_search_combined_filters(self, db: AgentsDB) -> None:
        """AGENTS-DT-008：query + project 同時滿足才入選。"""
        db.insert_handover(make_record(id="1", topic="parser", project="flight-mcp", tags=[]))
        db.insert_handover(make_record(id="2", topic="parser", project="other", tags=[]))
        db.insert_handover(make_record(id="3", topic="nothing", project="flight-mcp", tags=[]))

        rows = db.search(query="parser", project="flight-mcp")
        assert [r["id"] for r in rows] == ["1"]

    def test_agents_eg_002_search_limit_zero_raises(self, db: AgentsDB) -> None:
        """AGENTS-EG-002：limit<=0 應 raise。"""
        with pytest.raises(ValueError):
            db.search(limit=0)

    def test_agents_eg_003_read_recent_zero_raises(self, db: AgentsDB) -> None:
        """AGENTS-EG-003：read_recent last<=0 應 raise。"""
        with pytest.raises(ValueError):
            db.read_recent(last=0)

    def test_agents_dt_009_read_recent_project_filter(self, db: AgentsDB) -> None:
        """AGENTS-DT-009：read_recent project 過濾只回傳匹配的 rows。"""
        db.insert_handover(make_record(id="a", project="flight-mcp"))
        db.insert_handover(make_record(id="b", project="voice-lab"))
        rows = db.read_recent(last=10, project="flight-mcp")
        assert len(rows) == 1
        assert rows[0]["id"] == "a"

    def test_agents_dt_010_read_recent_project_filter_respects_last(self, db: AgentsDB) -> None:
        """AGENTS-DT-010：project 過濾時 last limit 仍有效。"""
        db.insert_handover(
            make_record(id="a", project="flight-mcp", timestamp="2026-04-14T00:00:00+00:00")
        )
        db.insert_handover(
            make_record(id="b", project="flight-mcp", timestamp="2026-04-15T00:00:00+00:00")
        )
        rows = db.read_recent(last=1, project="flight-mcp")
        assert len(rows) == 1
        assert rows[0]["id"] == "b"  # 最新一筆

    def test_agents_eg_004_read_recent_project_not_found_returns_empty(self, db: AgentsDB) -> None:
        """AGENTS-EG-004：project 不存在時回傳空 list，不拋例外。"""
        db.insert_handover(make_record(id="a", project="flight-mcp"))
        rows = db.read_recent(last=5, project="nonexistent")
        assert rows == []


class TestQueryLessons:
    def test_agents_lesson_dt_001_empty_db_returns_empty(self, db: AgentsDB) -> None:
        """AGENTS-LESSON-DT-001：空 DB 回傳空 list。"""
        rows = db.query_lessons()
        assert rows == []

    def test_agents_lesson_dt_002_only_returns_records_with_lessons(self, db: AgentsDB) -> None:
        """AGENTS-LESSON-DT-002：只回傳有 lessons_learned 的記錄。"""
        db.insert_handover(make_record(id="has-lesson", lessons_learned=["nom 比 regex 穩"]))
        db.insert_handover(make_record(id="no-lesson", lessons_learned=[]))
        rows = db.query_lessons()
        assert len(rows) == 1
        assert rows[0]["id"] == "has-lesson"
        assert "nom 比 regex 穩" in rows[0]["lessons_learned"]

    def test_agents_lesson_dt_003_project_filter(self, db: AgentsDB) -> None:
        """AGENTS-LESSON-DT-003：project 過濾只回傳匹配的記錄。"""
        db.insert_handover(make_record(id="a", project="proj-a", lessons_learned=["lesson a"]))
        db.insert_handover(make_record(id="b", project="proj-b", lessons_learned=["lesson b"]))
        rows = db.query_lessons(project="proj-a")
        assert len(rows) == 1
        assert rows[0]["id"] == "a"

    def test_agents_lesson_dt_004_limit(self, db: AgentsDB) -> None:
        """AGENTS-LESSON-DT-004：limit 控制回傳數量上限。"""
        for i in range(5):
            db.insert_handover(
                make_record(
                    id=f"r{i}",
                    timestamp=f"2026-04-{i + 10:02d}T00:00:00+00:00",
                    lessons_learned=[f"lesson {i}"],
                )
            )
        rows = db.query_lessons(limit=3)
        assert len(rows) == 3

    def test_agents_lesson_dt_005_includes_attempted_approaches(self, db: AgentsDB) -> None:
        """AGENTS-LESSON-DT-005：回傳記錄含 attempted_approaches 欄位。"""
        db.insert_handover(
            make_record(
                id="ap",
                lessons_learned=["lesson"],
                attempted_approaches=["試過 regex 太脆弱"],
            )
        )
        rows = db.query_lessons()
        assert rows[0]["attempted_approaches"] == ["試過 regex 太脆弱"]

    def test_agents_lesson_eg_001_limit_zero_raises(self, db: AgentsDB) -> None:
        """AGENTS-LESSON-EG-001：limit <= 0 應 raise ValueError。"""
        with pytest.raises(ValueError):
            db.query_lessons(limit=0)
