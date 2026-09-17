"""protect_push_pr_state.py 測試：推到「PR 已 merged/closed」的分支要攔截。

<!-- verified: incident PR#449 --> <!-- verified: probe -->

分兩層：
  * 純函式層 — 解析 push 目標分支、由 PR 清單決定 verdict，不碰網路。
  * CLI 層 — 以 PATH 注入假的 `gh` 執行整支 helper，驗證 exit code（0 放行 / 2 攔截）
    與 fail-open 條件（gh 不存在、gh 非零退出、輸出無法解析）。

fail-open 是刻意的：推到已 merged PR 的分支會浪費工作但不具破壞性，所以「查不出 PR 狀態」
時放行比擋住所有離線 push 更合理。每個被原諒的條件都在 helper 的 docstring 逐條列名。
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from protect_push_pr_state import (  # noqa: E402
    decide,
    main,
    push_targets,
)


class TestPushTargets:
    def test_pps_dt_001_bare_push_uses_current_branch(self) -> None:
        """PPS-DT-001: 裸 push 的目標是當前分支。"""
        assert push_targets("git push", current_branch="feat-a") == ["feat-a"]
        assert push_targets("git push -u origin", current_branch="feat-a") == ["feat-a"]

    def test_pps_dt_002_explicit_refspec_uses_rhs(self) -> None:
        """PPS-DT-002: `git push origin A:B` 的遠端目標是 B，不是當前分支。

        這正是本 guard 要涵蓋的形式（PR #449 事故用的就是它），而既有保護 3 對它早退放行。
        """
        assert push_targets("git push origin feat-a:feat-b", current_branch="other") == ["feat-b"]

    def test_pps_dt_003_explicit_branch_name(self) -> None:
        """PPS-DT-003: `git push origin B` 的目標是 B。"""
        assert push_targets("git push origin feat-b", current_branch="other") == ["feat-b"]

    def test_pps_dt_004_refs_heads_prefix_stripped(self) -> None:
        """PPS-DT-004: refs/heads/ 前綴會被去掉，才能拿去對 gh 的 --head 比對。"""
        assert push_targets("git push origin HEAD:refs/heads/feat-b", current_branch="x") == [
            "feat-b"
        ]

    def test_pps_dt_005_head_lhs_is_not_a_target_name(self) -> None:
        """PPS-DT-005: `git push origin HEAD` 推的是當前分支名。"""
        assert push_targets("git push origin HEAD", current_branch="feat-a") == ["feat-a"]

    def test_pps_dt_006_non_push_command_has_no_targets(self) -> None:
        """PPS-DT-006: 不是 git push 的指令沒有目標（含 commit message 內含 push 字樣）。"""
        assert push_targets("echo 'git push origin main'", current_branch="feat-a") == []
        assert push_targets("git commit -m 'fix push guard'", current_branch="feat-a") == []

    def test_pps_dt_007_unresolvable_target_is_skipped(self) -> None:
        """PPS-DT-007: 含變數展開或 glob 的目標無法靜態解析，略過（不查、不擋）。"""
        assert push_targets("git push origin $BRANCH", current_branch="feat-a") == []
        assert push_targets("git push origin 'feat-*'", current_branch="feat-a") == []

    def test_pps_dt_008_delete_refspec_is_skipped(self) -> None:
        """PPS-DT-008: 刪除 refspec（`:branch`）不是推內容，不在守備範圍。"""
        assert push_targets("git push origin :feat-b", current_branch="feat-a") == []

    def test_pps_dt_009_multiple_refspecs(self) -> None:
        """PPS-DT-009: 多個 refspec 全部都要檢查。"""
        assert push_targets("git push origin a:a b:b", current_branch="x") == ["a", "b"]


class TestDecide:
    def test_pps_dt_010_merged_only_blocks(self) -> None:
        """PPS-DT-010: 只有已 merged 的 PR -> 攔截。"""
        assert decide([{"number": 1, "state": "MERGED"}]) == "block"

    def test_pps_dt_011_closed_only_blocks(self) -> None:
        """PPS-DT-011: 只有已 closed 的 PR -> 攔截（同樣推不進任何 PR）。"""
        assert decide([{"number": 1, "state": "CLOSED"}]) == "block"

    def test_pps_dt_012_open_pr_allows(self) -> None:
        """PPS-DT-012: 有 open PR -> 放行，這是正常的 fix push。"""
        assert decide([{"number": 2, "state": "OPEN"}]) == "allow"

    def test_pps_dt_013_reused_branch_with_open_pr_allows(self) -> None:
        """PPS-DT-013: 分支被重用（舊 PR merged、新 PR open）-> 放行。

        只要還有一個 open PR，push 就有去處；以「有沒有 open PR」為準，不是「有沒有 merged PR」。
        """
        assert decide([{"number": 1, "state": "MERGED"}, {"number": 2, "state": "OPEN"}]) == "allow"

    def test_pps_dt_014_no_pr_allows(self) -> None:
        """PPS-DT-014: 這個分支沒有任何 PR（首次 push）-> 放行。"""
        assert decide([]) == "allow"

    def test_pps_dt_015_unknown_state_allows(self) -> None:
        """PPS-DT-015: 認不得的 state 字串不當成 merged，放行（保守）。"""
        assert decide([{"number": 1, "state": "DRAFT_SOMETHING"}]) == "allow"


def _fake_gh(bin_dir: Path, payload: str, exit_code: int = 0) -> None:
    """在 bin_dir 放一個假的 gh，印出 payload 後以 exit_code 結束。"""
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(
        f"#!/bin/bash\nprintf '%s' '{payload}'\nexit {exit_code}\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)


def _run_cli(cmd: str, bin_dir: Path | None, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # PATH 只留假 gh 與系統目錄：測試不可打到真的 GitHub
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin" if bin_dir else "/usr/bin:/bin"
    env.pop("PROTECT_PUSH_SKIP_PR_STATE", None)
    return subprocess.run(  # nosec B603
        [sys.executable, str(HOOKS_DIR / "protect_push_pr_state.py")],
        input=cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=30,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """一個有分支的拋棄式 git repo，讓 helper 能解析當前分支。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    for args in (
        ["init", "-q", "-b", "feat-a"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, env=env)  # nosec B603 B607
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env)  # nosec B603 B607
    subprocess.run(  # nosec B603 B607
        ["git", "commit", "-qm", "seed"], cwd=repo, check=True, env=env
    )
    return repo


