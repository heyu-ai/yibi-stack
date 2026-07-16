"""scripts/lessons wrapper 的 --project 注入策略測試。

這支 wrapper 承擔一個讀寫不對稱的保證：

- 寫入（add）必須注入 cwd 偵測到的 project——issue #243 的 287 條 retro lesson
  就是因為沒走 wrapper、cwd 被 `uv run --directory` 換成 yibi-stack 而被誤記。
- 讀取（show / search）必須**不**注入——mycelium CLI 對這兩者的 --project 預設是
  「顯示全部 project」，wrapper 若注入就靈默覆寫了該預設，呼叫端以為拿到跨 project
  結果、實際只拿到 cwd 那個 repo 的（ainization-skill PR #223 實測：DB 當天有 26 條
  lesson，經 wrapper 查詢回 0 條，無任何錯誤訊號）。

測法：PATH 注入假 `uv`，把 wrapper 最終組出的引數原樣印出來比對，不真的跑 mycelium。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "lessons"


def _make_env(tmp_path: Path) -> dict[str, str]:
    """組出讓 wrapper 可跑的隔離環境：假 HOME + 假 resolve-skill-repo + 假 uv。

    假 uv 把收到的引數原樣印到 stdout，讓測試能斷言 wrapper 到底組了什麼指令。
    """
    fake_home = tmp_path / "home"
    bin_dir = fake_home / ".agents" / "bin"
    bin_dir.mkdir(parents=True)

    skill_repo = tmp_path / "skill_repo"
    skill_repo.mkdir()

    resolver = bin_dir / "resolve-skill-repo"
    resolver.write_text(f'#!/usr/bin/env bash\necho "{skill_repo}"\n', encoding="utf-8")
    resolver.chmod(0o755)

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text('#!/usr/bin/env bash\necho "$@"\n', encoding="utf-8")
    uv_shim.chmod(0o755)

    return {
        **os.environ,
        "HOME": str(fake_home),
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
    }


def _run_wrapper(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """在隔離環境執行 wrapper，cwd 設為一個非 git 目錄以走 basename(pwd) 分支。"""
    cwd = tmp_path / "some-project"
    cwd.mkdir()
    return subprocess.run(  # nosec B603
        ["bash", str(WRAPPER), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
        cwd=str(cwd),
    )


class TestReadCommandsSkipProjectInjection:
    @pytest.mark.parametrize("subcmd", ["show", "search"])
    def test_lsw_dt_001_read_command_does_not_inject_project(
        self, tmp_path: Path, subcmd: str
    ) -> None:
        """LSW-DT-001: show / search 不注入 --project，保留 CLI 的「預設全部」語意。"""
        result = _run_wrapper(tmp_path, [subcmd, "--json"])
        assert result.returncode == 0, result.stderr
        assert "--project" not in result.stdout, (
            f"{subcmd} 被注入了 --project，會靈默把跨 project 查詢縮成單一 repo：{result.stdout!r}"
        )
        assert f"lessons {subcmd} --json" in result.stdout

    def test_lsw_dt_002_read_command_still_forwards_explicit_project(self, tmp_path: Path) -> None:
        """LSW-DT-002: 呼叫端明確指定 --project 時，show 仍原樣轉發（不吞掉）。"""
        result = _run_wrapper(tmp_path, ["show", "--project", "yibi-mvp"])
        assert result.returncode == 0, result.stderr
        assert "--project yibi-mvp" in result.stdout


class TestWriteCommandInjectsProject:
    def test_lsw_dt_003_add_injects_detected_project(self, tmp_path: Path) -> None:
        """LSW-DT-003: add 仍注入 cwd 偵測到的 project（issue #243 的防線，不可退化）。"""
        result = _run_wrapper(tmp_path, ["add", "--key", "k", "--type", "pitfall"])
        assert result.returncode == 0, result.stderr
        assert "--project some-project" in result.stdout, (
            f"add 未注入 --project，會重演 #243 的 287 條 lesson 記錯 project：{result.stdout!r}"
        )

    def test_lsw_dt_004_add_does_not_double_inject(self, tmp_path: Path) -> None:
        """LSW-DT-004: add 已帶 --project 時不重複注入。"""
        result = _run_wrapper(tmp_path, ["add", "--key", "k", "--project", "yibi-mvp"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("--project") == 1, result.stdout
        assert "--project yibi-mvp" in result.stdout

    def test_lsw_dt_005_unknown_subcommand_defaults_to_injecting(self, tmp_path: Path) -> None:
        """LSW-DT-005: 未知子命令 fail-safe 走注入路徑。

        未來若新增寫入類子命令（如 issue #242 的 delete / retire），漏改此處時
        寧可多帶 scope，也不要讓它靜默寫到錯的 project——#243 的代價高於多帶一個旗標。
        """
        result = _run_wrapper(tmp_path, ["retire", "--id", "abc"])
        assert result.returncode == 0, result.stderr
        assert "--project some-project" in result.stdout

    def test_lsw_eg_001_no_subcommand_does_not_crash(self, tmp_path: Path) -> None:
        """LSW-EG-001: 不帶任何引數時 `${1:-}` 不因 set -u 而炸（走注入路徑轉發給 CLI）。"""
        result = _run_wrapper(tmp_path, [])
        assert result.returncode == 0, result.stderr
        assert "unbound variable" not in result.stderr
