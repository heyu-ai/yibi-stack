"""NIGHTLY-config tests：首次執行自動偵測並落地 github_repo，避免每次都回傳空字串。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tasks.nightly_agent.config import load_config

CONFIG = "tasks.nightly_agent.config"


class TestLoadConfig:
    @patch(f"{CONFIG}._detect_github_repo", return_value="owner/repo")
    def test_missing_file_persists_detected_github_repo(
        self, _mock_detect: object, tmp_path: Path
    ) -> None:
        """NIGHTLY-EG-001: 設定檔不存在時自動偵測 origin remote 並落地，避免每次都用空 default。"""
        config_path = tmp_path / "nightly_agent.json"
        assert not config_path.exists()

        config = load_config(config_path)

        assert config.github_repo == "owner/repo"
        assert config_path.exists(), "首次執行應把偵測結果落地成設定檔"
        persisted = json.loads(config_path.read_text(encoding="utf-8"))
        assert persisted["github_repo"] == "owner/repo"

    @patch(f"{CONFIG}._detect_github_repo", return_value="")
    def test_missing_file_with_no_remote_still_persists_file(
        self, _mock_detect: object, tmp_path: Path
    ) -> None:
        """NIGHTLY-EG-002: 偵測不到 origin remote 時，仍落地空 github_repo 設定檔（不拋錯）。"""
        config_path = tmp_path / "nightly_agent.json"

        config = load_config(config_path)

        assert config.github_repo == ""
        assert config_path.exists()

    def test_existing_file_is_not_overwritten(self, tmp_path: Path) -> None:
        """NIGHTLY-EG-003: 設定檔已存在時直接讀取，不重新偵測或覆寫既有內容。"""
        config_path = tmp_path / "nightly_agent.json"
        config_path.write_text(
            json.dumps({"version": "1.0", "github_repo": "existing/repo"}), encoding="utf-8"
        )

        with patch(f"{CONFIG}._detect_github_repo") as mock_detect:
            config = load_config(config_path)
            mock_detect.assert_not_called()

        assert config.github_repo == "existing/repo"
