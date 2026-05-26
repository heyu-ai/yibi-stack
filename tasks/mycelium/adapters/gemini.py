"""Gemini CLI 帳號偵測：讀取 ~/.gemini/google_accounts.json。"""

from __future__ import annotations

import json
from pathlib import Path

from .base import AccountAdapter

_DEFAULT_PATH = Path.home() / ".gemini" / "google_accounts.json"


class GeminiAccountAdapter(AccountAdapter):
    """讀取 Gemini CLI 的 google_accounts.json 取得 active 帳號 email。"""

    agent_type = "gemini"

    def __init__(self, accounts_path: Path | None = None) -> None:
        self._path = accounts_path or _DEFAULT_PATH

    def detect(self) -> str | None:
        """回傳 active email，任何失敗靜默回傳 None。"""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            active = data.get("active", "")
            return active.strip() or None
        except Exception:  # noqa: BLE001
            return None
