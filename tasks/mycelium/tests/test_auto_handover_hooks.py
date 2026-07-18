"""測試 auto_handover_hooks：install / uninstall 冪等行為。"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest

from tasks.mycelium import auto_handover_hooks
from tasks.mycelium.auto_handover_hooks import (
    MyceliumBinaryNotFoundError,
    install_hooks,
    uninstall_hooks,
)


@pytest.fixture(autouse=True)
def fake_mycelium_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把可執行 fake mycelium 放進名稱含空白的 PATH 目錄。"""
    bin_dir = tmp_path / "mycelium tool" / "bin dir"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "mycelium"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    current_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", os.pathsep.join((str(bin_dir), current_path)))
    return binary.resolve()


class TestInstallHooks:
    def test_agents_ah_001_install_creates_both_entries(
        self, tmp_path: Path, fake_mycelium_on_path: Path
    ) -> None:
        """AGENTS-AH-001：全新 settings.json，安裝後有 PreCompact + SessionStart 兩個 hook。"""
        settings = tmp_path / "settings.json"
        precompact_new, session_new, _ = install_hooks(settings_path=settings)

        assert precompact_new is True
        assert session_new is True

        data = json.loads(settings.read_text(encoding="utf-8"))
        precompact_hooks = data["hooks"]["PreCompact"]
        session_start_hooks = data["hooks"]["SessionStart"]
        assert len(precompact_hooks) == 1
        assert len(session_start_hooks) == 1

        precompact_cmd = precompact_hooks[0]["hooks"][0]["command"]
        session_cmd = session_start_hooks[0]["hooks"][0]["command"]
        assert shlex.split(precompact_cmd) == [
            str(fake_mycelium_on_path),
            "hooks",
            "pre-compact",
        ]
        assert shlex.split(session_cmd) == [
            str(fake_mycelium_on_path),
            "hooks",
            "session-start",
        ]
        assert precompact_cmd.startswith("'")
        assert session_cmd.startswith("'")
        for command in (precompact_cmd, session_cmd):
            assert "python -m tasks.mycelium" not in command
            assert "uvx" not in command
            assert "uv run" not in command

    def test_agents_ah_002_precompact_matcher_is_auto(self, tmp_path: Path) -> None:
        """AGENTS-AH-002：PreCompact hook 的 matcher 必須是 'auto'（不攔截手動 compact）。"""
        settings = tmp_path / "settings.json"
        install_hooks(settings_path=settings)

        data = json.loads(settings.read_text(encoding="utf-8"))
        matcher = data["hooks"]["PreCompact"][0]["matcher"]
        assert matcher == "auto"

    def test_agents_ah_003_install_idempotent(self, tmp_path: Path) -> None:
        """AGENTS-AH-003：重複 install 回傳 is_new=False，不重複新增 entry。"""
        settings = tmp_path / "settings.json"
        install_hooks(settings_path=settings)
        precompact_new, session_new, _ = install_hooks(settings_path=settings)

        assert precompact_new is False
        assert session_new is False

        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["PreCompact"]) == 1
        assert len(data["hooks"]["SessionStart"]) == 1

    def test_agents_ah_004_install_preserves_existing_hooks(self, tmp_path: Path) -> None:
        """AGENTS-AH-004：install 不影響已有的其他 hook entries。"""
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {"matcher": "", "hooks": [{"type": "command", "command": "other-tool"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        install_hooks(settings_path=settings)

        data = json.loads(settings.read_text(encoding="utf-8"))
        stop_cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
        assert "other-tool" in stop_cmds
        assert "PreCompact" in data["hooks"]
        assert "SessionStart" in data["hooks"]

    def test_mycli_st_005_install_preserves_shared_entry_matcher(self, tmp_path: Path) -> None:
        """MYCLI-ST-005: shared entry 更新 owned hook 時保留 custom matcher。
        spec: mycelium-cli#settings-hooks-use-stable-binary"""
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreCompact": [
                            {
                                "matcher": "custom-matcher",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": ".claude/hooks/pre-compact-handover.sh",
                                    },
                                    {"type": "command", "command": "foreign-hook"},
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        install_hooks(settings_path=settings)

        data = json.loads(settings.read_text(encoding="utf-8"))
        entry = data["hooks"]["PreCompact"][0]
        assert entry["matcher"] == "custom-matcher"
        assert entry["hooks"][1]["command"] == "foreign-hook"
        assert "hooks pre-compact" in entry["hooks"][0]["command"]

    def test_agents_ah_005_install_to_nonexistent_settings(self, tmp_path: Path) -> None:
        """AGENTS-AH-005：settings.json 不存在時，install 會自動建立。"""
        settings = tmp_path / "subdir" / "settings.json"
        settings.parent.mkdir()
        install_hooks(settings_path=settings)

        assert settings.exists()
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "PreCompact" in data["hooks"]

    def test_mycli_st_005_missing_binary_fails_without_writing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """MYCLI-ST-005: PATH 無 mycelium 時 fail-loud，且 settings 保持原樣。
        spec: mycelium-cli#settings-hooks-use-stable-binary"""
        empty_bin = tmp_path / "empty bin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))
        settings = tmp_path / "settings.json"
        original = json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}
        )
        settings.write_text(original, encoding="utf-8")

        with pytest.raises(MyceliumBinaryNotFoundError):
            install_hooks(settings_path=settings)

        assert "[FAIL]" in capsys.readouterr().err
        assert settings.read_text(encoding="utf-8") == original


class TestRunPreCompactHook:
    def test_mycli_st_005_concurrent_state_deletion_is_graceful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCLI-ST-005: state file 在 stat 與 unlink 間消失時仍正常 passthrough。
        spec: mycelium-cli#settings-hooks-use-stable-binary"""
        monkeypatch.setattr(auto_handover_hooks, "_STATE_DIR", tmp_path)
        state_file = tmp_path / "claude-handover-suggested-race-session"
        state_file.touch()
        real_unlink = Path.unlink

        def delete_before_unlink(path: Path, missing_ok: bool = False) -> None:
            if path == state_file and path.exists():
                real_unlink(path)
            real_unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", delete_before_unlink)
        payload = json.dumps(
            {
                "hook_event_name": "PreCompact",
                "session_id": "race-session",
                "matcher": "auto",
            }
        )

        assert auto_handover_hooks.run_pre_compact_hook(payload) == (0, None)

    def test_mycli_st_005_permission_denied_touch_still_intercepts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCLI-ST-005: state touch 權限錯誤時仍回傳 intercept 訊息。
        spec: mycelium-cli#settings-hooks-use-stable-binary"""
        monkeypatch.setattr(auto_handover_hooks, "_STATE_DIR", tmp_path)
        state_file = tmp_path / "claude-handover-suggested-denied-session"
        real_touch = Path.touch

        def deny_state_touch(
            path: Path, mode: int = 0o666, exist_ok: bool = True
        ) -> None:
            if path == state_file:
                raise PermissionError("state file is not writable")
            real_touch(path, mode, exist_ok)

        monkeypatch.setattr(Path, "touch", deny_state_touch)
        payload = json.dumps(
            {
                "hook_event_name": "PreCompact",
                "session_id": "denied-session",
                "matcher": "auto",
            }
        )

        with pytest.warns(UserWarning, match="無法寫入狀態檔"):
            exit_code, message = auto_handover_hooks.run_pre_compact_hook(payload)

        assert exit_code == 2
        assert message is not None
        assert "/handover" in message

    def test_mycli_st_005_malformed_json_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCLI-ST-005: malformed JSON payload 靜默 passthrough。
        spec: mycelium-cli#settings-hooks-use-stable-binary"""
        monkeypatch.setattr(auto_handover_hooks, "_STATE_DIR", tmp_path)

        assert auto_handover_hooks.run_pre_compact_hook("{not-json") == (0, None)


class TestUninstallHooks:
    def test_agents_ah_010_uninstall_removes_both_entries(self, tmp_path: Path) -> None:
        """AGENTS-AH-010：install 後 uninstall，兩個 hook 都被移除。"""
        settings = tmp_path / "settings.json"
        install_hooks(settings_path=settings)
        removed, _ = uninstall_hooks(settings_path=settings)

        assert removed is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["hooks"].get("PreCompact", []) == []
        assert data["hooks"].get("SessionStart", []) == []

    def test_agents_ah_011_uninstall_missing_settings(self, tmp_path: Path) -> None:
        """AGENTS-AH-011：settings.json 不存在時回傳 False，不報錯。"""
        removed, msg = uninstall_hooks(settings_path=tmp_path / "nope.json")
        assert removed is False
        assert "不存在" in msg

    def test_agents_ah_012_uninstall_nothing_to_remove(self, tmp_path: Path) -> None:
        """AGENTS-AH-012：沒有 auto-handover hooks 時回傳 False，不報錯。"""
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps({"hooks": {"Stop": []}}),
            encoding="utf-8",
        )
        removed, _ = uninstall_hooks(settings_path=settings)
        assert removed is False

    def test_agents_ah_013_uninstall_preserves_other_hooks(self, tmp_path: Path) -> None:
        """AGENTS-AH-013：uninstall 不影響同事件下其他 hook entries。"""
        settings = tmp_path / "settings.json"
        install_hooks(settings_path=settings)

        # 在 PreCompact 下加入另一個 hook
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"]["PreCompact"].append(
            {"matcher": "manual", "hooks": [{"type": "command", "command": "other-hook"}]}
        )
        settings.write_text(json.dumps(data), encoding="utf-8")

        uninstall_hooks(settings_path=settings)

        data2 = json.loads(settings.read_text(encoding="utf-8"))
        precompact_entries = data2["hooks"].get("PreCompact", [])
        all_cmds = [h["command"] for e in precompact_entries for h in e["hooks"]]
        assert "other-hook" in all_cmds
        assert not any("hooks pre-compact" in c for c in all_cmds)