class TestCli:
    def test_pps_st_001_merged_pr_blocks_with_exit_2(self, repo: Path, tmp_path: Path) -> None:
        """PPS-ST-001: 目標分支的 PR 已 merged -> exit 2，訊息指出 PR 號與原因。"""
        _fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        res = _run_cli("git push origin feat-a:feat-a", tmp_path / "bin", repo)
        assert res.returncode == 2, res.stdout + res.stderr
        assert "448" in res.stdout
        assert "MERGED" in res.stdout or "merged" in res.stdout

    def test_pps_st_002_open_pr_allows(self, repo: Path, tmp_path: Path) -> None:
        """PPS-ST-002: 目標分支有 open PR -> exit 0 且不輸出雜訊。"""
        _fake_gh(tmp_path / "bin", json.dumps([{"number": 500, "state": "OPEN"}]))
        res = _run_cli("git push", tmp_path / "bin", repo)
        assert res.returncode == 0
        assert res.stdout == ""

    def test_pps_st_003_no_pr_allows(self, repo: Path, tmp_path: Path) -> None:
        """PPS-ST-003: 查無 PR（首次 push）-> exit 0。"""
        _fake_gh(tmp_path / "bin", "[]")
        assert _run_cli("git push -u origin feat-a", tmp_path / "bin", repo).returncode == 0

    def test_pps_st_004_gh_missing_fails_open(self, repo: Path) -> None:
        """PPS-ST-004: PATH 上沒有 gh -> 放行（具名的 fail-open 條件之一）。"""
        res = _run_cli("git push origin feat-a:feat-a", None, repo)
        assert res.returncode == 0

    def test_pps_st_005_gh_error_fails_open(self, repo: Path, tmp_path: Path) -> None:
        """PPS-ST-005: gh 非零退出（未登入 / 離線）-> 放行，不是攔截。"""
        _fake_gh(tmp_path / "bin", "gh: auth required", exit_code=1)
        assert _run_cli("git push origin feat-a:feat-a", tmp_path / "bin", repo).returncode == 0

    def test_pps_st_006_unparseable_output_fails_open(self, repo: Path, tmp_path: Path) -> None:
        """PPS-ST-006: gh 輸出不是 JSON -> 放行。"""
        _fake_gh(tmp_path / "bin", "not json at all")
        assert _run_cli("git push origin feat-a:feat-a", tmp_path / "bin", repo).returncode == 0

    def test_pps_st_007_non_push_command_skips_gh(self, repo: Path, tmp_path: Path) -> None:
        """PPS-ST-007: 非 push 指令不查 gh（避免在每個 Bash call 付出網路成本）。"""
        _fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        assert _run_cli("git status", tmp_path / "bin", repo).returncode == 0

    def test_pps_st_008_escape_hatch_allows(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PPS-ST-008: PROTECT_PUSH_SKIP_PR_STATE=1 -> 完全跳過（逃生口）。"""
        _fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        env = dict(os.environ)
        env["PATH"] = f"{tmp_path / 'bin'}:/usr/bin:/bin"
        env["PROTECT_PUSH_SKIP_PR_STATE"] = "1"
        res = subprocess.run(  # nosec B603
            [sys.executable, str(HOOKS_DIR / "protect_push_pr_state.py")],
            input="git push origin feat-a:feat-a",
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo),
            timeout=30,
        )
        assert res.returncode == 0

    def test_pps_st_009_main_is_importable_and_returns_int(self) -> None:
        """PPS-ST-009: main() 可被匯入呼叫並回傳 int（非 push 輸入 -> 0）。"""
        assert main(stdin_text="echo hi") == 0
