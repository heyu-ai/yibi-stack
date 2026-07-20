"""NIGHTLY-cli tests：_load_mycelium_lessons 的 schema 相容性。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tasks.nightly_agent.cli import _load_mycelium_lessons, cli, emit_failure_signal
from tasks.nightly_agent.models import NightlyAgentConfig
from tasks.nightly_agent.tests.test_drafter import make_cluster

CLI = "tasks.nightly_agent.cli"


def make_handover_db(tmp_path: Path, *, with_retrospective_id: bool) -> Path:
    """建立測試用 handover.db；with_retrospective_id 控制是否模擬已 migrate 過的 schema。"""
    db_dir = tmp_path / ".agents" / "handover"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "handover.db"

    columns = [
        "id TEXT PRIMARY KEY",
        "ts TEXT NOT NULL",
        "project TEXT NOT NULL",
        "type TEXT NOT NULL",
        "key TEXT NOT NULL",
        "insight TEXT NOT NULL",
        "confidence INTEGER NOT NULL",
        "source TEXT NOT NULL",
        "handover_id TEXT",
    ]
    if with_retrospective_id:
        columns.append("retrospective_id TEXT")

    conn = sqlite3.connect(str(db_path))
    conn.execute(f"CREATE TABLE lessons ({', '.join(columns)})")
    if with_retrospective_id:
        conn.execute(
            "INSERT INTO lessons "
            "(id, ts, project, type, key, insight, confidence, source, retrospective_id) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
            ("l1", "yibi-stack", "pitfall", "k1", "test insight", 5, "observed", "r1"),
        )
    else:
        conn.execute(
            "INSERT INTO lessons (id, ts, project, type, key, insight, confidence, source) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)",
            ("l1", "yibi-stack", "pitfall", "k1", "test insight", 5, "observed"),
        )
    conn.commit()
    conn.close()
    return db_path


class TestLoadMyceliumLessons:
    def test_pre_migration_schema_falls_back_to_null_retrospective_id(self, tmp_path: Path) -> None:
        """舊 handover.db 沒有 retrospective_id 欄位時，讀取仍成功，欄位回傳 None。"""
        db_path = make_handover_db(tmp_path, with_retrospective_id=False)
        schema_before = (
            sqlite3.connect(str(db_path))
            .execute("SELECT sql FROM sqlite_master WHERE name='lessons'")
            .fetchone()[0]
        )

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        schema_after = (
            sqlite3.connect(str(db_path))
            .execute("SELECT sql FROM sqlite_master WHERE name='lessons'")
            .fetchone()[0]
        )

        assert errors == []
        assert len(result) == 1
        assert result[0]["retrospective_id"] is None
        assert schema_after == schema_before, "讀取路徑不應寫入 schema（唯讀）"

    def test_migrated_schema_returns_retrospective_id(self, tmp_path: Path) -> None:
        """已 migrate 過的 handover.db（有 retrospective_id 欄位）正常回傳該值。"""
        make_handover_db(tmp_path, with_retrospective_id=True)

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        assert errors == []
        assert len(result) == 1
        assert result[0]["retrospective_id"] == "r1"

    def test_missing_lessons_table_returns_empty_with_warning(self, tmp_path: Path) -> None:
        """handover.db 存在但沒有 lessons table（極舊版本）：回傳空清單，記錄錯誤而非拋出例外。"""
        db_dir = tmp_path / ".agents" / "handover"
        db_dir.mkdir(parents=True)
        db_path = db_dir / "handover.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handovers (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        assert result == []
        assert len(errors) == 1
        assert "no such table" in errors[0].lower()

    def test_missing_db_file_returns_empty_no_error(self, tmp_path: Path) -> None:
        """handover.db 檔案完全不存在（首次使用）：回傳空清單，不記錄錯誤。"""
        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors)

        assert result == []
        assert errors == []


class TestFailureSignal:
    def test_nightly_failure_001_failed_run_writes_visible_marker(self, tmp_path: Path) -> None:
        """NIGHTLY-FAILURE-001：非預期失敗會寫入 marker 與 digest 的 FAIL 行。"""
        digest_dir = tmp_path / "digests"
        marker = emit_failure_signal(RuntimeError("測試故障"), digest_dir)
        digest = next(digest_dir.glob("digest-*.md"))
        assert "[FAIL]" in marker.read_text(encoding="utf-8")
        assert "測試故障" in digest.read_text(encoding="utf-8")

    def test_all_clusters_fail_emits_marker_and_fail_digest(self, tmp_path: Path) -> None:
        """所有 eligible clusters 草擬失敗仍留下排程可見失敗訊號。"""
        digest_dir = tmp_path / "digests"
        config = NightlyAgentConfig(
            digest_dir=str(digest_dir),
            friction_state_file=str(tmp_path / "frictions.json"),
        )
        cluster = make_cluster()
        with (
            patch("tasks.nightly_agent.config.load_config", return_value=config),
            patch("tasks.nightly_agent.extractor.TranscriptExtractor.extract", return_value=[]),
            patch(f"{CLI}._load_mycelium_lessons", return_value=[]),
            patch("tasks.nightly_agent.classifier.FrictionClassifier.classify", return_value=[]),
            patch(
                "tasks.nightly_agent.clusterer.FrictionClusterer.cluster", return_value=[cluster]
            ),
            patch(
                "tasks.nightly_agent.clusterer.FrictionClusterer.eligible", return_value=[cluster]
            ),
            patch(
                "tasks.nightly_agent.governance.FrictionRegistry.find_duplicate", return_value=None
            ),
            patch(
                "tasks.nightly_agent.drafter.ArtifactDrafter.draft",
                side_effect=RuntimeError("草擬故障"),
            ),
        ):
            result = CliRunner().invoke(cli, ["run"])

        assert result.exit_code == 0
        assert "[FAIL]" in (tmp_path / "LAST_FAILURE").read_text(encoding="utf-8")
        digest = next(digest_dir.glob("digest-*.md"))
        assert "[FAIL]" in digest.read_text(encoding="utf-8")
