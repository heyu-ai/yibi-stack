"""Lessons service 新 API（save_lesson + get_lessons）測試。"""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.lessons_service import _make_token_counter, get_lessons, save_lesson
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
        row = db.conn.execute("SELECT tier FROM lessons WHERE id = ?", (result["id"],)).fetchone()
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
        row = db.conn.execute("SELECT tier FROM lessons WHERE id = ?", (result["id"],)).fetchone()
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
        row = db.conn.execute("SELECT tags FROM lessons WHERE id = ?", (result["id"],)).fetchone()
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


class TestTokenCounterFallback:
    """token 計數的降級路徑（PR #249）。

    PR #249 之前 tiktoken 從未被宣告為依賴，故 len/4 是唯一跑過的路徑；新增 tokens
    extra 後 tiktoken 分支首次可達，其網路失敗模式也隨之從理論變成活的。
    """

    def test_myc_svc_eg_020_missing_tiktoken_degrades_silently(self) -> None:
        """MYC-SVC-EG-020: 未安裝 tiktoken 時退化為粗估，且**不**發警告。

        未裝 tokens extra 是預期情形而非異常。若這裡發警告，每個沒裝 extra 的使用者
        每次查 lessons 都會看到一則無法行動的雜訊。
        """
        with patch.dict("sys.modules", {"tiktoken": None}), warnings.catch_warnings():
            warnings.simplefilter("error")  # 任何警告都會變成例外
            counter = _make_token_counter()

        assert counter("a" * 40) == 10  # len/4 粗估

    def test_myc_svc_eg_021_tiktoken_network_failure_degrades_with_warning(self) -> None:
        """MYC-SVC-EG-021: get_encoding() 非 ImportError 失敗時退化並發警告。

        get_encoding() 在冷快取時會下載 BPE vocab，失敗拋的是網路／HTTP 錯誤而非
        ImportError。只捕捉 ImportError 會讓這個 best-effort 的估算把例外往外拋。
        會發警告：裝了 --extra tokens 卻仍拿到粗估的使用者需要知道原因。
        """
        fake_tiktoken = type(
            "FakeTiktoken",
            (),
            {
                "get_encoding": staticmethod(
                    lambda _name: (_ for _ in ()).throw(OSError("cdn down"))
                )
            },
        )

        with (
            patch.dict("sys.modules", {"tiktoken": fake_tiktoken}),
            pytest.warns(UserWarning, match="tiktoken 初始化失敗"),
        ):
            counter = _make_token_counter()

        assert counter("a" * 40) == 10  # 退化為 len/4，而非往外拋

    def test_myc_svc_eg_022_working_tiktoken_is_used(self) -> None:
        """MYC-SVC-EG-022: tiktoken 可用時真的使用它（而非永遠走粗估）。

        沒有這個正向對照，上面兩個測試在「tiktoken 分支根本壞掉、永遠退化」時也會通過。
        """
        fake_enc = type("FakeEnc", (), {"encode": staticmethod(lambda text: [0] * len(text))})
        fake_tiktoken = type(
            "FakeTiktoken", (), {"get_encoding": staticmethod(lambda _name: fake_enc)}
        )

        with patch.dict("sys.modules", {"tiktoken": fake_tiktoken}):
            counter = _make_token_counter()

        # fake encoder 每字元一個 token；粗估則是 len/4 -> 用得出的值區分走了哪條路
        assert counter("a" * 40) == 40
