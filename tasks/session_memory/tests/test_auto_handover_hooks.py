"""測試 auto_handover_hooks：install / uninstall 冪等行為。"""

from __future__ import annotations

import json
from pathlib import Path

from tasks.session_memory.auto_handover_hooks import install_hooks, uninstall_hooks


class TestInstallHooks:
    def test_agents_ah_001_install_creates_both_entries(self, tmp_path: Path) -> None:
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
        assert "pre-compact-handover.sh" in precompact_cmd
        assert "post-compact-handover-back.sh" in session_cmd

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

    def test_agents_ah_005_install_to_nonexistent_settings(self, tmp_path: Path) -> None:
        """AGENTS-AH-005：settings.json 不存在時，install 會自動建立。"""
        settings = tmp_path / "subdir" / "settings.json"
        settings.parent.mkdir()
        install_hooks(settings_path=settings)

        assert settings.exists()
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "PreCompact" in data["hooks"]


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
        assert not any("pre-compact-handover.sh" in c for c in all_cmds)
