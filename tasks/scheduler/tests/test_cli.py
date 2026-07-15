"""測試 cli.py：setup、status、history、install 命令。"""

from __future__ import annotations

import subprocess  # nosec B404
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ..cli import cli


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """執行 setup 用的 git 指令；**失敗即 raise**（理由見 tasks/tests/test_worktree_guard.py）。"""
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=True
    )


def _make_repo(root: Path) -> Path:
    """建立一個有 initial commit 的 git repo。

    不用 `git init -b`（2.28+）；理由見 .claude/rules/09-test-conventions.md。
    """
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", str(root)])
    _run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"])
    _run(["git", "-C", str(root), "config", "user.email", "test@example.com"])
    _run(["git", "-C", str(root), "config", "user.name", "test"])
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _run(["git", "-C", str(root), "add", "README.md"])
    _run(["git", "-C", str(root), "commit", "-qm", "init"])
    return root


def _make_worktree(tmp_path: Path) -> Path:
    """建立 linked worktree，並斷言 git 真的把它登記成 worktree。"""
    repo = _make_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)])
    listed = _run(["git", "-C", str(repo), "worktree", "list", "--porcelain"]).stdout
    assert f"worktree {wt.resolve()}" in listed, f"fixture 未建出 linked worktree：{listed}"
    return wt


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated(tmp_path: Path) -> Generator[dict[str, Path], None, None]:
    """在 tmp_path 中隔離 config、db、log 路徑。"""
    config_path = tmp_path / "schedules.json"
    db_path = tmp_path / "scheduler.db"
    log_dir = tmp_path / "logs"

    with (
        patch("tasks.scheduler.cli._CONFIG_PATH", config_path),
        patch("tasks.scheduler.cli._DB_PATH", db_path),
        patch("tasks.scheduler.cli._LOG_DIR", log_dir),
    ):
        yield {"config": config_path, "db": db_path, "log_dir": log_dir}


class TestSetupCommand:
    def test_creates_config_and_db(self, runner: CliRunner, isolated: dict[str, Path]) -> None:
        result = runner.invoke(cli, ["setup"])
        assert result.exit_code == 0
        assert isolated["config"].exists()
        assert isolated["db"].exists()

    def test_skips_existing_config(self, runner: CliRunner, isolated: dict[str, Path]) -> None:
        runner.invoke(cli, ["setup"])
        result = runner.invoke(cli, ["setup"])
        assert "已存在" in result.output
        assert result.exit_code == 0


class TestStatusCommand:
    def test_shows_jobs(self, runner: CliRunner, isolated: dict[str, Path]) -> None:
        runner.invoke(cli, ["setup"])
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "newsletter-extract" in result.output
        assert "newsletter-digest" in result.output

    def test_missing_config_exits_nonzero(
        self, runner: CliRunner, isolated: dict[str, Path]
    ) -> None:
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1


class TestHistoryCommand:
    def test_no_records(self, runner: CliRunner, isolated: dict[str, Path]) -> None:
        runner.invoke(cli, ["setup"])
        result = runner.invoke(cli, ["history"])
        assert result.exit_code == 0
        assert "無執行記錄" in result.output


class TestTickDryRun:
    def test_dry_run_no_execution(self, runner: CliRunner, isolated: dict[str, Path]) -> None:
        """--dry-run 只列出 due jobs，不實際執行。"""
        runner.invoke(cli, ["setup"])
        result = runner.invoke(cli, ["tick", "--dry-run"])
        # 沒有 job 到期，或只輸出 dry-run 資訊，不應有 error
        assert result.exit_code == 0


