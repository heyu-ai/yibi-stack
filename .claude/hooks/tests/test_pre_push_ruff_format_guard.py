"""pre-push-ruff-format-guard.py 黑盒測試。

策略：在 tmp_path 建真實 git repo，用 subprocess 以該 repo 為 cwd 呼叫 hook，
      傳入 Claude Code PreToolUse JSON 格式，驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）

ruff 呼叫走 _RUFF_CMD_ENV seam 注入「PATH 上的真 ruff」直接掃 tmp repo——用真 ruff
而非 mock，理由同姊妹 hook：mock 只驗證「程式有照我說的呼叫 ruff」，不驗證「我對 ruff
輸出格式的假設是否成立」（見 ~/.claude/CLAUDE.md 的 verify-mock-asserts-assumption）。
production 不設此 env，走專案 pinned 的 `uv run ruff`（版本與 CI 一致）。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "pre-push-ruff-format-guard.py"
RUFF = shutil.which("ruff")
_needs_ruff = pytest.mark.skipif(RUFF is None, reason="ruff 不在 PATH，無法用真 ruff 測行為")

_FORMATTED = "x = [1, 2, 3]\n"
_UNFORMATTED = "x=[1,2,3]\ndef f( a ,b ):\n     return a+b\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """帶一個已 commit、已格式化 .py 的乾淨 git repo。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "tracked.py").write_text(_FORMATTED)
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(
    cwd: Path,
    command: object,
    tool_name: str = "Bash",
    payload_cwd: Path | None = None,
    ruff_override: str | None = "__real__",
) -> subprocess.CompletedProcess[str]:
    """以給定 cwd 與指令執行 hook。

    ruff_override:
      "__real__"（預設）→ 注入 PATH 上的真 ruff（需 RUFF 存在）
      None                → 不設 seam，讓 hook 走預設 `uv run ruff`
      其他字串            → 原樣當成 _RUFF_CMD_ENV 值（測 fail-open）
    """
    env = os.environ.copy()
    if ruff_override == "__real__":
        env["PRE_PUSH_RUFF_GUARD_CMD"] = f"{RUFF} format --check ."
    elif ruff_override is None:
        env.pop("PRE_PUSH_RUFF_GUARD_CMD", None)
    else:
        env["PRE_PUSH_RUFF_GUARD_CMD"] = ruff_override
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"command": command},
            **({"cwd": str(payload_cwd)} if payload_cwd is not None else {}),
        }
    )
    return subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── 核心行為：已 commit 但未格式化 → 擋 ──────────────────────────────────


