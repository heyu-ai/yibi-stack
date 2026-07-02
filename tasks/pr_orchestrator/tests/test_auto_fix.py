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
            number=42,
            head_ref_name="feat-auto-fix",
            head_ref_oid="cafebabe",
            base_ref_name="main",
            author_login="bob",
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
    def test_pror_st_003_no_failures_returns_ci_wait(self, *mocks: MagicMock) -> None:
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

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.fetch_failed_check_logs")
    @patch("tasks.pr_orchestrator.auto_fix.pr_diff_files", return_value=["foo.md"])
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_011_fixer_applied_transitions_to_ci_wait(
        self,
        mock_clean: MagicMock,
        mock_diff: MagicMock,
        mock_failures: MagicMock,
        mock_log: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        """PROR-ST-011: fixer applied 成功 -> CI_WAIT，fix_attempts 增加一筆"""
        from unittest.mock import patch as _patch

        from tasks.pr_orchestrator import auto_fix
        from tasks.pr_orchestrator.fixers.base import FixOutcome, FixOutput
        from tasks.pr_orchestrator.models import CIFailure

        mock_failures.return_value = [
            CIFailure(run_id="r1", job_name="lint", log_text="MD013/line-length")
        ]
        mock_fixer = MagicMock()
        mock_fixer.name = "markdownlint"
        mock_fixer.can_fix.return_value = True
        mock_fixer.run.return_value = FixOutput(
            outcome=FixOutcome.applied, files_changed=["foo.md"]
        )

        with (
            _patch("tasks.pr_orchestrator.auto_fix.fixers_for", return_value=[mock_fixer]),
            _patch("tasks.pr_orchestrator.auto_fix._commit_and_push", return_value="abc123"),
        ):
            state = make_state()
            cfg = make_config(allow_fork_fix=True)
            result = auto_fix.run(state, cfg, Path("/tmp"))

        assert result.current_state == PRState.CI_WAIT
        assert len(result.fix_attempts) == 1
        assert result.fix_attempts[0].commit == "abc123"

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.fetch_failed_check_logs")
    @patch("tasks.pr_orchestrator.auto_fix.pr_diff_files", return_value=["foo.py"])
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_012_no_applicable_fixer_blocks(
        self,
        mock_clean: MagicMock,
        mock_diff: MagicMock,
        mock_failures: MagicMock,
        mock_log: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        """PROR-ST-012: 無匹配 fixer 時 -> BLOCKED，blocker reason 含「無對應 fixer」"""
        from unittest.mock import patch as _patch

        from tasks.pr_orchestrator import auto_fix
        from tasks.pr_orchestrator.models import CIFailure

        mock_failures.return_value = [
            CIFailure(run_id="r1", job_name="unknown-check", log_text="some unknown CI failure xyz")
        ]
        with _patch("tasks.pr_orchestrator.auto_fix.fixers_for", return_value=[]):
            state = make_state()
            cfg = make_config(allow_fork_fix=True)
            result = auto_fix.run(state, cfg, Path("/tmp"))

        assert result.current_state == PRState.BLOCKED
        assert any("無對應 fixer" in b.reason for b in result.blockers)

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.fetch_failed_check_logs")
    @patch("tasks.pr_orchestrator.auto_fix.pr_diff_files", return_value=["foo.md"])
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_013_ci_log_fetch_error_blocks(
        self,
        mock_clean: MagicMock,
        mock_diff: MagicMock,
        mock_failures: MagicMock,
        mock_log: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        """PROR-ST-013: fetch_failed_check_logs 拋 RuntimeError -> BLOCKED"""
        from tasks.pr_orchestrator import auto_fix

        mock_failures.side_effect = RuntimeError("gh 指令失敗：permission denied")
        state = make_state()
        cfg = make_config(allow_fork_fix=True)
        result = auto_fix.run(state, cfg, Path("/tmp"))
        assert result.current_state == PRState.BLOCKED
        assert any("無法取得 CI log" in b.reason for b in result.blockers)


class TestAutoFixRepoRootThreading:
    """PROR-ST-04N：auto-fix 的 gh 呼叫必須用目標 repo 的 repo_root 當 cwd。

    根因與 detect 同源：SKILL 在 `uv run --directory <skill_repo>` 下觸發，子行程 cwd 是
    skill repo。`_git` 已吃 repo_root，但 gh 偵測呼叫若不帶 cwd，會讀錯 repo 的 PR
    （fork 檢查與 diff 範圍全部作用在 skill repo），比 detect 更危險。
    """

    @patch("tasks.pr_orchestrator.auto_fix.persist_state")
    @patch("tasks.pr_orchestrator.log.append")
    @patch("tasks.pr_orchestrator.auto_fix.fetch_failed_check_logs", return_value=[])
    @patch("tasks.pr_orchestrator.auto_fix.pr_diff_files", return_value=[])
    @patch("tasks.pr_orchestrator.auto_fix.pr_by_number")
    @patch("tasks.pr_orchestrator.auto_fix.current_user", return_value="alice")
    @patch("tasks.pr_orchestrator.auto_fix._working_tree_clean", return_value=True)
    def test_pror_st_040_gh_calls_receive_repo_root_cwd(
        self,
        mock_clean: MagicMock,
        mock_user: MagicMock,
        mock_pr: MagicMock,
        mock_diff: MagicMock,
        mock_failures: MagicMock,
        mock_log: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        """PROR-ST-040: 四個 gh 偵測呼叫皆帶 cwd=repo_root"""
        from tasks.pr_orchestrator import auto_fix
        from tasks.pr_orchestrator.models import PRInfo

        # author == me → 通過 fork gate，繼續走到 diff/CI-log 擷取
        mock_pr.return_value = PRInfo(
            number=42,
            head_ref_name="feat-auto-fix",
            head_ref_oid="cafebabe",
            base_ref_name="main",
            author_login="alice",
        )
        repo_root = Path("/repos/yibi-mvp")
        state = make_state()
        cfg = make_config(allow_fork_fix=False)

        auto_fix.run(state, cfg, repo_root)

        assert mock_user.call_args.kwargs["cwd"] == repo_root
        assert mock_pr.call_args.kwargs["cwd"] == repo_root
        assert mock_diff.call_args.kwargs["cwd"] == repo_root
        assert mock_failures.call_args.kwargs["cwd"] == repo_root


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

    def test_pror_st_008_prettier_fixture_detected(self) -> None:
        """PROR-ST-008: prettier fixture log 被 PrettierFixer 偵測到"""
        from tasks.pr_orchestrator.fixers.prettier import PrettierFixer

        log = (FIXTURE_DIR / "prettier_failure.txt").read_text()
        assert PrettierFixer().can_fix(log)

    def test_pror_st_009_prettier_no_false_positive_on_ruff(self) -> None:
        """PROR-ST-009: ruff log 不被 PrettierFixer 誤報"""
        from tasks.pr_orchestrator.fixers.prettier import PrettierFixer

        log = (FIXTURE_DIR / "ruff_failure.txt").read_text()
        assert not PrettierFixer().can_fix(log)
