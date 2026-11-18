"""Tests for protect-worktree.py hook."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "protect-worktree.py"

_WT = ".claude/worktrees/t"


def run_hook(payload: dict) -> int:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
    )
    return result.returncode


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def _enter(branch: str | None = None, name: str | None = None) -> dict:
    body: dict = {}
    if branch is not None:
        body["branch"] = branch
    if name is not None:
        body["name"] = name
    return {"tool_name": "EnterWorktree", "tool_input": body}


class TestBashWorktreeAdd:
    def test_block_checkout_main(self) -> None:
        """WTHOOK-DT-001: git worktree add <path> main"""
        assert run_hook(_bash(f"git worktree add {_WT} main")) == 2

    def test_block_checkout_master(self) -> None:
        """WTHOOK-DT-002: git worktree add <path> master"""
        assert run_hook(_bash(f"git worktree add {_WT} master")) == 2

    def test_block_dash_b_main(self) -> None:
        """WTHOOK-DT-003: -b main creates branch named main"""
        assert run_hook(_bash(f"git worktree add -b main {_WT}")) == 2

    def test_block_dash_capital_b_main(self) -> None:
        """WTHOOK-DT-004: -B main force-creates branch named main"""
        assert run_hook(_bash(f"git worktree add -B main {_WT}")) == 2

    def test_block_refs_heads_main(self) -> None:
        """WTHOOK-DT-005: refs/heads/main normalized to main"""
        assert run_hook(_bash(f"git worktree add {_WT} refs/heads/main")) == 2

    def test_allow_detach_long(self) -> None:
        """WTHOOK-DT-006: --detach does not lock the branch ref"""
        assert run_hook(_bash(f"git worktree add --detach {_WT} main")) == 0

    def test_allow_detach_short(self) -> None:
        """WTHOOK-DT-007: -d is the short form of --detach"""
        assert run_hook(_bash(f"git worktree add -d {_WT} main")) == 0

    def test_allow_feature_branch(self) -> None:
        """WTHOOK-DT-008: checkout a non-protected branch is allowed"""
        assert run_hook(_bash(f"git worktree add {_WT} feature-branch")) == 0

    def test_allow_dash_b_feature(self) -> None:
        """WTHOOK-DT-009: -b with non-protected name is allowed"""
        assert run_hook(_bash(f"git worktree add -b feature-x {_WT}")) == 0

    def test_allow_dash_b_feature_from_main(self) -> None:
        """WTHOOK-DT-010: start-point is main, branch is feature-x"""
        assert run_hook(_bash(f"git worktree add -b feature-x {_WT} main")) == 0

    def test_allow_quoted_feature(self) -> None:
        """WTHOOK-DT-011: shlex.split strips quotes; 'feature' is allowed"""
        assert run_hook(_bash(f"git worktree add {_WT} 'feature'")) == 0

    def test_block_quoted_main(self) -> None:
        """WTHOOK-DT-012: shlex.split strips quotes; \"main\" is blocked"""
        assert run_hook(_bash(f'git worktree add {_WT} "main"')) == 2

    def test_allow_unrelated_command(self) -> None:
        """WTHOOK-DT-013: unrelated git command is allowed"""
        assert run_hook(_bash("git status")) == 0

    def test_fast_exit_no_worktree_keyword(self) -> None:
        """WTHOOK-DT-014: no 'worktree' keyword triggers fast-exit"""
        assert run_hook(_bash("git log --oneline -5")) == 0


class TestEnterWorktree:
    def test_block_branch_main(self) -> None:
        """WTHOOK-DT-015: EnterWorktree with branch=main"""
        assert run_hook(_enter(branch="main")) == 2

    def test_allow_name_only(self) -> None:
        """WTHOOK-DT-016: EnterWorktree with name (no branch param)"""
        assert run_hook(_enter(name="my-feature")) == 0


