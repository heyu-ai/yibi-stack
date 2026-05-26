"""測試帳號偵測 fallback 邏輯。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from tasks.mycelium.account import detect_account, detect_agent_type, detect_project
from tasks.mycelium.models import AgentsConfig


def _write_config(path: Path, **overrides: object) -> Path:
    """寫一份測試用 ~/.agents/config.json。"""
    defaults = {"device_id": "test-device", "default_account": None, "default_agent": "claude"}
    merged = {**defaults, **overrides}
    config = AgentsConfig.model_validate(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return path


class TestDetectAccount:
    """AGENTS-DT-001..003：帳號偵測基礎 fallback 決策表（env var / config / unknown）。

    adapter 層見 TestDetectAccountWithAdapter。
    """

    def test_agents_dt_001_env_var_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AGENTS-DT-001：env var 最優先，即使 config.json 有 default_account 也被蓋過。"""
        _write_config(tmp_path / "config.json", default_account="from-config")
        monkeypatch.setenv("AGENT_ACCOUNT", "from-env")
        with patch("tasks.mycelium.account.load_agents_config", return_value=None):
            assert detect_account() == "from-env"

    def test_agents_dt_002_config_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-002：env 未設，讀 config.json 的 default_account。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        cfg = AgentsConfig(device_id="d", default_account="from-config")
        with (
            patch("tasks.mycelium.account.get_adapter", return_value=None),
            patch("tasks.mycelium.account.load_agents_config", return_value=cfg),
        ):
            assert detect_account(warn=False) == "from-config"

    def test_agents_dt_003_unknown_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-003：env 未設且無 config.json，回傳 unknown。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        with (
            patch("tasks.mycelium.account.get_adapter", return_value=None),
            patch("tasks.mycelium.account.load_agents_config", return_value=None),
        ):
            assert detect_account(warn=False) == "unknown"

    def test_agents_eg_001_empty_env_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-EG-001：env 設為空字串時應 fallback（避免『有設但是空字串』的 corner case）。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "   ")
        with (
            patch("tasks.mycelium.account.get_adapter", return_value=None),
            patch("tasks.mycelium.account.load_agents_config", return_value=None),
        ):
            assert detect_account(warn=False) == "unknown"


class TestDetectAgentType:
    def test_agents_dt_004_env_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-004：AGENT_TYPE env var 最優先。"""
        monkeypatch.setenv("AGENT_TYPE", "gemini")
        with patch("tasks.mycelium.account.load_agents_config", return_value=None):
            assert detect_agent_type() == "gemini"

    def test_agents_dt_005_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-005：無 env、無 config 時回傳預設 claude。"""
        monkeypatch.delenv("AGENT_TYPE", raising=False)
        with patch("tasks.mycelium.account.load_agents_config", return_value=None):
            assert detect_agent_type() == "claude"


class TestDetectProject:
    def test_agents_cv_001_git_repo_name(self, tmp_path: Path) -> None:
        """AGENTS-CV-001：git repo 時 project = 主 repo 名稱（非 cwd basename）。"""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ".git\n"
            result = detect_project(project_dir)
        assert result == "my-project"

    def test_agents_cv_002_worktree_returns_main_repo_name(self, tmp_path: Path) -> None:
        """AGENTS-CV-002：git worktree 下 project = 主 repo 名稱，而非 worktree 目錄名稱。"""
        main_repo = tmp_path / "ainization-skill"
        main_repo.mkdir()
        worktree_dir = tmp_path / "deploy-stage-for-testing"
        worktree_dir.mkdir()
        git_common = main_repo / ".git"
        git_common.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = f"{git_common}\n"
            result = detect_project(worktree_dir)
        assert result == "ainization-skill"

    def test_agents_cv_003_non_git_fallback_to_basename(self, tmp_path: Path) -> None:
        """AGENTS-CV-003：非 git repo 時 fallback 回 cwd basename。"""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            result = detect_project(project_dir)
        assert result == "my-project"


class TestDetectAccountWithAdapter:
    """AGENTS-DT-010..013：四層 fallback 決策表（含 adapter 層）。"""

    def test_agents_dt_010_env_var_overrides_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-010：env var 設定時，adapter 不被呼叫。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "from-env")
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = "from-adapter"
        with patch("tasks.mycelium.account.get_adapter", return_value=mock_adapter):
            result = detect_account(agent_type="gemini")
        assert result == "from-env"
        mock_adapter.detect.assert_not_called()

    def test_agents_dt_011_adapter_wins_over_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-011：env 未設，adapter 有值時，優先於 config.json。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = "from-adapter"
        cfg = AgentsConfig(device_id="d", default_account="from-config")
        with (
            patch("tasks.mycelium.account.get_adapter", return_value=mock_adapter),
            patch("tasks.mycelium.account.load_agents_config", return_value=cfg),
            patch("tasks.mycelium.account.AccountRegistry"),
        ):
            result = detect_account(agent_type="gemini", warn=False)
        assert result == "from-adapter"

    def test_agents_dt_012_config_fallback_when_adapter_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AGENTS-DT-012：env 未設，adapter 回傳 None，讀 config.json。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = None
        cfg = AgentsConfig(device_id="d", default_account="from-config")
        with (
            patch("tasks.mycelium.account.get_adapter", return_value=mock_adapter),
            patch("tasks.mycelium.account.load_agents_config", return_value=cfg),
        ):
            result = detect_account(agent_type="gemini", warn=False)
        assert result == "from-config"

    def test_agents_dt_013_unknown_when_all_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-013：全部失敗回傳 unknown。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = None
        with (
            patch("tasks.mycelium.account.get_adapter", return_value=mock_adapter),
            patch("tasks.mycelium.account.load_agents_config", return_value=None),
        ):
            result = detect_account(agent_type="gemini", warn=False)
        assert result == "unknown"


