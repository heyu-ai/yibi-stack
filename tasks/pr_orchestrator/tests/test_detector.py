"""PROR-ST-NNN：detector mock 測試。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tasks.pr_orchestrator.detector import current_branch, pr_by_number, pr_for_branch


class TestPrForBranch:
    @patch("tasks.pr_orchestrator.detector._gh")
    def test_pror_st_010_single_pr_found(self, mock_gh: MagicMock) -> None:
        """PROR-ST-010: 單一 PR 正確解析"""
        mock_gh.return_value = json.dumps(
            [
                {
                    "number": 99,
                    "headRefName": "feat-foo",
                    "headRefOid": "deadbeef",
                    "baseRefName": "main",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "author": {"login": "alice"},
                }
            ]
        )
        result = pr_for_branch("feat-foo")
        assert result.number == 99
        assert result.head_ref_name == "feat-foo"

    @patch("tasks.pr_orchestrator.detector._gh")
    def test_pror_st_011_no_pr_raises(self, mock_gh: MagicMock) -> None:
        """PROR-ST-011: 無 PR 時 raise RuntimeError"""
        mock_gh.return_value = json.dumps([])
        with pytest.raises(RuntimeError, match="沒有對應的 open PR"):
            pr_for_branch("no-pr-branch")

    @patch("tasks.pr_orchestrator.detector._gh")
    def test_pror_st_012_multiple_prs_raises(self, mock_gh: MagicMock) -> None:
        """PROR-ST-012: 多個 PR 時 raise RuntimeError（fail-loud）"""
        mock_gh.return_value = json.dumps(
            [
                {
                    "number": 1,
                    "headRefName": "b",
                    "headRefOid": "a1",
                    "baseRefName": "main",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "author": {"login": "a"},
                },
                {
                    "number": 2,
                    "headRefName": "b",
                    "headRefOid": "a2",
                    "baseRefName": "main",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "author": {"login": "a"},
                },
            ]
        )
        with pytest.raises(RuntimeError, match="多個 PR"):
            pr_for_branch("b")


class TestRepoRootThreading:
    """PROR-ST-03N：`--repo-root` 讓 branch/gh 偵測回到目標 repo，而非 skill repo cwd。

    根因：SKILL 用 `uv run --directory <skill_repo>` 才能 import module，但這會把子行程
    cwd 換成 skill repo，`git branch --show-current` 便誤讀 skill repo 的分支。修法是把
    目標 repo 路徑一路傳成 subprocess 的 `cwd`。
    """

    @patch("tasks.pr_orchestrator.detector.subprocess.run")
    def test_pror_st_030_current_branch_passes_cwd(self, mock_run: MagicMock) -> None:
        """PROR-ST-030: current_branch(cwd=...) 必須把 cwd 傳給 git subprocess"""
        mock_run.return_value = MagicMock(returncode=0, stdout="feat-bar\n", stderr="")
        target = Path("/repos/yibi-mvp")
        assert current_branch(cwd=target) == "feat-bar"
        assert mock_run.call_args.kwargs["cwd"] == target

    @patch("tasks.pr_orchestrator.detector.subprocess.run")
    def test_pror_st_031_current_branch_defaults_none(self, mock_run: MagicMock) -> None:
        """PROR-ST-031: 未傳 cwd 時預設 None（沿用子行程 cwd，維持既有行為）"""
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n", stderr="")
        assert current_branch() == "main"
        assert mock_run.call_args.kwargs["cwd"] is None

    @patch("tasks.pr_orchestrator.detector.subprocess.run")
    def test_pror_st_032_pr_for_branch_passes_cwd(self, mock_run: MagicMock) -> None:
        """PROR-ST-032: pr_for_branch(cwd=...) 必須把 cwd 傳給 gh subprocess"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "number": 5,
                        "headRefName": "feat-bar",
                        "headRefOid": "cafe",
                        "baseRefName": "main",
                        "mergeable": "MERGEABLE",
                        "mergeStateStatus": "CLEAN",
                        "author": {"login": "bob"},
                    }
                ]
            ),
            stderr="",
        )
        target = Path("/repos/yibi-mvp")
        result = pr_for_branch("feat-bar", cwd=target)
        assert result.number == 5
        assert mock_run.call_args.kwargs["cwd"] == target

    @patch("tasks.pr_orchestrator.detector.subprocess.run")
    def test_pror_st_033_pr_by_number_passes_cwd(self, mock_run: MagicMock) -> None:
        """PROR-ST-033: pr_by_number(cwd=...) 必須把 cwd 傳給 gh subprocess"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "number": 7,
                    "headRefName": "feat-baz",
                    "headRefOid": "beef",
                    "baseRefName": "main",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "author": {"login": "carol"},
                }
            ),
            stderr="",
        )
        target = Path("/repos/yibi-mvp")
        result = pr_by_number(7, cwd=target)
        assert result.number == 7
        assert mock_run.call_args.kwargs["cwd"] == target
