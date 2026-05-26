"""Claude Code 帳號偵測：~/.claude/.claude.json userID hash → accounts.json 查表。"""

from __future__ import annotations

import json
from pathlib import Path

from ..registry import AccountRegistry
from .base import AccountAdapter

_DEFAULT_CLAUDE_JSON = Path.home() / ".claude" / ".claude.json"


class ClaudeAccountAdapter(AccountAdapter):
    """讀取 .claude.json 的 userID hash，查 accounts.json 對照表取 email。"""

    agent_type = "claude"

    def __init__(
        self,
        claude_json_path: Path | None = None,
        accounts_path: Path | None = None,
    ) -> None:
        self._claude_json = claude_json_path or _DEFAULT_CLAUDE_JSON
        self._registry = AccountRegistry(accounts_path=accounts_path)

    def detect(self) -> str | None:
        """回傳對照表中的 email，未命中或任何失敗靜默回傳 None。"""
        try:
            data = json.loads(self._claude_json.read_text(encoding="utf-8"))
            user_id = data.get("userID", "").strip()
            if not user_id:
                return None
            return self._registry.find_by_hash(user_id)
        except Exception:  # noqa: BLE001
            return None
