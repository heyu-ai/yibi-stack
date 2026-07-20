"""夜間 Agent 設定載入。"""

from __future__ import annotations

import json
import re
import sys
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
        return NightlyAgentConfig(github_repo=_detect_github_repo())
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise RuntimeError(f"無法讀取設定檔：{config_path}") from e
    config = NightlyAgentConfig.model_validate(data)
    if not config.github_repo:
        config.github_repo = _detect_github_repo()
    return config


def save_config(config: NightlyAgentConfig, path: Path | None = None) -> None:
    """儲存設定檔。"""
    config_path = path or get_default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _detect_github_repo() -> str:
    """嘗試從 git remote 取得 owner/repo 字串。"""
    import subprocess  # nosec B404

    try:
        common_dir = subprocess.run(  # nosec B603 B607
            [
                "git",
                "-C",
                str(PROJECT_ROOT),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        repo_root = (
            Path(common_dir.stdout.strip()).parent if common_dir.returncode == 0 else PROJECT_ROOT
        )
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            print("[WARN] 無法從 git origin 偵測 GitHub repo", file=sys.stderr)
            return ""
        url = result.stdout.strip()
        # Normalize: git@github.com:owner/repo.git → owner/repo
        if url.startswith("git@github.com:"):
            url = url.replace("git@github.com:", "").removesuffix(".git")
        elif "github.com/" in url:
            url = url.split("github.com/")[-1].removesuffix(".git")
        if re.fullmatch(r"[^/\s]+/[^/\s]+", url):
            return url
        print("[WARN] git origin 不是可辨識的 GitHub owner/repo", file=sys.stderr)
        return ""
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[WARN] 偵測 GitHub repo 失敗：{e}", file=sys.stderr)
        return ""


def generate_default_config(path: Path | None = None) -> Path:
    """產生預設設定檔並回傳路徑。"""
    config = NightlyAgentConfig(github_repo=_detect_github_repo())
    config_path = path or get_default_config_path()
    save_config(config, config_path)
    return config_path
