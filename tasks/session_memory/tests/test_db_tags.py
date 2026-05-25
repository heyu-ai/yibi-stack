"""Tests for AgentsDB tag management methods (get_all_tags, get_tag_usage, rename_tag, delete_by_tag)."""

from __future__ import annotations

import uuid

import pytest

from tasks.session_memory.db import AgentsDB
from tasks.session_memory.models import HandoverRecord, SessionType


def _make_db():
    db = AgentsDB(":memory:")
    db.init_db()
    return db


def _insert(db: AgentsDB, topic: str, tags: list[str], project: str | None = None) -> HandoverRecord:
    record = HandoverRecord(
        id=str(uuid.uuid4()),
        timestamp="2026-05-25T10:00:00+08:00",
        session_type=SessionType.admin,
        topic=topic,
        conversation_summary="summary",
        tags=tags,
        project=project,
    )
    db.insert_handover(record)
    return record


class TestGetAllTags:
    def test_empty_returns_empty_list(self):
        """DBTAG-DT-001: 空 DB 回傳空清單。"""
        db = _make_db()
        assert db.get_all_tags() == []

    def test_deduplicates_across_records(self):
        """DBTAG-DT-002: 跨記錄去重。"""
        db = _make_db()
        _insert(db, "A", ["alpha", "beta"])
        _insert(db, "B", ["beta", "gamma"])
        tags = db.get_all_tags()
        assert sorted(tags) == ["alpha", "beta", "gamma"]

    def test_returns_sorted_list(self):
        """DBTAG-DT-003: 回傳已排序清單。"""
        db = _make_db()
        _insert(db, "A", ["zebra", "apple", "mango"])
        tags = db.get_all_tags()
        assert tags == sorted(tags)

    def test_excludes_empty_tag_strings(self):
        """DBTAG-EG-001: 跳過空字串 tag。"""
        db = _make_db()
        _insert(db, "A", ["valid", ""])
        tags = db.get_all_tags()
        assert "" not in tags
        assert "valid" in tags


class TestGetTagUsage:
    def test_empty_returns_empty(self):
        """DBTAG-DT-004: 空 DB 回傳空清單。"""
        db = _make_db()
        assert db.get_tag_usage() == []

    def test_counts_correctly(self):
        """DBTAG-DT-005: 正確計算各 tag 出現次數。"""
        db = _make_db()
        _insert(db, "A", ["wave1", "pr1"])
        _insert(db, "B", ["wave1", "pr2"])
        _insert(db, "C", ["pr1"])

        usage = {row["tag"]: row["count"] for row in db.get_tag_usage()}
        assert usage["wave1"] == 2
        assert usage["pr1"] == 2
        assert usage["pr2"] == 1

    def test_sorted_by_count_desc(self):
        """DBTAG-DT-006: 結果按 count 降序排列。"""
        db = _make_db()
        for i in range(5):
            _insert(db, f"topic-{i}", ["popular"])
        _insert(db, "one-off", ["rare"])

        result = db.get_tag_usage()
        counts = [row["count"] for row in result]
        assert counts == sorted(counts, reverse=True)

    def test_records_latest_at(self):
        """DBTAG-DT-007: latest_at 反映最新記錄時間。"""
        db = _make_db()
        r1 = HandoverRecord(
            id=str(uuid.uuid4()),
            timestamp="2026-05-24T10:00:00+08:00",
            session_type=SessionType.admin,
            topic="old",
            conversation_summary="old",
            tags=["my-tag"],
        )
        r2 = HandoverRecord(
            id=str(uuid.uuid4()),
            timestamp="2026-05-25T10:00:00+08:00",
            session_type=SessionType.admin,
            topic="new",
            conversation_summary="new",
            tags=["my-tag"],
        )
        db.insert_handover(r1)
        db.insert_handover(r2)

        usage = {row["tag"]: row for row in db.get_tag_usage()}
        assert usage["my-tag"]["latest_at"] == "2026-05-25T10:00:00+08:00"


class TestRenameTag:
    def test_rename_updates_records(self):
        """DBTAG-DT-008: rename_tag 更新含舊 tag 的記錄。"""
        db = _make_db()
        _insert(db, "A", ["old", "keep"])
        _insert(db, "B", ["old"])
        n = db.rename_tag("old", "new")
        assert n == 2
        tags = db.get_all_tags()
        assert "old" not in tags
        assert "new" in tags
        assert "keep" in tags

    def test_rename_preserves_other_tags(self):
        """DBTAG-DT-009: rename 不影響未選中 tag。"""
        db = _make_db()
        _insert(db, "A", ["old", "preserve"])
        db.rename_tag("old", "new")
        tags = db.get_all_tags()
        assert "preserve" in tags

    def test_rename_same_tag_returns_zero(self):
        """DBTAG-EG-002: 新舊名稱相同時回傳 0。"""
        db = _make_db()
        _insert(db, "A", ["tag"])
        assert db.rename_tag("tag", "tag") == 0

    def test_rename_empty_new_tag_raises(self):
        """DBTAG-EG-003: new_tag 空字串 raise ValueError。"""
        db = _make_db()
        with pytest.raises(ValueError):
            db.rename_tag("old", "")


class TestDeleteByTag:
    def test_deletes_matching_records(self):
        """DBTAG-DT-010: delete_by_tag 刪除含指定 tag 的記錄。"""
        db = _make_db()
        _insert(db, "A", ["purge"])
        _insert(db, "B", ["purge", "keep"])
        _insert(db, "C", ["keep"])
        n = db.delete_by_tag("purge")
        assert n == 2
        assert db.count() == 1

    def test_does_not_delete_unrelated(self):
        """DBTAG-DT-011: delete_by_tag 不影響不含指定 tag 的記錄。"""
        db = _make_db()
        _insert(db, "A", ["delete-me"])
        _insert(db, "B", ["keep-me"])
        db.delete_by_tag("delete-me")
        remaining = db.read_recent(last=10)
        assert len(remaining) == 1
        assert remaining[0]["topic"] == "B"

    def test_nonexistent_tag_returns_zero(self):
        """DBTAG-EG-004: 不存在的 tag 回傳 0，不刪除任何記錄。"""
        db = _make_db()
        _insert(db, "A", ["existing"])
        n = db.delete_by_tag("ghost")
        assert n == 0
        assert db.count() == 1
