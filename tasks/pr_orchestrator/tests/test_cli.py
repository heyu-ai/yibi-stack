"""PROR-ST-02N：cli helper 測試（repo slug 解析）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tasks.pr_orchestrator import config
from tasks.pr_orchestrator.cli import _resolve_repo_slug, cli
from tasks.pr_orchestrator.models import PRInfo


class TestResolveRepoSlug:
    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_020_gh_repo_env_honored_without_subprocess(self, mock_run: MagicMock) -> None:
        """PROR-ST-020: GH_REPO 設定時直接採用，不呼叫 gh（避免 cwd 誤判）"""
        with patch.dict("os.environ", {"GH_REPO": "owner/target-repo"}, clear=False):
            assert _resolve_repo_slug() == "owner/target-repo"
        mock_run.assert_not_called()

    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_021_falls_back_to_gh_when_env_unset(self, mock_run: MagicMock) -> None:
        """PROR-ST-021: GH_REPO 未設時 fallback 到 gh repo view"""
        mock_run.return_value = MagicMock(returncode=0, stdout="owner/cwd-repo\n", stderr="")
        with patch.dict("os.environ", {}, clear=True):
            assert _resolve_repo_slug() == "owner/cwd-repo"
        mock_run.assert_called_once()

    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_022_blank_env_falls_back(self, mock_run: MagicMock) -> None:
        """PROR-ST-022: GH_REPO 為空白字串時視同未設，fallback 到 gh"""
        mock_run.return_value = MagicMock(returncode=0, stdout="owner/cwd-repo", stderr="")
        with patch.dict("os.environ", {"GH_REPO": "  "}, clear=False):
            assert _resolve_repo_slug() == "owner/cwd-repo"
        mock_run.assert_called_once()

    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_023_gh_failure_returns_empty(self, mock_run: MagicMock) -> None:
        """PROR-ST-023: gh 失敗時回空字串（non-fatal）"""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a repo")
        with patch.dict("os.environ", {}, clear=True):
            assert _resolve_repo_slug() == ""

    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_024_slug_fallback_uses_repo_root_cwd(self, mock_run: MagicMock) -> None:
        """PROR-ST-024: GH_REPO 未設時，slug fallback 的 gh 須在 repo_root 執行"""
        mock_run.return_value = MagicMock(returncode=0, stdout="owner/target\n", stderr="")
        target = Path("/repos/yibi-mvp")
        with patch.dict("os.environ", {}, clear=True):
            assert _resolve_repo_slug(repo_root=target) == "owner/target"
        assert mock_run.call_args.kwargs["cwd"] == target


class TestDetectRepoRoot:
    """PROR-ST-03N：detect 的 `--repo-root` 端到端串接。"""

    @patch("tasks.pr_orchestrator.cli.olog.append")
    @patch("tasks.pr_orchestrator.cli.persist_state")
    @patch("tasks.pr_orchestrator.cli._resolve_repo_slug", return_value="owner/target")
    @patch("tasks.pr_orchestrator.cli.state_path")
    @patch("tasks.pr_orchestrator.detector.pr_for_branch")
    @patch("tasks.pr_orchestrator.detector.current_branch")
    def test_pror_st_034_detect_threads_repo_root(
        self,
        mock_branch: MagicMock,
        mock_pr_for_branch: MagicMock,
        mock_state_path: MagicMock,
        mock_slug: MagicMock,
        mock_persist: MagicMock,
        mock_log: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PROR-ST-034: detect --repo-root 把路徑傳給 current_branch 與 pr_for_branch 的 cwd"""
        mock_branch.return_value = "feat-x"
        mock_pr_for_branch.return_value = PRInfo(
            number=42, head_ref_name="feat-x", head_ref_oid="deadbeef", base_ref_name="main"
        )
        no_state = MagicMock()
        no_state.is_file.return_value = False
        mock_state_path.return_value = no_state
        monkeypatch.setattr(config, "_STATE_DIR", tmp_path / "runtime")

        result = CliRunner().invoke(cli, ["detect", "--repo-root", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert mock_branch.call_args.kwargs["cwd"] == tmp_path
        assert mock_pr_for_branch.call_args.kwargs["cwd"] == tmp_path

    def test_pror_st_035_detect_rejects_nonexistent_repo_root(self) -> None:
        """PROR-ST-035: --repo-root 指向不存在的目錄時 fail-loud"""
        result = CliRunner().invoke(cli, ["detect", "--repo-root", "/no/such/dir/xyz"])
        assert result.exit_code == 1
        assert "--repo-root 不是目錄" in result.output

    @patch("tasks.pr_orchestrator.cli.olog.append")
    @patch("tasks.pr_orchestrator.cli.persist_state")
    @patch("tasks.pr_orchestrator.cli._resolve_repo_slug", return_value="owner/target")
    @patch("tasks.pr_orchestrator.cli.state_path")
    @patch("tasks.pr_orchestrator.detector.current_branch")
    @patch("tasks.pr_orchestrator.detector.pr_by_number")
    def test_pror_st_036_detect_pr_threads_repo_root_and_skips_branch(
        self,
        mock_pr_by_number: MagicMock,
        mock_branch: MagicMock,
        mock_state_path: MagicMock,
        mock_slug: MagicMock,
        mock_persist: MagicMock,
        mock_log: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PROR-ST-036: detect --pr N 把 cwd 傳給 pr_by_number，且完全不呼叫 current_branch"""
        mock_pr_by_number.return_value = PRInfo(
            number=88, head_ref_name="feat-y", head_ref_oid="c0ffee", base_ref_name="main"
        )
        no_state = MagicMock()
        no_state.is_file.return_value = False
        mock_state_path.return_value = no_state
        monkeypatch.setattr(config, "_STATE_DIR", tmp_path / "runtime")

        result = CliRunner().invoke(cli, ["detect", "--pr", "88", "--repo-root", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert mock_pr_by_number.call_args.kwargs["cwd"] == tmp_path
        mock_branch.assert_not_called()

    @patch("tasks.pr_orchestrator.detector.pr_by_number")
    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_038_detect_empty_repo_fails_loud(
        self,
        mock_run: MagicMock,
        mock_pr: MagicMock,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(config, "_STATE_DIR", tmp_path / "runtime")
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
        mock_pr.return_value = PRInfo(
            number=42, head_ref_name="feat", head_ref_oid="deadbeef", base_ref_name="main"
        )

        result = CliRunner().invoke(cli, ["detect", "--pr", "42", "--repo-root", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] 無法解析 repo slug" in result.output
        assert not config.state_path("unknown", 42).is_file()

    @patch("tasks.pr_orchestrator.detector.pr_by_number")
    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_039_detect_then_status_resolves_target_repo_from_cwd(
        self,
        mock_run: MagicMock,
        mock_pr: MagicMock,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(config, "_STATE_DIR", tmp_path / "runtime")
        mock_run.return_value = MagicMock(returncode=0, stdout="owner/target\n", stderr="")
        mock_pr.return_value = PRInfo(
            number=42, head_ref_name="feat", head_ref_oid="deadbeef", base_ref_name="main"
        )
        runner = CliRunner()

        detected = runner.invoke(cli, ["detect", "--pr", "42", "--repo-root", str(tmp_path)])
        shown = runner.invoke(cli, ["status", "--pr", "42", "--repo-root", str(tmp_path)])

        assert detected.exit_code == 0, detected.output
        assert shown.exit_code == 0, shown.output
        assert '"repo": "owner/target"' in shown.output
        assert all(call.kwargs["cwd"] == tmp_path for call in mock_run.call_args_list)


class TestResolveRepoSlugEnvPrecedence:
    @patch("tasks.pr_orchestrator.cli.subprocess.run")
    def test_pror_st_037_gh_repo_set_skips_repo_root_subprocess(self, mock_run: MagicMock) -> None:
        """PROR-ST-037: GH_REPO 設定時直接回傳，不因 repo_root 而 spawn gh subprocess"""
        with patch.dict("os.environ", {"GH_REPO": "owner/target"}, clear=False):
            assert _resolve_repo_slug(repo_root=Path("/repos/yibi-mvp")) == "owner/target"
        mock_run.assert_not_called()
