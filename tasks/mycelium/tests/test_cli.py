"""測試 CLI 指令：account link-claude。"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tasks.mycelium.cli import cli


class TestLinkClaude:
    def test_link_claude_creates_registry_entry(self, tmp_path: Path) -> None:
        """LCLI-DT-001：正常流程：輸入 email 後寫入 accounts.json。"""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"userID": "testhash123"}), encoding="utf-8")
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["account", "link-claude"],
            input="howie@gmail.com\n",
            obj={"claude_json_path": claude_json, "accounts_path": accounts_path},
        )
        assert result.exit_code == 0
        data = json.loads(accounts_path.read_text())
        assert len(data) == 1
        assert data[0]["email"] == "howie@gmail.com"
        assert data[0]["hash"] == "testhash123"

    def test_link_claude_missing_claude_json_exits_1(self, tmp_path: Path) -> None:
        """LCLI-EG-001：.claude.json 不存在時 exit code 1。"""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["account", "link-claude"],
            obj={
                "claude_json_path": tmp_path / "nonexistent.json",
                "accounts_path": tmp_path / "accounts.json",
            },
        )
        assert result.exit_code == 1
