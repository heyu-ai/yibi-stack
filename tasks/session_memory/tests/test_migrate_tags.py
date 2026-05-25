"""Tests for migrate.py tag-related migration helpers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from tasks.session_memory.db import AgentsDB
from tasks.session_memory.migrate import ensure_tag_index, rebuild_tags_index
from tasks.session_memory.models import HandoverRecord, SessionType


def _make_db_file(tmp_path: Path) -> Path:
    db_path = tmp_path / "handover.db"
    db = AgentsDB(db_path)
    db.init_db()
    db.close()
    return db_path


def _insert_with_tags(db_path: Path, topic: str, tags: list[str]) -> None:
    db = AgentsDB(db_path)
    db.init_db()
    db.insert_handover(
        HandoverRecord(
            id=str(uuid.uuid4()),
            timestamp="2026-05-25T10:00:00+08:00",
            session_type=SessionType.admin,
            topic=topic,
            conversation_summary="summary",
            tags=tags,
        )
    )
    db.close()


class TestEnsureTagIndex:
    def test_returns_true_when_db_exists(self, tmp_path: Path) -> None:
        """MGTAG-DT-001: DB 存在時回傳 True。"""
        db_path = _make_db_file(tmp_path)
        result = ensure_tag_index(db_path=db_path)
        assert result is True

    def test_returns_false_when_db_missing(self, tmp_path: Path) -> None:
        """MGTAG-DT-002: DB 不存在時回傳 False（跳過）。"""
        result = ensure_tag_index(db_path=tmp_path / "nonexistent.db")
        assert result is False

    def test_idempotent(self, tmp_path: Path) -> None:
        """MGTAG-DT-003: 多次呼叫不 raise（冪等）。"""
        db_path = _make_db_file(tmp_path)
        ensure_tag_index(db_path=db_path)
        ensure_tag_index(db_path=db_path)


class TestRebuildTagsIndex:
    def test_creates_cache_file(self, tmp_path: Path, monkeypatch) -> None:
        """MGTAG-DT-004: 建立 tags_index.json 快取檔案。"""
        from tasks.session_memory import config as cfg

        monkeypatch.setattr(cfg, "AGENTS_HOME", tmp_path)
        db_path = _make_db_file(tmp_path)
        _insert_with_tags(db_path, "A", ["wave1", "pr-retro"])
        _insert_with_tags(db_path, "B", ["wave1"])

        result = rebuild_tags_index(db_path=db_path)

        cache_path = tmp_path / "_cache" / "tags_index.json"
        assert cache_path.exists()
        cached = json.loads(cache_path.read_text())
        assert cached["wave1"] == 2
        assert cached["pr-retro"] == 1
        assert result == cached

    def test_empty_db_creates_empty_cache(self, tmp_path: Path, monkeypatch) -> None:
        """MGTAG-DT-005: 空 DB 建立空快取。"""
        from tasks.session_memory import config as cfg

        monkeypatch.setattr(cfg, "AGENTS_HOME", tmp_path)
        db_path = _make_db_file(tmp_path)
        result = rebuild_tags_index(db_path=db_path)
        assert result == {}

    def test_overwrites_existing_cache(self, tmp_path: Path, monkeypatch) -> None:
        """MGTAG-DT-006: 重建時覆蓋舊快取。"""
        from tasks.session_memory import config as cfg

        monkeypatch.setattr(cfg, "AGENTS_HOME", tmp_path)
        db_path = _make_db_file(tmp_path)

        _insert_with_tags(db_path, "A", ["old-tag"])
        rebuild_tags_index(db_path=db_path)

        db = AgentsDB(db_path)
        db.init_db()
        db.delete_by_tag("old-tag")
        db.close()

        result = rebuild_tags_index(db_path=db_path)
        assert "old-tag" not in result
