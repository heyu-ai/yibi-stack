"""User-level toggle config 管理（~/.agents/bash-hygiene.json）。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import AuditConfig

_CONFIG_PATH = Path.home() / ".agents" / "bash-hygiene.json"


def load_config() -> AuditConfig:
    """載入 toggle config；檔案不存在時回傳預設值（audit_enabled=False）。"""
    if not _CONFIG_PATH.is_file():
        return AuditConfig()
    try:
        return AuditConfig.model_validate(json.loads(_CONFIG_PATH.read_text("utf-8")))
    except Exception:
        return AuditConfig()


def save_config(config: AuditConfig) -> None:
    """儲存 toggle config 至 ~/.agents/bash-hygiene.json。"""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def config_path() -> Path:
    return _CONFIG_PATH
