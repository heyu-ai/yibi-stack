"""NIGHTLY-PR：branch 與 GitHub repo governance 測試。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tasks.nightly_agent.models import ArtifactProposal, ArtifactType, NightlyAgentConfig
from tasks.nightly_agent.pr_creator import PRCreator


def make_proposal(title: str) -> ArtifactProposal:
    return ArtifactProposal(
        id="proposal-123",
        cluster_id="cluster-中文",
        artifact_type=ArtifactType.CLAUDE_MD_GOTCHA,
        title=title,
        content="內容",
        target_file="CLAUDE.md",
    )


class TestPRGovernance:
    @patch("tasks.nightly_agent.pr_creator._get_main_repo")
    def test_nightly_pr_001_cjk_title_branch_has_stable_fallback(
        self, mock_repo: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-001：純 CJK title 不會形成空白或底線垃圾 slug。"""
        mock_repo.return_value = tmp_path
        creator = PRCreator(NightlyAgentConfig(github_repo="owner/repo"))
        with (
            patch.object(creator, "_git"),
            patch.object(creator, "_apply_artifact"),
            patch.object(creator, "_git_commit"),
            patch.object(
                creator,
                "_gh_pr_create",
                return_value="https://github.com/owner/repo/pull/7",
            ),
        ):
            record = creator.create_pr(make_proposal("中文輸入，英文回覆"), MagicMock())

        assert "/friction-" in record.branch
        assert "_" not in record.branch

    @patch("tasks.nightly_agent.pr_creator.subprocess.run")
    @patch("tasks.nightly_agent.pr_creator._get_main_repo")
    def test_nightly_pr_002_gh_receives_explicit_repo(
        self, mock_repo: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-002：gh pr create 必須收到明確 owner/repo。"""
        mock_repo.return_value = tmp_path
        mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/o/r/pull/1\n")
        creator = PRCreator(NightlyAgentConfig(github_repo="o/r"))
        creator._gh_pr_create("branch", "title", "body")
        argv = mock_run.call_args.args[0]
        assert argv[argv.index("--repo") + 1] == "o/r"
        assert "." not in argv
