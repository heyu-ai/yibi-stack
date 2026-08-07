"""NIGHTLY-pr_creator tests：branch slug 非 ASCII 處理、gh --repo fallback。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tasks.nightly_agent.models import NightlyAgentConfig
from tasks.nightly_agent.pr_creator import PRCreator, _slugify_title

PR_CREATOR = "tasks.nightly_agent.pr_creator"


class TestSlugifyTitle:
    def test_ascii_title_kept_as_kebab(self) -> None:
        """NIGHTLY-EG-001: 純英文 title 維持原本行為（小寫、非英數轉 dash）。"""
        assert _slugify_title("Chinese input triggers English reply", "cluster123") == (
            "chinese-input-triggers-english-reply"
        )

    def test_all_cjk_title_falls_back_to_cluster_id(self) -> None:
        """NIGHTLY-EG-002: 全中文 title 過濾後為空，須 fallback 為 cluster_id 前 8 碼。"""
        safe = _slugify_title("中文輸入觸發英文回覆", "3f9a1b2c-d4e5-6789-abcd-ef0123456789")
        assert safe == "3f9a1b2c"

    def test_mixed_cjk_ascii_collapses_to_single_dash(self) -> None:
        """NIGHTLY-EG-003: 中英夾雜時，連續非英數字元只變成單一 dash，不留下多個連續 dash。"""
        safe = _slugify_title("中文 input → 英文 reply", "clusterid")
        assert "--" not in safe
        assert not safe.startswith("-")
        assert not safe.endswith("-")

    def test_result_never_ends_with_dash_after_truncation(self) -> None:
        """NIGHTLY-EG-004: 截斷到 40 字元後也不可留下結尾 dash（防止 git ref 以 - 結尾）。"""
        title = "a" * 39 + "中" + "b" * 10
        safe = _slugify_title(title, "clusterid")
        assert safe == "a" * 39
        assert not safe.endswith("-")

    def test_fallback_used_when_cluster_id_also_has_no_safe_chars(self) -> None:
        """NIGHTLY-EG-007: title 與 cluster_id 都過濾後為空的極端狀況，仍須回傳非空字串。"""
        assert _slugify_title("中文中文", "中文") == "untitled"


class TestGhPrCreate:
    @staticmethod
    def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    @patch(f"{PR_CREATOR}._get_main_repo")
    def test_omits_repo_flag_when_github_repo_unset(
        self, mock_main_repo: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-EG-005: github_repo 未設定時不可傳 --repo .，應完全省略 --repo flag。"""
        mock_main_repo.return_value = tmp_path
        creator = PRCreator(NightlyAgentConfig(github_repo=""))
        with patch(f"{PR_CREATOR}.subprocess.run") as mock_run:
            mock_run.return_value = self._completed("https://github.com/o/r/pull/1\n")
            creator._gh_pr_create("branch", "title", "body")
        argv = mock_run.call_args.args[0]
        assert "--repo" not in argv
        assert "." not in argv

    @patch(f"{PR_CREATOR}._get_main_repo")
    def test_includes_repo_flag_when_github_repo_set(
        self, mock_main_repo: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-EG-006: github_repo 有值時應以 OWNER/REPO 格式傳入 --repo。"""
        mock_main_repo.return_value = tmp_path
        creator = PRCreator(NightlyAgentConfig(github_repo="owner/repo"))
        with patch(f"{PR_CREATOR}.subprocess.run") as mock_run:
            mock_run.return_value = self._completed("https://github.com/o/r/pull/1\n")
            creator._gh_pr_create("branch", "title", "body")
        argv = mock_run.call_args.args[0]
        assert "--repo" in argv
        assert argv[argv.index("--repo") + 1] == "owner/repo"
