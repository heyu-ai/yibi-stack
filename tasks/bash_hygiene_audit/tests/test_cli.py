"""BHAUDIT-ST CLI 層測試。"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tasks.bash_hygiene_audit.cli import cli


def _base_record(verdict: str = "allow", hook: str = "ap1") -> dict[str, object]:
    return {
        "ts": "2026-05-21T00:00:00Z",
        "hook": hook,
        "hook_version": "2",
        "exit_code": 2 if verdict == "block" else 0,
        "verdict": verdict,
        "block_reason": "ap2-unicode" if verdict == "block" else None,
        "cmd_snippet": "echo test",
        "command_hash": "abc123",
        "session_id": None,
        "duration_ms": 5,
    }


class TestEnableDisable:
    def test_bhaudit_st_010_enable_sets_flag(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-010: enable 指令寫入 audit_enabled=true。"""
        import tasks.bash_hygiene_audit.config as cfg_mod

        orig = cfg_mod._CONFIG_PATH
        cfg_mod._CONFIG_PATH = tmp_path / "bash-hygiene.json"
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["enable"])
            assert result.exit_code == 0
            assert "[OK]" in result.output
            data = json.loads((tmp_path / "bash-hygiene.json").read_text())
            assert data["audit_enabled"] is True
        finally:
            cfg_mod._CONFIG_PATH = orig

    def test_bhaudit_st_011_disable_sets_flag(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-011: disable 指令寫入 audit_enabled=false。"""
        import tasks.bash_hygiene_audit.config as cfg_mod

        orig = cfg_mod._CONFIG_PATH
        cfg_mod._CONFIG_PATH = tmp_path / "bash-hygiene.json"
        try:
            runner = CliRunner()
            runner.invoke(cli, ["enable"])
            result = runner.invoke(cli, ["disable"])
            assert result.exit_code == 0
            data = json.loads((tmp_path / "bash-hygiene.json").read_text())
            assert data["audit_enabled"] is False
        finally:
            cfg_mod._CONFIG_PATH = orig


class TestShow:
    def test_bhaudit_st_012_show_no_log(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-012: log 不存在時顯示「無記錄」。"""
        import tasks.bash_hygiene_audit.service as svc_mod

        orig_fn = svc_mod._find_log_path

        def mock_fn(project_root: Path | None = None) -> Path | None:
            return tmp_path / "nonexistent.jsonl"

        svc_mod._find_log_path = mock_fn
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["show"])
            assert result.exit_code == 0
            assert "無記錄" in result.output
        finally:
            svc_mod._find_log_path = orig_fn

    def test_bhaudit_st_013_show_records(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-013: show 指令正確顯示 verdict 和 hook。"""
        import tasks.bash_hygiene_audit.service as svc_mod

        log = tmp_path / "bash-hygiene-audit.jsonl"
        log.write_text(json.dumps(_base_record("block")) + "\n")

        orig_fn = svc_mod._find_log_path

        def mock_fn(project_root: Path | None = None) -> Path | None:
            return log

        svc_mod._find_log_path = mock_fn
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["show"])
            assert result.exit_code == 0
            assert "[BLOCK]" in result.output
            assert "ap1" in result.output
        finally:
            svc_mod._find_log_path = orig_fn

    def test_bhaudit_st_016_show_error_verdict(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-016: show 指令對 error verdict 顯示 [ERROR]（非 [ALLOW]）。"""
        import tasks.bash_hygiene_audit.service as svc_mod

        record = {**_base_record("allow"), "verdict": "error", "exit_code": 1}
        log = tmp_path / "bash-hygiene-audit.jsonl"
        log.write_text(json.dumps(record) + "\n")

        orig_fn = svc_mod._find_log_path

        def mock_fn(project_root: Path | None = None) -> Path | None:
            return log

        svc_mod._find_log_path = mock_fn
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["show"])
            assert result.exit_code == 0
            assert "[ERROR]" in result.output
            assert "[ALLOW]" not in result.output
        finally:
            svc_mod._find_log_path = orig_fn


class TestStatus:
    def test_bhaudit_st_015_status_shows_off(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-015: status 在 audit 停用時顯示 [OFF]。"""
        import tasks.bash_hygiene_audit.config as cfg_mod
        import tasks.bash_hygiene_audit.service as svc_mod

        orig_cfg = cfg_mod._CONFIG_PATH
        orig_fn = svc_mod._find_log_path
        cfg_mod._CONFIG_PATH = tmp_path / "nonexistent.json"
        svc_mod._find_log_path = lambda project_root=None: None
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "[OFF]" in result.output
            assert "尚無記錄" in result.output
        finally:
            cfg_mod._CONFIG_PATH = orig_cfg
            svc_mod._find_log_path = orig_fn


class TestStats:
    def test_bhaudit_st_014_stats_output(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-014: stats 指令輸出總計和 block 百分比。"""
        import tasks.bash_hygiene_audit.service as svc_mod

        log = tmp_path / "bash-hygiene-audit.jsonl"
        records = [_base_record("allow"), _base_record("block"), _base_record("allow")]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")

        orig_fn = svc_mod._find_log_path

        def mock_fn(project_root: Path | None = None) -> Path | None:
            return log

        svc_mod._find_log_path = mock_fn
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["stats"])
            assert result.exit_code == 0
            assert "3" in result.output
            assert "33.3%" in result.output
        finally:
            svc_mod._find_log_path = orig_fn
