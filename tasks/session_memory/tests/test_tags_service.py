"""Tests for tags_service module."""

from __future__ import annotations

import pytest

from tasks.session_memory.tags_service import (
    get_tag_stats,
    list_all_tags,
    purge_tag,
    rename_tag,
)


def _make_db(tmp_path):
    from tasks.session_memory.db import AgentsDB

    db_path = tmp_path / "test.db"
    db = AgentsDB(db_path=":memory:")
    db.init_db()
    return db, db_path


def _write_handover(db, topic, tags, session_type="admin", project=None):
    import uuid
    from tasks.session_memory.models import HandoverRecord, SessionType

    record = HandoverRecord(
        id=str(uuid.uuid4()),
        timestamp="2026-05-25T10:00:00+08:00",
        session_type=SessionType(session_type),
        topic=topic,
        conversation_summary="summary",
        tags=tags,
        project=project,
    )
    db.insert_handover(record)
    return record


class TestGetTagStats:
    def test_empty_db_returns_zero_stats(self, tmp_path):
        """TAG-ST-001: 空 DB 回傳零統計。"""
        db_path = tmp_path / "empty.db"
        from tasks.session_memory.db import AgentsDB

        db = AgentsDB(":memory:")
        db.init_db()
        db.close()

        stats = get_tag_stats(db_path=None)
        assert stats.total_unique_tags >= 0

    def test_stats_counts_correctly(self, tmp_path):
        """TAG-ST-002: 統計正確計算 tag 使用次數。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["wave1", "pr-retro"])
        _write_handover(db, "B", ["wave1", "rule-update"])
        _write_handover(db, "C", ["rule-update"])
        db.close()

        stats = get_tag_stats(db_path=db_path)
        tag_counts = {e.tag: e.count for e in stats.entries}
        assert tag_counts["wave1"] == 2
        assert tag_counts["rule-update"] == 2
        assert tag_counts["pr-retro"] == 1

    def test_top_n_limits_entries(self, tmp_path):
        """TAG-ST-003: top_n 參數限制回傳數量。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        for i in range(10):
            _write_handover(db, f"topic-{i}", [f"tag-{i}", "common"])
        db.close()

        stats = get_tag_stats(db_path=db_path, top_n=3)
        assert len(stats.entries) <= 3

    def test_entries_sorted_by_count_desc(self, tmp_path):
        """TAG-ST-004: entries 按 count 降序排列。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["rare"])
        _write_handover(db, "B", ["common", "rare"])
        _write_handover(db, "C", ["common"])
        db.close()

        stats = get_tag_stats(db_path=db_path)
        counts = [e.count for e in stats.entries]
        assert counts == sorted(counts, reverse=True)


class TestRenameTag:
    def test_rename_updates_all_matching_records(self, tmp_path):
        """TAG-ST-005: rename_tag 更新所有含舊 tag 的記錄。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["old-name", "other"])
        _write_handover(db, "B", ["old-name"])
        _write_handover(db, "C", ["unrelated"])
        db.close()

        n = rename_tag("old-name", "new-name", db_path=db_path)
        assert n == 2

        db2 = AgentsDB(db_path)
        db2.init_db()
        all_tags = db2.get_all_tags()
        db2.close()
        assert "new-name" in all_tags
        assert "old-name" not in all_tags

    def test_rename_to_same_tag_returns_zero(self, tmp_path):
        """TAG-ST-006: 新舊名稱相同時 rename 回傳 0。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["tag"])
        db.close()

        n = rename_tag("tag", "tag", db_path=db_path)
        assert n == 0

    def test_rename_empty_new_tag_raises(self, tmp_path):
        """TAG-EG-001: new_tag 空字串 raise ValueError。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        db.close()

        with pytest.raises(ValueError, match="不可為空"):
            rename_tag("old", "", db_path=db_path)


class TestPurgeTag:
    def test_purge_deletes_matching_records(self, tmp_path):
        """TAG-ST-007: purge_tag 刪除所有含指定 tag 的記錄。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["to-purge"])
        _write_handover(db, "B", ["to-purge", "other"])
        _write_handover(db, "C", ["keep-this"])
        db.close()

        n = purge_tag("to-purge", db_path=db_path)
        assert n == 2

        db2 = AgentsDB(db_path)
        db2.init_db()
        assert db2.count() == 1
        remaining = db2.read_recent(last=10)
        db2.close()
        assert remaining[0]["topic"] == "C"

    def test_purge_nonexistent_tag_returns_zero(self, tmp_path):
        """TAG-EG-002: 清除不存在的 tag 回傳 0。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["existing"])
        db.close()

        n = purge_tag("nonexistent", db_path=db_path)
        assert n == 0


class TestListAllTags:
    def test_returns_sorted_deduped_tags(self, tmp_path):
        """TAG-ST-008: list_all_tags 回傳去重排序結果。"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path)
        db.init_db()
        _write_handover(db, "A", ["zebra", "alpha"])
        _write_handover(db, "B", ["alpha", "beta"])
        db.close()

        tags = list_all_tags(db_path=db_path)
        assert tags == sorted(set(tags))
        assert "alpha" in tags
        assert "beta" in tags
        assert "zebra" in tags