class TestInstallWorktreeGuard:
    """SCHED-DT-*: install 在 worktree 內必須擋下，且**不留下 plist**（issue #237）。

    plist 住在 ~/Library/LaunchAgents/（機器層級），內容嵌入 PROJECT_ROOT。在 worktree
    裡裝完、分支合併、worktree 被刪，LaunchAgent 就會每 60 秒對著不存在的 python 失敗，
    且不通知任何人。
    """

    @pytest.fixture
    def wt_install_env(
        self, tmp_path: Path, isolated: dict[str, Path]
    ) -> Generator[dict[str, Path], None, None]:
        """把 install 的所有寫入點導到 tmp，並讓 PROJECT_ROOT 指向一個真的 worktree。"""
        wt = _make_worktree(tmp_path)

        # 必須備妥 .venv/bin/python。否則拿掉 guard 之後，install 會先死在
        # 「找不到 .venv/bin/python」而**同樣 exit 1**，本測試就會因錯的理由通過 ——
        # 突變驗證形同虛設（CLAUDE.md：每個 mutation 只改一件事，且測試要因對的理由紅）。
        venv_bin = wt / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("", encoding="utf-8")

        plist = tmp_path / "test.plist"

        class _FakeSubprocess:
            """攔掉 launchctl。

            只換掉 tasks.scheduler.cli 命名空間裡的 `subprocess` 名稱，不動真正的
            subprocess module —— tasks._worktree_guard 有自己的 binding，仍要能真的
            跑守門腳本。若在此 patch `subprocess.run` 本身，會把 guard 一起打壞。

            存在的意義是突變安全：拿掉 guard 後 install 會走到 `launchctl load`，
            那支 plist 的 Label 與使用者真正的 scheduler 相同，真的載入會覆蓋掉它。
            """

            @staticmethod
            def run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("tasks._worktree_guard.PROJECT_ROOT", wt),
            patch("tasks.scheduler.cli.PROJECT_ROOT", wt),
            patch("tasks.scheduler.cli._PLIST_PATH", plist),
            patch("tasks.scheduler.cli.subprocess", _FakeSubprocess),
        ):
            yield {"wt": wt, "plist": plist}

    def test_sched_dt_001_install_in_worktree_blocked(
        self, runner: CliRunner, wt_install_env: dict[str, Path]
    ) -> None:
        """SCHED-DT-001: worktree 內執行 install -> exit 1 且不寫出 plist。"""
        result = runner.invoke(cli, ["install"])
        assert result.exit_code == 1
        assert not wt_install_env["plist"].exists(), "guard 沒擋住，plist 已被寫出"

    def test_sched_dt_002_guard_runs_before_any_write(
        self, runner: CliRunner, wt_install_env: dict[str, Path], isolated: dict[str, Path]
    ) -> None:
        """SCHED-DT-002: guard 必須早於**所有**寫入，不只早於 plist。

        install 在寫 plist 之前還會 init DB 與生成預設 config。guard 若擺在那之後，
        機器層級狀態雖然乾淨，但 .runtime/ 已被動過 —— rule 11「guard 是第一個動作」
        在 Python 這側的對應斷言。
        """
        runner.invoke(cli, ["install"])
        assert not isolated["db"].exists(), "guard 之前就先建了 DB"
        assert not isolated["config"].exists(), "guard 之前就先寫了 config"

    def test_sched_dt_003_install_in_main_repo_passes(
        self, runner: CliRunner, tmp_path: Path, isolated: dict[str, Path]
    ) -> None:
        """SCHED-DT-003: 主 repo 內執行 install -> 正常寫出 plist（guard 不得誤擋）。

        與 DT-001/002 成對。只證明「擋得住」不夠：一個 repo_root 接錯、或永遠 raise 的
        guard 會讓 DT-001/002 全綠，而 install 在主 repo 已經永久壞掉且零測試訊號
        （由 mob review 的 pr-test-analyzer 指出——mycelium 與 wrapper 都有這一半，
        只有 scheduler 漏了）。
        """
        main_repo = _make_repo(tmp_path / "main")
        venv_bin = main_repo / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("", encoding="utf-8")
        plist = tmp_path / "ok.plist"

        class _FakeSubprocess:
            @staticmethod
            def run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("tasks._worktree_guard.PROJECT_ROOT", main_repo),
            patch("tasks.scheduler.cli.PROJECT_ROOT", main_repo),
            patch("tasks.scheduler.cli._PLIST_PATH", plist),
            patch("tasks.scheduler.cli.subprocess", _FakeSubprocess),
        ):
            result = runner.invoke(cli, ["install"])

        assert result.exit_code == 0, f"主 repo 被誤擋：{result.output}"
        assert plist.exists(), "主 repo 安裝未寫出 plist"
        assert str(main_repo) in plist.read_text(encoding="utf-8"), "plist 未嵌入主 repo 路徑"
