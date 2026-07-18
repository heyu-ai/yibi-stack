"""pre-push-tree-drift-guard.py 黑盒測試。

策略：在 tmp_path 建真實 git repo，用 subprocess 以該 repo 為 cwd 呼叫 hook，
      傳入 Claude Code PreToolUse JSON 格式，驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）

用真 git repo 而非 mock：本 hook 的整個價值在於它對 git 狀態的判讀是否正確，
mock 只會驗證「程式有照我說的呼叫 git」，不驗證「我對 git 的假設是否成立」
（見 ~/.claude/CLAUDE.md 的 verify-mock-asserts-assumption-not-reality）。
"""

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "pre-push-tree-drift-guard.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """帶一個已 commit 檔案的乾淨 git repo。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "tracked.py").write_text("x = 1\n")
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(cwd: Path, command: str, tool_name: str = "Bash") -> int:
    """以給定 cwd 與指令字串執行 hook，回傳 exit code。"""
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode


# ── 核心判斷：樹是否漂移 ───────────────────────────────────────────────


class TestTreeDrift:
    def test_pptd_dt_001_clean_tree_allows_push(self, repo: Path) -> None:
        """PPTD-DT-001: 工作區乾淨 -> 放行（正常流程：改 -> CI -> commit -> push）"""
        assert run_hook(repo, "git push origin feature") == 0

    def test_pptd_dt_002_unstaged_tracked_blocks_push(self, repo: Path) -> None:
        """PPTD-DT-002: 已追蹤檔有未 stage 改動（formatter 就地改寫的形狀）-> 攔截"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "git push origin feature") == 2

    def test_pptd_dt_003_staged_but_uncommitted_blocks_push(self, repo: Path) -> None:
        """PPTD-DT-003: 已 stage 但未 commit -> 攔截（push 出去的樹同樣不含它）"""
        (repo / "tracked.py").write_text("x = 3\n")
        _git(repo, "add", "tracked.py")
        assert run_hook(repo, "git push origin feature") == 2

    def test_pptd_dt_004_untracked_only_allows_push(self, repo: Path) -> None:
        """PPTD-DT-004: 只有未追蹤檔 -> 放行。

        關鍵誤報守門：未追蹤檔不影響 push 出去的樹，納入會讓 yibi-stack 那種
        滿地 generated 檔的 repo 每次 push 都被擋。
        """
        (repo / "scratch.log").write_text("noise\n")
        assert run_hook(repo, "git push origin feature") == 0


# ── 指令匹配：只認真正執行的 git push ─────────────────────────────────


class TestCommandMatching:
    def test_pptd_dt_005_non_push_command_allows(self, repo: Path) -> None:
        """PPTD-DT-005: 髒工作區 + 非 push 指令 -> 放行（本 hook 只管 push 時刻）"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "git commit -m wip") == 0

    def test_pptd_dt_006_push_as_literal_text_allows(self, repo: Path) -> None:
        """PPTD-DT-006: 'git push' 只出現在字串內容中 -> 放行（不是要執行它）"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "echo 'remember to git push later'") == 0

    def test_pptd_dt_007_git_c_path_push_blocks(self, repo: Path) -> None:
        """PPTD-DT-007: git -C <path> push 形式也要認得 -> 攔截"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, f"git -C {repo} push origin feature") == 2


# ── 邊界 ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_pptd_eg_001_non_bash_tool_allows(self, repo: Path) -> None:
        """PPTD-EG-001: 非 Bash 工具 -> 放行"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "git push origin feature", tool_name="Edit") == 0

    def test_pptd_eg_002_non_git_dir_fails_open(self, tmp_path: Path) -> None:
        """PPTD-EG-002: 非 git 目錄 -> fail-open 放行（hook 自己壞掉不該擋 push）"""
        assert run_hook(tmp_path, "git push origin feature") == 0
