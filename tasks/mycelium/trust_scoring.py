"""Bot trust weight 計算。

compute_bot_trust_weight() 依照 spec mycelium-bot-trust-mcp 的四等級表計算：
  - user_stated (source="user-stated")：weight = 1.0（覆蓋所有其他等級）
  - same_bot (source_bot == querying agent)：weight = 0.9
  - trusted_other_bot (source_bot in trusted_bots)：weight = 0.7
  - unknown：weight = 0.4
"""

from __future__ import annotations

from typing import Any

# Trust tier weights
_WEIGHT_USER_STATED = 1.0
_WEIGHT_SAME_BOT = 0.9
_WEIGHT_TRUSTED_OTHER = 0.7
_WEIGHT_UNKNOWN = 0.4


def compute_bot_trust_weight(
    lesson: Any,
    querying_agent_type: str,
    trusted_bots: list[str],
) -> float:
    """計算 lesson 的 bot trust weight。

    參數：
      lesson: LessonRecord 或 dict（含 source、source_bot 欄位）
      querying_agent_type: 目前查詢的 agent type（如 "claude"）
      trusted_bots: 受信任的 bot 清單（config 中設定）

    優先順序：user_stated > same_bot > trusted_other_bot > unknown
    """
    if isinstance(lesson, dict):
        source = lesson.get("source", "")
        source_bot = lesson.get("source_bot")
    else:
        source = str(getattr(lesson, "source", "") or "")
        source_bot = getattr(lesson, "source_bot", None)

    # Normalize source (may be LessonSource enum or str)
    if hasattr(source, "value"):
        source = source.value

    # Tier 1: user_stated overrides all
    if source == "user-stated":
        return _WEIGHT_USER_STATED

    # Tier 2: same_bot
    if source_bot and source_bot == querying_agent_type:
        return _WEIGHT_SAME_BOT

    # Tier 3: trusted_other_bot
    if source_bot and source_bot in trusted_bots:
        return _WEIGHT_TRUSTED_OTHER

    # Tier 4: unknown
    return _WEIGHT_UNKNOWN
