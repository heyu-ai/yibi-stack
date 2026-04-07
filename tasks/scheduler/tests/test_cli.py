"""測試 cli.py：setup、status、history 命令。"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ..cli import cli


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
