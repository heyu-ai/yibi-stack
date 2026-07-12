"""測試 migrate：舊 handover.db 與 insights.jsonl 搬遷冪等。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.migrate import (
    migrate_handover,
    migrate_insights,
    migrate_retrospectives_from_handovers,
)
from tasks.mycelium.models import HandoverRecord, SessionType


def _create_legacy_db(path: Path) -> None:
    """建立一個跟舊 `init_db.sh` 一致的 SQLite，寫入 2 筆假資料。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE handovers (
          id TEXT PRIMARY KEY,
          timestamp TEXT NOT NULL,
          operator TEXT NOT NULL DEFAULT 'howie',
          session_type TEXT NOT NULL CHECK(session_type IN ('sdd','debug','discussion','admin')),
          topic TEXT NOT NULL,
          conversation_summary TEXT NOT NULL,
          completed TEXT NOT NULL DEFAULT '[]',
          decisions TEXT NOT NULL DEFAULT '[]',
          blocked TEXT NOT NULL DEFAULT '[]',
          next_priorities TEXT NOT NULL DEFAULT '[]',
          lessons_learned TEXT NOT NULL DEFAULT '[]',
          attempted_approaches TEXT NOT NULL DEFAULT '[]',
          tags TEXT NOT NULL DEFAULT '[]',
          device TEXT,
          agent_type TEXT DEFAULT 'claude',
          subscription_account TEXT,
          branch TEXT,
          working_dir TEXT,
          last_files TEXT DEFAULT '[]',
          test_status TEXT,
          token_usage_estimate TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO handovers (id, timestamp, session_type, topic, conversation_summary, tags)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("old-1", "2026-04-10T00:00:00", "debug", "old topic 1", "summary 1", '["a"]'),
    )
    conn.execute(
        "INSERT INTO handovers (id, timestamp, session_type, topic, conversation_summary)"
        " VALUES (?, ?, ?, ?, ?)",
        ("old-2", "2026-04-11T00:00:00", "admin", "old topic 2", "summary 2"),
    )
    conn.commit()
    conn.close()


class TestMigrateHandover:
    def test_agents_st_020_migrate_copies_all_rows(self, tmp_path: Path) -> None:
        """AGENTS-ST-020：所有 row 都搬到新 DB，並寫 JSONL 鏡像。"""
        legacy = tmp_path / "legacy.db"
        new_db = tmp_path / "new.db"
        new_jsonl = tmp_path / "new.jsonl"
        _create_legacy_db(legacy)

        migrated, skipped, source = migrate_handover(legacy, new_db, new_jsonl)
        assert migrated == 2
        assert skipped == 0
        assert source == legacy

        db = AgentsDB(new_db)
        try:
            db.init_db()
            assert db.count() == 2
        finally:
            db.close()

        lines = new_jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_agents_st_021_migrate_idempotent(self, tmp_path: Path) -> None:
        """AGENTS-ST-021：再跑一次，所有 row 被 skip、不重複寫 JSONL。"""
        legacy = tmp_path / "legacy.db"
        new_db = tmp_path / "new.db"
        new_jsonl = tmp_path / "new.jsonl"
        _create_legacy_db(legacy)

        migrate_handover(legacy, new_db, new_jsonl)
        migrated, skipped, _ = migrate_handover(legacy, new_db, new_jsonl)

        assert migrated == 0
        assert skipped == 2

        db = AgentsDB(new_db)
        try:
            db.init_db()
            assert db.count() == 2
        finally:
            db.close()

    def test_agents_eg_020_no_legacy_db(self, tmp_path: Path) -> None:
        """AGENTS-EG-020：舊 DB 不存在時靜默回傳 (0, 0, None)。"""
        migrated, skipped, source = migrate_handover(
            tmp_path / "nonexistent.db",
            tmp_path / "new.db",
            tmp_path / "new.jsonl",
        )
        assert migrated == 0
        assert skipped == 0
        assert source is None


