"""測試 CLI 指令：account link-claude。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


class TestTokenUsageReportCli:
    def test_tuc_dt_001_computed_exits_zero(self, tmp_path: Path, monkeypatch) -> None:
        """TUC-DT-001：status=computed 時 exit code 0，輸出含成本估算。"""
        from tasks.mycelium.token_usage_service import TokenUsageReport

        report = TokenUsageReport(
            status="computed",
            total_input_tokens=1000,
            total_output_tokens=200,
            total_cost_usd=0.05,
            by_model=[
                {
                    "model": "claude-sonnet-5",
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cost_usd": 0.05,
                    "priced": True,
                }
            ],
        )
        monkeypatch.setattr(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            lambda *a, **k: report,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["token-usage", "report", "--workdir", str(tmp_path)])
        assert result.exit_code == 0
        assert "estimated_cost_usd" in result.output

    def test_tuc_dt_002_unavailable_exits_two(self, tmp_path: Path, monkeypatch) -> None:
        """TUC-DT-002：status=unavailable 時 exit code 2，輸出 [WARN]。"""
        from tasks.mycelium.token_usage_service import TokenUsageReport

        report = TokenUsageReport(status="unavailable", warning="找不到 transcript")
        monkeypatch.setattr(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            lambda *a, **k: report,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["token-usage", "report", "--workdir", str(tmp_path)])
        assert result.exit_code == 2
        assert "[WARN]" in result.output

    def test_tuc_dt_003_ambiguous_exits_three(self, tmp_path: Path, monkeypatch) -> None:
        """TUC-DT-003：status=ambiguous 時 exit code 3。"""
        from tasks.mycelium.token_usage_service import TokenUsageReport

        report = TokenUsageReport(status="ambiguous", warning="偵測到並行 session")
        monkeypatch.setattr(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            lambda *a, **k: report,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["token-usage", "report", "--workdir", str(tmp_path)])
        assert result.exit_code == 3

    def test_tuc_st_001_json_flag_outputs_valid_json(self, tmp_path: Path, monkeypatch) -> None:
        """TUC-ST-001：--json 輸出合法 JSON，欄位與 report 一致。"""
        from tasks.mycelium.token_usage_service import TokenUsageReport

        report = TokenUsageReport(status="computed", total_input_tokens=42)
        monkeypatch.setattr(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            lambda *a, **k: report,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["token-usage", "report", "--workdir", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_input_tokens"] == 42


def _make_fake_write_handover(captured: dict[str, object]):
    """建立一個記錄 kwargs 並回傳假 record 的 write_handover 替身。"""

    def _fake_write_handover(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            id="fake-id",
            topic=kwargs.get("topic"),
            session_type=kwargs.get("session_type"),
            device="fake-device",
            subscription_account="fake-account",
            project="fake-project",
        )

    return _fake_write_handover


class TestHandoverWriteAutoTokensCli:
    def test_hwc_st_001_auto_tokens_flag_passed_through(self, tmp_path: Path, monkeypatch) -> None:
        """HWC-ST-001：--auto-tokens 會傳入 write_handover(auto_token_usage=True)。"""
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "tasks.mycelium.handover_service.write_handover",
            _make_fake_write_handover(captured),
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "handover",
                "write",
                "--session-type",
                "discussion",
                "--topic",
                "t",
                "--summary",
                "s",
                "--auto-tokens",
            ],
        )
        assert result.exit_code == 0
        assert captured.get("auto_token_usage") is True

    def test_hwc_st_002_without_flag_defaults_false(self, tmp_path: Path, monkeypatch) -> None:
        """HWC-ST-002：未帶 --auto-tokens 時 auto_token_usage 預設 False。"""
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "tasks.mycelium.handover_service.write_handover",
            _make_fake_write_handover(captured),
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "handover",
                "write",
                "--session-type",
                "discussion",
                "--topic",
                "t",
                "--summary",
                "s",
            ],
        )
        assert result.exit_code == 0
        assert captured.get("auto_token_usage") is False
