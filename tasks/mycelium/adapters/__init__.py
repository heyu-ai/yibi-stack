"""Adapter registry：依 agent_type 取對應的 AccountAdapter 實例。"""

from __future__ import annotations

from .base import AccountAdapter
from .claude import ClaudeAccountAdapter
from .codex import CodexAccountAdapter
from .gemini import GeminiAccountAdapter

_REGISTRY: dict[str, type[AccountAdapter]] = {
    "gemini": GeminiAccountAdapter,
    "codex": CodexAccountAdapter,
    "claude": ClaudeAccountAdapter,
}


def get_adapter(agent_type: str) -> AccountAdapter | None:
    """依 agent_type 回傳對應 adapter 實例。未知類型回傳 None。"""
    cls = _REGISTRY.get(agent_type)
    return cls() if cls else None
