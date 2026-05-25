"""post-edit-mypy.sh 的黑盒測試（blackbox subprocess）。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).parents[1] / "post-edit-mypy.sh"


# Hook path guard pattern is */tasks/*.py (requires a prefix before tasks/).
# Claude Code sends absolute paths at runtime, so tests must do the same.
_TASKS_PY = str(Path(__file__).parents[3] / "tasks" / "models.py")


def _make_stdin(file_path: str = _TASKS_PY, duration_ms: int = 200) -> str:
    return json.dumps({"tool_input": {"file_path": file_path}, "duration_ms": duration_ms})


def _run_hook(stdin: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, **(env or {})}
    return subprocess.run(  # nosec B603
        ["bash", str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=e,
    )


class TestEffortGate:
    def test_mypy_001_effort_low_skip(self) -> None:
        """MYPY-001: CLAUDE_EFFORT=low 時靜默跳過，exit 0，不跑 mypy。"""
        result = _run_hook(
            _make_stdin(duration_ms=500),
            env={"CLAUDE_EFFORT": "low"},
        )
        assert result.returncode == 0
        assert "error:" not in result.stdout
        # Should not attempt to invoke mypy (no uv/mypy output in stderr)
        assert "mypy" not in result.stderr.lower()

    def test_mypy_002_effort_normal_does_not_skip(self) -> None:
        """MYPY-002: CLAUDE_EFFORT=normal 不觸發 effort skip（仍嘗試跑 mypy）。"""
        result = _run_hook(
            _make_stdin(duration_ms=500),
            env={"CLAUDE_EFFORT": "normal"},
        )
        assert result.returncode == 0
        # With abs path and normal effort, mypy is invoked (file may not exist but mypy still runs)
        assert "mypy" in result.stderr.lower(), "Expected mypy to be invoked for normal effort"

    def test_mypy_003_effort_unset_does_not_skip(self) -> None:
        """MYPY-003: CLAUDE_EFFORT 未設定時 fallback normal，不觸發 effort skip。"""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_EFFORT"}
        result = subprocess.run(  # nosec B603
            ["bash", str(HOOK)],
            input=_make_stdin(duration_ms=500),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        # With abs path and unset effort (falls back to normal), mypy is invoked
        assert "mypy" in result.stderr.lower(), (
            "Expected mypy to be invoked when CLAUDE_EFFORT unset"
        )


class TestPathGuard:
    def test_mypy_004_non_tasks_file_exits_zero(self) -> None:
        """MYPY-004: tasks/ 以外的檔案直接 exit 0，不執行 mypy。"""
        for path in [
            "/repo/scripts/foo.py",
            "/repo/skills/bar.py",
            "/repo/.claude/hooks/pre-commit.sh",
        ]:
            result = _run_hook(_make_stdin(path, 500))
            assert result.returncode == 0, f"Expected exit 0 for {path}"
            assert "mypy" not in result.stderr.lower()


class TestDurationGate:
    def test_mypy_005_short_duration_exits_zero(self) -> None:
        """MYPY-005: duration_ms < 100 視為超短編輯，exit 0，不跑 mypy。"""
        result = _run_hook(_make_stdin(duration_ms=50))
        assert result.returncode == 0
        assert "mypy" not in result.stderr.lower()


class TestFailOpen:
    def test_mypy_006_invalid_json_fail_open(self) -> None:
        """MYPY-006: 無效 JSON stdin 時 fail-open（exit 0），不阻擋 Claude。"""
        result = _run_hook("not valid json {{")
        assert result.returncode == 0

    def test_mypy_007_empty_stdin_fail_open(self) -> None:
        """MYPY-007: 空 stdin 時 fail-open（exit 0）。"""
        result = _run_hook("")
        assert result.returncode == 0

    def test_mypy_008_missing_file_path_exits_zero(self) -> None:
        """MYPY-008: file_path 為空字串時 exit 0（path guard 直接通過）。"""
        result = _run_hook(json.dumps({"tool_input": {"file_path": ""}, "duration_ms": 500}))
        assert result.returncode == 0
