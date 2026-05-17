"""Tests for protect-worktree.py hook."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / "protect-worktree.py"


def run_hook(payload: dict) -> int:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
    )
    return result.returncode


class TestBashWorktreeAdd:
    def test_block_checkout_main(self) -> None:
        """WTHOOK-DT-001: git worktree add <path> main"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add .claude/worktrees/t main"}}) == 2

    def test_block_checkout_master(self) -> None:
        """WTHOOK-DT-002: git worktree add <path> master"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add .claude/worktrees/t master"}}) == 2

    def test_block_dash_b_main(self) -> None:
        """WTHOOK-DT-003: -b main creates branch named main"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add -b main .claude/worktrees/t"}}) == 2

    def test_block_dash_capital_b_main(self) -> None:
        """WTHOOK-DT-004: -B main force-creates branch named main"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add -B main .claude/worktrees/t"}}) == 2

    def test_block_refs_heads_main(self) -> None:
        """WTHOOK-DT-005: refs/heads/main normalized to main"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add .claude/worktrees/t refs/heads/main"}}) == 2

    def test_allow_detach_long(self) -> None:
        """WTHOOK-DT-006: --detach does not lock the branch ref"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add --detach .claude/worktrees/t main"}}) == 0

    def test_allow_detach_short(self) -> None:
        """WTHOOK-DT-007: -d is the short form of --detach"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add -d .claude/worktrees/t main"}}) == 0

    def test_allow_feature_branch(self) -> None:
        """WTHOOK-DT-008: checkout a non-protected branch is allowed"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add .claude/worktrees/t feature-branch"}}) == 0

    def test_allow_dash_b_feature(self) -> None:
        """WTHOOK-DT-009: -b with non-protected name is allowed"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add -b feature-x .claude/worktrees/t"}}) == 0

    def test_allow_dash_b_feature_from_main(self) -> None:
        """WTHOOK-DT-010: -b feature-x <path> main — start-point is main, branch is feature-x"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add -b feature-x .claude/worktrees/t main"}}) == 0

    def test_allow_quoted_branch_name(self) -> None:
        """WTHOOK-DT-011: shlex.split strips quotes; 'feature' is allowed"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git worktree add .claude/worktrees/t 'feature'"}}) == 0

    def test_block_quoted_main(self) -> None:
        """WTHOOK-DT-012: shlex.split strips quotes; \"main\" is blocked"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": 'git worktree add .claude/worktrees/t "main"'}}) == 2

    def test_allow_unrelated_command(self) -> None:
        """WTHOOK-DT-013: unrelated git command is allowed"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git status"}}) == 0

    def test_fast_exit_no_worktree_keyword(self) -> None:
        """WTHOOK-DT-014: no 'worktree' keyword triggers fast-exit"""
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git log --oneline -5"}}) == 0


class TestEnterWorktree:
    def test_block_branch_main(self) -> None:
        """WTHOOK-DT-015: EnterWorktree with branch=main"""
        assert run_hook({"tool_name": "EnterWorktree", "tool_input": {"branch": "main"}}) == 2

    def test_allow_name_only(self) -> None:
        """WTHOOK-DT-016: EnterWorktree with name (no branch param)"""
        assert run_hook({"tool_name": "EnterWorktree", "tool_input": {"name": "my-feature"}}) == 0


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
