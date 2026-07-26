"""NIGHTLY-PR：branch 與 GitHub repo governance 測試。"""

import subprocess  # nosec B404
from pathlib import Path
from unittest.mock import MagicMock, patch

from tasks.nightly_agent.models import (
    ArtifactProposal,
    ArtifactType,
    NightlyAgentConfig,
)
from tasks.nightly_agent.models import TestResult as ArtifactTestResult
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


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


class TestWorktreeIsolation:
    """NIGHTLY-PR-003 系列：create_pr 絕不能碰到 main repo 的共用工作目錄。"""

    def test_nightly_pr_003_dirty_main_repo_does_not_block_or_get_touched(
        self, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-003：main repo 有未 commit 追蹤檔案改動時，create_pr 仍成功建立
        PR 分支，且完全不觸碰、不讀取 main repo 目前的未 commit 內容。

        重現真實事故（`.runtime/logs/nightly-self-improvement_20260725_210002.log`）：
        main repo 有未 commit 檔案時，舊版直接在 main repo 上 `git checkout -b` 會失敗
        （`would be overwritten by checkout`），同一次排程連續 4 次 create_pr 因此失敗。
        """
        origin = tmp_path / "origin.git"
        _run_git(["init", "--bare", "-b", "main", str(origin)], cwd=tmp_path)

        main_repo = tmp_path / "main-repo"
        _run_git(["init", "-b", "main", str(main_repo)], cwd=tmp_path)
        _run_git(["config", "user.email", "test@example.com"], cwd=main_repo)
        _run_git(["config", "user.name", "Test"], cwd=main_repo)
        (main_repo / "CLAUDE.md").write_text("original content\n", encoding="utf-8")
        _run_git(["add", "CLAUDE.md"], cwd=main_repo)
        _run_git(["commit", "-m", "init"], cwd=main_repo)
        _run_git(["remote", "add", "origin", str(origin)], cwd=main_repo)
        _run_git(["push", "-u", "origin", "main"], cwd=main_repo)

        # 重現事故：main repo 工作目錄有未 commit 的追蹤檔案改動（同一個檔案，最嚴格情境）。
        dirty_content = "original content\nSOMEONE ELSE'S UNCOMMITTED WORK\n"
        (main_repo / "CLAUDE.md").write_text(dirty_content, encoding="utf-8")

        config = NightlyAgentConfig(github_repo="o/r", pr_branch_prefix="nightly-agent")
        with patch("tasks.nightly_agent.pr_creator._get_main_repo", return_value=main_repo):
            creator = PRCreator(config)
        test_result = ArtifactTestResult(
            proposal_id="proposal-123",
            test_file="test.json",
            passed=True,
            previously_failed=True,
            behaviorally_validated=True,
            before_output="before",
            after_output="after",
        )
        with patch.object(creator, "_gh_pr_create", return_value="https://github.com/o/r/pull/9"):
            record = creator.create_pr(make_proposal("worktree isolation test"), test_result)

        assert record.pr_number == 9
        # main repo 的未 commit 內容從頭到尾都沒被動過。
        assert main_repo.joinpath("CLAUDE.md").read_text(encoding="utf-8") == dirty_content
        # 用完即刪：暫存 worktree 不應該留下。
        worktree_dir = main_repo / ".claude" / "worktrees" / record.branch.replace("/", "-")
        assert not worktree_dir.exists()
        # branch 真的推上了 origin，且內容是從乾淨的 origin/main 疊上去的。
        branch_list = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(origin), "branch", "--list", record.branch],
            capture_output=True,
            text=True,
        )
        assert record.branch in branch_list.stdout
        pushed_claude_md = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(origin), "show", f"{record.branch}:CLAUDE.md"],
            capture_output=True,
            text=True,
        )
        assert pushed_claude_md.stdout == "original content\n\n內容\n"