@_needs_ruff
class TestFormatGuard:
    def test_pprf_dt_001_all_formatted_allows_push(self, repo: Path) -> None:
        """PPRF-DT-001: 全部已格式化 → 放行"""
        assert run_hook(repo, "git push origin feature").returncode == 0

    def test_pprf_dt_002_unformatted_blocks_push(self, repo: Path) -> None:
        """PPRF-DT-002: 有已 commit 的未格式化 .py → 攔截並列出檔名"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        result = run_hook(repo, "git push origin feature")
        assert result.returncode == 2
        assert "bad.py" in result.stdout
        assert "ruff format" in result.stdout

    def test_pprf_dt_003_git_c_path_push_blocks(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """PPRF-DT-003: git -C <path> push 形式也要認得"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        clean_cwd = tmp_path_factory.mktemp("clean-cwd")
        _git(clean_cwd, "init", "-q")
        result = run_hook(clean_cwd, f"git -C {repo} push origin feature")
        assert result.returncode == 2
        assert "bad.py" in result.stdout

    def test_pprf_dt_004_payload_cwd_is_authoritative(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """PPRF-DT-004: 以 payload cwd（而非 launch cwd）定位目標 repo"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        launch_cwd = tmp_path_factory.mktemp("launch-cwd")
        assert run_hook(launch_cwd, "git push", payload_cwd=repo).returncode == 2


# ── 指令匹配：只認真正執行的 git push ─────────────────────────────────


@_needs_ruff
class TestCommandMatching:
    def test_pprf_dt_005_non_push_command_allows(self, repo: Path) -> None:
        """PPRF-DT-005: 未格式化 + 非 push 指令 → 放行（本 hook 只管 push 時刻）"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "git commit -m wip").returncode == 0

    @pytest.mark.parametrize(
        "command",
        ['git commit -m "add push"', "git show push", "git branch push-x"],
    )
    def test_pprf_dt_006_push_text_after_non_push_subcommand_allows(
        self, repo: Path, command: str
    ) -> None:
        """PPRF-DT-006: 第一個 subcommand 不是 push 時，不可被後續 push 字樣誤攔"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, command).returncode == 0

    def test_pprf_dt_007_push_as_literal_text_allows(self, repo: Path) -> None:
        """PPRF-DT-007: 'git push' 只出現在字串內容中 → 放行"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "echo 'remember to git push later'").returncode == 0

    @pytest.mark.parametrize(
        "command",
        [
            "git --no-pager push",
            "git -p push",
            "git -c http.x=y push",
            "env X=y git push",
            "X=y git push",
            "sudo git push",
            "(git push)",
        ],
    )
    def test_pprf_dt_008_global_options_and_wrappers_block(self, repo: Path, command: str) -> None:
        """PPRF-DT-008: 全域選項 / wrapper 形狀的 push 仍要認得"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, command).returncode == 2

    def test_pprf_dt_009_unrecognized_option_fails_open(self, repo: Path) -> None:
        """PPRF-DT-009: push 前出現非白名單 option → 保守放行（fail-open，非本 guard 目的）"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "git --mystery push").returncode == 0


# ── 邊界 / fail-open ───────────────────────────────────────────────────


class TestEdgeCases:
    @_needs_ruff
    def test_pprf_eg_001_non_bash_tool_allows(self, repo: Path) -> None:
        """PPRF-EG-001: 非 Bash 工具 → 放行"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "git push", tool_name="Edit").returncode == 0

    def test_pprf_eg_002_non_git_dir_fails_open(self, tmp_path: Path) -> None:
        """PPRF-EG-002: 非 git 目錄 → fail-open 放行（hook 自己壞掉不該擋 push）"""
        assert run_hook(tmp_path, "git push origin feature").returncode == 0

    def test_pprf_eg_003_non_string_command_allows(self, repo: Path) -> None:
        """PPRF-EG-003: command 非字串 → 放行"""
        assert run_hook(repo, ["git", "push"]).returncode == 0

    def test_pprf_eg_004_ruff_unavailable_fails_open(self, repo: Path) -> None:
        """PPRF-EG-004: ruff 執行不出來（指向不存在的 binary）→ fail-open 放行"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        result = run_hook(
            repo, "git push", ruff_override="/definitely/nonexistent/ruff format --check ."
        )
        assert result.returncode == 0


# ── ReDoS 回歸（比照姊妹 hook / CodeQL py/redos）───────────────────────


class TestReDoS:
    def test_pprf_re_001_git_command_regex_no_exponential_backtracking(self) -> None:
        """PPRF-RE-001: _GIT_COMMAND 對長重複 assignment 攻擊字串不得指數爆炸。

        本 hook 的 assignment 重複段 `(?:[A-Za-z_]\\w*=\\S+\\s+)*` 中 `\\S+` 與 `\\s+`
        字元類互斥、每段以 `=` 錨定，理論上線性；此測試以 timing 上限守住不回退。
        """
        import importlib.util
        import time

        spec = importlib.util.spec_from_file_location("_rfg_redos", HOOK)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        attack = "&A=" + ("A=x " * 4000)
        start = time.perf_counter()
        list(mod._GIT_COMMAND.finditer(attack))
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"疑似 ReDoS 回退：{elapsed:.2f}s"
