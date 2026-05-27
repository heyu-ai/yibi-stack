"""PROR-ST-NNN：detector mock 測試。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tasks.pr_orchestrator.detector import pr_for_branch


class TestPrForBranch:
    @patch("tasks.pr_orchestrator.detector._gh")
    def test_pror_st_010_single_pr_found(self, mock_gh: object) -> None:
        """PROR-ST-010: 單一 PR 正確解析"""
        import json

        mock_gh.return_value = json.dumps([{  # type: ignore[attr-defined]
            "number": 99,
            "headRefName": "feat-foo",
            "headRefOid": "deadbeef",
            "baseRefName": "main",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "author": {"login": "alice"},
        }])
        result = pr_for_branch("feat-foo")
        assert result.number == 99
        assert result.head_ref_name == "feat-foo"

    @patch("tasks.pr_orchestrator.detector._gh")
    def test_pror_st_011_no_pr_raises(self, mock_gh: object) -> None:
        """PROR-ST-011: 無 PR 時 raise RuntimeError"""
        import json

        mock_gh.return_value = json.dumps([])  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="沒有對應的 open PR"):
            pr_for_branch("no-pr-branch")

    @patch("tasks.pr_orchestrator.detector._gh")
    def test_pror_st_012_multiple_prs_raises(self, mock_gh: object) -> None:
        """PROR-ST-012: 多個 PR 時 raise RuntimeError（fail-loud）"""
        import json

        mock_gh.return_value = json.dumps([  # type: ignore[attr-defined]
            {"number": 1, "headRefName": "b", "headRefOid": "a1", "baseRefName": "main",
             "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "author": {"login": "a"}},
            {"number": 2, "headRefName": "b", "headRefOid": "a2", "baseRefName": "main",
             "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "author": {"login": "a"}},
        ])
        with pytest.raises(RuntimeError, match="多個 PR"):
            pr_for_branch("b")