class TestDetectAgentTypeWithCaller:
    """AGENTS-DT-014..016：detect_agent_type caller 參數。"""

    def test_agents_dt_014_caller_used_as_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-014：caller 有值，env 未設時回傳 caller。"""
        monkeypatch.delenv("AGENT_TYPE", raising=False)
        with patch("tasks.mycelium.account.load_agents_config", return_value=None):
            assert detect_agent_type(caller="gemini") == "gemini"

    def test_agents_dt_015_env_overrides_caller(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTS-DT-015：env var 設定時優先於 caller。"""
        monkeypatch.setenv("AGENT_TYPE", "codex")
        with patch("tasks.mycelium.account.load_agents_config", return_value=None):
            assert detect_agent_type(caller="gemini") == "codex"

    def test_agents_dt_016_no_caller_falls_back_to_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AGENTS-DT-016：caller 未傳，config.json 有值時讀 config。"""
        monkeypatch.delenv("AGENT_TYPE", raising=False)
        cfg = AgentsConfig(device_id="d", default_agent="gemini")
        with patch("tasks.mycelium.account.load_agents_config", return_value=cfg):
            assert detect_agent_type() == "gemini"


class TestAgentsConfigSkillRepo:
    def test_agents_vl_010_absolute_path_accepted(self) -> None:
        """AGENTS-VL-010：skill_repo 為絕對路徑時正常建立。"""
        cfg = AgentsConfig(device_id="d", skill_repo="/Users/doxa/Workspace/ainization-skill")
        assert cfg.skill_repo == "/Users/doxa/Workspace/ainization-skill"

    def test_agents_vl_011_none_accepted(self) -> None:
        """AGENTS-VL-011：skill_repo=None 表示尚未設定，為合法值。"""
        cfg = AgentsConfig(device_id="d")
        assert cfg.skill_repo is None

    def test_agents_vl_012_relative_path_raises(self) -> None:
        """AGENTS-VL-012：skill_repo 為相對路徑時應 raise ValidationError。"""
        with pytest.raises(ValidationError):
            AgentsConfig(device_id="d", skill_repo="relative/path")

    def test_agents_vl_013_empty_string_raises(self) -> None:
        """AGENTS-VL-013：skill_repo="" 不合法（應傳 None 表示未設定，空字串無意義）。"""
        with pytest.raises(ValidationError):
            AgentsConfig(device_id="d", skill_repo="")


class TestAgentsConfigDeviceId:
    def test_agents_vl_020_non_empty_device_id_accepted(self) -> None:
        """AGENTS-VL-020：device_id 為非空字串時正常建立。"""
        cfg = AgentsConfig(device_id="my-macbook")
        assert cfg.device_id == "my-macbook"

    def test_agents_vl_021_empty_device_id_raises(self) -> None:
        """AGENTS-VL-021：device_id="" 應 raise ValidationError（用於 DB key，不可為空）。"""
        with pytest.raises(ValidationError):
            AgentsConfig(device_id="")

    def test_agents_vl_022_whitespace_only_device_id_raises(self) -> None:
        """AGENTS-VL-022：device_id 純空白字元應 raise ValidationError。"""
        with pytest.raises(ValidationError):
            AgentsConfig(device_id="   ")

    def test_agents_vl_023_device_id_stripped_on_construction(self) -> None:
        """AGENTS-VL-023：device_id 前後空白自動 strip，避免 DB key 含空白字元。"""
        cfg = AgentsConfig(device_id="  my-mac  ")
        assert cfg.device_id == "my-mac"

    def test_agents_vl_014_skill_repo_empty_string_raises_with_clear_message(self) -> None:
        """AGENTS-VL-014：skill_repo="" 應 raise ValidationError，訊息說明需傳 None 而非空字串。"""
        with pytest.raises(ValidationError, match="空字串"):
            AgentsConfig(device_id="d", skill_repo="")


class TestLoadAgentsConfigValidation:
    def test_agents_eg_040_load_config_invalid_field_raises_runtime_error(
        self, tmp_path: Path
    ) -> None:
        """AGENTS-EG-040：config.json 含不合法欄位時 load_agents_config 應 raise RuntimeError。"""
        from tasks.mycelium.config import load_agents_config

        p = tmp_path / "config.json"
        p.write_text('{"device_id": "d", "skill_repo": "relative/path"}', encoding="utf-8")
        with pytest.raises(RuntimeError, match="設定檔欄位不合法"):
            load_agents_config(p)
