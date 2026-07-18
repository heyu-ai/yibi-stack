"""測試 CLI 指令：account link-claude、hook 安裝的 worktree 守門。"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from tasks.mycelium.cli import cli

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """執行 setup 用的 git 指令；**失敗即 raise**（理由見 tasks/tests/test_worktree_guard.py）。"""
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=True
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
    """建立 linked worktree，並斷言 git 真的把它登記成 worktree。"""
    repo = _make_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(wt)])
    listed = _run(["git", "-C", str(repo), "worktree", "list", "--porcelain"]).stdout
    assert f"worktree {wt.resolve()}" in listed, f"fixture 未建出 linked worktree：{listed}"
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


class TestInstalledHookCli:
    def test_installed_hook_group_appears_in_help(self) -> None:
        """MYCLI-ST-005：root help 與 hooks help 都列出已註冊的 commands。"""
        runner = CliRunner()

        root_help = runner.invoke(cli, ["--help"])
        hooks_help = runner.invoke(cli, ["hooks", "--help"])

        assert root_help.exit_code == 0
        assert "hooks" in root_help.output
        assert hooks_help.exit_code == 0
        assert "pre-compact" in hooks_help.output
        assert "session-start" in hooks_help.output

    def test_installed_hook_pre_compact_preserves_observable_behavior(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCLI-ST-005：PreCompact 第一次攔截、第二次放行，並記錄 matcher。"""
        from tasks.mycelium import auto_handover_hooks

        events: list[tuple[object, dict[str, object]]] = []

        def fake_log_event(event_type: object, **kwargs: object) -> None:
            events.append((event_type, kwargs))

        monkeypatch.setattr(auto_handover_hooks, "_STATE_DIR", tmp_path)
        monkeypatch.setattr("tasks.mycelium.metrics_service.log_event", fake_log_event)
        payload = json.dumps(
            {"hook_event_name": "PreCompact", "session_id": "session-005", "matcher": "auto"}
        )
        runner = CliRunner()

        first = runner.invoke(cli, ["hooks", "pre-compact"], input=payload)
        second = runner.invoke(cli, ["hooks", "pre-compact"], input=payload)

        assert first.exit_code == 2
        assert "/handover" in json.loads(first.output)["systemMessage"]
        assert second.exit_code == 0
        assert second.output == ""
        assert [event[0] for event in events] == ["layer2_intercept", "layer2_passthrough"]
        assert all(event[1]["session_id"] == "session-005" for event in events)
        assert all(event[1]["matcher"] == "auto" for event in events)

    def test_installed_hook_session_start_preserves_observable_behavior(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MYCLI-ST-006：compact SessionStart 提示恢復，其他 matcher 靜默略過。"""
        events: list[tuple[object, dict[str, object]]] = []

        def fake_log_event(event_type: object, **kwargs: object) -> None:
            events.append((event_type, kwargs))

        home = tmp_path / "home"
        handover_db = home / ".agents" / "handover" / "handover.db"
        handover_db.parent.mkdir(parents=True)
        handover_db.touch()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr("tasks.mycelium.metrics_service.log_event", fake_log_event)
        runner = CliRunner()

        supported = runner.invoke(
            cli,
            ["hooks", "session-start"],
            input=json.dumps(
                {"hook_event_name": "SessionStart", "matcher_type": "compact", "session_id": "s6"}
            ),
        )
        ignored = runner.invoke(
            cli,
            ["hooks", "session-start"],
            input=json.dumps({"hook_event_name": "SessionStart", "matcher": "startup"}),
        )

        assert supported.exit_code == 0
        assert "/handover-back" in json.loads(supported.output)["systemMessage"]
        assert ignored.exit_code == 0
        assert ignored.output == ""
        assert [event[0] for event in events] == ["layer3_session_start"]
        assert events[0][1]["session_id"] == "s6"
        assert events[0][1]["matcher"] == "compact"


_HOOK_WRAPPERS = [
    ("pre-compact-handover.sh", "pre-compact", 2),
    ("post-compact-handover-back.sh", "session-start", 0),
]


class TestHookWrappers:
    @pytest.mark.parametrize(("script_name", "subcommand", "exit_code"), _HOOK_WRAPPERS)
    def test_mycli_st_006_hook_wrapper_delegates_to_runtime_binary(
        self,
        script_name: str,
        subcommand: str,
        exit_code: int,
        tmp_path: Path,
    ) -> None:
        """MYCLI-ST-006：wrapper 保留 stdin/stdout/status，並使用 command -v 的絕對路徑。"""
        bin_dir = tmp_path / "mycelium runtime" / "bin dir"
        bin_dir.mkdir(parents=True)
        binary = bin_dir / "mycelium"
        binary.write_text(
            """#!/bin/bash
printf '%s\n' "$0" "$@" > "$HOOK_CAPTURE"
cat > "$HOOK_STDIN_CAPTURE"
printf '%s' "$HOOK_OUTPUT"
exit "$HOOK_EXIT"
""",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        capture = tmp_path / "argv.txt"
        stdin_capture = tmp_path / "stdin.json"
        payload = json.dumps({"hook_event_name": "Supported", "session_id": "wrapper-006"})
        output = json.dumps({"systemMessage": "delegated"})
        env = os.environ.copy()
        env.update(
            {
                "PATH": os.pathsep.join((str(bin_dir), "/usr/bin", "/bin")),
                "HOOK_CAPTURE": str(capture),
                "HOOK_STDIN_CAPTURE": str(stdin_capture),
                "HOOK_OUTPUT": output,
                "HOOK_EXIT": str(exit_code),
            }
        )
        wrapper = _REPO_ROOT / ".claude" / "hooks" / script_name

        result = subprocess.run(  # nosec B603
            [str(wrapper)], input=payload, capture_output=True, text=True, env=env, timeout=30
        )

        assert result.returncode == exit_code
        assert result.stdout == output
        assert result.stderr == ""
        assert capture.read_text(encoding="utf-8").splitlines() == [
            str(binary.resolve()),
            "hooks",
            subcommand,
        ]
        assert stdin_capture.read_text(encoding="utf-8") == payload

    @pytest.mark.parametrize(("script_name", "subcommand", "exit_code"), _HOOK_WRAPPERS)
    def test_mycli_st_006_hook_wrapper_missing_binary_fails_loud(
        self,
        script_name: str,
        subcommand: str,
        exit_code: int,
        tmp_path: Path,
    ) -> None:
        """MYCLI-ST-006：PATH 無 mycelium 時 wrapper 印 [FAIL] 並非零退出。"""
        del subcommand, exit_code
        empty_bin = tmp_path / "empty bin"
        empty_bin.mkdir()
        env = os.environ.copy()
        env["PATH"] = str(empty_bin)
        wrapper = _REPO_ROOT / ".claude" / "hooks" / script_name

        result = subprocess.run(  # nosec B603
            [str(wrapper)], input="{}", capture_output=True, text=True, env=env, timeout=30
        )

        assert result.returncode != 0
        assert "[FAIL]" in result.stderr

    @pytest.mark.parametrize(("script_name", "subcommand", "exit_code"), _HOOK_WRAPPERS)
    def test_mycli_st_006_hook_wrapper_source_has_no_checkout_invocation(
        self, script_name: str, subcommand: str, exit_code: int
    ) -> None:
        """MYCLI-ST-006：wrapper source 不含 checkout import、uvx 或 uv run。"""
        del subcommand, exit_code
        source = (_REPO_ROOT / ".claude" / "hooks" / script_name).read_text(encoding="utf-8")
        for forbidden in ("tasks.mycelium", "uvx", "uv run"):
            assert forbidden not in source


# hook 安裝指令，全部會把自我定位的 repo 路徑寫進 ~/.claude/settings.json。
# insight / recap 的 install-hook **沒有對應的 make target**，故 Python 層的 guard
# 是它們唯一的防線（handover install-hooks 另有 Makefile 層的 guard 形成雙層防護）。
#
# 第二欄是該指令應該傳給 guard 的復原指令——[FAIL] 訊息會原樣印出它。必須逐一釘住：
# 三個 call site 是互相複製出來的（recap 的註解字面上就是「同 insight install-hook」），
# 只驗 exit code 的話，recap 傳成 insight 的字串仍會全綠，而使用者拿到一條指向錯誤指令
# 的建議（由 mob review 的 pr-test-analyzer 指出）。
_HOOK_INSTALL_COMMANDS = [
    (["handover", "install-hooks"], "uv run python -m tasks.mycelium handover install-hooks"),
    (["insight", "install-hook"], "uv run python -m tasks.mycelium insight install-hook"),
    (["recap", "install-hook"], "uv run python -m tasks.mycelium recap install-hook"),
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

    @pytest.mark.parametrize(("args", "expected_command"), _HOOK_INSTALL_COMMANDS)
    def test_mycwg_dt_001_hook_install_in_worktree_blocked(
        self,
        args: list[str],
        expected_command: str,
        tmp_path: Path,
        home_settings: Path,
        monkeypatch: pytest.MonkeyPatch,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        """MYCWG-DT-001: worktree 內安裝 hook -> exit 1、settings.json 未建立、且訊息指名自己。

        第三個斷言不是裝飾：三個 call site 互相複製而來，傳錯字串時前兩個斷言仍會全綠。
        guard 寫的是真實 stderr（subprocess 繼承 fd），不是 CliRunner 的 buffer，故用
        capfd 而非 result.output。
        """
        monkeypatch.setattr("tasks._worktree_guard.PROJECT_ROOT", _make_worktree(tmp_path))
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 1
        assert not home_settings.exists(), f"{args} 的 guard 沒擋住，settings.json 已被寫出"
        assert expected_command in capfd.readouterr().err, (
            f"{args} 傳給 guard 的復原指令不是自己，使用者會拿到指向錯誤指令的建議"
        )

    @pytest.mark.parametrize(("args", "expected_command"), _HOOK_INSTALL_COMMANDS)
    def test_mycwg_dt_002_hook_install_in_main_repo_passes(
        self,
        args: list[str],
        expected_command: str,
        tmp_path: Path,
        home_settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MYCWG-DT-002: 主 repo 內安裝 hook -> 正常寫入（guard 不得誤擋）。

        與 DT-001 成對：只證明「擋得住」不夠，一個永遠回傳失敗的 guard 也能讓 DT-001
        全綠。這條釘住 guard 的另一半契約。
        """
        monkeypatch.setattr("tasks._worktree_guard.PROJECT_ROOT", _make_repo(tmp_path / "main"))
        bin_dir = tmp_path / "installed tools" / "bin dir"
        bin_dir.mkdir(parents=True)
        binary = bin_dir / "mycelium"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        current_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", os.pathsep.join((str(bin_dir), current_path)))
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0
        assert home_settings.exists(), f"{args} 在主 repo 被誤擋，settings.json 未寫出"

    def test_mycli_st_005_handover_install_hooks_missing_binary_fails_loud(
        self,
        tmp_path: Path,
        home_settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MYCLI-ST-005：CLI 將 missing-binary failure 轉為 exit 1，且不寫 settings。"""
        monkeypatch.setattr("tasks._worktree_guard.PROJECT_ROOT", _make_repo(tmp_path / "main"))
        empty_bin = tmp_path / "empty bin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))

        result = CliRunner().invoke(cli, ["handover", "install-hooks"])

        assert result.exit_code == 1
        assert "[FAIL]" in result.output
        assert not home_settings.exists()
