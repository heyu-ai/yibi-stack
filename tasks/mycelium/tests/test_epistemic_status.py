"""epistemic_status 與 supersession 功能的測試。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import LessonRecord


def _make_lesson(**overrides: object) -> LessonRecord:
    """建立 lesson fixture，只需指定差異欄位。"""
    defaults: dict[str, object] = {
        "project": "test-proj",
        "type": "pattern",
        "key": "test-key",
        "insight": "This is a test insight with enough characters to pass validation",
        "confidence": 7,
        "source": "observed",
    }
    defaults.update(overrides)
    return LessonRecord(**defaults)


class TestEpistemicStatusDefault:
    """新 lesson 的 epistemic_status 預設為 episode。"""

    def test_default_is_episode(self) -> None:
        lesson = _make_lesson()
        assert lesson.epistemic_status == "episode"

    def test_explicit_episode(self) -> None:
        lesson = _make_lesson(epistemic_status="episode")
        assert lesson.epistemic_status == "episode"

    def test_explicit_observation(self) -> None:
        lesson = _make_lesson(epistemic_status="observation")
        assert lesson.epistemic_status == "observation"

    def test_explicit_corroborated(self) -> None:
        lesson = _make_lesson(epistemic_status="corroborated")
        assert lesson.epistemic_status == "corroborated"

    def test_explicit_contradicted(self) -> None:
        lesson = _make_lesson(epistemic_status="contradicted")
        assert lesson.epistemic_status == "contradicted"

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_lesson(epistemic_status="unknown")


class TestEpistemicStatusDB:
    """DB 層的 epistemic_status CRUD。"""

    db: AgentsDB

    def setup_method(self) -> None:
        self.db = AgentsDB(db_path=":memory:")
        self.db.init_db()

    def teardown_method(self) -> None:
        self.db.close()

    def test_insert_default_episode(self) -> None:
        lesson = _make_lesson()
        self.db.insert_lesson(lesson)
        row = self.db.get_lesson(lesson.id)
        assert row is not None
        assert row["epistemic_status"] == "episode"

    def test_insert_explicit_observation(self) -> None:
        lesson = _make_lesson(epistemic_status="observation")
        self.db.insert_lesson(lesson)
        row = self.db.get_lesson(lesson.id)
        assert row is not None
        assert row["epistemic_status"] == "observation"

    def test_pre_migration_null_treated_as_episode(self) -> None:
        """NULL epistemic_status（pre-migration 資料）在讀取時不 crash。"""
        lesson = _make_lesson()
        self.db.insert_lesson(lesson)
        self.db.conn.execute(
            "UPDATE lessons SET epistemic_status = NULL WHERE id = ?", (lesson.id,)
        )
        self.db.conn.commit()
        row = self.db.get_lesson(lesson.id)
        assert row is not None
        assert row["epistemic_status"] is None


class TestEpistemicStatusIndependentOfTier:
    """epistemic_status 與 tier 互相獨立。"""

    db: AgentsDB

    def setup_method(self) -> None:
        self.db = AgentsDB(db_path=":memory:")
        self.db.init_db()

    def teardown_method(self) -> None:
        self.db.close()

    def test_tier_change_does_not_affect_status(self) -> None:
        lesson = _make_lesson(epistemic_status="corroborated")
        self.db.insert_lesson(lesson)
        self.db.conn.execute("UPDATE lessons SET tier = 'hot' WHERE id = ?", (lesson.id,))
        self.db.conn.commit()
        row = self.db.get_lesson(lesson.id)
        assert row is not None
        assert row["tier"] == "hot"
        assert row["epistemic_status"] == "corroborated"


class TestFilterByStatus:
    """query_lessons_typed 的 epistemic_status 過濾。"""

    db: AgentsDB

    def setup_method(self) -> None:
        self.db = AgentsDB(db_path=":memory:")
        self.db.init_db()

    def teardown_method(self) -> None:
        self.db.close()

    def test_filter_by_status(self) -> None:
        l1 = _make_lesson(key="key-a", epistemic_status="episode")
        l2 = _make_lesson(key="key-b", epistemic_status="observation")
        l3 = _make_lesson(key="key-c", epistemic_status="episode")
        for lesson in (l1, l2, l3):
            self.db.insert_lesson(lesson)

        episodes = self.db.query_lessons_typed(project="test-proj", epistemic_status="episode")
        assert len(episodes) == 2
        assert all(r["epistemic_status"] == "episode" for r in episodes)

        observations = self.db.query_lessons_typed(
            project="test-proj", epistemic_status="observation"
        )
        assert len(observations) == 1
        assert observations[0]["key"] == "key-b"

    def test_no_filter_returns_all(self) -> None:
        l1 = _make_lesson(key="key-a", epistemic_status="episode")
        l2 = _make_lesson(key="key-b", epistemic_status="observation")
        for lesson in (l1, l2):
            self.db.insert_lesson(lesson)

        all_lessons = self.db.query_lessons_typed(project="test-proj")
        assert len(all_lessons) == 2


class TestSupersession:
    """lesson supersession 功能。"""

    db: AgentsDB

    def setup_method(self) -> None:
        self.db = AgentsDB(db_path=":memory:")
        self.db.init_db()

    def teardown_method(self) -> None:
        self.db.close()

    def test_supersede_preserves_original(self) -> None:
        old = _make_lesson(key="old-key", insight="Original insight text for testing purposes")
        new = _make_lesson(key="new-key", insight="Corrected insight text for testing purposes")
        self.db.insert_lesson(old)
        self.db.insert_lesson(new)

        result = self.db.supersede_lesson(old.id, new.id)
        assert result is not None
        assert result["superseded_by"] == new.id
        assert result["insight"] == "Original insight text for testing purposes"

    def test_supersede_nonexistent_returns_none(self) -> None:
        result = self.db.supersede_lesson("nonexistent-id", "some-id")
        assert result is None

    def test_superseded_by_default_none(self) -> None:
        lesson = _make_lesson()
        self.db.insert_lesson(lesson)
        row = self.db.get_lesson(lesson.id)
        assert row is not None
        assert row["superseded_by"] is None

    def test_superseded_still_queryable(self) -> None:
        old = _make_lesson(key="old-key", insight="Original insight text for testing purposes")
        new = _make_lesson(key="new-key", insight="Corrected insight text for testing purposes")
        self.db.insert_lesson(old)
        self.db.insert_lesson(new)
        self.db.supersede_lesson(old.id, new.id)

        all_lessons = self.db.query_lessons_typed(project="test-proj")
        ids = [r["id"] for r in all_lessons]
        assert old.id in ids
