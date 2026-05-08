"""markdownlint-pre-commit.sh 黑盒測試。

策略：用 subprocess 呼叫 hook，傳入 Claude Code PreToolUse JSON 格式，
      驗證 exit code：
        0 = 放行（non-commit 指令、effort=low、或無 staged .md）
        非 0 = markdownlint 本身失敗（需 git 環境，不在此測試範圍）

注意：markdownlint 的實際執行（需 staged .md + git index）超出黑盒 unit test 範圍，
      此測試只覆蓋兩個 early-exit guard 的行為。
"""

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).parent.parent / "markdownlint-pre-commit.sh"


def run_hook(command: str, effort: str | None = None) -> subprocess.CompletedProcess[str]:
    """以給定指令字串執行 hook，可選傳入 CLAUDE_EFFORT。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = os.environ.copy()
    if effort is not None:
        env["CLAUDE_EFFORT"] = effort
    else:
        env.pop("CLAUDE_EFFORT", None)
    return subprocess.run(
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def run_hook_raw(stdin: str) -> int:
    """以原始字串（非 JSON）執行 hook，測試 fail-open 行為。"""
    result = subprocess.run(
        [str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode


# ── non-commit 指令（Guard 1：只在 git commit 時觸發）────────────────────


class TestNonCommitPassthrough:
    def test_ml_allow_001_non_commit_echo(self) -> None:
        """非 git commit 指令 → 放行（Guard 1）"""
        assert run_hook("echo hello").returncode == 0

    def test_ml_allow_002_git_status(self) -> None:
        """git status → 放行（非 commit 指令）"""
        assert run_hook("git status").returncode == 0

    def test_ml_allow_003_git_push(self) -> None:
        """git push → 放行（非 commit 指令）"""
        assert run_hook("git push origin HEAD").returncode == 0

    def test_ml_allow_004_invalid_json_fail_open(self) -> None:
        """無效 JSON → 靜默放行（fail-open）"""
        assert run_hook_raw("not valid json") == 0

    def test_ml_allow_005_empty_stdin_fail_open(self) -> None:
        """空輸入 → 靜默放行（fail-open）"""
        assert run_hook_raw("") == 0


# ── effort=low guard（Guard 2：品質 gate 跳過）────────────────────────────


class TestEffortLowBypass:
    def test_ml_effort_001_low_skips_on_commit(self) -> None:
        """CLAUDE_EFFORT=low + git commit → 跳過 lint，exit 0"""
        result = run_hook('git commit -m "test"', effort="low")
        assert result.returncode == 0

    def test_ml_effort_002_low_emits_skip_to_stderr(self) -> None:
        """CLAUDE_EFFORT=low 應在 stderr 輸出 [SKIP] 訊息（可觀測性）"""
        result = run_hook('git commit -m "test"', effort="low")
        assert "[SKIP]" in result.stderr

    def test_ml_effort_003_normal_does_not_skip(self) -> None:
        """CLAUDE_EFFORT=normal + git commit → 不從 effort guard 跳出（繼續往下執行）"""
        # 在無 git repo 的環境下，git diff --cached 會失敗或回傳空值，
        # hook 在 staged 檢查前就 exit 0；但不應在 effort guard 印出 [SKIP]。
        result = run_hook('git commit -m "test"', effort="normal")
        assert "[SKIP]" not in result.stderr

    def test_ml_effort_004_unset_does_not_skip(self) -> None:
        """CLAUDE_EFFORT 未設定 → 預設 normal，不從 effort guard 跳出"""
        result = run_hook('git commit -m "test"', effort=None)
        assert "[SKIP]" not in result.stderr

    def test_ml_effort_005_low_non_commit_exits_at_guard1(self) -> None:
        """CLAUDE_EFFORT=low + 非 commit 指令 → Guard 1 攔截，不進到 effort guard"""
        result = run_hook("echo hello", effort="low")
        assert result.returncode == 0
        assert "[SKIP]" not in result.stderr
