"""Agents 設定檔管理：~/.agents/config.json 與相關路徑常數。"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from .models import AgentsConfig

# 統一根目錄 — 跨 repo 共用，不在 .runtime/ 下
AGENTS_HOME = Path.home() / ".agents"
AGENTS_CONFIG_PATH = AGENTS_HOME / "config.json"
HANDOVER_DIR = AGENTS_HOME / "handover"
HANDOVER_DB_PATH = HANDOVER_DIR / "handover.db"
HANDOVER_JSONL_PATH = HANDOVER_DIR / "handover.jsonl"
INSIGHT_DIR = AGENTS_HOME / "insight"
INSIGHTS_JSONL_PATH = INSIGHT_DIR / "insights.jsonl"
REGISTRY_DIR = AGENTS_HOME / "_registry"
INBOX_DIR = AGENTS_HOME / "inbox"
STIGNORE_PATH = AGENTS_HOME / ".stignore"


def load_agents_config(path: Path | None = None) -> AgentsConfig | None:
    """載入 ~/.agents/config.json；不存在時回傳 None（呼叫端自行決定 fallback）。"""
    config_path = path or AGENTS_CONFIG_PATH
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"設定檔格式錯誤：{config_path}") from e
    return AgentsConfig.model_validate(data)


def save_agents_config(config: AgentsConfig, path: Path | None = None) -> None:
    """將設定寫入 ~/.agents/config.json。"""
    config_path = path or AGENTS_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def generate_default_config() -> AgentsConfig:
    """用當前主機名產生預設設定。"""
    return AgentsConfig(
        device_id=_detect_hostname(),
        default_account=None,
        default_agent="claude",
    )


def _detect_hostname() -> str:
    """偵測主機名作為 device_id；失敗時 fallback 到 'unknown-device'。"""
    try:
        return socket.gethostname() or "unknown-device"
    except OSError:
        return "unknown-device"


def ensure_dirs(home: Path | None = None) -> None:
    """建立 ~/.agents/ 下所有必要目錄。"""
    root = home or AGENTS_HOME
    for subdir in (
        root / "handover",
        root / "insight",
        root / "_registry",
        root / "inbox",
    ):
        subdir.mkdir(parents=True, exist_ok=True)
