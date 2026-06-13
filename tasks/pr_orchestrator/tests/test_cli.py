"""PROR-ST-02N：cli helper 測試（repo slug 解析）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tasks.pr_orchestrator.cli import _resolve_repo_slug


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
