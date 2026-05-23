"""BHAUDIT-FL: _audit_log.py fail-safe 合約測試。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_HOOK_DIR = Path(__file__).parents[3] / "plugins" / "bash-hygiene" / "hooks"

# 動態載入 _audit_log 模組（不在 tasks package 內）
_spec = importlib.util.spec_from_file_location("_audit_log", _HOOK_DIR / "_audit_log.py")
assert _spec is not None and _spec.loader is not None
_audit_log = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_audit_log", _audit_log)
_spec.loader.exec_module(_audit_log)


class TestEnabled:
    def test_bhaudit_fl_001_no_config_returns_false(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-001: config 檔不存在時 _enabled() 回傳 False。"""
        with patch.object(_audit_log, "CONFIG_PATH", tmp_path / "nonexistent.json"):
            assert _audit_log._enabled() is False

    def test_bhaudit_fl_002_corrupt_config_returns_false(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-002: config 檔損壞（非法 JSON）時 _enabled() 回傳 False，不拋例外。"""
        cfg = tmp_path / "bash-hygiene.json"
        cfg.write_text("not valid json", encoding="utf-8")
        with patch.object(_audit_log, "CONFIG_PATH", cfg):
            assert _audit_log._enabled() is False

    def test_bhaudit_fl_003_audit_disabled_returns_false(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-003: audit_enabled=false 時 _enabled() 回傳 False。"""
        cfg = tmp_path / "bash-hygiene.json"
        cfg.write_text(json.dumps({"audit_enabled": False}), encoding="utf-8")
        with patch.object(_audit_log, "CONFIG_PATH", cfg):
            assert _audit_log._enabled() is False

    def test_bhaudit_fl_004_audit_enabled_returns_true(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-004: audit_enabled=true 時 _enabled() 回傳 True。"""
        cfg = tmp_path / "bash-hygiene.json"
        cfg.write_text(json.dumps({"audit_enabled": True}), encoding="utf-8")
        with patch.object(_audit_log, "CONFIG_PATH", cfg):
            assert _audit_log._enabled() is True


class TestLogPath:
    def test_bhaudit_fl_005_git_unavailable_returns_none(self) -> None:
        """BHAUDIT-FL-005: git rev-parse 失敗（非 git 環境）時 _log_path() 回傳 None。"""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 1
        with patch("subprocess.run", mock_run):
            assert _audit_log._log_path() is None

    def test_bhaudit_fl_006_subprocess_exception_returns_none(self) -> None:
        """BHAUDIT-FL-006: subprocess 拋出例外時 _log_path() 仍回傳 None，不傳播例外。"""
        with patch("subprocess.run", side_effect=Exception("timeout")):
            assert _audit_log._log_path() is None


class TestLogEvent:
    def test_bhaudit_fl_007_does_not_raise_when_disabled(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-007: audit 停用時 log_event() 不拋例外。"""
        with patch.object(_audit_log, "CONFIG_PATH", tmp_path / "nonexistent.json"):
            _audit_log.log_event("ap1", "echo test", exit_code=0)

    def test_bhaudit_fl_008_does_not_raise_when_path_none(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-008: _log_path() 回傳 None 時 log_event() 不拋例外。"""
        cfg = tmp_path / "bash-hygiene.json"
        cfg.write_text(json.dumps({"audit_enabled": True}), encoding="utf-8")
        with (
            patch.object(_audit_log, "CONFIG_PATH", cfg),
            patch.object(_audit_log, "_log_path", return_value=None),
        ):
            _audit_log.log_event("ap1", "echo test", exit_code=0)

    def test_bhaudit_fl_009_writes_record_when_enabled(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-009: audit 啟用時正確寫入 JSONL 記錄。"""
        cfg = tmp_path / "bash-hygiene.json"
        cfg.write_text(json.dumps({"audit_enabled": True}), encoding="utf-8")
        log_file = tmp_path / "audit.jsonl"
        with (
            patch.object(_audit_log, "CONFIG_PATH", cfg),
            patch.object(_audit_log, "_log_path", return_value=log_file),
        ):
            _audit_log.log_event("ap2", "echo hello", exit_code=2, block_reason="ap2-unicode")
        assert log_file.is_file()
        record = json.loads(log_file.read_text("utf-8").strip())
        assert record["hook"] == "ap2"
        assert record["verdict"] == "block"
        assert record["block_reason"] == "ap2-unicode"
        assert record["cmd_snippet"] == "echo hello"

    def test_bhaudit_fl_010_exception_in_write_does_not_propagate(self, tmp_path: Path) -> None:
        """BHAUDIT-FL-010: 寫入過程拋出例外時 log_event() 仍不傳播例外（fail-safe）。"""
        cfg = tmp_path / "bash-hygiene.json"
        cfg.write_text(json.dumps({"audit_enabled": True}), encoding="utf-8")
        with (
            patch.object(_audit_log, "CONFIG_PATH", cfg),
            patch.object(_audit_log, "_log_path", side_effect=Exception("disk full")),
        ):
            _audit_log.log_event("ap1", "echo test", exit_code=0)
