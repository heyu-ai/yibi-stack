"""測試 insight_hook：install / uninstall 冪等、run_hook 擷取 ★ Insight。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tasks.mycelium.insight_hook import install_hook, run_hook, uninstall_hook


class TestInstallHook:
    def test_agents_st_030_install_creates_entry(self, tmp_path: Path) -> None:
        """AGENTS-ST-030：全新 settings.json 被建立，hooks.Stop 有一筆 entry。"""
        settings = tmp_path / "settings.json"
        cmd = "/usr/bin/x tasks.mycelium insight collect"
        is_new, _ = install_hook(settings_path=settings, hook_command=cmd)

        assert is_new is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["Stop"]) == 1
        cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "tasks.mycelium insight collect" in cmd

    def test_agents_st_031_install_idempotent(self, tmp_path: Path) -> None:
        """AGENTS-ST-031：第二次 install 應回傳 is_new=False，settings.json 不新增 entry。"""
        settings = tmp_path / "settings.json"
        cmd = "/usr/bin/x tasks.mycelium insight collect"
        install_hook(settings_path=settings, hook_command=cmd)
        is_new, _ = install_hook(settings_path=settings, hook_command=cmd)

        assert is_new is False
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["Stop"]) == 1

    def test_agents_st_032_install_preserves_other_hooks(self, tmp_path: Path) -> None:
        """AGENTS-ST-032：install 不影響已有的其他 hook entries。"""
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

        install_hook(settings_path=settings, hook_command="x tasks.mycelium insight collect")

        data = json.loads(settings.read_text(encoding="utf-8"))
        commands = [h["command"] for entry in data["hooks"]["Stop"] for h in entry["hooks"]]
        assert "other-tool" in commands
        assert any("tasks.mycelium insight collect" in c for c in commands)


class TestUninstallHook:
    def test_agents_st_033_uninstall_removes_entry(self, tmp_path: Path) -> None:
        """AGENTS-ST-033：uninstall 移除本 skill 的 hook entry。"""
        settings = tmp_path / "settings.json"
        install_hook(settings_path=settings, hook_command="x tasks.mycelium insight collect")
        removed, _ = uninstall_hook(settings_path=settings)

        assert removed is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["hooks"]["Stop"] == []

    def test_agents_st_034_uninstall_missing_settings(self, tmp_path: Path) -> None:
        """AGENTS-ST-034：settings.json 不存在時回傳 False。"""
        removed, _ = uninstall_hook(settings_path=tmp_path / "nope.json")
        assert removed is False

    def test_agents_eg_035_install_upgrades_legacy_marker(self, tmp_path: Path) -> None:
        """AGENTS-EG-035：settings.json 已有舊版 session_memory marker 時，install 就地升級為新版。"""
        settings = tmp_path / "settings.json"
        new_cmd = "x tasks.mycelium insight collect"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "uv run python -m tasks.session_memory insight collect",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        is_new, msg = install_hook(settings_path=settings, hook_command=new_cmd)

        assert is_new is True
        assert "升級" in msg
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["Stop"]) == 1
        stored_cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert stored_cmd == new_cmd

    def test_agents_eg_036_uninstall_removes_legacy_marker(self, tmp_path: Path) -> None:
        """AGENTS-EG-036：uninstall 移除舊版 session_memory hook entry。"""
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "uv run python -m tasks.session_memory insight collect",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        removed, _ = uninstall_hook(settings_path=settings)

        assert removed is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["hooks"]["Stop"] == []


class TestRunHook:
    def test_agents_st_040_extracts_insight_block(self, tmp_path: Path) -> None:
        """AGENTS-ST-040：transcript 含 ★ Insight 區塊時寫一筆到 output JSONL。"""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "sess-1",
                    "cwd": str(tmp_path),
                    "gitBranch": "main",
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": ("前言\n`★ Insight ─────`\n這是一個洞察\n`─────`\n後記"),
                            }
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        output = tmp_path / "insights.jsonl"
        stdin = json.dumps(
            {
                "hook_event_name": "Stop",
                "transcript_path": str(transcript),
                "reason": "end_of_turn",
            }
        )

        rc = run_hook(stdin_text=stdin, output_path=output)
        assert rc == 0

        lines = output.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["insight_text"] == "這是一個洞察"
        assert record["session_id"] == "sess-1"
        assert record["project"] == tmp_path.name

    def test_agents_st_041_no_insight_no_output(self, tmp_path: Path) -> None:
        """AGENTS-ST-041：transcript 無 ★ Insight 時不產生 output 檔。"""
        transcript = tmp_path / "transcript.jsonl"
        assistant_entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "no insight"}]},
        }
        transcript.write_text(
            json.dumps({"type": "user", "sessionId": "s", "cwd": str(tmp_path)})
            + "\n"
            + json.dumps(assistant_entry)
            + "\n",
            encoding="utf-8",
        )

        output = tmp_path / "insights.jsonl"
        stdin = json.dumps({"hook_event_name": "Stop", "transcript_path": str(transcript)})

        rc = run_hook(stdin_text=stdin, output_path=output)
        assert rc == 0
        assert not output.exists()

    def test_agents_eg_030_wrong_event_type_skipped(self, tmp_path: Path) -> None:
        """AGENTS-EG-030：非 Stop 事件直接 return，不做任何事。"""
        output = tmp_path / "insights.jsonl"
        rc = run_hook(
            stdin_text=json.dumps({"hook_event_name": "UserPromptSubmit"}),
            output_path=output,
        )
        assert rc == 0
        assert not output.exists()

    def test_agents_eg_031_invalid_stdin_swallowed(self, tmp_path: Path) -> None:
        """AGENTS-EG-031：無法解析的 stdin 不拋例外，回傳 0。"""
        output = tmp_path / "insights.jsonl"
        rc = run_hook(stdin_text="not-json", output_path=output)
        assert rc == 0
        assert not output.exists()

    def test_agents_eg_032_stdin_oserror_returns_zero(self, tmp_path: Path) -> None:
        """AGENTS-EG-032：stdin OSError（broken pipe 等）靜默回傳 0，不拋例外。"""
        output = tmp_path / "insights.jsonl"
        with patch("tasks.mycelium.insight_hook.sys") as mock_sys:
            mock_sys.stdin.read.side_effect = OSError("broken pipe")
            rc = run_hook(stdin_text=None, output_path=output)
        assert rc == 0
        assert not output.exists()

    def test_agents_st_042_insight_encodes_home_working_dir(self, tmp_path: Path) -> None:
        """AGENTS-ST-042：run_hook 寫入的 working_dir 對 $HOME 內路徑做 tilde-encode。"""
        fake_cwd = str(Path.home() / "Workspace" / "my-proj")
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "sess-encode",
                    "cwd": fake_cwd,
                    "gitBranch": "main",
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": "`★ Insight ─────`\nportable test\n`─────`",
                            }
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        output = tmp_path / "insights.jsonl"
        stdin = json.dumps(
            {"hook_event_name": "Stop", "transcript_path": str(transcript), "reason": "end_of_turn"}
        )
        run_hook(stdin_text=stdin, output_path=output)
        record = json.loads(output.read_text(encoding="utf-8").strip())
        assert record["working_dir"] == "~/Workspace/my-proj"
