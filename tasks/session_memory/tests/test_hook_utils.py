"""Tests for _hook_utils generic hook management API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tasks.session_memory._hook_utils import (
    install_hook,
    install_stop_hook,
    list_hooks,
    read_settings,
    uninstall_hook,
    uninstall_stop_hook,
    write_settings,
)


def _make_settings(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return p


class TestInstallHook:
    def test_install_new_hook(self, tmp_path: Path) -> None:
        """HOOK-DT-001: 新增 hook 到空 settings。"""
        path = tmp_path / "settings.json"
        is_new, msg = install_hook(
            hook_type="Stop",
            marker="session_memory",
            hook_label="Session Memory",
            hook_command="uv run python -m tasks.session_memory stop",
            settings_path=path,
        )
        assert is_new is True
        assert "已註冊" in msg
        data = json.loads(path.read_text())
        assert len(data["hooks"]["Stop"]) == 1
        cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "session_memory" in cmd

    def test_install_idempotent(self, tmp_path: Path) -> None:
        """HOOK-DT-002: 重複安裝相同 marker 應跳過。"""
        path = tmp_path / "settings.json"
        install_hook("Stop", "session_memory", "SM", "cmd", settings_path=path)
        is_new, msg = install_hook("Stop", "session_memory", "SM", "cmd", settings_path=path)
        assert is_new is False
        assert "跳過" in msg
        data = json.loads(path.read_text())
        assert len(data["hooks"]["Stop"]) == 1

    def test_install_different_hook_types(self, tmp_path: Path) -> None:
        """HOOK-DT-003: 不同 hook_type 互不干擾。"""
        path = tmp_path / "settings.json"
        install_hook("Stop", "marker_stop", "Stop Hook", "stop-cmd", settings_path=path)
        install_hook("PreToolUse", "marker_pre", "Pre Hook", "pre-cmd", settings_path=path)

        data = json.loads(path.read_text())
        assert "Stop" in data["hooks"]
        assert "PreToolUse" in data["hooks"]
        assert len(data["hooks"]["Stop"]) == 1
        assert len(data["hooks"]["PreToolUse"]) == 1

    def test_install_with_matcher(self, tmp_path: Path) -> None:
        """HOOK-DT-004: matcher 欄位正確寫入。"""
        path = tmp_path / "settings.json"
        install_hook(
            "PreToolUse", "mymarker", "My Hook", "my-cmd",
            settings_path=path, matcher="Bash(git *)"
        )
        data = json.loads(path.read_text())
        assert data["hooks"]["PreToolUse"][0]["matcher"] == "Bash(git *)"


class TestUninstallHook:
    def test_uninstall_existing_hook(self, tmp_path: Path) -> None:
        """HOOK-DT-005: 移除已存在的 hook。"""
        path = tmp_path / "settings.json"
        install_hook("Stop", "session_memory", "SM", "sm-cmd", settings_path=path)
        removed, msg = uninstall_hook("Stop", "session_memory", "SM", settings_path=path)
        assert removed is True
        data = json.loads(path.read_text())
        assert data["hooks"]["Stop"] == []

    def test_uninstall_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """HOOK-DT-006: 移除不存在的 hook 回傳 False。"""
        path = _make_settings(tmp_path, {"hooks": {"Stop": []}})
        removed, msg = uninstall_hook("Stop", "nonexistent_marker", "Missing", settings_path=path)
        assert removed is False

    def test_uninstall_missing_settings_file(self, tmp_path: Path) -> None:
        """HOOK-DT-007: settings.json 不存在時回傳 False。"""
        path = tmp_path / "nonexistent.json"
        removed, msg = uninstall_hook("Stop", "any", "Any", settings_path=path)
        assert removed is False
        assert "不存在" in msg

    def test_uninstall_only_removes_matching(self, tmp_path: Path) -> None:
        """HOOK-DT-008: 只移除 marker 符合的 hook，不影響其他 hook。"""
        path = tmp_path / "settings.json"
        install_hook("Stop", "hook_a", "Hook A", "cmd-a", settings_path=path)
        install_hook("Stop", "hook_b", "Hook B", "cmd-b", settings_path=path)
        uninstall_hook("Stop", "hook_a", "Hook A", settings_path=path)
        data = json.loads(path.read_text())
        remaining_cmds = [
            h["command"]
            for entry in data["hooks"]["Stop"]
            for h in entry["hooks"]
        ]
        assert all("hook_b" in c for c in remaining_cmds)


class TestListHooks:
    def test_list_empty(self, tmp_path: Path) -> None:
        """HOOK-DT-009: 無 hook 時回傳空清單。"""
        path = _make_settings(tmp_path, {})
        result = list_hooks("Stop", settings_path=path)
        assert result == []

    def test_list_returns_entries(self, tmp_path: Path) -> None:
        """HOOK-DT-010: 正確回傳已安裝的條目。"""
        path = tmp_path / "settings.json"
        install_hook("Stop", "session_memory", "SM", "sm-cmd", settings_path=path)
        result = list_hooks("Stop", settings_path=path)
        assert len(result) == 1
        assert result[0]["hooks"][0]["command"] == "sm-cmd"


class TestStopHookBackwardCompat:
    def test_install_stop_hook_delegates(self, tmp_path: Path) -> None:
        """HOOK-BC-001: install_stop_hook 透過 install_hook 正常運作。"""
        path = tmp_path / "settings.json"
        is_new, _ = install_stop_hook(
            "session_memory", "SM", settings_path=path, hook_command="sm-cmd"
        )
        assert is_new is True

    def test_uninstall_stop_hook_delegates(self, tmp_path: Path) -> None:
        """HOOK-BC-002: uninstall_stop_hook 透過 uninstall_hook 正常運作。"""
        path = tmp_path / "settings.json"
        install_stop_hook("session_memory", "SM", settings_path=path, hook_command="sm-cmd")
        removed, _ = uninstall_stop_hook("session_memory", "SM", settings_path=path)
        assert removed is True


class TestReadWriteSettings:
    def test_read_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """HOOK-EG-001: 讀取不存在的 settings.json 回傳空 dict。"""
        result = read_settings(tmp_path / "missing.json")
        assert result == {}

    def test_read_invalid_json_raises(self, tmp_path: Path) -> None:
        """HOOK-EG-002: settings.json 非法 JSON 時 raise RuntimeError。"""
        bad = tmp_path / "settings.json"
        bad.write_text("{not valid json}", encoding="utf-8")
        with pytest.raises(RuntimeError, match="格式錯誤"):
            read_settings(bad)

    def test_read_non_dict_raises(self, tmp_path: Path) -> None:
        """HOOK-EG-003: settings.json 根層非 object 時 raise RuntimeError。"""
        bad = tmp_path / "settings.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(RuntimeError, match="根層必須為"):
            read_settings(bad)

    def test_write_creates_parent(self, tmp_path: Path) -> None:
        """HOOK-EG-004: write_settings 自動建立父目錄。"""
        nested = tmp_path / "a" / "b" / "settings.json"
        write_settings(nested, {"key": "value"})
        assert nested.exists()
        assert json.loads(nested.read_text())["key"] == "value"
