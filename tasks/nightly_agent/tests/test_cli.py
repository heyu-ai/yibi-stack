"""NIGHTLY-cli tests：_load_mycelium_lessons 的 schema 相容性。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tasks.nightly_agent.cli import _load_mycelium_lessons, cli, emit_failure_signal
from tasks.nightly_agent.models import ArtifactProposal, ArtifactType, NightlyAgentConfig
from tasks.nightly_agent.models import TestResult as ArtifactTestResult
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

    def test_genuine_io_failure_is_fatal_not_benign(self, tmp_path: Path) -> None:
        """真正的 I/O 故障（磁碟讀取失敗、權限問題等，`OSError`）跟良性的 schema drift
        （`sqlite3.OperationalError`，例如缺 lessons table）不是同一類——前者必須計入
        `fatal_errors`，否則無論多嚴重的儲存層問題都只會產生一則 [WARN]，exit code
        仍是 0，排程層完全看不到（PR #349 mob review Important finding）。"""
        db_path = make_handover_db(tmp_path, with_retrospective_id=True)
        assert db_path.exists()

        errors: list[str] = []
        fatal_errors: list[str] = []
        with (
            patch(f"{CLI}.Path.home", return_value=tmp_path),
            patch("sqlite3.connect", side_effect=OSError("disk I/O error")),
        ):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors, fatal_errors)

        assert result == []
        assert len(errors) == 1
        assert len(fatal_errors) == 1
        assert "I/O" in fatal_errors[0] or "disk" in fatal_errors[0].lower()

    def test_operational_error_other_than_missing_table_is_fatal(self, tmp_path: Path) -> None:
        """`sqlite3.OperationalError` 涵蓋的範圍比「缺 lessons table」廣得多，也包含
        `database is locked`、`unable to open database file` 等真正的資料庫層故障
        （Codex round-2 mob review 指出：只分 OperationalError vs OSError 兩類不夠，
        OperationalError 內部「缺 table」以外的訊息也該是 fatal，不能全部歸為良性）。"""
        db_path = make_handover_db(tmp_path, with_retrospective_id=True)
        assert db_path.exists()

        errors: list[str] = []
        fatal_errors: list[str] = []
        with (
            patch(f"{CLI}.Path.home", return_value=tmp_path),
            patch(
                "sqlite3.connect",
                side_effect=sqlite3.OperationalError("database is locked"),
            ),
        ):
            result = _load_mycelium_lessons(24, ["pitfall", "pattern"], errors, fatal_errors)

        assert result == []
        assert len(errors) == 1
        assert len(fatal_errors) == 1
        assert "locked" in fatal_errors[0].lower()


class TestFailureSignal:
    def test_nightly_failure_001_failed_run_writes_visible_marker(self, tmp_path: Path) -> None:
        """NIGHTLY-FAILURE-001：非預期失敗會寫入 marker 與 digest 的 FAIL 行。"""
        digest_dir = tmp_path / "digests"
        marker = emit_failure_signal(RuntimeError("測試故障"), digest_dir)
        digest = next(digest_dir.glob("digest-*.md"))
        assert "[FAIL]" in marker.read_text(encoding="utf-8")
        assert "測試故障" in digest.read_text(encoding="utf-8")

    def test_all_clusters_fail_emits_marker_and_fail_digest(self, tmp_path: Path) -> None:
        """所有 eligible clusters 草擬失敗時，除了留下 marker/digest，行程本身也要以非零 exit
        code 結束——scheduler runner 的 status 完全依賴 subprocess exit code 判斷
        success/failed（見 tasks/scheduler/runner.py），沒有非零 exit code，失敗永遠不會被
        排程層看見，只能靠人主動翻 digest 才發現。"""
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

        assert result.exit_code == 1
        assert "[FAIL]" in (tmp_path / "LAST_FAILURE").read_text(encoding="utf-8")
        digest = next(digest_dir.glob("digest-*.md"))
        assert "[FAIL]" in digest.read_text(encoding="utf-8")


def make_proposal(title: str = "test proposal") -> ArtifactProposal:
    return ArtifactProposal(
        id="proposal-123",
        cluster_id="cluster-1",
        artifact_type=ArtifactType.CLAUDE_MD_GOTCHA,
        title=title,
        content="content",
        target_file="CLAUDE.md",
    )


