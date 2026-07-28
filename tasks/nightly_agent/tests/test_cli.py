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


def make_db_with_parked_and_retired(tmp_path: Path) -> Path:
    """建立含 tags / retired_at 欄位的 handover.db，塞入 active / parked / retired 各一筆。"""
    db_dir = tmp_path / ".agents" / "handover"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "handover.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE lessons ("
        "id TEXT PRIMARY KEY, ts TEXT NOT NULL, project TEXT NOT NULL, type TEXT NOT NULL, "
        "key TEXT NOT NULL, insight TEXT NOT NULL, confidence INTEGER NOT NULL, "
        "source TEXT NOT NULL, handover_id TEXT, retrospective_id TEXT, "
        "tags TEXT NOT NULL DEFAULT '[]', retired_at TEXT)"
    )
    rows = [
        ("active", "[]", None),
        ("parked", '["parked", "recurrence-1"]', None),
        ("retired", "[]", "2026-07-01T00:00:00+00:00"),
    ]
    for lesson_id, tags, retired_at in rows:
        conn.execute(
            "INSERT INTO lessons "
            "(id, ts, project, type, key, insight, confidence, source, tags, retired_at) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lesson_id,
                "yibi-stack",
                "pitfall",
                lesson_id,
                "insight",
                5,
                "observed",
                tags,
                retired_at,
            ),
        )
    conn.commit()
    conn.close()
    return db_path


class TestNightlyExcludesParkedAndRetired:
    """NIGHTLY-DT-010..012：park 的目的是不讓未驗證教訓回到 rule 生成管線。"""

    def test_nightly_dt_010_parked_and_retired_are_excluded(self, tmp_path: Path) -> None:
        """NIGHTLY-DT-010: parked 與 retired 教訓不得進 nightly digest"""
        make_db_with_parked_and_retired(tmp_path)

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall"], errors)

        assert errors == []
        assert [r["id"] for r in result] == ["active"], (
            "parked / retired 教訓從側門進了 nightly rule 生成管線"
        )

    def test_nightly_dt_011_missing_columns_do_not_break_the_read(self, tmp_path: Path) -> None:
        """NIGHTLY-DT-011: 舊 schema（無 tags / retired_at）仍可讀，且不過濾

        缺欄位等同「park 與 retire 當時還不存在」，不過濾是正確的；重點是不得因為少了欄位
        就整批讀取失敗。
        """
        make_handover_db(tmp_path, with_retrospective_id=False)

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall"], errors)

        assert errors == []
        assert len(result) == 1

    def test_nightly_dt_012_read_path_stays_read_only(self, tmp_path: Path) -> None:
        """NIGHTLY-DT-012: 讀取路徑不得留下**已 commit** 的 schema 或資料變更

        涵蓋面精確描述（不要放大）：本測試前後快照 schema 與資料列，因此抓得到
        `ALTER TABLE`（rule 07 點名的自我 migration，PR #210 的原始迴歸）與已 commit 的
        `UPDATE` / `INSERT` / `DELETE`。**未 commit 的寫入嘗試不在本測試涵蓋內**——讀取路徑
        不 commit，這類寫入會在連線關閉時回滾，快照自然看不到。

        這一段曾經寫成「插一句 `UPDATE lessons SET confidence = 1` 就會被抓到」，
        re-review 逐字照做後發現該 mutation **仍然存活**（不加 `conn.commit()` 就被回滾）
        ——docstring 宣稱的涵蓋面大於實際做到的，正是本 PR 一路在治的同一種病。
        未 commit 的那一面由下一條 `DT-013` 以 `PRAGMA query_only` 覆蓋。
        """
        db_path = make_db_with_parked_and_retired(tmp_path)

        def snapshot() -> tuple[str, list[tuple[object, ...]]]:
            conn = sqlite3.connect(str(db_path))
            try:
                ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='lessons'").fetchone()[
                    0
                ]
                rows = conn.execute(
                    "SELECT id, ts, project, type, key, insight, confidence, source, "
                    "tags, retired_at FROM lessons ORDER BY id"
                ).fetchall()
            finally:
                conn.close()
            return ddl, rows

        before = snapshot()

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            _load_mycelium_lessons(24, ["pitfall"], errors)

        after = snapshot()
        assert after[0] == before[0], "讀取路徑改動了 schema"
        assert after[1] == before[1], "讀取路徑改動了資料列"

    def test_nightly_dt_013_read_path_survives_a_query_only_connection(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """NIGHTLY-DT-013: 讀取路徑在 `PRAGMA query_only` 下必須完全不嘗試寫入

        補上 DT-012 抓不到的那一面：**未 commit** 的寫入嘗試。`query_only` 讓任何寫入直接
        raise，因此連「寫了但被回滾」都會被抓到。rule 07 點名的真正危害（read-only mount、
        被並行 writer 鎖住的 DB）恰恰在寫入被回滾時也會發生，所以這一面必須有覆蓋。
        """
        make_db_with_parked_and_retired(tmp_path)

        real_connect = sqlite3.connect

        def query_only_connect(database: str) -> sqlite3.Connection:
            conn = real_connect(database)
            conn.execute("PRAGMA query_only = ON")
            return conn

        monkeypatch.setattr(sqlite3, "connect", query_only_connect)

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall"], errors)

        assert errors == [], f"唯讀連線下讀取路徑嘗試了寫入：{errors}"
        assert [r["id"] for r in result] == ["active"]

    def test_nightly_dt_014_integer_ids_are_normalized_before_exclusion(
        self, tmp_path: Path
    ) -> None:
        """NIGHTLY-DT-014: id 以 INTEGER 寫入時，parked 過濾仍生效

        SQLite 無強型別，任何以 int 寫入 `lessons.id` 的來源會讓 `"5" != 5`——排除集合是
        `str`，比對端若不轉型就靜默漏過，parked 教訓回到 nightly 管線。兩端都 `str()` 的
        那行改動在此之前零測試涵蓋（re-review 實證：改回不轉型仍全綠）。
        """
        db_dir = tmp_path / ".agents" / "handover"
        db_dir.mkdir(parents=True)
        conn = sqlite3.connect(str(db_dir / "handover.db"))
        conn.execute(
            "CREATE TABLE lessons ("
            "id, ts TEXT NOT NULL, project TEXT NOT NULL, type TEXT NOT NULL, "
            "key TEXT NOT NULL, insight TEXT NOT NULL, confidence INTEGER NOT NULL, "
            "source TEXT NOT NULL, handover_id TEXT, retrospective_id TEXT, "
            "tags TEXT NOT NULL DEFAULT '[]', retired_at TEXT)"
        )
        for lesson_id, tags in [(5, '["parked", "recurrence-1"]'), (6, "[]")]:
            conn.execute(
                "INSERT INTO lessons "
                "(id, ts, project, type, key, insight, confidence, source, tags) "
                "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
                (
                    lesson_id,
                    "yibi-stack",
                    "pitfall",
                    f"k{lesson_id}",
                    "insight",
                    5,
                    "observed",
                    tags,
                ),
            )
        conn.commit()
        conn.close()

        errors: list[str] = []
        with patch(f"{CLI}.Path.home", return_value=tmp_path):
            result = _load_mycelium_lessons(24, ["pitfall"], errors)

        assert errors == []
        assert [str(r["id"]) for r in result] == ["6"], (
            "INTEGER id 的 parked 教訓漏過過濾——排除集合是 str，比對端未轉型"
        )


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
