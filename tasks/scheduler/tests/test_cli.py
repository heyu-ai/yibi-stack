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


class TestLaunchAgentPath:
    """LaunchAgent 的 PATH 必須能真的跑起 job 的執行檔。

    實測事故（PR #256）：plist 的 PATH 寫死成
    `~/.local/bin:~/.cargo/bin:/usr/local/bin:/usr/bin:/bin`，但 uv 裝在 `~/.asdf/shims/uv`。
    `nightly-self-improvement` 因此連續 4 晚（7/13～7/16）在 4 毫秒內 spawn 失敗
    （`[Errno 2] No such file or directory: 'uv'`），而 log 只寫 exit_code=1 不寫原因，
    真正的錯誤躺在沒人查的 DB 欄位裡 -> 壞了 4 天沒人發現。
    """

    def test_sched_dt_004_path_inherits_the_installing_environment(self, tmp_path: Path) -> None:
        """SCHED-DT-004: plist 的 PATH 必須繼承 install 當下的 PATH。

        install 是使用者在自己的 shell 裡跑的，那個 PATH 是**唯一被證明可行**的——
        工具就是在那裡跑得動的。寫死一份清單則必然漏掉 asdf/mise/pyenv 這類版本管理器
        的目錄（實測事故：uv 在 ~/.asdf/shims，寫死的 PATH 沒有它，連壞 4 晚）。

        用一個不可能出現在任何預設清單裡的目錄，確保測到的是「繼承」而非碰巧命中。
        """
        from ..cli import _build_launchagent_path
        from ..models import ScheduleConfig

        exotic = str(tmp_path / "some" / "exotic" / "toolchain" / "bin")

        with patch.dict("os.environ", {"PATH": f"{exotic}:/usr/bin"}):
            path_env = _build_launchagent_path("/home/u", ScheduleConfig(jobs=[]))

        assert exotic in path_env.split(":"), f"install 當下 PATH 裡的目錄必須被繼承：{path_env}"

    def test_sched_dt_007_path_keeps_base_dirs_even_in_minimal_env(self, tmp_path: Path) -> None:
        """SCHED-DT-007: 即使 install 在極簡環境下跑（如 CI），基礎目錄仍要在 PATH 裡。"""
        from ..cli import _build_launchagent_path
        from ..models import ScheduleConfig

        with patch.dict("os.environ", {"PATH": "/nonstandard/only"}):
            path_env = _build_launchagent_path("/home/u", ScheduleConfig(jobs=[]))

        parts = path_env.split(":")
        assert "/usr/bin" in parts and "/bin" in parts, f"基礎目錄遺失：{path_env}"
        assert "/home/u/.local/bin" in parts, f"~/.local/bin 遺失：{path_env}"

    def test_sched_dt_005_install_fails_loud_when_binary_unresolvable(self, tmp_path: Path) -> None:
        """SCHED-DT-005: 啟用中的 job 其執行檔在 PATH 裡找不到 -> install 必須大聲失敗。

        這道 gate 是本次事故的真正修法：LaunchAgent 在半夜跑，spawn 失敗沒人看得到。
        install 時就擋下來，好過每晚安靜失敗。
        """
        from ..cli import _assert_job_binaries_resolvable
        from ..models import JobConfig, ScheduleConfig

        config = ScheduleConfig(
            jobs=[
                JobConfig(
                    id="nightly-x",
                    description="test",
                    schedule="daily",
                    time="21:00",
                    command=["definitely-not-installed-xyz", "run"],
                )
            ]
        )

        with pytest.raises(SystemExit) as exc:
            _assert_job_binaries_resolvable(config, "/usr/bin:/bin")
        assert exc.value.code == 1

    def test_sched_dt_006_disabled_job_does_not_block_install(self, tmp_path: Path) -> None:
        """SCHED-DT-006: 停用的 job 其執行檔找不到，不該擋住 install。

        本 repo 的 schedules.json 有 4 個停用的 job（gmail-billing 等），它們的執行檔
        不一定裝在這台機器上。只有**啟用中**的 job 才是這道 gate 的守備範圍。
        """
        from ..cli import _assert_job_binaries_resolvable
        from ..models import JobConfig, ScheduleConfig

        config = ScheduleConfig(
            jobs=[
                JobConfig(
                    id="disabled-x",
                    description="test",
                    schedule="daily",
                    time="21:00",
                    command=["definitely-not-installed-xyz"],
                    enabled=False,
                )
            ]
        )

        _assert_job_binaries_resolvable(config, "/usr/bin:/bin")  # 不得 raise
