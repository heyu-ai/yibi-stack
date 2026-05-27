"""PROR-ST-NNN：auto-fix loop 測試（mock subprocess）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tasks.pr_orchestrator.config import OrchestratorConfig
from tasks.pr_orchestrator.models import OrchestratorState, PRState


def make_state(**kwargs: object) -> OrchestratorState:
    defaults = {
        "pr_number": 42,
        "branch": "feat-auto-fix",
        "head_sha": "cafebabe",
        "current_state": PRState.AUTO_FIX,
    }
    return OrchestratorState(**{**defaults, **kwargs})


def make_config(**kwargs: object) -> OrchestratorConfig:
    defaults: dict[str, object] = {"max_fix_iterations": 3, "allow_fork_fix": False}
    return OrchestratorConfig(**{**defaults, **kwargs})


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ci_logs"


class TestAutoFixSafetyGates:
    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=False)
    def test_pror_st_001_wip_blocks_fix(
        self, mock_clean: MagicMock, mock_log: MagicMock, mock_persist: MagicMock
    ) -> None:
        """PROR-ST-001: WIP 存在時 auto-fix -> BLOCKED"""
        from tasks.pr_orchestrator import auto_fix

        state = make_state()
        cfg = make_config()
        result = auto_fix.run(state, cfg, Path("/tmp"))
        assert result.current_state == PRState.BLOCKED
        assert any("Working tree" in b.reason for b in result.blockers)

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.current_user", return_value="alice")
    @patch("tasks.pr_orchestrator.auto_fix.pr_by_number")
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_002_fork_pr_blocked(
        self,
        mock_clean: MagicMock,
        mock_pr: MagicMock,
        mock_user: MagicMock,
        mock_log: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        """PROR-ST-002: fork PR 預設 -> BLOCKED"""
        from tasks.pr_orchestrator import auto_fix
        from tasks.pr_orchestrator.models import PRInfo
        mock_pr.return_value = PRInfo(
            number=42, head_ref_name="feat-auto-fix", head_ref_oid="cafebabe",
            base_ref_name="main", author_login="bob"
        )

        state = make_state()
        cfg = make_config(allow_fork_fix=False)
        result = auto_fix.run(state, cfg, Path("/tmp"))
        assert result.current_state == PRState.BLOCKED

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.fetch_failed_check_logs", return_value=[])
    @patch("tasks.pr_orchestrator.auto_fix.pr_diff_files", return_value=[])
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_003_no_failures_returns_ci_wait(
        self, *mocks: MagicMock
    ) -> None:
        """PROR-ST-003: 無 CI 失敗時 -> CI_WAIT"""
        from tasks.pr_orchestrator import auto_fix

        state = make_state()
        cfg = make_config(allow_fork_fix=True)
        result = auto_fix.run(state, cfg, Path("/tmp"))
        assert result.current_state == PRState.CI_WAIT

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.fetch_failed_check_logs")
    @patch("tasks.pr_orchestrator.auto_fix.pr_diff_files", return_value=[])
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_004_max_iterations_blocks(
        self,
        mock_clean: MagicMock,
        mock_diff: MagicMock,
        mock_failures: MagicMock,
        mock_log: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        """PROR-ST-004: 超過 max_fix_iterations -> BLOCKED"""
        from tasks.pr_orchestrator import auto_fix
        from tasks.pr_orchestrator.models import CIFailure, FixAttempt, FixResult

        mock_failures.return_value = [
            CIFailure(run_id="1", job_name="lint", log_text="MD013/line-length")
        ]
        # Simulate 3 prior iterations
        prior_attempts = [
            FixAttempt(iteration=i, fixer="markdownlint", result=FixResult.applied)
            for i in range(1, 4)
        ]
        state = make_state(fix_attempts=prior_attempts)
        cfg = make_config(allow_fork_fix=True, max_fix_iterations=3)
        result = auto_fix.run(state, cfg, Path("/tmp"))
        assert result.current_state == PRState.BLOCKED
        assert any("上限" in b.reason for b in result.blockers)


class TestFixerDetection:
    def test_pror_st_005_markdownlint_fixture_detected(self) -> None:
        """PROR-ST-005: markdownlint fixture log 被 MarkdownlintFixer 偵測到"""
        from tasks.pr_orchestrator.fixers.markdownlint import MarkdownlintFixer

        log = (FIXTURE_DIR / "markdownlint_failure.txt").read_text()
        assert MarkdownlintFixer().can_fix(log)

    def test_pror_st_006_ruff_fixture_detected(self) -> None:
        """PROR-ST-006: ruff fixture log 被 RuffFixer 偵測到"""
        from tasks.pr_orchestrator.fixers.ruff_fixer import RuffFixer

        log = (FIXTURE_DIR / "ruff_failure.txt").read_text()
        assert RuffFixer().can_fix(log)

    def test_pror_st_007_no_cross_detection(self) -> None:
        """PROR-ST-007: markdownlint log 不被 RuffFixer 誤報"""
        from tasks.pr_orchestrator.fixers.ruff_fixer import RuffFixer

        log = (FIXTURE_DIR / "markdownlint_failure.txt").read_text()
        assert not RuffFixer().can_fix(log)
