"""NIGHTLY-PR：branch 與 GitHub repo governance 測試。"""

import hashlib
import re
import subprocess  # nosec B404
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
            patch.object(creator, "_cleanup_worktree", return_value=True),
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
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True, timeout=30
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
        # `git worktree remove` 本身不會刪分支，NIGHTLY-PR-004 的教訓：main repo 也不該
        # 留下這個分支的本地 ref（已推上 origin，本地留著只是累積殘留）。
        local_branch = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(main_repo), "branch", "--list", record.branch],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert local_branch.stdout.strip() == ""
        # branch 真的推上了 origin，且內容是從乾淨的 origin/main 疊上去的。
        branch_list = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(origin), "branch", "--list", record.branch],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert record.branch in branch_list.stdout
        pushed_claude_md = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(origin), "show", f"{record.branch}:CLAUDE.md"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert pushed_claude_md.stdout == "original content\n\n內容\n"

    def test_nightly_pr_004_cleanup_runs_and_branch_is_removed_on_failure(
        self, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-004：`_gh_pr_create` 失敗時（push 已成功、只有開 PR 這步炸掉），
        `finally` 區塊仍要清乾淨暫存 worktree 與其本地 branch，且原始例外要原樣往外拋
        （不能被清理過程的例外蓋掉）。"""
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
        proposal = make_proposal("cleanup on failure test")

        with (
            patch.object(
                creator, "_gh_pr_create", side_effect=RuntimeError("gh pr create 失敗：boom")
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            creator.create_pr(proposal, test_result)

        # branch 名稱由 title + 當天日期 + proposal.id 短前綴決定，跟 create_pr 用同一條
        # 算法重建，用來確認 worktree 目錄與本地 branch 都清乾淨了。
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe = re.sub(r"[^a-z0-9-]+", "-", proposal.title.casefold())[:40].strip("-")
        if not safe:
            stable_id = hashlib.sha256(
                f"{proposal.cluster_id}|{proposal.title}".encode()
            ).hexdigest()[:10]
            safe = f"friction-{stable_id}"
        unique_suffix = proposal.id.replace("-", "") or "noid"
        branch = f"{config.pr_branch_prefix}/{date_str}/{safe}-{unique_suffix}"

        worktree_dir = main_repo / ".claude" / "worktrees" / branch.replace("/", "-")
        assert not worktree_dir.exists()
        local_branch = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(main_repo), "branch", "--list", branch],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert local_branch.stdout.strip() == ""

    @patch("tasks.nightly_agent.pr_creator._get_main_repo")
    def test_nightly_pr_005_cleanup_swallows_its_own_exception(
        self, mock_repo: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-005：`_cleanup_worktree` 自身拋出的例外（非 git 錯誤，例如
        `subprocess.run` 找不到 `git` 執行檔）必須被吞掉、印警告，絕不能往外拋——
        它是從 `create_pr` 的 `finally` 區塊呼叫的，往外拋會蓋掉當時正在處理的
        真正例外，讓呼叫端連 digest／`LAST_FAILURE` marker 都寫不進去。"""
        mock_repo.return_value = tmp_path
        creator = PRCreator(NightlyAgentConfig(github_repo="o/r"))
        with patch(
            "tasks.nightly_agent.pr_creator.subprocess.run",
            side_effect=OSError("boom: git binary vanished"),
        ):
            creator._cleanup_worktree(tmp_path / "nonexistent-worktree", "some/branch")

    @patch("tasks.nightly_agent.pr_creator._get_main_repo")
    def test_nightly_pr_006_registered_worktree_removal_failure_is_not_rmtreed(
        self, mock_repo: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-006：`git worktree remove --force` 失敗、但 git 仍把該路徑註冊為
        使用中的 worktree 時（可能被別的行程用著），只印警告，絕不 `shutil.rmtree`——
        盲目刪除仍被註冊、可能使用中的 worktree 違反 rule 15 Category 4 的精神。"""
        mock_repo.return_value = tmp_path
        creator = PRCreator(NightlyAgentConfig(github_repo="o/r"))
        worktree_dir = tmp_path / "still-in-use-worktree"
        worktree_dir.mkdir()

        def _fake_run(args: list[str], **_kwargs: object) -> MagicMock:
            if "remove" in args:
                return MagicMock(returncode=1, stdout="", stderr="worktree is locked")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("tasks.nightly_agent.pr_creator.subprocess.run", side_effect=_fake_run),
            patch.object(creator, "_is_registered_worktree", return_value=True),
            patch("tasks.nightly_agent.pr_creator.shutil.rmtree") as mock_rmtree,
        ):
            cleaned = creator._cleanup_worktree(worktree_dir, "some/branch")

        mock_rmtree.assert_not_called()
        assert worktree_dir.exists()
        assert cleaned is False

    @patch("tasks.nightly_agent.pr_creator._get_main_repo")
    def test_nightly_pr_007_probe_failure_is_treated_as_registered_not_rmtreed(
        self, mock_repo: MagicMock, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-007：`_is_registered_worktree` 探測本身失敗（`git worktree list`
        非零 exit）時回傳 `None`，`_cleanup_worktree` 必須把 `None` 當成「無法確定、保守
        不刪」處理，絕不能把探測失敗折疊成「未註冊」而去 `shutil.rmtree`——這正是三方
        mob review（code-reviewer、silent-failure-hunter、pr-test-analyzer）各自獨立
        抓到的 fail-open。"""
        mock_repo.return_value = tmp_path
        creator = PRCreator(NightlyAgentConfig(github_repo="o/r"))
        worktree_dir = tmp_path / "maybe-in-use-worktree"
        worktree_dir.mkdir()

        def _fake_run(args: list[str], **_kwargs: object) -> MagicMock:
            if "remove" in args:
                return MagicMock(returncode=1, stdout="", stderr="worktree is locked")
            if "list" in args:
                # 探測本身失敗：git 暫時性錯誤、repo 鎖定等，非「確認未註冊」。
                return MagicMock(returncode=128, stdout="", stderr="fatal: repository locked")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("tasks.nightly_agent.pr_creator.subprocess.run", side_effect=_fake_run),
            patch("tasks.nightly_agent.pr_creator.shutil.rmtree") as mock_rmtree,
        ):
            registered = creator._is_registered_worktree(worktree_dir)
            assert registered is None

            cleaned = creator._cleanup_worktree(worktree_dir, "some/branch")

        mock_rmtree.assert_not_called()
        assert worktree_dir.exists()
        assert cleaned is False

    def test_nightly_pr_008_same_title_different_proposals_get_distinct_branches(
        self, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-008：兩個獨立草擬的 proposal（各自新 UUID，即使 title 完全相同）
        必須產生不同的 worktree 路徑/分支名稱，讓兩個獨立的 nightly-agent process 即使
        同時處理到同一個 friction slug 也不會共用同一個路徑——這是 Codex mob review
        提出的並行執行安全疑慮的具體修法。"""
        with patch("tasks.nightly_agent.pr_creator._get_main_repo", return_value=tmp_path):
            creator = PRCreator(NightlyAgentConfig(github_repo="o/r"))

        proposal_a = ArtifactProposal(
            id="11111111-aaaa-bbbb-cccc-dddddddddddd",
            cluster_id="cluster-x",
            artifact_type=ArtifactType.CLAUDE_MD_GOTCHA,
            title="identical title",
            content="a",
            target_file="CLAUDE.md",
        )
        proposal_b = ArtifactProposal(
            id="22222222-aaaa-bbbb-cccc-dddddddddddd",
            cluster_id="cluster-x",
            artifact_type=ArtifactType.CLAUDE_MD_GOTCHA,
            title="identical title",
            content="b",
            target_file="CLAUDE.md",
        )

        with (
            patch.object(creator, "_cleanup_worktree", return_value=True),
            patch.object(creator, "_git"),
            patch.object(creator, "_apply_artifact"),
            patch.object(creator, "_git_commit"),
            patch.object(creator, "_gh_pr_create", return_value="https://github.com/o/r/pull/1"),
        ):
            record_a = creator.create_pr(proposal_a, MagicMock())
            record_b = creator.create_pr(proposal_b, MagicMock())

        assert record_a.branch != record_b.branch

    def test_nightly_pr_009_worktree_add_failure_still_triggers_cleanup(
        self, tmp_path: Path
    ) -> None:
        """NIGHTLY-PR-009：`git worktree add` 本身失敗（例如上次崩潰留下部分損毀的
        registration）時，`finally` 仍要呼叫 `_cleanup_worktree` 嘗試補救——`worktree add`
        現在位於 try 區塊內，不再是清理保證範圍外的破口。原始例外要原樣往外拋。"""
        with patch("tasks.nightly_agent.pr_creator._get_main_repo", return_value=tmp_path):
            creator = PRCreator(NightlyAgentConfig(github_repo="o/r"))

        def _fake_git(args: list[str], cwd: Path | None = None) -> str:
            if args[:2] == ["worktree", "add"]:
                raise RuntimeError("git worktree add 失敗：boom")
            return ""

        with (
            patch.object(creator, "_git", side_effect=_fake_git) as mock_git,
            patch.object(creator, "_cleanup_worktree", return_value=True) as mock_cleanup,
            pytest.raises(RuntimeError, match="boom"),
        ):
            creator.create_pr(make_proposal("worktree add failure test"), MagicMock())

        # pre-clean（呼叫前）+ finally 的補救（呼叫後），共 2 次。
        assert mock_cleanup.call_count == 2
        assert mock_git.call_count == 1
