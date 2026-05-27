"""夜間 Agent 設定載入。"""

from __future__ import annotations

import json
from pathlib import Path

from tasks._paths import PROJECT_ROOT, RUNTIME_DIR

from .models import NightlyAgentConfig

_CONFIG_PATH = RUNTIME_DIR / "nightly_agent.json"


def get_default_config_path() -> Path:
    return _CONFIG_PATH


def load_config(path: Path | None = None) -> NightlyAgentConfig:
    """載入設定；檔案不存在時回傳預設值（首次執行免 setup）。"""
    config_path = path or get_default_config_path()
    if not config_path.exists():
        return NightlyAgentConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise RuntimeError(f"無法讀取設定檔：{config_path}") from e
    return NightlyAgentConfig.model_validate(data)


def save_config(config: NightlyAgentConfig, path: Path | None = None) -> None:
    """儲存設定檔。"""
    config_path = path or get_default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _detect_github_repo() -> str:
    """嘗試從 git remote 取得 owner/repo 字串。"""
    import subprocess  # nosec B404

    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(PROJECT_ROOT), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = result.stdout.strip()
        # Normalize: git@github.com:owner/repo.git → owner/repo
        if url.startswith("git@github.com:"):
            url = url.replace("git@github.com:", "").removesuffix(".git")
        elif "github.com/" in url:
            url = url.split("github.com/")[-1].removesuffix(".git")
        return url
    except Exception:
        return ""


def generate_default_config(path: Path | None = None) -> Path:
    """產生預設設定檔並回傳路徑。"""
    config = NightlyAgentConfig(github_repo=_detect_github_repo())
    config_path = path or get_default_config_path()
    save_config(config, config_path)
    return config_path
