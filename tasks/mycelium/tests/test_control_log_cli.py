"""Control log CLI 測試（CTL-CV-001~003）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.control_log_service import write_control_log
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import ControlLogCategory, ControlLogEntry


def _seed(db_path: Path, pr: int = 1, count: int = 1, **kwargs: object) -> None:
    for i in range(count):
        entry = ControlLogEntry(
            pr_number=pr,
            category=ControlLogCategory.autonomous_decision,
            summary=f"decision {i}",
            user_requested=0,
            **kwargs,
        )
        write_control_log(entry, db_path=db_path)


def _env(db_path: Path) -> dict[str, str]:
    return {**os.environ, "MYCELIUM_DB_OVERRIDE": str(db_path)}


class TestControlLogCLI:
    def test_ctl_cv_001_add_writes_entry(self, tmp_path: Path) -> None:
        """CTL-CV-001: control-log add 輸出 '已寫入 control log entry (id=N)'，DB 有寫入。"""
        db = tmp_path / "t.db"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "control-log",
                "add",
                "--pr",
                "42",
                "--category",
                "autonomous_decision",
                "--summary",
                "Chose SQLite WAL mode",
                "--user-requested",
                "0",
            ],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "已寫入 control log entry (id=" in result.output

        db_obj = AgentsDB(db)
        db_obj.init_db()
        rows = db_obj.query_control_log_entries(pr_number=42)
        db_obj.close()
        assert len(rows) == 1
        assert rows[0]["summary"] == "Chose SQLite WAL mode"

    def test_ctl_cv_002_show_lists_entries(self, tmp_path: Path) -> None:
        """CTL-CV-002: control-log show --pr N 列出該 PR 所有 entries。"""
        db = tmp_path / "t.db"
        _seed(db, pr=10, count=3)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["control-log", "show", "--pr", "10"],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "decision 0" in result.output
        assert "decision 2" in result.output

    def test_ctl_cv_003_stats_json_parseable(self, tmp_path: Path) -> None:
        """CTL-CV-003: control-log stats --json 輸出可 json.loads() 解析，含四個核心欄位。"""
        db = tmp_path / "t.db"
        _seed(db, pr=1, count=5)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["control-log", "stats", "--json"],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "autonomy_ratio" in data
        assert "deviation_ratio" in data
        assert "irreversible_op_count" in data
        assert "verification_score" in data
        assert "total_entries" in data
        assert data["total_entries"] == 5

    def test_ctl_cv_010_add_invalid_user_requested_exits_nonzero(self, tmp_path: Path) -> None:
        """CTL-CV-010: control-log add --user-requested 2 觸發 Pydantic 驗證失敗，非零退出。"""
        db = tmp_path / "t.db"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "control-log",
                "add",
                "--pr",
                "1",
                "--category",
                "assumption",
                "--summary",
                "test summary",
                "--user-requested",
                "2",
            ],
            env=_env(db),
        )
        assert result.exit_code != 0

    def test_ctl_cv_004_add_files_valid_json(self, tmp_path: Path) -> None:
        """CTL-CV-004: control-log add --files '[\"foo.py\"]' 成功寫入。"""
        db = tmp_path / "t.db"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "control-log",
                "add",
                "--pr",
                "1",
                "--category",
                "assumption",
                "--summary",
                "test summary",
                "--user-requested",
                "0",
                "--files",
                '["foo.py"]',
            ],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "已寫入" in result.output

    def test_ctl_cv_005_add_files_invalid_json_exits_1(self, tmp_path: Path) -> None:
        """CTL-CV-005: control-log add --files 'not json' 應 exit 1。"""
        db = tmp_path / "t.db"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "control-log",
                "add",
                "--pr",
                "1",
                "--category",
                "assumption",
                "--summary",
                "test summary",
                "--user-requested",
                "0",
                "--files",
                "not-json",
            ],
            env=_env(db),
        )
        assert result.exit_code == 1

    def test_ctl_cv_006_add_invalid_severity_exits_nonzero(self, tmp_path: Path) -> None:
        """CTL-CV-006: control-log add 傳入無效 severity 應非零退出（Click choice validation）。"""
        db = tmp_path / "t.db"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "control-log",
                "add",
                "--pr",
                "1",
                "--category",
                "assumption",
                "--summary",
                "test summary",
                "--user-requested",
                "0",
                "--severity",
                "critical",
            ],
            env=_env(db),
        )
        assert result.exit_code != 0

    def test_ctl_cv_007_show_no_entries_prints_empty_message(self, tmp_path: Path) -> None:
        """CTL-CV-007: control-log show --pr N 無 entries 時輸出空訊息。"""
        db = tmp_path / "t.db"
        db_obj = AgentsDB(db)
        db_obj.init_db()
        db_obj.close()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["control-log", "show", "--pr", "99"],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "無 entries" in result.output

    def test_ctl_cv_008_stats_text_output(self, tmp_path: Path) -> None:
        """CTL-CV-008: control-log stats（無 --json）輸出含 autonomy_ratio 文字行。"""
        db = tmp_path / "t.db"
        _seed(db, pr=1, count=3)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["control-log", "stats"],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "autonomy_ratio" in result.output
        assert "total_entries" in result.output

    def test_ctl_cv_009_advice_command_runs(self, tmp_path: Path) -> None:
        """CTL-CV-009: control-log advice 指令可執行，回傳建議字串。"""
        db = tmp_path / "t.db"
        _seed(db, pr=1, count=1)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["control-log", "advice"],
            env=_env(db),
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0
