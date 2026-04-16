"""帳號、裝置、專案偵測：三層 fallback（env var → config.json → 預設值）。"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — git 指令需要 subprocess
import sys
from pathlib import Path

from .config import load_agents_config

_UNKNOWN_ACCOUNT = "unknown"
_ENV_KEY_ACCOUNT = "AGENT_ACCOUNT"
_ENV_KEY_AGENT = "AGENT_TYPE"


def detect_account(warn: bool = True) -> str:
    """三層 fallback：

    1. 環境變數 `AGENT_ACCOUNT`（特定 session override）
    2. `~/.agents/config.json` 的 `default_account`
    3. 回傳 "unknown" 並印 warning 到 stderr
    """
    if v := os.environ.get(_ENV_KEY_ACCOUNT):
        return v.strip() or _UNKNOWN_ACCOUNT

    config = load_agents_config()
    if config and config.default_account:
        return config.default_account

    if warn:
        print(
            "[agents] AGENT_ACCOUNT 未設定、config.json 無 default_account，記錄為 unknown。"
            "\n  設定方式：export AGENT_ACCOUNT=<your-account>"
            "\n  或編輯 ~/.agents/config.json 的 default_account 欄位。",
            file=sys.stderr,
        )
    return _UNKNOWN_ACCOUNT


def detect_agent_type(default: str = "claude") -> str:
    """偵測當前 agent 類型：env var → config.default_agent → default 參數。"""
    if v := os.environ.get(_ENV_KEY_AGENT):
        return v.strip() or default
    config = load_agents_config()
    if config and config.default_agent:
        return config.default_agent
    return default


def detect_device() -> str:
    """回傳 config.json 的 device_id，未設定則用 hostname fallback。"""
    config = load_agents_config()
    if config and config.device_id:
        return config.device_id
    import socket

    try:
        return socket.gethostname() or "unknown-device"
    except OSError:
        return "unknown-device"


def detect_project(cwd: Path | str | None = None) -> str:
    """以工作目錄 basename 作為 project 名稱。"""
    path = Path(cwd) if cwd else Path.cwd()
    return path.resolve().name


def detect_branch(cwd: Path | str | None = None) -> str | None:
    """讀取當前 git branch；非 git repo 或失敗時回傳 None。"""
    path = Path(cwd) if cwd else Path.cwd()
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None
