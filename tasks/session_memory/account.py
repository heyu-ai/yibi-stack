"""帳號、裝置、專案偵測：四層 fallback（env var → adapter → config.json → 預設值）。"""

from __future__ import annotations

import contextlib
import os
import subprocess  # nosec B404 — git 指令需要 subprocess
import sys
from pathlib import Path

from .adapters import get_adapter
from .config import load_agents_config
from .registry import AccountRegistry

_UNKNOWN_ACCOUNT = "unknown"
_ENV_KEY_ACCOUNT = "AGENT_ACCOUNT"
_ENV_KEY_AGENT = "AGENT_TYPE"


def detect_account(agent_type: str = "claude", warn: bool = True) -> str:
    """四層 fallback：

    1. 環境變數 `AGENT_ACCOUNT`（特定 session override）
    2. Agent-specific adapter（Gemini/Codex/Claude 自動偵測）
    3. `~/.agents/config.json` 的 `default_account`
    4. 回傳 "unknown" 並印 warning 到 stderr
    """
    # 層 1：env var
    if v := os.environ.get(_ENV_KEY_ACCOUNT):
        return v.strip() or _UNKNOWN_ACCOUNT

    # 層 2：adapter 偵測
    adapter = get_adapter(agent_type)
    if adapter:
        email = adapter.detect()
        if email:
            with contextlib.suppress(Exception):  # nosec B110 — auto_register 失敗不影響主流程
                AccountRegistry().auto_register(email, agent_type)
            return email

    # 層 3：config.json default_account
    config = load_agents_config()
    if config and config.default_account:
        return config.default_account

    # 層 4：unknown
    if warn:
        print(
            "[agents] AGENT_ACCOUNT 未設定、adapter 無法偵測、"
            "config.json 無 default_account，記錄為 unknown。"
            "\n  設定方式：export AGENT_ACCOUNT=<your-account>"
            "\n  或執行：uv run python -m tasks.session_memory account link-claude",
            file=sys.stderr,
        )
    return _UNKNOWN_ACCOUNT


def detect_agent_type(caller: str | None = None, default: str = "claude") -> str:
    """偵測當前 agent 類型：env var → caller → config.default_agent → default 參數。"""
    if v := os.environ.get(_ENV_KEY_AGENT):
        stripped = v.strip()
        if stripped:
            return stripped
    if caller:
        return caller
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
    """以工作目錄 basename 作為 project 名稱。路徑無效時回傳 'unknown-project'。"""
    import warnings

    path = Path(cwd) if cwd else Path.cwd()
    name = path.resolve().name
    if not name:
        warnings.warn(
            f"detect_project：無法從路徑取得 basename（path={path}），回傳 'unknown-project'",
            stacklevel=2,
        )
        return "unknown-project"
    return name


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