class TestFatalVsBenignErrors:
    """NIGHTLY-FATAL 系列：exit code 只反映真正的執行失敗，良性降級不應誤報排程失敗
    （PR #349 mob review finding 4/5：`errors` 混雜了良性降級與真正失敗）。"""

    def test_nightly_fatal_001_benign_mycelium_warning_alone_exits_zero(
        self, tmp_path: Path
    ) -> None:
        """沒有 eligible clusters、唯一的 errors 來源是良性的 mycelium read warning
        （例如舊 handover.db 缺 lessons table）時，exit code 必須是 0——這種降級是
        `test_missing_lessons_table_returns_empty_with_warning` 明確支援的行為，不是失敗。
        digest/`LAST_FAILURE` 仍然照寫（給人看的完整記錄），只是不影響 exit code。"""
        digest_dir = tmp_path / "digests"
        config = NightlyAgentConfig(digest_dir=str(digest_dir))

        def _fake_load(
            hours: int, lesson_types: list[str], errors: list[str], fatal_errors: list[str]
        ) -> list[object]:
            errors.append("mycelium read error: no such table: lessons")
            return []

        with (
            patch("tasks.nightly_agent.config.load_config", return_value=config),
            patch("tasks.nightly_agent.extractor.TranscriptExtractor.extract", return_value=[]),
            patch(f"{CLI}._load_mycelium_lessons", side_effect=_fake_load),
            patch("tasks.nightly_agent.classifier.FrictionClassifier.classify", return_value=[]),
            patch("tasks.nightly_agent.clusterer.FrictionClusterer.cluster", return_value=[]),
            patch("tasks.nightly_agent.clusterer.FrictionClusterer.eligible", return_value=[]),
        ):
            result = CliRunner().invoke(cli, ["run"])

        assert result.exit_code == 0
        assert "[FAIL]" in (tmp_path / "LAST_FAILURE").read_text(encoding="utf-8")

    def test_nightly_fatal_002_friction_already_resolved_does_not_fail_exit_code(
        self, tmp_path: Path
    ) -> None:
        """test 在套用 artifact 前就通過（`previously_failed=False`，代表 friction 已被
        別的地方處理掉）：`errors` 仍記一筆給 digest 看，但這不是執行失敗，exit code 須為 0。"""
        digest_dir = tmp_path / "digests"
        config = NightlyAgentConfig(
            digest_dir=str(digest_dir),
            friction_state_file=str(tmp_path / "frictions.json"),
        )
        cluster = make_cluster()
        proposal = make_proposal()
        already_resolved = ArtifactTestResult(
            proposal_id=proposal.id,
            test_file="test.json",
            passed=False,
            previously_failed=False,
            before_output="before",
            after_output="after",
            error="套用 artifact 前 lint 已通過；friction 可能已修正，略過 PR",
        )

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
            patch("tasks.nightly_agent.drafter.ArtifactDrafter.draft", return_value=proposal),
            patch(
                "tasks.nightly_agent.tester.TestValidator.validate",
                return_value=already_resolved,
            ),
        ):
            result = CliRunner().invoke(cli, ["run"])

        assert result.exit_code == 0

    def test_nightly_fatal_003_genuine_validation_failure_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """test 在套用 artifact 前就失敗（`previously_failed=True`），套用後仍失敗：
        這是真正的驗證失敗（artifact 沒解決它宣稱要解決的 friction），exit code 必須非零。"""
        digest_dir = tmp_path / "digests"
        config = NightlyAgentConfig(
            digest_dir=str(digest_dir),
            friction_state_file=str(tmp_path / "frictions.json"),
        )
        cluster = make_cluster()
        proposal = make_proposal()
        genuinely_failed = ArtifactTestResult(
            proposal_id=proposal.id,
            test_file="test.json",
            passed=False,
            previously_failed=True,
            before_output="before",
            after_output="after",
            error="套用 artifact 後 lint 仍失敗",
        )

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
            patch("tasks.nightly_agent.drafter.ArtifactDrafter.draft", return_value=proposal),
            patch(
                "tasks.nightly_agent.tester.TestValidator.validate",
                return_value=genuinely_failed,
            ),
        ):
            result = CliRunner().invoke(cli, ["run"])

        assert result.exit_code == 1

    def test_nightly_fatal_004_cleanup_incomplete_still_records_pr_but_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """PR 已成功建立（`create_pr` 正常回傳 `PRRecord`），但 worktree/分支清理未完全
        成功（`cleanup_ok=False`）：PR 仍然算數、被記錄下來（不因清理殘留而假裝 PR 沒
        建立成功），但排程的 exit code 仍要非零，讓「這次執行沒有完全乾淨」被看見
        （PR #349 mob review 的折衷方案：Codex/Claude 主張要讓呼叫端知道、Gemini 主張
        不該讓已成功的 PR 被回報成失敗，兩者在這個設計下同時滿足）。"""
        from tasks.nightly_agent.models import PRRecord

        digest_dir = tmp_path / "digests"
        config = NightlyAgentConfig(
            digest_dir=str(digest_dir),
            friction_state_file=str(tmp_path / "frictions.json"),
        )
        cluster = make_cluster()
        proposal = make_proposal()
        passed_result = ArtifactTestResult(
            proposal_id=proposal.id,
            test_file="test.json",
            passed=True,
            previously_failed=True,
            behaviorally_validated=True,
            before_output="before",
            after_output="after",
        )
        pr_record = PRRecord(
            proposal_id=proposal.id,
            cluster_id=proposal.cluster_id,
            pr_url="https://github.com/o/r/pull/1",
            pr_number=1,
            branch="nightly-agent/2026-01-01/test-abcd1234",
            artifact_file=proposal.target_file,
            test_file="test.json",
            behaviorally_validated=True,
            cleanup_ok=False,
        )

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
            patch("tasks.nightly_agent.drafter.ArtifactDrafter.draft", return_value=proposal),
            patch("tasks.nightly_agent.tester.TestValidator.validate", return_value=passed_result),
            patch("tasks.nightly_agent.pr_creator.PRCreator.create_pr", return_value=pr_record),
            patch("tasks.nightly_agent.governance.FrictionRegistry.record"),
        ):
            result = CliRunner().invoke(cli, ["run"])

        assert result.exit_code == 1
        assert f"PR #{pr_record.pr_number}" in result.output
