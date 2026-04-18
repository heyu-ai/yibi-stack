"""Agents 資料模型：AgentsConfig、HandoverRecord、InsightRecord、SessionType。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SessionType(StrEnum):
    """交班 session 類型。對應 handover table 的 CHECK constraint。"""

    sdd = "sdd"
    debug = "debug"
    discussion = "discussion"
    admin = "admin"


class AgentsConfig(BaseModel):
    """~/.agents/config.json 本機設定。"""

    version: str = "1.0"
    device_id: str
    default_account: str | None = None
    default_agent: str = "claude"
    operator: str = "howie"
    skill_repo: str | None = None  # make install 時寫入；供跨機器 command 找到 uv 專案


class HandoverRecord(BaseModel):
    """Handover 單筆記錄。Layer 1 為核心語意，Layer 2 為環境復原資訊。"""

    # Layer 1: Universal
    id: str
    timestamp: str
    operator: str = "howie"
    session_type: SessionType
    topic: str
    conversation_summary: str
    completed: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    next_priorities: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    attempted_approaches: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Layer 2: Environment-specific
    device: str | None = None
    agent_type: str = "claude"
    subscription_account: str | None = None
    branch: str | None = None
    working_dir: str | None = None
    last_files: list[str] = Field(default_factory=list)
    test_status: str | None = None
    token_usage_estimate: str | None = None
    project: str | None = None


class InsightRecord(BaseModel):
    """Insight 單筆記錄（JSONL 內 schema）。"""

    id: str
    timestamp: str
    session_id: str
    project: str
    working_dir: str
    branch: str
    agent_type: str = "claude"
    account: str = "unknown"
    device: str | None = None
    insight_text: str
    session_reason: str = ""
