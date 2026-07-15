"""測試 CLI 指令：account link-claude、hook 安裝的 worktree 守門。"""

from __future__ import annotations

import json
import subprocess  # nosec B404
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from tasks.mycelium.cli import cli


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=False
    )


def _make_repo(root: Path) -> Path:
    """建立一個有 initial commit 的 git repo。

    不用 `git init -b`（2.28+）；理由見 .claude/rules/09-test-conventions.md。
    """
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", str(root)])
    _run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"])
    _run(["git", "-C", str(root), "config", "user.email", "test@example.com"])
    _run(["git", "-C", str(root), "config", "user.name", "test"])
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _run(["git", "-C", str(root), "add", "README.md"])
    _run(["git", "-C", str(root), "commit", "-qm", "init"])
    return root


def _make_worktree(tmp_path: Path) -> Path:
    repo = _make_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)])
    return wt


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


def _make_fake_write_retrospective(captured: dict[str, object]):
    """建立一個記錄 kwargs 並回傳假 record 的 write_retrospective 替身。"""

    def _fake_write_retrospective(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            id="fake-id",
            pr_number=kwargs.get("pr_number"),
            topic=kwargs.get("topic"),
            device="fake-device",
            subscription_account="fake-account",
            project="fake-project",
        )

    return _fake_write_retrospective


class TestRetroWriteCli:
    def test_rwc_st_001_auto_tokens_flag_passed_through(self, tmp_path: Path, monkeypatch) -> None:
        """RWC-ST-001：--auto-tokens 會傳入 write_retrospective(auto_token_usage=True)。"""
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "tasks.mycelium.retrospective_service.write_retrospective",
            _make_fake_write_retrospective(captured),
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "retro",
                "write",
                "--pr-number",
                "205",
                "--topic",
                "t",
                "--summary",
                "s",
                "--auto-tokens",
            ],
        )
        assert result.exit_code == 0
        assert captured.get("auto_token_usage") is True
        assert captured.get("pr_number") == 205

    def test_rwc_st_002_without_flag_defaults_false(self, tmp_path: Path, monkeypatch) -> None:
        """RWC-ST-002：未帶 --auto-tokens 時 auto_token_usage 預設 False。"""
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "tasks.mycelium.retrospective_service.write_retrospective",
            _make_fake_write_retrospective(captured),
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "retro",
                "write",
                "--pr-number",
                "205",
                "--topic",
                "t",
                "--summary",
                "s",
            ],
        )
        assert result.exit_code == 0
        assert captured.get("auto_token_usage") is False


class TestRetroReadSearchCli:
    def test_rrc_st_001_read_json_flag(self, tmp_path: Path, monkeypatch) -> None:
        """RRC-ST-001：retro read --json 輸出 read_recent_retrospectives 的結果。"""
        monkeypatch.setattr(
            "tasks.mycelium.retrospective_service.read_recent_retrospectives",
            lambda *a, **k: [{"id": "r1", "pr_number": 205}],
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["retro", "read", "--last", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == [{"id": "r1", "pr_number": 205}]

    def test_rsc_st_001_search_pr_number_passthrough(self, tmp_path: Path, monkeypatch) -> None:
        """RSC-ST-001：retro search --pr-number 正確傳給 search_retrospectives。"""
        captured: dict[str, object] = {}

        def _fake_search(*args: object, **kwargs: object) -> list[dict[str, object]]:
            captured.update(kwargs)
            return []

        monkeypatch.setattr(
            "tasks.mycelium.retrospective_service.search_retrospectives", _fake_search
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["retro", "search", "--pr-number", "205"])
        assert result.exit_code == 0
        assert captured.get("pr_number") == 205


class TestRetroMigrateCli:
    def test_rmc_st_001_reports_counts(self, tmp_path: Path, monkeypatch) -> None:
        """RMC-ST-001：retro migrate-from-handovers 印出 migrate.py 回傳的統計。"""
        monkeypatch.setattr(
            "tasks.mycelium.migrate.migrate_retrospectives_from_handovers",
            lambda *a, **k: (3, 1),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["retro", "migrate-from-handovers"])
        assert result.exit_code == 0
        assert "3" in result.output
        assert "1" in result.output


# hook 安裝指令，全部會把自我定位的 repo 路徑寫進 ~/.claude/settings.json。
# insight / recap 的 install-hook **沒有對應的 make target**，故 Python 層的 guard
# 是它們唯一的防線（handover install-hooks 另有 Makefile 層的 guard 形成雙層防護）。
_HOOK_INSTALL_COMMANDS = [
    ["handover", "install-hooks"],
    ["insight", "install-hook"],
    ["recap", "install-hook"],
]


class TestHookInstallWorktreeGuard:
    """MYCWG-DT-*: hook 安裝在 worktree 內必須擋下且不動 settings.json（issue #237）。"""

    @pytest.fixture
    def home_settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """把 HOME 導到 tmp，讓 settings.json 的預設路徑落在拋棄式目錄。

        安裝函式內部是 `settings_path or (Path.home() / ".claude" / "settings.json")`，
        而 CLI 從不傳 settings_path —— 正是預設那條（真實機器層級）路徑。改 HOME 才能
        測到 CLI 真正會走的分支；也讓突變驗證是安全的：拿掉 guard 時寫進 tmp，
        不會污染使用者真正的 ~/.claude/settings.json。
        """
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        return home / ".claude" / "settings.json"

    @pytest.mark.parametrize("args", _HOOK_INSTALL_COMMANDS)
    def test_mycwg_dt_001_hook_install_in_worktree_blocked(
        self, args: list[str], tmp_path: Path, home_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCWG-DT-001: worktree 內安裝 hook -> exit 1 且 settings.json 未被建立。"""
        monkeypatch.setattr("tasks._worktree_guard.PROJECT_ROOT", _make_worktree(tmp_path))
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 1
        assert not home_settings.exists(), f"{args} 的 guard 沒擋住，settings.json 已被寫出"

    @pytest.mark.parametrize("args", _HOOK_INSTALL_COMMANDS)
    def test_mycwg_dt_002_hook_install_in_main_repo_passes(
        self, args: list[str], tmp_path: Path, home_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCWG-DT-002: 主 repo 內安裝 hook -> 正常寫入（guard 不得誤擋）。

        與 DT-001 成對：只證明「擋得住」不夠，一個永遠回傳失敗的 guard 也能讓 DT-001
        全綠。這條釘住 guard 的另一半契約。
        """
        monkeypatch.setattr("tasks._worktree_guard.PROJECT_ROOT", _make_repo(tmp_path / "main"))
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0
        assert home_settings.exists(), f"{args} 在主 repo 被誤擋，settings.json 未寫出"
