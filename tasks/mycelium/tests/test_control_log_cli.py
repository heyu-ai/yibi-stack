"""Control log CLI 測試（CTL-CV-001~003）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import ControlLogCategory, ControlLogEntry
from tasks.mycelium.control_log_service import write_control_log


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


class TestControlLogCLI:
    def test_ctl_cv_001_add_writes_entry(self, tmp_path: Path) -> None:
        """CTL-CV-001: control-log add 輸出 '已寫入 control log entry (id=N)'，DB 有寫入。"""
        db = tmp_path / "t.db"
        runner = CliRunner()
        env = {**os.environ, "MYCELIUM_DB_OVERRIDE": str(db)}
        result = runner.invoke(
            cli,
            [
                "control-log",
                "add",
                "--pr", "42",
                "--category", "autonomous_decision",
                "--summary", "Chose SQLite WAL mode",
                "--user-requested", "0",
            ],
            env=env,
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
        env = {**os.environ, "MYCELIUM_DB_OVERRIDE": str(db)}
        result = runner.invoke(
            cli,
            ["control-log", "show", "--pr", "10"],
            env=env,
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
        env = {**os.environ, "MYCELIUM_DB_OVERRIDE": str(db)}
        result = runner.invoke(
            cli,
            ["control-log", "stats", "--json"],
            env=env,
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
