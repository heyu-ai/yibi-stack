"""測試帳號偵測三層 fallback。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tasks.session_memory.account import detect_account, detect_agent_type, detect_project
from tasks.session_memory.models import AgentsConfig


def _write_config(path: Path, **overrides: object) -> Path:
    """寫一份測試用 ~/.agents/config.json。"""
    defaults = {"device_id": "test-device", "default_account": None, "default_agent": "claude"}
    merged = {**defaults, **overrides}
    config = AgentsConfig.model_validate(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return path


class TestDetectAccount:
    """AGENTS-DT-001..003：帳號偵測三層 fallback 決策表。"""

    def test_agents_dt_001_env_var_wins(self, tmp_path: Path, monkeypatch) -> None:
        """AGENTS-DT-001：env var 最優先，即使 config.json 有 default_account 也被蓋過。"""
        _write_config(tmp_path / "config.json", default_account="from-config")
        monkeypatch.setenv("AGENT_ACCOUNT", "from-env")
        with patch("tasks.session_memory.account.load_agents_config", return_value=None):
            assert detect_account() == "from-env"

    def test_agents_dt_002_config_fallback(self, tmp_path: Path, monkeypatch) -> None:
        """AGENTS-DT-002：env 未設，讀 config.json 的 default_account。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        cfg = AgentsConfig(device_id="d", default_account="from-config")
        with patch("tasks.session_memory.account.load_agents_config", return_value=cfg):
            assert detect_account(warn=False) == "from-config"

    def test_agents_dt_003_unknown_fallback(self, monkeypatch) -> None:
        """AGENTS-DT-003：env 未設且無 config.json，回傳 unknown。"""
        monkeypatch.delenv("AGENT_ACCOUNT", raising=False)
        with patch("tasks.session_memory.account.load_agents_config", return_value=None):
            assert detect_account(warn=False) == "unknown"

    def test_agents_eg_001_empty_env_falls_back(self, monkeypatch) -> None:
        """AGENTS-EG-001：env 設為空字串時應 fallback（避免『有設但是空字串』的 corner case）。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "   ")
        with patch("tasks.session_memory.account.load_agents_config", return_value=None):
            assert detect_account(warn=False) == "unknown"


class TestDetectAgentType:
    def test_agents_dt_004_env_wins(self, monkeypatch) -> None:
        """AGENTS-DT-004：AGENT_TYPE env var 最優先。"""
        monkeypatch.setenv("AGENT_TYPE", "gemini")
        with patch("tasks.session_memory.account.load_agents_config", return_value=None):
            assert detect_agent_type() == "gemini"

    def test_agents_dt_005_default(self, monkeypatch) -> None:
        """AGENTS-DT-005：無 env、無 config 時回傳預設 claude。"""
        monkeypatch.delenv("AGENT_TYPE", raising=False)
        with patch("tasks.session_memory.account.load_agents_config", return_value=None):
            assert detect_agent_type() == "claude"


class TestDetectProject:
    def test_agents_cv_001_basename_from_cwd(self, tmp_path: Path) -> None:
        """AGENTS-CV-001：project = 工作目錄 basename。"""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        assert detect_project(project_dir) == "my-project"
