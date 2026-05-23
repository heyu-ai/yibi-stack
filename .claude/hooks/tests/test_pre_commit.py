"""pre-commit.sh 的黑盒測試（blackbox subprocess）。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).parents[1] / "pre-commit.sh"

_GIT_COMMIT_JSON = json.dumps({"tool_input": {"command": "git commit -m 'test'"}})


def _run_hook(stdin: str, env: dict[str, str] | None = None, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, **(env or {})}
    return subprocess.run(  # nosec B603
        ["bash", str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
    )


class TestGuards:
    def test_pre_commit_001_non_commit_passthrough(self) -> None:
        """PRE-COMMIT-001: git commit 以外的指令直接通過，不執行 lint。"""
        for cmd in ["echo hello", "git status", "git push origin main", "make test"]:
            stdin = json.dumps({"tool_input": {"command": cmd}})
            result = _run_hook(stdin)
            assert result.returncode == 0, f"'{cmd}' should pass through, got exit {result.returncode}"
            assert "[FAIL]" not in result.stderr

    def test_pre_commit_002_effort_low_skip(self) -> None:
        """PRE-COMMIT-002: CLAUDE_EFFORT=low 時跳過整個 gate，stderr 有 [SKIP]。"""
        result = _run_hook(_GIT_COMMIT_JSON, env={"CLAUDE_EFFORT": "low"})
        assert result.returncode == 0
        assert "[SKIP]" in result.stderr

    def test_pre_commit_003_effort_normal_no_skip(self) -> None:
        """PRE-COMMIT-003: CLAUDE_EFFORT=normal 不觸發 [SKIP]。"""
        result = _run_hook(_GIT_COMMIT_JSON, env={"CLAUDE_EFFORT": "normal"})
        assert "[SKIP]" not in result.stderr

    def test_pre_commit_004_invalid_json_fail_open(self) -> None:
        """PRE-COMMIT-004: 無效 JSON stdin 時 fail-open（exit 0），不阻擋提交。"""
        result = _run_hook("not valid json {{")
        assert result.returncode == 0
        assert "[FAIL]" not in result.stderr

    def test_pre_commit_005_empty_stdin_fail_open(self) -> None:
        """PRE-COMMIT-005: 空 stdin 時 fail-open（exit 0）。"""
        result = _run_hook("")
        assert result.returncode == 0

    def test_pre_commit_006_progress_echoes_on_stderr(self, tmp_path: Path) -> None:
        """PRE-COMMIT-006: [pre-commit] 和 [OK] 進度訊息走 stderr，不走 stdout。"""
        repo = _make_git_repo(tmp_path)
        staged_md = tmp_path / "test.md"
        staged_md.write_text("# Test\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "test.md"], check=True, capture_output=True)  # nosec B603
        result = _run_hook(_GIT_COMMIT_JSON, cwd=str(repo))
        assert "[pre-commit]" not in result.stdout
        assert "[OK]" not in result.stdout


class TestStagedFiles:
    def test_pre_commit_007_no_staged_files_exit_zero(self, tmp_path: Path) -> None:
        """PRE-COMMIT-007: staged 檔案為空時 exit 0，不執行任何 linter。"""
        repo = _make_git_repo(tmp_path)
        result = _run_hook(_GIT_COMMIT_JSON, cwd=str(repo))
        assert result.returncode == 0
        assert "[FAIL]" not in result.stderr

    def test_pre_commit_008_no_py_files_skips_ruff(self, tmp_path: Path) -> None:
        """PRE-COMMIT-008: 只有 .md staged 時不執行 ruff（ruff section 靜默跳過）。"""
        repo = _make_git_repo(tmp_path)
        staged_md = tmp_path / "README.md"
        staged_md.write_text("# Test\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True)  # nosec B603
        result = _run_hook(_GIT_COMMIT_JSON, cwd=str(repo))
        assert "[pre-commit] ruff" not in result.stderr
        assert "[FAIL] ruff" not in result.stderr

    def test_pre_commit_009_no_md_files_skips_markdownlint(self, tmp_path: Path) -> None:
        """PRE-COMMIT-009: 只有 .py staged 時不執行 markdownlint（markdownlint section 靜默跳過）。"""
        repo = _make_git_repo(tmp_path)
        staged_py = tmp_path / "foo.py"
        staged_py.write_text("x = 1\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "foo.py"], check=True, capture_output=True)  # nosec B603
        result = _run_hook(_GIT_COMMIT_JSON, cwd=str(repo))
        assert "[pre-commit] markdownlint" not in result.stderr
        assert "[FAIL] markdownlint" not in result.stderr

    def test_pre_commit_010_git_diff_fail_warns_and_skips(self, tmp_path: Path) -> None:
        """PRE-COMMIT-010: git diff --cached 失敗時 [WARN] 到 stderr 並 exit 0（不阻擋）。"""
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text("#!/bin/bash\nexit 128\n")
        fake_git.chmod(0o755)
        env = {"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
        result = _run_hook(_GIT_COMMIT_JSON, cwd=str(tmp_path), env=env)
        assert result.returncode == 0
        assert "[WARN]" in result.stderr


def _make_git_repo(tmp_path: Path) -> Path:
    """最小 git repo with initial commit（供 staged-files 測試使用）。"""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)  # nosec B603
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], check=True, capture_output=True)  # nosec B603
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)  # nosec B603
    init = tmp_path / ".gitkeep"
    init.write_text("")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitkeep"], check=True, capture_output=True)  # nosec B603
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)  # nosec B603
    return tmp_path