class TestFailOpen:
    def test_invalid_json(self) -> None:
        """WTHOOK-EG-001: fail-open on invalid JSON"""
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_null_tool_input(self) -> None:
        """WTHOOK-EG-002: fail-open when tool_input is null"""
        assert run_hook({"tool_name": "Bash", "tool_input": None}) == 0

    def test_non_string_command(self) -> None:
        """WTHOOK-EG-003: fail-open when command is not a string"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": 42}}) == 0

    def test_non_dict_json(self) -> None:
        """WTHOOK-EG-004: fail-open when top-level JSON is an array"""
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input='["not", "a", "dict"]',
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_other_tool_name(self) -> None:
        """WTHOOK-EG-005: non-Bash/non-EnterWorktree tool is allowed"""
        assert run_hook({"tool_name": "Read", "tool_input": {"file_path": "/tmp/a"}}) == 0


_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(  # nosec B603 B607
        ["git", *args], cwd=cwd, check=True, env=_GIT_ENV, capture_output=True
    )


def _repo_with_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """建立主 repo（在 main，另有 master branch）與一個 linked worktree（在 feat）。"""
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _git(["init", "-q", "-b", "main"], main_repo)
    _git(
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "s"],
        main_repo,
    )
    _git(["branch", "master"], main_repo)
    wt = tmp_path / "wt"
    _git(["worktree", "add", "-q", "-b", "feat", str(wt)], main_repo)
    return main_repo, wt


def run_hook_in(payload: dict, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd),
    )


class TestCheckoutMainInsideLinkedWorktree:
    """Vector 3：linked worktree 裡 `git checkout/switch main|master` 會佔用 main ref。

    rule 15「A Linked Worktree Must Never Check Out main」說 hook enforce 這條不變量，但舊版只擋
    EnterWorktree 與 `git worktree add`，worktree 建好之後再切到 main 不受擋。
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "git checkout main",
            "git switch main",
            "git checkout master",
            "git switch refs/heads/main",
            "git fetch origin && git checkout main",
        ],
    )
    def test_block_in_linked_worktree(self, tmp_path: Path, cmd: str) -> None:
        """WTHOOK-DT-017: linked worktree 內切到 main/master -> 攔截，原因走 stderr。"""
        _, wt = _repo_with_linked_worktree(tmp_path)
        res = run_hook_in(_bash(cmd), wt)
        assert res.returncode == 2
        assert "BLOCKED" in res.stderr

    def test_block_git_dash_c_into_linked_worktree(self, tmp_path: Path) -> None:
        """WTHOOK-DT-018: 在主 repo 用 `git -C <worktree> switch main` -> 攔截（看 -C 的目標）。"""
        main_repo, wt = _repo_with_linked_worktree(tmp_path)
        assert run_hook_in(_bash(f"git -C {wt} switch main"), main_repo).returncode == 2

    @pytest.mark.parametrize(
        "cmd",
        [
            "git checkout feat",
            "git checkout main -- f.txt",
            "git checkout -b main-fix",
            "git switch -c hotfix main",
            "git checkout -",
            "echo git checkout main",
        ],
    )
    def test_allow_other_forms_in_linked_worktree(self, tmp_path: Path, cmd: str) -> None:
        """WTHOOK-DT-019: 切到其他 branch、從 main 還原檔案、以 main 為起點建新 branch -> 放行。"""
        _, wt = _repo_with_linked_worktree(tmp_path)
        assert run_hook_in(_bash(cmd), wt).returncode == 0

    def test_allow_in_main_repo(self, tmp_path: Path) -> None:
        """WTHOOK-DT-020: 主 repo 切回 main 是正常操作 -> 放行（負向對照）。"""
        main_repo, _ = _repo_with_linked_worktree(tmp_path)
        _git(["checkout", "-q", "-b", "other"], main_repo)
        assert run_hook_in(_bash("git checkout main"), main_repo).returncode == 0

    def test_allow_outside_git(self, tmp_path: Path) -> None:
        """WTHOOK-EG-006: 不在 git repo 裡 -> 放行（無法判斷就不擋）。"""
        assert run_hook_in(_bash("git checkout main"), tmp_path).returncode == 0