class TestMigrateInsights:
    def test_agents_st_022_migrate_append_and_fills_account(self, tmp_path: Path) -> None:
        """AGENTS-ST-022：搬遷舊 insights 到新 JSONL，並補上 account=unknown。"""
        legacy = tmp_path / "legacy.jsonl"
        new = tmp_path / "new.jsonl"
        legacy.write_text(
            json.dumps({"id": "i1", "project": "p", "insight_text": "t"})
            + "\n"
            + json.dumps({"id": "i2", "project": "p", "insight_text": "t2"})
            + "\n",
            encoding="utf-8",
        )

        migrated, skipped, _ = migrate_insights(legacy, new)
        assert migrated == 2
        assert skipped == 0

        lines = [
            json.loads(line)
            for line in new.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 2
        assert all(entry.get("account") == "unknown" for entry in lines)

    def test_agents_st_023_insights_idempotent(self, tmp_path: Path) -> None:
        """AGENTS-ST-023：同 id 的 insight 再搬一次會被 skip。"""
        legacy = tmp_path / "legacy.jsonl"
        new = tmp_path / "new.jsonl"
        legacy.write_text(
            json.dumps({"id": "i1", "project": "p", "insight_text": "t"}) + "\n",
            encoding="utf-8",
        )

        migrate_insights(legacy, new)
        migrated, skipped, _ = migrate_insights(legacy, new)

        assert migrated == 0
        assert skipped == 1

    def test_agents_eg_021_no_legacy_jsonl(self, tmp_path: Path) -> None:
        """AGENTS-EG-021：舊 jsonl 不存在時靜默回傳 (0, 0, None)。"""
        migrated, skipped, source = migrate_insights(
            tmp_path / "nope.jsonl", tmp_path / "new.jsonl"
        )
        assert migrated == 0
        assert skipped == 0
        assert source is None


def _make_retro_tagged_handover(**overrides: object) -> HandoverRecord:
    """建立一筆帶 pr-retrospective tag 的舊版 handover 記錄（搬家前的寫入格式）。"""
    defaults: dict[str, object] = {
        "id": "old-retro-1",
        "timestamp": "2026-04-10T00:00:00+00:00",
        "session_type": SessionType.discussion,
        "topic": "Retro: PR #205 - fix bug",
        "conversation_summary": "Problem: bug. Value: fixed. Experience: smooth.",
        "decisions": ["Value: fixed", "Experience: smooth"],
        "completed": ["PR #205 merged"],
        "lessons_learned": ["always test edge cases"],
        "tags": ["pr-retrospective", "main", "pr-205"],
        "device": "mac-mini",
        "project": "yibi-stack",
    }
    return HandoverRecord.model_validate({**defaults, **overrides})


class TestMigrateRetrospectivesFromHandovers:
    def test_retro_mig_st_001_migrates_tagged_rows(self, tmp_path: Path) -> None:
        """RETRO-MIG-ST-001：帶 pr-retrospective tag 的 handover 被搬進 retrospectives。"""
        db_path = tmp_path / "shared.db"
        jsonl_path = tmp_path / "retrospectives.jsonl"

        db = AgentsDB(db_path)
        try:
            db.init_db()
            db.insert_handover(_make_retro_tagged_handover())
        finally:
            db.close()

        migrated, skipped = migrate_retrospectives_from_handovers(
            handover_db_path=db_path, retro_jsonl_path=jsonl_path
        )
        assert migrated == 1
        assert skipped == 0

        db = AgentsDB(db_path)
        try:
            rows = db.read_recent_retrospectives(last=10)
        finally:
            db.close()
        assert len(rows) == 1
        assert rows[0]["id"] == "old-retro-1"
        assert rows[0]["pr_number"] == 205
        assert rows[0]["topic"] == "PR #205 - fix bug"  # "Retro: " 前綴已剝除
        assert "pr-retrospective" not in rows[0]["tags"]  # discriminator tag 已剝除

        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_retro_mig_st_002_idempotent(self, tmp_path: Path) -> None:
        """RETRO-MIG-ST-002：再跑一次，同 id 的記錄被 skip，不重複寫入。"""
        db_path = tmp_path / "shared.db"
        jsonl_path = tmp_path / "retrospectives.jsonl"

        db = AgentsDB(db_path)
        try:
            db.init_db()
            db.insert_handover(_make_retro_tagged_handover())
        finally:
            db.close()

        migrate_retrospectives_from_handovers(handover_db_path=db_path, retro_jsonl_path=jsonl_path)
        migrated, skipped = migrate_retrospectives_from_handovers(
            handover_db_path=db_path, retro_jsonl_path=jsonl_path
        )
        assert migrated == 0
        assert skipped == 1

    def test_retro_mig_st_003_untagged_handovers_ignored(self, tmp_path: Path) -> None:
        """RETRO-MIG-ST-003：沒有 pr-retrospective tag 的一般 handover 不被搬遷。"""
        db_path = tmp_path / "shared.db"
        jsonl_path = tmp_path / "retrospectives.jsonl"

        db = AgentsDB(db_path)
        try:
            db.init_db()
            db.insert_handover(
                HandoverRecord.model_validate(
                    {
                        "id": "normal-1",
                        "timestamp": "2026-04-10T00:00:00+00:00",
                        "session_type": SessionType.debug,
                        "topic": "mid-work handoff",
                        "conversation_summary": "still working on it",
                        "tags": ["main"],
                    }
                )
            )
        finally:
            db.close()

        migrated, skipped = migrate_retrospectives_from_handovers(
            handover_db_path=db_path, retro_jsonl_path=jsonl_path
        )
        assert migrated == 0
        assert skipped == 0

    def test_retro_mig_eg_001_unparseable_pr_number_skipped(self, tmp_path: Path) -> None:
        """RETRO-MIG-EG-001：tag/topic 都解析不出 pr_number 時該筆被跳過（不 raise）。"""
        db_path = tmp_path / "shared.db"
        jsonl_path = tmp_path / "retrospectives.jsonl"

        db = AgentsDB(db_path)
        try:
            db.init_db()
            db.insert_handover(
                _make_retro_tagged_handover(
                    id="no-pr-number",
                    topic="Retro: no PR reference here",
                    tags=["pr-retrospective", "main"],
                )
            )
        finally:
            db.close()

        migrated, skipped = migrate_retrospectives_from_handovers(
            handover_db_path=db_path, retro_jsonl_path=jsonl_path
        )
        assert migrated == 0
        assert skipped == 1
