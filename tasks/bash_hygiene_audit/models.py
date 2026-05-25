"""bash-hygiene audit log 資料模型。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AliasChoices, BaseModel, Field


class Verdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ERROR = "error"


class AuditConfig(BaseModel):
    """User-level toggle config（~/.agents/bash-hygiene.json）。"""

    audit_enabled: bool = False


class AuditRecord(BaseModel):
    """JSONL audit log 單筆記錄。"""

    ts: str
    hook: str
    hook_version: str = "2"
    exit_code: int
    verdict: Verdict
    block_reason: str | None = None
    rule_id: str = ""
    cmd_snippet: str = Field(
        default="",
        validation_alias=AliasChoices("cmd_snippet", "command_preview"),
        description="Command preview; v1 key 'command_preview' accepted for back-compat",
    )
    command_hash: str = ""
    session_id: str | None = None
    duration_ms: int | None = None


class AuditStats(BaseModel):
    """多筆 AuditRecord 的聚合統計。"""

    total: int = 0
    allow_count: int = 0
    block_count: int = 0
    error_count: int = 0
    by_hook: dict[str, int] = Field(default_factory=dict)
    by_reason: dict[str, int] = Field(default_factory=dict)
    avg_duration_ms: float | None = None


class RepeatEvent(BaseModel):
    """同一 session 內同一 command_hash 被 block 多次的事件群組。"""

    session_id: str
    command_hash: str
    command_preview: str
    block_reason: str | None = None
    count: int
    first_ts: str
    last_ts: str
    estimated_wasted_ms: int
    estimated_wasted_tokens: int


class RepeatStats(BaseModel):
    """重複攔截統計：same-session same-hash block >= 2 次。"""

    total_blocks: int = 0
    repeated_blocks: int = 0
    repeat_rate: float = 0.0
    unique_repeat_events: int = 0
    total_wasted_ms: int = 0
    total_wasted_tokens: int = 0
    top_offenders: list[RepeatEvent] = Field(default_factory=list)
    by_reason: dict[str, int] = Field(default_factory=dict)
